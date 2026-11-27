#!/usr/bin/env python3
"""Verify ARM64 NEON / x64 SSE2 Q4_0 dequantize+dot, AXPY, and in-place VADD stubs and lowering."""

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
from test_tensor_fusion import PRELUDE, build, f32, run, xu_f32s


LENGTHS = [0, 1, 2, 3, 4, 5, 7, 8, 15, 16, 17, 64, 129]
BLOCK_COUNTS = [0, 1, 2, 3, 7, 16, 32, 64]
PANIC_CASES = (
    "q4_short_qs",
    "q4_short_scales",
    "q4_short_x",
    "q4_neg_qoff",
    "q4_neg_soff",
    "q4_neg_xoff",
    "q4_overflow_nb",
    "axpy_short_dst",
    "axpy_short_src",
    "axpy_neg_off",
    "axpy_overflow_n",
    "vadd_short_dst",
    "vadd_overflow_off",
)
STUBS_STRICT = (
    "___xu_tensor_axpy_f32",
    "___xu_tensor_vadd_inplace_f32",
    "___xu_tensor_dot_q4_0_f32",
)
STUBS_FAST = (
    "___xu_tensor_axpy_fma_f32",
    "___xu_tensor_vadd_inplace_f32",
    "___xu_tensor_dot_q4_0_fast_f32",
)


def bits_to_f32(b):
    return struct.unpack("<f", struct.pack("<I", int(b)))[0]


