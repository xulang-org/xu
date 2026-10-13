#!/usr/bin/env python3
"""Archive host .o files into libxu_ui_host.a (foreign → .a → single Xu main)."""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys


def main() -> None:
    ap = argparse.ArgumentParser(description="ar rcs libxu_ui_host.a <objects...>")
    ap.add_argument("-o", "--output", type=pathlib.Path, required=True)
    ap.add_argument("objects", nargs="+", type=pathlib.Path)
    ap.add_argument("--ar", default="ar", help="ar binary (default: ar)")
    args = ap.parse_args()
    objs = [p for p in args.objects if p.is_file()]
    if not objs:
        raise SystemExit("ar_xu_host: no object files")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()
    cmd = [args.ar, "rcs", str(args.output), *[str(p) for p in objs]]
    subprocess.check_call(cmd)
    print("archive:", args.output, args.output.stat().st_size, "bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
