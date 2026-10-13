#!/usr/bin/env python3
"""Real CLI regression for checked integer-record leaf methods and fallbacks."""
from pathlib import Path
from collections import OrderedDict
import argparse, hashlib, json, os, platform, random, re, subprocess, tempfile

ROOT = Path(__file__).resolve().parents[1]
MODES = {'O0':['-O0'], 'O1':['-O1'], 'O2':['-O2'], 'O3':['-O3'],
         'no-regcache':['-O3','--no-regcache'], 'ra0':['-O3','--ra=0']}

def lru_case():
    original = (ROOT / 'tests/data/compiler_workloads/lru_cache.xu').read_text()
    prefix = original[:original.index('fn main()')]
    functions, gold = [], []
    for c in (1, 7, 17):
        rng = random.Random(20261007 + c)
        ops, keys, values = [], [], []
        order = OrderedDict()
        nodes = [[-1,0,-1,-1] for _ in range(c)]
        table = [-1] * 43
        count = 0
        for _ in range(240):
            put = rng.randrange(4) != 0
            key, value = rng.randrange(43), rng.randrange(-1000000,1000001)
            ops.append(int(put)); keys.append(key); values.append(value)
            if put:
                if key in order:
                    idx = order.pop(key)
                elif count < c:
                    idx = count; count += 1
                else:
                    oldkey, idx = order.popitem(last=True)
                    table[oldkey] = -1
                nodes[idx][0:2] = [key,value]
                table[key] = idx
                order[key] = idx; order.move_to_end(key,last=False)
                result = value
            elif key in order:
                idx = order.pop(key)
                result = nodes[idx][1]
                order[key] = idx; order.move_to_end(key,last=False)
            else:
                result = -1
            queue = list(order.values())
            for j, idx in enumerate(queue):
                nodes[idx][2:] = [queue[j-1] if j else -1,queue[j+1] if j+1<len(queue) else -1]
            gold += [result,queue[0] if queue else -1,queue[-1] if queue else -1,count]
            gold += [v for n in nodes for v in n]
            gold += table
        arr = lambda a: '[' + ','.join(map(str,a)) + ']'
        functions.append(f'''fn run{c}() {{
    mut l := new_lru({c},43)
    ops := {arr(ops)}
    keys := {arr(keys)}
    vals := {arr(values)}
    for i in 0:ops.len {{
        if ops[i] == 1 {{ println(l.put(keys[i],vals[i])) }}
        else {{ println(l.get(keys[i])) }}
        println(l.head)
        println(l.tail)
        println(l.count)
        for j in 0:l.nodes.len {{
            println(l.nodes[j].key)
            println(l.nodes[j].val)
            println(l.nodes[j].prev)
            println(l.nodes[j].next)
        }}
        for j in 0:l.table.len {{ println(l.table[j]) }}
    }}
}}
''')
    return prefix + '\n'.join(functions) + 'fn main() int {\nrun1()\nrun7()\nrun17()\n<< 0\n}\n', ('\n'.join(map(str,gold))+'\n').encode()

