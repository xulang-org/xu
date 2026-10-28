#!/usr/bin/env python3
"""Compile and execute Windows worker, Map, and environment regressions."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time


class WindowsTemporaryDirectory(tempfile.TemporaryDirectory):
    def cleanup(self) -> None:
        # x64 emulation can briefly retain the executable mapping after exit.
        for attempt in range(20):
            try:
                super().cleanup()
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.25)


SOURCE = """@main
fn worker(ch chan int,value int) {
    mut flags := map[int]bool{}
    flags[value] = true
    mut values := map[string]int{}
    values["worker"] = value
    for i in 0:64 {
        flags[value * 100 + i] = true
        values["key-" + str(i)] = i
    }
    sleep_ns(1000000)
    if flags[value] { ch <- values["worker"] }
    else { ch <- -1 }
}
fn main() int {
    if env_get("XU_WINDOWS_REGRESSION") != "case-insensitive" { eprintln("Windows environment name lookup failed")
        << 2 }
    for round in 0:8 {
        ch := chan int{cap: 0}
        for i in 0:32 { xu worker(ch,i) }
        mut total := 0
        for i in 0:32 { total += <-ch }
        if total != 496 { eprintln("worker result mismatch")
            << 1 }
    }
    println("Windows worker regression passed")
    << 0
}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--target", choices=("windows-arm64", "windows-x64"))
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("requires a Windows host")
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, XU_ROOT=str(root), XU_STDLIB_ROOT=str(root / "src"), XUPATH="")
    with WindowsTemporaryDirectory(prefix="xu-windows-workers-") as folder:
        workspace = Path(folder)
        source = workspace / "main.xu"
        source.write_text(SOURCE, encoding="utf-8")
        executable = workspace / "workers.exe"
        target = ["--target", args.target] if args.target else []
        subprocess.run([str(args.compiler.resolve()), "build", str(source), *target, "-o", str(executable)], env=env, check=True, timeout=120)
        # Supply mixed casing directly; Windows lookup must ignore name casing.
        run_env = dict(env)
        run_env["Xu_Windows_Regression"] = "case-insensitive"
        subprocess.run([str(executable)], env=run_env, check=True, timeout=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
