"""Registry drift checks and optional hosted ABI binding regression gate."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import pytest
ROOT = Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('xu_registry', ROOT/'scripts/generate_runtime_abi_registry.py')
registry=importlib.util.module_from_spec(spec);spec.loader.exec_module(registry)

def data(): return json.loads(registry.REGISTRY.read_bytes())

@pytest.mark.parametrize('raw', [b'{"schema":1,"schema":1}', b'{"effects":{"allocate":false,"allocate":true}}'])
def test_duplicate_json_keys_fail_closed(raw):
    with pytest.raises(ValueError, match='duplicate registry key'):
        registry.render(raw)


def test_generated_contract_matches_versioned_input():
    assert registry.OUTPUT.read_text()==registry.render(registry.REGISTRY.read_bytes())

@pytest.mark.parametrize('field,value', [('id',0),('abi','host'),('module','user'),('may_throw',1),('inline_hint','always'),('syntax_aliases','str'),('params',{})])
def test_rejects_invalid_contract_identity(field,value):
    j=data();j['entries'][0][field]=value
    with pytest.raises(ValueError): registry.validate(j)

@pytest.mark.parametrize('mutation', ['id','name','alias','own','shape','proof'])
def test_rejects_ambiguity_and_unsupported_permission(mutation):
    j=data();a,b=j['entries'][:2]
    if mutation=='id': b['id']=a['id']
    if mutation=='name': b['name']=a['name']
    if mutation=='alias': b['syntax_aliases']=a['syntax_aliases']
    if mutation=='own': a['params'][0]['ownership']='move'
    if mutation=='shape': a['params'][0]['shape']='raw_pointer'
    if mutation=='proof': j['effect_authority']='verified pure'
    with pytest.raises(ValueError): registry.validate(j)

def run_gate(compiler: Path, output: Path):
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    rows=[]
    bad=[
        ('owning','pub fn starts_with(s string, p string) bool { << false }','starts_with'),
        ('mutable','pub fn starts_with(s &mut string, p &string) bool { << false }','starts_with'),
        ('arity','pub fn starts_with(s &string) bool { << false }','starts_with'),
        ('result','pub fn starts_with(s &string, p &string) int { << 0 }','starts_with'),
        ('throws','pub fn parse_int(s &string) int { << 1 }','parse_int'),
        ('fixed_result','pub fn str_bytes(s &string) [3]int { mut a := [3]int{}; << a }','str_bytes'),
        ('array_element','pub fn str_bytes(s &string) []string { mut a := []string{}; << a }','str_bytes'),
        ('private','fn starts_with(s &string, p &string) bool { << false }','starts_with'),
        ('map_hash_arity','pub fn map_hash_int(k int) int { << k }','map_hash_int'),
        ('map_hash_owner','pub fn map_hash_string(k string, seed int) int { << seed }','map_hash_string'),
        ('map_policy_result','pub fn map_insert_action(live int, used int, cap int) bool { << false }','map_insert_action'),
    ]
    with tempfile.TemporaryDirectory(prefix='xu-runtime-abi-') as tmp:
        work=Path(tmp);(work/'main').mkdir();(work/'runtime').mkdir()
        main=work/'main/main.xu';runtime=work/'runtime/mod.xu';binary=work/'program'
        for opt in ('-O0','-O1','-O3'):
            cases=[(name,'@main\nfn main() int { << 0 }\n','@runtime\n'+src+'\n',symbol,None) for name,src,symbol in bad]
            # Module-qualified and fnval paths must encounter the same declaration gate.
            wrong='@runtime\npub fn starts_with(s string, p string) bool { << false }\n'
            cases.extend([
                ('direct','@main\n#runtime\nfn main() int { println(runtime.starts_with("a", "a")); << 0 }\n',wrong,'starts_with',None),
                ('fnval','@main\n#runtime\nfn main() int { f := runtime.starts_with; println(f("a", "a")); << 0 }\n',wrong,'starts_with',None),
                ('missing_map','@main\nfn main() int { mut m := map[int]int{}; m[1] = 2; << 0 }\n','@runtime\npub fn unrelated() int { << 0 }\n','map_mix64',None),
                ('missing_method','@main\nfn main() int { println("a".bytes().len); << 0 }\n','@runtime\npub fn unrelated() int { << 0 }\n','str_bytes',None),
                ('effect_not_permission','@main\nfn main() int { println(is_digit(48)); println(is_digit(48)); << 0 }\n','@runtime\npub fn is_digit(c int) bool { println("effect"); << false }\n',None,'effect\nfalse\neffect\nfalse\n'),
                ('user_override','@main\nfn starts_with(s string, p string) bool { << false }\nfn main() int { println(starts_with("a", "a")); << 0 }\n',None,None,'false\n'),
            ])
            for name,entry,impl,symbol,golden in cases:
                main.write_text(entry.replace("; ", "\n"));inputs=[str(main)]
                if impl is not None:runtime.write_text(impl.replace("; ", "\n"));inputs.append(str(runtime))
                binary.unlink(missing_ok=True)
                cmd=[str(ROOT/'scripts/run_product_compiler.sh'),str(compiler),'build',opt,*inputs,'-o',str(binary)]
                p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=120)
                row=dict(case=name,opt=opt,build_exit=p.returncode,stderr=p.stderr,input_sha256={n:sha(n) for n in inputs})
                if golden is None:
                    expected='runtime.'+symbol+' not found' if name in ('missing_method','missing_map') else 'runtime ABI mismatch: runtime.'+symbol
                    assert p.returncode==1 and expected in p.stderr and not binary.exists(),row
                    assert 'index out of bounds' not in p.stderr and 'internal compiler error' not in p.stderr,row
                else:
                    assert p.returncode==0,row
                    run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
                    assert run.returncode==0 and run.stdout==golden and not run.stderr,(row,run)
                    row.update(stdout=run.stdout,binary_sha256=sha(binary))
                rows.append(row)
    report=dict(status='PASS',compiler=str(compiler),compiler_sha256=sha(compiler),registry_sha256=sha(registry.REGISTRY),results=rows)
    output.write_text(json.dumps(report,indent=2)+'\n');print('PASS:',len(rows),'runtime ABI cases')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--xu',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args();run_gate(a.xu.resolve(),a.out)
