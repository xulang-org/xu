"""Frame-backed borrowed arguments must not disable independent scalar homes."""
from pathlib import Path
import os, subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get('XU', ROOT / 'bin/xu'))
PROGRAM = """@main
fn pick(a &[]int, index int, n int) int {
    mut sum := 0
    for j in 0:n { sum += a[(index + j) & 127] * 17 }
    << sum
}
fn worker(a &[]int, rounds int) int {
    mut sum := 0
    for r in 0:rounds {
        for i in 0:a.len {
            x := i * 31 + r
            sum += pick(a, i, 3) + x + i
        }
    }
    << sum
}
fn main() int {
    mut a := []int{}
    for i in 0:128 { a.push(i + 3) }
    println(worker(&a, 37))
    << 0
}
"""
GOLD = str(sum(sum(((i + j) & 127) + 3 for j in range(3)) * 17 + i * 32 + r
               for r in range(37) for i in range(128))) + '\n'

@pytest.mark.parametrize('flags', [(), ('-O3',)])
@pytest.mark.parametrize('variant', ['base', 'rename', 'import', 'split'])
def test_borrowed_call_scalar_homes(tmp_path, flags, variant):
    source = PROGRAM
    label = '_worker'
    if variant == 'rename':
        source = source.replace('worker', 'run').replace('pick', 'select_value').replace('sum', 'total')
        label = '_run'
    if variant == 'import':
        source = source.replace('@main\n', '@main\n#math\n#strings\n', 1)
    if variant == 'split':
        source = source.replace('fn pick(', 'fn inner_pick(')
        source += '\nfn pick(a &[]int, i int, n int) int { << inner_pick(a, i, n) }\n'
    path = tmp_path / 'main.xu'
    path.write_text(source)
    binary = tmp_path / 'program'
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
        'build', '--timings', *flags, str(path), '-o', str(binary)], cwd=ROOT,
        capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, GOLD, '')
    row = next(dict(w.split('=', 1) for w in line.split()[1:])
               for line in built.stderr.splitlines()
               if line.startswith('ra-fn:') and line.split()[1].endswith(label))
    assert row['mode'] == 'vreg' and row['reason'] == 'verified', row
    assert int(row['gpr']) > 0, row

@pytest.mark.parametrize('flags', [('-O0',), (), ('-O3',)])
def test_reference_contract_and_call_live_homes(tmp_path, flags):
    import shutil
    shutil.copytree(ROOT / 'src', tmp_path / 'src')
    shutil.copy2(ROOT / 'tests/mir_refcall_support.xu',
                 tmp_path / 'src/xu/types/refcall_test.xu')
    driver = tmp_path / 'src/cmd/compile/driver_entry.xu'
    driver.write_text(driver.read_text().replace('fn main()', 'fn unused_refcall_driver_main()', 1))
    prior = os.environ.get('XU_REFCALL_STAGE_SOURCE')
    if prior:
        shutil.copy2(prior, tmp_path / 'src/cmd/compile/emit_frame.xu')
    main = tmp_path / 'src/cmd/compile/main.xu'
    main.write_text("""@main
#xu/types
fn main() int {
    for mode in 0:4 {
        m := types.refcall_field_guard_mir(mode)
        assert(!fn_is_readonly_i64_field_index(&m, -1))
        assert(!fn_is_readonly_i64_field_index(&m, m.fns.len))
        assert(!fn_is_readonly_i64_field_index(&m, 0))
    }
    for mode in 0:19 {
        m := types.refcall_contract_mir(mode)
        admitted := vreg_direct_call_ok(&m, 0, 1)
        // Receiver metadata does not change this explicit one-reference ABI.
        // The same argument and return contract is valid for a method call.
        assert(admitted == (mode <= 2 || mode == 17))
        if admitted {
            for arch in 0:2 {
                plan := vreg_plan(&m, 0, arch)
                assert(plan.len == 4)
                assert(regplan_verify(&m, 0, arch, &plan))
                assert(plan[3] == 0)
                if arch == 0 { assert(plan[0] >= 8 && plan[0] < 14) }
                else { assert(plan[0] >= 2 && plan[0] < 6) }
            }
        }
    }
    for mode in 0:14 {
        m := types.refcall_remat_mir(mode)
        assert((vreg_call_local_alias(&m, 0, 0) == 0) == (mode == 0 || mode == 7))
        for arch in 0:2 {
            mut fr := Frame{local_slot: []int{}, temp_slot: []int{}, fp_split: []int{}, select_pairs: []int{}, sret_slot: -1, size: 0, plan_reason: 0, plan_instr: -1}
            fr.layout(&m, 0, 0, arch, true)
            frame_validate(&fr, &m, 0)
            assert((fr.temp_slot[0] == fr.local_slot[0]) == (mode == 0 || mode == 7))
        }
    }
    println("refcall PASS: 19 contracts, 2 targets")
    << 0
}
""")
    binary = tmp_path / 'contract'
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), '--cwd',
        str(tmp_path), str(XU), 'build', *flags, str(main.parent), '-o', str(binary)],
        cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, 'refcall PASS: 19 contracts, 2 targets\n', '')

