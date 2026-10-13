"""Canonical external identities through the actual product compiler."""
import json
import os
import platform
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))


@pytest.fixture
def modules(tmp_path):
    env = dict(os.environ, XUPATH="", XU_CACHE=str(tmp_path / "cache"))
    for key in ("XUOS", "XUARCH", "XU_STDLIB_ROOT", "XU_HEAP_STATS"):
        env.pop(key, None)
    app = tmp_path / "app"
    app.mkdir()

    def provider(path="example.com/team/my-lib", version="1.2.3", value=42, name="provider"):
        root = tmp_path / name
        root.mkdir(exist_ok=True)
        (root / "xu.xun").write_text(f'module: "{path}"\nversion: !ver {version}\n')
        (root / "mod.xu").write_text(f'@"{path}"\npub fn answer() int {{ << {value} }}\n')
        return root

    def project(require, source=None):
        entries = "".join(f'  "{path}": {locator}\n' for path, locator in require)
        (app / "xu.xun").write_text("module: main\nversion: !ver 0.1.0\nrequire:\n" + entries)
        if source is None:
            path = require[0][0]
            source = f'@main\nlib #"{path}"\nfn main() int {{ println(lib.answer())\n << 0 }}\n'
        (app / "main.xu").write_text(source)
        return app

    def build(command="build"):
        args = [str(XU), command, str(app if command == "install" else app / "main.xu")]
        if command == "build":
            args += ["-o", str(app / "program")]
        return subprocess.run(args, cwd=app, env=env, text=True, capture_output=True, timeout=90)

    def run():
        return subprocess.check_output([str(app / "program")], text=True, timeout=10)

    return tmp_path, app, env, provider, project, build, run


def ok(result):
    assert result.returncode == 0, result.stdout + result.stderr


def rejected(result, message):
    assert result.returncode != 0, "invalid external module was accepted"
    assert message in result.stderr, result.stderr


def test_domain_dot_hyphen_and_module_root(modules):
    _, _, _, provider, project, build, run = modules
    root = provider()
    project([("example.com/team/my-lib", "file:" + str(root))])
    ok(build())
    assert run() == "42\n"


def test_domain_root_is_distinct_from_legacy_dotted_package(modules):
    _, app, _, provider, project, build, run = modules
    root = provider("example.com")
    local = app / "example/com"
    local.mkdir(parents=True)
    (local / "mod.xu").write_text("@example/com\npub fn answer() int { << 7 }\n")
    project([("example.com", "file:" + str(root))],
            '@main\nremote #"example.com"\nlocal #example/com\n'
            'fn main() int { println(remote.answer() + local.answer())\n << 0 }\n')
    ok(build())
    assert run() == "49\n"


def test_major_versions_and_internal_packages_coexist(modules):
    _, _, _, provider, project, build, run = modules
    old = provider("example.com/vec", value=10, name="old")
    new = provider("example.com/vec/v2", version="2.3.0", value=20, name="new")
    sub = new / "detail"
    sub.mkdir()
    (sub / "mod.xu").write_text('@"example.com/vec/v2/detail"\npub fn answer() int { << 3 }\n')
    project([("example.com/vec", "file:" + str(old)), ("example.com/vec/v2", "file:" + str(new))],
            '@main\nold #example.com/vec\n#"example.com/vec/v2" as newer\n'
            'detail # "example.com/vec/v2/detail"\n'
            'fn main() int { println(old.answer() + newer.answer() + detail.answer())\n << 0 }\n')
    ok(build())
    assert run() == "33\n"


@pytest.mark.parametrize("path", ["Example.com/lib", "example..com/lib", "-example.com/lib", "example.com/a//b",
                                 "example.com/../b", "example.com/a/", "example.com/CON.txt", "example.com/aux",
                                 "example.com/LPT9", "example.com/short~1", "example.com/a!b", "example.com/a\\b",
                                 "example.com/.cache", "example.com/a.", "example.com/a b", "example.com/é"])
def test_invalid_portable_external_path_rejected(modules, path):
    _, _, _, provider, project, build, _ = modules
    root = provider()
    project([(path, "file:" + str(root))])
    rejected(build(), "module path")


@pytest.mark.parametrize("path,version", [("example.com/lib/v1", "1.2.3"), ("example.com/lib/v01", "1.2.3"),
                                        ("example.com/lib/v2.1", "2.1.0"), ("example.com/lib/v2", "1.2.3"),
                                        ("example.com/lib", "2.1.0"), ("gopkg.in/lib", "1.2.3"),
                                        ("gopkg.in/lib.v2", "1.2.3")])
def test_major_path_must_match_module_version(modules, path, version):
    _, _, _, provider, project, build, _ = modules
    root = provider(path, version)
    project([(path, "file:" + str(root))])
    rejected(build(), "module")


def test_gopkg_major_suffix(modules):
    _, _, _, provider, project, build, run = modules
    root = provider("gopkg.in/lib.v2", "2.1.0")
    project([("gopkg.in/lib.v2", "file:" + str(root))])
    ok(build())
    assert run() == "42\n"


def test_manifest_identity_and_missing_manifest_rejected(modules):
    _, _, _, provider, project, build, _ = modules
    root = provider("example.com/wrong")
    project([("example.com/lib", "file:" + str(root))])
    rejected(build(), "does not match")
    (root / "xu.xun").unlink()
    rejected(build(), "requires xu.xun")


