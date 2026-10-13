"""Product dependency boundaries; deterministic tools never access the network."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))
SOURCE = "@rempkg\npub fn answer() int { << 42 }\n"

@pytest.fixture
def dep(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    stub = '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
a=sys.argv[1:]
with open(os.environ['XU_DEP_LOG'],'a') as f: f.write(json.dumps([Path(sys.argv[0]).name,a])+'\\n')
if Path(sys.argv[0]).name=='curl':
 p=Path(a[a.index('-o')+1]); p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text('@rempkg\\npub fn answer() int { << 42 }\\n')
elif 'clone' in a:
 url=a[-2]; p=Path(a[-1]); (p/'rempkg').mkdir(parents=True,exist_ok=True)
 n=99 if 'origin-b' in url else 42
 (p/'rempkg/mod.xu').write_text('@rempkg\\npub fn answer() int { << '+str(n)+' }\\n')
 (p/'rempkg/xu.xun').write_text('module: rempkg\\nversion: !ver 1.0.0\\n')
elif 'checkout' not in a: sys.exit(2)
'''
    for tool in ("curl", "git"):
        p = tools / tool
        p.write_text(stub)
        p.chmod(0o755)
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
               XUPATH="", XU_CACHE=str(tmp_path / "cache"), XU_DEP_LOG=str(tmp_path / "calls"))
    for k in ("XUOS", "XUARCH", "XU_HEAP_STATS", "XU_STDLIB_ROOT"):
        env.pop(k, None)
    def project(name="app", locator="http://audit.invalid/rempkg.xu"):
        p = tmp_path / name
        p.mkdir(exist_ok=True)
        (p / "main.xu").write_text("@main\n#rempkg\nfn main() int { println(rempkg.answer())\n << 0 }\n")
        (p / "xu.xun").write_text("module: example/audit\nversion: !ver 0.1.0\nrequire:\n  rempkg: " + locator + "\n")
        return p
    def build(p, command="build"):
        argv = [str(XU), command]
        argv += [str(p)] if command == "install" else [str(p / "main.xu"), "-o", str(p / "program")]
        return subprocess.run(argv, cwd=p, env=env, capture_output=True, text=True, timeout=60)
    def run(p):
        return subprocess.check_output([str(p / "program")], text=True, timeout=10)
    return tmp_path, project, build, run, env

def ok(result):
    assert result.returncode == 0, result.stdout + result.stderr

def rejected(result, message):
    assert result.returncode != 0, "insecure dependency accepted"
    assert message in result.stderr, result.stderr

@pytest.mark.parametrize("command", ["build", "install"])
@pytest.mark.parametrize("locator", [
    "http://audit.invalid/$(printf checked > audit_marker)/rempkg.xu",
    "http://audit.invalid/`printf checked > audit_marker`/rempkg.xu",
    'http://audit.invalid/";printf checked > audit_marker;"/rempkg.xu',
    "git:https://audit.invalid/pkg@$(printf checked > audit_marker)",
])
def test_locator_is_literal(dep, command, locator):
    _, project, build, _, _ = dep
    p = project(locator=locator)
    build(p, command)
    assert not (p / "audit_marker").exists()

def test_existing_legacy_lock_is_not_silently_trusted(dep):
    _, project, build, _, _ = dep
    p = project()
    (p / "xu.lock").write_text("# legacy FNV\nrempkg 0000000000000000\n")
    rejected(build(p), "xu.lock")

def test_first_download_lock_and_cache_tamper(dep):
    root, project, build, run, _ = dep
    p = project()
    ok(build(p)); assert run(p) == "42\n"
    lock = p / "xu.lock"
    assert lock.is_file()
    before = lock.read_bytes()
    ok(build(p)); assert lock.read_bytes() == before
    files = list((root / "cache").rglob("rempkg.xu"))
    assert len(files) == 1
    files[0].write_text(SOURCE.replace("42", "99"))
    rejected(build(p), "checksum")
    assert lock.read_bytes() == before

def test_source_binding_and_cross_project_cache(dep):
    _, project, build, run, _ = dep
    p = project("a", "git:https://origin-a.invalid/pkg@v1.0.0")
    ok(build(p)); assert run(p) == "42\n"
    q = project("b", "git:https://origin-b.invalid/pkg@v1.0.0")
    ok(build(q)); assert run(q) == "99\n"
    project("a", "git:https://origin-b.invalid/pkg@v1.0.0")
    rejected(build(p), "source")

@pytest.mark.parametrize("pin", ["1..2", "1.2", "01.2.3", "1.02.3", "v", "1.2.3.4"])
def test_bad_version_rejected_even_with_legacy_cache(dep, pin):
    root, project, build, _, _ = dep
    p = project(locator=pin)
    cache = root / "cache/rempkg" / pin
    cache.mkdir(parents=True)
    (cache / ".ok").write_text("1")
    (cache / "rempkg.xu").write_text(SOURCE)
    rejected(build(p), "locator")

def test_external_src_sibling_is_not_standard_library(dep):
    root, project, build, _, _ = dep
    provider = root / "provider/src"
    for name in ("rempkg", "hidden"):
        d = provider / name; d.mkdir(parents=True)
        (d / "xu.xun").write_text("module: " + name + "\n")
        (d / "mod.xu").write_text("@" + name + "\npub fn answer() int { << 42 }\n")
    p = project(locator="file:" + str(provider))
    ok(build(p))
    (p / "main.xu").write_text("@main\n#hidden\nfn main() int { println(hidden.answer())\n << 0 }\n")
    rejected(build(p), "require")

def test_install_vendor_is_verified_without_network(dep):
    root, project, build, run, env = dep
    p = project()
    ok(build(p, "install"))
    vendor = p / "vendor/rempkg.xu"
    assert vendor.read_text() == SOURCE
    env["PATH"] = os.environ["PATH"]
    ok(build(p)); assert run(p) == "42\n"
    vendor.write_text(SOURCE.replace("42", "99"))
    rejected(build(p), "checksum")

def test_paths_with_spaces_and_apostrophes(dep):
    root, project, build, run, env = dep
    env["XU_CACHE"] = str(root / "cache 'quoted' $(printf checked > audit_marker)")
    p = project("app 'quote' space")
    ok(build(p)); assert run(p) == "42\n"
    assert not (p / "audit_marker").exists()

def tree_hash(p, rel=""):
    if p.is_dir():
        record = "D" + str(len(rel)) + ":" + rel + "\n"
        for child in sorted(p.iterdir()):
            if not rel and child.name in {".git", ".ok", "pkg.tgz"}:
                continue
            child_rel = rel + "/" + child.name if rel else child.name
            record += tree_hash(child, child_rel)
    else:
        record = "F" + str(len(rel)) + ":" + rel + ":" + hashlib.sha256(p.read_bytes()).hexdigest() + "\n"
    return record

def test_sha256_lock_matches_independent_reference_and_marker_cannot_override_it(dep):
    root, project, build, _, _ = dep
    p = project()
    ok(build(p))
    entry = (p / "xu.lock").read_text().splitlines()[1].split()
    cache = root / "cache" / entry[1]
    digest = hashlib.sha256(("xu-tree-v1\n" + tree_hash(cache)).encode()).hexdigest()
    assert digest == entry[2] == (cache / ".ok").read_text()
    locator = "http://audit.invalid/rempkg.xu"
    source = "xu-source-v2\n6:rempkg" + str(len(locator)) + ":" + locator
    assert hashlib.sha256(source.encode()).hexdigest() == entry[1]
    (cache / "rempkg.xu").write_text(SOURCE.replace("42", "99"))
    (cache / ".ok").write_text(hashlib.sha256(("xu-tree-v1\n" + tree_hash(cache)).encode()).hexdigest())
    rejected(build(p), "checksum")

def test_import_cannot_be_served_from_another_require_root(dep):
    root, project, build, _, _ = dep
    p = project()
    ok(build(p))
    provider = root / "other"
    provider.mkdir()
    (provider / "rempkg.xu").write_text(SOURCE.replace("42", "99"))
    manifest = p / "xu.xun"
    manifest.write_text(manifest.read_text().replace("require:\n", "require:\n  other: file:" + str(provider) + "\n"))
    rejected(build(p), "require")

def test_standard_library_child_symlink_cannot_grant_exemption(dep):
    root, project, build, _, env = dep
    p = project()
    trusted = root / "trusted/src"
    trusted.mkdir(parents=True)
    outside = root / "outside"
    outside.mkdir()
    (outside / "hidden.xu").write_text("@hidden\npub fn answer() int { << 99 }\n")
    (trusted / "hidden.xu").symlink_to(outside / "hidden.xu")
    env["XU_STDLIB_ROOT"] = str(trusted)
    (p / "main.xu").write_text("@main\n#hidden\nfn main() int { println(hidden.answer())\n << 0 }\n")
    rejected(build(p), "require")

def test_standard_library_directory_child_symlink_cannot_grant_exemption(dep):
    root, project, build, _, env = dep
    p = project()
    trusted = root / "trusted/src/hidden"
    trusted.mkdir(parents=True)
    outside = root / "outside.xu"
    outside.write_text("@hidden\npub fn answer() int { << 99 }\n")
    (trusted / "mod.xu").symlink_to(outside)
    env["XU_STDLIB_ROOT"] = str(trusted.parent)
    (p / "main.xu").write_text("@main\n#hidden\nfn main() int { println(hidden.answer())\n << 0 }\n")
    rejected(build(p), "require")

def test_install_does_not_follow_vendor_symlink(dep):
    root, project, build, _, _ = dep
    p = project()
    ok(build(p))
    outside = root / "outside"
    outside.mkdir()
    victim = outside / "rempkg.xu"
    victim.write_text("preserve this file")
    (p / "vendor").symlink_to(outside, target_is_directory=True)
    rejected(build(p, "install"), "symlink")
    assert victim.read_text() == "preserve this file"

def test_single_file_vendor_parent_manifest_is_not_authenticated(dep):
    _, project, build, _, _ = dep
    p = project()
    ok(build(p, "install"))
    (p / "vendor/xu.xun").write_text("module: rempkg\nnative:\n  evil: file:/outside/evil.a\n")
    rejected(build(p), "authenticated")

def test_more_specific_local_require_can_override_a_remote_parent(dep):
    root, project, build, run, _ = dep
    provider = root / "provider/rempkg/child"
    provider.mkdir(parents=True)
    (provider / "mod.xu").write_text("@rempkg/child\npub fn answer() int { << 73 }\n")
    (provider / "xu.xun").write_text("module: rempkg/child\n")
    p = project()
    manifest = p / "xu.xun"
    manifest.write_text(manifest.read_text() + "  rempkg/child: file:" + str(root / "provider") + "\n")
    (p / "main.xu").write_text("@main\n#rempkg/child\nfn main() int { println(child.answer())\n << 0 }\n")
    ok(build(p)); assert run(p) == "73\n"

def test_invalid_version_is_rejected_in_vendor_mode_too(dep):
    _, project, build, _, _ = dep
    p = project()
    ok(build(p, "install"))
    project(locator="1..2")
    lock = p / "xu.lock"
    entry = lock.read_text().splitlines()[1].split()
    entry[1] = hashlib.sha256(b"xu-source-v2\n6:rempkg4:1..2").hexdigest()
    lock.write_text("xu-lock-v2 sha256-tree-v1\n" + " ".join(entry) + "\n")
    rejected(build(p), "locator")

@pytest.mark.parametrize("escape", [False, True])
def test_remote_native_bytes_must_be_in_the_authenticated_tree(dep, escape):
    import shutil
    root, project, build, run, env = dep
    env["PATH"] = os.environ["PATH"]
    repo = root / "repo"
    package = repo / "rempkg"
    package.mkdir(parents=True)
    (package / "mod.xu").write_text(SOURCE)
    import platform
    artifact = package / "boundary.a"
    source = package / "native.c"
    source.write_text('long keep(void) __asm__("_xu_boundary_native_keep");\nlong keep(void) { return 1; }\n')
    metadata = package / "native.json"
    metadata.write_text(json.dumps({"module": "boundary_native", "abi": "xu-c-1",
                                   "exports": [{"name": "keep", "ret": "int"}]}))
    target = ("macos" if platform.system() == "Darwin" else "linux") + ("-arm64" if platform.machine() in {"arm64", "aarch64"} else "-x64")
    compiled = subprocess.run(["python3", str(ROOT / "scripts/xunative.py"), "compile", "--manifest", str(metadata),
                               "--target", target, "-o", str(artifact), str(source)], capture_output=True, text=True, timeout=60)
    ok(compiled)
    locator = str(artifact) if escape else "./boundary.a"
    (package / "xu.xun").write_text("module: rempkg\nnative:\n  boundary_native: file:" + locator + "\n")
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    git("init"); git("add", ".")
    git("-c", "user.name=Dependency test", "-c", "user.email=dependency@example.invalid", "commit", "-m", "dependency")
    p = project(locator="git:file://" + str(repo))
    if escape:
        rejected(build(p), "native file is outside authenticated")
    else:
        ok(build(p)); assert run(p) == "42\n"

def test_real_git_older_tag_and_offline_cache(dep):
    root, project, build, run, env = dep
    env["PATH"] = os.environ["PATH"]
    repo = root / "git source 'quoted'"
    repo.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    git("init")
    (repo / "rempkg.xu").write_text(SOURCE)
    git("add", ".")
    git("-c", "user.name=Dependency test", "-c", "user.email=dependency@example.invalid", "commit", "-m", "v1")
    git("tag", "v1.0.0")
    (repo / "rempkg.xu").write_text(SOURCE.replace("42", "99"))
    git("add", ".")
    git("-c", "user.name=Dependency test", "-c", "user.email=dependency@example.invalid", "commit", "-m", "v2")
    # Use a literal filesystem URL, including spaces/apostrophes.
    p = project(locator="git:file://" + str(repo) + "@v1.0.0")
    ok(build(p)); assert run(p) == "42\n"
    import shutil
    shutil.rmtree(repo)
    ok(build(p)); assert run(p) == "42\n"

@pytest.mark.parametrize("archive", [False, True])
def test_real_http_download_install_and_offline_vendor(dep, archive):
    import functools
    import http.server
    import io
    import tarfile
    import threading
    root, project, build, run, env = dep
    env["PATH"] = os.environ["PATH"]
    www = root / "www"
    www.mkdir()
    name = "rempkg.tgz" if archive else "rempkg.xu"
    if archive:
        with tarfile.open(www / name, "w:gz") as tar:
            entry = tarfile.TarInfo("rempkg.xu")
            entry.size = len(SOURCE.encode())
            tar.addfile(entry, io.BytesIO(SOURCE.encode()))
    else:
        (www / name).write_text(SOURCE)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(www))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    p = project(locator="http://127.0.0.1:" + str(server.server_port) + "/" + name)
    try:
        ok(build(p)); assert run(p) == "42\n"
        ok(build(p, "install"))
    finally:
        server.shutdown(); server.server_close(); thread.join()
    ok(build(p)); assert run(p) == "42\n"

@pytest.mark.parametrize("name", ["../escape", "a..b", "a//b", "a/b/", "CON"])
def test_unsafe_module_path_is_rejected(dep, name):
    _, project, build, _, _ = dep
    p = project()
    m = p / "xu.xun"
    m.write_text(m.read_text().replace("  rempkg:", "  " + name + ":"))
    rejected(build(p), "module path")
