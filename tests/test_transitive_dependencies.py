"""Resolve and freeze explicit-locator module graphs using the product CLI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get('XU', ROOT / 'bin/xu'))


@pytest.fixture
def graph(tmp_path):
    app = tmp_path / 'app'
    app.mkdir()
    env = dict(os.environ, XUPATH='', XU_CACHE=str(tmp_path / 'cache'),
               XU_STDLIB_ROOT=str(ROOT / 'src'))
    for name in ('XUOS', 'XUARCH', 'XU_HEAP_STATS'):
        env.pop(name, None)

    def module(folder, key, value=42, requires=(), dependency=None):
        p = tmp_path / folder
        p.mkdir(parents=True, exist_ok=True)
        decls = ''.join(f'  "{k}": {v}\n' for k,v in requires)
        body = f'module: "{key}"\nversion: !ver 1.0.0\n'
        if requires:
            body += 'require:\n' + decls
        (p / 'xu.xun').write_text(body)
        imports = f'child #"{dependency}"\n' if dependency else ''
        answer = 'child.answer() + 1' if dependency else str(value)
        (p / 'mod.xu').write_text(f'@"{key}"\n{imports}pub fn answer() int {{ << {answer} }}\n')
        return p

    def declare(requires, key):
        (app / 'xu.xun').write_text('module: app\nversion: !ver 0.1.0\nrequire:\n' +
                                  ''.join(f'  "{k}": {v}\n' for k,v in requires))
        (app / 'main.xu').write_text(f'@main\nlib #"{key}"\nfn main() int {{ println(lib.answer())\n << 0 }}\n')

    def invoke(command='build', flags=()):
        args=[str(XU),command,*flags]
        args += [str(app)] if command=='install' else [str(app/'main.xu'),'-o',str(app/'program')]
        return subprocess.run(args,cwd=app,env=env,capture_output=True,text=True,timeout=90)

    def output():
        return subprocess.check_output([str(app/'program')],text=True,timeout=10)

    return tmp_path,app,env,module,declare,invoke,output


def ok(r):
    assert r.returncode==0,r.stdout+r.stderr


@pytest.mark.parametrize('canonical',[False,True])
def test_local_chain_build_install_and_relocated_frozen_closure(graph,canonical):
    root,app,env,module,declare,invoke,output=graph
    keys=[f'example.com/{n}' if canonical else n for n in ('alpha','beta','gamma')]
    a,b,c=keys
    module('gamma',c)
    module('beta',b,requires=[(c,'file:../gamma')],dependency=c)
    module('alpha',a,requires=[(b,'file:../beta')],dependency=b)
    declare([(a,'file:../alpha')],a)
    ok(invoke());assert output()=='44\n'
    ok(invoke('install',['--offline']))
    lock=(app/'xu.lock').read_bytes()
    assert set(line.split()[0] for line in lock.decode().splitlines()[1:])==set(keys)
    for folder in ('alpha','beta','gamma'):shutil.rmtree(root/folder)
    ok(invoke(flags=['--frozen']));assert output()=='44\n'
    relocated=root/'relocated';shutil.copytree(app,relocated)
    r=subprocess.run([str(XU),'build','--frozen',str(relocated/'main.xu'),'-o',str(relocated/'program')],
                     cwd=relocated,env=env,capture_output=True,text=True,timeout=90)
    ok(r)
    assert (app/'xu.lock').read_bytes()==lock
    assert not (root/'cache').exists()


def test_relative_child_is_based_on_selected_package_not_shared_search_root(graph):
    root,app,_,module,declare,invoke,output=graph
    module('providers/beta','beta')
    module('providers/alpha','alpha',requires=[('beta','file:../beta')],dependency='beta')
    declare([('alpha','file:../providers')],'alpha')
    ok(invoke());assert output()=='43\n'
    ok(invoke('install'))
    shutil.rmtree(root/'providers')
    ok(invoke(flags=['--frozen']));assert output()=='43\n'


def test_diamond_deduplicates_one_consistent_source(graph):
    _,app,_,module,declare,invoke,_=graph
    module('common','example.com/common')
    module('left','example.com/left',requires=[('example.com/common','file:../common')])
    module('right','example.com/right',requires=[('example.com/common','file:../common')])
    declare([('example.com/left','file:../left'),('example.com/right','file:../right')],'example.com/left')
    ok(invoke('install'))
    entries=(app/'xu.lock').read_text().splitlines()[1:]
    assert len(entries)==3


@pytest.mark.parametrize('reverse',[False,True])
def test_conflicting_sources_fail_independently_of_declaration_order(graph,reverse):
    _,app,_,module,declare,invoke,_=graph
    module('one','example.com/common',value=1)
    module('two','example.com/common',value=2)
    module('left','example.com/left',requires=[('example.com/common','file:../one')])
    module('right','example.com/right',requires=[('example.com/common','file:../two')])
    edges=[('example.com/left','file:../left'),('example.com/right','file:../right')]
    declare(list(reversed(edges)) if reverse else edges,'example.com/left')
    r=invoke('install')
    assert r.returncode!=0 and 'conflicting dependency sources' in r.stderr,r.stderr
    assert not (app/'vendor').exists()
    assert not (app/'xu.lock').exists()


def test_manifest_cycle_terminates_without_duplicate_lock_entries(graph):
    _,app,_,module,declare,invoke,output=graph
    module('alpha','example.com/alpha',requires=[('example.com/beta','file:../beta')],dependency='example.com/beta')
    module('beta','example.com/beta',requires=[('example.com/alpha','file:../alpha')])
    declare([('example.com/alpha','file:../alpha')],'example.com/alpha')
    ok(invoke('install'));assert len((app/'xu.lock').read_text().splitlines())==3
    ok(invoke(flags=['--frozen']));assert output()=='43\n'


def test_transitive_snapshot_tamper_is_rejected(graph):
    _,app,_,module,declare,invoke,_=graph
    module('beta','example.com/beta')
    module('alpha','example.com/alpha',requires=[('example.com/beta','file:../beta')],dependency='example.com/beta')
    declare([('example.com/alpha','file:../alpha')],'example.com/alpha')
    ok(invoke('install'))
    lock=(app/'xu.lock').read_bytes()
    source=app/'vendor/example.com/beta/mod.xu';source.write_text(source.read_text().replace('42','99'))
    r=invoke(flags=['--frozen'])
    assert r.returncode!=0 and 'checksum' in r.stderr,r.stderr
    assert (app/'xu.lock').read_bytes()==lock


@pytest.mark.parametrize('inject_file',[False,True])
def test_remote_graph_downloads_children_and_vendor_runs_without_tools(graph,inject_file):
    root,app,env,module,declare,invoke,output=graph
    a='example.com/alpha';b='example.com/beta'
    child=module('beta',b)
    locator='file:'+str(child) if inject_file else 'https://invalid.example/beta.tgz'
    parent=module('alpha',a,requires=[(b,locator)],dependency=b)
    archives={}
    for name,source in [('alpha',parent),('beta',child)]:
        archive=root/(name+'.tgz')
        with tarfile.open(archive,'w:gz') as tar:
            for f in source.iterdir():tar.add(f,arcname=f.name)
        archives['https://invalid.example/'+name+'.tgz']=str(archive)
    tools=root/'tools';tools.mkdir()
    curl=tools/'curl'
    curl.write_text('''#!/usr/bin/env python3
import json,os,sys,shutil
with open(os.environ['XU_DEP_LOG'],'a') as f:f.write(json.dumps(sys.argv)+'\\n')
sources=json.loads(os.environ['XU_DEP_ARCHIVES'])
shutil.copyfile(sources[sys.argv[-1]],sys.argv[sys.argv.index('-o')+1])
''');curl.chmod(0o755)
    env.update(PATH=str(tools)+os.pathsep+os.environ['PATH'],XU_DEP_ARCHIVES=json.dumps(archives),XU_DEP_LOG=str(root/'calls'))
    declare([(a,'https://invalid.example/alpha.tgz')],a)
    r=invoke('install')
    if inject_file:
        assert r.returncode!=0 and 'remote module cannot introduce a file:' in r.stderr,r.stderr
        assert len((root/'calls').read_text().splitlines())==1
        return
    ok(r);assert len((root/'calls').read_text().splitlines())==2
    shutil.rmtree(root/'cache');shutil.rmtree(parent);shutil.rmtree(child)
    calls=(root/'calls').read_bytes()
    ok(invoke(flags=['--frozen']));assert output()=='43\n'
    assert (root/'calls').read_bytes()==calls
    assert not (root/'cache').exists()


def test_graph_limit_rejects_before_downloads_or_writes(graph):
    _,app,_,_,declare,invoke,_=graph
    requires=[(f'example.com/m{i}','https://invalid.example/m.tgz') for i in range(257)]
    declare(requires,'example.com/m0')
    r=invoke('install')
    assert r.returncode!=0 and 'exceeds 256 modules' in r.stderr,r.stderr
    assert not (app/'vendor').exists()
    assert not (app/'xu.lock').exists()
