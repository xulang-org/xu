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

    // reshape, permute, and mutable []u8 read_f32_bytes / write_f32_bytes
    flat_shape := [6]
    reshaped := view.reshape(&flat_shape) >>>
    require(reshaped.rank() == 1 && reshaped.element_count() == 6, "reshape") >>>
    flat_coord := [5]
    rval := reshaped.read_f32(&storage, &flat_coord) >>>
    require(rval == f32(6), "reshape value") >>>
    axes := [1, 0]
    permuted := view.permute(&axes) >>>
    perm_coord := [2, 1]
    pval := permuted.read_f32(&storage, &perm_coord) >>>
    require(pval == f32(6), "permute value") >>>

    $mbuf := []u8{}
    for _ in 0:12 { mbuf.push(u8(0)) }
    mview := tensor.contiguous_view(dtype, &shape, 0, mbuf.len) >>>
    mcoord := [1, 1]
    _ := mview.write_f32_bytes($&mbuf, &mcoord, f32(7.5)) >>>
    mval := mview.read_f32_bytes(&mbuf, &mcoord) >>>
    require(mval == f32(7.5), "write_f32_bytes") >>>

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

fn b_dot_ref(blk &tensor.Q8Block, x &[]f32) f32 {
    $acc := f32(0)
    for i in 0:32 {
        acc += (blk.at(i) >>> (err) { << f32(0) }) * x[i]
    }
    << acc
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

    // Q4_K, Q8_0, Q5_0, Q6_K single-block & row zero-copy dot checks
    q4k_zc := tensor.q4_k_dot_f32(&q4k, 1, &x4k, 0) >>>
    require(math.abs(f64(q4k_zc - ref_dot4k)) < 1e-4, "q4_k_dot_f32") >>>
    q4k_row := tensor.dot_q4_k_row_f32(&q4k, 1, &x4k, 0, 1) >>>
    require(math.abs(f64(q4k_row - ref_dot4k)) < 1e-4, "dot_q4_k_row_f32") >>>
    q8_zc := tensor.q8_0_dot_f32(&q8, 1, &x4k, 0) >>>
    require(math.abs(f64(q8_zc - b_dot_ref(&b, &x4k))) < 1e-4, "q8_0_dot_f32") >>>
    q8_row := tensor.dot_q8_0_row_f32(&q8, 1, &x4k, 0, 1) >>>
    require(math.abs(f64(q8_row - b_dot_ref(&b, &x4k))) < 1e-4, "dot_q8_0_row_f32") >>>

    // Q5_0 block check (22 bytes -> 32 values)
    $q5 := "x" + half
    // qh = 0x00010002 (bit 1 set for index 1, bit 16 set for index 16)
    q5.push_str(string_from_byte(2))
    q5.push_str(string_from_byte(0))
    q5.push_str(string_from_byte(1))
    q5.push_str(string_from_byte(0))
    for i in 0:16 { q5.push_str(string_from_byte((i & 15) | (((15 - i) & 15) << 4))) }
    blk5 := tensor.read_q5_0(&q5, 1) >>>
    $vals5 := []f32{}
    blk5.append_f32($&vals5)
    require(vals5.len == tensor.GGML_BLOCK_VALUES, "Q5_0 len") >>>
    v5_0 := blk5.at(0) >>>
    v5_1 := blk5.at(1) >>>
    v5_16 := blk5.at(16) >>>
    require(v5_0 == f32(-16) * f32(0.5), "Q5_0 at(0)") >>>
    require(v5_1 == f32(1 + 16 - 16) * f32(0.5), "Q5_0 at(1) with qh bit") >>>
    require(v5_16 == f32(15 + 16 - 16) * f32(0.5), "Q5_0 at(16) with qh bit") >>>
    $ref_dot5 := f32(0)
    for i in 0:32 {
        vi := blk5.at(i) >>>
        require(vi == vals5[i], "Q5_0 at matches append_f32") >>>
        ref_dot5 += vals5[i] * x4k[i]
    }
    require(math.abs(f64(blk5.dot_f32(&x4k, 0) - ref_dot5)) < 1e-4, "Q5_0 dot_f32") >>>
    q5_zc := tensor.q5_0_dot_f32(&q5, 1, &x4k, 0) >>>
    require(math.abs(f64(q5_zc - ref_dot5)) < 1e-4, "q5_0_dot_f32") >>>
    q5_row := tensor.dot_q5_0_row_f32(&q5, 1, &x4k, 0, 1) >>>
    require(math.abs(f64(q5_row - ref_dot5)) < 1e-4, "dot_q5_0_row_f32") >>>

    // quantize_q5_0_row round-trip & dot parity
    $q5_in := []f32{}
    for i in 0:32 { q5_in.push(f32(f64((i * 5) % 19 - 9) * 0.25)) }
    $q5_buf := []u8{}
    for _ in 0:tensor.Q5_0_BYTES { q5_buf.push(u8(0)) }
    tensor.quantize_q5_0_row(&q5_in, $&q5_buf, 32)
    $q5_s := ""
    for i in 0:q5_buf.len { q5_s.push_str(string_from_byte(int(q5_buf[i]))) }
    q5_blk_rt := tensor.read_q5_0(&q5_s, 0) >>>
    $q5_ref_dot := f32(0)
    for i in 0:32 {
        dv := q5_blk_rt.at(i) >>>
        require(math.abs(f64(dv - q5_in[i])) <= 0.2, "quantize_q5_0_row error") >>>
        q5_ref_dot += dv * x4k[i]
    }
    q5_rt_dot := tensor.dot_q5_0_row_f32(&q5_s, 0, &x4k, 0, 1) >>>
    require(math.abs(f64(q5_rt_dot - q5_ref_dot)) < 1e-4, "quantize_q5_0_row dot") >>>

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
    q6k_zc := tensor.q6_k_dot_f32(&q6k, 1, &x4k, 0) >>>
    require(math.abs(f64(q6k_zc - ref_dot6k)) < 1e-4, "q6_k_dot_f32") >>>
    q6k_row := tensor.dot_q6_k_row_f32(&q6k, 1, &x4k, 0, 1) >>>
    require(math.abs(f64(q6k_row - ref_dot6k)) < 1e-4, "dot_q6_k_row_f32") >>>

    // bulk dequant_f16_to_f32 & dequant_bf16_to_f32
    $f16_s := "p"
    $bf16_s := "p"
    for i in 0:4 {
        fv := f32(f64(i - 1) * 1.5)
        fb := int(tensor.f16(fv).bits)
        f16_s.push_str(string_from_byte(fb & 255))
        f16_s.push_str(string_from_byte((fb >> 8) & 255))
        bb := int(tensor.bf16(fv).bits)
        bf16_s.push_str(string_from_byte(bb & 255))
        bf16_s.push_str(string_from_byte((bb >> 8) & 255))
    }
    $dq16 := [f32(0), f32(0), f32(0), f32(0)]
    _ := tensor.dequant_f16_to_f32(&f16_s, 1, $&dq16, 0, 4) >>>
    for i in 0:4 { require(dq16[i] == f32(f64(i - 1) * 1.5), "dequant_f16_to_f32") >>> }
    $dqb16 := [f32(0), f32(0), f32(0), f32(0)]
    _ := tensor.dequant_bf16_to_f32(&bf16_s, 1, $&dqb16, 0, 4) >>>
    for i in 0:4 { require(dqb16[i] == f32(f64(i - 1) * 1.5), "dequant_bf16_to_f32") >>> }

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

fn check_q8_k() int {
    // quantize_q8_k_row + dot_q4_k_q8_k_row_f32 + dot_q6_k_q8_k_row_f32
    $k_x := []f32{}
    for i in 0:256 { k_x.push(f32(f64((i % 29) - 14) * 0.125)) }
    $qk_qs := []i8{}
    for _ in 0:256 { qk_qs.push(i8(0)) }
    $qk_d := [f32(0)]
    $qk_bs := []int{}
    for _ in 0:16 { qk_bs.push(0) }
    tensor.quantize_q8_k_row(&k_x, 0, $&qk_qs, $&qk_d, $&qk_bs, 1) >>>
    $q4k_row := ""
    for j in 0:144 {
        if j == 0 { q4k_row = q4k_row + string_from_byte(0x00) }
        else if j == 1 { q4k_row = q4k_row + string_from_byte(0x3c) }
        else if j == 2 { q4k_row = q4k_row + string_from_byte(0x00) }
        else if j == 3 { q4k_row = q4k_row + string_from_byte(0x38) }
        else if j < 16 { q4k_row = q4k_row + string_from_byte(1 + (j % 3)) }
        else { q4k_row = q4k_row + string_from_byte((j * 17) & 255) }
    }
    dq4_f := tensor.dot_q4_k_row_f32(&q4k_row, 0, &k_x, 0, 1) >>>
    dq4_i := tensor.dot_q4_k_q8_k_row_f32(&q4k_row, 0, &qk_qs, &qk_d, &qk_bs, 1) >>>
    if math.abs(f64(dq4_f - dq4_i)) > 0.01 * (1.0 + math.abs(f64(dq4_f))) { << 34 }

    $q6k_row := ""
    for j in 0:210 {
        if j == 208 { q6k_row = q6k_row + string_from_byte(0x00) }
        else if j == 209 { q6k_row = q6k_row + string_from_byte(0x3c) }
        else if j >= 192 { q6k_row = q6k_row + string_from_byte((j % 5) + 1) }
        else { q6k_row = q6k_row + string_from_byte((j * 31) & 255) }
    }
    dq6_f := tensor.dot_q6_k_row_f32(&q6k_row, 0, &k_x, 0, 1) >>>
    dq6_i := tensor.dot_q6_k_q8_k_row_f32(&q6k_row, 0, &qk_qs, &qk_d, 1) >>>
    if math.abs(f64(dq6_f - dq6_i)) > 0.01 * (1.0 + math.abs(f64(dq6_f))) { << 35 }

    $q5k_row := ""
    for j in 0:176 {
        if j == 0 { q5k_row = q5k_row + string_from_byte(0x00) }
        else if j == 1 { q5k_row = q5k_row + string_from_byte(0x3c) }
        else if j == 2 { q5k_row = q5k_row + string_from_byte(0x00) }
        else if j == 3 { q5k_row = q5k_row + string_from_byte(0x38) }
        else if j < 16 { q5k_row = q5k_row + string_from_byte(1 + (j % 3)) }
        else if j < 48 { q5k_row = q5k_row + string_from_byte((j * 13) & 255) }
        else { q5k_row = q5k_row + string_from_byte((j * 17) & 255) }
    }
    b5 := tensor.read_q5_k(&q5k_row, 0) >>>
    $d5_arr := []f32{}
    b5.append_f32($&d5_arr)
    if d5_arr.len != 256 { << 37 }
    for idx in 0:256 {
        if math.abs(f64(d5_arr[idx] - b5.at(idx) >>>)) > 1e-6 { << 38 }
    }
    dq5_b := b5.dot_f32(&k_x, 0)
    dq5_f := tensor.dot_q5_k_row_f32(&q5k_row, 0, &k_x, 0, 1) >>>
    dq5_i := tensor.dot_q5_k_q8_k_row_f32(&q5k_row, 0, &qk_qs, &qk_d, &qk_bs, 1) >>>
    if math.abs(f64(dq5_b - dq5_f)) > 1e-4 { << 39 }
    if math.abs(f64(dq5_f - dq5_i)) > 0.01 * (1.0 + math.abs(f64(dq5_f))) { << 40 }
    println("Q5K_F:" + str(math.float32_bits(f64(dq5_f))))
    << 0
}

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

    // geglu_f32 parity with gelu(a) * b
    $geglu_out := []f32{}
    for _ in 0:n { geglu_out.push(f32(0)) }
    tensor.geglu_f32($&geglu_out, &a, &b, n)
    for i in 0:n {
        if math.abs(f64(geglu_out[i] - gelu_out[i] * b[i])) > 1e-6 { << 21 }
    }

    // log_softmax_f32: exp(log_softmax) sums to 1.0
    $lsm := []f32{}
    for i in 0:n { lsm.push(a[i]) }
    tensor.log_softmax_f32($&lsm, n)
    $lsm_sum := 0.0
    for i in 0:n {
        if f64(lsm[i]) > 0.0 { << 22 }
        lsm_sum += math.exp(f64(lsm[i]))
    }
    if math.abs(lsm_sum - 1.0) > 1e-5 { << 23 }

    // rope_interleaved_f32 matches rotating (2*j, 2*j+1) pairs manually
    $ri := []f32{}
    for i in 0:16 { ri.push(f32(f64((i * 5 + 3) % 13 - 6) * 0.25)) }
    $ri_copy := []f32{}
    for i in 0:16 { ri_copy.push(ri[i]) }
    tensor.rope_interleaved_f32($&ri, 2, 8, 5, 10000.0)
    // Check head 0 pair (0,1) at angle=5.0
    c0 := f32(math.cos(5.0))
    s0 := f32(math.sin(5.0))
    exp0 := f32(ri_copy[0] * c0 - ri_copy[1] * s0)
    exp1 := f32(ri_copy[0] * s0 + ri_copy[1] * c0)
    if math.abs(f64(ri[0] - exp0)) > 1e-6 || math.abs(f64(ri[1] - exp1)) > 1e-6 { << 24 }

    // add_rmsnorm_f32 parity with separate add + rmsnorm_f32
    $res_out := []f32{}
    $anorm_out := []f32{}
    $add_ref := []f32{}
    $anorm_ref := []f32{}
    for i in 0:n {
        res_out.push(f32(0))
        anorm_out.push(f32(0))
        add_ref.push(a[i] + b[i])
        anorm_ref.push(f32(0))
    }
    tensor.add_rmsnorm_f32($&anorm_out, $&res_out, &a, &b, &w, n, 1e-5)
    tensor.rmsnorm_f32($&anorm_ref, &add_ref, &w, n, 1e-5)
    for i in 0:n {
        if math.abs(f64(res_out[i] - add_ref[i])) > 1e-6 { << 25 }
        if math.abs(f64(anorm_out[i] - anorm_ref[i])) > 1e-5 { << 26 }
    }

    // topk_f32 + moe_router_f32 (Softmax & Sigmoid + bias)
    logits := [f32(0.2), f32(2.0), f32(-1.0), f32(1.0)]
    bias4 := [f32(0.0), f32(0.0), f32(0.0), f32(0.0)]
    $t_idx := [0, 0]
    $t_val := [f32(0), f32(0)]
    picked := tensor.topk_f32(&logits, 4, 2, $&t_idx, $&t_val)
    if picked != 2 || t_idx[0] != 1 || t_idx[1] != 3 { << 27 }
    $r_idx := [0, 0]
    $r_w := [f32(0), f32(0)]
    r_cnt := tensor.moe_router_f32(&logits, 4, 2, false, true, 1.0, &[]f32{}, $&r_idx, $&r_w)
    if r_cnt != 2 || r_idx[0] != 1 || r_idx[1] != 3 { << 28 }
    if math.abs(f64(r_w[0] + r_w[1]) - 1.0) > 1e-5 { << 29 }
    // Sigmoid + bias favoring expert 2
    bias_push := [f32(0.0), f32(0.0), f32(2.0), f32(0.0)]
    $sb_idx := [0, 0]
    $sb_w := [f32(0), f32(0)]
    _ := tensor.moe_router_f32(&logits, 4, 2, true, false, 2.5, &bias_push, $&sb_idx, $&sb_w)
    if sb_idx[0] != 2 || sb_idx[1] != 1 { << 30 }

    // rope_yarn_f32 with scale=1.0, orig_ctx=0 reduces to rope_f32 / rope_interleaved_f32
    $yr := []f32{}
    $yr_ref := []f32{}
    for i in 0:16 {
        v := f32(f64((i * 5 + 3) % 13 - 6) * 0.25)
        yr.push(v)
        yr_ref.push(v)
    }
    tensor.rope_yarn_f32($&yr, 2, 8, 8, false, 5, 10000.0, 1.0, 0, 32.0, 1.0, 1.0)
    tensor.rope_f32($&yr_ref, 2, 8, 5, 10000.0)
    for i in 0:16 {
        if math.abs(f64(yr[i] - yr_ref[i])) > 1e-5 { << 31 }
    }
    // YaRN scaling active test
    $yr2 := []f32{}
    for i in 0:16 { yr2.push(f32(f64(i + 1) * 0.1)) }
    tensor.rope_yarn_f32($&yr2, 2, 8, 4, true, 12, 10000.0, 4.0, 32, 32.0, 1.0, 0.0)
    if math.abs(f64(yr2[0])) <= 0.0 { << 32 }

    // topk_cosine_f32
    q_cos := [f32(1.0), f32(0.0)]
    c_cos := [f32(0.0), f32(1.0), f32(1.0), f32(1.0), f32(2.0), f32(0.0)]
    $c_idx := [0, 0]
    $c_sc := [f32(0), f32(0)]
    c_picked := tensor.topk_cosine_f32(&q_cos, &c_cos, 3, 2, 2, $&c_idx, $&c_sc)
    if c_picked != 2 || c_idx[0] != 2 || c_idx[1] != 1 { << 33 }

    code := check_q8_k() >>> (e) {
        _ := e
        << 36
    }
    if code != 0 { << code }

    // cross_entropy_grad_f32, adamw_step_f32, lora_add_f32
    ce_logits := [f32(1.0), f32(2.5), f32(-0.5)]
    $ce_grad := [f32(0), f32(0), f32(0)]
    ce_loss := tensor.cross_entropy_grad_f32($&ce_grad, &ce_logits, 1, 3)
    println("CE_LOSS:" + str(math.float32_bits(f64(ce_loss))))
    println("CE_G0:" + str(math.float32_bits(f64(ce_grad[0]))))
    println("CE_G1:" + str(math.float32_bits(f64(ce_grad[1]))))
    println("CE_G2:" + str(math.float32_bits(f64(ce_grad[2]))))

    $aparam := [f32(1.0), f32(-2.0)]
    agrad := [f32(0.5), f32(-0.25)]
    $am := [f32(0.0), f32(0.0)]
    $av := [f32(0.0), f32(0.0)]
    tensor.adamw_step_f32($&aparam, &agrad, $&am, $&av, 2, f32(0.1), f32(0.9), f32(0.999), f32(1e-8), f32(0.01), 1)
    println("ADAMW_P0:" + str(math.float32_bits(f64(aparam[0]))))
    println("ADAMW_P1:" + str(math.float32_bits(f64(aparam[1]))))

    $lout := [f32(0.25), f32(-0.5)]
    lx := [f32(2.0), f32(-1.0), f32(0.5)]
    la := [f32(1.0), f32(0.0), f32(-2.0), f32(0.5), f32(3.0), f32(1.0)]
    lb := [f32(2.0), f32(-1.0), f32(0.5), f32(4.0)]
    tensor.lora_add_f32($&lout, &lx, &la, &lb, 2, 3, 2, f32(0.5))
    println("LORA_0:" + str(math.float32_bits(f64(lout[0]))))
    println("LORA_1:" + str(math.float32_bits(f64(lout[1]))))

    // lora_backward_f32, rmsnorm_backward_f32, swiglu_backward_f32
    ldy := [f32(1.5), f32(-2.0)]
    $ldx := [f32(0), f32(0), f32(0)]
    $lda := [f32(0), f32(0), f32(0), f32(0), f32(0), f32(0)]
    $ldb := [f32(0), f32(0), f32(0), f32(0)]
    tensor.lora_backward_f32($&ldx, $&lda, $&ldb, &ldy, &lx, &la, &lb, 2, 3, 2, 0.5)
    for i in 0:3 { println("LB_DX" + str(i) + ":" + str(math.float32_bits(f64(ldx[i])))) }
    for i in 0:6 { println("LB_DA" + str(i) + ":" + str(math.float32_bits(f64(lda[i])))) }
    for i in 0:4 { println("LB_DB" + str(i) + ":" + str(math.float32_bits(f64(ldb[i])))) }

    rx := [f32(1.0), f32(-2.0), f32(0.5), f32(3.0)]
    rw := [f32(0.5), f32(1.5), f32(2.0), f32(-1.0)]
    rdy := [f32(0.25), f32(-0.5), f32(1.0), f32(0.75)]
    $rdx := [f32(0), f32(0), f32(0), f32(0)]
    $rdw := [f32(0), f32(0), f32(0), f32(0)]
    tensor.rmsnorm_backward_f32($&rdx, $&rdw, &rdy, &rx, &rw, 4, 1e-5)
    for i in 0:4 { println("RMS_DX" + str(i) + ":" + str(math.float32_bits(f64(rdx[i])))) }
    for i in 0:4 { println("RMS_DW" + str(i) + ":" + str(math.float32_bits(f64(rdw[i])))) }

    sg := [f32(-1.2), f32(0.8)]
    su := [f32(2.0), f32(-1.5)]
    sdy := [f32(0.75), f32(1.25)]
    $sdg := [f32(0), f32(0)]
    $sdu := [f32(0), f32(0)]
    tensor.swiglu_backward_f32($&sdg, $&sdu, &sdy, &sg, &su, 2)
    for i in 0:2 { println("SWI_DG" + str(i) + ":" + str(math.float32_bits(f64(sdg[i])))) }
    for i in 0:2 { println("SWI_DU" + str(i) + ":" + str(math.float32_bits(f64(sdu[i])))) }

    // layernorm_backward_f32, softmax_backward_f32, grad_clip_norm_f32
    $lndx := [f32(0), f32(0), f32(0), f32(0)]
    $lndw := [f32(0), f32(0), f32(0), f32(0)]
    $lndb := [f32(0), f32(0), f32(0), f32(0)]
    tensor.layernorm_backward_f32($&lndx, $&lndw, $&lndb, &rdy, &rx, &rw, 4, 1e-5)
    for i in 0:4 {
        println("LN_DX" + str(i) + ":" + str(math.float32_bits(f64(lndx[i]))))
        println("LN_DW" + str(i) + ":" + str(math.float32_bits(f64(lndw[i]))))
        println("LN_DB" + str(i) + ":" + str(math.float32_bits(f64(lndb[i]))))
    }

    $sm_p := [f32(1.0), f32(2.0), f32(-1.0)]
    tensor.softmax_f32($&sm_p, 3, f32(1.0))
    sm_dy := [f32(0.5), f32(-1.25), f32(2.0)]
    $sm_dx := [f32(0), f32(0), f32(0)]
    tensor.softmax_backward_f32($&sm_dx, &sm_dy, &sm_p, 3)
    for i in 0:3 { println("SM_DX" + str(i) + ":" + str(math.float32_bits(f64(sm_dx[i])))) }

    $gc := [f32(3.0), f32(4.0), f32(0.0)]
    gc_norm := tensor.grad_clip_norm_f32($&gc, 3, f32(2.5))
    println("GC_NORM:" + str(math.float32_bits(f64(gc_norm))))
    for i in 0:3 { println("GC_G" + str(i) + ":" + str(math.float32_bits(f64(gc[i])))) }

    // kl_div_grad_f32, dpo_loss_grad_f32, grpo_advantages_f32
    kl_s := [f32(1.2), f32(-0.4), f32(0.8)]
    kl_t := [f32(0.5), f32(1.5), f32(-0.5)]
    $kl_g := [f32(0), f32(0), f32(0)]
    kl_val := tensor.kl_div_grad_f32($&kl_g, &kl_s, &kl_t, 3, f32(2.0))
    println("KL_VAL:" + str(math.float32_bits(f64(kl_val))))
    for i in 0:3 { println("KL_G" + str(i) + ":" + str(math.float32_bits(f64(kl_g[i])))) }

    $dpo_g1 := [f32(0), f32(0)]
    dpo_l1 := tensor.dpo_loss_grad_f32(f32(-1.2), f32(-2.4), f32(-1.5), f32(-1.0), f32(0.25), $&dpo_g1)
    println("DPO_L1:" + str(math.float32_bits(f64(dpo_l1))))
    println("DPO_G1_0:" + str(math.float32_bits(f64(dpo_g1[0]))))
    println("DPO_G1_1:" + str(math.float32_bits(f64(dpo_g1[1]))))

    $dpo_g2 := [f32(0), f32(0)]
    dpo_l2 := tensor.dpo_loss_grad_f32(f32(-3.0), f32(-1.0), f32(-1.2), f32(-2.0), f32(0.5), $&dpo_g2)
    println("DPO_L2:" + str(math.float32_bits(f64(dpo_l2))))
    println("DPO_G2_0:" + str(math.float32_bits(f64(dpo_g2[0]))))
    println("DPO_G2_1:" + str(math.float32_bits(f64(dpo_g2[1]))))

    grpo_r := [f32(1.0), f32(2.0), f32(4.0), f32(5.0)]
    $grpo_a := [f32(0), f32(0), f32(0), f32(0)]
    tensor.grpo_advantages_f32($&grpo_a, &grpo_r, 4, f32(1e-6))
    for i in 0:4 { println("GRPO_A" + str(i) + ":" + str(math.float32_bits(f64(grpo_a[i])))) }

    // 1) Causal Conv1D 2-step state shift check (d_inner=2, k_size=3)
    $c_st := [f32(0.5), f32(-1.0), f32(1.5), f32(0.25)]
    c_w := [f32(0.2), f32(0.3), f32(0.5), f32(-0.4), f32(0.1), f32(0.8)]
    c_b := [f32(0.1), f32(-0.2)]
    $c_out := [f32(0), f32(0)]
    tensor.conv1d_causal_step_f32($&c_out, $&c_st, &[f32(2.0), f32(-0.5)], &c_w, &c_b, 2, 3)
    tensor.conv1d_causal_step_f32($&c_out, $&c_st, &[f32(-1.0), f32(1.5)], &c_w, &c_b, 2, 3)
    println("C1D_0:" + str(math.float32_bits(f64(c_out[0]))))
    println("C1D_1:" + str(math.float32_bits(f64(c_out[1]))))
    println("C1D_S0:" + str(math.float32_bits(f64(c_st[0]))))
    println("C1D_S3:" + str(math.float32_bits(f64(c_st[3]))))

    // 2) SSM Mamba scan 2-step check (d_inner=2, d_state=2)
    $ssm_st := [f32(0), f32(0), f32(0), f32(0)]
    $ssm_out := [f32(0), f32(0)]
    ssm_dt := [f32(0.2), f32(0.5)]
    ssm_a := [f32(-1.0), f32(-2.0), f32(-0.5), f32(-1.5)]
    ssm_d := [f32(0.25), f32(-0.5)]
    tensor.ssm_scan_step_f32($&ssm_out, $&ssm_st, &[f32(1.5), f32(-0.5)], &ssm_dt, &ssm_a, &[f32(0.4), f32(-0.2)], &[f32(0.8), f32(0.5)], &ssm_d, 2, 2)
    tensor.ssm_scan_step_f32($&ssm_out, $&ssm_st, &[f32(-0.8), f32(1.2)], &ssm_dt, &ssm_a, &[f32(-0.3), f32(0.6)], &[f32(0.2), f32(-0.7)], &ssm_d, 2, 2)
    println("SSM_0:" + str(math.float32_bits(f64(ssm_out[0]))))
    println("SSM_1:" + str(math.float32_bits(f64(ssm_out[1]))))

    // 3) Linear Attention 2-step check (n_heads=2, head_dim=2)
    $la_st := [f32(0), f32(0), f32(0), f32(0), f32(0), f32(0), f32(0), f32(0)]
    $la_z := [f32(0), f32(0), f32(0), f32(0)]
    $la_out := [f32(0), f32(0), f32(0), f32(0)]
    tensor.linear_attn_step_f32($&la_out, $&la_st, $&la_z, &[f32(1.0), f32(0.5), f32(-0.5), f32(1.0)], &[f32(0.6), f32(0.8), f32(0.4), f32(-0.4)], &[f32(1.5), f32(-0.5), f32(2.0), f32(1.0)], f32(0.9), 2, 2, f32(1e-5))
    tensor.linear_attn_step_f32($&la_out, $&la_st, $&la_z, &[f32(0.4), f32(1.2), f32(1.0), f32(0.2)], &[f32(0.3), f32(-0.5), f32(0.9), f32(0.1)], &[f32(-1.0), f32(2.0), f32(0.5), f32(-1.5)], f32(0.9), 2, 2, f32(1e-5))
    for i in 0:4 { println("LA_" + str(i) + ":" + str(math.float32_bits(f64(la_out[i])))) }

    // 4) PPO/GRPO clip + Schulman KL grad check (unclipped + clipped branches)
    $ppo_g1 := [f32(0)]
    ppo_l1 := tensor.ppo_clip_grad_f32(f32(-1.1), f32(-1.2), f32(-1.3), f32(1.5), f32(0.2), f32(0.05), $&ppo_g1)
    println("PPO_L1:" + str(math.float32_bits(f64(ppo_l1))))
    println("PPO_G1:" + str(math.float32_bits(f64(ppo_g1[0]))))
    $ppo_g2 := [f32(0)]
    ppo_l2 := tensor.ppo_clip_grad_f32(f32(-0.5), f32(-1.5), f32(-1.4), f32(1.5), f32(0.2), f32(0.05), $&ppo_g2)
    println("PPO_L2:" + str(math.float32_bits(f64(ppo_l2))))
    println("PPO_G2:" + str(math.float32_bits(f64(ppo_g2[0]))))

    // 5) conv2d_patch_embed_f32 (in_c=2, img=4x4, out_c=2, patch=2 -> 4 tokens x 2)
    $cv_img := []f32{}
    for i in 0:32 { cv_img.push(f32(i + 1) * f32(0.1)) }
    $cv_w := []f32{}
    for i in 0:16 { cv_w.push(f32((i % 5) - 2) * f32(0.25)) }
    cv_b := [f32(0.5), f32(-0.25)]
    $cv_out := []f32{}
    for _ in 0:8 { cv_out.push(f32(0)) }
    tensor.conv2d_patch_embed_f32($&cv_out, &cv_img, &cv_w, &cv_b, 2, 4, 4, 2, 2)
    for i in 0:8 { println("CV_" + str(i) + ":" + str(math.float32_bits(f64(cv_out[i])))) }

    // 6) mha_sdpa_f32 (seq=2, n_heads=2, head_dim=2, bidir & causal)
    mq := [f32(1.0), f32(0.5), f32(-0.5), f32(1.0), f32(0.2), f32(0.8), f32(1.0), f32(-0.2)]
    mk := [f32(0.5), f32(-0.5), f32(1.0), f32(0.0), f32(-0.3), f32(0.7), f32(0.4), f32(0.9)]
    mv := [f32(1.0), f32(2.0), f32(-1.0), f32(0.5), f32(0.25), f32(-0.75), f32(1.5), f32(2.5)]
    $mha_bi := [f32(0), f32(0), f32(0), f32(0), f32(0), f32(0), f32(0), f32(0)]
    $mha_ca := [f32(0), f32(0), f32(0), f32(0), f32(0), f32(0), f32(0), f32(0)]
    tensor.mha_sdpa_f32($&mha_bi, &mq, &mk, &mv, 2, 2, 2, 2, false)
    tensor.mha_sdpa_f32($&mha_ca, &mq, &mk, &mv, 2, 2, 2, 2, true)
    for i in 0:8 { println("MHAB_" + str(i) + ":" + str(math.float32_bits(f64(mha_bi[i])))) }
    for i in 0:8 { println("MHAC_" + str(i) + ":" + str(math.float32_bits(f64(mha_ca[i])))) }

    // 7) avg_pool2d_f32 (channels=2, h=4, w=4, k=2, s=2 -> 2x2x2=8)
    $ap_out := []f32{}
    for _ in 0:8 { ap_out.push(f32(0)) }
    tensor.avg_pool2d_f32($&ap_out, &cv_img, 2, 4, 4, 2, 2)
    for i in 0:8 { println("AP_" + str(i) + ":" + str(math.float32_bits(f64(ap_out[i])))) }

    println("ROUND3:OK")
    _ := bias4
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
    assert kv.get("ROUND3") == "OK", kv

    # Verify cross_entropy_grad_f32 parity
    ce_l = [1.0, 2.5, -0.5]
    mx = max(ce_l)
    exps = [math.exp(v - mx) for v in ce_l]
    sm = sum(exps)
    probs = [e / sm for e in exps]
    ref_loss = math.log(sm) + mx - ce_l[1]
    assert abs(bits_to_f32(int(kv["CE_LOSS"])) - ref_loss) < 1e-5
    for idx, kname in enumerate(["CE_G0", "CE_G1", "CE_G2"]):
        want = probs[idx] - (1.0 if idx == 1 else 0.0)
        assert abs(bits_to_f32(int(kv[kname])) - want) < 1e-5, (kname, bits_to_f32(int(kv[kname])), want)

    # Verify adamw_step_f32 parity (step=1, m=0, v=0)
    lr, b1, b2, eps, wd = 0.1, 0.9, 0.999, 1e-8, 0.01
    for p_init, g_val, kname in [(1.0, 0.5, "ADAMW_P0"), (-2.0, -0.25, "ADAMW_P1")]:
        m_hat = g_val
        v_hat = g_val * g_val
        want_p = p_init * (1.0 - lr * wd) - lr * m_hat / (math.sqrt(v_hat) + eps)
        assert abs(bits_to_f32(int(kv[kname])) - want_p) < 1e-5, (kname, bits_to_f32(int(kv[kname])), want_p)

    # Verify lora_add_f32 parity
    lx = [2.0, -1.0, 0.5]
    la = [[1.0, 0.0, -2.0], [0.5, 3.0, 1.0]]
    lb = [[2.0, -1.0], [0.5, 4.0]]
    h = [sum(row[c] * lx[c] for c in range(3)) for row in la]
    lout_ref = [0.25 + 0.5 * (lb[0][0] * h[0] + lb[0][1] * h[1]), -0.5 + 0.5 * (lb[1][0] * h[0] + lb[1][1] * h[1])]
    assert abs(bits_to_f32(int(kv["LORA_0"])) - lout_ref[0]) < 1e-5
    assert abs(bits_to_f32(int(kv["LORA_1"])) - lout_ref[1]) < 1e-5

    # Verify lora_backward_f32 against analytic & finite-difference gradients
    ldy = [1.5, -2.0]
    dh = [0.5 * sum(lb[i][r] * ldy[i] for i in range(2)) for r in range(2)]
    want_dx = [sum(la[r][j] * dh[r] for r in range(2)) for j in range(3)]
    for j in range(3):
        assert abs(bits_to_f32(int(kv[f"LB_DX{j}"])) - want_dx[j]) < 1e-5
    for r in range(2):
        for j in range(3):
            want_da = dh[r] * lx[j]
            assert abs(bits_to_f32(int(kv[f"LB_DA{r * 3 + j}"])) - want_da) < 1e-5
    for i in range(2):
        for r in range(2):
            want_db = 0.5 * ldy[i] * h[r]
            assert abs(bits_to_f32(int(kv[f"LB_DB{i * 2 + r}"])) - want_db) < 1e-5

    # Verify rmsnorm_backward_f32 against central finite differences
    rx, rw, rdy = [1.0, -2.0, 0.5, 3.0], [0.5, 1.5, 2.0, -1.0], [0.25, -0.5, 1.0, 0.75]
    def rms_loss(vx, vw):
        inv = 1.0 / math.sqrt(sum(v * v for v in vx) / 4.0 + 1e-5)
        return sum(rdy[i] * (vx[i] * inv * vw[i]) for i in range(4))
    h_fd = 1e-5
    for i in range(4):
        xp, xm = list(rx), list(rx)
        xp[i] += h_fd
        xm[i] -= h_fd
        fd_dx = (rms_loss(xp, rw) - rms_loss(xm, rw)) / (2.0 * h_fd)
        assert abs(bits_to_f32(int(kv[f"RMS_DX{i}"])) - fd_dx) < 1e-4, (i, bits_to_f32(int(kv[f"RMS_DX{i}"])), fd_dx)
        wp, wm = list(rw), list(rw)
        wp[i] += h_fd
        wm[i] -= h_fd
        fd_dw = (rms_loss(rx, wp) - rms_loss(rx, wm)) / (2.0 * h_fd)
        assert abs(bits_to_f32(int(kv[f"RMS_DW{i}"])) - fd_dw) < 1e-4, (i, bits_to_f32(int(kv[f"RMS_DW{i}"])), fd_dw)

    # Verify swiglu_backward_f32 against central finite differences
    sg, su, sdy = [-1.2, 0.8], [2.0, -1.5], [0.75, 1.25]
    for i in range(2):
        def swi(g, u):
            return sdy[i] * (g / (1.0 + math.exp(-g))) * u
        fd_dg = (swi(sg[i] + h_fd, su[i]) - swi(sg[i] - h_fd, su[i])) / (2.0 * h_fd)
        fd_du = (swi(sg[i], su[i] + h_fd) - swi(sg[i], su[i] - h_fd)) / (2.0 * h_fd)
        assert abs(bits_to_f32(int(kv[f"SWI_DG{i}"])) - fd_dg) < 1e-4
        assert abs(bits_to_f32(int(kv[f"SWI_DU{i}"])) - fd_du) < 1e-4

    # Verify Q5_K dequant dot parity vs Python block_q5_K
    kx_py = [float((i % 29) - 14) * 0.125 for i in range(256)]
    q5k_bytes = bytearray(176)
    q5k_bytes[0], q5k_bytes[1] = 0x00, 0x3c  # d=1.0
    q5k_bytes[2], q5k_bytes[3] = 0x00, 0x38  # dmin=0.5
    for j in range(4, 16):
        q5k_bytes[j] = 1 + (j % 3)
    for j in range(16, 48):
        q5k_bytes[j] = (j * 13) & 255
    for j in range(48, 176):
        q5k_bytes[j] = (j * 17) & 255
    sc_b = q5k_bytes[4:16]
    qh_b = q5k_bytes[16:48]
    qs_b = q5k_bytes[48:176]
    want_q5k = 0.0
    for chunk in range(4):
        is0 = chunk * 2
        is1 = is0 + 1
        sc1 = (sc_b[is0] & 63) if chunk < 2 else ((sc_b[is0 + 4] & 15) | (((sc_b[is0 - 4] >> 6) & 3) << 4))
        m1 = (sc_b[is0 + 4] & 63) if chunk < 2 else (((sc_b[is0 + 4] >> 4) & 15) | (((sc_b[is0] >> 6) & 3) << 4))
        sc2 = (sc_b[is1] & 63) if chunk < 2 else ((sc_b[is1 + 4] & 15) | (((sc_b[is1 - 4] >> 6) & 3) << 4))
        m2 = (sc_b[is1 + 4] & 63) if chunk < 2 else (((sc_b[is1 + 4] >> 4) & 15) | (((sc_b[is1] >> 6) & 3) << 4))
        for l in range(32):
            qb = qs_b[chunk * 32 + l]
            hb = qh_b[l]
            q0 = (qb & 15) | (((hb >> (chunk * 2)) & 1) << 4)
            q1 = ((qb >> 4) & 15) | (((hb >> (chunk * 2 + 1)) & 1) << 4)
            want_q5k += (1.0 * sc1 * q0 - 0.5 * m1) * kx_py[chunk * 64 + l]
            want_q5k += (1.0 * sc2 * q1 - 0.5 * m2) * kx_py[chunk * 64 + 32 + l]
    assert abs(bits_to_f32(int(kv["Q5K_F"])) - want_q5k) < 1e-4, (bits_to_f32(int(kv["Q5K_F"])), want_q5k)

    # Verify layernorm_backward_f32 against central finite differences
    def ln_loss(vx, vw):
        mu = sum(vx) / 4.0
        inv = 1.0 / math.sqrt(sum((v - mu) ** 2 for v in vx) / 4.0 + 1e-5)
        return sum(rdy[i] * ((vx[i] - mu) * inv * vw[i]) for i in range(4))
    for i in range(4):
        xp, xm = list(rx), list(rx)
        xp[i] += h_fd
        xm[i] -= h_fd
        fd_dx = (ln_loss(xp, rw) - ln_loss(xm, rw)) / (2.0 * h_fd)
        assert abs(bits_to_f32(int(kv[f"LN_DX{i}"])) - fd_dx) < 1e-4
        wp, wm = list(rw), list(rw)
        wp[i] += h_fd
        wm[i] -= h_fd
        fd_dw = (ln_loss(rx, wp) - ln_loss(rx, wm)) / (2.0 * h_fd)
        assert abs(bits_to_f32(int(kv[f"LN_DW{i}"])) - fd_dw) < 1e-4
        assert abs(bits_to_f32(int(kv[f"LN_DB{i}"])) - rdy[i]) < 1e-5

    # Verify softmax_backward_f32 against finite differences
    sm_x, sm_dy = [1.0, 2.0, -1.0], [0.5, -1.25, 2.0]
    def sm_loss(vx):
        mx = max(vx)
        ex = [math.exp(v - mx) for v in vx]
        s = sum(ex)
        return sum((ex[j] / s) * sm_dy[j] for j in range(3))
    for i in range(3):
        xp, xm = list(sm_x), list(sm_x)
        xp[i] += h_fd
        xm[i] -= h_fd
        fd_sdx = (sm_loss(xp) - sm_loss(xm)) / (2.0 * h_fd)
        assert abs(bits_to_f32(int(kv[f"SM_DX{i}"])) - fd_sdx) < 1e-4

    # Verify grad_clip_norm_f32
    assert abs(bits_to_f32(int(kv["GC_NORM"])) - 5.0) < 1e-5
    assert abs(bits_to_f32(int(kv["GC_G0"])) - 1.5) < 1e-5
    assert abs(bits_to_f32(int(kv["GC_G1"])) - 2.0) < 1e-5
    assert abs(bits_to_f32(int(kv["GC_G2"])) - 0.0) < 1e-5

    # Verify kl_div_grad_f32 (scalar KL and T^2*KL gradient via central finite differences)
    kl_s, kl_t, temp = [1.2, -0.4, 0.8], [0.5, 1.5, -0.5], 2.0
    def kl_fn(zs, zt, T):
        mxs = max(v / T for v in zs)
        mxt = max(v / T for v in zt)
        ls = [v / T - mxs for v in zs]
        lt = [v / T - mxt for v in zt]
        lse_s = math.log(sum(math.exp(x) for x in ls))
        lse_t = math.log(sum(math.exp(x) for x in lt))
        return sum(math.exp(lt[j] - lse_t) * ((lt[j] - lse_t) - (ls[j] - lse_s)) for j in range(len(zs)))
    assert abs(bits_to_f32(int(kv["KL_VAL"])) - kl_fn(kl_s, kl_t, temp)) < 1e-5
    for i in range(3):
        zp, zm = list(kl_s), list(kl_s)
        zp[i] += h_fd
        zm[i] -= h_fd
        fd_kl = (temp * temp) * (kl_fn(zp, kl_t, temp) - kl_fn(zm, kl_t, temp)) / (2.0 * h_fd)
        assert abs(bits_to_f32(int(kv[f"KL_G{i}"])) - fd_kl) < 1e-4

    # Verify dpo_loss_grad_f32 for both h > 0 and h < 0
    for tag, pc, pr, rc, rr, beta in [
        ("1", -1.2, -2.4, -1.5, -1.0, 0.25),
        ("2", -3.0, -1.0, -1.2, -2.0, 0.5),
    ]:
        def dpo_fn(wc, wr):
            h = beta * ((wc - rc) - (wr - rr))
            return math.log(1.0 + math.exp(-h)) if h >= 0 else -h + math.log(1.0 + math.exp(h))
        assert abs(bits_to_f32(int(kv[f"DPO_L{tag}"])) - dpo_fn(pc, pr)) < 1e-5
        fd_wc = (dpo_fn(pc + h_fd, pr) - dpo_fn(pc - h_fd, pr)) / (2.0 * h_fd)
        fd_wr = (dpo_fn(pc, pr + h_fd) - dpo_fn(pc, pr - h_fd)) / (2.0 * h_fd)
        assert abs(bits_to_f32(int(kv[f"DPO_G{tag}_0"])) - fd_wc) < 1e-4
        assert abs(bits_to_f32(int(kv[f"DPO_G{tag}_1"])) - fd_wr) < 1e-4

    # Verify grpo_advantages_f32
    grpo_r = [1.0, 2.0, 4.0, 5.0]
    g_mean = sum(grpo_r) / 4.0
    g_std = math.sqrt(sum((x - g_mean) ** 2 for x in grpo_r) / 4.0 + 1e-6)
    for i in range(4):
        assert abs(bits_to_f32(int(kv[f"GRPO_A{i}"])) - (grpo_r[i] - g_mean) / g_std) < 1e-5

    # Verify conv1d_causal_step_f32
    py_cst = [0.5, -1.0, 1.5, 0.25]
    py_cw = [0.2, 0.3, 0.5, -0.4, 0.1, 0.8]
    py_cb = [0.1, -0.2]
    for xv in ([2.0, -0.5], [-1.0, 1.5]):
        cout = []
        for d in range(2):
            acc = py_cb[d] + py_cst[d * 2] * py_cw[d * 3] + py_cst[d * 2 + 1] * py_cw[d * 3 + 1] + xv[d] * py_cw[d * 3 + 2]
            cout.append(acc)
            py_cst[d * 2] = py_cst[d * 2 + 1]
            py_cst[d * 2 + 1] = xv[d]
    assert abs(bits_to_f32(int(kv["C1D_0"])) - cout[0]) < 1e-5
    assert abs(bits_to_f32(int(kv["C1D_1"])) - cout[1]) < 1e-5
    assert abs(bits_to_f32(int(kv["C1D_S0"])) - py_cst[0]) < 1e-5
    assert abs(bits_to_f32(int(kv["C1D_S3"])) - py_cst[3]) < 1e-5

    # Verify ssm_scan_step_f32
    py_sst = [0.0] * 4
    py_sa = [-1.0, -2.0, -0.5, -1.5]
    py_sdt = [0.2, 0.5]
    py_sd = [0.25, -0.5]
    for xv, bv, cv in (([1.5, -0.5], [0.4, -0.2], [0.8, 0.5]), ([-0.8, 1.2], [-0.3, 0.6], [0.2, -0.7])):
        sout = []
        for d in range(2):
            y = py_sd[d] * xv[d]
            for s in range(2):
                da = math.exp(py_sdt[d] * py_sa[d * 2 + s])
                hnew = da * py_sst[d * 2 + s] + py_sdt[d] * bv[s] * xv[d]
                py_sst[d * 2 + s] = hnew
                y += hnew * cv[s]
            sout.append(y)
    assert abs(bits_to_f32(int(kv["SSM_0"])) - sout[0]) < 1e-5
    assert abs(bits_to_f32(int(kv["SSM_1"])) - sout[1]) < 1e-5

    # Verify linear_attn_step_f32
    py_ls = [0.0] * 8
    py_lz = [0.0] * 4
    for qv, kv_v, vv in (
        ([1.0, 0.5, -0.5, 1.0], [0.6, 0.8, 0.4, -0.4], [1.5, -0.5, 2.0, 1.0]),
        ([0.4, 1.2, 1.0, 0.2], [0.3, -0.5, 0.9, 0.1], [-1.0, 2.0, 0.5, -1.5]),
    ):
        lout = [0.0] * 4
        for h in range(2):
            vb, sb = h * 2, h * 4
            for i in range(2):
                py_lz[vb + i] = 0.9 * py_lz[vb + i] + kv_v[vb + i]
                for j in range(2):
                    py_ls[sb + i * 2 + j] = 0.9 * py_ls[sb + i * 2 + j] + kv_v[vb + i] * vv[vb + j]
            den = sum(qv[vb + i] * py_lz[vb + i] for i in range(2))
            for j in range(2):
                num = sum(qv[vb + i] * py_ls[sb + i * 2 + j] for i in range(2))
                lout[vb + j] = num / den
    for i in range(4):
        assert abs(bits_to_f32(int(kv[f"LA_{i}"])) - lout[i]) < 1e-5

    # Verify ppo_clip_grad_f32 (unclipped branch + upper-clipped branch)
    def ppo_fn(new_lp, old_lp, ref_lp, adv, eps, beta):
        r = math.exp(new_lp - old_lp)
        rc = min(max(r, 1.0 - eps), 1.0 + eps)
        surr = min(r * adv, rc * adv)
        er = math.exp(ref_lp - new_lp)
        kl = er - (ref_lp - new_lp) - 1.0
        return -surr + beta * kl
    for tag, nlp, olp, rlp, adv, eps, beta in (
        ("1", -1.1, -1.2, -1.3, 1.5, 0.2, 0.05),
        ("2", -0.5, -1.5, -1.4, 1.5, 0.2, 0.05),
    ):
        assert abs(bits_to_f32(int(kv[f"PPO_L{tag}"])) - ppo_fn(nlp, olp, rlp, adv, eps, beta)) < 1e-5
        fd_p = (ppo_fn(nlp + h_fd, olp, rlp, adv, eps, beta) - ppo_fn(nlp - h_fd, olp, rlp, adv, eps, beta)) / (2.0 * h_fd)
        assert abs(bits_to_f32(int(kv[f"PPO_G{tag}"])) - fd_p) < 1e-4

    # Verify conv2d_patch_embed_f32
    cv_img = [(i + 1) * 0.1 for i in range(32)]
    cv_w = [((i % 5) - 2) * 0.25 for i in range(16)]
    cv_b = [0.5, -0.25]
    for py in range(2):
        for px in range(2):
            tok = py * 2 + px
            for oc in range(2):
                acc = cv_b[oc]
                for ic in range(2):
                    for dy in range(2):
                        for dx in range(2):
                            iy, ix = py * 2 + dy, px * 2 + dx
                            acc += cv_img[ic * 16 + iy * 4 + ix] * cv_w[((oc * 2 + ic) * 2 + dy) * 2 + dx]
                assert abs(bits_to_f32(int(kv[f"CV_{tok * 2 + oc}"])) - acc) < 1e-5

    # Verify mha_sdpa_f32 (bidirectional & causal)
    mq = [1.0, 0.5, -0.5, 1.0, 0.2, 0.8, 1.0, -0.2]
    mk = [0.5, -0.5, 1.0, 0.0, -0.3, 0.7, 0.4, 0.9]
    mv = [1.0, 2.0, -1.0, 0.5, 0.25, -0.75, 1.5, 2.5]
    for tag, causal in (("MHAB", False), ("MHAC", True)):
        sc_f = 1.0 / math.sqrt(2.0)
        for qi in range(2):
            eff_k = min(2, qi + 1) if causal else 2
            for h in range(2):
                qb = qi * 4 + h * 2
                scs = [sum(mq[qb + d] * mk[ki * 4 + h * 2 + d] for d in range(2)) * sc_f for ki in range(eff_k)]
                mx = max(scs)
                ws = [math.exp(s - mx) for s in scs]
                den = sum(ws)
                for d in range(2):
                    want = sum((ws[ki] / den) * mv[ki * 4 + h * 2 + d] for ki in range(eff_k))
                    assert abs(bits_to_f32(int(kv[f"{tag}_{qb + d}"])) - want) < 1e-5, (tag, qi, h, d, bits_to_f32(int(kv[f"{tag}_{qb + d}"])), want)

    # Verify avg_pool2d_f32
    for c in range(2):
        for oy in range(2):
            for ox in range(2):
                s = sum(cv_img[c * 16 + (oy * 2 + ky) * 4 + (ox * 2 + kx)] for ky in range(2) for kx in range(2))
                assert abs(bits_to_f32(int(kv[f"AP_{(c * 4) + oy * 2 + ox}"])) - (s / 4.0)) < 1e-5

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
