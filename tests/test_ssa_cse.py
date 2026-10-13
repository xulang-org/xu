"""SSA CSE at the real value-simplification seam, before Phi destruction."""
from pathlib import Path
import os,shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
XU=Path(os.environ.get('XU',ROOT/'bin/xu')).resolve()
MAIN='''@main
#xu/types
fn main() int {
    for mode in 0:21 {
        if !types.cse_test_case(mode, false) { println("SSA CSE case failed:")
            println(mode)
            assert(false) }
    }
    assert(types.cse_test_loop(false))
    assert(types.cse_test_bad_input())
    println("SSA CSE PASS: 23 cases")
    << 0
}
'''
@pytest.mark.parametrize('flags',[('-O0',),(),('-O3',)])
@pytest.mark.parametrize('entry',['checked','verified'])
def test_actual_ssa_cse(tmp_path,flags,entry):
    shutil.copytree(ROOT/'src',tmp_path/'src')
    support=(ROOT/'tests/mir_ssa_simplify_support.xu').read_text()+(ROOT/'tests/mir_ssa_cse_support.xu').read_text().replace('@xu/types\n','',1)
    prior=os.environ.get('XU_SSA_STAGE_SOURCE')
    if prior:shutil.copy2(prior,tmp_path/'src/xu/types/mir_17_ssa_simplify.xu')
    (tmp_path/'src/xu/types/ssa_cse_test.xu').write_text(support)
    main=MAIN if entry=='checked' else MAIN.replace('mode, false','mode, true').replace('cse_test_loop(false)','cse_test_loop(true)')
    (tmp_path/'main.xu').write_text(main);binary=tmp_path/'main'
    built=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),'--cwd',str(tmp_path),str(XU),'build',*flags,str(tmp_path/'main.xu'),'-o',str(binary)],cwd=tmp_path,capture_output=True,text=True,timeout=180)
    assert built.returncode==0,built.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert (run.returncode,run.stdout,run.stderr)==(0,'SSA CSE PASS: 23 cases\n','')

PROGRAM='''@main
fn kernel(n int) int {
    mut i := 0
    mut sum := 0
    while i < n {
        word := (i * 17) ^ 23
        if (i & 1) == 0 { sum += word + ((i * 17) ^ 23) + 3 }
        else { sum += word + ((i * 17) ^ 23) - 7 }
        i += 1
    }
    << sum
}
fn bump(p &mut int) int {
    before := *p
    *p = before + 4
    << before + *p
}
fn snapshots(seed int) int {
    mut storage := seed
    snapshot := storage
    first := (snapshot * 17) ^ 23
    effect := bump(mut &storage)
    << first + ((snapshot * 17) ^ 23) + effect + storage
}
fn main() int {
    for n in 0:33 {
        println(kernel(n))
        println(snapshots(n - 17))
    }
    << 0
}
'''
GOLD=''.join(str(sum(2*((i*17)^23)+(3 if i%2==0 else -7) for i in range(n)))+'\n'+str(2*(((n-17)*17)^23)+3*(n-17)+8)+'\n' for n in range(33))

def variant_source(variant):
    if variant=='rename':return PROGRAM.replace('kernel','accumulate').replace('word','scaled')
    if variant=='import':return PROGRAM.replace('@main\n','@main\n#math\n',1)
    return PROGRAM.replace('fn kernel(','fn inner_kernel(')+'\nfn kernel(n int) int { << inner_kernel(n) }\n'

@pytest.mark.parametrize('flags',[('-O0',),(),('-O2',),('-O3',),('--no-regcache',),('-O3','--ra=0')])
@pytest.mark.parametrize('variant',['rename','import','split'])
def test_native_values_and_snapshots(tmp_path,flags,variant):
    source=tmp_path/'main.xu';source.write_text(variant_source(variant));binary=tmp_path/'program'
    built=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),str(XU),'build',*flags,str(source),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert built.returncode==0,built.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert (run.returncode,run.stdout,run.stderr)==(0,GOLD,'')

@pytest.mark.parametrize('target',['linux-x64','linux-arm64','windows-x64','windows-arm64'])
def test_cross_target_cse(tmp_path,target):
    source=tmp_path/'main.xu';source.write_text(PROGRAM);binary=tmp_path/('program.exe' if target.startswith('windows') else 'program')
    built=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),str(XU),'build','-O3','--target',target,str(source),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert built.returncode==0,built.stderr
    assert binary.read_bytes().startswith(b'MZ' if target.startswith('windows') else b'\x7fELF')
