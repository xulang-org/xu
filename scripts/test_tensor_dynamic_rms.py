#!/usr/bin/env python3
"""Check guarded runtime-length f32 residual addition and square-sum fusion."""

import argparse
import math
import os
import platform
from pathlib import Path
import re
import subprocess
import tempfile

from test_tensor_dynamic import mir_functions
from test_tensor_fusion import (
    PRELUDE,
    RMS_INPUT_PAIRS,
    build,
    check_arm64_code,
    f32,
    float_bits,
    run,
    xu_f32s,
)


CAPACITY = 17
# Run CAPACITY first to dirty all tmp slots before testing every mem_zero tail size.
LENGTHS = (CAPACITY, 16, 15, 14, 11, 5, 1, 0, -7, CAPACITY)
MARKER = "call __xu_tensor_add_sqsum_f32("
NORM_MARKER = "call __xu_tensor_norm_f32("
TAIL_MARKER = "(.tensor_tail_i)"
MEM_ZERO = "_xu_runtime_core_mem_zero"
SENTINEL = 0x41400000
PANIC_CASES = (
    "x",
    "skip",
    "capacity",
    "overflow",
    "live_x",
    "live_capacity",
    "reuse_x",
    "reuse_out",
    "reuse_weight",
    "reuse_capacity",
)
POSITIVE = (
    "kernel_live",
    "kernel_reduce",
    "kernel_owned",
    "kernel_reuse",
    "kernel_reuse_weighted",
    "kernel_reuse_keep_scale",
    "kernel_impure_scale",
)
REUSE_POSITIVE = ("kernel_reuse", "kernel_reuse_weighted", "kernel_reuse_keep_scale")
NEGATIVE = ("kernel_mismatch", "kernel_late_seed")


def reduction(capacity, *, late_seed=False, bound="n", bind_value=False):
    seed = "    $sum := f32(0)\n"
    body = "sum += tmp[j] * tmp[j]"
    if bind_value:
        body = "value := tmp[j]\n        sum += value * value"
    return f"""{"" if late_seed else seed}    $tmp := [{capacity}]f32{{}}
    for i in 0:n {{ tmp[i] = x[i] + skip[i] }}
{seed if late_seed else ""}    for j in 0:{bound} {{
        {body}
    }}
"""


def fixtures():
    pairs = [RMS_INPUT_PAIRS[i % len(RMS_INPUT_PAIRS)] for i in range(CAPACITY + 1)]
    x, skip = zip(*pairs)
    residual = [f32(a + b) for a, b in pairs]
    return x, skip, residual


def sum_of_squares(values, n):
    result = 0.0
    for value in values[:max(0, n)]:
        square = f32(value * value)
        result = f32(result + square)
    return result


def expected_for(values, n, weights=None):
    total = sum_of_squares(values, n)
    active = max(0, n)
    scaled = []
    if active:
        inverse = f32(1.0 / math.sqrt(total / active + 0.00001))
        if weights is None:
            scaled = [float_bits(f32(v * inverse)) for v in values[:active]]
        else:
            scaled = [float_bits(f32(f32(v * inverse) * w)) for v, w in zip(values[:active], weights[:active])]
    return float_bits(total), scaled + [SENTINEL] * (CAPACITY + 1 - active)


