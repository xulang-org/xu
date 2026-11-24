#!/usr/bin/env python3
"""Check frame-object load reuse and alias invalidation using a built Xu compiler."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory


PROGRAM = """@main
#os

struct Pair {
    first int
    second int
}

fn fill(p $&Pair, n int) {
    if n > 0 { p.first = n }
}

fn frame_separate(x int, y int) int {
    $a := Pair{first: x, second: y}
    $b := Pair{first: y, second: x}
    fill($&a, x + 20)
    before := a.first
    fill($&b, y + 50)
    << before + a.first + b.first
}

fn frame_overlap(x int, y int) int {
    $a := Pair{first: x, second: y}
    fill($&a, x + 20)
    before := a.first
    fill($&a, y + 50)
    << before + a.first
}

fn scratch_only(n int) int {
    $scratch := Pair{first: n + 1, second: n + 10}
    fill($&scratch, n)
    << scratch.first + scratch.second
}

fn fill_with_scratch(p $&Pair, n int) int {
    $scratch := Pair{first: n + 1, second: n + 10}
    fill($&scratch, n)
    fill(p, scratch.first)
    << scratch.second
}

fn frame_call_readonly(p &Pair, n int) int {
    before := p.first
    result := scratch_only(n)
    << before + p.first + result
}

fn frame_call_separate(p $&Pair, n int) int {
    before := p.second
    result := fill_with_scratch(p, n)
    << before + p.second + result
}

fn frame_call_same(p $&Pair, n int) int {
    before := p.first
    result := fill_with_scratch(p, n)
    << before + p.first + result
}

fn mutate_view(s $&[]int, i int, v int) {
    $scratch := Pair{first: v, second: v + 1}
    fill($&scratch, v)
    s[i] = scratch.first
}

fn frame_call_view(s $&[]int, i int, v int) int {
    before := s[0]
    mutate_view(s, i, v)
    << before + s[0]
}

fn main() {
    args := os.argv()
    x := args.len
    println(frame_separate(x, x + 1))
    println(frame_overlap(x, x + 1))
    $p := Pair{first: 13, second: 17}
    println(frame_call_readonly(&p, x))
    println(frame_call_separate($&p, x + 1))
    println(frame_call_same($&p, x + 20))
    $backing := [11, 22, 33]
    $view := backing[1:3]
    println(frame_call_view($&view, x % 2, x + 30))
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiler", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory() as work:
        source = Path(work) / "case.xu"
        source.write_text(PROGRAM)
        for mode, options in (("isolated", []), ("product", []), ("no-opt", ["--no-opt"])):
            binary = Path(work) / mode
            env = os.environ.copy()
            if mode == "isolated":
                # Keep loads and summarized calls visible to the GVN pass.
                env.update(XU_NO_SROA="1", XU_NO_INLINE="1", XU_DUMP_MIR="_xu_main_frame_")
            run = subprocess.run([args.compiler.resolve(), "build", *options, source, "-o", binary],
                                 env=env, check=True, stdout=subprocess.PIPE, text=True)
            if mode == "isolated":
                functions = re.split(r"(?m)^fn _xu_main_frame_", run.stdout)[1:]
                bodies = {function.split()[0]: function for function in functions}
                for name, expected in {"separate": 2, "overlap": 2}.items():
                    # Only field reads after initialization and the first call.
                    body = bodies[name].split("call _xu_main_fill", 1)[1]
                    assert body.count(" = load8 [") == expected, body
                for name, expected in {"call_readonly": 1, "call_separate": 1, "call_same": 2}.items():
                    assert bodies[name].count(" = load8 [") == expected, bodies[name]
                # Both element loads remain around the unknown backing-buffer write.
                view = bodies["call_view"]
                assert len(re.findall(r" = load8 \[t[0-9]+\+0\]$", view, re.M)) == 2, view
            if sys.platform == "darwin":
                subprocess.run(["codesign", "-fs", "-", binary], check=True)
            for argv, output in [
                ((), "94\n73\n38\n46\n54\n44\n"),
                (("a",), "97\n75\n40\n47\n57\n54\n"),
                (("a", "b"), "100\n77\n42\n48\n60\n44\n"),
            ]:
                actual = subprocess.check_output([binary, *argv], text=True)
                assert actual == output, (mode, argv, actual)
    print("Frame range MIR and native execution checks passed")


if __name__ == "__main__":
    main()
