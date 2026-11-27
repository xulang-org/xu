#!/usr/bin/env python3
"""Verify Phase 5 compiler optimizations: slice.reserve, SwiGLU, Argmax, RMSNorm-batch, p4 GEMV/GEMM."""

import argparse
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import tempfile

from test_tensor_dynamic import mir_functions
from test_tensor_fusion import PRELUDE, build, run
from test_windows_workers import WindowsTemporaryDirectory


def xu_source():
    return """@main
#math
#os
#time

fn bits(value f32) int { << math.float32_bits(f64(value)) }
fn from_bits(value int) f32 { << f32(math.float32_from_bits(value)) }

fn check_reserve() int {
    $s := []int{}
    s.reserve(1000)
    $c0 := 0
    $p0 := 0
    unsafe {
        d := (&s) as *raw int
        p0 = *d
        cap_p := ((d as int) + 16) as *raw int
        c0 = *cap_p
    }
    if s.len != 0 || c0 != 1000 { << 1 }
    for i in 0:1000 { s.push(i * 3 + 1) }
    $p1 := 0
    $c1 := 0
    unsafe {
        d := (&s) as *raw int
        p1 = *d
        cap_p := ((d as int) + 16) as *raw int
        c1 = *cap_p
    }
    if s.len != 1000 || c1 != 1000 || p0 == 0 || p1 != p0 { << 2 }
    for i in 0:1000 {
        if s[i] != i * 3 + 1 { << 3 }
    }
    s.reserve(100)
    $c2 := 0
    unsafe {
        d := (&s) as *raw int
        cap_p := ((d as int) + 16) as *raw int
        c2 = *cap_p
    }
    if c2 != 1000 || s.len != 1000 { << 4 }

    $s2 := []int{}
    for i in 0:5 { s2.push(i + 10) }
    s2.reserve(64)
    $c3 := 0
    unsafe {
        d := (&s2) as *raw int
        cap_p := ((d as int) + 16) as *raw int
        c3 = *cap_p
    }
    if c3 < 64 || s2.len != 5 { << 5 }
    for i in 0:5 {
        if s2[i] != i + 10 { << 6 }
    }
    << 0
}

fn kernel_swiglu(dst $&[]f32, gate &[]f32, up &[]f32, n int) {
    for i in 0:n {
        g := gate[i]
        silu := f32(f64(g) / (1.0 + math.exp(f64(-g))))
        dst[i] = silu * up[i]
    }
}

fn kernel_swiglu_inplace(hb $&[]f32, hb2 &[]f32, n int) {
    for i in 0:n {
        g := hb[i]
        silu := f32(f64(g) / (1.0 + math.exp(f64(-g))))
        hb[i] = silu * hb2[i]
    }
}

fn kernel_argmax(x &[]f32, n int) int {
    $best_i := 0
    $best_v := x[0]
    for i in 1:n {
        if x[i] > best_v {
            best_v = x[i]
            best_i = i
        }
    }
    << (best_i << 32) | (bits(best_v) & 0xffffffff)
}

fn kernel_rmsnorm_batch(n int, m_cnt int, x &[]f32, weight &[]f32, out $&[]f32, eps f64) {
    for t in 0:m_cnt {
        base := t * n
        $sum := f32(0)
        for j in 0:n {
            v := x[base + j]
            sum += v * v
        }
        inv := f32(1.0 / math.sqrt(f64(sum) / f64(n) + eps))
        for k in 0:n {
            out[base + k] = (x[base + k] * inv) * weight[k]
        }
    }
}

fn kernel_gemv_q4_p4(out $&[]f32, qs_p &[]u8, ws_p &[]f32, p4_blk_off int,
                     xq &[]i8, xs &[]f32, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for rg in 0:rg_cnt {
        g_off := p4_blk_off + rg * nb
        out_off := rg * 4
        for r4 in 0:4 {
            $acc := f32(0)
            for b in 0:nb {
                gb := g_off + b
                q_base := gb * 64 + r4 * 16
                x_base := b * 32
                $isum := 0
                for j in 0:16 {
                    bv := int(qs_p[q_base + j])
                    q0 := (bv & 15) - 8
                    q1 := (bv >> 4) - 8
                    isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
                }
                acc += f32(isum) * (ws_p[gb * 4 + r4] * xs[b])
            }
            out[out_off + r4] = acc
        }
    }
}

fn kernel_gemv_q4_unpacked(out $&[]f32, qs &[]u8, ws &[]f32, blk_off int,
                           xq &[]i8, xs &[]f32, rows int, cols int) {
    nb := cols / 32
    for r in 0:rows {
        s_off := blk_off + r * nb
        q_off := s_off * 16
        $acc := f32(0)
        for b in 0:nb {
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

fn kernel_gemv_q8_p4(out $&[]f32, qs_p &[]i8, ws_p &[]f32, p4_blk_off int,
                     xq &[]i8, xs &[]f32, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for rg in 0:rg_cnt {
        g_off := p4_blk_off + rg * nb
        out_off := rg * 4
        for r4 in 0:4 {
            $acc := f32(0)
            for b in 0:nb {
                gb := g_off + b
                q_base := gb * 128 + r4 * 32
                x_base := b * 32
                $isum := 0
                for j in 0:32 {
                    isum += int(qs_p[q_base + j]) * int(xq[x_base + j])
                }
                acc += f32(isum) * (ws_p[gb * 4 + r4] * xs[b])
            }
            out[out_off + r4] = acc
        }
    }
}

fn kernel_gemv_q8_unpacked(out $&[]f32, qs &[]i8, ws &[]f32, blk_off int,
                           xq &[]i8, xs &[]f32, rows int, cols int) {
    nb := cols / 32
    for r in 0:rows {
        s_off := blk_off + r * nb
        q_off := s_off * 32
        $acc := f32(0)
        for b in 0:nb {
            $isum := 0
            q_base := q_off + b * 32
            x_base := b * 32
            for j in 0:32 {
                isum += int(qs[q_base + j]) * int(xq[x_base + j])
            }
            acc += f32(isum) * (ws[s_off + b] * xs[b])
        }
        out[r] = acc
    }
}

fn kernel_gemm_q4_p4(out $&[]f32, qs_p &[]u8, ws_p &[]f32, p4_blk_off int,
                     xq &[]i8, xs &[]f32, m_cnt int, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for m in 0:m_cnt {
        xm_s := m * nb
        xm_q := xm_s * 32
        m_out := m * rows
        for rg in 0:rg_cnt {
            g_off := p4_blk_off + rg * nb
            out_off := m_out + rg * 4
            for r4 in 0:4 {
                $acc := f32(0)
                for b in 0:nb {
                    gb := g_off + b
                    q_base := gb * 64 + r4 * 16
                    x_base := xm_q + b * 32
                    $isum := 0
                    for j in 0:16 {
                        bv := int(qs_p[q_base + j])
                        q0 := (bv & 15) - 8
                        q1 := (bv >> 4) - 8
                        isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
                    }
                    acc += f32(isum) * (ws_p[gb * 4 + r4] * xs[xm_s + b])
                }
                out[out_off + r4] = acc
            }
        }
    }
}

fn kernel_gemm_q4_unpacked(out $&[]f32, qs &[]u8, ws &[]f32, blk_off int,
                           xq &[]i8, xs &[]f32, m_cnt int, rows int, cols int) {
    nb := cols / 32
    for m in 0:m_cnt {
        xm_s := m * nb
        xm_q := xm_s * 32
        out_off := m * rows
        for r in 0:rows {
            s_off := blk_off + r * nb
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

fn kernel_gemm_q4_p4_f16(out $&[]f32, qs_p &[]u8, ws_p &[]u16, p4_blk_off int,
                         xq &[]i8, xs &[]f32, m_cnt int, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for m in 0:m_cnt {
        xm_s := m * nb
        xm_q := xm_s * 32
        m_out := m * rows
        for rg in 0:rg_cnt {
            g_off := p4_blk_off + rg * nb
            out_off := m_out + rg * 4
            for r4 in 0:4 {
                $acc := f32(0)
                for b in 0:nb {
                    gb := g_off + b
                    q_base := gb * 64 + r4 * 16
                    x_base := xm_q + b * 32
                    $isum := 0
                    for j in 0:16 {
                        bv := int(qs_p[q_base + j])
                        q0 := (bv & 15) - 8
                        q1 := (bv >> 4) - 8
                        isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
                    }
                    acc += f32(isum) * (math.float16_to_f32(int(ws_p[gb * 4 + r4])) * xs[xm_s + b])
                }
                out[out_off + r4] = acc
            }
        }
    }
}

fn kernel_gemv_q4_p4_f16(out $&[]f32, qs_p &[]u8, ws_p &[]u16, p4_blk_off int,
                         xq &[]i8, xs &[]f32, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for rg in 0:rg_cnt {
        g_off := p4_blk_off + rg * nb
        out_off := rg * 4
        for r4 in 0:4 {
            $acc := f32(0)
            for b in 0:nb {
                gb := g_off + b
                q_base := gb * 64 + r4 * 16
                x_base := b * 32
                $isum := 0
                for j in 0:16 {
                    bv := int(qs_p[q_base + j])
                    q0 := (bv & 15) - 8
                    q1 := (bv >> 4) - 8
                    isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
                }
                acc += f32(isum) * (math.float16_to_f32(int(ws_p[gb * 4 + r4])) * xs[b])
            }
            out[out_off + r4] = acc
        }
    }
}

fn kernel_gemv_q8_p4_f16(out $&[]f32, qs_p &[]i8, ws_p &[]u16, p4_blk_off int,
                         xq &[]i8, xs &[]f32, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for rg in 0:rg_cnt {
        g_off := p4_blk_off + rg * nb
        out_off := rg * 4
        for r4 in 0:4 {
            $acc := f32(0)
            for b in 0:nb {
                gb := g_off + b
                q_base := gb * 128 + r4 * 32
                x_base := b * 32
                $isum := 0
                for j in 0:32 {
                    isum += int(qs_p[q_base + j]) * int(xq[x_base + j])
                }
                acc += f32(isum) * (math.float16_to_f32(int(ws_p[gb * 4 + r4])) * xs[b])
            }
            out[out_off + r4] = acc
        }
    }
}

fn kernel_rope(vec $&[]f32, h_off int, half int, cos_tbl &[]f32, sin_tbl &[]f32, rope_off int) {
    h_off1 := h_off + half
    for j in 0:half {
        c := cos_tbl[rope_off + j]
        s := sin_tbl[rope_off + j]
        v0 := vec[h_off + j]
        v1 := vec[h_off1 + j]
        vec[h_off + j] = f32(v0 * c - v1 * s)
        vec[h_off1 + j] = f32(v0 * s + v1 * c)
    }
}

fn kernel_vscale(dst $&[]f32, off_d int, x &[]f32, off_x int, s f32, n int) {
    for d in 0:n {
        dst[off_d + d] = x[off_x + d] * s
    }
}

fn kernel_vscale_inplace(x $&[]f32, off int, s f32, n int) {
    for d in 0:n {
        x[off + d] = x[off + d] * s
    }
}

fn kernel_copy16_32(dst_u8 $&[]u8, off_u int, dst_i8 $&[]i8, off_i int, src &string, p int) {
    for j in 0:16 {
        dst_u8[off_u + j] = u8(src[p + j])
    }
    for j in 0:32 {
        dst_i8[off_i + j] = i8(src[p + j])
    }
}

fn hash_f32(arr &[]f32, n int) int {
    $h := 17
    for i in 0:n {
        h = (h * 1315423911 + bits(arr[i]) + i) & 0x7fffffffffffffff
    }
    << h
}

fn zeros_f32(n int) []f32 {
    $v := []f32{}
    v.reserve(n)
    for _ in 0:n { v.push(f32(0)) }
    << v
}

fn check_swiglu() int {
    edges := [f32(-100.0), f32(-20.0), f32(-10.0), f32(-1.0), f32(-0.01),
              f32(0.0), f32(0.01), f32(1.0), f32(10.0), f32(20.0), f32(100.0)]
    lens := [0, 1, 2, 3, 4, 5, 7, 8, 13, 128, 4864]
    for li in 0:lens.len {
        n := lens[li]
        $gate := []f32{}
        $up := []f32{}
        $dst := zeros_f32(n + 3)
        for i in 0:n {
            if i < edges.len {
                gate.push(edges[i])
            } else {
                gate.push(f32(f64(((i * 37) % 200) - 100) * 0.097))
            }
            up.push(f32(f64(((i * 53) % 140) - 70) * 0.0625))
        }
        kernel_swiglu($&dst, &gate, &up, n)
        for i in 0:n { println("SWIGLU:" + str(n) + ":" + str(i) + ":" + str(bits(dst[i]))) }

        $ip := []f32{}
        for i in 0:n { ip.push(gate[i]) }
        kernel_swiglu_inplace($&ip, &up, n)
        for i in 0:n {
            if bits(ip[i]) != bits(dst[i]) { << 1 }
        }
        if n == 13 {
            // Runtime overlap guard via unsafe descriptor alias: dst == up[1:] must take scalar fallback cleanly.
            $buf := []f32{}
            for i in 0:n + 2 {
                if i < n {
                    buf.push(up[i])
                } else {
                    buf.push(f32(0))
                }
            }
            $alias_dst := zeros_f32(n)
            unsafe {
                du := (&buf) as *raw int
                dd := ($&alias_dst) as *raw int
                saved := *dd
                *dd = *du + 4
                kernel_swiglu($&alias_dst, &gate, &buf, n)
                *dd = saved
            }
            println("SWIGLU_ALIAS:" + str(hash_f32(&buf, n + 2)))
        }
    }
    << 0
}

fn check_argmax() int {
    lens := [1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 1023, 1024]
    for li in 0:lens.len {
        n := lens[li]
        // Case A: negative values, pseudo-random variation across lanes and tail.
        $a := []f32{}
        for i in 0:n {
            a.push(f32(-1000.0 + f64(((i * 73 + n * 19) % 517)) * 0.5))
        }
        r0 := kernel_argmax(&a, n)
        println("ARGMAX:A:" + str(n) + ":" + str(r0))

        // Case B: ties — lowest index must win even across SIMD lanes.
        $b := []f32{}
        for i in 0:n {
            if i == 1 || i == 2 || i == n - 1 || (n > 8 && i == 5) {
                b.push(f32(5.5))
            } else {
                b.push(f32(-2.0 + f64(i % 4)))
            }
        }
        r1 := kernel_argmax(&b, n)
        println("ARGMAX:B:" + str(n) + ":" + str(r1))

        // Case C: max at index 0.
        $c := []f32{}
        for i in 0:n {
            if i == 0 { c.push(f32(99.5)) } else { c.push(f32(f64(i % 13))) }
        }
        r2 := kernel_argmax(&c, n)
        println("ARGMAX:C:" + str(n) + ":" + str(r2))
    }
    << 0
}

fn check_rms_batch() int {
    ms := [1, 4, 32]
    ns := [1, 3, 4, 7, 16, 896]
    for mi in 0:ms.len {
        m := ms[mi]
        for ni in 0:ns.len {
            n := ns[ni]
            $x := []f32{}
            $w := []f32{}
            $out := zeros_f32(m * n)
            for i in 0:m * n {
                x.push(f32(f64(((i * 29 + 3) % 41) - 20) * 0.125))
            }
            for i in 0:n {
                w.push(f32(0.5 + f64((i * 11) % 17) * 0.0625))
            }
            kernel_rmsnorm_batch(n, m, &x, &w, $&out, 1e-6)
            println("RMSBATCH:" + str(m) + ":" + str(n) + ":" + str(hash_f32(&out, m * n)))
        }
    }
    << 0
}

fn check_p4_quant() int {
    ms := [1, 2, 3, 4, 5, 7, 8, 9, 12, 32]
    ns := [4, 8, 12, 64]
    nbs := [1, 2, 3, 4, 28]
    for ni in 0:ns.len {
        rows := ns[ni]
        rg_cnt := rows / 4
        for bi in 0:nbs.len {
            nb := nbs[bi]
            cols := nb * 32
            // Include leading dummy group-blocks to test non-zero p4_blk_off!
            prefix_gb := 3
            prefix_blk := prefix_gb * 4
            $q4_qs := []u8{}
            $q4_ws := []f32{}
            $q8_qs := []i8{}
            $q8_ws := []f32{}
            for _ in 0:prefix_blk * 16 { q4_qs.push(u8(0x55)) }
            for _ in 0:prefix_blk * 32 { q8_qs.push(i8(3)) }
            for _ in 0:prefix_blk {
                q4_ws.push(f32(0.25))
                q8_ws.push(f32(0.25))
            }
            for r in 0:rows {
                for b in 0:nb {
                    q4_ws.push(f32(f64(((r * 13 + b * 7) % 19) - 9) * 0.03125))
                    q8_ws.push(f32(f64(((r * 17 + b * 5) % 19) - 9) * 0.015625))
                    for j in 0:16 {
                        lo := (r * 3 + b * 5 + j * 7) & 15
                        hi := (r * 11 + b * 3 + j * 13 + 5) & 15
                        q4_qs.push(u8(lo | (hi << 4)))
                    }
                    for j in 0:32 {
                        v := ((r * 19 + b * 23 + j * 7) % 241) - 120
                        q8_qs.push(i8(v))
                    }
                }
            }

            $q4_p4_qs := []u8{}
            $q4_p4_ws := []f32{}
            $q8_p4_qs := []i8{}
            $q8_p4_ws := []f32{}
            for _ in 0:prefix_gb * 64 { q4_p4_qs.push(u8(0)) }
            for _ in 0:prefix_gb * 128 { q8_p4_qs.push(i8(0)) }
            for _ in 0:prefix_gb * 4 {
                q4_p4_ws.push(f32(0))
                q8_p4_ws.push(f32(0))
            }
            for rg in 0:rg_cnt {
                for b in 0:nb {
                    for r4 in 0:4 {
                        row := rg * 4 + r4
                        blk := prefix_blk + row * nb + b
                        q4_p4_ws.push(q4_ws[blk])
                        q8_p4_ws.push(q8_ws[blk])
                    }
                    for r4 in 0:4 {
                        row := rg * 4 + r4
                        blk := prefix_blk + row * nb + b
                        for j in 0:16 { q4_p4_qs.push(q4_qs[blk * 16 + j]) }
                        for j in 0:32 { q8_p4_qs.push(q8_qs[blk * 32 + j]) }
                    }
                }
            }

            // Single-token activations -> compare Q4_p4 vs unpacked Q4 AND Q8_p4 vs unpacked Q8.
            $xq1 := []i8{}
            $xs1 := []f32{}
            for b in 0:nb {
                xs1.push(f32(f64(((b * 7) % 11) + 1) * 0.0625))
                for j in 0:32 {
                    xq1.push(i8(((b * 17 + j * 13) % 241) - 120))
                }
            }
            $o_p4_q4 := zeros_f32(rows)
            $o_unp_q4 := zeros_f32(rows)
            $o_p4_q8 := zeros_f32(rows)
            $o_unp_q8 := zeros_f32(rows)
            kernel_gemv_q4_p4($&o_p4_q4, &q4_p4_qs, &q4_p4_ws, prefix_gb, &xq1, &xs1, rows, cols)
            kernel_gemv_q4_unpacked($&o_unp_q4, &q4_qs, &q4_ws, prefix_blk, &xq1, &xs1, rows, cols)
            kernel_gemv_q8_p4($&o_p4_q8, &q8_p4_qs, &q8_p4_ws, prefix_gb, &xq1, &xs1, rows, cols)
            kernel_gemv_q8_unpacked($&o_unp_q8, &q8_qs, &q8_ws, prefix_blk, &xq1, &xs1, rows, cols)
            for r in 0:rows {
                if bits(o_p4_q4[r]) != bits(o_unp_q4[r]) {
                    eprintln("q4 p4!=unp rows=" + str(rows) + " nb=" + str(nb) + " r=" + str(r))
                    << 1
                }
                if bits(o_p4_q8[r]) != bits(o_unp_q8[r]) {
                    eprintln("q8 p4!=unp rows=" + str(rows) + " nb=" + str(nb) + " r=" + str(r))
                    << 2
                }
            }
            println("GEMV4_Q4_P4:" + str(rows) + ":" + str(nb) + ":" + str(hash_f32(&o_p4_q4, rows)))
            println("GEMV4_Q8_P4:" + str(rows) + ":" + str(nb) + ":" + str(hash_f32(&o_p4_q8, rows)))

            // GEMM shapes (only select representative pairs for large M to keep runtime quick)
            for mi in 0:ms.len {
                m := ms[mi]
                $xq := []i8{}
                $xs := []f32{}
                for t in 0:m {
                    for b in 0:nb {
                        xs.push(f32(f64(((t * 5 + b * 7) % 13) + 1) * 0.03125))
                        for j in 0:32 {
                            xq.push(i8(((t * 31 + b * 17 + j * 9) % 241) - 120))
                        }
                    }
                }
                $m_p4 := zeros_f32(m * rows)
                $m_unp := zeros_f32(m * rows)
                kernel_gemm_q4_p4($&m_p4, &q4_p4_qs, &q4_p4_ws, prefix_gb, &xq, &xs, m, rows, cols)
                kernel_gemm_q4_unpacked($&m_unp, &q4_qs, &q4_ws, prefix_blk, &xq, &xs, m, rows, cols)
                for idx in 0:m * rows {
                    if bits(m_p4[idx]) != bits(m_unp[idx]) {
                        eprintln("gemm q4 p4!=unp m=" + str(m) + " rows=" + str(rows) + " nb=" + str(nb))
                        << 3
                    }
                }
                println("GEMM4X8_Q4_P4:" + str(m) + ":" + str(rows) + ":" + str(nb) + ":" + str(hash_f32(&m_p4, m * rows)))
            }
        }
    }
    << 0
}

fn run_bench() int {
    // SwiGLU (4864)
    $g := []f32{}
    $u := []f32{}
    $d := zeros_f32(4864)
    for i in 0:4864 {
        g.push(f32(f64((i % 21) - 10) * 0.25))
        u.push(f32(f64((i % 13) - 6) * 0.125))
    }
    $cs := 0
    for _ in 0:50 { kernel_swiglu($&d, &g, &u, 4864) }
    t0 := time.now()
    for _ in 0:2000 {
        kernel_swiglu($&d, &g, &u, 4864)
        cs += bits(d[0])
    }
    println("BENCH:swiglu_4864_ns:" + str(time.since(t0) / 2000) + ":" + str(cs))

    // Argmax (151936)
    $lv := []f32{}
    for i in 0:151936 { lv.push(f32(f64((i * 17) % 1009) * 0.01)) }
    lv[123456] = f32(99.5)
    for _ in 0:20 { _ := kernel_argmax(&lv, 151936) }
    t1 := time.now()
    for _ in 0:200 { cs += kernel_argmax(&lv, 151936) }
    println("BENCH:argmax_151936_ns:" + str(time.since(t1) / 200) + ":" + str(cs))

    // GEMV4 Q4_0_p4 (4864 x 896 -> rg=1216, nb=28)
    $xq := []i8{}
    $xs := []f32{}
    for _ in 0:32 * 28 { xs.push(f32(0.05)) }
    for i in 0:32 * 896 { xq.push(i8((i % 91) - 45)) }
    $q4_p4_qs := []u8{}
    $q4_p4_ws := []f32{}
    q4_p4_qs.reserve(1216 * 28 * 64)
    q4_p4_ws.reserve(1216 * 28 * 4)
    for i in 0:1216 * 28 * 64 { q4_p4_qs.push(u8((i * 7) & 255)) }
    for i in 0:1216 * 28 * 4 { q4_p4_ws.push(f32(0.02)) }
    $out4864 := zeros_f32(4864)
    for _ in 0:10 { kernel_gemv_q4_p4($&out4864, &q4_p4_qs, &q4_p4_ws, 0, &xq, &xs, 4864, 896) }
    t2 := time.now()
    for _ in 0:100 {
        kernel_gemv_q4_p4($&out4864, &q4_p4_qs, &q4_p4_ws, 0, &xq, &xs, 4864, 896)
        cs += bits(out4864[0])
    }
    println("BENCH:gemv4_q4_p4_4864x896_ns:" + str(time.since(t2) / 100) + ":" + str(cs))

    // GEMM4x8 Q4_0_p4 (M=32, 4864 x 896)
    $outm := zeros_f32(32 * 4864)
    for _ in 0:3 { kernel_gemm_q4_p4($&outm, &q4_p4_qs, &q4_p4_ws, 0, &xq, &xs, 32, 4864, 896) }
    t3 := time.now()
    for _ in 0:20 {
        kernel_gemm_q4_p4($&outm, &q4_p4_qs, &q4_p4_ws, 0, &xq, &xs, 32, 4864, 896)
        cs += bits(outm[0])
    }
    println("BENCH:gemm4x8_q4_p4_32x4864x896_ns:" + str(time.since(t3) / 20) + ":" + str(cs))

    // GEMV4 Q8_0_p4 (151936 x 896 -> rg=37984, nb=28)
    $q8_p4_qs := []i8{}
    $q8_p4_ws := []f32{}
    q8_p4_qs.reserve(37984 * 28 * 128)
    q8_p4_ws.reserve(37984 * 28 * 4)
    for i in 0:37984 * 28 * 128 { q8_p4_qs.push(i8((i % 11) - 5)) }
    for i in 0:37984 * 28 * 4 { q8_p4_ws.push(f32(0.01)) }
    $outv := zeros_f32(151936)
    for _ in 0:2 { kernel_gemv_q8_p4($&outv, &q8_p4_qs, &q8_p4_ws, 0, &xq, &xs, 151936, 896) }
    t4 := time.now()
    for _ in 0:10 {
        kernel_gemv_q8_p4($&outv, &q8_p4_qs, &q8_p4_ws, 0, &xq, &xs, 151936, 896)
        cs += bits(outv[0])
    }
    println("BENCH:gemv4_q8_p4_151936x896_ns:" + str(time.since(t4) / 10) + ":" + str(cs))
    << 0
}

fn check_resize_zero() int {
    $b := []u8{}
    b.resize_zero(128)
    if b.len != 128 { << 1 }
    for i in 0:128 {
        if int(b[i]) != 0 { << 2 }
        b[i] = u8((i * 7 + 3) & 255)
    }
    b.resize_zero(16)
    if b.len != 16 { << 3 }
    b.resize_zero(200)
    if b.len != 200 { << 4 }
    for i in 0:16 {
        if int(b[i]) != ((i * 7 + 3) & 255) { << 5 }
    }
    for i in 16:200 {
        if int(b[i]) != 0 { << 6 }
    }
    b.resize_zero(-5)
    if b.len != 200 { << 7 }

    $h := []u16{}
    h.resize_zero(64)
    if h.len != 64 { << 8 }
    for i in 0:8 { h[i] = u16(0x3C00 + i * 17) }
    h.resize_zero(8)
    h.resize_zero(100)
    if h.len != 100 { << 9 }
    for i in 0:8 {
        if int(h[i]) != 0x3C00 + i * 17 { << 10 }
    }
    for i in 8:100 {
        if int(h[i]) != 0 { << 11 }
    }

    $f := []f32{}
    f.resize_zero(300)
    if f.len != 300 { << 12 }
    for i in 0:10 { f[i] = f32(f64(i) + 0.5) }
    f.resize_zero(10)
    f.resize_zero(40)
    if f.len != 40 { << 13 }
    for i in 0:10 {
        if bits(f[i]) != bits(f32(f64(i) + 0.5)) { << 14 }
    }
    for i in 10:40 {
        if bits(f[i]) != 0 { << 15 }
    }
    << 0
}

fn check_copy16_32() int {
    $src := ""
    for i in 0:80 {
        src.push_byte((i * 19 + 131) & 255)
    }
    $du := []u8{}
    $di := []i8{}
    du.resize_zero(48)
    di.resize_zero(64)
    kernel_copy16_32($&du, 8, $&di, 12, &src, 13)
    for i in 0:8 {
        if int(du[i]) != 0 { << 1 }
    }
    for j in 0:16 {
        if int(du[8 + j]) != src[13 + j] { << 2 }
    }
    for i in 24:48 {
        if int(du[i]) != 0 { << 3 }
    }
    for i in 0:12 {
        if int(di[i]) != 0 { << 4 }
    }
    for j in 0:32 {
        $exp := src[13 + j]
        if exp >= 128 { exp -= 256 }
        if int(di[12 + j]) != exp { << 5 }
    }
    for i in 44:64 {
        if int(di[i]) != 0 { << 6 }
    }
    << 0
}

fn check_vscale() int {
    lens := [1, 3, 4, 7, 16, 64]
    for li in 0:lens.len {
        n := lens[li]
        $x := []f32{}
        $dst := []f32{}
        $ip := []f32{}
        x.resize_zero(n + 10)
        dst.resize_zero(n + 10)
        ip.resize_zero(n + 10)
        for i in 0:n + 10 {
            v := f32(f64(((i * 17) % 37) - 18) * 0.25)
            x[i] = v
            ip[i] = v
        }
        s := f32(0.1875)
        kernel_vscale($&dst, 5, &x, 3, s, n)
        kernel_vscale_inplace($&ip, 3, s, n)
        for i in 0:n {
            println("VSCALE:" + str(n) + ":" + str(i) + ":" + str(bits(dst[5 + i])) + ":" + str(bits(ip[3 + i])))
        }
    }
    << 0
}

fn check_rope() int {
    halves := [1, 3, 4, 7, 32, 64]
    for hi in 0:halves.len {
        half := halves[hi]
        $vec := []f32{}
        $cos_t := []f32{}
        $sin_t := []f32{}
        vec.resize_zero(half * 2 + 12)
        cos_t.resize_zero(half + 9)
        sin_t.resize_zero(half + 9)
        for i in 0:half * 2 + 12 {
            vec[i] = f32(f64(((i * 23) % 43) - 21) * 0.125)
        }
        for i in 0:half + 9 {
            ang := f64(i + 1) * 0.17
            cos_t[i] = f32(math.cos(ang))
            sin_t[i] = f32(math.sin(ang))
        }
        kernel_rope($&vec, 5, half, &cos_t, &sin_t, 4)
        for j in 0:half * 2 {
            println("ROPE:" + str(half) + ":" + str(j) + ":" + str(bits(vec[5 + j])))
        }
    }
    << 0
}

fn check_p4_f16() int {
    f16_vals := [0x3C00, 0x3800, 0xB800, 0x3555, 0x2C00, 0x0000, 0x0200, 0x8000, 0x3200]
    rgs := [1, 2, 3, 4, 15, 16]
    nbs := [1, 2, 3]
    ms := [1, 3, 4, 5, 8, 9, 12, 16, 32]
    for ri in 0:rgs.len {
        rg_cnt := rgs[ri]
        rows := rg_cnt * 4
        for bi in 0:nbs.len {
            nb := nbs[bi]
            cols := nb * 32
            prefix_gb := 3
            $q4_p4_qs := []u8{}
            $q4_p4_ws := []u16{}
            $q8_p4_qs := []i8{}
            $q8_p4_ws := []u16{}
            q4_p4_qs.resize_zero((prefix_gb + rg_cnt * nb) * 64)
            q4_p4_ws.resize_zero((prefix_gb + rg_cnt * nb) * 4)
            q8_p4_qs.resize_zero((prefix_gb + rg_cnt * nb) * 128)
            q8_p4_ws.resize_zero((prefix_gb + rg_cnt * nb) * 4)
            for rg in 0:rg_cnt {
                for b in 0:nb {
                    gb := prefix_gb + rg * nb + b
                    for r4 in 0:4 {
                        row := rg * 4 + r4
                        hv := f16_vals[(row * 7 + b * 3) % f16_vals.len]
                        q4_p4_ws[gb * 4 + r4] = u16(hv)
                        q8_p4_ws[gb * 4 + r4] = u16(f16_vals[(row * 5 + b * 11) % f16_vals.len])
                        for j in 0:16 {
                            lo := (row * 3 + b * 5 + j * 7) & 15
                            hi := (row * 11 + b * 3 + j * 13 + 5) & 15
                            q4_p4_qs[gb * 64 + r4 * 16 + j] = u8(lo | (hi << 4))
                        }
                        for j in 0:32 {
                            v := ((row * 19 + b * 23 + j * 7) % 241) - 120
                            q8_p4_qs[gb * 128 + r4 * 32 + j] = i8(v)
                        }
                    }
                }
            }
            $xq1 := []i8{}
            $xs1 := []f32{}
            xq1.resize_zero(nb * 32)
            xs1.resize_zero(nb)
            for b in 0:nb {
                xs1[b] = f32(f64(((b * 7) % 11) + 1) * 0.0625)
                for j in 0:32 {
                    xq1[b * 32 + j] = i8(((b * 17 + j * 13) % 241) - 120)
                }
            }
            $o_q4 := []f32{}
            $o_q8 := []f32{}
            o_q4.resize_zero(rows)
            o_q8.resize_zero(rows)
            kernel_gemv_q4_p4_f16($&o_q4, &q4_p4_qs, &q4_p4_ws, prefix_gb, &xq1, &xs1, rows, cols)
            kernel_gemv_q8_p4_f16($&o_q8, &q8_p4_qs, &q8_p4_ws, prefix_gb, &xq1, &xs1, rows, cols)
            for r in 0:rows {
                println("F16GEMVQ4:" + str(rows) + ":" + str(nb) + ":" + str(r) + ":" + str(bits(o_q4[r])))
                println("F16GEMVQ8:" + str(rows) + ":" + str(nb) + ":" + str(r) + ":" + str(bits(o_q8[r])))
            }

            if (rg_cnt == 1 || rg_cnt == 3 || rg_cnt == 15) && nb == 2 {
                for mi in 0:ms.len {
                    m := ms[mi]
                    $xq := []i8{}
                    $xs := []f32{}
                    xq.resize_zero(m * nb * 32)
                    xs.resize_zero(m * nb)
                    for t in 0:m {
                        for b in 0:nb {
                            xs[t * nb + b] = f32(f64(((t * 5 + b * 7) % 13) + 1) * 0.03125)
                            for j in 0:32 {
                                xq[(t * nb + b) * 32 + j] = i8(((t * 31 + b * 17 + j * 9) % 241) - 120)
                            }
                        }
                    }
                    $mo := []f32{}
                    mo.resize_zero(m * rows)
                    kernel_gemm_q4_p4_f16($&mo, &q4_p4_qs, &q4_p4_ws, prefix_gb, &xq, &xs, m, rows, cols)
                    for idx in 0:m * rows {
                        println("F16GEMMQ4:" + str(m) + ":" + str(rows) + ":" + str(nb) + ":" + str(idx) + ":" + str(bits(mo[idx])))
                    }
                }
            }
        }
    }
    << 0
}

fn kernel_pack_q4_p4k4_signed(chunk &string, qs_p $&[]u8, ws_p $&[]u16,
                                gb_start int, cg_cnt int, nb int, row_bytes int) {
    for cg in 0:cg_cnt {
        base0 := cg * 4 * row_bytes
        g_off := gb_start + cg * nb
        for b in 0:nb {
            gb := g_off + b
            b_off := b * 18
            s_base := gb * 4
            for r4 in 0:4 {
                p := base0 + r4 * row_bytes + b_off
                ws_p[s_base + r4] = u16(chunk[p] | (chunk[p + 1] << 8))
            }
            q_gb := gb * 64
            for r4 in 0:4 {
                p := base0 + r4 * row_bytes + b_off + 2
                q_dst := q_gb + r4 * 4
                for j in 0:16 {
                    qs_p[q_dst + (j >> 2) * 16 + (j & 3)] = u8(chunk[p + j] ^ 136)
                }
            }
        }
    }
}

fn kernel_pack_q8_p4k4(chunk &string, qs_p $&[]i8, ws_p $&[]u16,
                        gb_start int, cg_cnt int, nb int, row_bytes int) {
    for cg in 0:cg_cnt {
        base0 := cg * 4 * row_bytes
        g_off := gb_start + cg * nb
        for b in 0:nb {
            gb := g_off + b
            b_off := b * 34
            s_base := gb * 4
            for r4 in 0:4 {
                p := base0 + r4 * row_bytes + b_off
                ws_p[s_base + r4] = u16(chunk[p] | (chunk[p + 1] << 8))
            }
            q_gb := gb * 128
            for r4 in 0:4 {
                p := base0 + r4 * row_bytes + b_off + 2
                q_dst := q_gb + r4 * 4
                for j in 0:32 {
                    qs_p[q_dst + (j >> 2) * 16 + (j & 3)] = i8(chunk[p + j])
                }
            }
        }
    }
}

fn kernel_gemv_q4_p4k4_signed(out $&[]f32, qs_p &[]u8, ws_p &[]u16, p4_blk_off int,
                                xq &[]i8, xs &[]f32, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for rg in 0:rg_cnt {
        g_off := p4_blk_off + rg * nb
        out_off := rg * 4
        for r4 in 0:4 {
            $acc := f32(0)
            for b in 0:nb {
                gb := g_off + b
                q_base := gb * 64 + r4 * 4
                x_base := b * 32
                $isum := 0
                for j in 0:16 {
                    bv := int(qs_p[q_base + (j >> 2) * 16 + (j & 3)]) ^ 136
                    q0 := (bv & 15) - 8
                    q1 := (bv >> 4) - 8
                    isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
                }
                acc += f32(isum) * (math.float16_to_f32(int(ws_p[gb * 4 + r4])) * xs[b])
            }
            out[out_off + r4] = acc
        }
    }
}

fn kernel_gemv_q8_p4k4(out $&[]f32, qs_p &[]i8, ws_p &[]u16, p4_blk_off int,
                         xq &[]i8, xs &[]f32, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for rg in 0:rg_cnt {
        g_off := p4_blk_off + rg * nb
        out_off := rg * 4
        for r4 in 0:4 {
            $acc := f32(0)
            for b in 0:nb {
                gb := g_off + b
                q_base := gb * 128 + r4 * 4
                x_base := b * 32
                $isum := 0
                for j in 0:32 {
                    isum += int(qs_p[q_base + (j >> 2) * 16 + (j & 3)]) * int(xq[x_base + j])
                }
                acc += f32(isum) * (math.float16_to_f32(int(ws_p[gb * 4 + r4])) * xs[b])
            }
            out[out_off + r4] = acc
        }
    }
}

fn kernel_gemm_q4_p4k4_signed(out $&[]f32, qs_p &[]u8, ws_p &[]u16, p4_blk_off int,
                                xq &[]i8, xs &[]f32, m_cnt int, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for m in 0:m_cnt {
        xm_s := m * nb
        xm_q := xm_s * 32
        m_out := m * rows
        for rg in 0:rg_cnt {
            g_off := p4_blk_off + rg * nb
            out_off := m_out + rg * 4
            for r4 in 0:4 {
                $acc := f32(0)
                for b in 0:nb {
                    gb := g_off + b
                    q_base := gb * 64 + r4 * 4
                    x_base := xm_q + b * 32
                    $isum := 0
                    for j in 0:16 {
                        bv := int(qs_p[q_base + (j >> 2) * 16 + (j & 3)]) ^ 136
                        q0 := (bv & 15) - 8
                        q1 := (bv >> 4) - 8
                        isum += q0 * int(xq[x_base + j]) + q1 * int(xq[x_base + 16 + j])
                    }
                    acc += f32(isum) * (math.float16_to_f32(int(ws_p[gb * 4 + r4])) * xs[xm_s + b])
                }
                out[out_off + r4] = acc
            }
        }
    }
}

fn kernel_gemm_q8_p4k4(out $&[]f32, qs_p &[]i8, ws_p &[]u16, p4_blk_off int,
                         xq &[]i8, xs &[]f32, m_cnt int, rows int, cols int) {
    rg_cnt := rows / 4
    nb := cols / 32
    for m in 0:m_cnt {
        xm_s := m * nb
        xm_q := xm_s * 32
        m_out := m * rows
        for rg in 0:rg_cnt {
            g_off := p4_blk_off + rg * nb
            out_off := m_out + rg * 4
            for r4 in 0:4 {
                $acc := f32(0)
                for b in 0:nb {
                    gb := g_off + b
                    q_base := gb * 128 + r4 * 4
                    x_base := xm_q + b * 32
                    $isum := 0
                    for j in 0:32 {
                        isum += int(qs_p[q_base + (j >> 2) * 16 + (j & 3)]) * int(xq[x_base + j])
                    }
                    acc += f32(isum) * (math.float16_to_f32(int(ws_p[gb * 4 + r4])) * xs[xm_s + b])
                }
                out[out_off + r4] = acc
            }
        }
    }
}

fn kernel_attn_scores_paged(q &[]f32, keys &[]f32, bt &[]int, scores $&[]f32,
                            q_off int, bt_off int, block_stride int, kv_base int, kv_dim int,
                            head_dim int, seq_len int) {
    for t in 0:seq_len {
        pb := bt[bt_off + (t >> 4)]
        k_off := pb * block_stride + kv_base + (t & 15) * kv_dim
        $sum := f32(0)
        for j in 0:head_dim {
            sum += q[q_off + j] * keys[k_off + j]
        }
        scores[t] = sum
    }
}

fn kernel_softmax_scaled(scores $&[]f32, seq_len int, scale f32) {
    $max_v := scores[0] * scale
    scores[0] = max_v
    for t in 1:seq_len {
        v := scores[t] * scale
        scores[t] = v
        if v > max_v { max_v = v }
    }
    $sum_v := 0.0
    for t in 0:seq_len {
        ew := f32(math.exp(f64(scores[t] - max_v)))
        scores[t] = ew
        sum_v += f64(ew)
    }
    inv := f32(1.0 / sum_v)
    for t in 0:seq_len {
        scores[t] = scores[t] * inv
    }
}

fn kernel_attn_vsum_paged(out $&[]f32, scores &[]f32, v_blocks &[]f32, bt &[]int,
                          out_off int, bt_off int, block_stride int, kv_base_off int, kv_dim int,
                          head_dim int, seq_len int) {
    for d in 0:head_dim { out[out_off + d] = f32(0) }
    for t in 0:seq_len {
        w := scores[t]
        t_pb := bt[bt_off + (t >> 4)]
        v_off := t_pb * block_stride + kv_base_off + (t & 15) * kv_dim
        for d in 0:head_dim {
            out[out_off + d] += w * v_blocks[v_off + d]
        }
    }
}

fn check_phase7() int {
    // 1) Test p4k4_signed (Q4) and p4k4 (Q8) packing + GEMV + GEMM across rows/nb/m_cnt
    rows := 8
    nb := 3
    cols := nb * 32
    cg_cnt := rows / 4
    prefix_gb := 2
    $raw_q4 := ""
    $raw_q8 := ""
    for r in 0:rows {
        for b in 0:nb {
            sc := (0x3400 + ((r * 5 + b * 3) & 0x1ff))
            raw_q4.push_byte(sc & 255)
            raw_q4.push_byte((sc >> 8) & 255)
            for j in 0:16 {
                raw_q4.push_byte((r * 17 + b * 29 + j * 13) & 255)
            }
            raw_q8.push_byte(sc & 255)
            raw_q8.push_byte((sc >> 8) & 255)
            for j in 0:32 {
                raw_q8.push_byte((r * 23 + b * 31 + j * 11) & 255)
            }
        }
    }
    $q4_qs := []u8{}
    $q4_ws := []u16{}
    $q8_qs := []i8{}
    $q8_ws := []u16{}
    for _ in 0:(prefix_gb + cg_cnt * nb) * 64 { q4_qs.push(u8(0)) }
    for _ in 0:(prefix_gb + cg_cnt * nb) * 128 { q8_qs.push(i8(0)) }
    for _ in 0:(prefix_gb + cg_cnt * nb) * 4 {
        q4_ws.push(u16(0))
        q8_ws.push(u16(0))
    }
    kernel_pack_q4_p4k4_signed(&raw_q4, $&q4_qs, $&q4_ws, prefix_gb, cg_cnt, nb, nb * 18)
    kernel_pack_q8_p4k4(&raw_q8, $&q8_qs, $&q8_ws, prefix_gb, cg_cnt, nb, nb * 34)
    $h_q4p := 0
    for i in 0:q4_qs.len { h_q4p = (h_q4p * 131 + int(q4_qs[i])) & 0x7fffffff }
    for i in 0:q4_ws.len { h_q4p = (h_q4p * 131 + int(q4_ws[i])) & 0x7fffffff }
    $h_q8p := 0
    for i in 0:q8_qs.len { h_q8p = (h_q8p * 131 + (int(q8_qs[i]) & 255)) & 0x7fffffff }
    for i in 0:q8_ws.len { h_q8p = (h_q8p * 131 + int(q8_ws[i])) & 0x7fffffff }
    println("PACK_Q4K4:" + str(rows) + ":" + str(nb) + ":" + str(h_q4p))
    println("PACK_Q8K4:" + str(rows) + ":" + str(nb) + ":" + str(h_q8p))

    $xq1 := []i8{}
    $xs1 := []f32{}
    for b in 0:nb {
        xs1.push(f32(0.0625 * f64((b % 5) + 1)))
        for j in 0:32 { xq1.push(i8(((b * 17 + j * 13) % 241) - 120)) }
    }
    $ov4 := zeros_f32(rows)
    $ov8 := zeros_f32(rows)
    kernel_gemv_q4_p4k4_signed($&ov4, &q4_qs, &q4_ws, prefix_gb, &xq1, &xs1, rows, cols)
    kernel_gemv_q8_p4k4($&ov8, &q8_qs, &q8_ws, prefix_gb, &xq1, &xs1, rows, cols)
    for r in 0:rows {
        println("P7F32:GVQ4:" + str(r) + ":" + str(bits(ov4[r])))
        println("P7F32:GVQ8:" + str(r) + ":" + str(bits(ov8[r])))
    }

    m_cnt := 15
    $xqm := []i8{}
    $xsm := []f32{}
    for mi in 0:m_cnt {
        for b in 0:nb {
            xsm.push(f32(0.03125 * f64(((mi + b) % 7) + 1)))
            for j in 0:32 { xqm.push(i8(((mi * 19 + b * 11 + j * 7) % 241) - 120)) }
        }
    }
    $om4 := zeros_f32(m_cnt * rows)
    $om8 := zeros_f32(m_cnt * rows)
    kernel_gemm_q4_p4k4_signed($&om4, &q4_qs, &q4_ws, prefix_gb, &xqm, &xsm, m_cnt, rows, cols)
    kernel_gemm_q8_p4k4($&om8, &q8_qs, &q8_ws, prefix_gb, &xqm, &xsm, m_cnt, rows, cols)
    for i in 0:m_cnt * rows {
        println("P7F32:GMQ4:" + str(i) + ":" + str(bits(om4[i])))
        println("P7F32:GMQ8:" + str(i) + ":" + str(bits(om8[i])))
    }

    // 2) Test paged attention (head_dim=64 and head_dim=40) across >1 page (seq_len=23)
    hds := [64, 40]
    for hi in 0:hds.len {
        hd := hds[hi]
        seq_len := 23
        kv_dim := hd * 2
        bs := 16 * kv_dim + 8
        bt := [99, 2, 0, 1]
        bt_off := 1
        kv_base := 5
        num_pages := 3
        $k_blocks := zeros_f32(num_pages * bs)
        $v_blocks := zeros_f32(num_pages * bs)
        for pg in 0:num_pages {
            for t in 0:16 {
                base := pg * bs + kv_base + t * kv_dim
                for d in 0:hd {
                    k_blocks[base + d] = f32(f64(((pg * 31 + t * 13 + d * 7) % 29) - 14) * 0.0625)
                    v_blocks[base + d] = f32(f64(((pg * 19 + t * 17 + d * 5) % 23) - 11) * 0.0625)
                }
            }
        }
        $q := zeros_f32(hd + 8)
        q_off := 4
        for d in 0:hd { q[q_off + d] = f32(f64(((d * 11 + 3) % 19) - 9) * 0.125) }
        $scores := zeros_f32(seq_len)
        kernel_attn_scores_paged(&q, &k_blocks, &bt, $&scores, q_off, bt_off, bs, kv_base, kv_dim, hd, seq_len)
        for t in 0:seq_len {
            println("P7F32:ATSC:" + str(hd) + ":" + str(t) + ":" + str(bits(scores[t])))
        }
        kernel_softmax_scaled($&scores, seq_len, f32(0.125))
        for t in 0:seq_len {
            println("P7F32:ATSM:" + str(hd) + ":" + str(t) + ":" + str(bits(scores[t])))
        }
        $aout := zeros_f32(hd + 6)
        out_off := 3
        kernel_attn_vsum_paged($&aout, &scores, &v_blocks, &bt, out_off, bt_off, bs, kv_base, kv_dim, hd, seq_len)
        for d in 0:hd {
            println("P7F32:ATVS:" + str(hd) + ":" + str(d) + ":" + str(bits(aout[out_off + d])))
        }
    }
    << 0
}

fn main() int {
    args := os.argv()
    if args.len > 1 && args[1] == "bench" {
        << run_bench()
    }
    rc0 := check_reserve()
    if rc0 != 0 {
        eprintln("reserve failed: " + str(rc0))
        << 1
    }
    rc1 := check_resize_zero()
    if rc1 != 0 {
        eprintln("resize_zero failed: " + str(rc1))
        << 6
    }
    rc2 := check_copy16_32()
    if rc2 != 0 {
        eprintln("copy16_32 failed: " + str(rc2))
        << 7
    }
    if check_swiglu() != 0 { << 2 }
    if check_argmax() != 0 { << 3 }
    if check_rms_batch() != 0 { << 4 }
    if check_p4_quant() != 0 { << 5 }
    if check_phase7() != 0 { << 6 }
    if check_vscale() != 0 { << 8 }
    if check_rope() != 0 { << 9 }
    if check_p4_f16() != 0 { << 10 }
    << 0
}
"""


