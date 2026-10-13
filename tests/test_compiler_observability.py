#!/usr/bin/env python3
"""Run compiler telemetry closure checks against an explicit hosted candidate."""
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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stats(stderr, prefix, unit=''):
    lines = [line for line in stderr.splitlines() if line.startswith(prefix + ': ')]
    if len(lines) != 1:
        raise ValueError(f'{prefix}: expected one statistics record: {lines}')
    values = {}
    for token in lines[0].split()[1:]:
        match = re.fullmatch(r'([a-z_]+)=([0-9]+)' + unit, token)
        if not match or match[1] in values:
            raise ValueError(f'{prefix}: malformed or duplicate counter {token}')
        values[match[1]] = int(match[2])
    return values


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    compiler = args.xu.resolve()
    identity = sha(compiler)
    manifest = json.loads(subprocess.check_output(
        ['python3', 'scripts/check_bootstrap_xu_boundary.py', '--strict-freeze', '--json'],
        cwd=ROOT))['source_manifest']
    rows = []
    acyclic_rows = []
    # Many simple functions make the lowering interval measurable without a
    # heavyweight standard-library import. The call chain has a fixed golden.
    source = '@main\n'
    for i in range(200):
        source += f'fn f_{i}(x int) int {{ << x + {i} }}\n'
    source += 'fn main() int {\nmut x := 0\n'
    for i in range(200):
        source += f'x = f_{i}(x)\n'
    source += 'println(x)\n<< 0\n}\n'
    with tempfile.TemporaryDirectory(prefix='xu-observe-') as td:
        work = Path(td)
        src = work / 'main.xu'
        src.write_text(source)
        for opt in ('-O0', '-O1'):
            binaries = []
            stderr_plain = None
            for diagnostic in (False, True):
                binary = work / f'{opt}-{diagnostic}'
                flags = [opt] + (['--timings'] if diagnostic else [])
                command = [str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                           'build', *flags, str(src), '-o', str(binary)]
                built = subprocess.run(command, cwd=ROOT, capture_output=True,
                                       text=True, timeout=120, check=True)
                run = subprocess.run([str(binary)], capture_output=True, text=True,
                                     timeout=30, check=True)
                if run.stdout != '19900\n' or run.stderr:
                    raise ValueError(f'{opt}/{diagnostic}: golden mismatch')
                binaries.append(sha(binary))
                if not diagnostic:
                    stderr_plain = built.stderr
                    continue
                timing = stats(built.stderr, 'timings', 'ms')
                ra = stats(built.stderr, 'ra-stats')
                mir = stats(built.stderr, 'opt-stats')
                if ra['fn'] != ra['vreg'] + ra['rc'] + ra['frame'] or ra['fn'] != mir['nfn']:
                    raise ValueError(f'function partition does not close: {ra}, {mir}')
                if ra['try'] != ra['vreg'] + ra['empty'] or ra['keep_rc'] > ra['fn']:
                    raise ValueError(f'RA admission partition does not close: {ra}')
                if mir['nins'] <= 0 or mir['nins_out'] <= 0 or timing['mir'] <= 0:
                    raise ValueError(f'previously disconnected counters remain zero: {mir}, {timing}')
                if opt == '-O0' and mir['nins'] != mir['nins_out']:
                    raise ValueError('O0 instruction-pool counts differ')
                phases = sum(timing[k] for k in ('load', 'parse', 'check', 'mir', 'emit', 'bin'))
                if not -6 <= timing['total'] - phases <= 100:
                    raise ValueError(f'phase milliseconds do not close: {timing}')
                diagnostics = '\n'.join(line for line in built.stderr.splitlines()
                                        if not line.startswith(('timings:', 'ra-stats:', 'opt-stats:')))
                if diagnostics != stderr_plain.rstrip('\n'):
                    raise ValueError('timings changed non-statistics diagnostics')
                rows.append(dict(opt=opt, timings_ms=timing, ra=ra, mir=mir,
                                 binary_sha256=binaries[-1]))
            if len(set(binaries)) != 1:
                raise ValueError(f'{opt}: timings changed emitted machine code')
        # Branch-only integer helpers must still reach register planning.
        # A blanket scalar-CFG fallback preserved output while silently
        # removing this path from map hashing and other acyclic helpers.
        branch_source = '@main\nfn branchy(x int) int {\nmut v := x\n'
        for i in range(16):
            branch_source += (f'if (v & {1 << i}) == 0 {{ v = v * 3 + {i + 1} }} '
                              f'else {{ v = v * 3 - {i + 1} }}\n')
        branch_source += ('<< v\n}\nfn main() int {\nprintln(branchy(-11))\n'
                          'println(branchy(7))\n<< 0\n}\n')
        def branch_oracle(v):
            for i in range(16):
                v = v * 3 + (i + 1 if v & (1 << i) == 0 else -(i + 1))
            return v
        branch_gold = ''.join(f'{branch_oracle(v)}\n' for v in (-11, 7))
        src.write_text(branch_source)
        for opt in ('-O2', '-O3'):
            binary = work / f'acyclic-{opt}'
            built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'),
                str(compiler), 'build', opt, '--timings', str(src), '-o', str(binary)],
                cwd=ROOT, capture_output=True, text=True, timeout=120, check=True)
            run = subprocess.run([str(binary)], capture_output=True, text=True,
                                 timeout=30, check=True)
            ra = stats(built.stderr, 'ra-stats')
            if run.stdout != branch_gold or run.stderr or ra['vreg'] < 1:
                raise ValueError(f'acyclic scalar admission/golden failed: {opt}, {ra}, {run}')
            acyclic_rows.append(dict(opt=opt, ra=ra, binary_sha256=sha(binary)))
    if sha(compiler) != identity:
        raise ValueError('compiler changed during telemetry gate')
    sidecar = Path(str(compiler) + '.provenance')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(status='PASS', compiler=str(compiler),
        compiler_sha256=identity, provenance=sidecar.read_text() if sidecar.exists() else None,
        source_manifest=manifest, source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        rows=rows, acyclic_scalar_rows=acyclic_rows), indent=2) + '\n')
    print('PASS: telemetry partitions, phase units, golden and binary invariance')


if __name__ == '__main__':
    main()
