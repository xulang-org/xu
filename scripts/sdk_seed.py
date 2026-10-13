#!/usr/bin/env python3
"""Extract and validate a platform SDK compiler for a native product CI hop."""
import argparse
import json
from pathlib import Path
import tarfile
import zipfile

from pack_release_bundle import SUPPORTED_TARGETS, compute_sha256, validate_binary


def extract_seed(archives: Path, target: str, destination: Path) -> Path:
    extension = "zip" if target.startswith("windows-") else "tar.gz"
    candidates = list(archives.rglob(f"xu-v*-{target}.{extension}"))
    if len(candidates) != 1:
        raise ValueError(f"Need exactly one {target} product SDK archive: {candidates}")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Seed destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    if extension == "zip":
        with zipfile.ZipFile(candidates[0]) as archive:
            for name in archive.namelist():
                if not (destination / name).resolve().is_relative_to(destination.resolve()):
                    raise ValueError(f"Unsafe ZIP member: {name}")
            archive.extractall(destination)
    else:
        with tarfile.open(candidates[0]) as archive:
            archive.extractall(destination, filter="data")
    roots = [p for p in destination.iterdir() if (p / "bundle.json").is_file()]
    if len(roots) != 1:
        raise ValueError("Seed archive must contain one SDK root")
    root = roots[0]
    metadata = json.loads((root / "bundle.json").read_text())
    if metadata.get("target") != target or metadata.get("lane") != "product":
        raise ValueError("Seed must be a product SDK for the runner target")
    compiler = root / "bin" / ("xu.exe" if target.startswith("windows-") else "xu")
    validate_binary(compiler, target)
    if metadata.get("binaries", {}).get(compiler.name) != compute_sha256(compiler):
        raise ValueError("Seed compiler checksum mismatch")
    compiler.chmod(0o755)
    return compiler.resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", type=Path, required=True)
    parser.add_argument("--target", choices=SUPPORTED_TARGETS, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compiler = extract_seed(args.archives, args.target, args.destination)
    args.output.write_bytes(compiler.as_posix().encode())


if __name__ == "__main__":
    main()