MEMORY = """@main
struct Holder { values []int, tag int }
fn bump(value &mut int, n int) int {
    for j in 0:n { *value += j + 1 }
    << *value
}
fn scalar_memory(value &mut int, rounds int) int {
    mut total := 0
    for i in 0:rounds {
        before := *value
        PRESSURE
        total += PRESSURE_NEST
        total += *value
    }
    << total
}
fn grow(a &mut []int, value int) int {
    for j in 0:3 { a.push(value + j) }
    << a.len
}
fn array_memory(a &mut []int, rounds int) int {
    mut total := 0
    for i in 0:rounds {
        before := a.len
        count := grow(a, i)
        total += before + count + a[count - 1]
    }
    << total
}
fn read_holder(h &Holder, n int) int {
    mut total := 0
    for j in 0:n { total += h.values[j] * h.tag }
    << total
}
fn record_memory(h &Holder, rounds int) int {
    mut total := 0
    for i in 0:rounds { total += read_holder(h, 3) + i }
    << total
}
fn text_size(s &string, n int) int {
    mut total := 0
    for j in 0:n { total += s.len + j }
    << total
}
fn text_memory(s &string, rounds int) int {
    mut total := 0
    for i in 0:rounds { total += text_size(s, 3) + i }
    << total
}
fn main() int {
    mut value := 4
    println(scalar_memory(mut &value, 97))
    mut values := []int{}
    println(array_memory(mut &values, 37))
    h := Holder{values: [2,3,5,7], tag: 11}
    println(record_memory(&h, 43))
    s := "hello"
    println(text_memory(&s, 41))
    << 0
}
""".replace('PRESSURE_NEST', ''.join(f'p{j} + (' for j in range(12)) +
    'bump(value, (i & 3) + 1)' + ')' * 12).replace(
    'PRESSURE', '\n        '.join(f'p{j} := (before * {j + 3}) ^ (i + {j + 1})' for j in range(12)))

def scalar_gold(rounds):
    value = 4
    total = 0
    for i in range(rounds):
        before = value
        n = (i & 3) + 1
        value += n * (n + 1) // 2
        total += 2 * value + sum((before * (j + 3)) ^ (i + j + 1) for j in range(12))
    return total

MEMORY_GOLD = '\n'.join(map(str, [scalar_gold(97),
    sum(7 * i + 5 for i in range(37)), sum(110 + i for i in range(43)),
    sum(18 + i for i in range(41))])) + '\n'

@pytest.mark.parametrize('flags', [('-O0',), (), ('-O2',), ('-O3',), ('--no-regcache',), ('-O3', '--ra=0')])
def test_references_mutation_growth_and_pressure(tmp_path, flags):
    path = tmp_path / 'main.xu'
    path.write_text(MEMORY)
    binary = tmp_path / 'memory'
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
        'build', '--timings', *flags, str(path), '-o', str(binary)], cwd=ROOT,
        capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, MEMORY_GOLD, '')
    if flags == ():
        row = next(dict(w.split('=', 1) for w in line.split()[1:])
                   for line in built.stderr.splitlines()
                   if line.startswith('ra-fn:') and '_scalar_memory ' in line)
        assert row['mode'] == 'vreg' and row['reason'] == 'verified', row
        assert int(row['gpr']) > 0 and int(row['spill']) > 0, row

@pytest.mark.parametrize('target', ['linux-x64', 'linux-arm64', 'windows-x64', 'windows-arm64'])
def test_refcall_cross_format(tmp_path, target):
    path = tmp_path / 'main.xu'
    path.write_text(PROGRAM)
    binary = tmp_path / ('program.exe' if target.startswith('windows') else 'program')
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
        'build', '-O3', '--target', target, str(path), '-o', str(binary)],
        cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    assert binary.read_bytes().startswith(b'MZ' if target.startswith('windows') else b'\x7fELF')
