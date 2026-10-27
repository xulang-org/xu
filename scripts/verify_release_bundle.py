#!/usr/bin/env python3
"""Verify every release archive, file inventory and embedded setup payload."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import platform
import struct
import subprocess
import tarfile
import zipfile


TARGETS = ("macos-arm64", "macos-x64", "linux-x64", "linux-arm64",
           "linux-loongarch64", "linux-riscv64", "windows-x64", "windows-arm64")
TOOLS = ("xu", "xu-setup", "xu-doctor", "xu-fmt", "xu-doc", "xu-map",
         "xu-desktop", "xu-update", "xu-lsp", "xu-native", "xu-xacp")
ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def architecture(header, target):
    if target.startswith("windows-"):
        assert header[:2] == b"MZ", target
        offset = struct.unpack_from("<I", header, 60)[0]
        assert header[offset:offset + 4] == b"PE\0\0", target
        assert struct.unpack_from("<H", header, offset + 4)[0] == (0xaa64 if target.endswith("arm64") else 0x8664)
    elif target.startswith("linux-"):
        assert header[:6] == b"\x7fELF\x02\x01", target
        assert struct.unpack_from("<H", header, 18)[0] == {
            "linux-x64": 62, "linux-arm64": 183, "linux-loongarch64": 258, "linux-riscv64": 243}[target]
    else:
        assert header[:4] == b"\xcf\xfa\xed\xfe", target
        assert struct.unpack_from("<I", header, 4)[0] == (0x100000c if target.endswith("arm64") else 0x1000007)


def verify_archive(path, version, target, host):
    prefix = f"xu-v{version}" + ("-devkit/" if target == "devkit-all" else "/")
    actual, metadata, editor = {}, None, False

    def consume(name, source):
        nonlocal metadata, editor
        assert name.startswith(prefix), name
        relative = name[len(prefix):]
        parts = PurePosixPath(relative).parts
        assert parts and ".." not in parts and "\\" not in relative and relative not in actual, name
        assert parts[0] not in {".git", "docs", "tests", "notes", "reports", "tmp"}, name
        assert "AGENTS.md" not in parts and "CLAUDE.md" not in parts, name
        digest = hashlib.sha256()
        header = b""
        kept = [] if relative == "bundle.json" or relative.endswith(".vsix") else None
        while block := source.read(1024 * 1024):
            digest.update(block)
            if len(header) < 4096:
                header += block[:4096 - len(header)]
            if kept is not None:
                kept.append(block)
        actual[relative] = digest.hexdigest()
        if relative == "bundle.json":
            metadata = json.loads(b"".join(kept))
        elif relative.endswith(".vsix"):
            with zipfile.ZipFile(io.BytesIO(b"".join(kept))) as extension:
                package = json.loads(extension.read("extension/package.json"))
                assert relative.endswith(f"{package['name']}-{package['version']}.vsix")
                assert "extension/dist/extension.js" in extension.namelist()
                editor = True
        if parts[0] == "bin":
            binary_target = target
            if target == "devkit-all":
                binary_target = parts[2] if len(parts) == 4 and parts[1] == "platform" else host
            architecture(header, binary_target)

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if not entry.is_dir():
                    with archive.open(entry) as source:
                        consume(entry.filename, source)
    else:
        with tarfile.open(path, "r|gz") as archive:
            for entry in archive:
                if entry.isdir():
                    continue
                assert entry.isfile(), entry.name
                with archive.extractfile(entry) as source:
                    consume(entry.name, source)
    assert metadata and metadata["version"] == version and metadata["target"] == target
    assert metadata["lane"] == "product" and editor
    assert set(actual) == set(metadata["files"]) | {"bundle.json"}
    assert all(actual[name] == expected for name, expected in metadata["files"].items())
    if target == "devkit-all":
        assert set(metadata["platforms"]) == set(TARGETS)
        for platform_target in TARGETS:
            suffix = ".exe" if platform_target.startswith("windows-") else ""
            assert all(f"bin/platform/{platform_target}/{tool}{suffix}" in actual for tool in TOOLS)
    else:
        suffix = ".exe" if target.startswith("windows-") else ""
        assert set(metadata["binaries"]) == {tool + suffix for tool in TOOLS}
        assert all(actual["bin/" + name] == expected for name, expected in metadata["binaries"].items())
    print(f"release-verify: {target} complete inventory, tools, architectures and VSIX PASS", flush=True)


def verify(root, receipt):
    version = (ROOT / "VERSION").read_text().strip()
    sums = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split(None, 1)
        name = name.strip().lstrip("*")
        assert Path(name).name == name and name not in sums
        assert sha256(root / name) == expected, name
        sums[name] = expected
    assert len(sums) == 27
    assert {p.name for p in root.iterdir() if p.is_file()} == set(sums) | {
        "SHA256SUMS", "RELEASE_MANIFEST.md", "RELEASE_NOTES.md"}
    host_os = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}[platform.system()]
    host_arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    host = host_os + "-" + host_arch
    for target in TARGETS:
        extension = ".zip" if target.startswith("windows-") else ".tar.gz"
        sdk = f"xu-v{version}-{target}{extension}"
        verify_archive(root / sdk, version, target, host)
        suffix = ".exe" if target.startswith("windows-") else ""
        installer = root / f"xu-setup-{target}{suffix}"
        alias = root / f"xu-v{version}-{target}-setup{suffix}"
        assert sha256(installer) == sha256(alias)
        with installer.open("rb") as source:
            source.seek(-24, 2)
            footer = source.read()
            assert footer[16:] == b"XUPACK01"
            size = int(footer[:16])
            assert 0 < size < installer.stat().st_size - 24
            source.seek(-24 - size, 2)
            digest = hashlib.sha256()
            while size:
                chunk = source.read(min(size, 1024 * 1024))
                assert chunk
                digest.update(chunk)
                size -= len(chunk)
            assert digest.hexdigest() == sums[sdk], target
    verify_archive(root / f"xu-v{version}-devkit-all.tar.gz", version, "devkit-all", host)
    for target in ("macos-arm64", "macos-x64"):
        with (root / f"xu-v{version}-{target}.pkg").open("rb") as package:
            assert package.read(4) == b"xar!"
    record = {"version": version, "tag": "v" + version,
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
              "assets": {p.name: {"sha256": sha256(p), "size": p.stat().st_size}
                         for p in sorted(root.iterdir()) if p.is_file()}}
    receipt.write_text(json.dumps(record, indent=2) + "\n")
    print("release-verify: all 30 publishable files and embedded SDK payloads PASS", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    verify(args.root.resolve(), args.receipt.resolve())
