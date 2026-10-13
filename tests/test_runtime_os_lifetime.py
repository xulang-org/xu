#!/usr/bin/env python3
"""Check repeated owning environment snapshots against a same-process baseline."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '''@main
#os
fn snapshot() int {
    first := os.environ()
    second := os.environ()
    mut hits := 0
    if first.len > 0 && first.len == second.len { hits += 1 }
    value := os.lookup_env("PATH")
    if value.found && value.value.len > 0 { hits += 1 }
    << hits
}
fn main() int {
    mut hits := 0
    for i in 0:COUNT { hits += snapshot() }
    println(hits)
    << 0
}
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    compiler = args.xu.resolve()
    identity = sha(compiler)
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-env-lifetime-') as td:
        work = Path(td)
        for opt in ('-O0', '-O1', '-O3'):
            baseline = None
            for count in (0, 1, 100):
                src = work / 'main.xu'
                src.write_text(SOURCE.replace('COUNT', str(count)))
                binary = work / 'program'  # argv storage must match the zero-iteration baseline
                build = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                    'build', opt, str(src), '-o', str(binary)], cwd=ROOT,
                    env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'), capture_output=True,
                    text=True, timeout=120)
                if build.returncode:
                    raise ValueError(build.stderr)
                run = subprocess.run([str(binary)], cwd=work, env=dict(os.environ, XU_HEAP_STATS='1'),
                                     capture_output=True, text=True, timeout=30)
                ledger = {}
                for line in run.stderr.splitlines():
                    m = re.fullmatch(r'xu_heap_stats ([a-z_]+)=([0-9]+)', line)
                    if not m or m[1] in ledger:
                        raise ValueError(f'invalid ledger line: {line}')
                    ledger[m[1]] = int(m[2])
                if run.returncode or run.stdout != f'{count * 2}\n' or len(ledger) != 7:
                    raise ValueError(f'{opt}/{count}: golden/ledger mismatch: {run}')
                if any(ledger[k] for k in ('unknown_frees', 'double_frees', 'ledger_overflows')):
                    raise ValueError(f'ownership error: {ledger}')
                if baseline is None:
                    baseline = ledger
                if ledger['live_bytes'] != baseline['live_bytes'] or ledger['allocs'] - ledger['frees'] != baseline['allocs'] - baseline['frees']:
                    raise ValueError(f'{opt}/{count}: repeated snapshots retain allocations: {baseline}, {ledger}')
                rows.append(dict(opt=opt, count=count, ledger=ledger, source_sha256=sha(src),
                                 binary_sha256=sha(binary)))
    if sha(compiler) != identity:
        raise ValueError('compiler changed during environment resource gate')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(status='PASS', compiler=str(compiler),
        compiler_sha256=identity, results=rows), indent=2) + '\n')
    print('PASS: independent owning snapshots, repeated lookup, baseline live allocations')


if __name__ == '__main__':
    main()
