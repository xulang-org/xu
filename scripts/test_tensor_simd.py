#!/usr/bin/env python3
"""Verify ARM64 NEON / x64 SSE tensor SIMD stubs, dot/GEMV lowering, and fast-math mode."""

import argparse
import os
import platform
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

from test_tensor_dynamic import mir_functions
from test_tensor_fusion import PRELUDE, build, f32, float_bits, run, xu_f32s


LENGTHS = list(range(0, 20)) + [127, 128, 129, 255, 256, 257]
PANIC_CASES = ("negative_off", "overflow_off", "short_a", "short_b", "short_fixed", "overflow_n")
STUBS_STRICT = (
    "___xu_tensor_mul_add_f32",
    "___xu_tensor_add_sqsum_f32",
    "___xu_tensor_norm_f32",
    "___xu_tensor_dot_f32",
)
STUBS_FAST = (
    "___xu_tensor_mul_add_fma_f32",
    "___xu_tensor_add_sqsum_fast_f32",
    "___xu_tensor_dot_fast_f32",
)


def test_source():
    n_max = 270
    vals_a = [f32(((i * 17) % 29 - 14) * 0.125 + (2**-24 if i % 7 == 0 else 0.0)) for i in range(n_max)]
    vals_b = [f32(((i * 13) % 23 - 11) * 0.25) for i in range(n_max)]
    vals_c = [f32(((i * 7) % 19 - 9) * 0.0625) for i in range(n_max)]
    lengths_literal = ", ".join(str(v) for v in LENGTHS)
    return PRELUDE + f"""
fn kernel_mul_add(n int, x &[]f32, scale &[]f32, bias &[]f32, out $&[]f32) {{
    $tmp := [270]f32{{}}
    for i in 0:n {{ tmp[i] = x[i] * scale[i] }}
    for j in 0:n {{ out[j] = tmp[j] + bias[j] }}
}}

fn kernel_rms_reuse(n int, x &[]f32, skip &[]f32, weight &[]f32, out $&[]f32) int {{
    $sum := f32(0)
    $tmp := [270]f32{{}}
    for i in 0:n {{ tmp[i] = x[i] + skip[i] }}
    for j in 0:n {{ sum += tmp[j] * tmp[j] }}
    inv := f32(1.0 / math.sqrt(f64(sum) / f64(n) + 0.00001))
    for k in 0:n {{ out[k] = (tmp[k] * inv) * weight[k] }}
    << bits(sum)
}}

fn kernel_dot(n int, off_a int, off_b int, seed_bits int, a &[]f32, b &[]f32) int {{
    $sum := from_bits(seed_bits)
    for i in 0:n {{ sum += a[off_a + i] * b[i + off_b] }}
    << bits(sum)
}}

fn kernel_dot_fixed(n int) int {{
    a := [5]f32{{f32(1.5), f32(-2.25), f32(3.0), f32(0.5), f32(-4.0)}}
    b := [5]f32{{f32(2.0), f32(4.0), f32(-1.0), f32(8.0), f32(0.25)}}
    $sum := f32(0)
    for i in 0:n {{ sum += a[i] * b[i] }}
    << bits(sum)
}}

fn kernel_gemv(rows int, cols int, w &[]f32, x &[]f32, out $&[]f32) {{
    for r in 0:rows {{
        row_off := r * cols
        $acc := f32(0)
        for c in 0:cols {{ acc += w[row_off + c] * x[c] }}
        out[r] = acc
    }}
}}

fn kernel_self_square_neg(n int, x &[]f32) int {{
    $sum := f32(0)
    for i in 0:n {{ sum += x[i] * x[i] }}
    << bits(sum)
}}

fn trigger_panic(which string) {{
    $n := 5
    $off := 1
    $a := [f32(1), f32(2), f32(3), f32(4), f32(5), f32(6)]
    $b := [f32(1), f32(2), f32(3), f32(4), f32(5), f32(6)]
    if which == "negative_off" {{ off = -1 }}
    if which == "overflow_off" {{ off = 0x4000000000000001 }}
    if which == "overflow_n" {{
        n = 0x4000000000000001
        off = 0
    }}
    if which == "short_a" {{ n = 6 }}
    if which == "short_b" {{ off = 2 }}
    if which == "short_fixed" {{
        println(kernel_dot_fixed(6))
        <<
    }}
    println(kernel_dot(n, off, 0, 0, &a, &b))
}}

fn main() int {{
    args := os.argv()
    if args.len > 1 {{
        trigger_panic(args[1])
        << 3
    }}
    a := [{xu_f32s(vals_a)}]
    b := [{xu_f32s(vals_b)}]
    c := [{xu_f32s(vals_c)}]
    $out := []f32{{}}
    $out2 := []f32{{}}
    for _ in 0:270 {{
        out.push(f32(0))
        out2.push(f32(0))
    }}
    lengths := [{lengths_literal}]
    for li in 0:lengths.len {{
        n := lengths[li]
        kernel_mul_add(n, &a, &b, &c, $&out)
        s_rms := kernel_rms_reuse(n, &a, &b, &c, $&out2)
        d0 := kernel_dot(n, 0, 0, 0, &a, &b)
        d1 := kernel_dot(n, 3, 7, 0x80000000, &a, &b)
        $h1 := 0
        $h2 := 0
        for k in 0:n {{
            h1 = h1 ^ (bits(out[k]) + k * 131)
            h2 = h2 ^ (bits(out2[k]) + k * 257)
        }}
        println(str(n) + ":" + str(s_rms) + ":" + str(d0) + ":" + str(d1) + ":" + str(h1) + ":" + str(h2))
    }}
    println("fixed:" + str(kernel_dot_fixed(5)))
    println("neg0_dot:" + str(kernel_dot(0, 0, 0, 0x80000000, &a, &b)))
    println("neg0_neg:" + str(kernel_dot(-3, 0, 0, 0x80000000, &a, &b)))
    println("self_sq:" + str(kernel_self_square_neg(7, &a)))

    // Special IEEE-754 edge values: -0.0, subnormals, finite extremes, Inf, NaN.
    edge_a := [from_bits(0x80000000), from_bits(0x00000001), from_bits(0x3f800001), f32(1e20), f32(-1e20), f32(2.0), from_bits(0x7fc00000)]
    edge_b := [from_bits(0x00000000), from_bits(0x3f800000), from_bits(0x3f800001), f32(1.0), f32(1.0), from_bits(0x7f800000), f32(1.0)]
    for len in [1, 2, 3, 4, 5, 6, 7] {{
        println("edge:" + str(len) + ":" + str(kernel_dot(len, 0, 0, 0x80000000, &edge_a, &edge_b)))
    }}

    // Row-offset GEMV (16 x 37)
    $w := []f32{{}}
    for i in 0:16 * 37 {{ w.push(f32(f64((i * 11) % 31 - 15) * 0.0625)) }}
    $gx := []f32{{}}
    for i in 0:37 {{ gx.push(f32(f64((i * 7) % 19 - 9) * 0.125)) }}
    $gout := []f32{{}}
    for _ in 0:16 {{ gout.push(f32(0)) }}
    kernel_gemv(16, 37, &w, &gx, $&gout)
    for r in 0:16 {{ println("gemv:" + str(r) + ":" + str(bits(gout[r]))) }}
    << 0
}}
"""


