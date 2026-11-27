#!/usr/bin/env python3
"""Verify ARM64 NEON / SDOT & x64 SSE2 quantize_q8_0, Q8_0 GEMV, and 4x4 Prefill GEMM."""

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
from test_tensor_fusion import PRELUDE, build, run
from test_windows_workers import WindowsTemporaryDirectory


M_COUNTS = [0, 1, 2, 3, 4, 5, 16]
N_COUNTS = [0, 1, 2, 3, 4, 5, 7, 17]
K_COUNTS = [0, 1, 2, 3, 4, 5, 8, 9, 17, 37]
NB_COUNTS = [0, 1, 2, 3, 5, 8, 16]

PANIC_CASES = (
    "quant_short_x",
    "quant_short_xq",
    "quant_short_xs",
    "quant_neg_xs_off",
    "q8gemv_short_out",
    "q8gemv_short_wqs",
    "q8gemv_short_ws",
    "q8gemv_short_xq",
    "q8gemv_short_xs",
    "q8gemv_neg_blk",
    "gemm_f32_short_out",
    "gemm_f32_short_w",
    "gemm_f32_short_x",
    "gemm_f32_neg_off",
    "gemm_q4q8_short_out",
    "gemm_q4q8_short_qs",
    "gemm_q4q8_short_ws",
    "gemm_q4q8_short_xq",
    "gemm_q4q8_short_xs",
    "gemm_q4q8_neg_blk",
)

STUBS_STRICT = (
    "___xu_tensor_quantize_q8_0",
    "___xu_tensor_gemv4_q8_0_q8_0_f32",
    "___xu_tensor_gemm4x4_f32",
    "___xu_tensor_gemm4x4_q4_0_q8_0_f32",
)
STUBS_FAST = (
    "___xu_tensor_quantize_q8_0_fast",
    "___xu_tensor_gemv4_q8_0_q8_0_fast_f32",
    "___xu_tensor_gemm4x4_fast_f32",
    "___xu_tensor_gemm4x4_q4_0_q8_0_fast_f32",
)


def bits_to_f32(b):
    return struct.unpack("<f", struct.pack("<I", int(b)))[0]


