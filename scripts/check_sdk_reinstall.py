#!/usr/bin/env python3
"""Exercise actual native/script reinstalls, corruption rejection and rollback."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def run(args, work, env, success=True):
    result = subprocess.run([str(a) for a in args], cwd=work, env=env, text=True,
                            encoding="utf-8", errors="replace", capture_output=True, timeout=180)
    if (result.returncode == 0) != success:
        raise RuntimeError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify(prefix, manifest):
    assert (prefix / "VERSION").read_text().strip() == manifest["version"]
    for name, expected in manifest["files"].items():
        assert digest(prefix / name) == expected, name
    for name, expected in manifest["binaries"].items():
        assert digest(prefix / "bin" / name) == expected, name


def poison(prefix, suffix):
    (prefix / "src/os/mod.xu").write_text("stale standard library")
    (prefix / "src/obsolete.xu").write_text("obsolete")
    (prefix / "bin" / ("xu-doctor" + suffix)).write_text("stale tool")
    (prefix / "src").chmod(0o555)
    (prefix / "bin" / ("xu-doctor" + suffix)).chmod(0o444)
    if os.name != "nt":
        prefix.chmod(0o555)


def rollback_probe(compiler, work, env):
    source = work / "rollback probe"
    source.mkdir()
    (source / "xu.xun").write_text("module: main\nversion: !ver 0.1.0\n")
    (source / "main.xu").write_text("""@main
#os
#internal/sdk
fn main() int {
    args := os.argv()
    sdk.commit_install(&args[1], &args[2], &args[3]) or (err) {
        eprintln(err.msg())
        << 7
    }
    << 0
}
""")
    probe = source / ("probe.exe" if os.name == "nt" else "probe")
    build_env = env | {"XU_STDLIB_ROOT": str(ROOT / "src"), "XUPATH": str(ROOT / "src")}
    build_env.pop("XU_ROOT", None)
    run([compiler, "build", source / "main.xu", "-o", probe], work, build_env)
    old = work / "rollback original"
    old.mkdir()
    (old / "value").write_text("original")
    parent = work / "blocked stage parent"
    parent.mkdir()
    stage = parent / "stage"
    stage.mkdir()
    (stage / "value").write_text("new")
    backup = work / "rollback backup"
    handle = None
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        handle = kernel.CreateFileW(str(stage), 0, 3, None, 3, 0x02000000, None)
        assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    else:
        if os.geteuid() == 0:
            raise RuntimeError("readonly reinstall validation requires a non-root account")
        parent.chmod(0o555)
    try:
        result = run([probe, stage, old, backup], work, env, success=False)
        assert result.returncode == 7
        assert (old / "value").read_text() == "original"
        assert (stage / "value").read_text() == "new"
        assert not backup.exists()
    finally:
        if handle is not None:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
        else:
            parent.chmod(0o755)


def check(archive):
    suffix = ".exe" if os.name == "nt" else ""
    with tempfile.TemporaryDirectory(prefix="xu-sdk-reinstall-") as directory:
        work = Path(directory)
        unpacked = work / "unpacked"
        unpacked.mkdir()
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as source:
                source.extractall(unpacked)
        else:
            with tarfile.open(archive) as source:
                source.extractall(unpacked, filter="data")
        payload, = (p for p in unpacked.iterdir() if p.is_dir())
        manifest_path = payload / "bundle.json"
        original_manifest = manifest_path.read_text()
        manifest = json.loads(original_manifest)
        assert manifest.get("files"), "complete SDK file inventory is required"
        env = dict(os.environ)
        for key in ("XU_ROOT", "XU_STDLIB_ROOT", "XUPATH", "XUOS", "XUARCH",
                    "XU_PACKAGES_ROOT", "XU_EXAMPLES_ROOT", "XU_VSCODE_ROOT", "XU_VERSION"):
            env.pop(key, None)
        home = work / "home"
        home.mkdir()
        env.update(HOME=str(home), TMPDIR=str(work), XU_SKIP_EDITOR_INSTALL="1")
        prefix = work / "installed SDK with spaces"
        native = [payload / ("xu-setup" + suffix), "--yes", "--prefix", prefix, "--no-modify-path"]
        run(native, work, env)
        verify(prefix, manifest)
        banner = run([prefix / "bin" / ("xu" + suffix), "--version"], work, env).stdout
        assert "Xu Compiler Toolchain v" + manifest["version"] + " (self-hosted)" in banner
        assert ("Xu Compiler Toolchain v" + manifest["version"]) in banner.splitlines()
        private = prefix / "user-data"
        private.mkdir(mode=0o700)
        (private / "settings").write_text("preserve user state")
        (private / "settings").chmod(0o600)
        outside = work / "outside userdata"
        outside.mkdir()
        (outside / "keep").write_text("never follow cleanup links")
        if os.name != "nt":
            (prefix / "external-data").symlink_to(outside, target_is_directory=True)
        if os.name == "nt":
            script = ["pwsh", "-NoProfile", "-File", payload / "install.ps1", "-Prefix", prefix, "-NoModifyPath"]
        else:
            script = ["bash", payload / "install.sh", "--prefix", prefix, "--no-modify-path", "--yes"]
        automatic = ["pwsh", "-NoProfile", "-File", payload / "install.ps1", "-NoModifyPath"] if os.name == "nt" else [
            "bash", payload / "install.sh", "--no-modify-path", "--yes"]
        selected_env = env | {"PATH": str(prefix / "bin") + os.pathsep + env.get("PATH", "")}
        selected_env.pop("XU_INSTALL_DIR", None)
        updater = [prefix / "bin" / ("xu" + suffix), "update", "--force", "--version",
                   manifest["version"], "--archive", archive]
        for command in (native, script, automatic, updater):
            before = set(work.glob(".xu-setup-backup-*"))
            poison(prefix, suffix)
            run(command, work, selected_env)
            verify(prefix, manifest)
            assert not (prefix / "src/obsolete.xu").exists()
            assert (private / "settings").read_text() == "preserve user state"
            if os.name != "nt":
                assert private.stat().st_mode & 0o777 == 0o700
                assert (prefix / "external-data").is_symlink()
            saved, = set(work.glob(".xu-setup-backup-*")) - before
            assert (saved / "src/obsolete.xu").read_text() == "obsolete"
        # Reject a corrupt incoming payload before publishing it, even when
        # preserving a user symlink. Its external target must remain intact.
        bad = json.loads(original_manifest)
        bad["binaries"]["xu-doctor" + suffix] = "0" * 64
        manifest_path.write_text(json.dumps(bad))
        run(native, work, env, success=False)
        verify(prefix, manifest)
        assert (outside / "keep").read_text() == "never follow cleanup links"
        manifest_path.write_text(original_manifest)
        lock = work / ("." + prefix.name + ".xu-install.lock")
        lock.write_text("another owner")
        try:
            run(native, work, env, success=False)
            assert lock.read_text() == "another owner"
            verify(prefix, manifest)
        finally:
            lock.unlink()
        rollback_probe(payload / "bin" / ("xu" + suffix), work, env)
        print(f"sdk-reinstall: PASS {manifest['target']} {manifest['version']}: readonly native/script "
              "replacement, PATH selection, running updater, complete hashes, userdata, backups, corruption, lock and rollback")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    check(args.archive.resolve())
