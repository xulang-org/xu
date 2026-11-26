#!/usr/bin/env python3
"""Verify low-precision tensor types, model loading, and paged KV storage."""

import argparse
import bisect
import json
import math
import os
import re
import struct
import subprocess
import tempfile
from pathlib import Path

from test_llm_engine import (
    CFG, bits_to_f32, generate_weight_dict, parse_bench, parse_verify, write_gguf_q4_0, write_safetensors,
)
from test_tensor_dynamic import mir_functions
from test_tensor_fusion import build, run


FP8_FORMATS = {
    "fp8_e4m3fn": ("F8_E4M3", 3, 7),
    "fp8_e5m2": ("F8_E5M2", 2, 15),
    "fp8_e4m3fnuz": ("F8_E4M3FNUZ", 3, 8),
    "fp8_e5m2fnuz": ("F8_E5M2FNUZ", 2, 16),
}
EXE_SUFFIX = ".exe" if os.name == "nt" else ""


XU_CHECKS = """@main

#errors
#math
#tensor

fn require(ok bool, message string) int {
    if !ok { >>> errors.new(message) }
    << 0
}

fn check_view() int {
    $storage := "prefix"
    for i in 1:7 {
        raw := tensor.f16(f32(i)).bits
        storage.push_str(string_from_byte(int(raw) & 255))
        storage.push_str(string_from_byte(int(raw) >> 8))
    }

    dtype := tensor.dtype_f16()
    shape := [2, 3]
    view := tensor.contiguous_view(dtype, &shape, 6, storage.len) >>>
    require(view.is_contiguous() && view.rank() == 2 && view.element_count() == 6, "shape") >>>
    require(view.storage_start() == 6 && view.storage_end() == 18, "span") >>>
    coord := [1, 2]
    value := view.read_f32(&storage, &coord) >>>
    require(value == f32(6), "indexed value") >>>

    transposed := view.transpose(0, 1) >>>
    first_axis := transposed.stride(0) >>>
    require(!transposed.is_contiguous() && first_axis == 1, "transpose stride") >>>
    $values := []f32{}
    transposed.append_f32(&storage, $&values) >>>
    expected := [f32(1), f32(4), f32(2), f32(5), f32(3), f32(6)]
    for i in 0:expected.len {
        require(values[i] == expected[i], "transpose order") >>>
    }
    stepped := view.slice(1, 0, 3, 2) >>>
    stride := stepped.stride(1) >>>
    require(stride == 2, "slice stride") >>>
    stepped.copy_f32(&storage, 1, 2, $&values, 3) >>>
    require(values[3] == f32(3) && values[4] == f32(4), "sliced range") >>>
    broadcast_strides := [0, 1]
    broadcast := tensor.strided_view(dtype, &shape, &broadcast_strides, 6, storage.len) >>>
    repeated := broadcast.read_f32_linear(&storage, 4) >>>
    require(repeated == f32(2), "stride-zero broadcast") >>>
    scalar_shape := []int{}
    scalar := tensor.contiguous_view(dtype, &scalar_shape, 8, storage.len) >>>
    scalar_value := scalar.read_f32(&storage, &scalar_shape) >>>
    require(scalar_value == f32(2), "rank-zero scalar") >>>
    empty := view.slice(1, 3, 3, 1) >>>
    require(empty.element_count() == 0, "empty slice") >>>

    _ := empty.read_f32_linear(&storage, 0) >>> (err) { << 1 }
    >>> errors.new("empty read succeeded")
}

fn check_rejections() int {
    dtype := tensor.dtype_f16()
    bad_shape := [-1, 3]
    shape := [2, 3]
    strides := [9223372036854775807, 1]
    huge_shape := [9223372036854775807, 2]
    _ := tensor.contiguous_view(dtype, &bad_shape, 0, 12) >>> (err) {
        _ := tensor.contiguous_view(dtype, &huge_shape, 0, 12) >>> (err) {
            _ := tensor.strided_view(dtype, &shape, &strides, 0, 12) >>> (err) {
                _ := tensor.contiguous_view(dtype, &shape, 1, 12) >>> (err) { << 4 }
                >>> errors.new("short backing succeeded")
            }
            >>> errors.new("stride overflow succeeded")
        }
        >>> errors.new("shape overflow succeeded")
    }
    >>> errors.new("negative shape succeeded")
}

fn check_blocks() int {
    half := string_from_byte(0) + string_from_byte(56)
    $q4 := "x" + half
    $q8 := "x" + half
    for i in 0:16 { q4.push_str(string_from_byte(i | ((15 - i) << 4))) }
    for i in 0:32 { q8.push_str(string_from_byte((i - 16) & 255)) }
    a := tensor.read_q4_0(&q4, 1) >>>
    b := tensor.read_q8_0(&q8, 1) >>>
    $values := []f32{}
    a.append_f32($&values)
    b.append_f32($&values)
    for i in 0:32 {
        $quant4 := i - 8
        if i >= 16 { quant4 = 23 - i }
        expected4 := f32(quant4) * f32(0.5)
        expected8 := f32(i - 16) * f32(0.5)
        indexed4 := a.at(i) >>>
        indexed8 := b.at(i) >>>
        require(indexed4 == expected4 && values[i] == expected4, "Q4_0 layout") >>>
        require(indexed8 == expected8 && values[i + 32] == expected8, "Q8_0 signed lanes") >>>
    }

    // Q4_K super-block check (144 bytes -> 256 values, exercising scales[0..11] & high nibbles)
    $q4k := "x" + half + string_from_byte(0) + string_from_byte(52) // d=0.5, dmin=0.25
    // scales[0..3]=sc0..3 (low 6 bits) + high bits of sc4..7; scales[4..7]=m0..3 + high bits of m4..7; scales[8..11]=low 4 bits
    q4k.push_str(string_from_byte(1 | (1 << 6)))  // sc0=1, sc4_hi=1
    q4k.push_str(string_from_byte(2 | (0 << 6)))  // sc1=2, sc5_hi=0
    q4k.push_str(string_from_byte(3 | (2 << 6)))  // sc2=3, sc6_hi=2
    q4k.push_str(string_from_byte(4 | (3 << 6)))  // sc3=4, sc7_hi=3
    q4k.push_str(string_from_byte(0 | (1 << 6)))  // m0=0,  m4_hi=1
    q4k.push_str(string_from_byte(1 | (0 << 6)))  // m1=1,  m5_hi=0
    q4k.push_str(string_from_byte(2 | (1 << 6)))  // m2=2,  m6_hi=1
    q4k.push_str(string_from_byte(3 | (0 << 6)))  // m3=3,  m7_hi=0
    q4k.push_str(string_from_byte(5 | (2 << 4)))  // sc4_lo=5 -> 21, m4_lo=2 -> 18
    q4k.push_str(string_from_byte(6 | (3 << 4)))  // sc5_lo=6 -> 6,  m5_lo=3 -> 3
    q4k.push_str(string_from_byte(7 | (4 << 4)))  // sc6_lo=7 -> 39, m6_lo=4 -> 20
    q4k.push_str(string_from_byte(8 | (5 << 4)))  // sc7_lo=8 -> 56, m7_lo=5 -> 5
    for i in 0:128 { q4k.push_str(string_from_byte(((i * 3) & 15) | (((15 - (i & 15)) & 15) << 4))) }
    blk4k := tensor.read_q4_k(&q4k, 1) >>>
    $vals4k := []f32{}
    blk4k.append_f32($&vals4k)
    require(vals4k.len == tensor.QK_K, "Q4_K len") >>>
    $x4k := []f32{}
    $ref_dot4k := f32(0)
    for i in 0:256 {
        v := blk4k.at(i) >>>
        require(v == vals4k[i], "Q4_K at matches append_f32") >>>
        xv := f32(f64((i % 9) - 4) * 0.125)
        x4k.push(xv)
        ref_dot4k += v * xv
    }
    // Check known spots: i=0 (chunk0 lo: d=0.5,sc=1,m=0,q=0 => 0.0), i=32 (chunk0 hi: sc=2,m=1,q=15 => 14.75), i=160 (chunk2 hi: sc=6,m=3,q=15 => 44.25)
    require(vals4k[0] == f32(0.0) && vals4k[32] == f32(14.75) && vals4k[160] == f32(44.25), "Q4_K decoded values") >>>
    require(math.abs(f64(blk4k.dot_f32(&x4k, 0) - ref_dot4k)) < 1e-4, "Q4_K dot_f32") >>>

    // Q6_K super-block check (210 bytes -> 256 values)
    $q6k := "x"
    for i in 0:128 { q6k.push_str(string_from_byte(((i * 5) & 15) | (((i * 7 + 3) & 15) << 4))) }
    for i in 0:64 { q6k.push_str(string_from_byte((i * 11) & 255)) }
    for i in 0:16 {
        $sc := i - 8
        if sc == 0 { sc = 3 }
        q6k.push_str(string_from_byte(sc & 255))
    }
    q6k.push_str(half) // d = 0.5
    blk6k := tensor.read_q6_k(&q6k, 1) >>>
    $vals6k := []f32{}
    blk6k.append_f32($&vals6k)
    require(vals6k.len == tensor.QK_K, "Q6_K len") >>>
    $ref_dot6k := f32(0)
    for i in 0:256 {
        v := blk6k.at(i) >>>
        require(v == vals6k[i], "Q6_K at matches append_f32") >>>
        ref_dot6k += v * x4k[i]
    }
    require(math.abs(f64(blk6k.dot_f32(&x4k, 0) - ref_dot6k)) < 1e-4, "Q6_K dot_f32") >>>

    _ := tensor.read_q4_k(&q4k, 2) >>> (err) {
        _ := tensor.read_q6_k(&q6k, 2) >>> (err2) {
            _ := tensor.read_q8_0(&q8, 2) >>> (err3) { << 1 }
            >>> errors.new("truncated Q8_0 block succeeded")
        }
        >>> errors.new("truncated Q6_K block succeeded")
    }
    >>> errors.new("truncated Q4_K block succeeded")
}

fn check_narrow() int {
    dtypes := [tensor.dtype_f16(), tensor.dtype_bf16()]
    for variant in 0:dtypes.len {
        dtype := dtypes[variant]
        $nan_threshold := 0x7c00
        if variant == 1 { nan_threshold = 0x7f80 }
        for raw in 0:65536 {
            if (raw & 0x7fff) <= nan_threshold {
                value := dtype.decode_bits(raw)
                require(dtype.encode_bits(value) == raw, "16-bit roundtrip") >>>
            }
        }
    }
    require(tensor.f16(f32(1.00048828125)).bits == 0x3c00, "F16 even tie") >>>
    require(tensor.f16(f32(1.00146484375)).bits == 0x3c02, "F16 odd tie") >>>
    require(tensor.f16(f32(65520)).bits == 0x7c00, "F16 overflow") >>>
    require(tensor.bf16(f32(1.00390625)).bits == 0x3f80, "BF16 even tie") >>>
    require(tensor.bf16(f32(1.01171875)).bits == 0x3f82, "BF16 odd tie") >>>
    require(tensor.fp8_e4m3fn(f32(1.0625)).bits == 0x38, "FP8 even tie") >>>
    require(tensor.fp8_e4m3fn(f32(1.1875)).bits == 0x3a, "FP8 odd tie") >>>
    require(tensor.fp8_e4m3fn(f32(1000)).bits == 0x7e, "E4M3FN saturation") >>>
    require(tensor.fp8_e5m2(f32(100000)).bits == 0x7b, "E5M2 saturation") >>>
    << 0
}

fn main() int {
    check_all() >>> (err) {
        eprintln(err.msg())
        << 1
    }
    << 0
}

fn check_all() int {
    check_view() >>>
    check_rejections() >>>
    check_blocks() >>>
    check_narrow() >>>
    dtypes := [tensor.dtype_fp8_e4m3fn(), tensor.dtype_fp8_e5m2(),
               tensor.dtype_fp8_e4m3fnuz(), tensor.dtype_fp8_e5m2fnuz()]
    for dtype in dtypes {
        for raw in 0:256 {
            value := dtype.decode_bits(raw)
            println(str(math.float32_bits(f64(value))) + " " + str(dtype.encode_bits(value)))
        }
    }
    << 0
}
"""