def test_source():
    ms_lit = ", ".join(str(v) for v in M_COUNTS)
    ns_lit = ", ".join(str(v) for v in N_COUNTS)
    ks_lit = ", ".join(str(v) for v in K_COUNTS)
    nbs_lit = ", ".join(str(v) for v in NB_COUNTS)
    tagged_call = (
        "if verify_overlap_and_tagged(0x0400000000000000) != 0 { << 10 }"
        if platform.system() == "Darwin" and platform.machine() == "arm64"
        else "if verify_overlap_and_tagged(0) != 0 { << 10 }"
    )
    return PRELUDE + f"""
fn kernel_quantize_q8(x &[]f32, xq $&[]i8, x_scales $&[]f32, xs_off int, nb int) {{
    for b in 0:nb {{
        base := b * 32
        $amax := 0.0
        for i in 0:32 {{
            $v := f64(x[base + i])
            if v < 0.0 {{ v = -v }}
            if v > amax {{ amax = v }}
        }}
        scale := f32(amax / 127.0)
        x_scales[xs_off + b] = scale
        $inv := 0.0
        if f64(scale) != 0.0 {{ inv = 1.0 / f64(scale) }}
        for i in 0:32 {{
            vf := f64(x[base + i]) * inv
            $q := 0
            if vf >= 0.0 {{ q = int(vf + 0.5) }} else {{ q = -int(0.5 - vf) }}
            if q > 127 {{ q = 127 }}
            if q < -127 {{ q = -127 }}
            xq[base + i] = i8(q)
        }}
    }}
}}

fn kernel_quantize_alias(x $&[]f32, xq $&[]i8, xs_idx_off int, nb int) {{
    // Alias xs and x via same buffer x: must take scalar fallback safely.
    for b in 0:nb {{
        base := b * 32
        $amax := 0.0
        for i in 0:32 {{
            $v := f64(x[base + i])
            if v < 0.0 {{ v = -v }}
            if v > amax {{ amax = v }}
        }}
        scale := f32(amax / 127.0)
        x[xs_idx_off + b] = scale
        $inv := 0.0
        if f64(scale) != 0.0 {{ inv = 1.0 / f64(scale) }}
        for i in 0:32 {{
            vf := f64(x[base + i]) * inv
            $q := 0
            if vf >= 0.0 {{ q = int(vf + 0.5) }} else {{ q = -int(0.5 - vf) }}
            if q > 127 {{ q = 127 }}
            if q < -127 {{ q = -127 }}
            xq[base + i] = i8(q)
        }}
    }}
}}

fn kernel_gemv_q8_q8(rows int, n_blocks int, blk_off int, out_off int, xq_off int, xs_off int,
                     out $&[]f32, w_qs &[]i8, w_scales &[]f32, xq &[]i8, x_scales &[]f32) {{
    for r in 0:rows {{
        s_off := blk_off + r * n_blocks
        q_off := s_off * 32
        $acc := f32(0)
        for b in 0:n_blocks {{
            $isum := 0
            q_base := q_off + b * 32
            x_base := xq_off + b * 32
            for j in 0:32 {{
                isum += int(w_qs[q_base + j]) * int(xq[x_base + j])
            }}
            acc += f32(isum) * (w_scales[s_off + b] * x_scales[xs_off + b])
        }}
        out[out_off + r] = acc
    }}
}}

fn kernel_gemm_f32(m_cnt int, n_cnt int, k_cnt int, out_base int, w_base int, x_base int,
                   out $&[]f32, w &[]f32, x &[]f32) {{
    for m in 0:m_cnt {{
        x_off := x_base + m * k_cnt
        out_off := out_base + m * n_cnt
        for r in 0:n_cnt {{
            row_off := w_base + r * k_cnt
            $acc := f32(0)
            for c in 0:k_cnt {{
                acc += w[row_off + c] * x[x_off + c]
            }}
            out[out_off + r] = acc
        }}
    }}
}}

fn kernel_gemm_f32_overlap(m_cnt int, n_cnt int, k_cnt int, w &[]f32, buf $&[]f32) {{
    for m in 0:m_cnt {{
        x_off := m * k_cnt
        out_off := 1 + m * n_cnt
        for r in 0:n_cnt {{
            row_off := r * k_cnt
            $acc := f32(0)
            for c in 0:k_cnt {{ acc += w[row_off + c] * buf[x_off + c] }}
            buf[out_off + r] = acc
        }}
    }}
}}

fn kernel_gemm_q4_q8(m_cnt int, n_cnt int, n_blocks int, blk_off int, out_base int, xs_base int,
                     out $&[]f32, qs &[]u8, ws &[]f32, xq &[]i8, xs &[]f32) {{
    for m in 0:m_cnt {{
        xm_s := xs_base + m * n_blocks
        xm_q := xm_s * 32
        out_off := out_base + m * n_cnt
        for r in 0:n_cnt {{
            s_off := blk_off + r * n_blocks
            q_off := s_off * 16
            $acc := f32(0)
            for b in 0:n_blocks {{
                $isum := 0
                q_base := q_off + b * 16
                x_base := xm_q + b * 32
                for j in 0:16 {{
                    bv := int(qs[q_base + j])
                    q0 := (bv & 15) - 8
                    q1 := (bv >> 4) - 8
                    isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
                }}
                acc += f32(isum) * (ws[s_off + b] * xs[xm_s + b])
            }}
            out[out_off + r] = acc
        }}
    }}
}}

fn hash_f32_prefix(arr &[]f32, n int, off int) int {{
    $h := 17
    for i in 0:n {{
        h = (h * 1315423911 + bits(arr[off + i]) + i) & 0x7fffffffffffffff
    }}
    << h
}}

fn hash_i8_prefix(arr &[]i8, n int) int {{
    $h := 29
    for i in 0:n {{
        h = (h * 131 + int(arr[i]) + 256 + i) & 0x7fffffffffffffff
    }}
    << h
}}

fn zeros_f32(n int) []f32 {{
    $out := []f32{{}}
    for _ in 0:n {{ out.push(f32(0)) }}
    << out
}}

fn zeros_i8(n int) []i8 {{
    $out := []i8{{}}
    for _ in 0:n {{ out.push(i8(0)) }}
    << out
}}

fn zeros_u8(n int) []u8 {{
    $out := []u8{{}}
    for _ in 0:n {{ out.push(u8(0)) }}
    << out
}}

fn verify_overlap_and_tagged(tag int) int {{
    $wf := []f32{{}}
    for i in 0:64 {{ wf.push(f32(f64((i % 7) - 3) * 0.25)) }}
    $ov := []f32{{}}
    for i in 0:64 {{ ov.push(f32(f64(i % 9) * 0.125)) }}
    kernel_gemm_f32_overlap(3, 5, 8, &wf, $&ov)
    h0 := hash_f32_prefix(&ov, 24, 0)
    $ax := []f32{{}}
    $axq := []i8{{}}
    for i in 0:64 {{
        ax.push(f32(f64((i % 11) - 5) * 0.5))
        axq.push(i8(0))
    }}
    kernel_quantize_alias($&ax, $&axq, 32, 2)
    h1 := hash_f32_prefix(&ax, 64, 0) + hash_i8_prefix(&axq, 64)

    $q := zeros_f32(16)
    $k := zeros_f32(16)
    $out := zeros_f32(16)
    for i in 0:16 {{
        q[i] = f32(f64(i + 1) * 0.25)
        k[i] = f32(f64(i % 5) * 0.5)
    }}
    kernel_gemm_f32(2, 3, 4, tag & 0, tag & 0, tag & 0, $&out, &q, &k)
    if h0 == 0 && h1 == 0 {{ << 1 }}
    println("overlap:" + str(h0) + ":" + str(h1) + ":" + str(hash_f32_prefix(&out, 6, 0)))
    << 0
}}

fn run_panic(case string) int {{
    $fx := []f32{{}}
    $fxq := []i8{{}}
    $fxs := []f32{{}}
    for i in 0:64 {{
        fx.push(f32(i))
        fxq.push(i8(i & 63))
    }}
    for _ in 0:4 {{ fxs.push(f32(0.5)) }}

    if case == "quant_short_x" {{
        $hx := zeros_f32(16)
        kernel_quantize_q8(&hx, $&fxq, $&fxs, 0, 1)
        << 1
    }}
    if case == "quant_short_xq" {{
        $hq := zeros_i8(16)
        kernel_quantize_q8(&fx, $&hq, $&fxs, 0, 1)
        << 1
    }}
    if case == "quant_short_xs" {{
        $hs := zeros_f32(1)
        kernel_quantize_q8(&fx, $&fxq, $&hs, 0, 2)
        << 1
    }}
    if case == "quant_neg_xs_off" {{
        kernel_quantize_q8(&fx, $&fxq, $&fxs, -1, 1)
        << 1
    }}

    $out := zeros_f32(4)
    $wqs := []i8{{}}
    $ws := zeros_f32(8)
    for i in 0:128 {{ wqs.push(i8(1)) }}
    if case == "q8gemv_short_out" {{
        $so := zeros_f32(2)
        kernel_gemv_q8_q8(3, 1, 0, 0, 0, 0, $&so, &wqs, &ws, &fxq, &fxs)
        << 1
    }}
    if case == "q8gemv_short_wqs" {{
        $sq := zeros_i8(16)
        kernel_gemv_q8_q8(1, 1, 0, 0, 0, 0, $&out, &sq, &ws, &fxq, &fxs)
        << 1
    }}
    if case == "q8gemv_short_ws" {{
        $sw := zeros_f32(1)
        kernel_gemv_q8_q8(2, 1, 0, 0, 0, 0, $&out, &wqs, &sw, &fxq, &fxs)
        << 1
    }}
    if case == "q8gemv_short_xq" {{
        $sx := zeros_i8(16)
        kernel_gemv_q8_q8(1, 1, 0, 0, 0, 0, $&out, &wqs, &ws, &sx, &fxs)
        << 1
    }}
    if case == "q8gemv_short_xs" {{
        $ss := zeros_f32(1)
        kernel_gemv_q8_q8(1, 2, 0, 0, 0, 0, $&out, &wqs, &ws, &fxq, &ss)
        << 1
    }}
    if case == "q8gemv_neg_blk" {{
        kernel_gemv_q8_q8(1, 1, -1, 0, 0, 0, $&out, &wqs, &ws, &fxq, &fxs)
        << 1
    }}

    $w := zeros_f32(16)
    $x := zeros_f32(16)
    if case == "gemm_f32_short_out" {{
        $so := zeros_f32(5)
        kernel_gemm_f32(2, 3, 4, 0, 0, 0, $&so, &w, &x)
        << 1
    }}
    if case == "gemm_f32_short_w" {{
        $sw := zeros_f32(8)
        kernel_gemm_f32(2, 3, 4, 0, 0, 0, $&out, &sw, &x)
        << 1
    }}
    if case == "gemm_f32_short_x" {{
        $sx := zeros_f32(6)
        kernel_gemm_f32(2, 3, 4, 0, 0, 0, $&out, &w, &sx)
        << 1
    }}
    if case == "gemm_f32_neg_off" {{
        kernel_gemm_f32(1, 2, 2, -1, 0, 0, $&out, &w, &x)
        << 1
    }}

    $qs := zeros_u8(64)
    $gom := zeros_f32(8)
    if case == "gemm_q4q8_short_out" {{
        $so := zeros_f32(3)
        kernel_gemm_q4_q8(2, 2, 1, 0, 0, 0, $&so, &qs, &ws, &fxq, &fxs)
        << 1
    }}
    if case == "gemm_q4q8_short_qs" {{
        $sq := zeros_u8(16)
        kernel_gemm_q4_q8(1, 2, 1, 0, 0, 0, $&gom, &sq, &ws, &fxq, &fxs)
        << 1
    }}
    if case == "gemm_q4q8_short_ws" {{
        $sw := zeros_f32(1)
        kernel_gemm_q4_q8(1, 2, 1, 0, 0, 0, $&gom, &qs, &sw, &fxq, &fxs)
        << 1
    }}
    if case == "gemm_q4q8_short_xq" {{
        $sx := zeros_i8(32)
        kernel_gemm_q4_q8(2, 1, 1, 0, 0, 0, $&gom, &qs, &ws, &sx, &fxs)
        << 1
    }}
    if case == "gemm_q4q8_short_xs" {{
        $ss := zeros_f32(1)
        kernel_gemm_q4_q8(2, 1, 1, 0, 0, 0, $&gom, &qs, &ws, &fxq, &ss)
        << 1
    }}
    if case == "gemm_q4q8_neg_blk" {{
        kernel_gemm_q4_q8(1, 1, 1, -1, 0, 0, $&gom, &qs, &ws, &fxq, &fxs)
        << 1
    }}
    << 0
}}

fn main() int {{
    args := os.argv()
    if args.len >= 2 {{
        << run_panic(args[1])
    }}
    {tagged_call}

    // 1. Edge cases for quantize_q8_0: all zero, -0.0, exact +-0.5 ties, uniform non-zero, clamping.
    $q_in := []f32{{}}
    $q_xq := []i8{{}}
    $q_xs := []f32{{}}
    for _ in 0:160 {{
        q_in.push(f32(0))
        q_xq.push(i8(0))
    }}
    for _ in 0:8 {{ q_xs.push(f32(-99)) }}
    // Block 0: all +/-0.0
    q_in[3] = from_bits(0x80000000)
    // Block 1: exact +/-0.5 ties when scale=1.0 (amax=127.0 -> inv=1.0)
    q_in[32 + 0] = f32(127.0)
    q_in[32 + 1] = f32(-127.0)
    q_in[32 + 2] = f32(0.5)
    q_in[32 + 3] = f32(-0.5)
    q_in[32 + 4] = f32(1.5)
    q_in[32 + 5] = f32(-1.5)
    q_in[32 + 6] = f32(126.5)
    q_in[32 + 7] = f32(-126.5)
    q_in[32 + 8] = f32(-0.0)
    // Blocks 2..4: mixed values spanning negative & positive ranges
    for i in 64:160 {{
        v := f64(((i * 37) % 101) - 50) * 0.1375
        q_in[i] = f32(v)
    }}
    kernel_quantize_q8(&q_in, $&q_xq, $&q_xs, 1, 5)
    $q_sc_bits := 19
    for i in 0:6 {{ q_sc_bits = (q_sc_bits * 131 + bits(q_xs[i])) & 0x7fffffffffffffff }}
    println("quant_edge:" + str(hash_i8_prefix(&q_xq, 160)) + ":" + str(q_sc_bits))
    for i in 0:10 {{ println("qtie:" + str(i) + ":" + str(int(q_xq[32 + i]))) }}

    // Zero blocks / negative nb guard
    kernel_quantize_q8(&q_in, $&q_xq, $&q_xs, 0, 0)
    kernel_quantize_q8(&q_in, $&q_xq, $&q_xs, 0, -2)

    // 2. GEMV Q8_0 x Q8_0 shape & offset matrix
    ns := [{ns_lit}]
    nbs := [{nbs_lit}]
    $w_q8 := []i8{{}}
    $w_s := []f32{{}}
    $x_q8 := []i8{{}}
    $x_s := []f32{{}}
    for i in 0:16384 {{ w_q8.push(i8(((i * 53) % 240) - 120)) }}
    for i in 0:512 {{ w_s.push(f32(f64((i % 13) - 6) * 0.03125)) }}
    for i in 0:4096 {{ x_q8.push(i8(((i * 29) % 240) - 120)) }}
    for i in 0:128 {{ x_s.push(f32(f64((i % 7) + 1) * 0.015625)) }}
    $out_q8 := zeros_f32(64)
    for ri in 0:ns.len {{
        for bi in 0:nbs.len {{
            rr := ns[ri]
            nb := nbs[bi]
            for k in 0:64 {{ out_q8[k] = f32(-1.0) }}
            kernel_gemv_q8_q8(rr, nb, 0, 0, 0, 0, $&out_q8, &w_q8, &w_s, &x_q8, &x_s)
            h0 := hash_f32_prefix(&out_q8, 64, 0)
            kernel_gemv_q8_q8(rr, nb, 2, 3, 32, 1, $&out_q8, &w_q8, &w_s, &x_q8, &x_s)
            h1 := hash_f32_prefix(&out_q8, 64, 0)
            println("q8g:" + str(rr) + ":" + str(nb) + ":" + str(h0) + ":" + str(h1))
        }}
    }}

    // 3. GEMM 4x4 F32 shape & offset matrix
    ms := [{ms_lit}]
    ks := [{ks_lit}]
    $wf := []f32{{}}
    $xf := []f32{{}}
    for i in 0:2048 {{ wf.push(f32(f64((i % 17) - 8) * 0.0625)) }}
    for i in 0:2048 {{ xf.push(f32(f64((i % 13) - 6) * 0.125)) }}
    $out_gf := zeros_f32(512)
    for mi in 0:ms.len {{
        for ni in 0:ns.len {{
            for ki in 0:ks.len {{
                mm := ms[mi]
                nn := ns[ni]
                kk := ks[ki]
                if mm * nn <= 400 && mm * kk <= 1024 && nn * kk <= 1024 {{
                    for k in 0:512 {{ out_gf[k] = f32(-2.0) }}
                    kernel_gemm_f32(mm, nn, kk, 0, 0, 0, $&out_gf, &wf, &xf)
                    h0 := hash_f32_prefix(&out_gf, mm * nn + 4, 0)
                    kernel_gemm_f32(mm, nn, kk, 5, 7, 3, $&out_gf, &wf, &xf)
                    h1 := hash_f32_prefix(&out_gf, mm * nn + 8, 0)
                    println("gf32:" + str(mm) + ":" + str(nn) + ":" + str(kk) + ":" + str(h0) + ":" + str(h1))
                }}
            }}
        }}
    }}

    // 4. GEMM 4x4 Q4_0 x Q8_0 shape & offset matrix
    $qs4 := []u8{{}}
    for i in 0:8192 {{ qs4.push(u8((i * 73 + 19) & 255)) }}
    $out_gq := zeros_f32(512)
    for mi in 0:ms.len {{
        for ni in 0:ns.len {{
            for bi in 0:nbs.len {{
                mm := ms[mi]
                nn := ns[ni]
                nb := nbs[bi]
                if mm * nn <= 400 && nn * nb <= 400 && mm * nb <= 24 {{
                    for k in 0:512 {{ out_gq[k] = f32(-3.0) }}
                    kernel_gemm_q4_q8(mm, nn, nb, 0, 0, 0, $&out_gq, &qs4, &w_s, &x_q8, &x_s)
                    h0 := hash_f32_prefix(&out_gq, mm * nn + 4, 0)
                    kernel_gemm_q4_q8(mm, nn, nb, 3, 4, 1, $&out_gq, &qs4, &w_s, &x_q8, &x_s)
                    h1 := hash_f32_prefix(&out_gq, mm * nn + 8, 0)
                    println("gq4q8:" + str(mm) + ":" + str(nn) + ":" + str(nb) + ":" + str(h0) + ":" + str(h1))
                }}
            }}
        }}
    }}

    // 5. Representative float samples for fast-math tolerance checks
    $sq := []f32{{}}
    for _ in 0:17 {{ sq.push(f32(0)) }}
    kernel_gemv_q8_q8(17, 16, 0, 0, 0, 0, $&sq, &w_q8, &w_s, &x_q8, &x_s)
    for r in 0:17 {{ println("sq8g:" + str(r) + ":" + str(bits(sq[r]))) }}

    $sgf := zeros_f32(64)
    kernel_gemm_f32(5, 7, 37, 0, 0, 0, $&sgf, &wf, &xf)
    for idx in 0:35 {{ println("sgf:" + str(idx) + ":" + str(bits(sgf[idx]))) }}

    $sgq := zeros_f32(64)
    kernel_gemm_q4_q8(5, 7, 16, 0, 0, 0, $&sgq, &qs4, &w_s, &x_q8, &x_s)
    for idx in 0:35 {{ println("sgq:" + str(idx) + ":" + str(bits(sgq[idx]))) }}
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
        if "quantize_q8_0" in sym:
            assert "fabs.4s" in body and "fmaxnm.4s" in body and "fmaxnmv.4s" in body and "smax.16b" in body, sym
            assert ("fcvtas.4s" in body) if fast_math else ("fcvtzs.2d" in body), sym
        elif "q8_0_q8_0" in sym or "q4_0_q8_0" in sym:
            assert "sdot.4s" in body and "addp.4s" in body and "scvtf.4s" in body, sym
            if fast_math:
                assert "fmla.4s" in body, sym
        elif "gemm4x4" in sym:
            assert "ldp" in body or "ldr" in body, sym
            if fast_math:
                assert "fmla.4s" in body and "faddp.4s" in body, sym
        if not fast_math and "gemm4x4" in sym or "q8_0_q8_0" in sym and not fast_math:
            assert not re.search(r"\bf(?:n?madd|n?msub|mla|mls)\b", body), sym


def check_x64_cross(compiler, env, src, work):
    x64_exe = work / "gemm-x64"
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
            if "quantize_q8_0" in sym:
                assert "maxps" in body and "cvttsd2si" in body, sym
            elif "q8_0_q8_0" in sym or "q4_0_q8_0" in sym:
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
fn bench_quantize(x &[]f32, xq $&[]i8, xs $&[]f32, nb int) {
    for b in 0:nb {
        base := b * 32
        $amax := 0.0
        for i in 0:32 {
            $v := f64(x[base + i])
            if v < 0.0 { v = -v }
            if v > amax { amax = v }
        }
        scale := f32(amax / 127.0)
        xs[b] = scale
        $inv := 0.0
        if f64(scale) != 0.0 { inv = 1.0 / f64(scale) }
        for i in 0:32 {
            vf := f64(x[base + i]) * inv
            $q := 0
            if vf >= 0.0 { q = int(vf + 0.5) } else { q = -int(0.5 - vf) }
            if q > 127 { q = 127 }
            if q < -127 { q = -127 }
            xq[base + i] = i8(q)
        }
    }
}

fn bench_gemv_q8(rows int, nb int, out $&[]f32, wqs &[]i8, ws &[]f32, xq &[]i8, xs &[]f32) {
    for r in 0:rows {
        s_off := r * nb
        q_off := s_off * 32
        $acc := f32(0)
        for b in 0:nb {
            $isum := 0
            q_base := q_off + b * 32
            x_base := b * 32
            for j in 0:32 { isum += int(wqs[q_base + j]) * int(xq[x_base + j]) }
            acc += f32(isum) * (ws[s_off + b] * xs[b])
        }
        out[r] = acc
    }
}

fn bench_gemm_f32(m_cnt int, n_cnt int, k_cnt int, out $&[]f32, w &[]f32, x &[]f32) {
    for m in 0:m_cnt {
        x_off := m * k_cnt
        out_off := m * n_cnt
        for r in 0:n_cnt {
            row_off := r * k_cnt
            $acc := f32(0)
            for c in 0:k_cnt { acc += w[row_off + c] * x[x_off + c] }
            out[out_off + r] = acc
        }
    }
}

fn bench_gemm_q4(m_cnt int, n_cnt int, nb int, out $&[]f32, qs &[]u8, ws &[]f32, xq &[]i8, xs &[]f32) {
    for m in 0:m_cnt {
        xm_s := m * nb
        xm_q := xm_s * 32
        out_off := m * n_cnt
        for r in 0:n_cnt {
            s_off := r * nb
            q_off := s_off * 16
            $acc := f32(0)
            for b in 0:nb {
                $isum := 0
                q_base := q_off + b * 16
                x_base := xm_q + b * 32
                for j in 0:16 {
                    bv := int(qs[q_base + j])
                    q0 := (bv & 15) - 8
                    q1 := (bv >> 4) - 8
                    isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
                }
                acc += f32(isum) * (ws[s_off + b] * xs[xm_s + b])
            }
            out[out_off + r] = acc
        }
    }
}

fn main() int {
    args := os.argv()
    kind := args[1]
    if kind == "quant_q8" {
        n := 4096
        nb := 128
        $x := []f32{}
        $xq := []i8{}
        $xs := []f32{}
        for i in 0:n {
            x.push(f32(f64((i % 29) - 14) * 0.0625))
            xq.push(i8(0))
        }
        for _ in 0:nb { xs.push(f32(0)) }
        $elapsed := [100]int{}
        $cs := 0
        for s in 0:120 {
            t0 := time.now()
            bench_quantize(&x, $&xq, $&xs, nb)
            d := time.since(t0)
            if s >= 20 { elapsed[s - 20] = d }
            cs += int(xq[s % n]) + bits(xs[s % nb])
        }
        println(cs)
        for i in 0:100 { println(elapsed[i]) }
        << 0
    }
    m_cnt := 32
    n_cnt := 512
    k_cnt := 512
    nb := 16
    if kind == "gemv_q8" {
        $out := []f32{}
        $wqs := []i8{}
        $ws := []f32{}
        $xq := []i8{}
        $xs := []f32{}
        for _ in 0:n_cnt { out.push(f32(0)) }
        for i in 0:n_cnt * k_cnt { wqs.push(i8(((i * 19) % 240) - 120)) }
        for i in 0:n_cnt * nb { ws.push(f32(f64((i % 13) - 6) * 0.03125)) }
        for i in 0:k_cnt { xq.push(i8(((i * 17) % 240) - 120)) }
        for i in 0:nb { xs.push(f32(f64((i % 7) + 1) * 0.015625)) }
        $elapsed := [100]int{}
        $cs := 0
        for s in 0:120 {
            t0 := time.now()
            bench_gemv_q8(n_cnt, nb, $&out, &wqs, &ws, &xq, &xs)
            d := time.since(t0)
            if s >= 20 { elapsed[s - 20] = d }
            cs += bits(out[s % n_cnt])
        }
        println(cs)
        for i in 0:100 { println(elapsed[i]) }
        << 0
    }
    if kind == "gemm_f32" {
        $out := []f32{}
        $w := []f32{}
        $x := []f32{}
        for _ in 0:m_cnt * n_cnt { out.push(f32(0)) }
        for i in 0:n_cnt * k_cnt { w.push(f32(f64((i % 13) - 6) * 0.03125)) }
        for i in 0:m_cnt * k_cnt { x.push(f32(f64((i % 11) - 5) * 0.0625)) }
        $elapsed := [40]int{}
        $cs := 0
        for s in 0:48 {
            t0 := time.now()
            bench_gemm_f32(m_cnt, n_cnt, k_cnt, $&out, &w, &x)
            d := time.since(t0)
            if s >= 8 { elapsed[s - 8] = d }
            cs += bits(out[s % (m_cnt * n_cnt)])
        }
        println(cs)
        for i in 0:40 { println(elapsed[i]) }
        << 0
    }
    $out := []f32{}
    $qs := []u8{}
    $ws := []f32{}
    $xq := []i8{}
    $xs := []f32{}
    for _ in 0:m_cnt * n_cnt { out.push(f32(0)) }
    for i in 0:n_cnt * nb * 16 { qs.push(u8((i * 73 + 11) & 255)) }
    for i in 0:n_cnt * nb { ws.push(f32(f64((i % 13) - 6) * 0.03125)) }
    for i in 0:m_cnt * k_cnt { xq.push(i8(((i * 17) % 240) - 120)) }
    for i in 0:m_cnt * nb { xs.push(f32(f64((i % 7) + 1) * 0.015625)) }
    $elapsed := [40]int{}
    $cs := 0
    for s in 0:48 {
        t0 := time.now()
        bench_gemm_q4(m_cnt, n_cnt, nb, $&out, &qs, &ws, &xq, &xs)
        d := time.since(t0)
        if s >= 8 { elapsed[s - 8] = d }
        cs += bits(out[s % (m_cnt * n_cnt)])
    }
    println(cs)
    for i in 0:40 { println(elapsed[i]) }
    << 0
}
"""