def test_source():
    x, skip, residual = fixtures()
    weights = [f32(((i % 5) + 1) * 0.25) for i in range(CAPACITY + 1)]
    call_checks = ""
    for case, n in enumerate(LENGTHS):
        total, result = expected_for(residual, n)
        expected = ", ".join(f"{bits:#x}" for bits in result)
        _, weighted_result = expected_for(residual, n, weights)
        weighted_expected = ", ".join(f"{bits:#x}" for bits in weighted_result)
        call_checks += f"""    expected_{case} := [{expected}]
    weighted_expected_{case} := [{weighted_expected}]
    if verify({n}, &x, &skip, &weight, {total:#x}, &expected_{case}, &weighted_expected_{case}) != 0 {{ << 1 }}
"""
    alias_residual = [f32(v + v) for v in x]
    alias_total, alias_result = expected_for(alias_residual, 5)
    alias_expected = ", ".join(f"{bits:#x}" for bits in alias_result)
    _, alias_weighted = expected_for(alias_residual, 5, weights)
    alias_weighted_expected = ", ".join(f"{bits:#x}" for bits in alias_weighted)
    owned_total, _ = expected_for(residual, 5)
    mismatch = float_bits(sum_of_squares(residual, 4))
    impure_weights = [f32(-0.75)] + list(weights[1:])
    impure_total, impure_result = expected_for(residual, 5, impure_weights)
    impure_expected = ", ".join(f"{bits:#x}" for bits in impure_result)
    keep_scale_inv = float_bits(f32(1.0 / math.sqrt(sum_of_squares(residual, 5) / 5.0 + 0.00001)))
    keep_scale_neg_inv = float_bits(f32(1.0 / math.sqrt(0.0 / -7.0 + 0.00001)))
    tagged_overlap = ""
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        tagged_overlap = """    if verify_reuse_overlap(0x0400000000000000) != 0 { << 10 }
"""
    return PRELUDE + f"""
fn bump_and_read_out(out &[]f32, weight $&[]f32, sum f32, n int) f32 {{
    if out.len > 0 && bits(out[0]) == 0 {{
        weight[0] = f32(7.0)
    }} else {{
        weight[0] = f32(-0.75)
    }}
    << f32(1.0 / math.sqrt(f64(sum) / f64(n) + 0.00001))
}}

fn kernel_live(n int, x &[]f32, skip &[]f32, out $&[]f32) int {{
{reduction(CAPACITY, bind_value=True)}    if n > 0 {{
        inv := f32(1.0 / math.sqrt(f64(sum) / f64(n) + 0.00001))
        for i in 0:n {{ out[i] = tmp[i] * inv }}
    }}
    $tail := n
    if tail < 0 {{ tail = 0 }}
    for i in tail:{CAPACITY} {{
        if bits(tmp[i]) != 0 {{ << -1 }}
    }}
    << bits(sum)
}}

fn kernel_reuse(n int, x &[]f32, skip &[]f32, out $&[]f32) int {{
{reduction(CAPACITY, bind_value=True)}    inv := f32(1.0 / math.sqrt(f64(sum) / f64(n) + 0.00001))
    for i in 0:n {{ out[i] = tmp[i] * inv }}
    << bits(sum)
}}

fn kernel_reuse_weighted(n int, x &[]f32, skip &[]f32, weight &[]f32, out $&[]f32) int {{
{reduction(CAPACITY)}    inv := f32(1.0 / math.sqrt(f64(sum) / f64(n) + 0.00001))
    for k in 0:n {{ out[k] = (tmp[k] * inv) * weight[k] }}
    << bits(sum)
}}

fn kernel_reuse_keep_scale(n int, x &[]f32, skip &[]f32, out $&[]f32) int {{
{reduction(CAPACITY)}    inv := f32(1.0 / math.sqrt(f64(sum) / f64(n) + 0.00001))
    for k in 0:n {{ out[k] = tmp[k] * inv }}
    << bits(inv)
}}

fn kernel_impure_scale(n int, x &[]f32, skip &[]f32, weight $&[]f32, out $&[]f32) int {{
{reduction(CAPACITY)}    inv := bump_and_read_out(out, weight, sum, n)
    for k in 0:n {{ out[k] = (tmp[k] * inv) * weight[k] }}
    << bits(sum)
}}

fn kernel_reduce(n int, x &[]f32, skip &[]f32) int {{
{reduction(CAPACITY)}    << bits(sum)
}}

fn kernel_owned(n int) int {{
    x := [{xu_f32s(x)}]
    skip := [{xu_f32s(skip)}]
{reduction(CAPACITY)}    << bits(sum)
}}

fn kernel_mismatch(n int, other int, x &[]f32, skip &[]f32) int {{
{reduction(CAPACITY, bound="other")}    << bits(sum)
}}

fn kernel_late_seed(n int, x &[]f32, skip &[]f32) int {{
{reduction(CAPACITY, late_seed=True)}    << bits(sum)
}}

fn check_out(n int, out &[]f32, expected &[]int) int {{
    for i in 0:out.len {{
        if bits(out[i]) != expected[i] {{
            println(n)
            println(i)
            println(bits(out[i]))
            << 2
        }}
    }}
    << 0
}}

fn verify(n int, x &[]f32, skip &[]f32, weight &[]f32, total int, expected &[]int, weighted_expected &[]int) int {{
    $out := []f32{{}}
    $out_reuse := []f32{{}}
    $out_weighted := []f32{{}}
    for _ in 0:{CAPACITY + 1} {{
        out.push(from_bits({SENTINEL:#x}))
        out_reuse.push(from_bits({SENTINEL:#x}))
        out_weighted.push(from_bits({SENTINEL:#x}))
    }}
    actual := kernel_live(n, x, skip, $&out)
    reused := kernel_reuse(n, x, skip, $&out_reuse)
    weighted := kernel_reuse_weighted(n, x, skip, weight, $&out_weighted)
    dead := kernel_reduce(n, x, skip)
    if actual != total || reused != total || weighted != total || dead != total {{
        println(n)
        println(actual)
        println(reused)
        println(weighted)
        println(dead)
        << 1
    }}
    if check_out(n, &out, expected) != 0 {{ << 2 }}
    if check_out(n, &out_reuse, expected) != 0 {{ << 2 }}
    if check_out(n, &out_weighted, weighted_expected) != 0 {{ << 2 }}
    << 0
}}

fn verify_reuse_overlap(tag int) int {{
    $x := [f32(1), f32(2), f32(3), f32(4), f32(5)]
    skip := [f32(10), f32(20), f32(30), f32(40), f32(50)]
    $w := [f32(0.5), f32(1.5), f32(2.5), f32(3.5), f32(4.5)]
    $out := [f32(0), f32(0), f32(0), f32(0)]
    unsafe {{
        desc_x := (&x) as *raw int
        desc_out := ($&out) as *raw int
        saved := *desc_out
        *desc_out = (*desc_x + 4) | tag
        _ := kernel_reuse(4, &x, &skip, $&out)
        *desc_out = saved
    }}
    $ref_x := [f32(1), f32(2), f32(3), f32(4), f32(5)]
    $ref_x_out := [f32(0), f32(0), f32(0), f32(0)]
    _ := kernel_reuse(4, &ref_x, &skip, $&ref_x_out)
    if f64(x[0]) != 1.0 || bits(x[1]) != bits(ref_x_out[0]) || bits(x[2]) != bits(ref_x_out[1]) {{ << 1 }}
    $x2 := [f32(1), f32(2), f32(3), f32(4)]
    $skip2 := [f32(10), f32(20), f32(30), f32(40)]
    $out2 := [f32(0), f32(0), f32(0), f32(0)]
    unsafe {{
        desc_w := ($&w) as *raw int
        desc_out2 := ($&out2) as *raw int
        saved := *desc_out2
        *desc_out2 = (*desc_w) | tag
        _ := kernel_reuse_weighted(4, &x2, &skip2, &w, $&out2)
        *desc_out2 = saved
    }}
    $ref_out := [f32(0), f32(0), f32(0), f32(0)]
    ref_w := [f32(0.5), f32(1.5), f32(2.5), f32(3.5), f32(4.5)]
    _ := kernel_reuse_weighted(4, &x2, &skip2, &ref_w, $&ref_out)
    for i in 0:4 {{
        if bits(w[i]) != bits(ref_out[i]) {{ << 2 }}
    }}
    << 0
}}

fn trigger_panic(which string) {{
    $n := 3
    if which == "capacity" || which == "live_capacity" || which == "reuse_capacity" {{ n = {CAPACITY + 1} }}
    $x := []f32{{}}
    $skip := []f32{{}}
    $weight := []f32{{}}
    $out := []f32{{}}
    for i in 0:n {{
        if (which != "x" && which != "live_x" && which != "reuse_x") || i < n - 1 {{ x.push(f32(2)) }}
        if which != "skip" || i < n - 1 {{ skip.push(f32(3)) }}
        if which != "reuse_weight" || i < n - 1 {{ weight.push(f32(1.5)) }}
        if which != "reuse_out" || i < n - 1 {{ out.push(f32(0)) }}
    }}
    if which == "overflow" {{ n = 0x4000000000000000 }}
    if which == "live_x" || which == "live_capacity" {{
        $live_out := []f32{{}}
        for _ in 0:{CAPACITY + 1} {{ live_out.push(f32(0)) }}
        println(kernel_live(n, &x, &skip, $&live_out))
        <<
    }}
    if which == "reuse_x" || which == "reuse_out" || which == "reuse_capacity" {{
        println(kernel_reuse(n, &x, &skip, $&out))
        <<
    }}
    if which == "reuse_weight" {{
        println(kernel_reuse_weighted(n, &x, &skip, &weight, $&out))
        <<
    }}
    println(kernel_reduce(n, &x, &skip))
}}

fn main() int {{
    args := os.argv()
    if args.len > 1 {{
        trigger_panic(args[1])
        << 3
    }}
    x := [{xu_f32s(x)}]
    skip := [{xu_f32s(skip)}]
    weight := [{xu_f32s(weights)}]
{call_checks}    alias_expected := [{alias_expected}]
    alias_weighted := [{alias_weighted_expected}]
    if verify(5, &x, &x, &weight, {alias_total:#x}, &alias_expected, &alias_weighted) != 0 {{ << 4 }}
    empty := []f32{{}}
    empty_expected := [{", ".join([hex(SENTINEL)] * (CAPACITY + 1))}]
    if verify(0, &empty, &empty, &empty, 0, &empty_expected, &empty_expected) != 0 {{ << 5 }}
    if verify(-7, &empty, &empty, &empty, 0, &empty_expected, &empty_expected) != 0 {{ << 5 }}
    if kernel_owned(5) != {owned_total:#x} {{ << 6 }}
    if kernel_mismatch(5, 4, &x, &skip) != {mismatch:#x} {{ << 7 }}
    if kernel_late_seed(5, &x, &skip) != {owned_total:#x} {{ << 8 }}
    $mut_weight := [{xu_f32s(weights)}]
    $impure_out := []f32{{}}
    for _ in 0:{CAPACITY + 1} {{ impure_out.push(from_bits({SENTINEL:#x})) }}
    if kernel_impure_scale(5, &x, &skip, $&mut_weight, $&impure_out) != {impure_total:#x} {{ << 9 }}
    impure_expected := [{impure_expected}]
    if check_out(5, &impure_out, &impure_expected) != 0 {{ << 9 }}
    $keep_out := []f32{{}}
    for _ in 0:{CAPACITY + 1} {{ keep_out.push(from_bits({SENTINEL:#x})) }}
    if kernel_reuse_keep_scale(5, &x, &skip, $&keep_out) != {keep_scale_inv:#x} {{ << 11 }}
    if kernel_reuse_keep_scale(-7, &empty, &empty, $&keep_out) != {keep_scale_neg_inv:#x} {{ << 11 }}
    if verify_reuse_overlap(0) != 0 {{ << 10 }}
{tagged_overlap}    << 0
}}
"""


