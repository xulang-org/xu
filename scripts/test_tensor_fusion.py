#!/usr/bin/env python3
"""Check opt-in f32 tensor fusion on identical Xu sources with the pass on and off."""

import argparse
import math
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import tempfile


PRELUDE = """@main
#math
#os

fn bits(value f32) int { << math.float32_bits(f64(value)) }
fn from_bits(value int) f32 { << f32(math.float32_from_bits(value)) }
"""
EXPECTED = [0, 0x80000000, 0x40E00000, 0x00000002, 0x7F800000]
INPUT_BITS = {
    "x": [0x3F800001, 0x80000000, 0x40000000, 0x00000001, 0x7F7FFFFF],
    "scale": [0x3F800001, 0x3F800000, 0x40400000, 0x3F800000, 0x40000000],
    "bias": [0xBF800002, 0x80000000, 0x3F800000, 0x00000001, 0x00000000],
}
RMS_INPUT_PAIRS = [
    (4096.0, 2**-13), (0.0, 1.0), (-2.0, 0.0), (-0.0, -0.0), (1.0, 2**-24),
]
RMS_REUSE_EXTENT = 11
RMS_WEIGHTS = ([1.1875, -2.625, 0.125, 3.0, 1.015625] * 3)[:RMS_REUSE_EXTENT]


def fixture(name, n, variant="plain"):
    args = f"x &[{n}]f32" if variant == "borrowed" else ""
    dst = "x" if variant == "overlap" else "out"
    offset = f"(i + 1) % {n}" if variant == "shifted" else "i"
    x_extent = n - 1 if variant == "bounds" else n
    extra = {
        "observed": "    if bits(tmp[2]) != 0x40c00000 { << 2 }\n",
        "captured": "    read := fn() f32 { << tmp[2] }\n    if bits(read()) != 0x40c00000 { << 2 }\n",
    }.get(variant, "")
    sources = ""
    for source, values in INPUT_BITS.items():
        if source == "x" and variant == "borrowed":
            continue
        extent = x_extent if source == "x" else n
        items = ", ".join(f"from_bits({values[i % len(values)]:#x})" for i in range(extent))
        mutable = "$" if source == dst else ""
        sources += f"    {mutable}{source} := [{extent}]f32{{{items}}}\n"
    if dst == "out":
        sources += f"    $out := [{n}]f32{{}}\n"
    expected = [EXPECTED[i % len(EXPECTED)] for i in range(n)]
    if variant == "shifted":
        # Use a separate output value known to depend on the shifted index.
        check = f"    if bits({dst}[0]) != 0xbf800002 {{ << 1 }}\n"
    else:
        values = ", ".join(hex(value) for value in expected)
        check = f"""    expected := [{values}]
    for k in 0:{n} {{
        if bits({dst}[k]) != expected[k] {{ << 1 }}
    }}
"""
    return f"""
fn {name}({args}) int {{
{sources}    $tmp := [{n}]f32{{}}
    for i in 0:{n} {{ tmp[i] = x[{offset}] * scale[i] }}
    for j in 0:{n} {{ {dst}[j] = tmp[j] + bias[j] }}
{extra}{check}    << 0
}}
"""


def float_bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def xu_f32s(values):
    return ", ".join(f"from_bits({float_bits(value):#x})" for value in values)


