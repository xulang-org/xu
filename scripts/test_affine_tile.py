#!/usr/bin/env python3
"""Build and execute the typed affine tile regression with a candidate compiler."""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import tempfile


GRID = """fn grid() int {
    $a := [323]int{}
    for i in 0:17 {
        for j in 0:19 {
            a[j * 17 + i] = i
        }
    }
    $sum := 0
    for k in 0:323 { sum += a[k] * (k + 1) }
    << sum
}
"""
ALIGNED = GRID.replace("grid()", "aligned()").replace("323", "256").replace("17", "16").replace("19", "16")
ALIGNED = ALIGNED.replace("= i\n", "= j\n")
DEPENDENT = GRID.replace("grid()", "dependent()").replace(
    "= i\n", "= a[(j * 17 + i + 1) % 323] + 1\n")
TRANSPOSE = """
fn transpose() int {
    $src := [323]int{}
    $dst := [323]int{}
    for k in 0:323 { src[k] = 3 * k - 17 }
    for i in 0:17 {
        for j in 0:19 { dst[j * 17 + i] = src[i * 19 + j] }
    }
    $sum := 0
    for k in 0:323 { sum += dst[k] * (k + 1) }
    << sum
}

fn transpose_same() int {
    $data := [323]int{}
    for k in 0:323 { data[k] = 3 * k - 17 }
    for i in 0:17 {
        for j in 0:19 { data[j * 17 + i] = data[i * 19 + j] }
    }
    $sum := 0
    for k in 0:323 { sum += data[k] * (k + 1) }
    << sum
}

fn transpose_borrow(src &[323]int) int {
    $dst := [323]int{}
    for i in 0:17 {
        for j in 0:19 { dst[j * 17 + i] = src[i * 19 + j] }
    }
    << dst[1]
}

fn transpose_short() {
    src := [322]int{}
    $dst := [323]int{}
    for i in 0:17 {
        for j in 0:19 { dst[j * 17 + i] = src[i * 19 + j] }
    }
    println(dst[0])
}
"""
SOURCE = "@main\n#os\n" + GRID + ALIGNED + DEPENDENT + TRANSPOSE + """
fn view() int {
    $backing := []int{}
    for k in 0:324 { backing.push(0) }
    $a := backing[1:324]
    for i in 0:17 { for j in 0:19 { a[j * 17 + i] = i } }
    << a[322]
}
fn main() int {
    args := os.argv()
    if args.len > 1 { transpose_short() }
    println(grid())
    println(aligned())
    println(dependent())
    println(view())
    println(transpose())
    println(transpose_same())
    $src := [323]int{}
    src[19] = 13
    println(transpose_borrow(&src))
    << 0
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    compiler = parser.parse_args().compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        source = work / "grid.xu"
        source.write_text(SOURCE)
        for mode, tile, poll in [("baseline", "0", "0"), ("tile", "1", "0"),
                                 ("poll", "1", "1"), ("no-opt", "1", "0")]:
            env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                       XU_DUMP_MIR="_xu_main_", XU_AFFINE_TILE=tile, XU_TASK_POLL=poll)
            output = work / ("grid.exe" if os.name == "nt" else "grid")
            cmd = [str(compiler), "build", str(source), "-o", str(output)]
            if mode == "no-opt":
                cmd.append("--no-opt")
            built = subprocess.run(cmd, env=env, capture_output=True, text=True)
            if built.returncode:
                raise RuntimeError(built.stdout + built.stderr)
            candidates = {"grid", "aligned", "transpose"}
            for label in ("grid", "aligned", "dependent", "view", "transpose",
                          "transpose_same", "transpose_borrow", "transpose_short"):
                body = built.stdout.split("fn _xu_main_" + label + " ", 1)[1].split("\nfn ", 1)[0]
                assert ("(.tile_i)" in body) == (mode == "tile" and label in candidates), (mode, label)
            if platform.system() == "Darwin":
                subprocess.run(["codesign", "-fs", "-", str(output)], check=True, capture_output=True)
            result = subprocess.check_output([str(output)], text=True)
            assert result.splitlines() == ["426360", "333760", "55556", "16",
                                           "25319970", "13786944", "13"], (mode, result)
            panic = subprocess.run([str(output), "short"], capture_output=True, text=True)
            assert panic.returncode != 0 and "index out of bounds" in panic.stderr, (mode, panic)
            print(mode, "passed")


if __name__ == "__main__":
    main()
