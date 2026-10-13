#!/usr/bin/env python3
"""Independent effect/count oracle for owned I/O outcomes and buffered retry safety."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT/'tests/drivers/io_progress.xu'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def inputs():
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted([*ROOT.joinpath('src').rglob('*.xu'),DRIVER,Path(__file__),ROOT/'scripts/run_product_compiler.sh'])}

def oracle(sm,wm,size,limit):
    off = reads = writes = total = 0; accepted = ''
    def done(tag,count,text='',code=0):
        head=f'C:{count}' if tag=='C' else f'{tag}:{count}:{text}:{code}'
        return [head,'data:'+accepted,f'state:{off}:{reads}:{writes}']
    if limit < -2: return done('F',0,'io: invalid count')
    if limit == -2: size=4096; limit=-1
    elif limit >= 0: size=4096
    if size <= 0: return done('F',0,'io: invalid buffer size')
    while limit < 0 or total < limit:
        request=size if limit < 0 else min(size,limit-total)
        reads+=1
        if sm==6: return done('F',total,'read throw',414)
        if sm==4: return done('F',total,'io: no progress')
        if sm==5:
            data='abcdefg'; terminal=True
        else:
            data='abcdef'[off:off+request];off+=len(data)
            terminal=off==6 and (sm!=0 or not data)
        if len(data)>request: return done('F',total,'io: invalid read count')
        if data:
            writes+=1
            n=len(data) if wm==0 else min(len(data),2)
            accepted+=data[:n]
            if wm in (5,6): return done('U',total,'io: invalid write count')
            if wm==4: return done('U',total,'write throw',424)
            if wm==3: return done('U',total,'unknown write',423)
            if wm==2: return done('F',total+n,'write failure',422)
            total+=n
            if n!=len(data): return done('F',total,'short write')
        if terminal:
            if sm==2: return done('F',total,'read failure',411)
            if sm==3: return done('F',total,'',413)
            if limit>=0 and total<limit: return done('F',total,'EOF')
            return done('C',total)
    return done('C',total)

REJECT = {
 'wrong-reader-return': ('@main\n#io\nstruct Bad {}\nfn (r &mut Bad) read_result(n int) int { << n }\nfn main() { mut r := Bad{}\n mut w := io.buffer()\n io.copy_result(mut &w,mut &r) }','does not satisfy'),
 'wrong-writer-parameter': ('@main\n#io\nstruct Bad {}\nfn (w &mut Bad) write_result(n int) io.WriteResult { << io.WriteResult.Written(n) }\nfn main() { mut r := io.cursor("x")\n mut w := Bad{}\n io.copy_result(mut &w,mut &r) }','does not satisfy'),
 'consumed-outcome': ('@main\n#io\nfn main() { r := io.ReadResult.End("x")\n match r { else {} }\n match r { else {} } }','moved'),
 'borrowed-endpoint': ('@main\n#io\nfn main() { mut r := io.cursor("x")\n a := &r\n mut w := io.buffer()\n io.copy_result(mut &w,mut &r)\n println(a.size()) }','borrow'),
 'invented-qualifier': ('@main\n#io\nfn main() { r := io.bogus.ReadResult.End("x") }','undefined'),
 'wrong-enum-module': ('@main\n#io\n#os\nfn main() { r := io.ReadResult.End("x")\n match r { os.ReadResult.End(x) {}\n else {} } }','does not match'),
}

BORROW_ERROR='@main\n#io\n#errors\nstruct BorrowErr { ptr &int }\nfn (e BorrowErr) msg() string { << str(*e.ptr) }\n'
REJECT.update({
 'borrowed-error-result':(BORROW_ERROR+'fn fail() io.ReadResult { x := 7\n err := BorrowErr{ptr:&x}\n << io.ReadResult.Failed("",err) }\nfn main() { _ := fail() }','reference'),
 'borrowed-error-box':(BORROW_ERROR+'fn fail() errors.Error { x := 7\n << errors.Error(BorrowErr{ptr:&x}) }\nfn main() { _ := fail() }','reference'),
 'borrowed-error-throw':(BORROW_ERROR+'fn fail() int { x := 7\n err := BorrowErr{ptr:&x}\n >> err }\nfn main() int { fail() or (err) { << 0 }\n << 1 }','reference'),
})

THROW_MSG='@main\n#io\n#errors\nstruct BadError { code int }\nfn (e BadError) msg() string { >> errors.new("bad msg") }\n'
REJECT.update({
 'dynamic-reference-receiver':('@main\n#errors\nstruct E { code int }\nfn (e &E) msg() string { << "ref" }\nfn main() { _ := errors.Error(E{code:1}) }','receiver'),
 'dynamic-mutable-receiver':('@main\n#io\nfn main() { _ := io.ProgressReader(io.cursor("x")) }','receiver'),
 'dynamic-reference-result':('@main\nstruct@ View { fn get(&int) &int }\nstruct E { code int }\nfn (e E) get(x &a int) &a int { << x }\nfn main() { _ := View(E{code:1}) }','reference result'),
 'shadowed-error-signature':('@main\n#errors\nstruct@ Error { fn msg() int }\nstruct Bad { code int }\nfn (e Bad) msg() int { << e.code }\nfn main() { _ := errors.Error(Bad{code:1}) }','incompatible signature'),
 'throwing-error-box':(THROW_MSG+'fn main() { e := errors.Error(BadError{code:1}) }','may throw'),
 'throwing-error-result':(THROW_MSG+'fn main() { e := io.ReadResult.Failed("",BadError{code:1}) }','may throw'),
 'throwing-error-throw':(THROW_MSG+'fn fail() int { >> BadError{code:1} }\nfn main() int { fail() or (err) { << 0 }\n << 1 }','may throw'),
})

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--developer',action='store_true');ap.add_argument('--skip-net',action='store_true')
    args=ap.parse_args();xu=args.xu.resolve()
    report=dict(compiler=str(xu),compiler_sha256=sha(xu),input_sha256=inputs(),lane='developer' if args.developer else 'product',results=[])
    prefix=[xu] if args.developer else [ROOT/'scripts/run_product_compiler.sh',xu]
    def run(cmd,env=None,cwd=ROOT): return subprocess.run(list(map(str,cmd)),cwd=cwd,capture_output=True,text=True,timeout=180,env=env)
    def record(case,opt,p,expected,**detail):
        ok=p.returncode==0 and p.stdout.splitlines()==expected
        report['results'].append(dict(case=case,mode=opt,passed=ok,exit=p.returncode,stdout=p.stdout,stderr=p.stderr,expected=expected,**detail))
        if not ok: print('FAIL',case,opt,p.stdout,p.stderr,flush=True)
    with tempfile.TemporaryDirectory(prefix='xu-io-progress-') as td:
        td=Path(td)
        for opt in ('-O0','-O3'):
            binary=td/'driver'
            compiled=run([*prefix,'build',DRIVER,opt,'-o',binary],env=dict(os.environ,XU_GEN1_HEAP_LEDGER='1'))
            if compiled.returncode: raise RuntimeError(compiled.stderr)
            matrix=[(sm,wm,size,-1) for sm,wm,size in itertools.product(range(7),range(7),(1,3,8))]
            matrix += [(sm,wm,3,n) for sm,wm,n in itertools.product((0,1,2,3),(0,2,3),(0,2,6,9))]
            matrix += [(1,0,0,-1),(1,0,-1,-1),(1,0,1,-3),(1,0,1,-2)]
            for sm,wm,size,n in matrix:
                record(f'copy-{sm}-{wm}-{size}-{n}',opt,run([binary,'copy',sm,wm,size,n]),oracle(sm,wm,size,n))
            checks={
              'reader':(['reader'],['D:','F::bufio: invalid count:0','D:a','5','D:bc','F:def:read failure:411','F::read failure:0','1','E:abcdef']),
              'reader-throw':(['reader-throw'],['F::read throw:414','F::read throw:0','1']),
              'throws':(['throws'],['factory:431','literal:432','local:433','boxed:434','arm:435','factory:431']),
              'nested':(['nested'],['F:6:read failure:411','abcdef']),
              'flush':(['flush'],['W:3','F:2:write failure:422','pending:c','ab']),
              'legacy':(['legacy'],['U:0:legacy partial:425','ab']),
              'bytes':(['bytes'],['C:3','abc','E:def']),
              'file':(['file',str(td/'file')],['W:12','F:0:os: file is closed:0','C:12','file payload','F::os: file is closed:0']),
            }
            for wm in (1,2,3,4,5,6):
                text,code={1:('short write',0),2:('write failure',422),3:('unknown write',423),4:('write throw',424),5:('bufio: invalid write count',0),6:('bufio: invalid write count',0)}[wm]
                pending='cd' if wm in (1,2) else 'abcd'
                checks[f'writer-{wm}']=(['writer',wm],[f'F:4:{text}:{code}','pending:'+pending,'data:ab',f'F:0:{text}:0',f'F:0:{text}:0','W:0','1','W:2','W:2','xy'])
            for name,(argv,expected) in checks.items(): record(name,opt,run([binary,*argv]),expected)
            imported=td/'imported.xu'; imported.write_text('@main\n#bufio\nfn main() { println("imported") }\n')
            for stats_mode in ('0','1'):
                p=run([*prefix,'build',imported,opt,'-o',td/'imported'],env=dict(os.environ,XU_GEN1_MAP_STATS=stats_mode))
                if p.returncode: record('import-only-bufio-'+stats_mode,opt,p,['imported'])
                else: record('import-only-bufio-'+stats_mode,opt,run([td/'imported']),['imported'])
            dynamic=td/'dynamic.xu'
            dynamic.write_text('@main\n#io\nstruct Reader { data string }\nfn (r Reader) read_result(n int) io.ReadResult { << io.ReadResult.End(r.data + "") }\nfn main() { value := io.ProgressReader(Reader{data:"dynamic"})\n result := value.read_result(9)\n match result { io.ReadResult.End(data) { println(data) }\n else {} } }\n')
            p=run([*prefix,'build',dynamic,opt,'-o',td/'dynamic'])
            if p.returncode: record('dynamic-result',opt,p,['dynamic'])
            else: record('dynamic-result',opt,run([td/'dynamic']),['dynamic'])
            shadow=td/'shadow.xu'
            shadow.write_text('@main\n#errors\nstruct@ Error { fn other() int }\nfn main() { value := errors.Error(errors.code(1,"shadow"))\n println(value.msg()) }\n')
            p=run([*prefix,'build',shadow,opt,'-o',td/'shadow'])
            if p.returncode: record('qualified-error-interface',opt,p,['shadow'])
            else: record('qualified-error-interface',opt,run([td/'shadow']),['shadow'])
            alias=td/'alias.xu'
            alias.write_text('@main\n#io as flow\nfn main() { value := flow.ReadResult.End("alias")\n match value { flow.ReadResult.End(data) { println(data) }\n else {} } }\n')
            p=run([*prefix,'build',alias,opt,'-o',td/'alias'])
            if p.returncode: record('enum-alias',opt,p,['alias'])
            else: record('enum-alias',opt,run([td/'alias']),['alias'])
            cross=td/'cross'; secret=cross/'src/secret';secret.mkdir(parents=True,exist_ok=True)
            (secret/'mod.xu').write_text('@secret\npub enum Public { Value(string) }\nenum Hidden { Value(string) }\npub fn hidden() Hidden { << Hidden.Value("hidden") }\n')
            visibility={
              'public-enum':('@main\n#secret\nfn main() { value := secret.Public.Value("public")\n match value { secret.Public.Value(data) { println(data) }\n else {} } }',['public']),
              'private-constructor':('@main\n#secret\nfn main() { value := secret.Hidden.Value("hidden") }','private'),
              'private-short-pattern':('@main\n#secret\nfn main() { value := secret.hidden()\n match value { Hidden.Value(data) {}\n else {} } }','private'),
              'private-pattern':('@main\n#secret\nfn main() { value := secret.hidden()\n match value { secret.Hidden.Value(data) {}\n else {} } }','private'),
            }
            for name,(source,expected) in visibility.items():
                path=cross/'main.xu';path.write_text(source)
                p=run([*prefix,'build',path,secret/'mod.xu',opt,'-o',cross/'test'],cwd=cross)
                if isinstance(expected,list):
                    if p.returncode: record(name,opt,p,expected)
                    else: record(name,opt,run([cross/'test']),expected)
                else: report['results'].append(dict(case=name,mode=opt,passed=p.returncode!=0 and expected in p.stderr,exit=p.returncode,stderr=p.stderr))
            baseline=None
            for count in (0,2,1000):
                p=run([binary,'ledger',str(count).zfill(4)],env=dict(os.environ,XU_HEAP_STATS='1'))
                stats={k:int(v) for k,v in re.findall(r'xu_heap_stats (\w+)=(\d+)',p.stderr)}
                if baseline is None: baseline=stats
                ok=len(stats)==7 and all(stats[k]==0 for k in ('unknown_frees','double_frees','ledger_overflows')) and stats['live_bytes']==baseline['live_bytes'] and stats['allocs']-stats['frees']==baseline['allocs']-baseline['frees']
                record('heap-'+str(count),opt,p,[str(count//2)],ledger=stats,balanced=ok)
                if not ok: report['results'][-1]['passed']=False
            for name,(source,error) in REJECT.items():
                path=td/(name+'.xu');path.write_text(source)
                p=run([*prefix,'build',path,opt,'-o',td/'reject'])
                report['results'].append(dict(case=name,mode=opt,passed=p.returncode!=0 and error in p.stderr,exit=p.returncode,stderr=p.stderr))
            if not args.skip_net:
                with socket.socket() as listener:
                    listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(5)
                    observed={}
                    def serve():
                        with listener.accept()[0] as peer:
                            peer.settimeout(5);data=b''
                            while len(data)<7:
                                chunk=peer.recv(7-len(data))
                                if not chunk: raise RuntimeError('premature client EOF')
                                data+=chunk
                            observed['request']=data.decode();peer.sendall(b'native reply');peer.shutdown(socket.SHUT_WR)
                            observed['eof']=peer.recv(1)==b''
                    thread=threading.Thread(target=serve);thread.start()
                    p=run([binary,'tcp',f'127.0.0.1:{listener.getsockname()[1]}']);thread.join(6)
                    record('tcp',opt,p,['W:7','C:12','native reply'],server=observed)
                    if thread.is_alive() or observed!={'request':'request','eof':True}: report['results'][-1]['passed']=False
            print('finished',opt,flush=True)
    report['input_changed']=report['input_sha256']!=inputs();report['compiler_changed']=report['compiler_sha256']!=sha(xu)
    failures=sum(not r['passed'] for r in report['results'])
    report['status']='PASS' if not failures and not report['input_changed'] and not report['compiler_changed'] else 'FAIL'
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(report['status'],len(report['results']),'checks,',failures,'failures')
    return report['status']!='PASS'
if __name__=='__main__': raise SystemExit(main())