def check_arm64_disassembly(exe, fast_math):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return
    asm = run(["otool", "-tV", exe])
    stubs = STUBS_FAST if fast_math else STUBS_STRICT
    for sym in stubs:
        m = re.search(rf"^{sym}:\n((?:[0-9a-f]+[^\n]*\n)+)", asm, re.M)
        assert m, f"Missing ARM64 stub {sym}"
        body = m[1]
        if fast_math:
            assert re.search(r"\bfmla\.4s\b", body), sym
        else:
            assert re.search(r"\bf(?:mul|add)\.4s\b", body), sym
            assert not re.search(r"\bf(?:n?madd|n?msub|mla|mls)\b", body), sym


def check_x64_cross(compiler, env, src, work):
    x64_exe = work / "simd-x64"
    build(compiler, dict(env, XU_TENSOR_FUSION="1", XU_TENSOR_FAST_MATH="1", XU_TASK_POLL="0"),
          src, x64_exe, ("--target", "macos-x64"))
    raw = x64_exe.read_bytes()
    magic, cputype = struct.unpack("<II", raw[:8])
    assert magic == 0xFEEDFACF and cputype == 0x01000007, (hex(magic), hex(cputype))
    if shutil.which("otool"):
        asm = run(["otool", "-tv", x64_exe])
        for sym in STUBS_STRICT + STUBS_FAST:
            m = re.search(rf"^{sym}:\n((?:[0-9a-f]+[^\n]*\n)+)", asm, re.M)
            assert m, f"Missing x64 stub {sym}"
            body = m[1]
            assert "movups" in body and "mulps" in body, sym
            for forbidden in ("xmm6", "xmm7", "xmm8", "xmm9", "xmm10", "xmm11", "xmm12", "xmm13", "xmm14", "xmm15",
                              "%rbx", "%rbp", "%r12", "%r13", "%r14"):
                assert forbidden not in body, (sym, forbidden)
    else:
        for sym in STUBS_STRICT + STUBS_FAST:
            assert sym.encode("ascii") in raw, f"Missing x64 stub symbol {sym}"
        print("macos-x64 Mach-O header & stub symbols verified (otool disassembly skipped on non-macOS host)")