def decode_fp8(raw, name):
    _, mantissa_bits, bias = FP8_FORMATS[name]
    fraction = raw & ((1 << mantissa_bits) - 1)
    exponent = (raw & 0x7f) >> mantissa_bits
    sign = -1 if raw & 0x80 else 1
    if name.endswith("fnuz") and raw == 0x80:
        return math.nan
    if name == "fp8_e4m3fn" and (raw & 0x7f) == 0x7f:
        return math.nan
    if name == "fp8_e5m2" and exponent == 31:
        return math.nan if fraction else sign * math.inf
    if exponent == 0:
        return sign * math.ldexp(fraction, 1 - bias - mantissa_bits)
    return sign * math.ldexp((1 << mantissa_bits) + fraction, exponent - bias - mantissa_bits)


def check_scalars(compiler, env, work):
    source = work / "tensor-types.xu"
    source.write_text(XU_CHECKS)
    exe = work / ("tensor-types" + EXE_SUFFIX)
    build(compiler, env, source, exe)
    lines = run([exe], env=env).splitlines()
    assert len(lines) == 1024, len(lines)
    for format_index, name in enumerate(FP8_FORMATS):
        for raw in range(256):
            bits, encoded = map(int, lines[format_index * 256 + raw].split())
            expected = decode_fp8(raw, name)
            if math.isnan(expected):
                assert math.isnan(bits_to_f32(bits)), (name, raw, bits)
                assert math.isnan(decode_fp8(encoded, name)), (name, raw, encoded)
            else:
                expected_bits = struct.unpack("<I", struct.pack("<f", expected))[0]
                assert (bits, encoded) == (expected_bits, raw), (name, raw, bits, encoded)
    print("OK: F16/BF16 roundtrips, all FP8 codes, strided views, GGML blocks and bounds")


