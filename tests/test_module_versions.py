"""Exercise release checks against real Git trees, including nested modules."""

import subprocess
import shutil
from pathlib import Path

import pytest

from scripts import module_versions as versions

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.name", "Version test")
    git(tmp_path, "config", "user.email", "version@example.invalid")
    for name in ("src/cmd/demo", "src/cmd/demo/child", "packages/unchanged"):
        write(tmp_path, f"{name}/xu.xun", f"module: demo\nversion: !ver 0.2.9\nxu: !ver 0.1.0\n")
        write(tmp_path, f"{name}/main.xu", "old source\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial modules")
    return tmp_path


@pytest.mark.parametrize("change", ["source", "delete", "add", "dependency", "doc"])
def test_changes_require_bump_and_preserve_language_version(repo, change):
    module = repo / "src/cmd/demo"
    if change == "source":
        write(repo, "src/cmd/demo/main.xu", "changed source\n")
    elif change == "delete":
        (module / "main.xu").unlink()
    elif change == "add":
        write(repo, "src/cmd/demo/new.xu", "new source\n")
    elif change == "doc":
        write(repo, "src/cmd/demo/README.md", "changed documentation\n")
    else:
        with (module / "xu.xun").open("a") as stream:
            stream.write("require:\n  pkg: !ver 1.0.0\n")
    errors = versions.process(repo, "HEAD")
    assert len(errors) == 1 and "did not increase" in errors[0]
    assert versions.process(repo, "HEAD", bump=True) == []
    text = (module / "xu.xun").read_text()
    assert "version: !ver 0.2.10\n" in text
    assert "xu: !ver 0.1.0\n" in text
    assert versions.process(repo, "HEAD") == []
    versions.process(repo, "HEAD", bump=True)
    assert (module / "xu.xun").read_text() == text


def test_nested_module_owns_its_changes(repo):
    write(repo, "src/cmd/demo/child/main.xu", "changed\n")
    assert versions.process(repo, "HEAD", bump=True) == []
    assert "0.2.10" in (repo / "src/cmd/demo/child/xu.xun").read_text()
    assert "0.2.9" in (repo / "src/cmd/demo/xu.xun").read_text()
    assert "0.2.9" in (repo / "packages/unchanged/xu.xun").read_text()


def test_new_and_legacy_modules_initialize_without_false_release(repo):
    write(repo, "packages/new/xu.xun", "module: new\n")
    write(repo, "packages/new/main.xu", "new source\n")
    write(repo, "packages/unchanged/xu.xun", "module: demo\nxu: !ver 0.1.0\n")
    git(repo, "add", "packages/unchanged/xu.xun")
    git(repo, "commit", "-m", "legacy manifest")
    assert versions.process(repo, "HEAD", bump=True) == []
    assert "version: !ver 0.1.0" in (repo / "packages/new/xu.xun").read_text()
    assert "version: !ver 0.1.0" in (repo / "packages/unchanged/xu.xun").read_text()
    assert versions.process(repo, "HEAD") == []
    write(repo, "packages/unchanged/main.xu", "changed\n")
    assert versions.process(repo, "HEAD", bump=True) == []
    assert "version: !ver 0.1.1" in (repo / "packages/unchanged/xu.xun").read_text()


