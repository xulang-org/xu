"""Explicit local borrows keep references in the frame and scalar work in registers."""
from pathlib import Path
import os, subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get('XU', ROOT / 'bin/xu'))
PROGRAM = """@main
fn bump(value &mut int, n int) int {
    for j in 0:n { *value += j + 1 }
    << *value
}
fn worker(rounds int) int {
    mut value := 4
    mut total := 0
    for i in 0:rounds {
        before := value
        x := (i * 17) ^ 23
        total += before + (x + bump(mut &value, (i & 3) + 1))
        total += value
    }
    << total
}
fn main() int { println(worker(97))
    << 0 }
"""

def scalar_gold(rounds, pressure=False):
    value, total = 4, 0
    for i in range(rounds):
        before = value
        n = (i & 3) + 1
        value += n * (n + 1) // 2
        work = sum((before * (j + 3)) ^ (i + j + 1) for j in range(12)) if pressure else (i * 17) ^ 23
        total += before + work + 2 * value
    return str(total) + '\n'

GOLD = scalar_gold(97)
PRESSURE = PROGRAM.replace('x := (i * 17) ^ 23', '\n        '.join(
    f'p{j} := (before * {j + 3}) ^ (i + {j + 1})' for j in range(12))).replace(
    'x + bump(mut &value, (i & 3) + 1)', ''.join(f'p{j} + (' for j in range(12)) +
    'bump(mut &value, (i & 3) + 1)' + ')' * 12)

def build_and_run(tmp_path, source, flags, expected):
    path, binary = tmp_path / 'main.xu', tmp_path / 'program'
    path.write_text(source)
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
        'build', '--timings', *flags, str(path), '-o', str(binary)], cwd=ROOT,
        capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, expected, '')
    return built.stderr

@pytest.mark.parametrize('flags', [(), ('-O3',)])
@pytest.mark.parametrize('variant', ['base', 'rename', 'import', 'split'])
def test_local_borrow_scalar_homes(tmp_path, flags, variant):
    source, label = PROGRAM, '_worker'
    if variant == 'rename':
        source = source.replace('worker', 'run').replace('bump', 'advance').replace('total', 'sum')
        label = '_run'
    if variant == 'import':
        source = source.replace('@main\n', '@main\n#math\n#strings\n', 1)
    if variant == 'split':
        source = source.replace('fn bump(', 'fn advance(')
        source += '\nfn bump(value &mut int, n int) int { << advance(value, n) }\n'
    stderr = build_and_run(tmp_path, source, flags, GOLD)
    row = next(dict(w.split('=', 1) for w in line.split()[1:])
               for line in stderr.splitlines() if line.startswith('ra-fn:') and line.split()[1].endswith(label))
    assert row['mode'] == 'vreg' and row['reason'] == 'verified', row
    assert int(row['gpr']) > 0, row

@pytest.mark.parametrize('flags', [('-O0',), (), ('-O2',), ('-O3',), ('--no-regcache',), ('-O3', '--ra=0')])
def test_local_mutation_snapshot_and_pressure(tmp_path, flags):
    stderr = build_and_run(tmp_path, PRESSURE, flags, scalar_gold(97, True))
    if flags == ():
        row = next(dict(w.split('=', 1) for w in line.split()[1:])
                   for line in stderr.splitlines() if line.startswith('ra-fn:') and '_worker ' in line)
        assert row['mode'] == 'vreg' and row['reason'] == 'verified', row
        assert int(row['gpr']) > 0 and int(row['spill']) > 0, row

# Multiword objects and scalar pointees share the checked borrow seam. Their
# layouts, ownership and observable mutations remain unchanged at every level.
AGGREGATES = """@main
struct Pair { left int, right int }
fn read_pair(p &Pair, n int) int { mut s := 0
    for i in 0:n { s += p.left + p.right + i }
    << s }
fn grow(a &mut []int, n int) int { for i in 0:n { a.push(i + 7) }
    << a.len }
fn text_size(s &string, n int) int { mut v := 0
    for i in 0:n { v += s.len + i }
    << v }
fn read_fixed(a &[4]int, n int) int { mut v := 0
    for i in 0:n { v += a[i & 3] }
    << v }
fn flip(b &mut bool) int { *b = !*b
    if *b { << 1 }
    << 0 }
fn main() int {
    p := Pair{left: 3, right: 5}
    a := [4]int{2,3,5,7}
    mut values := []int{}
    s := "hello"
    mut b := false
    mut sum := 0
    for i in 0:37 {
        before := values.len
        sum += read_pair(&p, 3) + read_fixed(&a, 7) + text_size(&s, 3)
        count := grow(mut &values, 3)
        sum += before + count + values[values.len - 1] + flip(mut &b) + i
    }
    println(sum)
    << 0
}
"""
AGGREGATE_GOLD = str(sum(27 + 27 + 18 + 6 * i + 3 + 9 + (1 if i % 2 == 0 else 0) + i for i in range(37))) + '\n'