def check_reduction_loop(function, name, keep_residual):
    match = re.search(r"call __xu_tensor_add_sqsum_f32\(([^,]+),", function)
    assert match, name
    assert (match[1] != "0") == keep_residual, name


def check_norm_loop(function, name, weighted):
    match = re.search(r"call __xu_tensor_norm_f32\(([^,]+), ([^,]+), ([^,]+),", function)
    assert match, name
    assert match[1] == match[2], name
    assert (match[3] != "0") == weighted, name


def verify(compiler, env, work):
    source = work / "tensor_dynamic_rms.xu"
    source.write_text(test_source())
    baseline = {}
    for mode, enabled, poll, flags in (
        ("baseline", "0", "0", ()),
        ("fusion", "1", "0", ()),
        ("no-opt", "1", "0", ("--no-opt",)),
        ("task-poll", "1", "1", ()),
    ):
        exe = work / (mode + (".exe" if os.name == "nt" else ""))
        mir = build(compiler, dict(env, XU_TENSOR_FUSION=enabled, XU_TASK_POLL=poll), source, exe, flags)
        functions = mir_functions(mir)
        for name in POSITIVE:
            assert (MARKER in functions[name]) == (mode == "fusion"), (mode, name)
            assert (NORM_MARKER in functions[name]) == (mode == "fusion" and name in REUSE_POSITIVE), (mode, name)
        for name in NEGATIVE:
            assert MARKER not in functions[name], (mode, name)
            if mode == "baseline":
                baseline[name] = functions[name]
            elif mode == "fusion":
                assert functions[name] == baseline[name], name
        if mode == "fusion":
            for name in POSITIVE:
                assert "(tmp)" in functions[name], name
                check_reduction_loop(functions[name], name, name in ("kernel_live", "kernel_impure_scale") or name in REUSE_POSITIVE)
            for name in REUSE_POSITIVE:
                check_norm_loop(functions[name], name, name == "kernel_reuse_weighted")
                assert MEM_ZERO not in functions[name], name
            assert MEM_ZERO in functions["kernel_live"], "kernel_live"
            assert MEM_ZERO in functions["kernel_impure_scale"], "kernel_impure_scale"
            assert TAIL_MARKER not in functions["kernel_live"], "kernel_live"
            assert MEM_ZERO not in functions["kernel_reduce"], "kernel_reduce"
            assert MEM_ZERO not in functions["kernel_owned"], "kernel_owned"
            check_arm64_code(exe, POSITIVE)
        assert run([exe]) == "", mode
        for case in PANIC_CASES:
            result = subprocess.run([exe, case], text=True, capture_output=True, timeout=30)
            assert result.returncode not in (0, 3) and "index out of bounds" in result.stderr, (mode, case, result)
            outcome = result.returncode, result.stdout, result.stderr
            if mode == "baseline":
                baseline[case] = outcome
            else:
                assert outcome == baseline[case], (mode, case, result)
        print(mode, "passed")