def benchmark_source():
    return PRELUDE.replace("#os", "#os\n#time", 1) + """
fn bench_mul_add(n int, x &[]f32, s &[]f32, b &[]f32, out $&[]f32) {
    $tmp := [4096]f32{}
    for i in 0:n { tmp[i] = x[i] * s[i] }
    for j in 0:n { out[j] = tmp[j] + b[j] }
}

fn bench_rmsnorm(n int, x &[]f32, skip &[]f32, w &[]f32, out $&[]f32) {
    $sum := f32(0)
    $tmp := [4096]f32{}
    for i in 0:n { tmp[i] = x[i] + skip[i] }
    for j in 0:n { sum += tmp[j] * tmp[j] }
    inv := f32(1.0 / math.sqrt(f64(sum) / f64(n) + 0.00001))
    for k in 0:n { out[k] = (tmp[k] * inv) * w[k] }
}

fn bench_gemv(rows int, cols int, w &[]f32, x &[]f32, out $&[]f32) {
    for r in 0:rows {
        row_off := r * cols
        $acc := f32(0)
        for c in 0:cols { acc += w[row_off + c] * x[c] }
        out[r] = acc
    }
}

fn main() int {
    args := os.argv()
    kind := args[1]
    $n := 4096
    if kind == "rms128" { n = 128 }
    if kind == "gemv" {
        rows := 512
        cols := 512
        $w := []f32{}
        $x := []f32{}
        $out := []f32{}
        for i in 0:rows * cols { w.push(f32(f64((i % 13) - 6) * 0.03125)) }
        for i in 0:cols { x.push(f32(f64((i % 11) - 5) * 0.0625)) }
        for _ in 0:rows { out.push(f32(0)) }
        $elapsed := [200]int{}
        $checksum := 0
        for sample in 0:240 {
            start := time.now()
            bench_gemv(rows, cols, &w, &x, $&out)
            dur := time.since(start)
            if sample >= 40 { elapsed[sample - 40] = dur }
            checksum += bits(out[sample % rows])
        }
        println(checksum)
        for i in 0:200 { println(elapsed[i]) }
        << 0
    }
    $x := []f32{}
    $s := []f32{}
    $b := []f32{}
    $out := []f32{}
    for i in 0:n {
        x.push(f32(f64((i % 11) - 5) * 0.125))
        s.push(f32(f64((i % 7) + 1) * 0.25))
        b.push(f32(f64((i % 5) - 2) * 0.0625))
        out.push(f32(0))
    }
    $elapsed := [1000]int{}
    $checksum := 0
    for sample in 0:1200 {
        start := time.now()
        if kind == "mul_add" {
            bench_mul_add(n, &x, &s, &b, $&out)
        } else {
            bench_rmsnorm(n, &x, &s, &b, $&out)
        }
        dur := time.since(start)
        if sample >= 200 { elapsed[sample - 200] = dur }
        checksum += bits(out[sample % n])
    }
    println(checksum)
    for i in 0:1000 { println(elapsed[i]) }
    << 0
}
"""


