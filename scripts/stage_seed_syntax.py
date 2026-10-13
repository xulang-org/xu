#!/usr/bin/env python3
"""Stage slash declarations for legacy dot-syntax seeds; never edit product sources."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

DECL = re.compile(rb"\A@([A-Za-z_]\w*(?:/[A-Za-z_]\w*)+)(?=\s|$)")
MODULE = re.compile(rb"(?m)^(module: )([A-Za-z_]\w*(?:/[A-Za-z_]\w*)+)(?=\r?$)")


def stage(source: Path, destination: Path) -> int:
    if destination.exists():
        raise ValueError("seed staging destination already exists")
    destination.mkdir(parents=True)
    count = 0
    for path in sorted(source.rglob("*")):
        if path.suffix != ".xu" and path.name != "xu.xun":
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"seed input must be a regular file: {path}")
        data = path.read_bytes()
        if path.suffix == ".xu":
            data = DECL.sub(lambda m: b"@" + m[1].replace(b"/", b"."), data, count=1)
        else:
            data = MODULE.sub(lambda m: m[1] + m[2].replace(b"/", b"."), data)
        dest = destination / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--dest-root", type=Path, required=True)
    args = parser.parse_args()
    print(f"seed slash bridge: staged {stage(args.source_root, args.dest_root)} files")


if __name__ == "__main__":
    main()