def benchmark_source(capacity):
    return PRELUDE.replace("#os", "#os\n#time", 1) + f"""
fn kernel_live(n int, x &[]f32, skip &[]f32, out $&[]f32) {{
{reduction(capacity, bind_value=True)}    inv := f32(1.0 / math.sqrt(f64(sum) / f64(n) + 0.00001))
    for i in 0:n {{ out[i] = tmp[i] * inv }}
}}

fn kernel_reduce(n int, x &[]f32, skip &[]f32) int {{
{reduction(capacity)}    << bits(sum)
}}

fn main() int {{
    args := os.argv()
    $n := {capacity}
    if args.len > 1 && args[1] == "short" {{ n = 128 }}
    use_reduce := args.len > 2 && args[2] == "reduce"
    $x := []f32{{}}
    $skip := []f32{{}}
    $out := []f32{{}}
    for i in 0:n {{
        x.push(f32(i % 11))
        skip.push(f32(i % 7))
        out.push(f32(0))
    }}
    $elapsed := [1000]int{{}}
    $checksum := 0
    if use_reduce {{
        for sample in 0:1200 {{
            start := time.now()
            value := kernel_reduce(n, &x, &skip)
            duration := time.since(start)
            if sample >= 200 {{ elapsed[sample - 200] = duration }}
            checksum += value
        }}
    }} else {{
        for sample in 0:1200 {{
            start := time.now()
            kernel_live(n, &x, &skip, $&out)
            duration := time.since(start)
            if sample >= 200 {{ elapsed[sample - 200] = duration }}
            checksum += bits(out[sample % n])
        }}
    }}
    println(checksum)
    for i in 0:1000 {{ println(elapsed[i]) }}
    << 0
}}
"""


