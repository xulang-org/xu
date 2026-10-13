#!/usr/bin/env python3
"""DEPRECATED for product path.

Product entry is self-hosted xu: `xu doctor` / `xu build AppDir --desktop`
(src/cmd/compile — pure Xu on macOS; no python3 subprocess).

This script is retained for CI/debug only. Do not wire product xu back to it.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def resolve_xu_entry(src: pathlib.Path) -> pathlib.Path:
    """Desktop project: accept App/main.xu or App/ (→ App/main.xu)."""
    if src.is_file():
        return src
    if src.is_dir():
        main = src / "main.xu"
        if main.is_file():
            return main
    raise SystemExit(f"missing --src (want file or App/main.xu): {src}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Xu desktop oneexe pack (called by product xu --desktop)"
    )
    ap.add_argument("--src", type=pathlib.Path, required=True, help=".xu entry or app dir")
    ap.add_argument(
        "--target",
        required=True,
        help="macos-arm64|macos-x64|windows-x64|linux-x64|linux-arm64",
    )
    ap.add_argument("-o", "--output", type=pathlib.Path, required=True)
    ap.add_argument("--www", type=pathlib.Path, default=None)
    ap.add_argument("--webview", action="store_true")
    ap.add_argument("--no-webview", action="store_true")
    args = ap.parse_args()

    src = args.src if args.src.is_absolute() else (pathlib.Path.cwd() / args.src).resolve()
    src = resolve_xu_entry(src)
    out = args.output if args.output.is_absolute() else (pathlib.Path.cwd() / args.output).resolve()
    target = args.target

    if target.startswith("macos-"):
        arch = "arm64" if target.endswith("arm64") else "x64"
        script = ROOT / "scripts" / "pack_macos_ui_oneexe.py"
        cmd = [
            sys.executable,
            str(script),
            "--src",
            str(src),
            "--arch",
            arch,
            "-o",
            str(out),
        ]
    elif target.startswith("windows-"):
        if target != "windows-x64":
            raise SystemExit(f"xu desktop: unsupported target {target} (need windows-x64)")
        script = ROOT / "scripts" / "pack_windows_ui_oneexe.py"
        cmd = [
            sys.executable,
            str(script),
            "--src",
            str(src),
            "-o",
            str(out),
        ]
    elif target.startswith("linux-"):
        if target not in ("linux-x64", "linux-arm64"):
            raise SystemExit(f"xu desktop: unsupported target {target}")
        script = ROOT / "scripts" / "pack_linux_ui_oneexe.py"
        cmd = [
            sys.executable,
            str(script),
            "--src",
            str(src),
            "--target",
            target,
            "-o",
            str(out),
        ]
    else:
        raise SystemExit(f"xu desktop: not a hosted desktop target: {target}")

    if args.www is not None:
        www = args.www if args.www.is_absolute() else ROOT / args.www
        cmd.extend(["--www", str(www)])
    if args.webview:
        cmd.append("--webview")
    if args.no_webview:
        cmd.append("--no-webview")

    print("xu desktop pack:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    main()