def encode_values(values, name):
    if name == "f32":
        return struct.pack(f"<{len(values)}f", *values), values
    if name == "f16":
        raw = struct.pack(f"<{len(values)}e", *values)
        return raw, list(struct.unpack(f"<{len(values)}e", raw))
    if name == "bf16":
        raw = bytearray()
        decoded = []
        for value in values:
            bits = struct.unpack("<I", struct.pack("<f", value))[0]
            rounded = (bits + 0x7fff + ((bits >> 16) & 1)) >> 16
            raw.extend(struct.pack("<H", rounded))
            decoded.append(bits_to_f32(rounded << 16))
        return bytes(raw), decoded

    candidates = [(decode_fp8(raw, name), raw) for raw in range(128)]
    candidates = [(value, raw) for value, raw in candidates if math.isfinite(value)]
    magnitude = [value for value, _ in candidates]
    raw = bytearray()
    for value in values:
        size = abs(value)
        index = bisect.bisect_left(magnitude, size)
        adjacent = candidates[max(0, index - 1):index + 1]
        _, code = min(adjacent, key=lambda pair: (abs(pair[0] - size), pair[1] & 1))
        if value < 0 and (code or not name.endswith("fnuz")):
            code |= 0x80
        raw.append(code)
    return bytes(raw), [decode_fp8(code, name) for code in raw]


