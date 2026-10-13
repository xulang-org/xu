#!/usr/bin/env python3
"""Independent MD5 and IntHeap oracles through the hosted compiler/ledger."""
import argparse
import hashlib
import heapq
import json
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def md5_case():
    rng = random.Random(20261007)
    code = ['@main', '#crypto/md5', 'fn main() int {']
    golden = []
    for text in ('', 'a', 'abc', 'message digest', 'abcdefghijklmnopqrstuvwxyz',
                 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
                 '1234567890' * 8):
        code += [f'println(md5.sum("{text}"))']
        golden += [hashlib.md5(text.encode()).hexdigest()]
    for index, n in enumerate((0, 1, 3, 7, 55, 56, 63, 64, 65, 111, 112,
                                127, 128, 129, 255, 256, 1024, 4097)):
        data = bytes(rng.randrange(256) for _ in range(n))
        code += [f'mut s{index} := make_string({n})']
        for j, value in enumerate(data):
            code += [f's{index}[{j}] = {value}']
        code += [f'println(md5.sum(s{index} + ""))', f'mut d{index} := md5.new()']
        golden += [hashlib.md5(data).hexdigest()]
        start = 0
        # Include empty chunks and cross 55/56/63/64-byte boundaries.
        for chunk, size in enumerate((0, 1, 54, 1, 7, 1, 64, 0, n)):
            end = min(n, start + size)
            code += [f'p{index}_{chunk} := s{index}[{start}:{end}]',
                     f'd{index}.write(&p{index}_{chunk})',
                     f'println(d{index}.sum())', f'println(d{index}.sum())']
            golden += [hashlib.md5(data[:end]).hexdigest()] * 2
            start = end
        code += [f'd{index}.reset()', f'println(d{index}.sum())']
        golden += [hashlib.md5(b'').hexdigest()]
    block = '0123456789abcdef' * 4
    code += [f'block := "{block}"', 'mut stream := md5.new()',
             'for i in 0:1003 { stream.write(&block) }',
             'println(stream.sum())', 'println(stream.sum())',
             'stream.reset()', 'println(stream.sum())']
    golden += [hashlib.md5(block.encode() * 1003).hexdigest()] * 2
    golden += [hashlib.md5(b'').hexdigest()]
    code += ['<< 0', '}']
    return '\n'.join(code) + '\n', '\n'.join(golden) + '\n'


def heap_case():
    rng = random.Random(20261007)
    code = ['@main', '#container/heap',
            'fn main() int {', 'mut h := heap.from_ints([9,1,1,0,-9,7,8])']
    values = [9, 1, 1, 0, -9, 7, 8]
    heapq.heapify(values)
    golden = []
    for i in range(800):
        if not values or rng.random() < .6:
            v = rng.randrange(-1000, 1001)
            heapq.heappush(values, v)
            code += [f'h.push({v})']
        else:
            golden += [str(heapq.heappop(values))]
            code += [f'v{i} := h.pop() or (err) {{ << 1 }}', f'println(v{i})']
    for i in range(len(values)):
        golden += [str(heapq.heappop(values))]
        code += [f'tail{i} := h.pop() or (err) {{ << 1 }}', f'println(tail{i})']
    code += ['_ := h.pop() or (err) { println("empty")\n << 0 }', '<< 1', '}']
    golden += ['empty']
    return '\n'.join(code) + '\n', '\n'.join(golden) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--source-root', type=Path, default=ROOT,
                    help='Matched source snapshot used for regression evidence')
    args = ap.parse_args()
    compiler = args.xu.resolve()
    identity = hashlib.sha256(compiler.read_bytes()).hexdigest()
    source_root = args.source_root.resolve()
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-md5-heap-') as td:
        work = Path(td)
        for name, (source, golden) in [('md5', md5_case()), ('heap', heap_case())]:
            path = work / (name + '.xu')
            path.write_text(source)
            for flags in (['-O0'], ['-O1'], ['-O2'], ['-O3'], ['-O1', '--no-regcache'],
                          ['-O3', '--ra=0']):
                binary = work / 'test'
                built = subprocess.run([str(source_root / 'scripts/run_product_compiler.sh'), str(compiler),
                    'build', *flags, '--timings', str(path), '-o', str(binary)], cwd=source_root, capture_output=True,
                    text=True, timeout=120, env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'))
                row = dict(name=name, flags=flags, build_exit=built.returncode, build_stderr=built.stderr,
                           source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                           golden_sha256=hashlib.sha256(golden.encode()).hexdigest())
                if not built.returncode:
                    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60,
                        env=dict(os.environ, XU_HEAP_STATS='1'))
                    ledger = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', run.stderr)}
                    extra = re.sub(r'xu_heap_stats \w+=\d+\n', '', run.stderr)
                    row.update(run_exit=run.returncode, stdout=run.stdout, stderr=run.stderr, ledger=ledger)
                    row['status'] = 'PASS' if (not run.returncode and run.stdout == golden and not extra
                        and len(ledger) == 7 and ledger['live_bytes'] == 0 and ledger['allocs'] == ledger['frees']
                        and not any(ledger[k] for k in ('unknown_frees', 'double_frees', 'ledger_overflows'))) else 'FAIL'
                else:
                    row['status'] = 'FAIL'
                if name == 'md5' and flags == ['-O3']:
                    stats = re.search(r'ra-stats:.*?try=(\d+) vreg=(\d+)', built.stderr)
                    row['compression_planning'] = bool(stats and int(stats[1]) >= 1
                                                      and int(stats[2]) >= 1)
                    if not row['compression_planning']:
                        row['status'] = 'FAIL'
                rows.append(row)
                print(name, flags, row['status'], row.get('ledger', built.stderr[:250]), flush=True)
        if hashlib.sha256(compiler.read_bytes()).hexdigest() != identity:
            raise ValueError('compiler changed during test')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(compiler_sha256=identity, rows=rows), indent=2) + '\n')
    return any(row['status'] != 'PASS' for row in rows)


if __name__ == '__main__':
    raise SystemExit(main())