def benchmark(compiler, env, work):
    source = work / "benchmark_dynamic_rms.xu"
    source.write_text(benchmark_source(4096))
    totals = {}
    cases = (
        ("live", 128, ["short"]),
        ("live", 4096, ["full"]),
        ("reduce", 128, ["short", "reduce"]),
        ("reduce", 4096, ["full", "reduce"]),
    )
    for mode, enabled in (("baseline", "0"), ("fusion", "1")):
        exe = work / ("bench-" + mode + (".exe" if os.name == "nt" else ""))
        mir = build(compiler, dict(env, XU_TENSOR_FUSION=enabled, XU_TASK_POLL="0"), source, exe)
        functions = mir_functions(mir)
        for name in ("kernel_live", "kernel_reduce"):
            assert (MARKER in functions[name]) == (mode == "fusion"), (mode, name)
        if mode == "fusion":
            assert NORM_MARKER in functions["kernel_live"]
            assert MEM_ZERO not in functions["kernel_live"]
            assert MEM_ZERO not in functions["kernel_reduce"]
        for kind, n, arguments in cases:
            checksum, *samples = map(int, run([exe, *arguments]).splitlines())
            assert len(samples) == 1000
            key = (kind, n)
            if mode == "baseline":
                totals[key] = checksum
            else:
                assert checksum == totals[key], key
            samples.sort()
            print(f"{kind:6} N={n:4} {mode:8} n={len(samples)} P50={samples[499]} ns P99={samples[989]} ns")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as path:
        work = Path(path)
        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_DUMP_MIR="_xu_main_kernel_", XU_KEEP_SYMBOLS="1")
        verify(compiler, env, work)
        if args.benchmark:
            benchmark(compiler, env, work)


if __name__ == "__main__":
    main()