def rms_fixture(name, n, variant):
    x, skip = zip(*(RMS_INPUT_PAIRS[i % len(RMS_INPUT_PAIRS)] for i in range(n)))
    if variant == "round_add":
        x, skip = (2**-24,), (1.0,)
    residual = [f32(a + b) for a, b in zip(x, skip)]
    reduce_extent = n - 1 if variant == "short" else n
    total = 0.0
    for i in range(reduce_extent):
        neighbor = (i + 1) % n if variant == "shifted" else i
        total = f32(total + f32(residual[i] * residual[neighbor]))
    epsilon = 1e-5
    inv_rms = f32(1.0 / math.sqrt(total / n + epsilon))
    expected = [float_bits(f32(value * inv_rms)) for value in residual]
    input_extent = n - 1 if variant == "bounds" else n
    x_values = xu_f32s(x[:input_extent])
    skip_values = xu_f32s(skip)
    right_index = f"(j + 1) % {n}" if variant == "shifted" else "j"
    seed = "    $sum := f32(0.0)\n"
    before, between = seed, ""
    if variant == "late_seed":
        before, between = "", seed
    if variant == "seed_call":
        before, between = "", "    $sum := from_bits(0)\n"
    check = f"    if bits(sum) != {float_bits(total):#x} {{ << 1 }}\n"
    out = ""
    if variant == "captured":
        check += f"""    read := fn() f32 {{ << tmp[0] }}
    if bits(read()) != {float_bits(residual[0]):#x} {{ << 2 }}
"""
    elif variant != "reduce_only":
        out = f"    $out := [{n}]f32{{}}\n"
        values = ", ".join(f"{v:#x}" for v in expected)
        check += f"""    inv_rms := f32(1.0 / math.sqrt(f64(sum) / f64({n}) + {epsilon}))
    for k in 0:{n} {{ out[k] = tmp[k] * inv_rms }}
    expected := [{values}]
    for k in 0:{n} {{
        if bits(out[k]) != expected[k] {{ << 2 }}
    }}
"""
    reduce_body = f"sum += tmp[j] * tmp[{right_index}]"
    if variant == "bound_value":
        reduce_body = "value := tmp[j]\n        sum += value * value"
    return f"""
fn {name}() int {{
    x := [{input_extent}]f32{{{x_values}}}
    skip := [{n}]f32{{{skip_values}}}
{out}{before}    $tmp := [{n}]f32{{}}
    for i in 0:{n} {{ tmp[i] = x[i] + skip[i] }}
{between}    for j in 0:{reduce_extent} {{
        {reduce_body}
    }}
{check}    << 0
}}
"""


def rms_reuse_fixture(name, variant):
    n = RMS_REUSE_EXTENT
    # The second weighted result differs by one bit if the first
    # multiplication is rounded late or the two multiplications reassociate.
    pairs = [(4096.0, 2**-13), (-1.35, 0.0), (-2.4, 0.0), (-0.0, -0.0), (1.2, 0.0)]
    x, skip = zip(*(pairs[i % len(pairs)] for i in range(n)))
    residual = [f32(f32(a) + f32(b)) for a, b in zip(x, skip)]
    total = 0.0
    for value in residual:
        total = f32(total + f32(value * value))

    weighted = variant in ("weighted", "mutating_scale", "borrowed_weight")
    weights = RMS_WEIGHTS.copy()
    weight_decl = ""
    formals = ""
    if variant == "borrowed_weight":
        formals = f"weight &[{n}]f32"
    elif weighted:
        mutable = "$" if variant == "mutating_scale" else ""
        weight_decl = f"    {mutable}weight := [{n}]f32{{{xu_f32s(weights)}}}\n"

    extra = " + f64(tmp[1])" if variant == "scale_reads_tmp" else ""
    scale = f"f32(1.0 / math.sqrt(f64(sum) / f64({n}) + 0.00001{extra}))"
    helper = ""
    if variant == "mutating_scale":
        weights[0] = -0.75
        scale = "adjust_scale(sum, $&weight)"
        helper = f"""
fn adjust_scale(sum f32, weight $&[{n}]f32) f32 {{
    weight[0] = f32(-0.75)
    << f32(1.0 / math.sqrt(f64(sum) / f64({n}) + 0.00001))
}}
"""
    mean = total / n + 0.00001
    if extra:
        mean += residual[1]
    inv_rms = f32(1.0 / math.sqrt(mean))
    normalized = [f32(value * inv_rms) for value in residual]
    product = "tmp[k] * inv_rms"
    if weighted:
        normalized = [f32(value * weight) for value, weight in zip(normalized, weights)]
        product = f"({product}) * weight[k]"
    out_index = "k"
    if variant == "shifted_output":
        out_index = f"(k + 1) % {n}"
        normalized = normalized[-1:] + normalized[:-1]
    out_extent = n
    if variant == "partial_output":
        out_extent = n - 1
        normalized[-1] = 0.0
    expected = ", ".join(f"{float_bits(value):#x}" for value in normalized)
    observe = ""
    if variant == "captured_tmp":
        observe = f"""    read := fn() f32 {{ << tmp[0] }}
    if bits(read()) != {float_bits(residual[0]):#x} {{ << 2 }}
"""
    return helper + f"""
fn {name}({formals}) int {{
    x := [{n}]f32{{{xu_f32s(x)}}}
    skip := [{n}]f32{{{xu_f32s(skip)}}}
{weight_decl}    $sum := f32(0.0)
    $tmp := [{n}]f32{{}}
    for i in 0:{n} {{ tmp[i] = x[i] + skip[i] }}
    for j in 0:{n} {{ sum += tmp[j] * tmp[j] }}
    inv_rms := {scale}
    $out := [{n}]f32{{}}
    for k in 0:{out_extent} {{ out[{out_index}] = {product} }}
{observe}    if bits(sum) != {float_bits(total):#x} {{ << 1 }}
    expected := [{expected}]
    for k in 0:{n} {{
        if bits(out[k]) != expected[k] {{ << 2 }}
    }}
    << 0
}}
"""


