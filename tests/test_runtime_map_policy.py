#!/usr/bin/env python3
"""Actual native-map probes, occupancy and owning-ledger gate for a hosted compiler."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEAP = {'live_bytes', 'peak_bytes', 'allocs', 'frees', 'unknown_frees', 'double_frees', 'ledger_overflows'}
FIELDS = {'live', 'used', 'deleted', 'capacity', 'searches', 'probes', 'max_probe', 'grows', 'compacts', 'used_recorded', 'deleted_recorded'}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def parse(stderr):
    maps, current, bucket, heap = [], None, None, {}
    for line in stderr.splitlines():
        m = re.fullmatch(r'xu_map_stats ([a-z_]+)=([0-9]+)', line)
        if m:
            key, value = m[1], int(m[2])
            if key == 'begin':
                if current is not None or value != 1: raise ValueError(line)
                current = {'histogram': {}}
            elif key == 'end':
                if current is None or bucket is not None or value != 1: raise ValueError(line)
                if set(current) != FIELDS | {'histogram'}: raise ValueError(current)
                hist = current['histogram']
                if sum(hist.values()) != current['searches']: raise ValueError(current)
                if current['max_probe'] <= 4096 and sum(k*v for k,v in hist.items()) != current['probes']: raise ValueError(current)
                if current['used'] != current['live'] + current['deleted']: raise ValueError(current)
                for pct in (50, 99):
                    threshold = math.ceil(current['searches'] * pct / 100)
                    count = 0
                    for k,v in sorted(hist.items()):
                        count += v
                        if count >= threshold:
                            current[f'p{pct}'] = k
                            break
                current['quantiles_exact'] = current['max_probe'] <= 4096
                maps.append(current); current = None
            elif key == 'probe_bucket':
                if current is None or bucket is not None: raise ValueError(line)
                bucket = value
            elif key == 'probe_count':
                if current is None or bucket is None or bucket in current['histogram']: raise ValueError(line)
                current['histogram'][bucket] = value; bucket = None
            else:
                if current is None or key in current or key not in FIELDS: raise ValueError(line)
                current[key] = value
            continue
        m = re.fullmatch(r'xu_heap_stats ([a-z_]+)=([0-9]+)', line)
        if not m or m[1] in heap: raise ValueError(line)
        heap[m[1]] = int(m[2])
    if current is not None or bucket is not None or not maps or heap.keys() != HEAP: raise ValueError((stderr, maps, heap))
    if heap['allocs'] != heap['frees'] or any(heap[k] for k in ('live_bytes','unknown_frees','double_frees','ledger_overflows')): raise ValueError(heap)
    return maps, heap

def cases():
    yield 'no-stdout', '@main\nfn main() int {\n mut m := map[int]int{}\n m[1] = 2\n m.delete(1)\n << 0\n}\n', ''
    for name,key in [('sequential','i'),('shifted','i << 20'),('negative','0 - i - 1'),('aligned','i << 12'),('permuted','(i * 1103515245 + 12345) ^ (i << 32)')]:
        source='''@main
fn main() int {
 mut m := map[int]int{}
 for i in 0:512 { m[KEY] = i + 1 }
 mut total := 0
 for i in 0:512 { total += m[KEY] }
 println(total)
 println(m.len())
 << 0
}
'''.replace('KEY',key)
        yield name, source, '131328\n512\n'
    source='''@main
fn main() int {
 mut m := map[int]int{}
 for i in 0:128 { m[i] = i + 1 }
 mut start := 32
 mut total := 0
 for round in 0:32 {
  for j in 0:96 { m.delete(start + j) }
  start = 128 + round * 96
  for j in 0:96 { m[start + j] = j + 1 }
  for j in 0:96 { total += m[start + j] }
  for j in 0:96 { total += m.get_or(0 - start - j - 1, 0) }
 }
 println(total)
 println(m.len())
 << 0
}
'''
    yield 'churn', source, f'{32*96*97//2}\n128\n'

def owning_cases():
    yield 'owning-strings', '''@main
fn main() int {
 mut m := map[string]string{}
 for i in 0:32 { m[str(i)] = "v" + str(i) }
 mut start := 12
 mut total := 0
 for round in 0:8 {
  for j in 0:20 { m.delete(str(start + j)) }
  start = 32 + round * 20
  for j in 0:20 { m[str(start + j)] = "v" + str(j) }
  m["0"] = "keep" + str(round)
  for j in 0:20 { total += m.get_or(str(start + j), "bad").len }
 }
 t := m.take(str(start))
 m.delete("missing")
 println(total)
 println(t)
 println(m.len())
 << 0
}
''', '400\nv0\n31\n'
    yield 'owning-arrays', '''@main
fn main() int {
 mut m := map[int][]int{}
 for i in 0:32 {
  mut x := []int{}
  x.push(i + 1)
  m[i] = x
 }
 mut start := 12
 mut total := 0
 for round in 0:8 {
  for j in 0:20 { m.delete(start + j) }
  start = 32 + round * 20
  for j in 0:20 {
   mut x := []int{}
   x.push(j + 1)
   m[start + j] = x
  }
  for j in 0:20 {
   idx := start + j
   r := &m[idx]
   total += r[0]
  }
 }
 t := m.take(start)
 m.delete(0 - 1)
 println(total)
 println(t[0])
 println(m.len())
 << 0
}
''', '1680\n1\n31\n'
    yield 'owning-structs', '''@main
struct Item { n int; s string }
fn main() int {
 mut m := map[int]Item{}
 for i in 0:32 { m[i] = Item{n: i + 1, s: "v" + str(i)} }
 mut start := 12
 mut total := 0
 for round in 0:8 {
  for j in 0:20 { m.delete(start + j) }
  start = 32 + round * 20
  for j in 0:20 { m[start + j] = Item{n: j + 1, s: "v" + str(j)} }
  m[0] = Item{n: 900, s: "replacement" + str(round)}
  for j in 0:20 {
   idx := start + j
   r := &m[idx]
   total += r.n + r.s.len
  }
 }
 t := m.take(start)
 m.delete(0 - 1)
 println(total)
 println(t.n)
 println(t.s.len)
 println(m.len())
 << 0
}
'''.replace(';', '\n'), '2080\n1\n2\n31\n'

def temporary_key_case():
    fixture = ROOT / 'tests/fixtures/map_temporary_keys'
    return 'temporary-keys', (fixture / 'main.xu').read_text(), (fixture / 'expected.txt').read_text()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--reference-report', type=Path, help='Require identical native-policy probe/state counters against a previous certified report.')
    ap.add_argument('--baseline',action='store_true',help='Measure unfixed policy; do not require improved probe bounds or tracked occupancy.')
    ap.add_argument('--modes',default='-O0,-O1,-O3,-O3 --target macos-x64')
    args=ap.parse_args();compiler=args.xu.resolve();identity=sha(compiler)
    manifest=json.loads(subprocess.check_output(['python3','scripts/check_bootstrap_xu_boundary.py','--strict-freeze','--json'],cwd=ROOT))['source_manifest']
    rows=[]
    with tempfile.TemporaryDirectory(prefix='xu-map-policy-') as td:
        work=Path(td)
        for mode in args.modes.split(','):
            for name,source,golden in [*cases(), *owning_cases(), temporary_key_case()]:
                src=work/'main.xu';src.write_text(source);binary=work/'program'
                env=dict(os.environ,XU_GEN1_MAP_STATS='1',XU_GEN1_HEAP_LEDGER='1')
                build=subprocess.run(['scripts/run_product_compiler.sh',str(compiler),'build',*shlex.split(mode),str(src),'-o',str(binary)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=120)
                if build.returncode: raise ValueError((name,mode,build.stderr))
                run=subprocess.run([str(binary)],env=dict(os.environ,XU_HEAP_STATS='1'),capture_output=True,text=True,timeout=30)
                if run.returncode or run.stdout!=golden: raise ValueError((name,mode,run))
                maps,heap=parse(run.stderr)
                if len(maps)!=1 or not maps[0]['quantiles_exact']: raise ValueError(maps)
                stats=maps[0]
                if not args.baseline:
                    if stats['used_recorded']!=stats['used'] or stats['deleted_recorded']!=stats['deleted']: raise ValueError(stats)
                    if stats['p99']>64 or stats['max_probe']>128: raise ValueError((name,mode,'unbounded probes',stats))
                    if name=='no-stdout' and (stats['capacity']!=16 or stats['grows']!=0): raise ValueError(stats)
                    if name=='churn' and (stats['capacity']!=256 or stats['compacts']==0): raise ValueError(stats)
                    if name.startswith('owning-') and (stats['capacity']!=64 or stats['compacts']==0): raise ValueError(stats)
                rows.append(dict(name=name,mode=mode,source=source,source_sha256=sha(src),binary_sha256=sha(binary),stats=stats,heap=heap))
                print('PASS',name,mode,{k:v for k,v in stats.items() if k!='histogram'},flush=True)
    parity = None
    if args.reference_report:
        reference = json.loads(args.reference_report.read_text())
        assert reference['status'] == 'PASS'
        old = {(r['name'], r['mode']): r['stats'] for r in reference['results']}
        current = {(r['name'], r['mode']): json.loads(json.dumps(r['stats'])) for r in rows}
        assert current == old, 'hash/policy migration changed certified probe/state counters'
        parity = dict(path=str(args.reference_report.resolve()), sha256=sha(args.reference_report), compiler_sha256=reference['compiler_sha256'], exact_stats_equal=True)
    assert sha(compiler)==identity
    assert manifest==json.loads(subprocess.check_output(['python3','scripts/check_bootstrap_xu_boundary.py','--strict-freeze','--json'],cwd=ROOT))['source_manifest']
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(dict(status='MEASURED BASELINE' if args.baseline else 'PASS',compiler=str(compiler),compiler_sha256=identity,source_manifest=manifest,reference_report=parity,scope='per-map actual slot visits in shared framed search paths, includes rehash placement; stats emit-time flag; histogram exact through 4096, overflow bucket otherwise; not fast-path instruction count or product timing',results=rows),indent=2)+'\n')
    print('PASS',len(rows),'map policy cases')

if __name__=='__main__': main()