def write_model(path, cfg, tensors):
    names = ["f16", "bf16", *FP8_FORMATS]
    file_types = {"f16": "F16", "bf16": "BF16", "f32": "F32"}
    file_types.update({name: spec[0] for name, spec in FP8_FORMATS.items()})
    reference = {}
    header = {"__metadata__": {key: str(value) for key, value in cfg.items()}}
    payload = bytearray()
    storage_bytes = 0
    matrix_index = 0
    for key, (shape, values) in tensors.items():
        name = "bf16"
        if len(shape) == 2:
            name = names[matrix_index % len(names)]
            matrix_index += 1
        raw, decoded = encode_values(values, name)
        if len(shape) == 2:
            storage_bytes += len(raw)
        reference[key] = (shape, decoded)
        header[key] = {
            "dtype": file_types[name], "shape": shape,
            "data_offsets": [len(payload), len(payload) + len(raw)],
        }
        payload.extend(raw)
    write_model_bytes(path, header, payload)
    return reference, storage_bytes, header, payload


def write_model_bytes(path, header, payload):
    encoded = json.dumps(header, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 8)
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + payload)


def check_gguf(engine, env, work, cfg, tensors):
    compact_path = work / "mixed.gguf"
    reference_path = work / "canonical.gguf"
    layouts = [(1, "f16"), (30, "bf16"), (43, "fp8_e4m3fn")]
    reference_data = {}
    compact_bytes = 0

    def encode_compact(key, shape, values):
        nonlocal compact_bytes
        index = len(reference_data) % len(layouts)
        type_id, name = layouts[index]
        raw, decoded = encode_values(values, name)
        reference_data[key] = encode_values(decoded, "f32")[0]
        if len(shape) == 2:
            compact_bytes += len(raw)
        return type_id, raw

    write_gguf_q4_0(compact_path, cfg, tensors, tied_output=True, encode_dense=encode_compact)
    write_gguf_q4_0(reference_path, cfg, tensors, tied_output=True,
                    encode_dense=lambda key, shape, values: (0, reference_data[key]))
    ref_seq, ref_cb, _ = parse_verify(run([engine, "verify", reference_path], env=env))
    seq, cb, meta = parse_verify(run([engine, "verify", compact_path], env=env))
    assert seq and seq == cb == ref_seq == ref_cb
    assert int(meta["compact_weight_bytes"]) == compact_bytes
    print("OK: mixed F16/BF16/FP8 GGUF matches F32 with tied output weights")


