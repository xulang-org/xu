"""Real promotion seam: unit size must not disable bounded integer CFGs."""
from pathlib import Path
import os,shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
XU=Path(os.environ.get('XU',ROOT/'bin/xu')).resolve()
MAIN='''@main
#xu/types
fn main() int {
    assert(types.scope_test_promote(0))
    assert(types.scope_test_promote(1))
    for mode in 1:22 { assert(types.scope_test_boundary(mode)) }
    for mode in 0:3 { assert(types.scope_test_bad_operand(mode)) }
    for mode in 0:14 { assert(types.scope_test_strict_reads(mode)) }
    println("SSA unit scope PASS: 40 cases")
    << 0
}
'''
@pytest.mark.parametrize('flags',[('-O0',),(),('-O3',)])
def test_actual_large_unit_promotion(tmp_path,flags):
    shutil.copytree(ROOT/'src',tmp_path/'src')
    support=(ROOT/'tests/mir_ssa_simplify_support.xu').read_text()+(ROOT/'tests/mir_ssa_unit_scope_support.xu').read_text().replace('@xu/types\n','',1)
    prior=os.environ.get('XU_PROMOTE_STAGE_SOURCE')
    if prior:shutil.copy2(prior,tmp_path/'src/xu/types/mir_17_opt_promote.xu')
    (tmp_path/'src/xu/types/ssa_scope_test.xu').write_text(support)
    (tmp_path/'main.xu').write_text(MAIN);binary=tmp_path/'main'
    built=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),'--cwd',str(tmp_path),str(XU),'build',*flags,str(tmp_path/'main.xu'),'-o',str(binary)],cwd=tmp_path,capture_output=True,text=True,timeout=180)
    assert built.returncode==0,built.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert (run.returncode,run.stdout,run.stderr)==(0,'SSA unit scope PASS: 40 cases\n','')

from test_ssa_simplify import PROGRAM,GOLD

@pytest.mark.parametrize('flags',[('-O0',),(),('-O2',),('-O3',),('--no-regcache',),('-O3','--ra=0')])
@pytest.mark.parametrize('variant',['base','rename','split'])
def test_large_unit_native_values(tmp_path,flags,variant):
    source=PROGRAM.replace('@main\n','@main\n#math\n#strings\n',1)
    if variant=='rename':source=source.replace('kernel','compute').replace('rotate','swap_loop')
    if variant=='split':source=source.replace('fn kernel(','fn inner_kernel(')+'\nfn kernel(n int, flag bool) int { << inner_kernel(n, flag) }\n'
    path=tmp_path/'main.xu';path.write_text(source);binary=tmp_path/'program'
    built=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),str(XU),'build',*flags,str(path),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert built.returncode==0,built.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert (run.returncode,run.stdout,run.stderr)==(0,GOLD,'')

@pytest.mark.parametrize('target',['linux-x64','linux-arm64','windows-x64','windows-arm64'])
def test_large_unit_cross_format(tmp_path,target):
    path=tmp_path/'main.xu';path.write_text(PROGRAM.replace('@main\n','@main\n#math\n#strings\n',1))
    binary=tmp_path/('program.exe' if target.startswith('windows') else 'program')
    built=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),str(XU),'build','-O3','--target',target,str(path),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert built.returncode==0,built.stderr
    assert binary.read_bytes().startswith(b'MZ' if target.startswith('windows') else b'\x7fELF')
