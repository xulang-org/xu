#!/usr/bin/env python3
"""Independent SHA-1/SHA-256 boundary and streaming oracles through the hosted compiler/ledger."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def sha_case(algorithm):
    code = ['@main', '#crypto/' + algorithm, 'fn main() int {']
    golden = []
    sumfn = 'sum256' if algorithm == 'sha256' else 'sum'
    for index, n in enumerate((0, 1, 3, 7, 55, 56, 63, 64, 65, 111, 112, 127, 128, 129, 255, 256, 1024, 4097)):
        data = bytes((j * 73 + 31 + n) & 255 for j in range(n))
        digest = lambda value: getattr(hashlib, algorithm)(value).hexdigest()
        code += [f'mut s{index} := ""', f'for j in 0:{n} {{ s{index}.push_byte((j * 73 + 31 + {n}) & 255) }}',
                 f'println({algorithm}.{sumfn}(s{index} + ""))', f'mut d{index} := {algorithm}.new()']
        golden += [digest(data)]
        start = 0
        for chunk, size in enumerate((0, 1, 54, 1, 7, 1, 64, 0, n)):
            end = min(n, start + size)
            code += [f'p{index}_{chunk} := s{index}[{start}:{end}]', f'd{index}.write(&p{index}_{chunk})',
                     f'println(d{index}.sum())', f'println(d{index}.sum())']
            golden += [digest(data[:end])] * 2
            start = end
        code += [f'd{index}.reset()', f'println(d{index}.sum())']
        golden += [digest(b'')]
    code += ['<< 0', '}']
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
    with tempfile.TemporaryDirectory(prefix='xu-sha-lane-') as td:
        work = Path(td)
        for name, (source, golden) in [(name, sha_case(name)) for name in ('sha1', 'sha256')]:
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
                rows.append(row)
                print(name, flags, row['status'], row.get('ledger', built.stderr[:250]), flush=True)
        if hashlib.sha256(compiler.read_bytes()).hexdigest() != identity:
            raise ValueError('compiler changed during test')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(compiler_sha256=identity, rows=rows), indent=2) + '\n')
    return any(row['status'] != 'PASS' for row in rows)


if __name__ == '__main__':
    raise SystemExit(main())
