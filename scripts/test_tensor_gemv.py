#!/usr/bin/env python3
"""Verify ARM64 SDOT / 4-row GEMV and x64 SSE2 PMADDWD / GEMV stubs and MIR lowering."""

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


ROW_COUNTS = [0, 1, 2, 3, 4, 5, 7, 8, 16, 17]
COL_COUNTS = [0, 1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 37, 64]
Q4_ROW_COUNTS = [0, 1, 2, 3, 4, 5, 7, 16, 17]
Q4_BLOCKS = [0, 1, 2, 3, 7, 16]

PANIC_CASES = (
    "f32_short_out",
    "f32_short_w",
    "f32_short_x",
    "f32_neg_off",
    "f32_overflow_rows",
    "q4q8_short_out",
    "q4q8_short_qs",
    "q4q8_short_ws",
    "q4q8_short_xq",
    "q4q8_short_xs",
    "q4q8_neg_blk",
    "dot_short_qs",
    "dot_short_xq",
    "dot_overflow_nb",
)

STUBS_STRICT = (
    "___xu_tensor_gemv4_f32",
    "___xu_tensor_dot_q4_0_q8_0_f32",
    "___xu_tensor_gemv4_q4_0_q8_0_f32",
)
STUBS_FAST = (
    "___xu_tensor_gemv4_fast_f32",
    "___xu_tensor_dot_q4_0_q8_0_fast_f32",
    "___xu_tensor_gemv4_q4_0_q8_0_fast_f32",
)


def bits_to_f32(b):
    return struct.unpack("<f", struct.pack("<I", int(b)))[0]


