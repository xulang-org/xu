"""Formal SSA simplification at production promotion/destruction seams."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get('XU', ROOT / 'bin/xu')).resolve()
MAIN = '''@main
#xu/types
fn main() int {
    assert(types.ssa_test_diamond(false))
    assert(types.ssa_test_diamond(true))
    assert(types.ssa_test_loop(false))
    assert(types.ssa_test_loop(true))
    for mode in 0:7 { assert(types.ssa_test_storage_and_calls(mode)) }
    for mode in 0:2 { assert(types.ssa_test_float_and_budget(mode)) }
    for mode in 0:3 { assert(types.ssa_test_narrow(mode)) }
    assert(types.ssa_test_single_temp())
    println("SSA simplify PASS: 17 cases")
    << 0
}
'''

@pytest.mark.parametrize('flags', [('-O0',), (), ('-O3',)])
@pytest.mark.parametrize('entry', ['checked', 'promoted'])
def test_actual_ssa_stage(tmp_path, flags, entry):
    shutil.copytree(ROOT / 'src', tmp_path / 'src')
    support = (ROOT / 'tests/mir_ssa_simplify_support.xu').read_text()
    if entry == 'promoted':
        # Only these two real promotion seams carry a fresh strict SSA proof.
        # Malformed/direct inputs below continue through the checked wrapper.
        for name in ['ssa_test_diamond', 'ssa_test_loop']:
            start = support.index('pub fn ' + name + '(')
            end = support.index('\npub fn ', start + 1)
            part = support[start:end]
            assert part.count('mir_ssa_simplify_f(mut &f)') == 1
            support = support[:start] + part.replace('mir_ssa_simplify_f(mut &f)',
                                                   'mir_ssa_simplify_verified_f(mut &f)') + support[end:]
    prior_stage = os.environ.get('XU_SSA_STAGE_SOURCE')
    if prior_stage:
        # Controlled before/after replay; only the isolated test tree changes.
        shutil.copy2(prior_stage, tmp_path / 'src/xu/types/mir_17_ssa_simplify.xu')
    # Before the stage exists, this identity adapter recreates the existing
    # immediate promotion->Phi-elimination boundary. RED must be an assertion
    # failure on unchanged SSA, never an undefined-function compiler error.
    if os.environ.get('XU_SSA_IDENTITY_ADAPTER') == '1':
        support += '\nfn mir_ssa_simplify_f(f &mut MFn) int { << 0 }\n'
    (tmp_path / 'src/xu/types/ssa_simplify_test.xu').write_text(support)
    (tmp_path / 'main.xu').write_text(MAIN)
    binary = tmp_path / 'main'
    result = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), '--cwd', str(tmp_path), str(XU),
                             'build', *flags, str(tmp_path / 'main.xu'), '-o', str(binary)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, 'SSA simplify PASS: 17 cases\n', '')

PROGRAM = '''@main
fn kernel(n int, flag bool) int {
    mut base := 0
    if flag { base = 37 } else { base = 37 }
    mut sum := 0
    mut i := 0
    while i < n {
        if (i & 1) == 0 { sum += i * base } else { sum -= i ^ base }
        i += 1
    }
    << sum
}
fn rotate(n int) int {
    mut a := 11
    mut b := 22
    mut i := 0
    while i < n {
        before := a
        a = b
        b = before
        i += 1
    }
    << a * 3 + b
}
fn update(p &mut int) int {
    before := *p
    *p = before + 4
    << before + *p
}
fn main() int {
    for n in 0:33 {
        println(kernel(n, true))
        println(kernel(n, false))
        println(rotate(n))
    }
    mut x := 37
    println(update(mut &x))
    println(x)
    << 0
}
'''
GOLD = ''.join(f'{sum(i * 37 if i % 2 == 0 else -(i ^ 37) for i in range(n))}\n' * 2
               + f'{55 if n % 2 == 0 else 77}\n' for n in range(33)) + '78\n41\n'

@pytest.mark.parametrize('flags', [(), ('-O2',), ('-O3',), ('--no-regcache',), ('-O3', '--ra=0')])
def test_frontend_loop_and_storage_semantics(tmp_path, flags):
    source = tmp_path / 'main.xu'
    source.write_text(PROGRAM)
    binary = tmp_path / 'program'
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
                            'build', *flags, str(source), '-o', str(binary)],
                           cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, GOLD, '')

@pytest.mark.parametrize('variant', ['rename', 'import', 'split'])
def test_equivalent_programs(tmp_path, variant):
    source = PROGRAM
    if variant == 'rename':
        source = source.replace('kernel', 'compute').replace('rotate', 'swap_loop')
    elif variant == 'import':
        source = source.replace('@main\n', '@main\n#math\n', 1)
    else:
        source = source.replace('fn kernel(', 'fn inner_kernel(')
        source += '\nfn kernel(n int, flag bool) int { << inner_kernel(n, flag) }\n'
    path = tmp_path / 'main.xu'
    path.write_text(source)
    binary = tmp_path / 'program'
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
                            'build', str(path), '-o', str(binary)],
                           cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, GOLD, '')

@pytest.mark.parametrize('target', ['linux-x64', 'linux-arm64', 'windows-x64', 'windows-arm64'])
def test_cross_target_emission(tmp_path, target):
    source = tmp_path / 'main.xu'
    source.write_text(PROGRAM)
    binary = tmp_path / ('program.exe' if target.startswith('windows') else 'program')
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
                            'build', '-O3', '--target', target, str(source), '-o', str(binary)],
                           cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    # These targets are compile evidence, not native execution evidence.
    assert binary.read_bytes().startswith(b'MZ' if target.startswith('windows') else b'\x7fELF')

# SSA Copy removal changes which de-SSA loop values feed bit intrinsics.
# The historical cfg fixture includes multiple backedges, continue and real
# rotate calls; whole-function use checks alone cannot elide its Phi copies.
BITS_CFG = ROOT / 'tests/fixtures/math_bits_scalar_cfg'

@pytest.mark.parametrize('flags', [(), ('-O2',), ('-O3',)])
@pytest.mark.parametrize('renamed', [False, True])
def test_bits_intrinsic_loop_phi_copies(tmp_path, flags, renamed):
    source = (BITS_CFG / 'main.xu').read_text()
    if renamed:
        source = source.replace('fold', 'compute').replace('value', 'word')
    path = tmp_path / 'main.xu'
    path.write_text(source)
    binary = tmp_path / 'program'
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
                            'build', *flags, str(path), '-o', str(binary)],
                           cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (run.returncode, run.stdout, run.stderr) == (0, (BITS_CFG / 'expected.txt').read_text(), '')

@pytest.mark.parametrize('target', ['linux-x64', 'linux-arm64', 'windows-x64', 'windows-arm64'])
def test_bits_intrinsic_cross_emission(tmp_path, target):
    binary = tmp_path / ('program.exe' if target.startswith('windows') else 'program')
    built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(XU),
                            'build', '-O3', '--target', target, str(BITS_CFG / 'main.xu'),
                            '-o', str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert built.returncode == 0, built.stderr
    assert binary.read_bytes().startswith(b'MZ' if target.startswith('windows') else b'\x7fELF')
