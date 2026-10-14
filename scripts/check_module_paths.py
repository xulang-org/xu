#!/usr/bin/env python3
"""Reject dotted module separators in current Xu sources and manifests."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ("src", "packages", "developer", "tests")


def errors(path: Path, text: str) -> list[str]:
    found = []
    if path.suffix == ".xu":
        declaration = re.match(r"@([^\s]+)", text)
        if declaration and not declaration[1].startswith('"') and "." in declaration[1]:
            found.append("dotted @package declaration; use slash separators")
        # Only import statements; expression/property dots are outside scope.
        for match in re.finditer(r"(?m)^\s*(?:[A-Za-z_]\w*\s+)?#([^\s]+)", text):
            value = match[1]
            if '"' not in value and "." in value and "/" not in value:
                found.append("dotted #import; use slashes or quote an external domain")
    if path.name == "xu.xun":
        module = re.search(r"(?m)^module:\s*(?:!\w+\s+)?([^\s]+)", text)
        if module and not module[1].startswith('"') and "." in module[1] and "/" not in module[1]:
            found.append("dotted module: identity; use slashes or quote an external domain")
    return [f"{path}: {message}" for message in found]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    if args.paths:
        paths = args.paths
    else:
        names = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others",
                                         "--exclude-standard", "--", *DOMAINS]).decode().split("\0")
        paths = [ROOT / name for name in names if name]
    failures = []
    count = 0
    for path in paths:
        if not path.is_file() or (path.suffix != ".xu" and path.name != "xu.xun"):
            continue
        count += 1
        failures.extend(errors(path, path.read_text(encoding="utf-8")))
    for failure in failures:
        print(failure)
    print(f"Module paths: {count} files checked; {len(failures)} violations")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