def benchmark(compiler, env, work):
    source = work / "bench_gemm.xu"
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
        for kind in ("quant_q8", "gemv_q8", "gemm_f32", "gemm_q4"):
            checksum, *samples = map(int, run([exe, kind]).splitlines())
            if mode == "baseline":
                strict_totals[kind] = checksum
            elif mode == "neon-strict":
                assert checksum == strict_totals[kind], (kind, checksum, strict_totals[kind])
            samples.sort()
            p50 = samples[len(samples) // 2 - 1]
            p99 = samples[len(samples) * 99 // 100 - 1]
            print(f"{kind:10} {mode:11} n={len(samples):3} P50={p50:9} ns P99={p99:9} ns")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    with WindowsTemporaryDirectory(prefix="xu-tensor-gemm-") as td:
        work = Path(td)
        src = work / "tensor_gemm.xu"
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
                assert "call __xu_tensor_quantize_q8_0(" in functions["kernel_quantize_q8"]
                assert "call __xu_tensor_gemv4_q8_0_q8_0_f32(" in functions["kernel_gemv_q8_q8"]
                assert "call __xu_tensor_gemm4x4_f32(" in functions["kernel_gemm_f32"]
                assert "call __xu_tensor_gemm4x4_q4_0_q8_0_f32(" in functions["kernel_gemm_q4_q8"]
                check_arm64_disassembly(exe, fast_math=False)
            elif mode == "fast-math":
                assert "call __xu_tensor_quantize_q8_0_fast(" in functions["kernel_quantize_q8"]
                assert "call __xu_tensor_gemv4_q8_0_q8_0_fast_f32(" in functions["kernel_gemv_q8_q8"]
                assert "call __xu_tensor_gemm4x4_fast_f32(" in functions["kernel_gemm_f32"]
                assert "call __xu_tensor_gemm4x4_q4_0_q8_0_fast_f32(" in functions["kernel_gemm_q4_q8"]
                check_arm64_disassembly(exe, fast_math=True)

            out = run([exe]).splitlines()
            if mode == "baseline":
                baseline_out = out
            elif mode != "fast-math":
                assert out == baseline_out, (mode, "bit-exact mismatch vs baseline")
            else:
                for pfx in ("overlap:",):
                    assert [l for l in out if l.startswith(pfx)] == [l for l in baseline_out if l.startswith(pfx)]
                for pfx in ("sq8g:", "sgf:", "sgq:"):
                    b_lines = [l for l in baseline_out if l.startswith(pfx)]
                    f_lines = [l for l in out if l.startswith(pfx)]
                    assert len(b_lines) == len(f_lines)
                    for lb, lf in zip(b_lines, f_lines):
                        pb = lb.split(":")
                        pf = lf.split(":")
                        assert abs(bits_to_f32(pb[2]) - bits_to_f32(pf[2])) < 1e-4, (lb, lf)

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
        print("macos-x64 cross-compile and SSE2 quantize/Q8/GEMM disassembly passed")
        if args.benchmark:
            benchmark(compiler, env, work)


if __name__ == "__main__":
    main()