def test_source():
    rows_lit = ", ".join(str(v) for v in ROW_COUNTS)
    cols_lit = ", ".join(str(v) for v in COL_COUNTS)
    qrows_lit = ", ".join(str(v) for v in Q4_ROW_COUNTS)
    qblk_lit = ", ".join(str(v) for v in Q4_BLOCKS)
    tagged_call = (
        "if verify_overlap_and_tagged(0x0400000000000000) != 0 { << 10 }"
        if platform.system() == "Darwin" and platform.machine() == "arm64"
        else "if verify_overlap_and_tagged(0) != 0 { << 10 }"
    )
    return PRELUDE + f"""
fn kernel_gemv_f32(rows int, cols int, out $&[]f32, w &[]f32, x &[]f32) {{
    for r in 0:rows {{
        row_off := r * cols
        $acc := f32(0)
        for c in 0:cols {{ acc += w[row_off + c] * x[c] }}
        out[r] = acc
    }}
}}

fn kernel_gemv_f32_off(rows int, cols int, out_off int, w_off int, x_off int, out $&[]f32, w &[]f32, x &[]f32) {{
    for r in 0:rows {{
        row_off := w_off + r * cols
        $acc := f32(0)
        for c in 0:cols {{ acc += w[row_off + c] * x[x_off + c] }}
        out[out_off + r] = acc
    }}
}}

fn kernel_gemv_f32_overlap(rows int, cols int, w &[]f32, buf $&[]f32) {{
    for r in 0:rows {{
        row_off := r * cols
        $acc := f32(0)
        for c in 0:cols {{ acc += w[row_off + c] * buf[c] }}
        buf[1 + r] = acc
    }}
}}

fn kernel_dot_q4_q8(n_blocks int, q_off int, ws_off int, xq_off int, xs_off int, seed_bits int,
                    qs &[]u8, ws &[]f32, xq &[]i8, xs &[]f32) int {{
    $acc := from_bits(seed_bits)
    for b in 0:n_blocks {{
        $isum := 0
        q_base := q_off + b * 16
        x_base := xq_off + b * 32
        for j in 0:16 {{
            bv := int(qs[q_base + j])
            q0 := (bv & 15) - 8
            q1 := (bv >> 4) - 8
            isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
        }}
        acc += f32(isum) * (ws[ws_off + b] * xs[xs_off + b])
    }}
    << bits(acc)
}}

fn kernel_gemv_q4_q8(rows int, n_blocks int, out $&[]f32, qs &[]u8, ws &[]f32, xq &[]i8, xs &[]f32) {{
    for r in 0:rows {{
        s_off := r * n_blocks
        q_off := s_off * 16
        $acc := f32(0)
        for b in 0:n_blocks {{
            $isum := 0
            q_base := q_off + b * 16
            x_base := b * 32
            for j in 0:16 {{
                bv := int(qs[q_base + j])
                q0 := (bv & 15) - 8
                q1 := (bv >> 4) - 8
                isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
            }}
            acc += f32(isum) * (ws[s_off + b] * xs[b])
        }}
        out[r] = acc
    }}
}}

fn kernel_gemv_q4_q8_off(rows int, n_blocks int, out_off int, blk_off int, xq_off int, xs_off int,
                         out $&[]f32, qs &[]u8, ws &[]f32, xq &[]i8, xs &[]f32) {{
    for r in 0:rows {{
        s_off := blk_off + r * n_blocks
        q_off := s_off * 16
        $acc := f32(0)
        for b in 0:n_blocks {{
            $isum := 0
            q_base := q_off + b * 16
            x_base := xq_off + b * 32
            for j in 0:16 {{
                bv := int(qs[q_base + j])
                q0 := (bv & 15) - 8
                q1 := (bv >> 4) - 8
                isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
            }}
            acc += f32(isum) * (ws[s_off + b] * xs[xs_off + b])
        }}
        out[out_off + r] = acc
    }}
}}

fn verify_overlap_and_tagged(tag int) int {{
    $w := []f32{{}}
    for i in 0:48 {{ w.push(f32(f64((i % 7) - 3) * 0.25)) }}
    $b1 := []f32{{}}
    $b2 := []f32{{}}
    for i in 0:12 {{
        b1.push(f32(f64(i + 1) * 0.5))
        b2.push(f32(f64(i + 1) * 0.5))
    }}
    kernel_gemv_f32_overlap(5, 6, &w, $&b1)
    for r in 0:5 {{
        $acc := f32(0)
        for c in 0:6 {{ acc += w[r * 6 + c] * b2[c] }}
        b2[1 + r] = acc
    }}
    for i in 0:12 {{
        if bits(b1[i]) != bits(b2[i]) {{ << 1 }}
    }}

    if tag != 0 {{
        $o1 := [f32(0), f32(0), f32(0), f32(0), f32(0)]
        $o2 := [f32(0), f32(0), f32(0), f32(0), f32(0)]
        x := [f32(1), f32(2), f32(3), f32(4), f32(5), f32(6)]
        kernel_gemv_f32(5, 6, $&o2, &w, &x)
        unsafe {{
            op := ($&o1) as *raw int
            saved := *op
            *op = saved | tag
            kernel_gemv_f32(5, 6, $&o1, &w, &x)
            *op = saved
        }}
        for i in 0:5 {{
            if bits(o1[i]) != bits(o2[i]) {{ << 2 }}
        }}
    }}
    << 0
}}

fn hash_prefix(v &[]f32, n int) int {{
    $h := 0
    for i in 0:n {{ h = h ^ (bits(v[i]) + i * 131) }}
    << h
}}

fn trigger_panic(which string) {{
    $out := []f32{{}}
    for _ in 0:4 {{ out.push(f32(0)) }}
    $w := []f32{{}}
    for i in 0:24 {{ w.push(f32(f64(i) * 0.25)) }}
    $x := [f32(1), f32(2), f32(3), f32(4), f32(5), f32(6)]
    if which == "f32_short_out" {{
        kernel_gemv_f32(5, 4, $&out, &w, &x)
        <<
    }}
    if which == "f32_short_w" {{
        kernel_gemv_f32(5, 5, $&out, &w, &x)
        <<
    }}
    if which == "f32_short_x" {{
        kernel_gemv_f32(3, 7, $&out, &w, &x)
        <<
    }}
    if which == "f32_neg_off" {{
        kernel_gemv_f32_off(2, 4, -1, 0, 0, $&out, &w, &x)
        <<
    }}
    if which == "f32_overflow_rows" {{
        kernel_gemv_f32(0x10000001, 4, $&out, &w, &x)
        <<
    }}

    $qs := []u8{{}}
    for i in 0:64 {{ qs.push(u8(i * 19 + 3)) }}
    $ws := [f32(0.5), f32(0.25), f32(0.75), f32(1.0)]
    $xq := []i8{{}}
    for i in 0:64 {{ xq.push(i8((i % 23) - 11)) }}
    $xs := [f32(0.125), f32(0.25)]
    if which == "q4q8_short_out" {{
        $o2 := [f32(0)]
        kernel_gemv_q4_q8(2, 2, $&o2, &qs, &ws, &xq, &xs)
        <<
    }}
    if which == "q4q8_short_qs" {{
        $bqs := []u8{{}}
        for i in 0:63 {{ bqs.push(u8(i)) }}
        kernel_gemv_q4_q8(2, 2, $&out, &bqs, &ws, &xq, &xs)
        <<
    }}
    if which == "q4q8_short_ws" {{
        bws := [f32(1), f32(1), f32(1)]
        kernel_gemv_q4_q8(2, 2, $&out, &qs, &bws, &xq, &xs)
        <<
    }}
    if which == "q4q8_short_xq" {{
        $bxq := []i8{{}}
        for i in 0:63 {{ bxq.push(i8(1)) }}
        kernel_gemv_q4_q8(2, 2, $&out, &qs, &ws, &bxq, &xs)
        <<
    }}
    if which == "q4q8_short_xs" {{
        bxs := [f32(1)]
        kernel_gemv_q4_q8(2, 2, $&out, &qs, &ws, &xq, &bxs)
        <<
    }}
    if which == "q4q8_neg_blk" {{
        kernel_gemv_q4_q8_off(1, 1, 0, -1, 0, 0, $&out, &qs, &ws, &xq, &xs)
        <<
    }}
    if which == "dot_short_qs" {{
        $bqs := []u8{{}}
        for i in 0:31 {{ bqs.push(u8(i)) }}
        println(kernel_dot_q4_q8(2, 0, 0, 0, 0, 0, &bqs, &ws, &xq, &xs))
        <<
    }}
    if which == "dot_short_xq" {{
        $bxq := []i8{{}}
        for i in 0:63 {{ bxq.push(i8(1)) }}
        println(kernel_dot_q4_q8(2, 0, 0, 0, 0, 0, &qs, &ws, &bxq, &xs))
        <<
    }}
    if which == "dot_overflow_nb" {{
        println(kernel_dot_q4_q8(0x4000000000000001, 0, 0, 0, 0, 0, &qs, &ws, &xq, &xs))
        <<
    }}
}}

fn main() int {{
    args := os.argv()
    if args.len > 1 {{
        trigger_panic(args[1])
        << 3
    }}

    // 1. F32 GEMV matrix across row/col shapes & offsets
    $wf := []f32{{}}
    for i in 0:32 * 80 {{ wf.push(f32(f64(((i * 17) % 29) - 14) * 0.0625)) }}
    $xf := []f32{{}}
    for i in 0:80 {{ xf.push(f32(f64(((i * 11) % 23) - 11) * 0.125)) }}
    $outf := []f32{{}}
    for _ in 0:32 {{ outf.push(f32(0)) }}

    rows_list := [{rows_lit}]
    cols_list := [{cols_lit}]
    for ri in 0:rows_list.len {{
        r := rows_list[ri]
        for ci in 0:cols_list.len {{
            c := cols_list[ci]
            for k in 0:outf.len {{ outf[k] = from_bits(0x3f800000) }}
            kernel_gemv_f32(r, c, $&outf, &wf, &xf)
            h0 := hash_prefix(&outf, 20)
            for k in 0:outf.len {{ outf[k] = from_bits(0x40000000) }}
            kernel_gemv_f32_off(r, c, 2, 7, 5, $&outf, &wf, &xf)
            h1 := hash_prefix(&outf, 22)
            println("gf32:" + str(r) + "x" + str(c) + ":" + str(h0) + ":" + str(h1))
        }}
    }}
    {tagged_call}

    // 2. Q4_0 x Q8_0 dot & 2D GEMV across shapes, offsets, signed extremes, and -0.0
    $qs := []u8{{}}
    extremes := [0x00, 0xFF, 0x88, 0x0F, 0xF0, 0x78, 0x87, 0x19]
    for i in 0:24 * 20 * 16 {{
        if i < 16 {{
            qs.push(u8(extremes[i % 8]))
        }} else {{
            qs.push(u8((i * 73 + 17) & 255))
        }}
    }}
    $ws := []f32{{}}
    for i in 0:24 * 20 {{ ws.push(f32(f64(((i * 7) % 19) - 9) * 0.03125)) }}
    $xq := []i8{{}}
    for i in 0:24 * 32 {{
        if i == 0 {{ xq.push(i8(-128)) }}
        else if i == 1 {{ xq.push(i8(127)) }}
        else if i == 2 {{ xq.push(i8(-127)) }}
        else {{ xq.push(i8(((i * 29) % 255) - 127)) }}
    }}
    $xs := []f32{{}}
    for i in 0:24 {{ xs.push(f32(f64(((i * 5) % 17) - 8) * 0.015625)) }}

    qrows := [{qrows_lit}]
    qblks := [{qblk_lit}]
    for ri in 0:qrows.len {{
        r := qrows[ri]
        for bi in 0:qblks.len {{
            nb := qblks[bi]
            for k in 0:outf.len {{ outf[k] = from_bits(0x3f800000) }}
            kernel_gemv_q4_q8(r, nb, $&outf, &qs, &ws, &xq, &xs)
            h0 := hash_prefix(&outf, 20)
            for k in 0:outf.len {{ outf[k] = from_bits(0x40000000) }}
            kernel_gemv_q4_q8_off(r, nb, 3, 2, 64, 2, $&outf, &qs, &ws, &xq, &xs)
            h1 := hash_prefix(&outf, 22)
            println("gq4q8:" + str(r) + "x" + str(nb) + ":" + str(h0) + ":" + str(h1))
        }}
    }}

    for bi in 0:qblks.len {{
        nb := qblks[bi]
        d0 := kernel_dot_q4_q8(nb, 0, 0, 0, 0, 0, &qs, &ws, &xq, &xs)
        d1 := kernel_dot_q4_q8(nb, 32, 2, 64, 2, 0x80000000, &qs, &ws, &xq, &xs)
        println("dq4q8:" + str(nb) + ":" + str(d0) + ":" + str(d1))
    }}
    println("dq4q8_neg0:" + str(kernel_dot_q4_q8(0, 0, 0, 0, 0, 0x80000000, &qs, &ws, &xq, &xs)))
    println("dq4q8_negnb:" + str(kernel_dot_q4_q8(-2, 0, 0, 0, 0, 0x80000000, &qs, &ws, &xq, &xs)))

    // Representative row sample check for fast-math tolerance
    $sample_f32 := []f32{{}}
    for _ in 0:17 {{ sample_f32.push(f32(0)) }}
    kernel_gemv_f32(17, 64, $&sample_f32, &wf, &xf)
    for r in 0:17 {{ println("sf32:" + str(r) + ":" + str(bits(sample_f32[r]))) }}
    kernel_gemv_q4_q8(17, 16, $&sample_f32, &qs, &ws, &xq, &xs)
    for r in 0:17 {{ println("sq4:" + str(r) + ":" + str(bits(sample_f32[r]))) }}
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
        if "q4_0_q8_0" in sym:
            assert "sdot.4s" in body and "addv.4s" in body and "scvtf" in body, sym
        if fast_math:
            if "gemv4_f32" in sym:
                assert "fmla.4s" in body and "faddp.4s" in body, sym
            elif "gemv4_q4_0_q8_0" in sym or "dot_q4_0_q8_0" in sym:
                assert "fmadd" in body, sym
        else:
            assert not re.search(r"\bf(?:n?madd|n?msub|mla|mls)\b", body), sym


def check_x64_cross(compiler, env, src, work):
    x64_exe = work / "gemv-x64"
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
            if "q4_0_q8_0" in sym:
                assert "pmaddwd" in body and "paddd" in body and "cvtdq2ps" in body, sym
            else:
                assert "mulps" in body and ("addps" in body if "fast" in sym else "addss" in body), sym
            for forbidden in ("xmm6", "xmm7", "xmm8", "xmm9", "xmm10", "xmm11", "xmm12", "xmm13", "xmm14", "xmm15",
                              "%rbx", "%rbp", "%r12", "%r13", "%r14"):
                assert forbidden not in body, (sym, forbidden)
    else:
        for sym in STUBS_STRICT + STUBS_FAST:
            assert sym.encode("ascii") in raw, f"Missing x64 stub symbol {sym}"
        print("macos-x64 Mach-O header & stub symbols verified (otool disassembly skipped on non-macOS host)")


def benchmark_source():
    return PRELUDE.replace("#os", "#os\n#time", 1) + """