@pytest.mark.parametrize('flags', [('-O0',), (), ('-O2',), ('-O3',), ('--no-regcache',), ('-O3', '--ra=0')])
def test_local_aggregate_borrows(tmp_path, flags):
    build_and_run(tmp_path, AGGREGATES, flags, AGGREGATE_GOLD)

@pytest.mark.parametrize('target', ['linux-x64', 'linux-arm64', 'windows-x64', 'windows-arm64'])
def test_local_borrow_cross_format(tmp_path, target):
    path = tmp_path / 'main.xu'
    path.write_text(PROGRAM)
    binary = tmp_path / ('program.exe' if target.startswith('windows') else 'program')
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
        'build', '-O3', '--target', target, str(path), '-o', str(binary)], cwd=ROOT,
        capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    assert binary.read_bytes().startswith(b'MZ' if target.startswith('windows') else b'\x7fELF')

@pytest.mark.parametrize('flags', [('-O0',), (), ('-O3',)])
def test_local_address_contract_and_real_frame(tmp_path, flags):
    import shutil
    shutil.copytree(ROOT / 'src', tmp_path / 'src')
    for name in ['refcall', 'local_borrow']:
        shutil.copy2(ROOT / f'tests/mir_{name}_support.xu', tmp_path / f'src/xu/types/{name}_test.xu')
    staged = os.environ.get('XU_LOCAL_BORROW_STAGE')
    if staged:
        for path in ['src/cmd/compile/emit_frame.xu', 'src/xu/types/mir_06_expr_complex.xu']:
            shutil.copy2(Path(staged) / path, tmp_path / path)
    driver = tmp_path / 'src/cmd/compile/driver_entry.xu'
    driver.write_text(driver.read_text().replace('fn main()', 'fn unused_local_borrow_driver_main()', 1))
    main = tmp_path / 'src/cmd/compile/main.xu'
    main.write_text("""@main
#xu/types
#xu/scanner
#xu/parser
#xu/ast
fn main() int {
    for mode in 0:8 {
        m := types.local_borrow_contract_mir(mode)
        for arch in 0:2 {
            plan := vreg_plan(&m, 0, arch)
            mut has_home := false
            for home in plan { if home >= 2 { has_home = true } }
            assert(has_home == (mode == 0))
            if has_home {
                assert(regplan_verify(&m, 0, arch, &plan))
                assert(plan[3] == 0)
                assert(vreg_call_local_alias(&m, 0, 0) < 0)
                mut fr := Frame{local_slot: []int{}, temp_slot: []int{}, fp_split: []int{}, select_pairs: []int{}, sret_slot: -1, size: 0, plan_reason: 0, plan_instr: -1}
                fr.layout(&m, 0, 0, arch, true)
                frame_validate(&fr, &m, 0)
                assert(is_frame_slot(fr.local_slot[0]))
                assert(is_frame_slot(fr.temp_slot[3]))
                assert(fr.local_slot[0] != fr.temp_slot[3])
                assert(fr.local_slot[0] != fr.temp_slot[0])
            }
        }
    }
    mut tokens := []ast.Token{}
    scanner.lex("@main\\nfn bump(p &mut int) int { *p += 1\\n << *p }\\nfn work(n int) int { mut v := 4\\n mut s := 0\\n for i in 0:n { x := v\\n s += x + bump(mut &v)\\n s += v + i }\\n << s }\\nfn main() int { << work(9) }\\n", mut &tokens, "localborrow.xu")
    mut p := parser.new_parser(tokens)
    p.parse_module()
    mut c := types.Checker{}
    mut m := types.empty_mir()
    m.opt_level = 0
    mut functions := []types.CFn{}
    types.run_checker(mut &c, &p, 0, 0, 0, []string{}, []string{}, 1, mut &m, []string{}, "", false, false, 1, false, mut &functions)
    mut found := 0
    for fi in 0:m.fns.len {
        for ii in 0:types.mir_nins(&m, fi) {
            if types.mir_ikind(&m, fi, ii) == 16 && types.mir_ic(&m, fi, ii) == 0 {
                dest := types.mir_ia(&m, fi, ii)
                local := types.mir_ib(&m, fi, ii)
                assert(types.mir_temp_ty(&m, fi, dest) == 2001)
                assert(types.mir_temp_nslots(&m, fi, dest) == 1)
                assert(types.mir_local_ty(&m, fi, local) == 1)
                found += 1
            }
        }
    }
    assert(found == 1)
    println("local borrow PASS: checked lowering, 8 contracts, 2 targets")
    << 0
}
""")
    binary = tmp_path / 'contract'
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), '--cwd', str(tmp_path),
        str(XU), 'build', *flags, str(main.parent), '-o', str(binary)], cwd=tmp_path,
        capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (
        0, 'local borrow PASS: checked lowering, 8 contracts, 2 targets\n', '')