def build_source():
    pointwise = ["kernel_one", "kernel_width", "kernel_tail", "kernel_longer"]
    variants = ["observed", "captured", "overlap", "borrowed", "shifted", "bounds"]
    pointwise_fallbacks = ["kernel_" + v for v in variants]
    rms_cases = {"norm": 5, "late_seed": 17, "bound_value": 5, "round_add": 1,
                 "reduce_only": 17, "captured": 5}
    rms_fallbacks = ["shifted", "short", "seed_call", "bounds"]
    reuse_cases = ["plain", "weighted", "mutating_scale"]
    reuse_fallbacks = [
        "scale_reads_tmp", "captured_tmp", "shifted_output", "partial_output", "borrowed_weight",
    ]
    source = PRELUDE
    for name, n in zip(pointwise, (1, 4, 5, 17)):
        source += fixture(name, n)
    for name, variant in zip(pointwise_fallbacks, variants):
        source += fixture(name, 5, variant)
    for variant, n in rms_cases.items():
        source += rms_fixture("kernel_rms_" + variant, n, variant)
    for variant in rms_fallbacks:
        source += rms_fixture("kernel_rms_" + variant, 5, variant)
    for variant in reuse_cases + reuse_fallbacks:
        source += rms_reuse_fixture("kernel_rms_reuse_" + variant, variant)
    items = ", ".join(f"from_bits({b:#x})" for b in INPUT_BITS["x"])
    source += f"""
fn main() int {{
    args := os.argv()
    if args.len > 1 {{
        if args[1] == "rms-bounds" {{ << kernel_rms_bounds() }}
        << kernel_bounds()
    }}
    x := [5]f32{{{items}}}
    weight := [{len(RMS_WEIGHTS)}]f32{{{xu_f32s(RMS_WEIGHTS)}}}
"""
    positive = {name: (("tensor_i",), False) for name in pointwise}
    positive.update({
        "kernel_rms_" + v: (("tensor_reduce_i",), v != "reduce_only") for v in rms_cases
    })
    positive.update({
        "kernel_rms_reuse_" + v: (("tensor_reduce_i", "tensor_normalize_i"), False)
        for v in reuse_cases
    })
    positive.update({"kernel_rms_reuse_" + v: (("tensor_reduce_i",), True) for v in reuse_fallbacks})
    negative = pointwise_fallbacks + ["kernel_rms_" + v for v in rms_fallbacks]
    for name in list(positive) + negative:
        if name.endswith("_bounds"):
            continue
        args = {"kernel_borrowed": "&x", "kernel_rms_reuse_borrowed_weight": "&weight"}.get(name, "")
        source += f"""    rc_{name} := {name}({args})
    if rc_{name} != 0 {{
        println("{name}")
        << rc_{name}
    }}
"""
    return source + "    << 0\n}\n", positive, negative


