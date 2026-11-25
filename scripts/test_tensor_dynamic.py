#!/usr/bin/env python3
"""Check runtime-length f32 Mul -> Add fusion and its guarded fallback."""

import argparse
import os
import platform
from pathlib import Path
import re
import subprocess
import tempfile

from test_tensor_fusion import EXPECTED, INPUT_BITS, PRELUDE, build, check_arm64_code, run


CAPACITY = 17
LENGTH = CAPACITY + 2
SENTINEL = 0x41400000
MARKER = "call __xu_tensor_mul_add_f32("
PANIC_CASES = ("x", "scale", "bias", "out", "capacity", "overflow")


def kernel(name, capacity, second_bound="n", tail=""):
    return f"""
fn {name}(n int, x &[]f32, scale &[]f32, bias &[]f32, out $&[]f32) {{
    $tmp := [{capacity}]f32{{}}
    for i in 0:n {{ tmp[i] = x[i] * scale[i] }}
    for j in 0:{second_bound} {{ out[j] = tmp[j] + bias[j] }}
{tail}}}
"""


def f32_literals(values, count):
    return ", ".join(f"from_bits({values[i % len(values)]:#x})" for i in range(count))


def test_source():
    inputs = "\n".join(
        f"    {name} := [{f32_literals(values, LENGTH)}]"
        for name, values in INPUT_BITS.items()
    )
    output = f32_literals([SENTINEL], LENGTH)
    expected = ", ".join(f"{b:#x}" for b in EXPECTED)
    tagged_overlap = ""
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        tagged_overlap = "    << verify_overlap(0x0400000000000000)"
    return (
        PRELUDE
        + kernel("kernel_dynamic", CAPACITY)
        + kernel("kernel_different_bound", CAPACITY, second_bound="(n - 1)")
        + kernel("kernel_observed", CAPACITY, tail="    println(bits(tmp[1]))\n")
        + f"""
fn kernel_owned(n int) int {{
{inputs}
    $out := [{output}]
    $tmp := [{CAPACITY}]f32{{}}
    for i in 0:n {{ tmp[i] = x[i] * scale[i] }}
    for j in 0:n {{ out[j] = tmp[j] + bias[j] }}
    << verify_bits(&out, n)
}}

fn verify_output(n int, mode int) int {{
{inputs}
    $out := [{output}]
    $written := n
    if mode == 1 {{
        kernel_different_bound(n, &x, &scale, &bias, $&out)
        written = n - 1
    }} else if mode == 2 {{
        kernel_observed(n, &x, &scale, &bias, $&out)
    }} else {{
        kernel_dynamic(n, &x, &scale, &bias, $&out)
    }}
    << verify_bits(&out, written)
}}

fn verify_bits(out &[]f32, written int) int {{
    expected := [{expected}]
    for i in 0:out.len {{
        $want := {SENTINEL:#x}
        if i < written {{ want = expected[i % {len(EXPECTED)}] }}
        if bits(out[i]) != want {{
            println(i)
            println(bits(out[i]))
            << 1
        }}
    }}
    << 0
}}

fn verify_empty() {{
    x := []f32{{}}
    scale := []f32{{}}
    bias := []f32{{}}
    $out := []f32{{}}
    kernel_dynamic(0, &x, &scale, &bias, $&out)
    kernel_dynamic(-1, &x, &scale, &bias, $&out)
}}

fn verify_overlap(tag int) int {{
    $x := [f32(1), f32(2), f32(3), f32(4)]
    scale := [f32(2), f32(2), f32(2)]
    bias := [f32(0), f32(0), f32(0)]
    $out := [f32(0), f32(0), f32(0)]
    unsafe {{
        // Temporarily point out's three-element slice header at x[1:].
        // Restore its original backing storage before either slice drops.
        desc_x := (&x) as *raw int
        desc_out := ($&out) as *raw int
        saved := *desc_out
        *desc_out = (*desc_x + 4) | tag
        kernel_dynamic(3, &x, &scale, &bias, $&out)
        *desc_out = saved
    }}
    // An unchecked fused loop feeds its prior store back into the next
    // multiply and produces 2, 4, 8 here, instead of 2, 4, 6.
    if f64(x[0]) != 1.0 || f64(x[1]) != 2.0 || f64(x[2]) != 4.0 || f64(x[3]) != 6.0 {{
        << 2
    }}
    << 0
}}

fn trigger_panic(which string) {{
    $n := 3
    if which == "capacity" {{ n = {CAPACITY + 1} }}
    $x := []f32{{}}
    $scale := []f32{{}}
    $bias := []f32{{}}
    $out := []f32{{}}
    for i in 0:n {{
        if which != "x" || i < n - 1 {{ x.push(f32(2)) }}
        if which != "scale" || i < n - 1 {{ scale.push(f32(3)) }}
        if which != "bias" || i < n - 1 {{ bias.push(f32(4)) }}
        if which != "out" || i < n - 1 {{ out.push(f32(5)) }}
    }}
    if which == "overflow" {{ n = 0x4000000000000000 }}
    kernel_dynamic(n, &x, &scale, &bias, $&out)
}}

fn main() int {{
    args := os.argv()
    if args.len > 1 {{
        trigger_panic(args[1])
        << 3
    }}
    verify_empty()
    for n in [-7, 0, 1, 5, 11, {CAPACITY}] {{
        result := verify_output(n, 0)
        if result != 0 {{ << result }}
    }}
    owned := kernel_owned(5)
    if owned != 0 {{ << owned }}
    shifted := verify_output(5, 1)
    if shifted != 0 {{ << shifted }}
    observed := verify_output(5, 2)
    if observed != 0 {{ << observed }}
    overlap := verify_overlap(0)
    if overlap != 0 {{ << overlap }}
{tagged_overlap if tagged_overlap else "    << 0"}
}}
"""
    )