def check_model(compiler, env, work, source):
    cfg = dict(CFG, dim=64, hidden_dim=96, n_layers=2, n_heads=2, n_kv_heads=1, vocab_size=64)
    tensors = generate_weight_dict(cfg)
    compact_path = work / "mixed.safetensors"
    reference_path = work / "canonical.safetensors"
    reference, compact_bytes, header, payload = write_model(compact_path, cfg, tensors)
    write_safetensors(reference_path, cfg, reference)
    engine = work / ("llm-engine" + EXE_SUFFIX)
    build(compiler, env, source, engine)
    seq, cb, meta = parse_verify(run([engine, "verify", reference_path], env=env))
    compact_seq, compact_cb, compact_meta = parse_verify(run([engine, "verify", compact_path], env=env))
    assert seq and seq == cb == compact_seq == compact_cb
    assert int(meta["compact_weight_bytes"]) == 0
    assert int(compact_meta["compact_weight_bytes"]) == compact_bytes
    full_bytes = int(meta["kv_storage_bytes"])
    for dtype in ["f16", "bf16", *FP8_FORMATS]:
        seq, cb, meta = parse_verify(run([engine, "verify", compact_path, "--kv-dtype", dtype], env=env))
        assert seq and seq == cb, dtype
        assert all(math.isfinite(bits_to_f32(bits)) for req in seq.values() for _, bits in req), dtype
        assert int(meta["kv_storage_bytes"]) * (2 if dtype in ("f16", "bf16") else 4) == full_bytes, dtype
        spans_pages = run([engine, "bench", compact_path, "4", "single", "31", "--kv-dtype", dtype], env=env)
        bench = parse_bench(spans_pages)
        assert bench["prefill_tokens"] == 31 and len(bench["tokens"].split(",")) == 5, dtype
    malformed = work / "bad.safetensors"
    header["embed_tokens.weight"]["data_offsets"][1] -= 1
    write_model_bytes(malformed, header, payload)
    bad = subprocess.run([engine, "verify", malformed], capture_output=True, text=True, env=env, timeout=30)
    assert bad.returncode != 0 and "embed_tokens.weight" in bad.stderr, bad
    print("OK: mixed-precision Safetensors matches F32 and all paged KV modes use the expected storage")
    check_gguf(engine, env, work, cfg, tensors)


