"""Exercise shared MIR contracts and ordinary CFG register allocation."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))
WRAPPER = ROOT / "scripts/run_product_compiler.sh"

ORDINARY = """@main
struct Box { value int }
fn choose(x int) int {
    if (x & 1) == 0 { << x * 3 + 7 }
    << x * 5 - 11
}
fn run_loop(box &mut Box, n int) int {
    mut acc := 0
    mut i := 0
    while i < n {
        acc += ((i * 17) ^ 23) + choose(i)
        box.value += (i & 3)
        i += 1
    }
    << acc + box.value
}
fn main() int {
    mut box := Box{value: 13}
    println(run_loop(mut &box, 100))
    << 0
}
"""
GOLD = str(13 + sum(((i * 17) ^ 23) + (i * 3 + 7 if i % 2 == 0 else i * 5 - 11) + (i & 3)
                    for i in range(100))) + "\n"


def compile_source(tmp_path, source, *flags, target=None):
    src = tmp_path / "main.xu"
    src.write_text(source)
    binary = tmp_path / "program"
    args = [str(WRAPPER), str(XU), "build", str(src), "-o", str(binary), *flags]
    if target:
        args.extend(["--target", target])
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    return binary, result.stderr


@pytest.mark.parametrize("flags", [(), ("-O2",), ("-O3",)])
@pytest.mark.parametrize("target", [None, "linux-x64"])
def test_ordinary_loop_calls_and_memory_use_fixed_homes(tmp_path, flags, target):
    binary, stderr = compile_source(tmp_path, ORDINARY, "--timings", *flags, target=target)
    rows = [dict(token.split("=", 1) for token in line.split()[1:])
            for line in stderr.splitlines() if line.startswith("ra-fn:")]
    assert rows, stderr
    loop = next(row for row in rows if row["label"].endswith("_run_loop"))
    assert loop["mode"] == "vreg", loop
    assert int(loop["gpr"]) > 0 and int(loop["frame"]) > 0, loop
    assert loop["reason"] == "verified", loop
    if target is None:
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
        assert (result.returncode, result.stdout, result.stderr) == (0, GOLD, "")


def test_diagnostics_do_not_change_program_bytes(tmp_path):
    binary, quiet = compile_source(tmp_path, ORDINARY)
    first = binary.read_bytes()
    binary, report = compile_source(tmp_path, ORDINARY, "--timings")
    assert binary.read_bytes() == first
    assert "ra-fn:" not in quiet and "ra-fn:" in report


@pytest.mark.parametrize("name", ["loop_sum", "nested_loop", "method_sum", "algorithm_search",
                                   "match_sum", "copy_bytes", "scan_dep"])
def test_generic_opportunity_preserves_existing_loop_transformations(tmp_path, name):
    # The separate paired performance gate measures the speed contract. Here
    # verify the backend choice and the complete independent golden output.
    import json
    expected = json.loads((ROOT / "tests/data/compiler_workloads/expected.json").read_text())[name]
    binary, stderr = compile_source(tmp_path, (ROOT / "tests/data/compiler_workloads" / (name + ".xu")).read_text(), "--timings")
    label = "_xu_sort_search_ints" if name == "algorithm_search" else "_xu_main"
    row = next(line for line in stderr.splitlines()
               if line.startswith(f"ra-fn: label={label} "))
    assert "reason=legacy-loop-priority" in row, row
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (result.returncode, result.stdout, result.stderr) == (0, expected, "")


def test_noopt_reports_disabled_and_runs_correctly(tmp_path):
    binary, stderr = compile_source(tmp_path, ORDINARY, "--no-opt", "--timings")
    rows = [line for line in stderr.splitlines() if line.startswith("ra-fn:")]
    assert rows and all("reason=disabled" in row and "mode=frame" in row for row in rows)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
    assert (result.returncode, result.stdout, result.stderr) == (0, GOLD, "")


@pytest.mark.parametrize("variant", ["rename", "split", "import"])
def test_register_coverage_survives_equivalent_source_changes(tmp_path, variant):
    source = ORDINARY
    suffix = "_run_loop"
    if variant == "rename":
        source = source.replace("run_loop", "worker").replace("choose", "bias")
        suffix = "_worker"
    elif variant == "split":
        source = source.replace("fn choose(x int)", "fn pick_branch(x int)")
        source += "\nfn choose(x int) int { << pick_branch(x) }\n"
    else:
        source = source.replace("@main\n", "@main\n#math\n", 1)
    binary, stderr = compile_source(tmp_path, source, "--timings")
    row = next(line for line in stderr.splitlines()
               if line.startswith("ra-fn:") and f"{suffix} " in line)
    assert "mode=vreg" in row and "reason=verified" in row, row
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
    assert (result.returncode, result.stdout, result.stderr) == (0, GOLD, "")


def test_shared_read_and_definition_contract(tmp_path):
    source = """@main