def cases():
    alias = '''@main
struct Record { pub x int pub y int }
struct Bag { pub a []Record pub n int }
fn (b &mut Bag) step(i int,j int,x int) int {
    before := b.a[i].x
    b.a[j].x = before + x
    b.a[i].y = b.a[j].x - before
    b.n = b.n + b.a[i].y
    << b.a[i].x + b.a[i].y + b.n
}
fn main() int {
    mut b := Bag{a:[Record{x:3,y:0},Record{x:7,y:0}],n:0}
    for i in 0:100 { println(b.step(i % 2,(i / 3) % 2,i - 50)) }
    << 0
}
'''
    a,n,gold = [[3,0],[7,0]],0,[]
    for k in range(100):
        i,j,x = k%2,(k//3)%2,k-50
        before = a[i][0]; a[j][0] = before+x; a[i][1] = a[j][0]-before
        n += a[i][1]; gold.append(a[i][0]+a[i][1]+n)
    generic = alias.replace('struct Bag {','struct Bag#T {').replace('[]Record pub','[]T pub').replace('&mut Bag)', '&mut Bag#Record)').replace('Bag{a:', 'Bag#Record{a:')
    fallback = '''@main
struct Record { pub x int pub y int }
struct Bag { pub a []Record pub n int }
fn grow(b &mut Bag,n int) {
    if n > 0 { grow(b,n - 1) }
    else { b.a.push(Record{x:17,y:23}) }
}
fn (b &mut Bag) step(x int) int {
    old := b.a[0].x
    grow(b,x)
    b.a[0].x = old + b.a[b.a.len - 1].y
    << b.a[0].x
}
fn main() int {
    mut b := Bag{a:[Record{x:1,y:2}],n:0}
    for i in 0:40 { println(b.step(i % 3)) }
    << 0
}
'''
    bounds = '''@main
struct Record { pub x int pub y int }
struct Bag { pub a []Record pub n int }
fn (b &mut Bag) step(i int) int {
    v := b.a[i].x
    b.a[0].y = v
    << v
}
fn main() int {
    mut b := Bag{a:[Record{x:7,y:11}],n:0}
    println(b.step(INDEX))
    << 0
}
'''
    lru,g = lru_case()
    expected = ('\n'.join(map(str,gold))+'\n').encode()
    owning = alias.replace('pub x int pub y int }','pub x int pub y int pub s string }')
    owning = owning.replace('Record{x:3,y:0}', 'Record{x:3,y:0,s:"left"}').replace('Record{x:7,y:0}', 'Record{x:7,y:0,s:"right"}')
    fields = ''.join(' pub f'+str(i)+' int' for i in range(15))
    initial = ''.join(',f'+str(i)+':0' for i in range(15))
    wide = alias.replace('pub x int pub y int }','pub x int pub y int'+fields+' }')
    wide = wide.replace('Record{x:3,y:0}', 'Record{x:3,y:0'+initial+'}').replace('Record{x:7,y:0}', 'Record{x:7,y:0'+initial+'}')
    return {'random-lru':(lru,g,True), 'same-array-alias':(alias,expected,True),
            'generic-records':(generic,expected,True),
            'owning-record':(owning,expected,False), 'wide-record':(wide,expected,False),
            'unknown-grow-call':(fallback,('\n'.join(str(1+23*(i+1)) for i in range(40))+'\n').encode(),False),
            'negative-index':(bounds.replace('INDEX','-1'),None,True),
            'upper-index':(bounds.replace('INDEX','1'),None,True)}

def run(xu,out,modes,require_admission=True):
    out.mkdir(parents=True,exist_ok=True)
    rows = []
    for name,(source,gold,admission) in cases().items():
        path = out/(name+'.xu'); path.write_text(source)
        for mode in modes:
            binary = out/(name+'-'+mode)
            argv = [str(ROOT/'scripts/run_product_compiler.sh'),str(xu),'build',str(path),*MODES[mode],'--timings','-o',str(binary)]
            p = subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=120)
            log = p.stdout+p.stderr; (out/(binary.name+'.build.log')).write_bytes(log)
            assert p.returncode == 0,(name,mode,log.decode(errors='replace'))
            stats = re.search(rb'ra-stats:.*?try=(\d+) vreg=(\d+)',log)
            assert stats,(name,mode,'no RA stats')
            tried,planned = map(int,stats.groups())
            p = subprocess.run([str(binary)],capture_output=True,timeout=30)
            (out/(binary.name+'.stdout')).write_bytes(p.stdout)
            (out/(binary.name+'.stderr')).write_bytes(p.stderr)
            if gold is None:
                assert p.returncode != 0 and b'index' in (p.stdout+p.stderr).lower(),(name,mode,p)
            else:
                assert p.returncode == 0 and p.stdout == gold and not p.stderr,(name,mode,p.returncode,p.stdout[-200:],p.stderr)
            if require_admission and admission and mode in ('O2','O3'):
                assert tried > 0 and planned > 0,(name,mode,'record container plan refused')
            if name in ('unknown-grow-call','owning-record','wide-record') and mode in ('O2','O3'):
                assert tried == 0 and planned == 0,(name,mode,'unknown call entered leaf admission')
            rows.append(dict(case=name,mode=mode,tried=tried,planned=planned,returncode=p.returncode,
                             stdout_sha256=hashlib.sha256(p.stdout).hexdigest(),argv=argv))
    report = dict(status='PASS',rows=rows)
    (out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

def test_record_container_ra():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        import pytest
        pytest.skip('native ARM64 record container regression')
    with tempfile.TemporaryDirectory(prefix='xu-record-container-') as tmp:
        run(Path(os.environ.get('XU',ROOT/'bin/xu')).resolve(),Path(tmp),['O3'])

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu',type=Path,default=ROOT/'bin/xu')
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--modes',default=','.join(MODES))
    ap.add_argument('--no-admission',action='store_true')
    args = ap.parse_args()
    print(json.dumps(run(args.xu.resolve(),args.out.resolve(),args.modes.split(','),not args.no_admission),indent=2))