XU_OPS_CHECKS = """@main

#math
#tensor

fn bits(v f32) int { << math.float32_bits(f64(v)) }

fn main() int {
    n := 13
    $a := []f32{}
    $b := []f32{}
    $w := []f32{}
    for i in 0:n {
        a.push(f32(f64((i * 5 + 1) % 11 - 5) * 0.25))
        b.push(f32(f64((i * 7 + 2) % 9 - 4) * 0.5))
        w.push(f32(f64((i * 3 + 1) % 7 + 1) * 0.25))
    }
    println("DOT:" + str(bits(tensor.dot_f32(&a, &b, n))))

    $ax := []f32{}
    for i in 0:n { ax.push(a[i]) }
    tensor.axpy_f32($&ax, &b, f32(0.75), n)
    for i in 0:n { println("AXPY:" + str(i) + ":" + str(bits(ax[i]))) }

    $va := []f32{}
    for i in 0:n { va.push(a[i]) }
    tensor.vadd_f32($&va, &b, n)
    for i in 0:n { println("VADD:" + str(i) + ":" + str(bits(va[i]))) }

    $vm := []f32{}
    for _ in 0:n { vm.push(f32(0)) }
    tensor.vmul_f32($&vm, &a, &b, n)
    for i in 0:n { println("VMUL:" + str(i) + ":" + str(bits(vm[i]))) }

    $vs := []f32{}
    for i in 0:n { vs.push(a[i]) }
    tensor.vscale_f32($&vs, f32(1.5), n)
    for i in 0:n { println("VSCALE:" + str(i) + ":" + str(bits(vs[i]))) }

    $rn := []f32{}
    for _ in 0:n { rn.push(f32(0)) }
    tensor.rmsnorm_f32($&rn, &a, &w, n, 1e-5)
    for i in 0:n { println("RMS:" + str(i) + ":" + str(bits(rn[i]))) }

    $sm := []f32{}
    for i in 0:n { sm.push(a[i]) }
    tensor.softmax_f32($&sm, n, f32(0.5))
    for i in 0:n { println("SOFTMAX:" + str(i) + ":" + str(bits(sm[i]))) }

    $sg := []f32{}
    for _ in 0:n { sg.push(f32(0)) }
    tensor.swiglu_f32($&sg, &a, &b, n)
    for i in 0:n { println("SWIGLU:" + str(i) + ":" + str(bits(sg[i]))) }

    rows := 5
    cols := 7
    m_cnt := 3
    $mw := []f32{}
    for r in 0:rows {
        for c in 0:cols {
            mw.push(f32(f64((r * 7 + c * 3) % 13 - 6) * 0.125))
        }
    }
    $mx := []f32{}
    for m in 0:m_cnt {
        for c in 0:cols {
            mx.push(f32(f64((m * 5 + c * 2) % 11 - 5) * 0.25))
        }
    }
    $mv_out := []f32{}
    for _ in 0:rows { mv_out.push(f32(0)) }
    tensor.matvec_f32($&mv_out, &mx, &mw, rows, cols)
    for r in 0:rows { println("MATVEC:" + str(r) + ":" + str(bits(mv_out[r]))) }

    $mm_out := []f32{}
    for _ in 0:m_cnt * rows { mm_out.push(f32(0)) }
    tensor.matmul_f32($&mm_out, &mx, &mw, m_cnt, rows, cols)
    for i in 0:m_cnt * rows { println("MATMUL:" + str(i) + ":" + str(bits(mm_out[i]))) }

    println("ARGMAX:" + str(tensor.argmax_f32(&a, n)))

    qn := 64
    $qx := []f32{}
    for i in 0:qn { qx.push(f32(f64((i * 11 + 3) % 23 - 11) * 0.25)) }
    $xq := []i8{}
    for _ in 0:qn { xq.push(i8(0)) }
    $qsc := []f32{}
    for _ in 0:qn / 32 { qsc.push(f32(0)) }
    tensor.quantize_q8_0(&qx, $&xq, $&qsc, qn)
    for i in 0:qn { println("Q8Q:" + str(i) + ":" + str(int(xq[i]))) }
    for b_i in 0:qn / 32 { println("Q8S:" + str(b_i) + ":" + str(bits(qsc[b_i]))) }

    $vsub := []f32{}
    for _ in 0:n { vsub.push(f32(0)) }
    tensor.vsub_f32($&vsub, &a, &b, n)
    for i in 0:n { println("VSUB:" + str(i) + ":" + str(bits(vsub[i]))) }

    $silu_out := []f32{}
    $gelu_out := []f32{}
    $ln_out := []f32{}
    $l2_out := []f32{}
    $bias := []f32{}
    for i in 0:n {
        silu_out.push(f32(0))
        gelu_out.push(f32(0))
        ln_out.push(f32(0))
        l2_out.push(f32(0))
        bias.push(f32(f64(i % 5) * 0.125))
    }
    tensor.silu_f32($&silu_out, &a, n)
    tensor.gelu_f32($&gelu_out, &a, n)
    tensor.layernorm_f32($&ln_out, &a, &w, &bias, n, 1e-5)
    tensor.l2_normalize_f32($&l2_out, &a, n, 1e-12)
    for i in 0:n {
        println("SILU:" + str(i) + ":" + str(bits(silu_out[i])))
        println("GELU:" + str(i) + ":" + str(bits(gelu_out[i])))
        println("LN:" + str(i) + ":" + str(bits(ln_out[i])))
        println("L2:" + str(i) + ":" + str(bits(l2_out[i])))
    }
    println("L2NORM:" + str(bits(tensor.dot_f32(&l2_out, &l2_out, n))))
    println("COS:" + str(bits(tensor.cosine_similarity_f32(&a, &b, n))))
    println("COSSELF:" + str(bits(tensor.cosine_similarity_f32(&a, &a, n))))

    $rope_vec := []f32{}
    for i in 0:16 { rope_vec.push(f32(f64((i * 5 + 3) % 13 - 6) * 0.25)) }
    tensor.rope_f32($&rope_vec, 2, 8, 5, 10000.0)
    for i in 0:16 { println("ROPE:" + str(i) + ":" + str(bits(rope_vec[i]))) }

    $q4p := []u8{}
    for _ in 0:(qn / 32) * 16 { q4p.push(u8(0)) }
    $q4sc := []f32{}
    for _ in 0:qn / 32 { q4sc.push(f32(0)) }
    tensor.quantize_q4_0_row(&qx, $&q4p, $&q4sc, qn)
    for i in 0:q4p.len { println("Q4P:" + str(i) + ":" + str(int(q4p[i]))) }
    for b_i in 0:q4sc.len { println("Q4S:" + str(b_i) + ":" + str(bits(q4sc[b_i]))) }
    << 0
}
"""


