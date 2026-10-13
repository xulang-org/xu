#!/usr/bin/env python3
"""Resource ownership, cleanup layout and native descriptor reuse conformance."""
import argparse
from collections import Counter
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOKEN = '''@main
struct Token { id int }
fn (r &mut Token) drop() { println(r.id) }
'''
CASES = {
    'recursive-container': ('@main\nstruct Node { kids []Node }\nfn main() { ns := [Node{kids:[]Node{}}]\n println(ns.len) }', ['1']),
    'move': (TOKEN + 'fn main() { a := Token{id:7}\n b := a\n println(b.id) }', ['7', '7']),
    'array': (TOKEN + 'fn main() { xs := [Token{id:3},Token{id:4}]\n println(xs.len) }', ['2','3','4']),
    'array-replace': (TOKEN + 'fn main() { mut xs := [Token{id:1},Token{id:2}]\n xs[0] = Token{id:3}\n println(xs.len) }', ['1','2','2','3']),
    'generic': (TOKEN + 'struct Box#T { item T }\nfn main() { b := Box#Token{item:Token{id:5}}\n println(b.item.id) }', ['5','5']),
    'map': (TOKEN + 'fn main() { mut xs := map[int]Token{}\n xs[1] = Token{id:1}\n xs[1] = Token{id:2}\n xs[2] = Token{id:3}\n xs.delete(1)\n t := xs.take(2)\n println(t.id) }', ['1','2','3','3']),
    'nested': (TOKEN + 'struct Outer { item Token\n tag int }\nfn (r &mut Outer) drop() { println(r.tag) }\nfn main() { xs := [Outer{item:Token{id:1},tag:11}, Outer{item:Token{id:2},tag:12}] }', ['11','1','12','2']),
    'wide-layout': ('@main\nstruct Token { id int\n text string }\nfn (r &mut Token) drop() { println(r.id)\n println(r.text) }\nfn main() { xs := [Token{id:3,text:"hi"},Token{id:4,text:"bye"}]\n println(xs.len) }', ['2','3','hi','4','bye']),
    'boxed': (TOKEN + 'fn main() { let e: temp = Token{id:6} }', ['6']),
    'boxed-array': (TOKEN + 'fn main() { let a: temp = Token{id:21}\n let b: temp = Token{id:22}\n xs := [a,b] }', ['21','22']),
    'enum-unused': (TOKEN + 'enum Opt { Empty\n Full(Token) }\nfn main() { e := Opt.Full(Token{id:23}) }', ['23']),
    'enum-ignored-binding': (TOKEN + 'enum Opt { Empty\n Full(Token) }\nfn main() { e := Opt.Full(Token{id:35})\n match e { Opt.Empty {}\n Opt.Full(_) {} } }', ['35']),
    'enum-else': (TOKEN + 'enum Opt { Empty\n Full(Token) }\nfn main() { e := Opt.Full(Token{id:36})\n match e { else {} } }', ['36']),
    'enum-else-return': (TOKEN + 'enum Opt { Empty\n Full(Token) }\nfn work() { e := Opt.Full(Token{id:37})\n match e { else { << } } }\nfn main() { work() }', ['37']),
    'discard-result': (TOKEN + 'fn produce() Token { << Token{id:25} }\nfn main() { produce()\n Token{id:26} }', ['25','26']),
    'return-transfer': (TOKEN + 'fn produce() Token { t := Token{id:24}\n << t }\nfn consume(t Token) { println(t.id) }\nfn main() { t := produce()\n consume(t) }', ['24','24']),
    'enum': (TOKEN + 'enum Opt { Empty\n Full(Token) }\nfn main() { e := Opt.Full(Token{id:8})\n match e { Opt.Empty { println(0) }\n Opt.Full(t) { println(t.id) } } }', ['8','8']),
    'closure': (TOKEN + 'fn main() { t := Token{id:9}\n f := fn() { println(t.id) }\n f() }', ['9','9']),
    'error-unwind': (TOKEN.replace('@main', '@main\n#errors') + 'fn work() int { t := Token{id:10}\n >> errors.new("stop") }\nfn main() int { work() or (err) { println(99)\n << 0 }\n << 1 }', ['10','99']),
    'free-drop': ('@main\n#errors\nfn drop() { println(42) }\nfn main() { drop() }', ['42']),
}
REJECT = {
    'erased-closure-argument': (TOKEN + 'fn consume(f fn() int) { println(f()) }\nfn main() { t := Token{id:27}\n f := fn() int { << t.id }\n consume(f) }', 'cannot erase'),
    'erased-borrowed-closure': (TOKEN + 'fn produce() fn() int { t := Token{id:29}\n r := &t\n << fn() int { << r.id } }\nfn main() { f := produce()\n println(f()) }', 'cannot erase a borrowed'),
    'erased-closure-return': (TOKEN + 'fn produce() fn() int { t := Token{id:28}\n << fn() int { << t.id } }\nfn main() { f := produce()\n println(f()) }', 'cannot erase'),
    'partial-box-field': ('@main\nstruct Holder { e temp\n id int }\nfn (r &mut Holder) drop() { println(r.id) }\nfn main() { h := Holder{e:1,id:8}\n x := h.e as int\n println(x) }', 'cannot partially move'),
    'fixed-resource': (TOKEN + 'fn main() { xs := [2]Token{Token{id:1},Token{id:2}} }', 'fixed arrays containing resource'),
    'fixed-nested-resource': (TOKEN + 'struct Box { items []Token }\nfn main() { xs := [1]Box{Box{items:[Token{id:1}]}} }', 'fixed arrays containing resource'),
    'owning-slice': (TOKEN + 'fn main() { xs := [Token{id:1},Token{id:2}]\n ys := xs[0:1] }', 'non-string owning'),
    'owning-index-copy': (TOKEN + 'fn main() { xs := [Token{id:1}]\n x := xs[0] }', 'owning'),
    'enum-copy': (TOKEN + 'enum Opt { Full(Token) }\nfn main() { a := Opt.Full(Token{id:1})\n b := a\n match a { Opt.Full(t) { println(t.id) } } }', 'moved'),
    'closure-copy': (TOKEN + 'fn main() { t := Token{id:1}\n f := fn() { println(t.id) }\n g := f\n f() }', 'moved'),
    'move-use': (TOKEN + 'fn main() { a := Token{id:1}\n b := a\n println(a.id) }', 'moved'),
    'manual-drop': (TOKEN + 'fn main() { mut a := Token{id:1}\n a.drop() }', 'compiler-managed'),
    'drop-value': (TOKEN + 'fn main() { mut a := Token{id:1}\n f := a.drop\n f() }', 'compiler-managed'),
    'bad-receiver': ('@main\nstruct Token { id int }\nfn (r Token) drop() {}\nfn main() {}', 'concrete &mut'),
    'bad-args': ('@main\nstruct Token { id int }\nfn (r &mut Token) drop(n int) {}\nfn main() {}', 'concrete &mut'),
    'bad-result': ('@main\nstruct Token { id int }\nfn (r &mut Token) drop() int { << 0 }\nfn main() {}', 'concrete &mut'),
    'throwing-drop': ('@main\n#os\nstruct Token { id int }\nfn (r &mut Token) drop() { os.remove("missing") or >> }\nfn main() {}', 'cannot propagate'),
    'generic-drop': ('@main\nstruct Token#T { id T }\nfn (r &mut Token#T) drop() {}\nfn main() {}', 'generic structs'),
    'mixed-packed-drop': ('@main\nstruct Token { lo byte\n hi byte\n id int }\nfn (r &mut Token) drop() {}\nfn main() {}', 'word-aligned'),
    'nested-packed-drop': ('@main\nstruct Packed { lo byte\n hi byte\n id int }\nstruct Token { inner Packed\n tag int }\nfn (r &mut Token) drop() {}\nfn main() {}', 'word-aligned'),
    'packed-drop': ('@main\nstruct Token { id byte }\nfn (r &mut Token) drop() {}\nfn main() {}', 'word-aligned'),
    'zero-file': ('@main\n#os\nfn main() { f := os.File{} }', 'requires a constructor'),
    'private-http-fd': ('@main\n#net/http\nfn main() { mut c := http.new_client()\n c.idle_fd = 1 }', 'private'),
    'private-file': ('@main\n#os\nfn main() { f := os.File{fd:1} }', 'private'),
    'file-copy': ('@main\n#os\nfn main() int { a := os.open("/dev/null") or (err) { << 1 }\n b := a\n println(a.descriptor() or (err) { << 2 })\n << 0 }', 'moved'),
    'borrow-close': ('@main\n#os\nfn main() int { mut a := os.open("/dev/null") or (err) { << 1 }\n r := &a\n a.close() or (err) { << 2 }\n println(r.descriptor() or (err) { << 3 })\n << 0 }', 'borrow'),
}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--developer', action='store_true', help='Exploratory candidate; not product evidence')
    args = ap.parse_args(); xu = args.xu.resolve()
    inputs = list((ROOT/'src').rglob('*.xu')) + [Path(__file__)]
    report = dict(compiler=str(xu), compiler_sha256=digest(xu), lane='developer' if args.developer else 'product', input_sha256={str(p.relative_to(ROOT)):digest(p) for p in sorted(inputs)}, results=[])
    def run(cmd, env=None):
        return subprocess.run(list(map(str, cmd)), cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    def record(name, opt, ok, **detail):
        report['results'].append(dict(case=name, optimization=opt, passed=ok, **detail))
        print(('PASS' if ok else 'FAIL')+' '+name+' '+opt, flush=True)
    with tempfile.TemporaryDirectory(prefix='xu-resource-conformance-') as td:
        tmp = Path(td)
        native = '''@main
#os
#errors
fn opened(path string, fail bool) int {
 mut f := os.create(path) or >>
 f.write("x") or >>
 if fail { >> errors.new("injected") }
 << 0
}
fn failed_close(f &mut os.File) int { f.close() or (err) { << 1 }
 << 0 }
fn fds() int { xs := os.entries("/dev/fd") or >>
 << xs.len }
fn main() int {
 path := "__PATH__"
 before := fds() or (err) { << 1 }
 for _ in 0:1000 {
  opened(path + "", false) or (err) { << 2 }
  opened(path + "", true) or (err) { -> }
 }
 after := fds() or (err) { << 3 }
 println(before == after)
 mut f := os.create(path + "") or (err) { << 4 }
 fd := f.descriptor() or (err) { << 5 }
 f.close() or (err) { << 6 }
 mut g := os.create(path + "") or (err) { << 7 }
 println(fd == (g.descriptor() or (err) { << 8 }))
 f.close() or (err) { << 9 }
 println((g.write("safe") or (err) { << 10 }) == 4)
 // Fault injection: close the borrowed raw fd behind its owner, then
 // ensure a failed explicit close cannot later close a reused descriptor.
 gfd := g.descriptor() or (err) { << 11 }
 os_fd_close(gfd) or (err) { << 12 }
 println(failed_close(mut &g) == 1)
 mut h := os.create(path + "") or (err) { << 13 }
 println(gfd == (h.descriptor() or (err) { << 14 }))
 g.close() or (err) { << 15 }
 println((h.write("safe") or (err) { << 16 }) == 4)
 h.close() or (err) { << 17 }
 os.remove(path) or (err) { << 12 }
 << 0
}
'''.replace('__PATH__',str(tmp/'native-file'))
        cases = dict(CASES)
        if run(['uname','-s']).stdout.strip() in ('Darwin','Linux'):
            cases['native-fd-reuse'] = (native, ['true']*6)
        for opt in ('O0','O3'):
            for name, (source, expected) in list(cases.items()) + list(REJECT.items()):
                src=tmp/(name+'.xu'); src.write_text(source); binary=tmp/name
                prefix=[xu] if args.developer else [ROOT/'scripts/run_product_compiler.sh',xu]
                compiled=run(prefix+['build',src,'-'+opt,'-o',binary])
                if name in REJECT:
                    ok=compiled.returncode != 0 and expected in compiled.stderr and 'panic' not in compiled.stderr and 'index out of bounds' not in compiled.stderr
                    record(name,opt,ok,compile_exit=compiled.returncode,stderr=compiled.stderr)
                else:
                    p=run([binary]) if compiled.returncode == 0 else compiled
                    ok=compiled.returncode == 0 and p.returncode == 0 and (Counter(p.stdout.splitlines()) == Counter(expected) if name in ('map','array-replace') else p.stdout.splitlines() == expected)
                    record(name,opt,ok,compile_exit=compiled.returncode,run_exit=p.returncode,stdout=p.stdout,stderr=compiled.stderr+p.stderr)
            ledger_source = """@main
#errors
struct Token { id int
 text string }
fn (t &mut Token) drop() {}
enum Opt { Empty
 Full(Token) }
fn exercise(k int, fail bool) int {
 xs := [Token{id:k,text:"array"+str(k)},Token{id:k,text:"array2"+str(k)}]
 mut m := map[int]Token{}
 m[k] = Token{id:k,text:"map"+str(k)}
 m[k] = Token{id:k,text:"replace"+str(k)}
 m.delete(k)
 e := Opt.Full(Token{id:k,text:"enum"+str(k)})
 match e { Opt.Empty {}
  Opt.Full(t) { _ := t.text.len } }
 ignored := Opt.Full(Token{id:k,text:"ignored"+str(k)})
 match ignored { else {} }
 let box: temp = Token{id:k,text:"box"+str(k)}
 Token{id:k,text:"discarded"+str(k)}
 t := Token{id:k,text:"closure"+str(k)}
 f := fn() int { << t.text.len }
 f()
 if fail { >> errors.new("injected") }
 << 1
}
fn main() int {
 mut hits := 0
 for i in 0:COUNT {
  hits += exercise(i,false) or (err) { << 1 }
  exercise(i,true) or (err) { hits += 1
   -> }
 }
 println(hits)
 << 0
}
"""
            baseline = None
            for count in (0,1,1000):
                src=tmp/'ledger.xu';src.write_text(ledger_source.replace('COUNT',str(count)))
                binary=tmp/'ledger'
                env=dict(os.environ,XU_GEN1_HEAP_LEDGER='1')
                compiled=run(prefix+['build',src,'-'+opt,'-o',binary],env)
                p=run([binary],dict(os.environ,XU_HEAP_STATS='1')) if compiled.returncode==0 else compiled
                ledger={}
                for line in p.stderr.splitlines():
                    match=re.fullmatch(r'xu_heap_stats ([a-z_]+)=([0-9]+)',line)
                    if match:ledger[match[1]]=int(match[2])
                valid=len(ledger)==7 and all(ledger.get(k,-1)==0 for k in ('unknown_frees','double_frees','ledger_overflows'))
                if baseline is None:baseline=ledger
                ok=compiled.returncode==0 and p.returncode==0 and p.stdout==str(count*2)+'\n' and valid and ledger.get('live_bytes')==baseline.get('live_bytes') and ledger.get('allocs',0)-ledger.get('frees',0)==baseline.get('allocs',0)-baseline.get('frees',0)
                record('heap-ledger-'+str(count),opt,ok,compile_exit=compiled.returncode,run_exit=p.returncode,stdout=p.stdout,stderr=compiled.stderr+p.stderr,ledger=ledger)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    return 0 if all(r['passed'] for r in report['results']) else 1

if __name__=='__main__':
    raise SystemExit(main())