def parse_lines(out):
    swiglu = {}
    f32_vals = {}
    other = {}
    for line in out.splitlines():
        if line.startswith("SWIGLU:"):
            _, n, i, b = line.split(":")
            swiglu[(int(n), int(i))] = int(b)
        elif line.startswith(("VSCALE:", "ROPE:", "F16GEMVQ4:", "F16GEMVQ8:", "F16GEMMQ4:", "P7F32:")):
            k, v = line.rsplit(":", 1)
            if line.startswith("VSCALE:"):
                parts = line.split(":")
                f32_vals[("VSCALE_DST", parts[1], parts[2])] = int(parts[3])
                f32_vals[("VSCALE_IP", parts[1], parts[2])] = int(parts[4])
            else:
                f32_vals[k] = int(v)
        elif line.startswith(("ARGMAX:", "RMSBATCH:", "GEMV4_", "GEMM4X8_", "SWIGLU_ALIAS:", "PACK_Q4K4:", "PACK_Q8K4:")):
            k, v = line.rsplit(":", 1)
            other[k] = int(v)
    return swiglu, f32_vals, other


def bits_to_f32(b):
    return struct.unpack("<f", struct.pack("<I", b & 0xffffffff))[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]

    with WindowsTemporaryDirectory(prefix="xu-tensor-opt-") as td:
        work = Path(td)
        src = work / "tensor_opt.xu"
        src.write_text(xu_source())
        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_MIR_BORROW_GATE="1", XU_DUMP_MIR="_xu_main_kernel_", XU_KEEP_SYMBOLS="1")

        modes = (
            ("baseline", "0", "0", ()),
            ("strict", "1", "0", ()),
            ("fast", "1", "1", ()),
        )
        results = {}
        exes = {}
        for mode, fusion, fast, flags in modes:
            exe = work / f"opt-{mode}"
            mir = build(compiler, dict(env, XU_TENSOR_FUSION=fusion, XU_TENSOR_FAST_MATH=fast, XU_TASK_POLL="0"),
                        src, exe, flags)
            exes[mode] = exe
            funcs = mir_functions(mir)
            if mode == "baseline":
                for fn_mir in funcs.values():
                    assert "__xu_tensor_" not in fn_mir
            else:
                suf = "_fast" if fast == "1" else ""
                assert f"call __xu_tensor_swiglu{suf}_f32(" in funcs["kernel_swiglu"], mode
                assert f"call __xu_tensor_swiglu{suf}_f32(" in funcs["kernel_swiglu_inplace"], mode
                assert "call __xu_tensor_argmax_f32(" in funcs["kernel_argmax"], mode
                dot_suf = "_fast" if fast == "1" else ""
                assert f"call __xu_tensor_dot{dot_suf}_f32(" in funcs["kernel_rmsnorm_batch"], mode
                assert "call __xu_tensor_norm_f32(" in funcs["kernel_rmsnorm_batch"], mode
                assert "call __xu_tensor_norm_f32(" in funcs["kernel_vscale"], mode
                assert "call __xu_tensor_norm_f32(" in funcs["kernel_vscale_inplace"], mode
                assert "call __xu_tensor_rope_f32(" in funcs["kernel_rope"], mode
                assert f"call __xu_tensor_gemv4_q4_0_p4_q8_0{suf}_f32(" in funcs["kernel_gemv_q4_p4"], mode
                assert f"call __xu_tensor_gemv4_q8_0_p4_q8_0{suf}_f32(" in funcs["kernel_gemv_q8_p4"], mode
                assert f"call __xu_tensor_gemm4x8_q4_0_p4_q8_0{suf}_f32(" in funcs["kernel_gemm_q4_p4"], mode
                assert f"call __xu_tensor_gemv4_q4_0_p4_f16_q8_0{suf}_f32(" in funcs["kernel_gemv_q4_p4_f16"], mode
                assert f"call __xu_tensor_gemv4_q8_0_p4_f16_q8_0{suf}_f32(" in funcs["kernel_gemv_q8_p4_f16"], mode
                assert f"call __xu_tensor_gemm4x8_q4_0_p4_f16_q8_0{suf}_f32(" in funcs["kernel_gemm_q4_p4_f16"], mode
                assert "call __xu_tensor_pack_q4_0_p4k4_signed(" in funcs["kernel_pack_q4_p4k4_signed"], mode
                assert "call __xu_tensor_pack_q8_0_p4k4(" in funcs["kernel_pack_q8_p4k4"], mode
                assert f"call __xu_tensor_gemv4_q4_0_p4k4_signed_f16_q8_0{suf}_f32(" in funcs["kernel_gemv_q4_p4k4_signed"], mode
                assert f"call __xu_tensor_gemv4_q8_0_p4k4_f16_q8_0{suf}_f32(" in funcs["kernel_gemv_q8_p4k4"], mode
                assert f"call __xu_tensor_gemm4x8_q4_0_p4k4_signed_f16_q8_0{suf}_f32(" in funcs["kernel_gemm_q4_p4k4_signed"], mode
                assert f"call __xu_tensor_attn_scores_paged{suf}_f32(" in funcs["kernel_attn_scores_paged"], mode
                assert f"call __xu_tensor_softmax_scaled{suf}_f32(" in funcs["kernel_softmax_scaled"], mode
                assert f"call __xu_tensor_attn_vsum_paged{suf}_f32(" in funcs["kernel_attn_vsum_paged"], mode
                target_arch = (os.environ.get("XU_TARGET") or os.environ.get("XUARCH") or platform.machine()).lower()
                if "arm64" in target_arch or "aarch64" in target_arch:
                    assert f"call __xu_tensor_gemm4x8_q8_0_p4k4_f16_q8_0{suf}_f32(" in funcs["kernel_gemm_q8_p4k4"], mode
                copy_mir = funcs["kernel_copy16_32"]
                assert copy_mir.count("load8 [") >= 6 and copy_mir.count("store8 [") >= 6, copy_mir

                if platform.system() == "Darwin" and platform.machine() == "arm64":
                    asm = run(["otool", "-tV", exe])
                    expected_syms = [
                        f"___xu_tensor_swiglu{suf}_f32",
                        "___xu_tensor_argmax_f32",
                        "___xu_tensor_rope_f32",
                        f"___xu_tensor_dot{dot_suf}_f32",
                        "___xu_tensor_norm_f32",
                        f"___xu_tensor_gemv4_q4_0_p4_q8_0{suf}_f32",
                        f"___xu_tensor_gemv4_q8_0_p4_q8_0{suf}_f32",
                        f"___xu_tensor_gemm4x8_q4_0_p4_q8_0{suf}_f32",
                        f"___xu_tensor_gemv4_q4_0_p4_f16_q8_0{suf}_f32",
                        f"___xu_tensor_gemv4_q8_0_p4_f16_q8_0{suf}_f32",
                        f"___xu_tensor_gemm4x8_q4_0_p4_f16_q8_0{suf}_f32",
                        "___xu_tensor_pack_q4_0_p4k4_signed",
                        "___xu_tensor_pack_q8_0_p4k4",
                        f"___xu_tensor_gemv4_q4_0_p4k4_signed_f16_q8_0{suf}_f32",
                        f"___xu_tensor_gemv4_q8_0_p4k4_f16_q8_0{suf}_f32",
                        f"___xu_tensor_gemm4x8_q4_0_p4k4_signed_f16_q8_0{suf}_f32",
                        f"___xu_tensor_attn_scores_paged{suf}_f32",
                        f"___xu_tensor_softmax_scaled{suf}_f32",
                        f"___xu_tensor_attn_vsum_paged{suf}_f32",
                    ]
                    for sym in expected_syms:
                        assert f"{sym}:" in asm, (mode, sym)
                    m_f16_gv = re.search(rf"^___xu_tensor_gemv4_q4_0_p4_f16_q8_0{suf}_f32:[\s\S]*?(?=^___|\Z)", asm, re.M)[0]
                    assert "fcvtl\t" in m_f16_gv and "stp\t" in m_f16_gv, m_f16_gv
                    m_f16_gm = re.search(rf"^___xu_tensor_gemm4x8_q4_0_p4_f16_q8_0{suf}_f32:[\s\S]*?(?=^___|\Z)", asm, re.M)[0]
                    assert "fcvtl\t" in m_f16_gm and "sub.16b" in m_f16_gm, m_f16_gm

            out = run([exe])
            results[mode] = parse_lines(out)
            print(f"{mode} passed")

        base_sw, base_f32, base_ot = results["baseline"]
        strict_sw, strict_f32, strict_ot = results["strict"]
        fast_sw, fast_f32, fast_ot = results["fast"]

        assert strict_ot == base_ot, (set(strict_ot.items()) ^ set(base_ot.items()))
        assert fast_ot == base_ot or all(
            (k.startswith(("ARGMAX:", "RMSBATCH:")) and fast_ot[k] == base_ot[k]) or not k.startswith(("ARGMAX:", "RMSBATCH:"))
            for k in base_ot
        ), "ARGMAX/RMSBATCH mismatch in fast mode"
        for k, b_bits in base_f32.items():
            s_bits = strict_f32[k]
            assert s_bits == b_bits, f"strict f32 mismatch at {k}: base={b_bits:#x} strict={s_bits:#x}"
            fv = bits_to_f32(fast_f32[k])
            bv = bits_to_f32(b_bits)
            err = abs(fv - bv)
            tol = 1e-5 + 1e-5 * abs(bv)
            assert err <= tol, f"fast f32 mismatch at {k}: {fv} vs {bv} err={err}"
        max_ulp = 0
        for k, b_bits in base_sw.items():
            s_bits = strict_sw[k]
            if s_bits != b_bits:
                ulp = abs(s_bits - b_bits)
                max_ulp = max(max_ulp, ulp)
                assert ulp == 0, f"strict SwiGLU diff at {k}: base={b_bits:#x} strict={s_bits:#x} ulp={ulp}"
            fv = bits_to_f32(fast_sw[k])
            bv = bits_to_f32(b_bits)
            err = abs(fv - bv)
            tol = 1e-5 + 2e-6 * abs(bv)
            assert err <= tol, f"fast SwiGLU diff at {k}: {fv} vs {bv} err={err}"
        print(f"strict bit-exact (0 ULP across {len(base_sw)} SwiGLU + {len(base_f32)} vscale/rope/p4-f16 values) & p4 GEMV/GEMM/argmax/rms_batch verified")

        # Cross-target x64 compilation check for all new stubs
        if platform.system() == "Darwin":
            x64_exe = work / "opt-x64"
            x64_mir = build(compiler, dict(env, XU_TENSOR_FUSION="1", XU_TENSOR_FAST_MATH="0", XU_TASK_POLL="0"),
                            src, x64_exe, flags=("--target", "macos-x64"))
            assert "call __xu_tensor_swiglu_f32(" in x64_mir
            assert "call __xu_tensor_argmax_f32(" in x64_mir
            assert "call __xu_tensor_rope_f32(" in x64_mir
            assert "call __xu_tensor_gemv4_q4_0_p4_q8_0_f32(" in x64_mir
            assert "call __xu_tensor_gemv4_q8_0_p4_q8_0_f32(" in x64_mir
            assert "call __xu_tensor_gemm4x8_q4_0_p4_q8_0_f32(" in x64_mir
            assert "call __xu_tensor_gemv4_q4_0_p4_f16_q8_0_f32(" in x64_mir
            assert "call __xu_tensor_gemv4_q8_0_p4_f16_q8_0_f32(" in x64_mir
            assert "call __xu_tensor_gemm4x8_q4_0_p4_f16_q8_0_f32(" in x64_mir
            assert "call __xu_tensor_pack_q4_0_p4k4_signed(" in x64_mir
            assert "call __xu_tensor_pack_q8_0_p4k4(" in x64_mir
            assert "call __xu_tensor_gemv4_q4_0_p4k4_signed_f16_q8_0_f32(" in x64_mir
            assert "call __xu_tensor_gemv4_q8_0_p4k4_f16_q8_0_f32(" in x64_mir
            assert "call __xu_tensor_gemm4x8_q4_0_p4k4_signed_f16_q8_0_f32(" in x64_mir
            assert "call __xu_tensor_attn_scores_paged_f32(" in x64_mir
            assert "call __xu_tensor_softmax_scaled_f32(" in x64_mir
            assert "call __xu_tensor_attn_vsum_paged_f32(" in x64_mir
            x64_asm = run(["otool", "-tV", x64_exe])
            for sym in ("___xu_tensor_swiglu_f32", "___xu_tensor_argmax_f32", "___xu_tensor_rope_f32",
                        "___xu_tensor_gemv4_q4_0_p4_q8_0_f32",
                        "___xu_tensor_gemv4_q8_0_p4_q8_0_f32",
                        "___xu_tensor_gemm4x8_q4_0_p4_q8_0_f32",
                        "___xu_tensor_gemv4_q4_0_p4_f16_q8_0_f32",
                        "___xu_tensor_gemv4_q8_0_p4_f16_q8_0_f32",
                        "___xu_tensor_gemm4x8_q4_0_p4_f16_q8_0_f32",
                        "___xu_tensor_pack_q4_0_p4k4_signed",
                        "___xu_tensor_pack_q8_0_p4k4",
                        "___xu_tensor_gemv4_q4_0_p4k4_signed_f16_q8_0_f32",
                        "___xu_tensor_gemv4_q8_0_p4k4_f16_q8_0_f32",
                        "___xu_tensor_gemm4x8_q4_0_p4k4_signed_f16_q8_0_f32",
                        "___xu_tensor_attn_scores_paged_f32",
                        "___xu_tensor_softmax_scaled_f32",
                        "___xu_tensor_attn_vsum_paged_f32"):
                assert f"{sym}:" in x64_asm, ("macos-x64", sym)
            print("macos-x64 cross-compile and SSE stub disassembly passed")

        if args.benchmark:
            bench = {}
            for mode in ("baseline", "strict", "fast"):
                out = run([exes[mode], "bench"])
                bench[mode] = {}
                for line in out.splitlines():
                    if line.startswith("BENCH:"):
                        _, k, ns, _cs = line.split(":")
                        bench[mode][k] = int(ns)
            print("\nMicro-benchmark (ns per call):")
            for k in bench["baseline"]:
                b_ns = bench["baseline"][k]
                s_ns = bench["strict"][k]
                f_ns = bench["fast"][k]
                print(f"  {k:34s}: base={b_ns:9d} ns | strict={s_ns:8d} ns ({b_ns/s_ns:5.2f}x) | fast={f_ns:8d} ns ({b_ns/f_ns:5.2f}x)")


if __name__ == "__main__":
    main()