def check_ops(compiler, env, work):
    source = work / "tensor-ops.xu"
    source.write_text(XU_OPS_CHECKS)
    base_exe = work / ("tensor-ops-base" + EXE_SUFFIX)
    fused_exe = work / ("tensor-ops-fused" + EXE_SUFFIX)
    base_env = dict(env, XU_TENSOR_FUSION="0", XU_TENSOR_FAST_MATH="0")
    fused_env = dict(env, XU_TENSOR_FUSION="1", XU_TENSOR_FAST_MATH="0", XU_DUMP_MIR="_xu_tensor_")
    build(compiler, base_env, source, base_exe)
    mir = build(compiler, fused_env, source, fused_exe)
    base_out = run([base_exe], env=base_env).splitlines()
    fused_out = run([fused_exe], env=fused_env).splitlines()
    assert base_out == fused_out, (base_out[:10], fused_out[:10])
    kv = {line.split(":", 1)[0]: line.split(":", 1)[1] for line in base_out}
    l2_norm_sq = bits_to_f32(int(kv["L2NORM"]))
    assert abs(l2_norm_sq - 1.0) < 1e-5, l2_norm_sq
    cos_self = bits_to_f32(int(kv["COSSELF"]))
    assert abs(cos_self - 1.0) < 1e-5, cos_self
    parts = re.split(r"(?m)^fn _xu_tensor_(\w+) ", mir)
    funcs = {name: body.split("\nBuild complete:", 1)[0] for name, body in zip(parts[1::2], parts[2::2])}
    expected_calls = {
        "dot_f32": "__xu_tensor_dot_f32",
        "axpy_f32": "__xu_tensor_axpy_f32",
        "vadd_f32": "__xu_tensor_vadd_inplace_f32",
        "vmul_f32": "__xu_tensor_vmul_f32",
        "vscale_f32": "__xu_tensor_norm_f32",
        "rmsnorm_f32": "__xu_tensor_norm_f32",
        "softmax_f32": "__xu_tensor_softmax_scaled_f32",
        "swiglu_f32": "__xu_tensor_swiglu_f32",
        "matvec_f32": "__xu_tensor_gemv4_f32",
        "matmul_f32": "__xu_tensor_gemm4x4_f32",
        "argmax_f32": "__xu_tensor_argmax_f32",
        "quantize_q8_0": "__xu_tensor_quantize_q8_0",
    }
    for fn_name, stub in expected_calls.items():
        assert f"call {stub}(" in funcs[fn_name], (fn_name, stub, funcs.get(fn_name, ""))
    print("OK: tensor.ops numerical primitives match baseline bit-for-bit and trigger MIR SIMD kernels")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_MIR_BORROW_GATE="1", XU_TENSOR_FUSION="0", XU_TENSOR_FAST_MATH="0", XU_TASK_POLL="0")
        check_scalars(args.compiler.resolve(), env, work)
        check_ops(args.compiler.resolve(), env, work)
        check_model(args.compiler.resolve(), env, work, root / "examples/llm_engine/main.xu")


if __name__ == "__main__":
    main()
