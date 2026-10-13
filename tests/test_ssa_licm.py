"""Default scalar loop code motion at the real promotion/SSA commit seam."""
from pathlib import Path
import os, shutil, subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
XU=Path(os.environ.get('XU',ROOT/'bin/xu')).resolve()

@pytest.mark.parametrize('flags',[('-O0',),(),('-O3',)])
def test_actual_ssa_loop_motion(tmp_path,flags):
    shutil.copytree(ROOT/'src',tmp_path/'src')
    stage=os.environ.get('XU_LICM_STAGE')
    if stage:
        for name in ['mir_17_opt_promote.xu','mir_17_ssa_licm.xu']:
            shutil.copy2(Path(stage)/'src/xu/types'/name,tmp_path/'src/xu/types'/name)
    support=(ROOT/'tests/mir_ssa_licm_support.xu').read_text()+'\n'+(ROOT/'tests/mir_ssa_simplify_support.xu').read_text().replace('@xu/types\n','',1)+'\n'+(ROOT/'tests/mir_ssa_cse_support.xu').read_text().replace('@xu/types\n','',1)
    (tmp_path/'src/xu/types/licm_test.xu').write_text(support)
    main=tmp_path/'main.xu';binary=tmp_path/'program'
    main.write_text('@main\n#xu/types\nfn main() int { mut c := types.Checker{}\n assert(types.licm_test_central(mut &c))\n for mode in 0:19 { if !types.licm_test_graph(mode) { println(mode)\n assert(false) } }\n println("SSA loop motion PASS")\n << 0 }\n')
    p=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),'--cwd',str(tmp_path),str(XU),'build',*flags,str(main),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert p.returncode==0,p.stderr
    p=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert (p.returncode,p.stdout,p.stderr)==(0,'SSA loop motion PASS\n','')

PROGRAM='''@main
fn worker(seed int, salt int, n int) int {
    factor := seed
    bias := salt
    mut sum := 0
    mut i := 0
    while i < n {
        mixed := (factor * 17) ^ bias
        sum += mixed + i
        i += 1
    }
    << sum
}
fn main() int {
    for seed in -17:25 {
        for salt in -3:4 {
            for n in -2:34 { println(worker(seed, salt, n)) }
        }
    }
    << 0
}
'''

def program(variant):
    source=PROGRAM
    if variant=='rename':source=source.replace('worker','accumulate').replace('factor','scale').replace('bias','mask')
    if variant=='import':source=source.replace('@main\n','@main\n#math\n#strings\n',1)
    if variant=='split':source=source.replace('fn worker(','fn inner(')+'\nfn worker(seed int, salt int, n int) int { << inner(seed,salt,n) }\n'
    if variant=='mutate':source=source.replace('factor := seed','mut factor := seed').replace('i += 1','factor += 1\n        i += 1')
    if variant=='borrow':
        source=source.replace('factor := seed','mut factor := seed').replace('i += 1','step(mut &factor)\n        i += 1')+'\nfn step(p &mut int) { *p += 1 }\n'
    return source

def expected(variant):
    return ''.join(str(sum((((seed+(i if variant in ('mutate','borrow') else 0))*17)^salt)+i for i in range(max(n,0))))+'\n'
                   for seed in range(-17,25) for salt in range(-3,4) for n in range(-2,34))

@pytest.mark.parametrize('flags',[('-O0',),(),('-O2',),('-O3',),('--no-regcache',),('-O3','--ra=0')])
@pytest.mark.parametrize('variant',['base','rename','import','split','mutate','borrow'])
def test_native_loop_semantics(tmp_path,flags,variant):
    path=tmp_path/'main.xu';path.write_text(program(variant));binary=tmp_path/'program'
    p=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),str(XU),'build',*flags,str(path),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert p.returncode==0,p.stderr
    p=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert (p.returncode,p.stdout,p.stderr)==(0,expected(variant),'')

@pytest.mark.parametrize('target',['linux-x64','linux-arm64','windows-x64','windows-arm64'])
def test_loop_cross_format(tmp_path,target):
    path=tmp_path/'main.xu';path.write_text(PROGRAM);binary=tmp_path/('program.exe' if target.startswith('windows') else 'program')
    p=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),str(XU),'build','--target',target,str(path),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert p.returncode==0,p.stderr
    assert binary.read_bytes().startswith(b'MZ' if target.startswith('windows') else b'\x7fELF')
