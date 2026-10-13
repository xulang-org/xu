"""Portable SDK packaging and installer regression contracts."""
import functools
import http.server
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pack_release_bundle as bundle
from sdk_seed import extract_seed


def executable(target):
    data = bytearray(128)
    if target.startswith("windows-"):
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 60, 64)
        data[64:68] = b"PE\0\0"
        struct.pack_into("<H", data, 68, 0xAA64 if target.endswith("arm64") else 0x8664)
    elif target.startswith("linux-"):
        data[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", data, 18, {"x64": 62, "arm64": 183, "riscv64": 243, "loongarch64": 258}[target[6:]])
    else:
        data[:4] = b"\xcf\xfa\xed\xfe"
        struct.pack_into("<I", data, 4, 0x0100000C if target.endswith("arm64") else 0x01000007)
    return data


@pytest.mark.parametrize("target", bundle.SUPPORTED_TARGETS)
def test_binary_identity_rejects_wrong_platform(tmp_path, target):
    path = tmp_path / "binary"
    path.write_bytes(executable(target))
    bundle.validate_binary(path, target)
    wrong = "windows-x64" if target != "windows-x64" else "windows-arm64"
    with pytest.raises(ValueError, match="does not match"):
        bundle.validate_binary(path, wrong)
    path.write_bytes(b"not an executable")
    with pytest.raises(ValueError):
        bundle.validate_binary(path, target)


def test_failed_tool_build_never_copies_native_placeholder(monkeypatch, tmp_path):
    native = tmp_path / "bin/xu-fmt"
    native.parent.mkdir()
    native.write_bytes(executable("macos-arm64"))
    monkeypatch.setattr(bundle, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(bundle.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b"build failed"))
    with pytest.raises(RuntimeError, match="Failed to build"):
        bundle.ensure_tool_built(tmp_path / "bin/xu", "linux-x64", "xu-fmt", "src/cmd/fmt", tmp_path / "cache")
    assert not (tmp_path / "cache/linux-x64/xu-fmt").exists()


def test_windows_snapshot_keeps_arch_in_filename(monkeypatch, tmp_path):
    monkeypatch.setattr(bundle, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(bundle, "get_host_target", lambda: "macos-arm64")
    monkeypatch.setattr(bundle, "SIBLING_TOOLS", [])
    monkeypatch.setattr(bundle, "project_root", lambda project: tmp_path / project)
    monkeypatch.setattr(bundle, "vscode_package_files", lambda path: [])
    (tmp_path / "src").mkdir()
    snapshot = tmp_path / "developer/bin/xu.windows.arm64.exe"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(executable("windows-arm64"))
    dest = tmp_path / "stage"
    bundle.assemble_bundle_dir("windows-arm64", dest, tmp_path / "host-xu", tmp_path / "cache", "0.8.2")
    assert (dest / "bin/xu.exe").read_bytes() == snapshot.read_bytes()


def test_sdk_seed_rejects_tampered_compiler(tmp_path):
    stage = tmp_path / "sdk"
    compiler = stage / "bin/xu"
    compiler.parent.mkdir(parents=True)
    compiler.write_bytes(executable("linux-x64"))
    metadata = {"target": "linux-x64", "lane": "product", "binaries": {"xu": bundle.compute_sha256(compiler)}}
    (stage / "bundle.json").write_text(json.dumps(metadata))
    archives = tmp_path / "artifacts/dist/sdk-ci"
    archive = archives / "xu-v0.8.3-linux-x64.tar.gz"
    bundle.package_tar_gz(stage, archive, "xu-v0.8.3")
    result = extract_seed(tmp_path / "artifacts", "linux-x64", tmp_path / "seed")
    assert result.read_bytes() == compiler.read_bytes()
    compiler.write_bytes(compiler.read_bytes() + b"tampered")
    bundle.package_tar_gz(stage, archive, "xu-v0.8.3")
    with pytest.raises(ValueError, match="checksum mismatch"):
        extract_seed(tmp_path / "artifacts", "linux-x64", tmp_path / "tampered seed")


def test_bundled_example_uses_installed_packages_root(monkeypatch, tmp_path):
    core = tmp_path / "xu"
    (core / "src").mkdir(parents=True)
    compiler = core / "xu"
    compiler.write_bytes(executable("linux-x64"))
    monkeypatch.setattr(bundle, "REPO_ROOT", core)
    monkeypatch.setattr(bundle, "get_host_target", lambda: "linux-x64")
    monkeypatch.setattr(bundle, "SIBLING_TOOLS", [])
    monkeypatch.setattr(bundle, "project_root", lambda project: tmp_path / project)
    monkeypatch.setattr(bundle, "vscode_package_files", lambda path: [])
    example = tmp_path / "examples/examples/driver"
    example.mkdir(parents=True)
    manifest = example / "xu.xun"
    original = 'module: main\nversion: !ver 0.1.0\nrequire:\n  "github.com/xulang-org/packages": file:../../../packages\n'
    manifest.write_text(original)
    packages = tmp_path / "packages"
    packages.mkdir()
    (packages / "xu.xun").write_text('module: "github.com/xulang-org/packages"\nversion: !ver 0.1.0\n')
    stage = tmp_path / "stage"
    bundle.assemble_bundle_dir("linux-x64", stage, compiler, tmp_path / "cache", "0.8.3")
    text = (stage / "examples/driver/xu.xun").read_text()
    assert "file:../../packages" in text
    assert (stage / "examples/driver/../../packages/xu.xun").resolve().is_file()
    assert manifest.read_text() == original


@pytest.mark.skipif(os.name == "nt", reason="Unix shell installer; native Windows installer runs in the SDK matrix")
def test_online_install_handles_versioned_archive_root_and_preserves_paths(tmp_path):
    target = bundle.get_host_target()
    version = "0.8.2"
    stage = tmp_path / "archive sources"
    (stage / "src").mkdir(parents=True)
    (stage / "bin").mkdir()
    (stage / "VERSION").write_text(version)
    (stage / "TARGET").write_text(target)
    compiler = stage / "bin/xu"
    compiler.write_text('#!/bin/sh\nprintf "Xu v0.8.2\\n"\n')
    compiler.chmod(0o755)
    import shutil
    shutil.copy2(ROOT / "scripts/env.sh", stage / "env.sh")
    webroot = tmp_path / "downloads"
    archive = webroot / f"v{version}/xu-v{version}-{target}.tar.gz"
    bundle.package_tar_gz(stage, archive, f"xu-v{version}")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(webroot))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Copy only the online entry point, outside a source checkout.
    installer = tmp_path / "online entry/install.sh"
    installer.parent.mkdir()
    shutil.copy2(ROOT / "scripts/install.sh", installer)
    prefix = tmp_path / "installed Xu SDK"
    env = dict(os.environ, XU_DOWNLOAD_URL=f"http://127.0.0.1:{server.server_port}", XU_SKIP_EDITOR_INSTALL="1")
    for key in ("XU_PACKAGES_ROOT", "XU_VSCODE_ROOT"):
        env.pop(key, None)
    try:
        result = subprocess.run(["bash", str(installer), "--version", version, "--prefix", str(prefix), "--no-modify-path"],
                                cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert result.returncode == 0, result.stdout + result.stderr
    assert (prefix / "src").is_dir()
    assert (prefix / "bin/xu").is_file()
    env["XUPATH"] = str(tmp_path / "user packages")
    result = subprocess.run(["bash", "-c", 'source "$1/env.sh" >/dev/null; source "$1/env.sh" >/dev/null; printf "%s\\n" "$XUPATH" "$XU_STDLIB_ROOT"', "activate", str(prefix)],
                            env=env, text=True, capture_output=True, check=True)
    assert result.stdout.splitlines() == [str(prefix / "src") + ":" + env["XUPATH"], str(prefix / "src")]


@pytest.mark.skipif(os.name == "nt", reason="Unix shell installer")
def test_wrong_platform_fails_before_overwriting_install(tmp_path):
    import shutil
    stage = tmp_path / "bundle"
    (stage / "bin").mkdir(parents=True)
    (stage / "src").mkdir()
    (stage / "VERSION").write_text("0.8.2")
    (stage / "TARGET").write_text("windows-x64")
    shutil.copy2(ROOT / "scripts/install.sh", stage / "install.sh")
    prefix = tmp_path / "existing install"
    prefix.mkdir()
    (prefix / "keep").write_text("previous installation")
    result = subprocess.run(["bash", str(stage / "install.sh"), "--prefix", str(prefix), "--no-modify-path"], text=True, capture_output=True)
    assert result.returncode != 0
    assert "does not match host" in result.stderr
    assert (prefix / "keep").read_text() == "previous installation"
    assert not (prefix / "bin").exists()


@pytest.mark.skipif(os.name == "nt", reason="Unix activation")
def test_devkit_activation_selects_native_platform(tmp_path):
    import shutil
    (tmp_path / "src").mkdir()
    native_bin = tmp_path / "bin/platform" / bundle.get_host_target()
    native_bin.mkdir(parents=True)
    compiler = native_bin / "xu"
    compiler.write_text('#!/bin/sh\nprintf "native compiler\\n"\n')
    compiler.chmod(0o755)
    wrong = tmp_path / "bin/xu"
    wrong.write_text('#!/bin/sh\nexit 99\n')
    wrong.chmod(0o755)
    shutil.copy2(ROOT / "scripts/env.sh", tmp_path / "env.sh")
    result = subprocess.run(["bash", "-c", 'source "$1/env.sh" >/dev/null; xu --version', "devkit", str(tmp_path)],
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "native compiler"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell parser runs on Windows")
def test_powershell_scripts_parse():
    for name in ("install.ps1", "env.ps1", "uninstall.ps1"):
        path = str(ROOT / "scripts" / name).replace("'", "''")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command",
            f"$tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors); if ($errors.Count) {{ $errors | Out-String | Write-Error; exit 1 }}"],
            text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
