#!/usr/bin/env python3
"""Compile and run zero- and one-word spawn ABI checks using the given host compiler."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SOURCE = """@main

struct Packet { a int b int c int }

fn worker() { println(10) }
fn single(x int) { println(x) }
fn single_tiny(x int) { println(x) }
fn floating(x f64) { println(int(x * 4.0)) }
fn send(c chan int) { c <- 77 }
fn multi(a int, b int) { println(a + b) }
fn wide(x Packet) { println(x.a + x.b + x.c) }
fn wide_result() Packet {
    println(30)
    << Packet{a: 1, b: 2, c: 3}
}

fn launch() {
    xu worker()
    $local := 20
    xu single(local)
    local = 0
    xu single(local)
    xu single_tiny(-21)
    xu floating(2.75)
    xu multi(20, 22)
    xu wide(Packet{a: 1, b: 2, c: 3})
    xu wide_result()
}

fn main() int {
    launch()
    launch()
    ready := chan int{cap: 1}
    xu send(ready)
    println(<-ready)
    // The receive lets the earlier children exit before their stack records
    // are reused for the final batch.
    launch()
    << 0
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiler", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        src = work / "spawn.xu"
        src.write_text(SOURCE)
        program = work / ("program.exe" if os.name == "nt" else "program")
        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_DUMP_MIR="launch", XU_NO_INLINE="1", XU_TASK_POLL="0", XU_TINY_STACK="0")
        for options, poll in (([], "0"), (["--no-opt"], "0"), ([], "1")):
            env["XU_TASK_POLL"] = poll
            build = subprocess.run([args.compiler.resolve(), "build", *options, src, "-o", program],
                                   capture_output=True, text=True, env=env, check=True)
            calls = build.stdout
            for name, count in (("task_spawn_word(", 5), ("alloc(128)", 1), ("alloc(152)", 2)):
                if calls.count("call _xu_runtime_core_" + name) != count:
                    raise AssertionError(f"unexpected number of calls to {name}\n{calls}")
            word_calls = [line for line in calls.splitlines() if "call _xu_runtime_core_task_spawn_word(" in line]
            tiny_count = sum(line.endswith(", 1)") for line in word_calls)
            if tiny_count != (1 if poll == "0" else 0):
                raise AssertionError(f"unexpected tiny task count {tiny_count}\n{calls}")
            if sys.platform == "darwin":
                subprocess.run(["codesign", "-fs", "-", program], check=True)
            run = subprocess.run([program], capture_output=True, text=True, check=True, timeout=20,
                                 env=dict(os.environ, XU_DEBUG_FREE="1"))
            batch = ["10", "20", "0", "-21", "11", "42", "6", "30"]
            if run.stdout.splitlines() != batch * 2 + ["77"] + batch:
                raise AssertionError(run.stdout)
    print("single-word spawn, stack reuse, and owned argument fallbacks passed")


if __name__ == "__main__":
    main()
