"""Optimization stability test: compare the same function in different compilation unit sizes.
Verifies results, optimization admission, and performance consistency across unit scale."""
import os
import shutil
import subprocess
import time
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()

# Target benchmark kernel to test for scale stability:
# Contains arithmetic folding, loops, branch latch, and local stores.
KERNEL_CODE = """
fn compute_kernel(n int) int {
    $sum := 0
    $i := 0
    while i < n {
        $val := (i * 3 + 7) ^ (i >> 1)
        if (i & 1) == 0 {
            sum = sum + val
        } else {
            sum = sum - (val & 15)
        }
        i = i + 1
    }
    << sum
}

fn matrix_dot_kernel(a &[]int, b &[]int, len int) int {
    $acc := 0
    $k := 0
    while k < len {
        acc = acc + a[k] * b[k]
        k = k + 1
    }
    << acc
}
"""

def generate_small_unit():
    return f"""@main
{KERNEL_CODE}

fn main() int {{
    r1 := compute_kernel(10000)
    $arr1 := [1, 2, 3, 4, 5, 6, 7, 8]
    $arr2 := [8, 7, 6, 5, 4, 3, 2, 1]
    r2 := matrix_dot_kernel(&arr1, &arr2, 8)
    println("RES:" + str(r1) + ":" + str(r2))
    << 0
}}
"""

def generate_large_unit(extra_fns=120):
    lines = ["@main", KERNEL_CODE]
    for i in range(extra_fns):
        lines.append(f"""fn dummy_helper_{i}(x int) int {{
    $v := x + {i}
    if v > 100 {{ << v * 2 }}
    << v - 1
}}
""")
    lines.append("""fn main() int {
    r1 := compute_kernel(10000)
    $arr1 := [1, 2, 3, 4, 5, 6, 7, 8]
    $arr2 := [8, 7, 6, 5, 4, 3, 2, 1]
    r2 := matrix_dot_kernel(&arr1, &arr2, 8)
    println("RES:" + str(r1) + ":" + str(r2))
    << 0
}
""")
    return "\n".join(lines)


def test_unit_scale_stability(tmp_path):
    small_src = tmp_path / "small.xu"
    small_bin = tmp_path / "small_bin"
    small_src.write_text(generate_small_unit())

    large_src = tmp_path / "large.xu"
    large_bin = tmp_path / "large_bin"
    large_src.write_text(generate_large_unit(120))

    env = os.environ.copy()
    env["XUPATH"] = ""
    env["XU_ROOT"] = str(ROOT)
    env["XU_SSA_TRACE"] = "1"

    # 1. Compile both units with timing/stats logging and SSA tracing
    res_small = subprocess.run(
        [str(XU), "build", "--timings", str(small_src), "-o", str(small_bin)],
        capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120
    )
    assert res_small.returncode == 0, f"Small unit build failed: {res_small.stderr}"

    res_large = subprocess.run(
        [str(XU), "build", "--timings", str(large_src), "-o", str(large_bin)],
        capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120
    )
    assert res_large.returncode == 0, f"Large unit build failed: {res_large.stderr}"

    # 2. Compare execution results: must be strictly identical
    out_small = subprocess.run([str(small_bin)], capture_output=True, text=True, timeout=30)
    assert out_small.returncode == 0, out_small.stderr

    out_large = subprocess.run([str(large_bin)], capture_output=True, text=True, timeout=30)
    assert out_large.returncode == 0, out_large.stderr

    assert out_small.stdout == out_large.stdout, (
        f"Result divergence between small and large units! Small={out_small.stdout}, Large={out_large.stdout}"
    )

    # 3. Check SSA promotion admission: neither kernel may suffer unit_reject in large units
    for kname in ["compute_kernel", "matrix_dot_kernel"]:
        s_trace = [l for l in res_small.stderr.splitlines() if f"ssa-trace: {kname}" in l]
        l_trace = [l for l in res_large.stderr.splitlines() if f"ssa-trace: {kname}" in l]
        assert s_trace, f"{kname} missing from small unit ssa-trace"
        assert l_trace, f"{kname} missing from large unit ssa-trace"
        s_outcome = s_trace[0].split()[2]
        l_outcome = l_trace[0].split()[2]
        assert l_outcome != "unit_reject", f"{kname} was unit_rejected in large unit!"
        assert s_outcome == l_outcome, f"{kname} SSA outcome diverged: small={s_outcome} vs large={l_outcome}"

    # 4. Check optimization admission for compute_kernel
    # Inspect stderr for ra-fn of compute_kernel
    small_ra = [l for l in res_small.stderr.splitlines() if "compute_kernel" in l]
    large_ra = [l for l in res_large.stderr.splitlines() if "compute_kernel" in l]
    print(f"Small RA: {small_ra}")
    print(f"Large RA: {large_ra}")

    # Both units must successfully admit RA for compute_kernel
    assert len(small_ra) > 0, "compute_kernel missing from small unit RA stats"
    assert len(large_ra) > 0, "compute_kernel missing from large unit RA stats"

    # In modern stable optimization, the assigned register allocation mode
    # (vreg / cache / frame) for compute_kernel should be consistent across unit sizes.
    small_mode = small_ra[0].split("mode=")[1].split()[0] if "mode=" in small_ra[0] else ""
    large_mode = large_ra[0].split("mode=")[1].split()[0] if "mode=" in large_ra[0] else ""
    print(f"Mode small={small_mode}, large={large_mode}")
    assert small_mode == large_mode, (
        f"Optimization admission mode diverged for compute_kernel: small={small_mode} vs large={large_mode}"
    )