def test_source():
    n_max = 150
    vals_d = [f32(((i * 19) % 29 - 14) * 0.125) for i in range(n_max)]
    vals_s = [f32(((i * 13) % 23 - 11) * 0.0625 + (2**-24 if i % 5 == 0 else 0.0)) for i in range(n_max)]
    lengths_literal = ", ".join(str(v) for v in LENGTHS)
    nb_literal = ", ".join(str(v) for v in BLOCK_COUNTS)

    tagged_check = ""
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        tagged_check = """    if verify_axpy_tagged_and_overlap(0x0400000000000000) != 0 { << 10 }
"""
    else:
        tagged_check = """    if verify_axpy_tagged_and_overlap(0) != 0 { << 10 }
"""

    return PRELUDE + f"""
fn kernel_axpy_addassign(n int, off_d int, off_s int, alpha f32, dst $&[]f32, src &[]f32) {{
    for i in 0:n {{ dst[off_d + i] += alpha * src[off_s + i] }}
}}

fn kernel_axpy_assign(n int, off_d int, off_s int, alpha f32, dst $&[]f32, src &[]f32) {{
    for i in 0:n {{ dst[off_d + i] = dst[off_d + i] + src[off_s + i] * alpha }}
}}

fn kernel_axpy_self_alias(n int, alpha f32, buf $&[]f32) {{
    for i in 0:n {{ buf[i] += alpha * buf[i] }}
}}

fn kernel_axpy_overlap(n int, alpha f32, buf $&[]f32) {{
    for i in 0:n {{ buf[1 + i] += alpha * buf[i] }}
}}

fn kernel_vadd_addassign(n int, off_d int, off_s int, dst $&[]f32, src &[]f32) {{
    for i in 0:n {{ dst[off_d + i] += src[off_s + i] }}
}}

fn kernel_vadd_assign(n int, off_d int, off_s int, dst $&[]f32, src &[]f32) {{
    for i in 0:n {{ dst[off_d + i] = src[off_s + i] + dst[off_d + i] }}
}}

fn kernel_vadd_self_alias(n int, buf $&[]f32) {{
    for i in 0:n {{ buf[i] += buf[i] }}
}}

fn kernel_vadd_overlap(n int, buf $&[]f32) {{
    for i in 0:n {{ buf[1 + i] += buf[i] }}
}}

fn kernel_vadd3_neg(n int, a &[]f32, b &[]f32, c $&[]f32) {{
    for i in 0:n {{ c[i] = a[i] + b[i] }}
}}

fn kernel_dot_q4_0(n_blocks int, q_off int, s_off int, x_off int, seed_bits int, qs &[]u8, scales &[]f32, x &[]f32) int {{
    $acc := from_bits(seed_bits)
    for b in 0:n_blocks {{
        $bsum := f32(0)
        q_base := q_off + b * 16
        x_base := x_off + b * 32
        for j in 0:16 {{
            bv := int(qs[q_base + j])
            q0 := (bv & 15) - 8
            q1 := (bv >> 4) - 8
            bsum += f32(q0) * x[x_base + j] + f32(q1) * x[x_base + 16 + j]
        }}
        acc += bsum * scales[s_off + b]
    }}
    << bits(acc)
}}

fn kernel_dot_q4_0_zero_off(n_blocks int, qs &[]u8, scales &[]f32, x &[]f32) int {{
    $acc := f32(0)
    for b in 0:n_blocks {{
        $bsum := f32(0)
        q_base := b * 16
        x_base := b * 32
        for j in 0:16 {{
            bv := int(qs[q_base + j])
            q0 := (bv & 15) - 8
            q1 := ((bv >> 4) & 15) - 8
            bsum += f32(q0) * x[x_base + j] + f32(q1) * x[x_base + 16 + j]
        }}
        acc += scales[b] * bsum
    }}
    << bits(acc)
}}

fn verify_axpy_tagged_and_overlap(tag int) int {{
    $buf1 := []f32{{}}
    $buf2 := []f32{{}}
    for i in 0:16 {{
        buf1.push(f32(f64(i + 1) * 0.5))
        buf2.push(f32(f64(i + 1) * 0.5))
    }}
    kernel_axpy_overlap(12, f32(0.25), $&buf1)
    // Scalar ground truth
    for i in 0:12 {{ buf2[1 + i] = buf2[1 + i] + f32(0.25) * buf2[i] }}
    for i in 0:16 {{
        if bits(buf1[i]) != bits(buf2[i]) {{ << 1 }}
    }}

    $vbuf1 := []f32{{}}
    $vbuf2 := []f32{{}}
    for i in 0:16 {{
        vbuf1.push(f32(f64(i + 1) * 0.5))
        vbuf2.push(f32(f64(i + 1) * 0.5))
    }}
    kernel_vadd_overlap(12, $&vbuf1)
    for i in 0:12 {{ vbuf2[1 + i] = vbuf2[1 + i] + vbuf2[i] }}
    for i in 0:16 {{
        if bits(vbuf1[i]) != bits(vbuf2[i]) {{ << 2 }}
    }}

    if tag != 0 {{
        $d := [f32(1), f32(2), f32(3), f32(4), f32(5), f32(6)]
        s := [f32(10), f32(20), f32(30), f32(40), f32(50), f32(60)]
        $ref_d := [f32(1), f32(2), f32(3), f32(4), f32(5), f32(6)]
        kernel_axpy_addassign(6, 0, 0, f32(0.5), $&ref_d, &s)
        unsafe {{
            dp := ($&d) as *raw int
            saved := *dp
            *dp = saved | tag
            kernel_axpy_addassign(6, 0, 0, f32(0.5), $&d, &s)
            *dp = saved
        }}
        for i in 0:6 {{
            if bits(d[i]) != bits(ref_d[i]) {{ << 3 }}
        }}
    }}
    << 0
}}

fn trigger_panic(which string) {{
    $qs := []u8{{}}
    for i in 0:32 {{ qs.push(u8(i * 17)) }}
    $scales := [f32(0.25), f32(0.5)]
    $qx := []f32{{}}
    for i in 0:64 {{ qx.push(f32(f64(i % 7) * 0.125)) }}
    $nb := 2
    $qo := 0
    $so := 0
    $xo := 0
    if which == "q4_short_qs" {{
        $bad_qs := []u8{{}}
        for i in 0:31 {{ bad_qs.push(u8(i)) }}
        println(kernel_dot_q4_0(2, 0, 0, 0, 0, &bad_qs, &scales, &qx))
        <<
    }}
    if which == "q4_short_scales" {{
        bad_sc := [f32(0.5)]
        println(kernel_dot_q4_0(2, 0, 0, 0, 0, &qs, &bad_sc, &qx))
        <<
    }}
    if which == "q4_short_x" {{
        $bad_x := []f32{{}}
        for i in 0:63 {{ bad_x.push(f32(1)) }}
        println(kernel_dot_q4_0(2, 0, 0, 0, 0, &qs, &scales, &bad_x))
        <<
    }}
    if which == "q4_neg_qoff" {{
        println(kernel_dot_q4_0(1, -1, 0, 0, 0, &qs, &scales, &qx))
        <<
    }}
    if which == "q4_neg_soff" {{
        println(kernel_dot_q4_0(1, 0, -1, 0, 0, &qs, &scales, &qx))
        <<
    }}
    if which == "q4_neg_xoff" {{
        println(kernel_dot_q4_0(1, 0, 0, -1, 0, &qs, &scales, &qx))
        <<
    }}
    if which == "q4_overflow_nb" {{
        println(kernel_dot_q4_0(0x4000000000000001, 0, 0, 0, 0, &qs, &scales, &qx))
        <<
    }}

    $dst := [f32(1), f32(2), f32(3), f32(4), f32(5)]
    src := [f32(10), f32(20), f32(30), f32(40), f32(50)]
    if which == "axpy_short_dst" {{
        kernel_axpy_addassign(6, 0, 0, f32(0.5), $&dst, &src)
        <<
    }}
    if which == "axpy_short_src" {{
        $dst6 := [f32(1), f32(2), f32(3), f32(4), f32(5), f32(6)]
        kernel_axpy_addassign(6, 0, 0, f32(0.5), $&dst6, &src)
        <<
    }}
    if which == "axpy_neg_off" {{
        kernel_axpy_addassign(3, -1, 0, f32(0.5), $&dst, &src)
        <<
    }}
    if which == "axpy_overflow_n" {{
        kernel_axpy_addassign(0x4000000000000001, 0, 0, f32(0.5), $&dst, &src)
        <<
    }}
    if which == "vadd_short_dst" {{
        kernel_vadd_addassign(6, 0, 0, $&dst, &src)
        <<
    }}
    if which == "vadd_overflow_off" {{
        kernel_vadd_addassign(2, 0x4000000000000001, 0, $&dst, &src)
        <<
    }}
}}

fn hash_f32(v &[]f32) int {{
    $h := 0
    for i in 0:v.len {{ h = h ^ (bits(v[i]) + i * 131) }}
    << h
}}

fn main() int {{
    args := os.argv()
    if args.len > 1 {{
        trigger_panic(args[1])
        << 3
    }}

    base_d := [{xu_f32s(vals_d)}]
    src := [{xu_f32s(vals_s)}]
    lengths := [{lengths_literal}]
    for li in 0:lengths.len {{
        n := lengths[li]
        $d1 := []f32{{}}
        $d2 := []f32{{}}
        $v1 := []f32{{}}
        $v2 := []f32{{}}
        $v3 := []f32{{}}
        for i in 0:base_d.len {{
            d1.push(base_d[i])
            d2.push(base_d[i])
            v1.push(base_d[i])
            v2.push(base_d[i])
            v3.push(f32(0))
        }}
        kernel_axpy_addassign(n, 0, 0, f32(0.375), $&d1, &src)
        kernel_axpy_assign(n, 5, 3, f32(-0.625), $&d2, &src)
        kernel_vadd_addassign(n, 0, 0, $&v1, &src)
        kernel_vadd_assign(n, 4, 2, $&v2, &src)
        kernel_vadd3_neg(n, &base_d, &src, $&v3)
        println("vec:" + str(n) + ":" + str(hash_f32(&d1)) + ":" + str(hash_f32(&d2)) + ":" + str(hash_f32(&v1)) + ":" + str(hash_f32(&v2)) + ":" + str(hash_f32(&v3)))
    }}

    // Self-alias dst == src
    $sa := []f32{{}}
    $sv := []f32{{}}
    for i in 0:37 {{
        sa.push(base_d[i])
        sv.push(base_d[i])
    }}
    kernel_axpy_self_alias(37, f32(0.25), $&sa)
    kernel_vadd_self_alias(37, $&sv)
    println("self_alias:" + str(hash_f32(&sa)) + ":" + str(hash_f32(&sv)))

    {tagged_check}

    // Q4_0 across block counts, arbitrary offsets, extreme nibbles, and IEEE-754 edges.
    max_nb := 68
    $qs := []u8{{}}
    extremes := [0x00, 0xFF, 0x88, 0x0F, 0xF0, 0x78, 0x87, 0x19]
    for i in 0:max_nb * 16 {{
        if i < 16 {{
            qs.push(u8(extremes[i % 8]))
        }} else {{
            qs.push(u8((i * 73 + 19) & 255))
        }}
    }}
    $scales := []f32{{}}
    for b in 0:max_nb {{
        if b == 0 {{
            scales.push(f32(0.5))
        }} else {{
            scales.push(f32(f64(((b * 7) % 19) - 9) * 0.03125))
        }}
    }}
    $qx := []f32{{}}
    for i in 0:max_nb * 32 {{
        $tiny := 0.0
        if i % 9 == 0 {{ tiny = 0.000000059604644775390625 }}
        qx.push(f32(f64(((i * 11) % 23) - 11) * 0.0625 + tiny))
    }}

    nb_list := [{nb_literal}]
    for bi in 0:nb_list.len {{
        nb := nb_list[bi]
        r0 := kernel_dot_q4_0(nb, 0, 0, 0, 0, &qs, &scales, &qx)
        r1 := kernel_dot_q4_0(nb, 32, 2, 64, 0x80000000, &qs, &scales, &qx)
        r2 := kernel_dot_q4_0_zero_off(nb, &qs, &scales, &qx)
        println("q4:" + str(nb) + ":" + str(r0) + ":" + str(r1) + ":" + str(r2))
    }}
    println("q4_neg0:" + str(kernel_dot_q4_0(0, 0, 0, 0, 0x80000000, &qs, &scales, &qx)))
    println("q4_negnb:" + str(kernel_dot_q4_0(-2, 0, 0, 0, 0x80000000, &qs, &scales, &qx)))

    // IEEE-754 edge values in Q4_0 inputs/scales
    $eqs := []u8{{}}
    for _ in 0:32 {{ eqs.push(u8(0x99)) }} // (+1, +1)
    esc := [from_bits(0x00000001), f32(1.0)]
    $ex := []f32{{}}
    for _ in 0:64 {{ ex.push(f32(1.0)) }}
    ex[5] = from_bits(0x80000000)
    ex[35] = from_bits(0x7fc00000)
    println("q4_edge1:" + str(kernel_dot_q4_0(1, 0, 0, 0, 0x80000000, &eqs, &esc, &ex)))
    println("q4_edge2:" + str(kernel_dot_q4_0(2, 0, 0, 0, 0, &eqs, &esc, &ex)))
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
            if sym != "___xu_tensor_vadd_inplace_f32":
                assert re.search(r"\bfmla\.4s\b", body), sym
            else:
                assert re.search(r"\bfadd\.4s\b", body), sym
            if "q4_0" in sym:
                assert "sshll" in body and "scvtf.4s" in body, sym
        else:
            assert re.search(r"\bf(?:mul|add)\.4s\b", body), sym
            assert not re.search(r"\bf(?:n?madd|n?msub|mla|mls)\b", body), sym


def check_x64_cross(compiler, env, src, work):
    x64_exe = work / "quant-x64"
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
            assert "addps" in body, sym
            if "q4_0" in sym:
                assert "punpcklbw" in body and "cvtdq2ps" in body and "mulps" in body, sym
                # Critical regression check: x += 128 must use imm32 (0x80), never sign-extended imm8 (-0x80)!
                assert re.search(r"\badd[ql]?\s+\$0x80,\s*%rdx\b", body), f"Expected add $0x80, %rdx in {sym}:\n{body}"
                assert "$-0x80" not in body, f"Sign-extended -0x80 bug in {sym}"
            for forbidden in ("xmm6", "xmm7", "xmm8", "xmm9", "xmm10", "xmm11", "xmm12", "xmm13", "xmm14", "xmm15",
                              "%rbx", "%rbp", "%r12", "%r13", "%r14"):
                assert forbidden not in body, (sym, forbidden)
    else:
        for sym in STUBS_STRICT + STUBS_FAST:
            assert sym.encode("ascii") in raw, f"Missing x64 stub symbol {sym}"
        print("macos-x64 Mach-O header & stub symbols verified (otool disassembly skipped on non-macOS host)")


def benchmark_source():
    return PRELUDE.replace("#os", "#os\n#time", 1) + """
