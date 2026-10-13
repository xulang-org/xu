"""Algebraic simplification and reassociation in SSA form (Go rewrite & LLVM InstCombine aligned)."""
from pathlib import Path
import os, subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get('XU', ROOT / 'bin/xu')).resolve()

PROGRAM = '''@main

fn check_algebraic_identities(x int, y int) int {
    // Identities & Annihilators
    a1 := x ^ x       // 0
    a2 := x & 0       // 0
    a3 := x & -1      // x
    a4 := x | 0       // x
    a5 := x | -1      // -1
    a6 := x + 0       // x
    a7 := x - 0       // x
    a8 := x - x       // 0
    a9 := x * 0       // 0
    a10 := x * 1      // x
    a11 := x << 0     // x
    a12 := x >> 0     // x
    a13 := 0 << y     // 0
    a14 := 0 >> y     // 0

    // Comparisons
    mut c1 := 0
    if x == x { c1 = 1 }
    mut c2 := 0
    if x != x { c2 = 1 }
    mut c3 := 0
    if x <= x { c3 = 1 }
    mut c4 := 0
    if x >= x { c4 = 1 }

    << a1 + a2 + a3 + a4 + a5 + a6 + a7 + a8 + a9 + a10 + a11 + a12 + a13 + a14 + c1 + c2 + c3 + c4
}

fn check_associative_reassoc(x int, y int) int {
    // Nested bitwise AND masks
    m1 := (x & 255) & 255          // x & 255
    m2 := (x & 65280) & 255        // 0
    m3 := (x & 15) & 255           // x & 15

    // Nested XOR constant cancellation and folding
    x1 := (x ^ 123) ^ 123          // x
    x2 := (x ^ 10) ^ 20            // x ^ 30

    // XOR cancellation with variables: (x ^ y) ^ x -> y
    xy := x ^ y
    x3 := xy ^ x                   // y
    x4 := xy ^ y                   // x

    // Nested bitwise OR
    o1 := (x | 255) | 255          // x | 255
    o2 := (x | 15) | 240           // x | 255

    // Nested addition
    ad1 := (x + 10) + 20           // x + 30
    ad2 := (x + 100) + (0 - 100)   // x

    // Nested shifts
    s1 := (x << 2) << 3            // x << 5
    s2 := (x >> 2) >> 3            // x >> 5

    << m1 + m2 + m3 + x1 + x2 + x3 + x4 + o1 + o2 + ad1 + ad2 + s1 + s2
}

fn golden_identities(x int, y int) int {
    a3 := x
    a4 := x
    a5 := -1
    a6 := x
    a7 := x
    a10 := x
    a11 := x
    a12 := x
    c1 := 1
    c3 := 1
    c4 := 1
    << a3 + a4 + a5 + a6 + a7 + a10 + a11 + a12 + c1 + c3 + c4
}

fn golden_reassoc(x int, y int) int {
    m1 := x & 255
    m2 := 0
    m3 := x & 15
    x1 := x
    x2 := x ^ 30
    x3 := y
    x4 := x
    o1 := x | 255
    o2 := x | 255
    ad1 := x + 30
    ad2 := x
    s1 := x << 5
    s2 := x >> 5
    << m1 + m2 + m3 + x1 + x2 + x3 + x4 + o1 + o2 + ad1 + ad2 + s1 + s2
}

fn main() int {
    for x in -50:50 {
        for y in 1:10 {
            v1 := check_algebraic_identities(x, y)
            g1 := golden_identities(x, y)
            if v1 != g1 {
                println("Mismatch in check_algebraic_identities")
                assert(false)
            }

            v2 := check_associative_reassoc(x, y)
            g2 := golden_reassoc(x, y)
            if v2 != g2 {
                println("Mismatch in check_associative_reassoc")
                assert(false)
            }
        }
    }
    println("SSA algebraic PASS")
    << 0
}
'''

@pytest.mark.parametrize('flags', [('-O0',), (), ('-O3',)])
def test_ssa_algebraic_execution(tmp_path, flags):
    src = tmp_path / 'main.xu'
    binary = tmp_path / 'program'
    src.write_text(PROGRAM)
    p = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), '--cwd', str(tmp_path), str(XU),
                        'build', *flags, str(src), '-o', str(binary)],
                       cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, p.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, 'SSA algebraic PASS\n', '')
