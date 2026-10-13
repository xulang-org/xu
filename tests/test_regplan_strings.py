"""Borrowed byte loops color scalars without moving string descriptors."""
from pathlib import Path
import os
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu"))
PROGRAM = """@main
fn fold(s &string, start int, rounds int) int {
    mut acc := 0
    for r in 0:rounds {
        for i in start:s.len {
            b := s[i]
            if (b & 1) == 0 { acc += b * 17 + i }
            else { acc -= b * 3 + r }
        }
    }
    << acc + s.len
}
fn main() int {
    a := ""
    b := "0123456789ABCDEFGHIJKLMNOPQ"
    println(fold(&a, 0, 7))
    println(fold(&b, 0, 37))
    println(fold(&b, 3, 11))
    << 0
}
"""
DATA = b"0123456789ABCDEFGHIJKLMNOPQ"


def build(tmp_path, source, flags=(), target=None):
    path = tmp_path / "main.xu"
    path.write_text(source)
    binary = tmp_path / ("program.exe" if target and target.startswith("windows") else "program")
    command = [str(ROOT / "scripts/run_product_compiler.sh"), str(XU),
               "build", "--timings", *flags]
    if target:
        command += ["--target", target]
    p = subprocess.run(command + [str(path), "-o", str(binary)],
                       cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, p.stderr
    return binary, p.stderr


@pytest.mark.parametrize("flags", [(), ("-O3",)])
@pytest.mark.parametrize("variant", ["base", "rename", "import"])
def test_borrowed_string_scalar_homes(tmp_path, flags, variant):
    source = PROGRAM
    label = "_fold"
    if variant == "rename":
        source = source.replace("fold", "checksum").replace("acc", "total")
        label = "_checksum"
    if variant == "import":
        source = source.replace("@main\n", "@main\n#math\n#strings\n", 1)
    binary, diagnostic = build(tmp_path, source, flags)
    def expected(start, rounds):
        return len(DATA) + sum(b * 17 + i if b % 2 == 0 else -(b * 3 + r)
                               for r in range(rounds)
                               for i, b in enumerate(DATA) if i >= start)
    gold = f"0\n{expected(0, 37)}\n{expected(3, 11)}\n"
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, gold, "")
    row = next(dict(word.split("=", 1) for word in line.split()[1:])
               for line in diagnostic.splitlines()
               if line.startswith("ra-fn:") and line.split()[1].endswith(label))
    assert row["mode"] == "vreg" and row["reason"] == "verified", row
    assert int(row["gpr"]) > 0, row


@pytest.mark.parametrize("flags", [("-O0",), (), ("-O3",), ("--no-regcache",)])
@pytest.mark.parametrize("index", [-1, 0, 25, 26])
def test_string_index_bounds(tmp_path, flags, index):
    source = """@main
fn read(s &string, i int) int { << s[i] + s.len }
fn main() int {
    s := "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    println(read(&s, INDEX))
    << 0
}
""".replace("INDEX", str(index))
    binary, _ = build(tmp_path, source, flags)
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    if index < 0 or index >= 26:
        assert (run.returncode, run.stdout, run.stderr) == (1, "", "index out of bounds\n")
    else:
        assert (run.returncode, run.stdout, run.stderr) == (0, str(65 + index + 26) + "\n", "")


@pytest.mark.parametrize("target", ["linux-x64", "linux-arm64", "windows-x64", "windows-arm64"])
def test_string_cross_format(tmp_path, target):
    binary, _ = build(tmp_path, PROGRAM, ("-O3",), target)
    assert binary.read_bytes().startswith(b"MZ" if target.startswith("windows") else b"\x7fELF")


@pytest.mark.parametrize("flags", [(), ("-O3",)])
@pytest.mark.parametrize("variant", ["base", "rename", "import"])
def test_string_and_borrowed_lookup_table(tmp_path, flags, variant):
    source = """@main
fn lookup(s &string, table &[256]int, rounds int) int {
    mut acc := 0
    for r in 0:rounds {
        for i in 0:s.len { acc += table[s[i] & 255] + i + r }
    }
    << acc
}
fn main() int {
    s := "0123456789ABCDEFGHIJKLMNOPQ"
    mut table := [256]int{}
    for i in 0:256 { table[i] = i * 17 - 300 }
    println(lookup(&s, &table, 37))
    << 0
}
"""
    label = "_lookup"
    if variant == "rename":
        source = source.replace("lookup", "map_bytes").replace("acc", "total")
        label = "_map_bytes"
    if variant == "import":
        source = source.replace("@main\n", "@main\n#math\n#strings\n", 1)
    binary, diagnostic = build(tmp_path, source, flags)
    gold = str(sum(b * 17 - 300 + i + r for r in range(37)
                   for i, b in enumerate(DATA))) + "\n"
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, gold, "")
    row = next(dict(word.split("=", 1) for word in line.split()[1:])
               for line in diagnostic.splitlines()
               if line.startswith("ra-fn:") and line.split()[1].endswith(label))
    assert row["mode"] == "vreg" and row["reason"] == "verified", row
    assert int(row["gpr"]) > 0, row


@pytest.mark.parametrize("flags", [("-O0",), (), ("-O3",)])
def test_actual_string_contract_and_plan(tmp_path, flags):
    import shutil
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy2(ROOT / "tests/mir_readonly_string_support.xu",
                 tmp_path / "src/xu/types/readonly_string_test.xu")
    driver = tmp_path / "src/cmd/compile/driver_entry.xu"
    driver.write_text(driver.read_text().replace("fn main()", "fn string_unused_driver_main()", 1))
    main = tmp_path / "src/cmd/compile/main.xu"
    main.write_text("""@main
#xu/types
fn main() int {
    for mode in 0:34 {
        m := types.readonly_string_test_mir(mode)
        want := mode <= 2 || mode == 7 || mode == 20 || mode == 21 || mode == 28
        admitted := fn_is_readonly_i64_index(&m, 0)
        if admitted != want { println("admission mode: " + str(mode)) }
        assert(admitted == want)
        if want {
            for arch in 0:2 {
                plan := vreg_plan(&m, 0, arch)
                if plan.len == 0 { println("empty plan: " + str(mode) + ":" + str(arch)) }
                assert(plan.len > 0)
                assert(regplan_verify(&m, 0, arch, &plan))
                mut colored := false
                for t in 0:types.mir_ntemps(&m, 0) {
                    if plan[t] != 0 { colored = true }
                    if !vreg_temp_eligible(&m, 0, t) { assert(plan[t] == 0) }
                }
                if !colored { println("uncolored plan: " + str(mode) + ":" + str(arch)) }
                assert(colored)
            }
        }
    }
    println("readonly string PASS: 34 cases, 2 targets")
    << 0
}
""")
    sources = [main] + sorted(p for p in main.parent.glob("*.xu") if p != main)
    binary = tmp_path / "contract"
    p = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), "--cwd", str(tmp_path),
                        str(XU), "build", *flags, *map(str, sources), "-o", str(binary)],
                       cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, p.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, "readonly string PASS: 34 cases, 2 targets\n", "")