fn bench_gemv_f32(rows int, cols int, out $&[]f32, w &[]f32, x &[]f32) {
    for r in 0:rows {
        row_off := r * cols
        $acc := f32(0)
        for c in 0:cols { acc += w[row_off + c] * x[c] }
        out[r] = acc
    }
}

fn bench_gemv_q4_q8(rows int, n_blocks int, out $&[]f32, qs &[]u8, ws &[]f32, xq &[]i8, xs &[]f32) {
    for r in 0:rows {
        s_off := r * n_blocks
        q_off := s_off * 16
        $acc := f32(0)
        for b in 0:n_blocks {
            $isum := 0
            q_base := q_off + b * 16
            x_base := b * 32
            for j in 0:16 {
                bv := int(qs[q_base + j])
                q0 := (bv & 15) - 8
                q1 := (bv >> 4) - 8
                isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
            }
            acc += f32(isum) * (ws[s_off + b] * xs[b])
        }
        out[r] = acc
    }
}

fn main() int {
    args := os.argv()
    kind := args[1]
    rows := 512
    cols := 512
    n_blocks := 16
    $out := []f32{}
    for _ in 0:rows { out.push(f32(0)) }

    if kind == "gemv_f32" {
        $w := []f32{}
        $x := []f32{}
        for i in 0:rows * cols { w.push(f32(f64((i % 13) - 6) * 0.03125)) }
        for i in 0:cols { x.push(f32(f64((i % 11) - 5) * 0.0625)) }
        $elapsed := [200]int{}
        $checksum := 0
        for s in 0:240 {
            t0 := time.now()
            bench_gemv_f32(rows, cols, $&out, &w, &x)
            d := time.since(t0)
            if s >= 40 { elapsed[s - 40] = d }
            checksum += bits(out[s % rows])
        }
        println(checksum)
        for i in 0:200 { println(elapsed[i]) }
        << 0
    }

    $qs := []u8{}
    $ws := []f32{}
    $xq := []i8{}
    $xs := []f32{}
    for i in 0:rows * n_blocks * 16 { qs.push(u8((i * 73 + 11) & 255)) }
    for i in 0:rows * n_blocks { ws.push(f32(f64((i % 13) - 6) * 0.03125)) }
    for i in 0:cols { xq.push(i8(((i * 17) % 240) - 120)) }
    for i in 0:n_blocks { xs.push(f32(f64((i % 7) + 1) * 0.015625)) }
    $elapsed := [200]int{}
    $checksum := 0
    for s in 0:240 {
        t0 := time.now()
        bench_gemv_q4_q8(rows, n_blocks, $&out, &qs, &ws, &xq, &xs)
        d := time.since(t0)
        if s >= 40 { elapsed[s - 40] = d }
        checksum += bits(out[s % rows])
    }
    println(checksum)
    for i in 0:200 { println(elapsed[i]) }
    << 0
}
"""


def benchmark(compiler, env, work):
    source = work / "bench_gemv.xu"
    source.write_text(benchmark_source())
    strict_totals = {}
    for mode, fusion, fast in (
        ("baseline", "0", "0"),
        ("neon-strict", "1", "0"),
        ("neon-fast", "1", "1"),
    ):
        exe = work / ("bench-" + mode)
        build(compiler, dict(env, XU_TENSOR_FUSION=fusion, XU_TENSOR_FAST_MATH=fast, XU_TASK_POLL="0"),
              source, exe)
        for kind in ("gemv_f32", "gemv_q4_q8"):
            checksum, *samples = map(int, run([exe, kind]).splitlines())
            if mode == "baseline":
                strict_totals[kind] = checksum
            elif mode == "neon-strict":
                assert checksum == strict_totals[kind], (kind, checksum, strict_totals[kind])
            samples.sort()
            p50 = samples[len(samples) // 2 - 1]
            p99 = samples[len(samples) * 99 // 100 - 1]
            print(f"{kind:11} 512x512 {mode:11} n={len(samples)} P50={p50} ns P99={p99} ns")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        src = work / "tensor_gemv.xu"
        src.write_text(test_source())
        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_DUMP_MIR="_xu_main_kernel_", XU_KEEP_SYMBOLS="1")

        baseline_out = None
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
            if mode == "strict":
                assert "call __xu_tensor_gemv4_f32(" in functions["kernel_gemv_f32"]
                assert "call __xu_tensor_gemv4_f32(" in functions["kernel_gemv_f32_off"]
                assert "call __xu_tensor_dot_q4_0_q8_0_f32(" in functions["kernel_dot_q4_q8"]
                assert "call __xu_tensor_gemv4_q4_0_q8_0_f32(" in functions["kernel_gemv_q4_q8"]
                assert "call __xu_tensor_gemv4_q4_0_q8_0_f32(" in functions["kernel_gemv_q4_q8_off"]
                check_arm64_disassembly(exe, fast_math=False)
            elif mode == "fast-math":
                assert "call __xu_tensor_gemv4_fast_f32(" in functions["kernel_gemv_f32"]
                assert "call __xu_tensor_dot_q4_0_q8_0_fast_f32(" in functions["kernel_dot_q4_q8"]
                assert "call __xu_tensor_gemv4_q4_0_q8_0_fast_f32(" in functions["kernel_gemv_q4_q8"]
                check_arm64_disassembly(exe, fast_math=True)

            out = run([exe]).splitlines()
            if mode == "baseline":
                baseline_out = out
            elif mode != "fast-math":
                assert out == baseline_out, (mode, "bit-exact mismatch vs baseline")
            else:
                assert "dq4q8_neg0:2147483648" in out and "dq4q8_negnb:2147483648" in out
                for prefix in ("sf32:", "sq4:", "dq4q8:"):
                    b_lines = [l for l in baseline_out if l.startswith(prefix)]
                    f_lines = [l for l in out if l.startswith(prefix)]
                    assert len(b_lines) == len(f_lines)
                    for lb, lf in zip(b_lines, f_lines):
                        pb = lb.split(":")
                        pf = lf.split(":")
                        for idx in range(2, len(pb)):
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
        print("macos-x64 cross-compile and SSE2 GEMV4/PMADDWD disassembly passed")
        if args.benchmark:
            benchmark(compiler, env, work)


if __name__ == "__main__":
    main()
