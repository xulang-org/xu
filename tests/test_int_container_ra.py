#!/usr/bin/env python3
"""Exercise integer-container admission, array growth and fallback via product xu."""
from pathlib import Path
import argparse
import hashlib
import heapq
import json
import os
import platform
import random
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MODES = {'O0': ['-O0'], 'O1': ['-O1'], 'O2': ['-O2'], 'O3': ['-O3'],
         'no-regcache': ['-O3', '--no-regcache'], 'ra0': ['-O3', '--ra=0']}


def heap_case():
    rng = random.Random(20261007)
    heap, commands, values, gold = [], [], [], []
    for i in range(2200):
        push = not heap or rng.randrange(5) < 3
        n = rng.randrange(-1000000000, 1000000001)
        commands.append(1 if push else 0)
        values.append(n)
        if push:
            heapq.heappush(heap, n)
        else:
            gold.append(str(heapq.heappop(heap)))
    while heap:
        gold.append(str(heapq.heappop(heap)))
    source = '''@main
#container/heap as heap
fn main() int {
    mut h := heap.new_ints()
    commands := COMMANDS
    values := VALUES
    for i in 0:commands.len {
        if commands[i] == 1 { h.push(values[i]) }
        else { println(h.pop() or (err) { << 1 }) }
    }
    while h.n > 0 { println(h.pop() or (err) { << 2 }) }
    << 0
}
'''.replace('COMMANDS', '[' + ','.join(map(str, commands)) + ']')
    source = source.replace('VALUES', '[' + ','.join(map(str, values)) + ']')
    return source, ('\n'.join(gold) + '\n').encode()


def cases():
    positive = '''@main
struct Bag { pub a []int pub n int }
fn (b &mut Bag) step(x int) int {
    if b.n >= b.a.len { b.a.push(x * 33 + 7) }
    mut j := b.n
    mut z := x
    while j > 0 {
        z = z + b.a[j - 1]
        j -= 1
    }
    b.a[b.n] = z
    b.n += 1
    << z
}
fn main() int {
    mut b := Bag{a: []int{}, n: 0}
    for i in 0:13 { println(b.step(i - 6)) }
    << 0
}
'''
    vals, gold = [], []
    for i in range(13):
        z = i - 6 + sum(vals)
        vals.append(z)
        gold.append(str(z))
    # User call mutates the descriptor between reads: the new predicate must
    # reject this method and preserve fresh descriptor loads on the fallback.
    fallback = '''@main
struct Bag { pub a []int pub n int }
fn change(b &mut Bag, n int) {
    if n > 0 { change(b, n - 1) }
    else { b.a.push(41) }
}
fn (b &mut Bag) step(x int) int {
    before := b.a[0]
    change(b, x)
    b.a[0] = before + b.a[b.a.len - 1]
    << b.a[0]
}
fn main() int {
    mut b := Bag{a: [1], n: 0}
    for i in 0:40 { println(b.step(i % 3)) }
    << 0
}
'''
    bounds = '''@main
struct Bag { pub a []int pub n int }
fn (b &mut Bag) step(x int) int {
    v := b.a[x]
    b.a[0] = v
    << v
}
fn main() int {
    mut b := Bag{a: [7], n: 0}
    println(b.step(-1))
    << 0
}
'''
    # Two separately addressed descriptor fields grow and then reuse their
    # backing storage. Nonzero field offsets and independent element values
    # expose a descriptor address incorrectly treated as a dead scalar home.
    paired = (ROOT / 'tests/fixtures/array_field_push_pair/main.xu').read_text()
    paired_gold = (ROOT / 'tests/fixtures/array_field_push_pair/expected.txt').read_bytes()
    hsource, hgold = heap_case()
    return {'paired-field-growth': (paired, paired_gold, True),
            'growth-loop': (positive, ('\n'.join(gold) + '\n').encode(), True),
            'random-heap': (hsource, hgold, True),
            'unknown-call': (fallback, ('\n'.join(str(1 + 41 * (i + 1)) for i in range(40)) + '\n').encode(), False),
            'bounds': (bounds, None, True)}


def run(xu, out, modes, require_admission=True):
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, (source, gold, admission) in cases().items():
        path = out / (name + '.xu')
        path.write_text(source)
        for mode in modes:
            binary = out / (name + '-' + mode)
            argv = [str(ROOT / 'scripts/run_product_compiler.sh'), str(xu), 'build',
                    str(path), *MODES[mode], '--timings', '-o', str(binary)]
            p = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=120)
            (out / (binary.name + '.build.log')).write_bytes(p.stdout + p.stderr)
            assert p.returncode == 0, (name, mode, p.stderr.decode(errors='replace'))
            stats = re.search(rb'ra-stats:.*?try=(\d+) vreg=(\d+)', p.stdout + p.stderr)
            assert stats, (name, mode, 'missing compiler admission stats')
            tried, planned = map(int, stats.groups())
            p = subprocess.run([str(binary)], capture_output=True, timeout=30)
            (out / (binary.name + '.stdout')).write_bytes(p.stdout)
            (out / (binary.name + '.stderr')).write_bytes(p.stderr)
            if gold is None:
                assert p.returncode != 0 and b'index' in (p.stdout + p.stderr).lower(), (name, mode, p)
            else:
                assert p.returncode == 0 and p.stdout == gold and not p.stderr, (name, mode, p.returncode, p.stdout[-200:], p.stderr)
            if require_admission and admission and mode in ('O2', 'O3'):
                assert tried > 0 and planned > 0, (name, mode, 'container scalar plan was refused')
            if name == 'unknown-call' and mode in ('O2', 'O3'):
                assert tried == 0 and planned == 0, (name, mode, 'unknown descriptor mutation entered container planning')
            rows.append(dict(case=name, mode=mode, tried=tried, planned=planned,
                             returncode=p.returncode, stdout_sha256=hashlib.sha256(p.stdout).hexdigest(), argv=argv))
    report = dict(status='PASS', rows=rows)
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def test_int_container_ra():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        import pytest
        pytest.skip('native ARM64 container admission regression')
    with tempfile.TemporaryDirectory(prefix='xu-int-container-') as tmp:
        run(Path(os.environ.get('XU', ROOT / 'bin/xu')).resolve(), Path(tmp), ['O3'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, default=ROOT / 'bin/xu')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--modes', default=','.join(MODES))
    ap.add_argument('--no-admission', action='store_true')
    args = ap.parse_args()
    print(json.dumps(run(args.xu.resolve(), args.out.resolve(), args.modes.split(','), not args.no_admission), indent=2))