def benchmark(compiler, env, work):
    source = work / "bench_simd.xu"
    source.write_text(benchmark_source())
    cases = (("mul_add", 4096), ("rms128", 128), ("rms4096", 4096), ("gemv", 512))
    strict_totals = {}
    for mode, fusion, fast in (
        ("baseline", "0", "0"),
        ("neon-strict", "1", "0"),
        ("neon-fast", "1", "1"),
    ):
        exe = work / ("bench-" + mode)
        build(compiler, dict(env, XU_TENSOR_FUSION=fusion, XU_TENSOR_FAST_MATH=fast, XU_TASK_POLL="0"),
              source, exe)
        for kind, size in cases:
            checksum, *samples = map(int, run([exe, kind]).splitlines())
            if mode == "baseline":
                strict_totals[kind] = checksum
            elif mode == "neon-strict":
                assert checksum == strict_totals[kind], (kind, checksum, strict_totals[kind])
            samples.sort()
            p50 = samples[len(samples) // 2 - 1]
            p99 = samples[len(samples) * 99 // 100 - 1]
            print(f"{kind:8} N={size:4} {mode:11} n={len(samples)} P50={p50} ns P99={p99} ns")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        src = work / "tensor_simd.xu"
        src.write_text(test_source())
        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_DUMP_MIR="_xu_main_kernel_", XU_KEEP_SYMBOLS="1")

        baseline_out = None
        baseline_mir = {}
        baseline_panics = {}
        for mode, fusion, fast, poll, flags in (
            ("baseline", "0", "0", "0", ()),
            ("strict", "1", "0", "0", ()),
            ("no-opt", "1", "0", "0", ("--no-opt",)),
            ("task-poll", "1", "0", "1", ()),
            ("fast-math", "1", "1", "0", ()),
        ):
            exe = work / mode
            mir = build(compiler, dict(env, XU_TENSOR_FUSION=fusion, XU_TENSOR_FAST_MATH=fast, XU_TASK_POLL=poll),
                        src, exe, flags)
            functions = mir_functions(mir)
            if mode == "baseline":
                baseline_mir["self_square_neg"] = functions["kernel_self_square_neg"]
            elif mode == "strict":
                assert "call __xu_tensor_mul_add_f32(" in functions["kernel_mul_add"]
                assert "call __xu_tensor_add_sqsum_f32(" in functions["kernel_rms_reuse"]
                assert "call __xu_tensor_norm_f32(" in functions["kernel_rms_reuse"]
                assert "call __xu_tensor_dot_f32(" in functions["kernel_dot"]
                assert "call __xu_tensor_dot_f32(" in functions["kernel_dot_fixed"]
                assert "call __xu_tensor_gemv4_f32(" in functions["kernel_gemv"]
                assert functions["kernel_self_square_neg"] == baseline_mir["self_square_neg"]
                check_arm64_disassembly(exe, fast_math=False)
            elif mode == "fast-math":
                assert "call __xu_tensor_mul_add_fma_f32(" in functions["kernel_mul_add"]
                assert "call __xu_tensor_add_sqsum_fast_f32(" in functions["kernel_rms_reuse"]
                assert "call __xu_tensor_norm_f32(" in functions["kernel_rms_reuse"]
                assert "call __xu_tensor_dot_fast_f32(" in functions["kernel_dot"]
                assert "call __xu_tensor_gemv4_fast_f32(" in functions["kernel_gemv"]
                check_arm64_disassembly(exe, fast_math=True)

            out = run([exe]).splitlines()
            if mode == "baseline":
                baseline_out = out
            elif mode != "fast-math":
                assert out == baseline_out, (mode, "bit-exact mismatch vs baseline")
            else:
                # Even in fast-math mode, n<=0 must preserve -0.0 and gemv must stay accurate.
                assert "neg0_dot:2147483648" in out and "neg0_neg:2147483648" in out
                import struct
                def bits_to_f(b): return struct.unpack("<f", struct.pack("<I", int(b)))[0]
                for row_b, row_f in zip(baseline_out[-16:], out[-16:]):
                    fb = bits_to_f(row_b.split(":")[-1])
                    ff = bits_to_f(row_f.split(":")[-1])
                    assert abs(fb - ff) < 1e-4, (row_b, row_f)

            for case in PANIC_CASES:
                res = subprocess.run([exe, case], text=True, capture_output=True, timeout=30)
                assert res.returncode not in (0, 3) and "index out of bounds" in res.stderr, (mode, case, res)
                outcome = (res.returncode, res.stdout, res.stderr)
                if mode == "baseline":
                    baseline_panics[case] = outcome
                else:
                    assert outcome == baseline_panics[case], (mode, case, outcome)
            print(mode, "passed")

        check_x64_cross(compiler, env, src, work)
        print("macos-x64 cross-compile and SSE stub disassembly passed")
        if args.benchmark:
            benchmark(compiler, env, work)


if __name__ == "__main__":
    main()
