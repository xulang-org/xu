"""Read-only container loops must keep ordinary scalars in fixed homes."""
from pathlib import Path
import os, subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))
PROGRAM = """@main
fn accumulate(a &[]int, rounds int) int {
    mut result := 0
    for r in 0:rounds {
        for i in 0:a.len {
            word := a[i] * 17
            result += word + (a[i] * 17) + i
        }
    }
    << result
}
fn main() int {
    mut a := []int{}
    for i in 0:128 { a.push(i + 3) }
    println(accumulate(&a, 37))
    << 0
}
"""
GOLD = str(37 * sum(34 * (i + 3) + i for i in range(128))) + "\n"
@pytest.mark.parametrize("flags", [(), ("-O3",)])
@pytest.mark.parametrize("variant", ["base", "rename", "import"])
def test_readonly_index_scalar_homes(tmp_path, flags, variant):
    source = PROGRAM
    label = "_accumulate"
    if variant == "rename":
        source = source.replace("accumulate", "fold").replace("word", "scaled")
        label = "_fold"
    if variant == "import":
        source = source.replace("@main\n", "@main\n#math\n#strings\n", 1)
    path = tmp_path / "main.xu"; path.write_text(source)
    binary = tmp_path / "program"
    built = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), str(XU), "build", "--timings", *flags, str(path), "-o", str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, GOLD, "")
    row = next(dict(word.split("=", 1) for word in line.split()[1:]) for line in built.stderr.splitlines() if line.startswith("ra-fn:") and line.split()[1].endswith(label))
    assert row["mode"] == "vreg" and row["reason"] == "verified", row
    assert int(row["gpr"]) > 0, row


@pytest.mark.parametrize("flags", [("-O0",), (), ("-O3",)])
def test_actual_header_contract_and_plan(tmp_path, flags):
    import shutil
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy2(ROOT / "tests/mir_readonly_header_support.xu", tmp_path / "src/xu/types/readonly_header_test.xu")
    driver = tmp_path / "src/cmd/compile/driver_entry.xu"
    driver.write_text(driver.read_text().replace("fn main()", "fn readonly_unused_driver_main()", 1))
    prior = os.environ.get("XU_READONLY_STAGE_SOURCE")
    if prior:
        shutil.copy2(prior, tmp_path / "src/cmd/compile/emit_ra_intfield.xu")
    main = tmp_path / "src/cmd/compile/main.xu"
    main.write_text("""@main
#xu/types
fn main() int {
    for mode in 0:15 {
        m := types.readonly_header_test_mir(mode)
        admitted := fn_is_readonly_i64_index(&m, 0)
        want := mode == 0 || mode == 1 || mode == 13 || mode == 14
        assert(admitted == want)
        if want {
            for arch in 0:2 {
                plan := vreg_plan(&m, 0, arch)
                assert(plan.len > 0)
                assert(regplan_verify(&m, 0, arch, &plan))
                mut colored := false
                for t in 0:types.mir_ntemps(&m, 0) {
                    if plan[t] != 0 { colored = true }
                    if types.mir_temp_nslots(&m, 0, t) != 1 { assert(plan[t] == 0) }
                }
                assert(colored)
            }
        }
    }
    println("readonly header PASS: 15 cases, 2 targets")
    << 0
}
""")
    sources = [main] + sorted(p for p in main.parent.glob("*.xu") if p != main)
    binary = tmp_path / "contract"
    built = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), "--cwd", str(tmp_path), str(XU), "build", *flags, *map(str, sources), "-o", str(binary)], cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, "readonly header PASS: 15 cases, 2 targets\n", "")

@pytest.mark.parametrize("flags", [("-O0",), (), ("-O2",), ("-O3",), ("--no-regcache",), ("-O3", "--ra=0")])
def test_readonly_empty_and_record_values(tmp_path, flags):
    source = """@main
struct Bucket { values []int, factor int }
fn fold(a &[]int, factor int) int {
    mut acc := 0
    for i in 0:a.len {
        if (i & 1) == 0 { acc += a[i] * factor }
        else { acc -= a[i] + factor }
    }
    << acc + a.len
}
fn from_record(b &Bucket) int { << fold(&b.values, b.factor) }
fn main() int {
    mut values := []int{}
    println(fold(&values, 7))
    for i in 0:17 { values.push(i * 3 - 5) }
    println(fold(&values, 7))
    b := Bucket{values: values, factor: 11}
    println(from_record(&b))
    << 0
}
"""
    values = [i * 3 - 5 for i in range(17)]
    result = lambda f: 17 + sum(v * f if i % 2 == 0 else -(v + f) for i, v in enumerate(values))
    expected = "0\n" + str(result(7)) + "\n" + str(result(11)) + "\n"
    path = tmp_path / "main.xu"; path.write_text(source)
    binary = tmp_path / "program"
    built = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), str(XU), "build", *flags, str(path), "-o", str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, expected, "")

@pytest.mark.parametrize("target", ["linux-x64", "linux-arm64", "windows-x64", "windows-arm64"])
def test_readonly_cross_format(tmp_path, target):
    path = tmp_path / "main.xu"; path.write_text(PROGRAM)
    binary = tmp_path / ("program.exe" if target.startswith("windows") else "program")
    built = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), str(XU), "build", "-O3", "--target", target, str(path), "-o", str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    assert binary.read_bytes().startswith(b"MZ" if target.startswith("windows") else b"\x7fELF")


@pytest.mark.parametrize("flags", [(), ("-O2",), ("-O3",), ("--no-regcache",)])
@pytest.mark.parametrize("index", [-1, 0, 127, 128])
def test_checked_readonly_index_values_and_traps(tmp_path, flags, index):
    source = """@main
fn read(a &[]int, i int) int { << a[i] + a.len }
fn main() int {
    mut values := []int{}
    for i in 0:128 { values.push(i + 3) }
    println(read(&values, INDEX))
    << 0
}
""".replace("INDEX", str(index))
    path = tmp_path / "main.xu"; path.write_text(source)
    binary = tmp_path / "program"
    built = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), str(XU), "build", *flags, str(path), "-o", str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    if index < 0 or index >= 128:
        assert (run.returncode, run.stdout, run.stderr) == (1, "", "index out of bounds\n")
    else:
        assert (run.returncode, run.stdout, run.stderr) == (0, str(index + 3 + 128) + "\n", "")