def test_check_uses_requested_base_for_committed_changes(repo):
    write(repo, "src/cmd/demo/main.xu", "changed\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "forgot version")
    assert versions.process(repo, "HEAD") == []
    assert "did not increase" in versions.process(repo, "HEAD~1")[0]


def test_regression_blocks_all_writes(repo):
    write(repo, "src/cmd/demo/xu.xun", "module: demo\nversion: 0.1.0\n")
    write(repo, "packages/unchanged/main.xu", "changed\n")
    original = (repo / "packages/unchanged/xu.xun").read_text()
    assert "regressed" in versions.process(repo, "HEAD", bump=True)[0]
    assert (repo / "packages/unchanged/xu.xun").read_text() == original


def test_snapshots_and_fixtures_are_excluded(repo):
    for folder in ("dist/staging", "docs/audit/snapshot", "tests/fixtures/bad"):
        write(repo, f"{folder}/xu.xun", "deliberately invalid\n")
    assert versions.process(repo, "HEAD") == []


@pytest.mark.parametrize("value", ["1.2", "01.2.3", "1.2.x", "1.2.3.4", "v1.2.3"])
def test_invalid_versions_are_rejected(value):
    with pytest.raises(ValueError):
        versions.read_version(f"version: {value}\n")


def prepare_release(repo):
    write(repo, "VERSION", "0.3.0\n")
    write(repo, "src/cmd/compile/driver_entry.xu", 'println("Xu Compiler Toolchain v0.3.0 (self-hosted)")\n')
    write(repo, "src/cmd/desktop/pack_macos.xu", '<key>CFBundleShortVersionString</key> <string>0.3.0</string>\n')


def test_release_aligns_all_modules_and_is_idempotent(repo):
    prepare_release(repo)
    write(repo, "packages/new/xu.xun", "module: new\nversion: !ver 0.1.0\nrequire:\n  dep: !ver 0.2.0\n")
    write(repo, "tests/fixtures/invalid/xu.xun", "invalid fixture\n")
    write(repo, "dist/staging/xu.xun", "historical snapshot\n")
    assert versions.release(repo, check=True)
    assert versions.release(repo) == []
    assert versions.release(repo, check=True) == []
    for name in ("src/cmd/demo", "src/cmd/demo/child", "packages/unchanged", "packages/new"):
        text = (repo / name / "xu.xun").read_text()
        expected = "0.1.0" if name == "packages/new" else "0.2.9"
        assert f"version: !ver {expected}\n" in text
        assert "xu: !ver 0.3.0\n" in text
    assert "dep: !ver 0.2.0" in (repo / "packages/new/xu.xun").read_text()
    path = repo / "packages/new/xu.xun"
    before = path.stat().st_mtime_ns
    assert versions.release(repo) == []
    assert path.stat().st_mtime_ns == before
    assert (repo / "tests/fixtures/invalid/xu.xun").read_text() == "invalid fixture\n"
    assert (repo / "dist/staging/xu.xun").read_text() == "historical snapshot\n"


@pytest.mark.parametrize("kind,expected", [("patch", "0.3.1"), ("minor", "0.4.0"), ("major", "1.0.0")])
def test_release_bump_updates_product_sources_and_all_manifests(repo, kind, expected):
    prepare_release(repo)
    assert versions.release(repo, kind, allow_stable=kind == "major") == []
    assert (repo / "VERSION").read_text().strip() == expected
    assert expected in (repo / "src/cmd/compile/driver_entry.xu").read_text()
    assert expected in (repo / "src/cmd/desktop/pack_macos.xu").read_text()
    assert versions.release(repo, check=True) == []
    assert "version: !ver 0.2.9" in (repo / "src/cmd/demo/xu.xun").read_text()


def test_compiler_version_follows_product_instead_of_independent_bump(repo):
    prepare_release(repo)
    compiler = repo / "src/cmd/compile/xu.xun"
    write(repo, str(compiler.relative_to(repo)), "module: xu\nversion: !ver 1.0.0\nxu: !ver 0.3.0\n")
    assert any("compiler version:" in error for error in versions.release(repo, check=True))
    assert versions.release(repo) == []
    assert versions.read_version(compiler.read_text()) == (0, 3, 0)
    assert versions.release(repo, "patch") == []
    assert versions.read_version(compiler.read_text()) == (0, 3, 1)
    assert versions.read_xu_version(compiler.read_text()) == (0, 3, 1)
    assert versions.release(repo, check=True) == []
    compiler.write_text(compiler.read_text().replace("version: !ver 0.3.1", "version: !ver 0.4.0"))
    assert any("compiler version:" in error for error in versions.process(repo, "HEAD", bump=True))


def test_stable_release_requires_explicit_decision_and_changes_nothing(repo):
    prepare_release(repo)
    paths = [p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
    before = {p: p.read_bytes() for p in paths}
    errors = versions.release(repo, "major")
    assert len(errors) == 1 and "explicit stable release decision" in errors[0]
    assert {p: p.read_bytes() for p in paths} == before


@pytest.mark.parametrize("allow", [False, True])
def test_stable_release_cli_opt_in(repo, allow):
    prepare_release(repo)
    script = repo / "scripts/module_versions.py"
    script.parent.mkdir()
    shutil.copy2(ROOT / "scripts/module_versions.py", script)
    args = ["python3", str(script), "--release-bump", "major"]
    if allow:
        args.append("--allow-stable")
    result = subprocess.run(args, cwd=repo, capture_output=True, text=True)
    assert (result.returncode == 0) == allow, result.stdout + result.stderr
    assert (repo / "VERSION").read_text().strip() == ("1.0.0" if allow else "0.3.0")


def test_xu_sync_does_not_bump_module_versions_even_if_module_version_is_higher(repo):
    prepare_release(repo)
    write(repo, "packages/unchanged/xu.xun", "module: pkg\nversion: !ver 4.5.6\nxu: !ver 0.1.0\n")
    assert versions.release(repo) == []
    text = (repo / "packages/unchanged/xu.xun").read_text()
    assert "version: !ver 4.5.6" in text
    assert "xu: !ver 0.3.0" in text
    assert versions.process(repo, "HEAD") == []
    assert versions.process(repo, "HEAD", bump=True) == []
    assert (repo / "src/cmd/demo/xu.xun").read_text().startswith("module: demo\nversion: !ver 0.2.9\n")


@pytest.mark.parametrize("bad", ["xu: nope", "xu: 0.9.0"])
def test_release_errors_do_not_partially_update_version_or_sources(repo, bad):
    prepare_release(repo)
    write(repo, "packages/bad/xu.xun", f"module: bad\nversion: !ver 0.1.0\n{bad}\n")
    tracked = [repo / name for name in ("VERSION", "src/cmd/compile/driver_entry.xu", "src/cmd/desktop/pack_macos.xu", "src/cmd/demo/xu.xun")]
    before = [p.read_bytes() for p in tracked]
    assert versions.release(repo, "patch")
    assert [p.read_bytes() for p in tracked] == before


def prepare_make(repo):
    prepare_release(repo)
    shutil.copy2(ROOT / "Makefile", repo / "Makefile")
    (repo / "scripts").mkdir(exist_ok=True)
    for name in ("module_versions.py", "bump_version.sh", "check_release_identity.py", "check_module_paths.py", "companion_repos.py", "xu_host_seed.sh"):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    for name in ("compile", "doctor", "desktop", "fmt", "map", "doc"):
        write(repo, f"src/cmd/{name}/xu.xun", f"module: cmd/{name}\nversion: !ver 0.2.9\nxu: !ver 0.1.0\n")
    write(repo, "fake_build.py", '''import subprocess,sys
from pathlib import Path
subprocess.run([sys.executable,"scripts/module_versions.py","--check-release"],check=True)
version=Path("VERSION").read_text().strip()
out=Path(sys.argv[1]);out.parent.mkdir(exist_ok=True)
out.write_text("#!/bin/sh\\necho 'Xu v"+version+"'\\n");out.chmod(0o755)
''')
    write(repo, "TestBuild.mk", '$(XU) $(XU_DOCTOR) $(XU_DESKTOP) $(XU_FMT) $(XU_MAP) $(XU_DOC):\n\t$(PYTHON) fake_build.py "$@"\n')


def make(repo, *args):
    return subprocess.run(["make", "-f", "Makefile", "-f", "TestBuild.mk", "SELFHOST_POLICY=", *args], cwd=repo, capture_output=True, text=True)


def test_make_publish_prepares_once_before_parallel_builds(repo):
    prepare_make(repo)
    result = make(repo, "-j4", "xu", "BUMP=patch")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / "VERSION").read_text() == "0.3.1\n"
    assert versions.release(repo, check=True) == []
    assert "release identity: PASS" in result.stdout


def test_make_dry_run_help_and_invalid_bump_do_not_modify_versions(repo):
    prepare_make(repo)
    paths = [p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
    before = {p: p.read_bytes() for p in paths}
    for args in (("-n", "xu", "BUMP=patch"), ("help", "BUMP=patch")):
        result = make(repo, *args)
        assert result.returncode == 0, result.stdout + result.stderr
        assert {p: p.read_bytes() for p in paths} == before
    result = make(repo, "xu", "BUMP=invalid")
    assert result.returncode != 0
    assert {p: p.read_bytes() for p in paths} == before


def test_unborn_repository_initializes_only_missing_versions(tmp_path):
    git(tmp_path, "init")
    write(tmp_path, "src/cmd/demo/xu.xun", "module: demo\nversion: !ver 0.2.9\n")
    write(tmp_path, "packages/new/xu.xun", "module: new\n")
    assert versions.process(tmp_path, "HEAD", bump=True) == []
    assert "version: !ver 0.2.9" in (tmp_path / "src/cmd/demo/xu.xun").read_text()
    assert "version: !ver 0.1.0" in (tmp_path / "packages/new/xu.xun").read_text()
    before = {p: p.read_bytes() for p in tmp_path.rglob("xu.xun")}
    assert versions.process(tmp_path, "HEAD", bump=True) == []
    assert versions.process(tmp_path, "HEAD") == []
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("xu.xun")}
    with pytest.raises(subprocess.CalledProcessError):
        versions.process(tmp_path, "missing-user-base")
