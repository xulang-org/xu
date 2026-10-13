"""Call-point splitting through the real allocator, frame and native emitters."""
from pathlib import Path
import os, shutil, subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))
STAGE = Path(os.environ.get("XU_CALL_SPLIT_STAGE_ROOT", ROOT))

@pytest.mark.parametrize("flags", [("-O0",), (), ("-O3",)])
def test_integer_pressure_uses_call_point_splits(tmp_path, flags):
    shutil.copytree(STAGE / "src", tmp_path / "src")
    shutil.copy2(ROOT / "tests/mir_call_split_support.xu", tmp_path / "src/xu/types/call_split_test.xu")
    driver = tmp_path / "src/cmd/compile/driver_entry.xu"
    driver.write_text(driver.read_text().replace("fn main()", "fn unused_split_main()", 1))
    main = tmp_path / "src/cmd/compile/main.xu"
    main.write_text("""@main
#xu/types
fn main() int {
    assert(types.call_split_empty_admission())
    for mode in 0:14 {
        m := types.call_split_case_mir(mode)
        plan := vreg_plan(&m, 0, 0)
        nt := types.mir_ntemps(&m, 0)
        assert(plan.len >= nt)
        assert(regplan_verify(&m, 0, 0, &plan))
        if mode != 1 && mode != 3 && mode != 9 {
            for t in 0:7 { assert(plan[t] >= 2) }
            assert(plan.len > nt)
        } else { assert(plan.len == nt) }
        mut p := nt
        while p + 1 < plan.len {
            ii := plan[p]
            t := plan[p+1]
            assert(t != types.mir_ia(&m, 0, ii))
            if t < 7 { assert(ii == 7 || mode == 2 || mode == 4 || mode == 6) }
            p += 2
        }
        mut fr := Frame{local_slot: []int{}, temp_slot: []int{}, fp_split: []int{}, select_pairs: []int{}, sret_slot: -1, size: 0, plan_reason: 0, plan_instr: -1}
        fr.layout(&m, 0, 0, 0, true)
        frame_validate(&fr, &m, 0)
        for t in 0:7 {
            if vreg_plan_temp_has_fp_split(&plan, nt, t) { assert(fr.fp_split[t] >= 0) }
            else { assert(fr.fp_split[t] == -1) }
        }
        if mode == 0 {
            mut bad := []int{}
            for v in plan { bad.push(v) }
            bad.push(7)
            assert(!regplan_verify(&m, 0, 0, &bad))
            bad.push(7) // A call result must never be restored over itself.
            assert(!regplan_verify(&m, 0, 0, &bad))
            bad[bad.len-1] = 6
            bad[bad.len-2] = 0 // Non-call instruction.
            assert(!regplan_verify(&m, 0, 0, &bad))
        }
    }
    println("call-split PASS")
    << 0
}
""")
    binary = tmp_path / "contract"
    built = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), "--cwd", str(tmp_path), str(XU), "build", *flags, str(main.parent), "-o", str(binary)], cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, "call-split PASS\n", "")

PROGRAM = """@main
fn touch(a &mut []int, x int) int {
    mut out := x
    for j in 0:3 { out = (out * 3 + a[j]) & 1023 }
    a[7] = out
    << out
}
fn worker(a &mut []int, n int) int {
    p0 := (a[0] * 3) ^ 7
    p1 := (a[1] * 4) ^ 8
    p2 := (a[2] * 5) ^ 9
    p3 := (a[3] * 6) ^ 10
    p4 := (a[4] * 7) ^ 11
    p5 := (a[5] * 8) ^ 12
    p6 := (a[6] * 9) ^ 13
    v := touch(a, n)
    << p0 * 2 + p1 * 3 + p2 * 4 + p3 * 5 + p4 * 6 + p5 * 7 + p6 * 8 + p0 * 8 + p1 * 9 + p2 * 10 + p3 * 11 + p4 * 12 + p5 * 13 + p6 * 14 + p0 * 12 + p1 * 13 + p2 * 14 + p3 * 15 + p4 * 16 + p5 * 17 + p6 * 18 + p0 * 18 + p1 * 19 + p2 * 20 + p3 * 21 + p4 * 22 + p5 * 23 + p6 * 24 + v
}

fn main() int {
    mut a := [3,5,7,11,13,17,19,0]
    mut total := 0
    for i in 0:ROUNDS { total += worker(mut &a, i) }
    println(total)
    println(a[7])
    << 0
}
"""

