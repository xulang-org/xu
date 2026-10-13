"""Canonical root-module packages load only imported, authenticated native bytes."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))
MODULE = "github.com/xulang-org/packages"

@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = dict(os.environ, XUPATH="", XU_CACHE=str(tmp_path / "cache"))
    for key in ("XUOS", "XUARCH", "XU_HEAP_STATS"):
        env.pop(key, None)
    def publish(locator):
        (repo / "xu.xun").write_text(f'module: "{MODULE}"\nversion: !ver 0.1.0\nnative:\n  boundary_native: file:{locator}\n')
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "--", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Root test", "-c", "user.email=root@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"], check=True)
        revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        return "git:" + str(repo) + "@" + revision
    def app(path, locator):
        work = tmp_path / "app"
        work.mkdir()
        (work / "xu.xun").write_text(f'module: app\nversion: !ver 0.1.0\nrequire:\n  "{MODULE}": {locator}\n')
        (work / "main.xu").write_text(f'@main\nlib #"{MODULE}/{path}"\nfn main() int {{ println(lib.answer())\n << 0 }}\n')
        return work
    def command(work, action="build", flags=()):
        args = [str(XU), action, str(work), *flags]
        if action == "build":
            args += ["-o", str(work / "program")]
        return subprocess.run(args, cwd=work, env=env, capture_output=True, text=True, timeout=90)
    return repo, tmp_path, publish, app, command

def ok(result):
    assert result.returncode == 0, result.stdout + result.stderr

def make_native(repo):
    source = repo / "native.c"
    source.write_text('long keep(void) __asm__("_xu_boundary_native_keep");\nlong keep(void) { return 42; }\n')
    metadata = repo / "native.json"
    metadata.write_text(json.dumps({"module": "boundary_native", "abi": "xu-c-1", "exports": [{"name": "keep", "ret": "int"}]}))
    target = ("macos" if platform.system() == "Darwin" else "linux") + ("-arm64" if platform.machine() in {"arm64", "aarch64"} else "-x64")
    artifact = repo / "native.a"
    ok(subprocess.run(["python3", str(ROOT / "scripts/xunative.py"), "compile", "--manifest", str(metadata), "--target", target, "-o", str(artifact), str(source)], capture_output=True, text=True, timeout=60))
    return artifact

def test_unused_native_resource_is_not_loaded_for_a_pure_package(repository):
    repo, _, publish, app, command = repository
    package = repo / "mysql"
    package.mkdir()
    (package / "mod.xu").write_text(f'@"{MODULE}/mysql"\npub fn answer() int {{ << 42 }}\n')
    work = app("mysql", publish("/unavailable/native.a"))
    ok(command(work))
    assert subprocess.check_output([str(work / "program")], text=True) == "42\n"

@pytest.mark.parametrize("escape", [False, True])
def test_native_resource_in_root_module_stays_bound_to_its_source(repository, escape):
    repo, tmp, publish, app, command = repository
    artifact = make_native(repo)
    package = repo / "sqlite"
    package.mkdir()
    (package / "mod.xu").write_text(f'@"{MODULE}/sqlite"\n#boundary_native\npub fn answer() int {{ << boundary_native.keep() }}\n')
    work = app("sqlite", publish(str(artifact) if escape else "./native.a"))
    result = command(work)
    if escape:
        assert result.returncode != 0
        assert "native file is outside authenticated" in result.stderr
        assert not (work / "program").exists()
        return
    ok(result)
    assert subprocess.check_output([str(work / "program")], text=True) == "42\n"
    ok(command(work, "install"))
    lock = (work / "xu.lock").read_bytes()
    shutil.rmtree(repo)
    shutil.rmtree(tmp / "cache")
    ok(command(work, flags=("--frozen",)))
    assert subprocess.check_output([str(work / "program")], text=True) == "42\n"
    assert (work / "xu.lock").read_bytes() == lock


def test_application_import_cannot_activate_an_unrelated_package_native_root(repository):
    repo, _, publish, app, command = repository
    package = repo / "mysql"
    package.mkdir()
    (package / "mod.xu").write_text(f'@"{MODULE}/mysql"\npub fn answer() int {{ << 42 }}\n')
    work = app("mysql", publish("/unavailable/native.a"))
    source = work / "main.xu"
    source.write_text(source.read_text().replace('fn main()', '#boundary_native\nfn main()'))
    result = command(work)
    assert result.returncode != 0
    assert 'boundary_native' in result.stderr
    assert 'native file is outside' not in result.stderr
    assert 'cannot read native' not in result.stderr
