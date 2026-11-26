#!/usr/bin/env python3
"""Verify low-precision tensor types, model loading, and paged KV storage."""

import argparse
import bisect
import json
import math
import os
import struct
import subprocess
import tempfile
from pathlib import Path

from test_llm_engine import (
    CFG, bits_to_f32, generate_weight_dict, parse_bench, parse_verify, write_gguf_q4_0, write_safetensors,
)
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
    if !ok { >> errors.new(message) }
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
    view := tensor.contiguous_view(dtype, &shape, 6, storage.len) or >>
    require(view.is_contiguous() && view.rank() == 2 && view.element_count() == 6, "shape") or >>
    require(view.storage_start() == 6 && view.storage_end() == 18, "span") or >>
    coord := [1, 2]
    value := view.read_f32(&storage, &coord) or >>
    require(value == f32(6), "indexed value") or >>

    transposed := view.transpose(0, 1) or >>
    first_axis := transposed.stride(0) or >>
    require(!transposed.is_contiguous() && first_axis == 1, "transpose stride") or >>
    $values := []f32{}
    transposed.append_f32(&storage, $&values) or >>
    expected := [f32(1), f32(4), f32(2), f32(5), f32(3), f32(6)]
    for i in 0:expected.len {
        require(values[i] == expected[i], "transpose order") or >>
    }
    stepped := view.slice(1, 0, 3, 2) or >>
    stride := stepped.stride(1) or >>
    require(stride == 2, "slice stride") or >>
    stepped.copy_f32(&storage, 1, 2, $&values, 3) or >>
    require(values[3] == f32(3) && values[4] == f32(4), "sliced range") or >>
    broadcast_strides := [0, 1]
    broadcast := tensor.strided_view(dtype, &shape, &broadcast_strides, 6, storage.len) or >>
    repeated := broadcast.read_f32_linear(&storage, 4) or >>
    require(repeated == f32(2), "stride-zero broadcast") or >>
    scalar_shape := []int{}
    scalar := tensor.contiguous_view(dtype, &scalar_shape, 8, storage.len) or >>
    scalar_value := scalar.read_f32(&storage, &scalar_shape) or >>
    require(scalar_value == f32(2), "rank-zero scalar") or >>
    empty := view.slice(1, 3, 3, 1) or >>
    require(empty.element_count() == 0, "empty slice") or >>

    _ := empty.read_f32_linear(&storage, 0) or (err) { << 1 }
    >> errors.new("empty read succeeded")
}

fn check_rejections() int {
    dtype := tensor.dtype_f16()
    bad_shape := [-1, 3]
    shape := [2, 3]
    strides := [9223372036854775807, 1]
    huge_shape := [9223372036854775807, 2]
    _ := tensor.contiguous_view(dtype, &bad_shape, 0, 12) or (err) {
        _ := tensor.contiguous_view(dtype, &huge_shape, 0, 12) or (err) {
            _ := tensor.strided_view(dtype, &shape, &strides, 0, 12) or (err) {
                _ := tensor.contiguous_view(dtype, &shape, 1, 12) or (err) { << 4 }
                >> errors.new("short backing succeeded")
            }
            >> errors.new("stride overflow succeeded")
        }
        >> errors.new("shape overflow succeeded")
    }
    >> errors.new("negative shape succeeded")
}

fn check_blocks() int {
    half := string_from_byte(0) + string_from_byte(56)
    $q4 := "x" + half
    $q8 := "x" + half
    for i in 0:16 { q4.push_str(string_from_byte(i | ((15 - i) << 4))) }
    for i in 0:32 { q8.push_str(string_from_byte((i - 16) & 255)) }
    a := tensor.read_q4_0(&q4, 1) or >>
    b := tensor.read_q8_0(&q8, 1) or >>
    $values := []f32{}
    a.append_f32($&values)
    b.append_f32($&values)
    for i in 0:32 {
        $quant4 := i - 8
        if i >= 16 { quant4 = 23 - i }
        expected4 := f32(quant4) * f32(0.5)
        expected8 := f32(i - 16) * f32(0.5)
        indexed4 := a.at(i) or >>
        indexed8 := b.at(i) or >>
        require(indexed4 == expected4 && values[i] == expected4, "Q4_0 layout") or >>
        require(indexed8 == expected8 && values[i + 32] == expected8, "Q8_0 signed lanes") or >>
    }
    _ := tensor.read_q8_0(&q8, 2) or (err) { << 1 }
    >> errors.new("truncated Q8_0 block succeeded")
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
                require(dtype.encode_bits(value) == raw, "16-bit roundtrip") or >>
            }
        }
    }
    require(tensor.f16(f32(1.00048828125)).bits == 0x3c00, "F16 even tie") or >>
    require(tensor.f16(f32(1.00146484375)).bits == 0x3c02, "F16 odd tie") or >>
    require(tensor.f16(f32(65520)).bits == 0x7c00, "F16 overflow") or >>
    require(tensor.bf16(f32(1.00390625)).bits == 0x3f80, "BF16 even tie") or >>
    require(tensor.bf16(f32(1.01171875)).bits == 0x3f82, "BF16 odd tie") or >>
    require(tensor.fp8_e4m3fn(f32(1.0625)).bits == 0x38, "FP8 even tie") or >>
    require(tensor.fp8_e4m3fn(f32(1.1875)).bits == 0x3a, "FP8 odd tie") or >>
    require(tensor.fp8_e4m3fn(f32(1000)).bits == 0x7e, "E4M3FN saturation") or >>
    require(tensor.fp8_e5m2(f32(100000)).bits == 0x7b, "E5M2 saturation") or >>
    << 0
}

fn main() int {
    check_all() or (err) {
        eprintln(err.msg())
        << 1
    }
    << 0
}

fn check_all() int {
    check_view() or >>
    check_rejections() or >>
    check_blocks() or >>
    check_narrow() or >>
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
        check_model(args.compiler.resolve(), env, work, root / "examples/llm_engine/main.xu")


if __name__ == "__main__":
    main()
