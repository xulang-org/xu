#!/usr/bin/env python3
"""Verify generic pair selection against independent original MIR execution."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / 'tests/generate_mir_select_pair_oracle.py'
SUPPORT = ROOT / 'tests/mir_select_pair_test.xu'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xu', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--modes', default='O0,O1,O2,O3,no-regcache,ra0,ra1,ra2')
    args = parser.parse_args()
    source, compiler = args.source_root.resolve(), args.xu.resolve()
    compiler_identity = sha(compiler)
    source_identity = {str(p.relative_to(source)): sha(p) for p in (source/'src').rglob('*.xu')}
    test_identity = {str(p.relative_to(ROOT)): sha(p) for p in (GENERATOR, SUPPORT, Path(__file__))}
    options = dict(O0=['-O0'], O1=['-O1'], O2=['-O2'], O3=['-O3'],
                   **{'no-regcache': ['--no-regcache'], 'ra0': ['--ra=0'], 'ra1': ['--ra=1'], 'ra2': ['--ra=2']})
    modes = args.modes.split(',')
    if any(mode not in options for mode in modes): parser.error('unknown mode')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    data = (args.data_dir or args.out.parent/'select-pair-data').resolve()
    subprocess.run([sys.executable, str(GENERATOR), '--out-dir', str(data)], check=True)
    oracle = json.loads((data/'oracle.json').read_text())
    expected = (data/'expected.txt').read_bytes()
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-select-pair-') as td:
        work = Path(td)
        shutil.copytree(source/'src', work/'src')
        shutil.copytree(source/'scripts', work/'scripts')
        shutil.copy2(data/'support.xu', work/'src/xu/types/select_pair_test.xu')
        shutil.copy2(data/'main.xu', work/'main.xu')
        for mode in modes:
            binary = work/mode
            build_env = dict(os.environ); build_env.pop('XU_HEAP_STATS', None)
            if mode in ('O0', 'O3'): build_env['XU_GEN1_HEAP_LEDGER'] = '1'
            built = subprocess.run([str(work/'scripts/run_product_compiler.sh'), str(compiler),
                'build', *options[mode], str(work/'main.xu'), '-o', str(binary)],
                cwd=work, capture_output=True, env=build_env, timeout=300)
            if built.returncode: raise ValueError(f'{mode}: build failed: {built.stderr.decode(errors="replace")}')
            run_env = dict(os.environ); run_env.pop('XU_HEAP_STATS', None)
            run = subprocess.run([str(binary)], capture_output=True, env=run_env, timeout=90)
            if run.returncode or run.stderr or run.stdout != expected:
                want, got = expected.decode().splitlines(), run.stdout.decode(errors='replace').splitlines()
                first = next((i+1 for i, (a, b) in enumerate(zip(want, got)) if a != b), min(len(want), len(got))+1)
                case = next((r['name'] for r in oracle['cases'] if r['first_line'] <= first <= r['last_line']), 'outside')
                args.out.with_suffix('.failure.json').write_text(json.dumps(dict(mode=mode, rc=run.returncode,
                    stderr=run.stderr.decode(errors='replace'), case=case, first_mismatch_line=first,
                    expected=expected.decode(), actual=run.stdout.decode(errors='replace')), indent=2)+'\n')
                raise ValueError(f'{mode}: mismatch line {first} in {case}')
            heap = {}
            if mode in ('O0', 'O3'):
                ledgers = []
                for arg in ('baseline', 'run_____'):
                    result = subprocess.run([str(binary), arg], capture_output=True, text=True, timeout=90,
                                            env=dict(run_env, XU_HEAP_STATS='1'))
                    stats = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', result.stderr)}
                    extra = re.sub(r'xu_heap_stats \w+=\d+\n', '', result.stderr)
                    if result.returncode or extra or len(stats) != 7 or result.stdout != ('' if arg == 'baseline' else expected.decode()):
                        raise ValueError(f'{mode}/{arg}: ledger output mismatch: {result.stderr}')
                    ledgers.append(stats)
                baseline, actual = ledgers
                if (actual['live_bytes'] != baseline['live_bytes'] or
                    actual['allocs']-actual['frees'] != baseline['allocs']-baseline['frees'] or
                    any(row[k] for row in ledgers for k in ('unknown_frees', 'double_frees', 'ledger_overflows'))):
                    raise ValueError(f'{mode}: ledger mismatch {ledgers}')
                heap = dict(baseline=baseline, actual=actual, incremental_live_bytes=actual['live_bytes']-baseline['live_bytes'],
                            incremental_net_allocations=(actual['allocs']-actual['frees'])-(baseline['allocs']-baseline['frees']))
            rows.append(dict(mode=mode, status='PASS', golden_lines=len(expected.splitlines()),
                             heap_ledger=heap, build_stderr=built.stderr.decode(errors='replace'),
                             binary_sha256=sha(binary), stdout_sha256=hashlib.sha256(run.stdout).hexdigest()))
    if (sha(compiler) != compiler_identity or source_identity != {str(p.relative_to(source)): sha(p) for p in (source/'src').rglob('*.xu')} or
        test_identity != {str(p.relative_to(ROOT)): sha(p) for p in (GENERATOR, SUPPORT, Path(__file__))}):
        raise ValueError('compiler/source/test changed during SelectPair gate')
    report = dict(status='PASS', compiler_sha256=compiler_identity, source_sha256=source_identity,
                  test_sha256=test_identity, oracle_sha256=sha(data/'oracle.json'), expected_sha256=sha(data/'expected.txt'),
                  support_sha256=sha(data/'support.xu'), cases=len(oracle['cases']), golden_lines=oracle['output_lines'],
                  semantic_runs=oracle['semantic_runs'], rows=rows,
                  scope='General typed pair reader vs independent sequential MIR and simultaneous SSA Phi oracle; no emitter, allocation, or runtime gain claim.')
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(f"PASS: {report['cases']} cases, {report['golden_lines']} golden lines x {len(rows)} modes; {report['semantic_runs']} original MIR/selected pair executions per mode")


if __name__ == '__main__':
    main()