def test_ambiguous_provider_is_rejected(modules):
    _, _, _, provider, project, build, _ = modules
    root = provider("example.com/lib", name="outer")
    sub = root / "sub"
    sub.mkdir()
    (sub / "mod.xu").write_text('@"example.com/lib/sub"\npub fn answer() int { << 7 }\n')
    other = provider("example.com/lib/sub", name="inner")
    project([("example.com/lib", "file:" + str(root)), ("example.com/lib/sub", "file:" + str(other))],
            '@main\nlib #"example.com/lib/sub"\nfn main() int { println(lib.answer())\n << 0 }\n')
    rejected(build(), "ambiguous")


def test_only_actual_provider_is_selected(modules):
    _, _, _, provider, project, build, run = modules
    root = provider("example.com/lib", name="outer")
    sub = root / "sub"
    sub.mkdir()
    (sub / "mod.xu").write_text('@"example.com/lib/sub"\npub fn answer() int { << 7 }\n')
    other = provider("example.com/lib/sub", name="inner")
    (other / "mod.xu").unlink()
    project([("example.com/lib", "file:" + str(root)), ("example.com/lib/sub", "file:" + str(other))],
            '@main\nlib #"example.com/lib/sub"\nfn main() int { println(lib.answer())\n << 0 }\n')
    ok(build())
    assert run() == "7\n"


def test_duplicate_alias_rejected(modules):
    _, _, _, provider, project, build, _ = modules
    a = provider("example.com/a", name="a")
    b = provider("example.com/b", name="b")
    project([("example.com/a", "file:" + str(a)), ("example.com/b", "file:" + str(b))],
            '@main\nlib #"example.com/a"\nlib #"example.com/b"\nfn main() {}\n')
    rejected(build(), "duplicate import alias")


def test_external_types_methods_and_generic_calls(modules):
    _, _, _, provider, project, build, run = modules
    root = provider("example.com/my-lib")
    (root / "mod.xu").write_text('''@"example.com/my-lib"
pub struct Item { pub value int }
pub fn (v Item) read() int { << v.value }
pub fn identity#T(v T) T { << v }
''')
    project([("example.com/my-lib", "file:" + str(root))],
            '@main\nlib #"example.com/my-lib"\nfn main() int { v := lib.Item{value: 42}\n'
            'println(lib.identity(v.read()))\n << 0 }\n')
    ok(build())
    assert run() == "42\n"


def test_real_git_cache_vendor_case_escape_and_tamper(modules):
    _, app, _, provider, project, build, run = modules
    path = "example.com/team/My-Lib"
    root = provider(path)
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=Module test", "-c", "user.email=module@example.invalid", "commit", "-qm", "initial")
    revision = git("rev-parse", "HEAD")
    project([(path, "git:" + str(root) + "@" + revision)])
    ok(build())
    assert run() == "42\n"
    before = (app / "xu.lock").read_text()
    assert before.splitlines()[1].split()[0] == path
    ok(build("install"))
    vendor = app / "vendor/example.com/team/!my-!lib"
    assert (vendor / "xu.xun").is_file()
    # Once vendored the unavailable original checkout is irrelevant.
    root.rename(root.with_name("offline"))
    ok(build())
    assert run() == "42\n"
    lock = (app / "xu.lock").read_bytes()
    (vendor / "mod.xu").write_text((vendor / "mod.xu").read_text().replace("42", "99"))
    rejected(build(), "checksum")
    assert (app / "xu.lock").read_bytes() == lock


def test_dotted_declaration_is_rejected_with_migration_message(modules):
    _, app, _, _, project, build, _ = modules
    project([], "@old.package\nfn main() {}\n")
    rejected(build(), "dot module separators are removed")


def test_canonical_native_metadata_and_default_symbol(modules):
    if platform.system() not in {"Darwin", "Linux"}:
        pytest.skip("native link execution needs the platform C toolchain")
    _, _, _, provider, project, build, run = modules
    path = "example.com/native-lib"
    root = provider(path)
    (root / "mod.xu").write_text(f'@"{path}"\n')
    label = "_xu_path." + path.encode().hex() + "_answer"
    asm_label = label
    source = root / "native.c"
    source.write_text(f'long answer(void) __asm__("{asm_label}");\nlong answer(void) {{ return 42; }}\n')
    manifest = root / "native.json"
    manifest.write_text(json.dumps({"module": path, "abi": "xu-c-1", "exports": [{"name": "answer", "ret": "int"}]}))
    target = ("macos" if platform.system() == "Darwin" else "linux") + ("-arm64" if platform.machine() in {"arm64", "aarch64"} else "-x64")
    artifact = root / "native.a"
    result = subprocess.run(["python3", str(ROOT / "scripts/xunative.py"), "compile", "--manifest", str(manifest),
                             "--target", target, "-o", str(artifact), str(source)], text=True, capture_output=True, timeout=60)
    ok(result)
    (root / "xu.xun").write_text(f'module: "{path}"\nversion: !ver 1.2.3\nnative:\n  "{path}": file:./native.a\n')
    project([(path, "file:" + str(root))])
    ok(build())
    assert run() == "42\n"
