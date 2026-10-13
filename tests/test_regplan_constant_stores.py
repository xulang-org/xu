"""Checked integer array constants retain fixed homes and exact word values."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get('XU', ROOT/'bin/xu'))
WRAPPER = ROOT/'scripts/run_product_compiler.sh'
PROGRAM = '@main\nfn clear(a &mut []int, lo int, hi int) {\n    for i in lo:hi { a[i] = 0 }\n}\nfn boundaries(a &mut []int) {\n    a[0] = -9223372036854775807 - 1\n    a[1] = 9223372036854775807\n    a[2] = 4294967296\n    a[3] = -17\n}\nfn main() int {\n    mut a := []int{}\n    for i in 0:257 { a.push(i + 9) }\n    clear(mut &a, 9, 246)\n    boundaries(mut &a)\n    for i in 0:a.len { println(a[i]) }\n    << 0\n}\n'
VALUES = [i+9 if i < 9 or i >= 246 else 0 for i in range(257)]
VALUES[:4] = [-(1<<63), (1<<63)-1, 1<<32, -17]
GOLD = ''.join(str(x)+'\n' for x in VALUES)

@pytest.mark.parametrize('flags', [(), ('-O3',), ('--no-opt',)])
@pytest.mark.parametrize('target', [None, 'linux-x64'])
def test_checked_constants_preserve_words_and_register_path(tmp_path, flags, target):
    source, binary = tmp_path/'main.xu', tmp_path/'program'
    source.write_text(PROGRAM)
    command = [str(WRAPPER), str(XU), 'build', '--timings', *flags, str(source), '-o', str(binary)]
    if target: command += ['--target', target]
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    rows = [dict(word.split('=',1) for word in line.split()[1:])
            for line in built.stderr.splitlines() if line.startswith('ra-fn:')]
    for suffix in ('_clear', '_boundaries'):
        row = next(row for row in rows if row['label'].endswith(suffix))
        assert row['mode'] == ('frame' if flags == ('--no-opt',) else 'vreg'), row
        if not flags: assert row['reason'] == 'verified', row
    if target:
        assert binary.read_bytes().startswith(b'\x7fELF')
    else:
        run = subprocess.run([str(binary)], capture_output=True,text=True,timeout=30)
        assert (run.returncode,run.stdout,run.stderr) == (0,GOLD,'')


def test_pooled_operand_contract_fails_closed(tmp_path):
    shutil.copytree(ROOT/'src', tmp_path/'src')
    stage = os.environ.get('XU_CONSTANT_STORE_STAGE')
    if stage:
        shutil.copy2(Path(stage)/'src/cmd/compile/emit_frame.xu', tmp_path/'src/cmd/compile/emit_frame.xu')
    shutil.copy2(ROOT/'tests/mir_constant_store_support.xu', tmp_path/'src/xu/types/constant_store_test.xu')
    driver = tmp_path/'src/cmd/compile/driver_entry.xu'
    driver.write_text(driver.read_text().replace('fn main()', 'fn unused_constant_store_driver_main()', 1))
    main = tmp_path/'src/cmd/compile/main.xu'
    main.write_text("""@main
#xu/types
fn main() int {
    for mode in 0:6 {
        m := types.constant_store_contract_mir(mode)
        assert(vreg_storeindex_int_ok(&m, 0, 0, 1, -2, 8) == (mode == 0))
        // -1 is a missing value; -3 is beyond this one-entry pool. The
        // minimum signed ID exercises overflow-safe constant indexing.
        assert(!vreg_storeindex_int_ok(&m, 0, 0, 1, -1, 8))
        assert(!vreg_storeindex_int_ok(&m, 0, 0, 1, -3, 8))
        assert(!vreg_storeindex_int_ok(&m, 0, 0, 1, -9223372036854775807 - 1, 8))
        assert(!vreg_storeindex_int_ok(&m, 0, 0, 1, -2, 1))
        assert(!vreg_storeindex_int_ok(&m, 0, 0, 1, -2, 0))
    }
    println("constant store contract PASS")
    << 0
}
""")
    sources = [main]+sorted(p for p in main.parent.glob('*.xu') if p != main)
    binary = tmp_path/'contract'
    built = subprocess.run([str(WRAPPER),'--cwd',str(tmp_path),str(XU),'build',*map(str,sources),'-o',str(binary)],
                           cwd=tmp_path,capture_output=True,text=True,timeout=240)
    assert built.returncode == 0,built.stderr
    run = subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert (run.returncode,run.stdout,run.stderr) == (0,'constant store contract PASS\n','')


@pytest.mark.parametrize('flags', [(), ('--no-opt',)])
@pytest.mark.parametrize('size,index', [(4,-1), (4,4), (0,0)])
def test_constant_store_keeps_runtime_bounds_check(tmp_path, flags, size, index):
    source, binary = tmp_path/'bounds.xu', tmp_path/'bounds'
    source.write_text(f"""@main
fn write(a &mut []int, i int) {{
    for repeat in 0:2 {{ a[i] = 0 }}
}}
fn main() int {{
    mut a := make_ints({size})
    write(mut &a, {index})
    << 0
}}
""")
    built = subprocess.run([str(WRAPPER),str(XU),'build',*flags,str(source),'-o',str(binary)],
                           cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert built.returncode == 0,built.stderr
    run = subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert (run.returncode,run.stdout,run.stderr) == (1,'','index out of bounds\n')