def mir_functions(mir):
    functions = re.split(r"(?m)^fn _xu_main_(\w+) ", mir)
    return {
        name: body.split("\nBuild complete:", 1)[0]
        for name, body in zip(functions[1::2], functions[2::2])
    }


def verify(compiler, env, work):
    source = work / "tensor_dynamic.xu"
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
        for name in ("kernel_dynamic", "kernel_owned"):
            assert (MARKER in functions[name]) == (mode == "fusion"), (mode, name)
        for name in ("kernel_different_bound", "kernel_observed"):
            assert MARKER not in functions[name], (mode, name)
            if mode == "baseline":
                baseline[name] = functions[name]
            elif mode == "fusion":
                assert functions[name] == baseline[name], name
        if mode == "fusion":
            # Guard failures still have the original local and checked loops.
            body = functions["kernel_dynamic"]
            assert "(tmp)" in body and re.search(r"_xu_runtime_core_(?:index|rt)_panic", body)
            check_arm64_code(exe, ("kernel_dynamic", "kernel_owned"))
        assert run([exe]).strip() == str(0x80000000), mode
        for case in PANIC_CASES:
            panic = subprocess.run([exe, case], text=True, capture_output=True, timeout=30)
            assert panic.returncode not in (0, 3) and "index out of bounds" in panic.stderr, (mode, case, panic)
            if mode == "baseline":
                baseline[case] = (panic.returncode, panic.stderr)
            else:
                assert (panic.returncode, panic.stderr) == baseline[case], (mode, case, panic)
        print(mode, "passed")


def benchmark_source(capacity):
    return (
        PRELUDE.replace("#os", "#os\n#time", 1)
        + kernel("kernel_dynamic", capacity)
        + f"""
fn main() int {{
    args := os.argv()
    $n := {capacity}
    if args.len > 1 {{ n = 128 }}
    $x := []f32{{}}
    $scale := []f32{{}}
    $bias := []f32{{}}
    $out := []f32{{}}
    for i in 0:n {{
        x.push(f32(i % 11))
        scale.push(f32(i % 7))
        bias.push(f32(i % 3))
        out.push(f32(0))
    }}
    $elapsed := [1000]int{{}}
    $checksum := 0
    for sample in 0:1200 {{
        start := time.now()
        kernel_dynamic(n, &x, &scale, &bias, $&out)
        duration := time.since(start)
        if sample >= 200 {{ elapsed[sample - 200] = duration }}
        checksum += bits(out[sample % n])
    }}
    println(checksum)
    for i in 0:1000 {{ println(elapsed[i]) }}
    << 0
}}
"""
    )


def benchmark(compiler, env, work):
    source = work / "benchmark_dynamic.xu"
    source.write_text(benchmark_source(4096))
    expected = {}
    for mode, enabled in (("baseline", "0"), ("fusion", "1")):
        exe = work / ("bench-" + mode + (".exe" if os.name == "nt" else ""))
        mir = build(compiler, dict(env, XU_TENSOR_FUSION=enabled, XU_TASK_POLL="0"), source, exe)
        assert (MARKER in mir) == (mode == "fusion"), mode
        for n, args in ((128, ["short"]), (4096, [])):
            checksum, *samples = map(int, run([exe, *args]).splitlines())
            assert len(samples) == 1000
            if mode == "baseline":
                expected[n] = checksum
            else:
                assert checksum == expected[n], n
            samples.sort()
            print(f"N={n:4} {mode:8} n={len(samples)} P50={samples[499]} ns P99={samples[989]} ns")


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