def native_source(variant, rounds):
    text = PROGRAM.replace("ROUNDS", str(rounds))
    if variant == "rename": text = text.replace("worker", "accumulate").replace("touch", "adjust")
    if variant.startswith("import"): text = text.replace("@main\n", "@main\n#math\n#strings\n", 1)
    if variant == "split": text = text.replace("fn touch(", "fn inner_touch(") + "\nfn touch(a &mut []int, x int) int { << inner_touch(a, x) }\n"
    if variant == "print": text = text.replace("v := touch(a, n)", "v := touch(a, n)\n    println(n)")
    if variant.endswith("mutate"): text = text.replace("a[7] = out", "a[0] += 1\n    a[7] = out")
    if variant.endswith("grow"): text = text.replace("a[7] = out", "a.push(out)\n    a[7] = out").replace("mut a := [3,5,7,11,13,17,19,0]", "mut a := []int{}\n    for v in [3,5,7,11,13,17,19,0] { a.push(v) }")
    return text

def native_expected(variant, rounds):
    a = [3,5,7,11,13,17,19,0]
    total = 0
    for i in range(max(rounds, 0)):
        ps = [(a[j] * (j+3)) ^ (j+7) for j in range(7)]
        out = i
        for v in a[:3]: out = (out*3+v) & 1023
        if variant.endswith("mutate"): a[0] += 1
        if variant.endswith("grow"): a.append(out)
        a[7] = out
        total += sum(ps[j] * (z+j+1) for z in [1,7,11,17] for j in range(7)) + out
    prefix = "".join(f"{i}\n" for i in range(max(rounds, 0))) if variant == "print" else ""
    return prefix + f"{total}\n{a[7]}\n"

@pytest.mark.parametrize("flags", [("-O0",), (), ("-O2",), ("-O3",), ("--no-regcache",), ("-O3", "--ra=0")])
@pytest.mark.parametrize("variant", ["base", "rename", "import", "split", "mutate", "grow", "print", "import_mutate", "import_grow"])
def test_native_call_pressure_and_objects(tmp_path, flags, variant):
    # Runtime inputs include empty, one-trip and changing borrowed storage.
    for rounds in [-1, 0, 1, 2, 37]:
        path = tmp_path / "main.xu"; path.write_text(native_source(variant, rounds)); binary = tmp_path / "native"
        p = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), "--cwd", str(STAGE), str(XU), "build", "--timings", *flags, str(path), "-o", str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert p.returncode == 0, p.stderr
        report = p.stderr
        p = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
        assert (p.returncode, p.stdout, p.stderr) == (0, native_expected(variant, rounds), "")
        if flags == () and variant in ("base", "rename", "import", "mutate", "grow", "import_mutate", "import_grow"):
            row = next(dict(w.split("=",1) for w in line.split()[1:]) for line in report.splitlines() if line.startswith("ra-fn:") and ("_worker " in line or "_accumulate " in line))
            assert row["mode"] == "vreg" and int(row["split_gpr"]) > 0, row

@pytest.mark.parametrize("target", ["linux-x64", "linux-arm64", "windows-x64", "windows-arm64"])
def test_call_split_cross_format(tmp_path, target):
    path = tmp_path / "main.xu";path.write_text(native_source("base", 37));binary = tmp_path / ("program.exe" if target.startswith("windows") else "program")
    p = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), "--cwd", str(STAGE), str(XU), "build", "--target", target, str(path), "-o", str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, p.stderr
    assert binary.read_bytes().startswith(b"MZ" if target.startswith("windows") else b"\x7fELF")


def test_split_diagnostics_preserve_binary_bytes(tmp_path):
    path = tmp_path / "main.xu";path.write_text(native_source("base", 37));binary = tmp_path / "program"
    cmd = [str(ROOT / "scripts/run_product_compiler.sh"), "--cwd", str(STAGE), str(XU), "build", str(path), "-o", str(binary)]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert p.returncode == 0 and "ra-fn:" not in p.stderr
    quiet = binary.read_bytes()
    p = subprocess.run([*cmd, "--timings"], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert p.returncode == 0 and "split_gpr=" in p.stderr
    assert binary.read_bytes() == quiet
