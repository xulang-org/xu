"""Record storage must not block independent scalar SSA promotion."""
from pathlib import Path
import os, shutil, subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
XU=Path(os.environ.get('XU',ROOT/'bin/xu')).resolve()
PROGRAM='@main\nstruct Record { bias int, stride int }\nfn worker(h Record, n int) int {\n    mut sum := 0\n    mut i := 0\n    while i < n {\n        sum += i * h.stride + h.bias\n        i += 1\n    }\n    << sum\n}\nfn main() int { h := Record{bias: 3, stride: 17}\n    println(worker(h, 97))\n    << 0 }\n'
GOLD=str(17*97*96//2+3*97)+'\n'

def build_run(tmp_path,source,flags,expected,stage=False):
    path=tmp_path/'main.xu';path.write_text(source);binary=tmp_path/'program'
    opts=['--cwd',str(tmp_path)] if stage else []
    result=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),*opts,str(XU),'build','--timings',*flags,str(path),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stderr
    built_stderr=result.stderr
    result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert (result.returncode,result.stdout,result.stderr)==(0,expected,'')
    return built_stderr

@pytest.mark.parametrize('flags',[('-O0',),(),('-O3',)])
def test_actual_record_promotion(tmp_path,flags):
    shutil.copytree(ROOT/'src',tmp_path/'src')
    prior=os.environ.get('XU_RECORD_STAGE')
    if prior:
        for name in ['mir_17_opt_promote.xu','mir_17_opt_promote_records.xu','mir_05_expr.xu']:
            shutil.copy2(Path(prior)/'src/xu/types'/name,tmp_path/'src/xu/types'/name)
    (tmp_path/'src/xu/types/record_test.xu').write_text((ROOT/'tests/mir_ssa_record_support.xu').read_text())
    source='@main\n#xu/types\nfn main() int { for mode in 0:26 { mut c := types.Checker{}\n assert(types.record_test(mut &c, mode)) }\n println("record SSA PASS: 26 cases")\n << 0 }\n'
    build_run(tmp_path,source,flags,'record SSA PASS: 26 cases\n',True)

@pytest.mark.parametrize('flags',[('-O0',),(),('-O2',),('-O3',),('--no-regcache',),('-O3','--ra=0')])
@pytest.mark.parametrize('variant',['base','rename','import','split','mutate'])
def test_record_native_values(tmp_path,flags,variant):
    source=PROGRAM
    if variant=='rename':source=source.replace('worker','compute').replace('sum','total').replace('Record','Options')
    if variant=='import':source=source.replace('@main\n','@main\n#math\n#strings\n',1)
    if variant=='split':source=source.replace('fn worker(','fn inner(')+'\nfn worker(h Record, n int) int { << inner(h,n) }\n'
    expected=GOLD
    if variant=='mutate':
        source=source.replace('worker(h Record','worker(h &mut Record').replace('sum += i * h.stride + h.bias','h.bias += 1\n        sum += i * h.stride + h.bias').replace('h := Record','mut h := Record').replace('worker(h, 97)','worker(mut &h, 97)')
        expected=str(17*97*96//2+3*97+97*98//2)+'\n'
    stderr=build_run(tmp_path,source,flags,expected)
    if flags in [(),('-O3',)] and variant!='mutate':
        label='_inner' if variant=='split' else ('_compute' if variant=='rename' else '_worker')
        row=next(dict(w.split('=',1) for w in line.split()[1:]) for line in stderr.splitlines() if line.startswith('ra-fn:') and line.split()[1].endswith(label))
        assert row['mode']=='vreg' and row['reason']=='verified',row

@pytest.mark.parametrize('target',['linux-x64','linux-arm64','windows-x64','windows-arm64'])
def test_record_cross_format(tmp_path,target):
    path=tmp_path/'main.xu';path.write_text(PROGRAM);binary=tmp_path/('program.exe' if target.startswith('windows') else 'program')
    result=subprocess.run([str(ROOT/'scripts/run_product_compiler.sh'),str(XU),'build','-O3','--target',target,str(path),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stderr
    assert binary.read_bytes().startswith(b'MZ' if target.startswith('windows') else b'\x7fELF')