fn bench_axpy(n int, alpha f32, dst $&[]f32, src &[]f32) {
    for i in 0:n { dst[i] += alpha * src[i] }
}

fn bench_vadd(n int, dst $&[]f32, src &[]f32) {
    for i in 0:n { dst[i] += src[i] }
}

fn bench_gemv_q4_0(rows int, n_blocks int, qs &[]u8, scales &[]f32, x &[]f32, out $&[]f32) {
    for r in 0:rows {
        s_off := r * n_blocks
        q_off := s_off * 16
        $acc := f32(0)
        for b in 0:n_blocks {
            $bsum := f32(0)
            q_base := q_off + b * 16
            x_base := b * 32
            for j in 0:16 {
                bv := int(qs[q_base + j])
                q0 := (bv & 15) - 8
                q1 := (bv >> 4) - 8
                bsum += f32(q0) * x[x_base + j] + f32(q1) * x[x_base + 16 + j]
            }
            acc += bsum * scales[s_off + b]
        }
        out[r] = acc
    }
}

fn main() int {
    args := os.argv()
    kind := args[1]
    if kind == "gemv_q4_0" {
        rows := 512
        n_blocks := 16
        cols := 512
        $qs := []u8{}
        $scales := []f32{}
        $x := []f32{}
        $out := []f32{}
        for i in 0:rows * n_blocks * 16 { qs.push(u8((i * 73 + 11) & 255)) }
        for i in 0:rows * n_blocks { scales.push(f32(f64((i % 13) - 6) * 0.03125)) }
        for i in 0:cols { x.push(f32(f64((i % 11) - 5) * 0.0625)) }
        for _ in 0:rows { out.push(f32(0)) }
        $elapsed := [200]int{}
        $checksum := 0
        for sample in 0:240 {
            start := time.now()
            bench_gemv_q4_0(rows, n_blocks, &qs, &scales, &x, $&out)
            dur := time.since(start)
            if sample >= 40 { elapsed[sample - 40] = dur }
            checksum += bits(out[sample % rows])
        }
        println(checksum)
        for i in 0:200 { println(elapsed[i]) }
        << 0
    }
    n := 4096
    $dst := []f32{}
    $src := []f32{}
    for i in 0:n {
        dst.push(f32(f64((i % 11) - 5) * 0.125))
        src.push(f32(f64((i % 7) + 1) * 0.015625))
    }
    alpha := f32(0.0625)
    $elapsed := [1000]int{}
    $checksum := 0
    for sample in 0:1200 {
        start := time.now()
        if kind == "axpy" {
            bench_axpy(n, alpha, $&dst, &src)
        } else {
            bench_vadd(n, $&dst, &src)
        }
        dur := time.since(start)
        if sample >= 200 { elapsed[sample - 200] = dur }
        checksum += bits(dst[sample % n])
    }
    println(checksum)
    for i in 0:1000 { println(elapsed[i]) }
    << 0
}
"""


def benchmark(compiler, env, work):
    source = work / "bench_quant.xu"
    source.write_text(benchmark_source())
    cases = (("axpy", 4096), ("vadd", 4096), ("gemv_q4_0", 512))
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
            print(f"{kind:10} N={size:4} {mode:11} n={len(samples)} P50={p50} ns P99={p99} ns")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        work = Path(td)
        src = work / "tensor_quant.xu"
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
                baseline_mir["vadd3_neg"] = functions["kernel_vadd3_neg"]
            elif mode == "strict":
                assert "call __xu_tensor_axpy_f32(" in functions["kernel_axpy_addassign"]
                assert "call __xu_tensor_axpy_f32(" in functions["kernel_axpy_assign"]
                assert "call __xu_tensor_axpy_f32(" in functions["kernel_axpy_self_alias"]
                assert "call __xu_tensor_vadd_inplace_f32(" in functions["kernel_vadd_addassign"]
                assert "call __xu_tensor_vadd_inplace_f32(" in functions["kernel_vadd_assign"]
                assert "call __xu_tensor_vadd_inplace_f32(" in functions["kernel_vadd_self_alias"]
                assert "call __xu_tensor_dot_q4_0_f32(" in functions["kernel_dot_q4_0"]
                assert "call __xu_tensor_dot_q4_0_f32(" in functions["kernel_dot_q4_0_zero_off"]
                assert functions["kernel_vadd3_neg"] == baseline_mir["vadd3_neg"]
                check_arm64_disassembly(exe, fast_math=False)
            elif mode == "fast-math":
                assert "call __xu_tensor_axpy_fma_f32(" in functions["kernel_axpy_addassign"]
                assert "call __xu_tensor_vadd_inplace_f32(" in functions["kernel_vadd_addassign"]
                assert "call __xu_tensor_dot_q4_0_fast_f32(" in functions["kernel_dot_q4_0"]
                check_arm64_disassembly(exe, fast_math=True)

            out = run([exe]).splitlines()
            if mode == "baseline":
                baseline_out = out
            elif mode != "fast-math":
                assert out == baseline_out, (mode, "bit-exact mismatch vs baseline")
            else:
                assert "q4_neg0:2147483648" in out and "q4_negnb:2147483648" in out
                q4_base = [l for l in baseline_out if l.startswith("q4:")]
                q4_fast = [l for l in out if l.startswith("q4:")]
                assert len(q4_base) == len(q4_fast)
                for lb, lf in zip(q4_base, q4_fast):
                    pb = lb.split(":")
                    pf = lf.split(":")
                    assert pb[1] == pf[1]
                    for idx in (2, 3, 4):
                        assert abs(bits_to_f32(pb[idx]) - bits_to_f32(pf[idx])) < 1e-4, (lb, lf)

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
        print("macos-x64 cross-compile and SSE2 Q4_0/AXPY/VADD disassembly passed")
        if args.benchmark:
            benchmark(compiler, env, work)


if __name__ == "__main__":
    main()