#xu/types
fn main() int {
    for kind in 0:49 {
        m := types.mir_operand_probe(kind)
        schema := types.mir_instr_use_schema(kind, types.mir_ic(&m, 0, 0))
        if schema < 0 { -> }
        counts := types.mir_operand_probe_counts(kind, 1)
        for t in 0:224 {
            mut found := false
            for pos in 0:260 {
                if types.mir_instr_read_m(&m, 0, 0, pos) == t { found = true }
            }
            assert(found == types.mir_instr_uses_temp_m(&m, 0, 0, t))
            assert(types.mir_instr_read_occurrences_m(&m, 0, 0, t) == counts[t])
        }
        dest := types.mir_instr_def_m(&m, 0, 0)
        if !types.mir_instr_has_dest(kind) { assert(dest == -1) }
    }
    println("contract PASS")
    << 0
}
"""
    binary, _ = compile_source(tmp_path, source)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    assert (result.returncode, result.stdout, result.stderr) == (0, "contract PASS\n", "")


@pytest.mark.parametrize("flags", [(), ("-O3",)])
def test_body_descriptor_is_not_read_by_a_header_guard(tmp_path, flags):
    # fill_bits copies the borrowed array descriptor inside the self-loop.
    # A hoisted guard used that uninitialized copy before its LoadPtr; the
    # ordinary register path made triple encryption deterministically trap.
    fixture = ROOT / "tests/fixtures/crypto_des"
    binary, _ = compile_source(tmp_path, (fixture / "main.xu").read_text(), *flags)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (result.returncode, result.stdout, result.stderr) == (
        0, (fixture / "expected.txt").read_text(), "")


@pytest.mark.parametrize("flags", [(), ("-O2",), ("-O3",)])
def test_multiblock_backedge_reloads_its_own_constant(tmp_path, flags):
    source = """@main
const u32_max = 4294967295
const poly = 79764919
fn crc_msb_set(c int) bool {
    << c > 2147483647
}

fn crc_update(crc0 int, buf &[]int) int {
    mut c := (crc0 & u32_max) ^ u32_max
    mut i := 0
    while i < buf.len {
        b := buf[i] & 255
        c = (c ^ (b << 24)) & u32_max
        mut k := 0
        while k < 8 {
            // The helper gives the compiler a branch to inline.
            if crc_msb_set(c) {
                c = ((c << 1) ^ poly) & u32_max
            } else {
                c = (c << 1) & u32_max
            }
            k = k + 1
        }
        i = i + 1
    }
    << (c ^ u32_max) & u32_max
}

fn main() int {
 values := [104, 101, 108, 108, 111, 32, 98, 122, 105, 112, 50]
 println(crc_update(0, &values))
 << 0
}
"""
    binary, _ = compile_source(tmp_path, source, *flags)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    # Independent MSB-first polynomial reference for these eleven bytes.
    crc = 0xFFFFFFFF
    for value in b"hello bzip2":
        crc ^= value << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04C11DB7 if crc & 0x80000000 else 0)) & 0xFFFFFFFF
    gold = str(crc ^ 0xFFFFFFFF) + "\n"
    assert (result.returncode, result.stdout, result.stderr) == (0, gold, "")