def run(cmd, **kwargs):
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=120, **kwargs)
    if result.returncode:
        raise RuntimeError(f"{cmd} exited {result.returncode}\n{result.stdout}{result.stderr}")
    return result.stdout


def build(compiler, env, source, output, flags=()):
    mir = run([compiler, "build", *flags, source, "-o", output], env=env)
    if platform.system() == "Darwin":
        run(["codesign", "-fs", "-", output])
    return mir


def check_arm64_code(executable, positive):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return
    assembly = run(["otool", "-tV", executable])
    for name in positive:
        match = re.search(rf"^_+xu_main_{name}:\n((?:[0-9a-f]+[^\n]*\n)+)", assembly, re.M)
        assert match, name
        body = match[1]
        assert re.search(r"\bbl\s+___xu_tensor_(?:mul_add|add_sqsum|norm)_f32\b", body), name
        assert not re.search(r"\bf(?:n?madd|n?msub|mla|mls)\b", body), name
    for stub in ("___xu_tensor_mul_add_f32", "___xu_tensor_add_sqsum_f32", "___xu_tensor_norm_f32"):
        match = re.search(rf"^{stub}:\n((?:[0-9a-f]+[^\n]*\n)+)", assembly, re.M)
        if not match:
            continue
        body = match[1]
        assert re.search(r"\bf(?:mul|add)\.4s\b", body), stub
        assert not re.search(r"\bf(?:n?madd|n?msub|mla|mls)\b", body), stub


