"""Real CLI module graphs, proxy boundaries and kernel-lock transactions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))


def escaped(value):
    return "".join("!" + c.lower() if c.isupper() else c for c in value)


@pytest.fixture
def modules(tmp_path):
    proxy = tmp_path / "proxy"
    proxy.mkdir()
    cache = tmp_path / "cache"
    env = dict(os.environ, XUPATH="", XU_CACHE=str(cache),
               XU_STDLIB_ROOT=str(ROOT / "src"), XUPROXY=proxy.as_uri())
    for name in ("XUOS", "XUARCH", "XU_HEAP_STATS", "XUPRIVATE", "XUNOPROXY"):
        env.pop(name, None)

    def release(key, version, value=42, requires=(), dependency=None,
                archive_entries=None, compression=zipfile.ZIP_DEFLATED):
        folder = proxy / escaped(key) / "@v"
        folder.mkdir(parents=True, exist_ok=True)
        manifest = f'module: "{key}"\nversion: !ver {version[1:]}\n'
        if requires:
            manifest += "require:\n" + "".join(f'  "{k}": {v}\n' for k, v in requires)
        imports = f'child #"{dependency}"\n' if dependency else ""
        answer = "child.answer() + 1" if dependency else str(value)
        source = f'@"{key}"\n{imports}pub fn answer() int {{ << {answer} }}\n'
        (folder / (escaped(version) + ".info")).write_text(json.dumps({"Version": version}))
        (folder / (escaped(version) + ".mod")).write_text(manifest)
        archive = folder / (escaped(version) + ".zip")
        with zipfile.ZipFile(archive, "w", compression=compression) as z:
            z.writestr(f"{key}@{version}/xu.xun", manifest)
            z.writestr(f"{key}@{version}/mod.xu", source)
            for name, body in archive_entries or ():
                z.writestr(name, body)
        return folder

    def app(name="app", requires=(), imported=None):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "xu.xun").write_text('module: app\nversion: !ver 0.1.0\nrequire:\n' +
                                      "".join(f'  "{k}": {v}\n' for k, v in requires))
        if imported is None:
            imported = requires[0][0]
        (folder / "main.xu").write_text(f'@main\nlib #"{imported}"\nfn main() int {{ println(lib.answer())\n << 0 }}\n')
        return folder

    def run(folder, command="build", flags=(), custom_env=None):
        args = [str(XU), command, *flags]
        args += [str(folder)] if command == "install" else [str(folder / "main.xu"), "-o", str(folder / "program")]
        return subprocess.run(args, cwd=folder, env=custom_env or env,
                              capture_output=True, text=True, timeout=90)

    return tmp_path, proxy, cache, env, release, app, run


def ok(result):
    assert result.returncode == 0, result.stdout + result.stderr


def reject(result, needle):
    assert result.returncode != 0, "dependency policy was ignored"
    assert needle in result.stderr, result.stderr


def output(app):
    return subprocess.check_output([str(app / "program")], text=True, timeout=10)


def versions(app):
    lines = (app / "xu.lock").read_text().splitlines()
    assert lines[0] == "xu-lock-v3 sha256-tree-v1"
    return {(f[0], f[4]) for f in (line.split() for line in lines[1:])}


@pytest.mark.parametrize("reverse", [False, True])
def test_mvs_diamond_selects_highest_minimum_and_frozen_replays_graph(modules, reverse):
    root, _, cache, env, release, app, run = modules
    common, left, right = [f"example.com/{name}" for name in ("common", "left", "right")]
    release(common, "v1.2.0", value=12)
    release(common, "v1.10.0", value=110)
    release(left, "v1.0.0", requires=[(common, "v1.2.0")], dependency=common)
    release(right, "v1.0.0", requires=[(common, "v1.10.0")])
    edges = [(left, "v1.0.0"), (right, "v1.0.0")]
    p = app(requires=list(reversed(edges)) if reverse else edges, imported=left)
    ok(run(p))
    assert output(p) == "111\n"
    assert (common, "v1.2.0") in versions(p) and (common, "v1.10.0") in versions(p)
    ok(run(p, "install", ["--offline"]))
    shutil.rmtree(cache)
    lock = (p / "xu.lock").read_bytes()
    ok(run(p, flags=["--frozen"]))
    assert output(p) == "111\n"
    relocated = root / "relocated"
    shutil.copytree(p, relocated)
    ok(run(relocated, flags=["--frozen"]))
    assert output(relocated) == "111\n"
    assert (p / "xu.lock").read_bytes() == lock
    assert not cache.exists()


def test_superseded_version_still_contributes_its_requirements(modules):
    _, _, _, _, release, app, run = modules
    a, b = "example.com/a", "example.com/b"
    release(a, "v1.0.0", requires=[(b, "v1.9.0")])
    release(a, "v1.1.0", requires=[(b, "v1.2.0")], dependency=b)
    release(b, "v1.2.0", value=2)
    release(b, "v1.9.0", value=9, requires=[(a, "v1.1.0")])
    c = "example.com/c"
    release(c, "v1.0.0", requires=[(a, "v1.0.0")])
    p = app(requires=[(a, "v1.1.0"), (c, "v1.0.0")])
    ok(run(p))
    assert output(p) == "10\n"
    assert len(versions(p)) == 5


@pytest.mark.parametrize("lo,hi", [
    ("v1.0.0-rc.9", "v1.0.0-rc.10"),
    ("v1.0.0-alpha", "v1.0.0"),
    ("v1.0.0-1", "v1.0.0-alpha"),
    ("v1.0.0-alpha", "v1.0.0-alpha.1"),
    ("v1.99999999999999999999.0", "v1.100000000000000000000.0"),
])
def test_semver_ordering_without_integer_overflow(modules, lo, hi):
    _, _, _, _, release, app, run = modules
    a, b = "example.com/semver", "example.com/parent"
    release(a, lo, value=1)
    release(a, hi, value=2)
    release(b, "v1.0.0", requires=[(a, hi)])
    p = app(requires=[(a, lo), (b, "v1.0.0")])
    ok(run(p))
    assert output(p) == "2\n"


@pytest.mark.parametrize("pin", ["v01.0.0", "v1.0.0-01", "v1.0", "v1.0.0+metadata", "v2.0.0"])
def test_invalid_or_wrong_major_version_fails_before_io(modules, pin):
    _, _, cache, _, _, app, run = modules
    p = app(requires=[("example.com/module", pin)])
    reject(run(p), "invalid locator")
    assert not cache.exists() and not (p / "xu.lock").exists()


def test_two_major_versions_can_coexist(modules):
    _, _, _, _, release, app, run = modules
    release("example.com/module", "v1.0.0", value=1)
    release("example.com/module/v2", "v2.0.0", value=2)
    p = app(requires=[("example.com/module", "v1.0.0"), ("example.com/module/v2", "v2.0.0")], imported="example.com/module/v2")
    ok(run(p))
    assert output(p) == "2\n"


def test_version_snapshot_tamper_is_rejected(modules):
    _, _, cache, _, release, app, run = modules
    key = "example.com/module"
    release(key, "v1.0.0")
    p = app(requires=[(key, "v1.0.0")])
    ok(run(p, "install"))
    shutil.rmtree(cache)
    snapshot = next((p / "vendor/.xu-versions").glob("*/mod.xu"))
    snapshot.write_text(snapshot.read_text().replace("42", "99"))
    reject(run(p, flags=["--frozen"]), "snapshot checksum mismatch")


@contextmanager
def server(proxy, *, status=200, delay=0):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if delay:
                time.sleep(delay)
            target = proxy / self.path.lstrip("/")
            actual = status if status != 200 else (200 if target.is_file() else 404)
            self.send_response(actual)
            self.end_headers()
            if actual == 200:
                self.wfile.write(target.read_bytes())
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}", requests
    finally:
        http.shutdown()
        thread.join()
        http.server_close()


@pytest.mark.parametrize("status,separator,success", [
    (404, ",", True), (410, ",", True), (403, ",", False),
    (500, ",", False), (500, "|", True),
])
def test_proxy_fallback_respects_gatekeeper_errors(modules, status, separator, success):
    _, proxy, _, env, release, app, run = modules
    key = "example.com/module"
    release(key, "v1.0.0")
    p = app(requires=[(key, "v1.0.0")])
    with server(proxy, status=status) as (url, requests):
        env["XUPROXY"] = url + separator + proxy.as_uri()
        r = run(p)
    if success:
        ok(r)
        assert output(p) == "42\n"
    else:
        reject(r, "proxy request failed")
        assert not (p / "xu.lock").exists()
    assert requests == [f"/{key}/@v/v1.0.0.info"]


def test_proxy_case_escaping_and_offline_cache(modules):
    _, proxy, _, env, release, app, run = modules
    key = "example.com/My-Lib"
    release(key, "v1.0.0-RC.1")
    p = app(requires=[(key, "v1.0.0-RC.1")])
    with server(proxy) as (url, requests):
        env["XUPROXY"] = url
        ok(run(p))
    assert requests == [f"/example.com/!my-!lib/@v/v1.0.0-!r!c.1{suffix}" for suffix in (".info", ".mod", ".zip")]
    env["XUPROXY"] = "off"
    ok(run(p, flags=["--offline"]))
    assert output(p) == "42\n"


@pytest.mark.parametrize("part", [".info", ".mod", ".zip"])
def test_successful_but_inconsistent_proxy_data_never_falls_back(modules, part):
    root, proxy, _, env, release, app, run = modules
    key, version = "example.com/module", "v1.0.0"
    folder = release(key, version)
    other = root / "other"
    shutil.copytree(proxy, other)
    target = folder / (version + part)
    if part == ".info":
        target.write_text(json.dumps({"Version": "v1.1.0"}))
        needle = ".info version mismatch"
    elif part == ".mod":
        target.write_text(target.read_text().replace("1.0.0", "1.1.0"))
        needle = ".mod differs"
    else:
        target.write_bytes(b"corrupt zip")
        needle = "module ZIP"
    env["XUPROXY"] = proxy.as_uri() + "|" + other.as_uri()
    p = app(requires=[(key, version)])
    reject(run(p), needle)
    assert not (p / "xu.lock").exists()


@pytest.mark.parametrize("name", [
    "example.com/module@v1.0.0/../escape.xu",
    "wrong@v1.0.0/mod.xu",
    "example.com/module@v1.0.0/CON.txt",
    "example.com/module@v1.0.0/mod.XU",
    "example.com/module@v1.0.0/.ok",
])
def test_module_zip_rejects_unsafe_or_colliding_paths(modules, name):
    _, _, _, _, release, app, run = modules
    key = "example.com/module"
    release(key, "v1.0.0", archive_entries=[(name, "unsafe")])
    p = app(requires=[(key, "v1.0.0")])
    reject(run(p), "ZIP")
    assert not (p / "xu.lock").exists()


def test_concurrent_cold_projects_download_each_version_once(modules):
    _, proxy, _, env, release, app, run = modules
    key = "example.com/module"
    release(key, "v1.0.0")
    projects = [app(f"app{i}", requires=[(key, "v1.0.0")]) for i in range(6)]
    with server(proxy, delay=0.05) as (url, requests):
        env["XUPROXY"] = url
        with ThreadPoolExecutor(max_workers=len(projects)) as pool:
            results = list(pool.map(run, projects))
    for result in results:
        ok(result)
    assert len(requests) == 3, requests
    for p in projects:
        assert output(p) == "42\n"
        assert versions(p) == {(key, "v1.0.0")}


def test_same_project_parallel_install_and_build_preserve_vendor_and_lock(modules):
    _, proxy, _, env, release, app, run = modules
    a, b = "example.com/a", "example.com/b"
    release(a, "v1.0.0", requires=[(b, "v1.0.0")], dependency=b)
    release(b, "v1.0.0")
    p = app(requires=[(a, "v1.0.0")])
    with server(proxy, delay=0.03) as (url, requests):
        env["XUPROXY"] = url
        with ThreadPoolExecutor(max_workers=6) as pool:
            tasks = [pool.submit(run, p, "install" if i % 2 else "build") for i in range(6)]
            for task in tasks:
                ok(task.result())
    assert len(requests) == 6
    assert versions(p) == {(a, "v1.0.0"), (b, "v1.0.0")}
    ok(run(p, flags=["--frozen"]))
    assert output(p) == "43\n"


def test_failed_download_does_not_strand_lock_or_publish_partial_cache(modules):
    _, proxy, cache, env, release, app, run = modules
    key = "example.com/module"
    release(key, "v1.0.0")
    p = app(requires=[(key, "v1.0.0")])
    with server(proxy, status=500) as (url, _):
        env["XUPROXY"] = url
        reject(run(p), "proxy request failed")
    assert not list(cache.glob("*/.ok"))
    env["XUPROXY"] = proxy.as_uri()
    ok(run(p))
    assert output(p) == "42\n"


def test_private_patterns_bypass_proxy_without_leaking_paths(modules):
    _, proxy, _, env, _, app, run = modules
    key = "private.example.com/team/module"
    p = app(requires=[(key, "v1.0.0")])
    with server(proxy) as (url, requests):
        env.update(XUPROXY=url, XUPRIVATE="*.example.com/team")
        reject(run(p), "direct version discovery supports")
    assert requests == []


def test_kernel_lock_is_exclusive_and_released_when_owner_is_killed(tmp_path):
    source = tmp_path / "lock.xu"
    source.write_text('''@main
#os
#time
fn main() int {
    args := os.argv()
    mut file := os.open_lock(args[1] + "", false) or (err) { << 2 }
    println("LOCKED")
    time.sleep(30000000000)
    file.close() or (err) { << 3 }
    << 0
}
''')
    binary = tmp_path / "lock"
    env = dict(os.environ, XUPATH="", XU_STDLIB_ROOT=str(ROOT / "src"))
    for name in ("XUOS", "XUARCH", "XU_HEAP_STATS"):
        env.pop(name, None)
    ok(subprocess.run([str(XU), "build", str(source), "-o", str(binary)],
                      cwd=ROOT, env=env, capture_output=True, text=True, timeout=90))
    command = [str(binary), str(tmp_path / "process.lck")]
    for _ in range(2):
        owner = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
        try:
            assert owner.stdout.readline().strip() == "LOCKED"
            denied = subprocess.run(command, capture_output=True, text=True, timeout=5)
            assert denied.returncode == 2
        finally:
            owner.kill()
            owner.wait(timeout=5)


@pytest.mark.parametrize("separator,success", [(",", False), ("|", True)])
def test_transport_error_fallback_is_explicit(modules, separator, success):
    _, proxy, _, env, release, app, run = modules
    key = "example.com/module"
    release(key, "v1.0.0")
    env["XUPROXY"] = "http://127.0.0.1:1" + separator + proxy.as_uri()
    p = app(requires=[(key, "v1.0.0")])
    result = run(p)
    if success:
        ok(result)
    else:
        reject(result, "proxy request failed")
        assert not (p / "xu.lock").exists()


def test_zip_data_descriptors_are_supported(modules):
    _, _, _, _, release, app, run = modules
    key, version = "example.com/module", "v1.0.0"
    folder = release(key, version)
    archive = folder / (version + ".zip")
    with zipfile.ZipFile(archive) as z:
        entries = [(info.filename, z.read(info)) for info in z.infolist()]
    class StreamingBuffer(io.BytesIO):
        def seekable(self):
            return False
        def seek(self, *args):
            raise io.UnsupportedOperation("stream")
    stream = StreamingBuffer()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, body in entries:
            z.writestr(name, body)
    archive.write_bytes(stream.getvalue())
    p = app(requires=[(key, version)])
    ok(run(p))
    assert output(p) == "42\n"


def test_symlink_zip_entry_cannot_escape_staging(modules):
    root, _, _, _, release, app, run = modules
    key, version = "example.com/module", "v1.0.0"
    folder = release(key, version)
    link = zipfile.ZipInfo(f"{key}@{version}/link")
    link.create_system = 3
    link.external_attr = 0o120777 << 16
    with zipfile.ZipFile(folder / (version + ".zip"), "a") as z:
        z.writestr(link, "../outside")
    p = app(requires=[(key, version)])
    reject(run(p), "ZIP links")
    assert not (p / "xu.lock").exists() and not (root / "outside").exists()


def test_lowercase_collisions_in_ancestor_directories_are_rejected(modules):
    _, _, _, _, release, app, run = modules
    key, version = "example.com/module", "v1.0.0"
    prefix = f"{key}@{version}/"
    release(key, version, archive_entries=[(prefix + "Dir/a.txt", "one"), (prefix + "dir/b.txt", "two")])
    p = app(requires=[(key, version)])
    reject(run(p), "path collision")


def test_offline_missing_version_does_not_create_cache_or_lock(modules):
    _, _, cache, env, _, app, run = modules
    env["XUPROXY"] = "off"
    p = app(requires=[("example.com/module", "v1.0.0")])
    reject(run(p, flags=["--offline"]), "offline")
    assert not cache.exists() and not (p / "xu.lock").exists()


@pytest.mark.parametrize("submodule", [False, True, "nested_major"])
def test_direct_github_download_checks_root_and_submodule_tags(modules, submodule):
    root, _, cache, env, _, app, run = modules
    provider = root / "provider"
    provider.mkdir()
    repository = "github.com/xulang-org/packages"
    key = repository + "/client" if submodule else repository
    version = "v1.0.0"
    if submodule == "nested_major":
        key += "/v2"
        version = "v2.0.0"
    folder = provider / "client" if submodule else provider
    folder.mkdir(exist_ok=True)
    (folder / "xu.xun").write_text(f'module: "{key}"\nversion: !ver {version[1:]}\n')
    (folder / "mod.xu").write_text(f'@"{key}"\npub fn answer() int {{ << 42 }}\n')
    real_git = shutil.which("git")
    def git(*args):
        subprocess.run([real_git, "-C", str(provider), *args], check=True, capture_output=True)
    git("init")
    git("add", ".")
    git("-c", "user.name=Module test", "-c", "user.email=module@example.invalid", "commit", "-m", "v1")
    git("tag", "client/" + version if submodule else version)
    tools = root / "tools"
    tools.mkdir()
    stub = tools / "git"
    stub.write_text('''#!/usr/bin/env python3
import json,os,sys
args=sys.argv[1:]
with open(os.environ['DIRECT_LOG'],'a') as f:f.write(json.dumps(args)+'\\n')
if 'clone' in args:
    assert args[-2]=='https://github.com/xulang-org/packages.git',args
    args[-2]=os.environ['DIRECT_REPO']
os.execv(os.environ['REAL_GIT'],[os.environ['REAL_GIT'],*args])
''')
    stub.chmod(0o755)
    env.update(PATH=str(tools) + os.pathsep + os.environ["PATH"],
               REAL_GIT=real_git, DIRECT_REPO=str(provider), DIRECT_LOG=str(root / "direct.log"),
               XUPROXY="direct")
    p = app(requires=[(key, version)])
    ok(run(p, "install"))
    shutil.rmtree(cache)
    calls = (root / "direct.log").read_bytes()
    ok(run(p, flags=["--frozen"]))
    assert output(p) == "42\n"
    assert (root / "direct.log").read_bytes() == calls
    assert versions(p) == {(key, version)}


def test_private_patterns_can_be_overridden_for_an_internal_proxy(modules):
    _, _, _, env, release, app, run = modules
    key = "private.example.com/module"
    release(key, "v1.0.0")
    env.update(XUPRIVATE="*.example.com", XUNOPROXY="none")
    p = app(requires=[(key, "v1.0.0")])
    ok(run(p))
    assert output(p) == "42\n"


def test_hidden_resources_survive_version_snapshot_and_vendor_copy(modules):
    _, _, cache, _, release, app, run = modules
    key, version = "example.com/module", "v1.0.0"
    release(key, version, archive_entries=[(f"{key}@{version}/.resources/data.txt", "resource")])
    p = app(requires=[(key, version)])
    ok(run(p, "install"))
    assert (p / "vendor" / key / ".resources/data.txt").read_text() == "resource"
    hidden = next((p / "vendor/.xu-versions").glob("*/.resources/data.txt"))
    assert hidden.read_text() == "resource"
    shutil.rmtree(cache)
    ok(run(p, flags=["--frozen"]))
    hidden.write_text("tampered")
    reject(run(p, flags=["--frozen"]), "snapshot checksum mismatch")


def test_read_dir_preserves_hidden_files_and_remove_all_removes_them(tmp_path):
    folder = tmp_path / "content"
    folder.mkdir()
    (folder / ".hidden").write_text("one")
    nested = folder / ".nested"
    nested.mkdir()
    (nested / ".file").write_text("two")
    (folder / "visible").write_text("three")
    source = tmp_path / "main.xu"
    source.write_text('''@main
#os
fn main() int {
    args := os.argv()
    names := os.read_dir(args[1] + "") or (err) { << 1 }
    println(names)
    os.remove_all(args[1] + "") or (err) { << 2 }
    << 0
}
''')
    binary = tmp_path / "list"
    env = dict(os.environ, XUPATH="", XU_STDLIB_ROOT=str(ROOT / "src"))
    for name in ("XUOS", "XUARCH", "XU_HEAP_STATS"):
        env.pop(name, None)
    ok(subprocess.run([str(XU), "build", str(source), "-o", str(binary)],
                      cwd=ROOT, env=env, capture_output=True, text=True, timeout=90))
    result = subprocess.run([str(binary), str(folder)], env=env, capture_output=True, text=True, timeout=10)
    ok(result)
    assert set(result.stdout.splitlines()) - {""} == {".hidden", ".nested", "visible"}
    assert not folder.exists()


def test_proxy_zip_accepts_portable_asset_names_and_hidden_resources(modules):
    _, _, _, _, release, app, run = modules
    key, version = "example.com/module", "v1.0.0"
    prefix = f"{key}@{version}/"
    release(key, version, archive_entries=[(prefix + "README.md", "readme"),
                                         (prefix + ".Config/Data File.TXT", "asset")])
    p = app(requires=[(key, version)])
    ok(run(p, "install"))
    assert (p / "vendor" / key / "README.md").read_text() == "readme"
    assert (p / "vendor" / key / ".Config/Data File.TXT").read_text() == "asset"


def test_relative_file_proxy_is_rejected(modules):
    _, _, _, env, _, app, run = modules
    env["XUPROXY"] = "file://relative"
    p = app(requires=[("example.com/module", "v1.0.0")])
    reject(run(p), "absolute path")
    assert not (p / "xu.lock").exists()