def benchmark(compiler, env, work):
    samples = 1000
    warmup = 200
    source = work / "benchmark.xu"
    kernels = [(kind, n) for kind in ("mul-add", "rmsnorm", "rms-reuse") for n in (128, 4096)]
    for kind, n in kernels:
        is_rms = kind != "mul-add"
        out_decl = f"    $out := [{n}]f32{{}}\n"
        kernel = f"""        $tmp := [{n}]f32{{}}
        for i in 0:{n} {{ tmp[i] = x[i] * scale[i] }}
        for j in 0:{n} {{ out[j] = tmp[j] + bias[j] }}"""
        marker = "call __xu_tensor_mul_add_f32("
        if is_rms:
            kernel = f"""        $sum := f32(0.0)
        $tmp := [{n}]f32{{}}
        for i in 0:{n} {{ tmp[i] = x[i] + skip[i] }}
        for j in 0:{n} {{
            value := tmp[j]
            sum += value * value
        }}
        inv_rms := f32(1.0 / math.sqrt(f64(sum) / f64({n}) + 0.00001))
        for k in 0:{n} {{ out[k] = tmp[k] * inv_rms }}"""
            marker = "call __xu_tensor_add_sqsum_f32("
            if kind == "rms-reuse":
                out_decl = ""
                normalize = f"        for k in 0:{n} {{ out[k] = tmp[k] * inv_rms }}"
                kernel = kernel.replace(normalize, f"        $out := [{n}]f32{{}}\n{normalize}")
                marker = "call __xu_tensor_norm_f32("
        arrays = {"x": 11, "skip": 7} if is_rms else {"x": 11, "scale": 7, "bias": 3}
        declarations = "".join(f"    ${name} := [{n}]f32{{}}\n" for name in arrays)
        initialize = "".join(f"        {name}[i] = f32(i % {divisor})\n"
                             for name, divisor in arrays.items())
        source.write_text(f"""@main
#time
#math

fn main() int {{
{declarations}{out_decl}    $elapsed := [{samples}]int{{}}
    for i in 0:{n} {{
{initialize}    }}
    $checksum := 0
    for sample in 0:{warmup + samples} {{
        start := time.now()
{kernel}
        duration := time.since(start)
        if sample >= {warmup} {{
            elapsed[sample - {warmup}] = duration
        }}
        checksum += math.float32_bits(f64(out[sample % {n}]))
    }}
    println(checksum)
    for k in 0:{samples} {{ println(elapsed[k]) }}
    << 0
}}
""")
        totals = []
        for mode, enabled in (("baseline", "0"), ("fusion", "1")):
            exe = work / ("bench-" + mode + (".exe" if os.name == "nt" else ""))
            mir = build(compiler, dict(env, XU_DUMP_MIR="_xu_main", XU_TENSOR_FUSION=enabled,
                                       XU_TASK_POLL="0"), source, exe)
            assert (marker in mir) == (mode == "fusion"), (kind, n, mode)
            checksum, *results = map(int, run([exe]).splitlines())
            totals.append(checksum)
            assert len(results) == samples
            results.sort()
            print(f"{kind:9} N={n:4} {mode:8} n={samples} P50={results[samples // 2 - 1]} ns "
                  f"P99={results[samples * 99 // 100 - 1]} ns")
        assert totals[0] == totals[1], (kind, n, totals)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--benchmark", action="store_true", help="also time pointwise and RMSNorm kernels")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        source_text, positive, negative = build_source()
        source = work / "tensor.xu"
        source.write_text(source_text)
        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_DUMP_MIR="_xu_main_kernel_", XU_KEEP_SYMBOLS="1")
        baseline = {}
        for mode, enabled, poll, flags in (
            ("baseline", "0", "0", ()),
            ("fusion", "1", "0", ()),
            ("no-opt", "1", "0", ("--no-opt",)),
            ("task-poll", "1", "1", ()),
        ):
            exe = work / (mode + (".exe" if os.name == "nt" else ""))
            mir = build(compiler, dict(env, XU_TENSOR_FUSION=enabled, XU_TASK_POLL=poll), source, exe, flags)
            for name in sorted(positive) + negative:
                body = mir.split(f"fn _xu_main_{name} ", 1)[1]
                body = re.split(r"\n(?:fn |Build complete:)", body, maxsplit=1)[0]
                fused = mode == "fusion" and name in positive
                markers, keep = positive[name] if fused else ((), True)
                expected_calls = set()
                if "tensor_i" in markers:
                    expected_calls.add("mul_add")
                if "tensor_reduce_i" in markers:
                    expected_calls.add("add_sqsum")
                if "tensor_normalize_i" in markers:
                    expected_calls.add("norm")
                emitted_calls = set(re.findall(r"call __xu_tensor_(mul_add|add_sqsum|norm)_f32\(", body))
                assert emitted_calls == expected_calls, (mode, name, emitted_calls)
                assert ("(tmp)" in body) == keep, (mode, name)
                if "tensor_reduce_i" in markers:
                    reuse = "tensor_normalize_i" in markers
                    call_match = re.search(r"call __xu_tensor_add_sqsum_f32\(([^,]+),", body)
                    assert call_match, name
                    dst_arg = call_match[1]
                    assert (dst_arg != "0") == (keep or reuse), name
                    if reuse:
                        outputs = set(re.findall(r"(t\d+) = addr l\d+\(out\)", body))
                        assert dst_arg in outputs, (name, dst_arg, outputs)
                if mode == "baseline":
                    baseline[name] = body
                elif mode == "fusion" and not fused:
                    assert body == baseline[name], name
            run([exe])
            for case in ("bounds", "rms-bounds"):
                panic = subprocess.run([exe, case], text=True, capture_output=True, timeout=30)
                assert panic.returncode and "index out of bounds" in panic.stderr, (mode, case, panic)
            if mode == "fusion":
                check_arm64_code(exe, positive)
            print(mode, "passed")
        if args.benchmark:
            benchmark(compiler, env, work)


if __name__ == "__main__":
    main()
