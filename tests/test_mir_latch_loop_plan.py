#!/usr/bin/env python3
"""Verify complete initial-guard/body/latch lower-bound plans with independent MIR execution."""
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
GENERATOR = ROOT / 'tests/generate_mir_latch_loop_oracle.py'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xu', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT,
                        help='Immutable accepted source snapshot; defaults to repository.')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--modes', default='O0,O1,O2,O3,no-regcache,ra0,ra1,ra2')
    args = parser.parse_args()
    compiler = args.xu.resolve()
    source = args.source_root.resolve()
    compiler_identity = sha(compiler)
    source_identity = {str(p.relative_to(source)): sha(p) for p in (source / 'src').rglob('*.xu')}
    options = dict(O0=['-O0'], O1=['-O1'], O2=['-O2'], O3=['-O3'],
                   **{'no-regcache': ['--no-regcache'], 'ra0': ['--ra=0'],
                      'ra1': ['--ra=1'], 'ra2': ['--ra=2']})
    labels = args.modes.split(',')
    if any(label not in options for label in labels):
        parser.error('unknown mode')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    data = (args.data_dir or args.out.parent / 'latch-loop-data').resolve()
    subprocess.run([sys.executable, str(GENERATOR), '--out-dir', str(data)], check=True)
    oracle = json.loads((data / 'oracle.json').read_text())
    expected = (data / 'expected.txt').read_bytes()
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-latch-loop-') as td:
        work = Path(td)
        shutil.copytree(source / 'src', work / 'src')
        shutil.copytree(source / 'scripts', work / 'scripts')
        shutil.copy2(data / 'support.xu', work / 'src/xu/types/loop_plan_test.xu')
        shutil.copy2(data / 'main.xu', work / 'main.xu')
        for label in labels:
            binary = work / label
            build_env = dict(os.environ)
            build_env.pop('XU_HEAP_STATS', None)
            if label in ('O0', 'O3'):
                build_env['XU_GEN1_HEAP_LEDGER'] = '1'
            built = subprocess.run([str(work / 'scripts/run_product_compiler.sh'), str(compiler),
                'build', *options[label], str(work / 'main.xu'), '-o', str(binary)],
                cwd=work, capture_output=True, timeout=300, env=build_env)
            if built.returncode:
                raise ValueError(f'{label}: compile failed: {built.stderr.decode(errors="replace")}')
            run_env = dict(os.environ)
            run_env.pop('XU_HEAP_STATS', None)
            run = subprocess.run([str(binary)], capture_output=True, timeout=90, env=run_env)
            if run.returncode or run.stderr or run.stdout != expected:
                want, got = expected.decode().splitlines(), run.stdout.decode(errors='replace').splitlines()
                first = next((i + 1 for i, pair in enumerate(zip(want, got)) if pair[0] != pair[1]),
                             min(len(want), len(got)) + 1)
                case = next((c['name'] for c in oracle['cases'] if c['first_line'] <= first <= c['last_line']), 'outside')
                args.out.with_suffix('.failure.json').write_text(json.dumps(dict(
                    mode=label, rc=run.returncode, stderr=run.stderr.decode(errors='replace'),
                    first_mismatch_line=first, case=case, expected=expected.decode(),
                    actual=run.stdout.decode(errors='replace')), indent=2) + '\n')
                raise ValueError(f'{label}: oracle mismatch line {first} in {case}')
            heap = {}
            if label in ('O0', 'O3'):
                ledger = []
                for arg in ('baseline', 'run_____'):
                    result = subprocess.run([str(binary), arg], capture_output=True, text=True,
                                            timeout=90, env=dict(run_env, XU_HEAP_STATS='1'))
                    stats = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', result.stderr)}
                    extra = re.sub(r'xu_heap_stats \w+=\d+\n', '', result.stderr)
                    stdout = '' if arg == 'baseline' else expected.decode()
                    if result.returncode or extra or len(stats) != 7 or result.stdout != stdout:
                        raise ValueError(f'{label}/{arg}: ledger output mismatch: {result.stderr}')
                    ledger.append(stats)
                baseline, actual = ledger
                if (actual['live_bytes'] != baseline['live_bytes'] or
                    actual['allocs'] - actual['frees'] != baseline['allocs'] - baseline['frees'] or
                    any(r[k] for r in ledger for k in ('unknown_frees', 'double_frees', 'ledger_overflows'))):
                    raise ValueError(f'{label}: ledger mismatch {ledger}')
                heap = dict(baseline=baseline, actual=actual,
                            incremental_live_bytes=actual['live_bytes'] - baseline['live_bytes'],
                            incremental_net_allocations=(actual['allocs'] - actual['frees']) - (baseline['allocs'] - baseline['frees']))
            rows.append(dict(mode=label, status='PASS', golden_lines=len(expected.splitlines()),
                             heap_ledger=heap, build_stderr=built.stderr.decode(errors='replace'),
                             binary_sha256=sha(binary), stdout_sha256=hashlib.sha256(run.stdout).hexdigest()))
    if (sha(compiler) != compiler_identity or
        source_identity != {str(p.relative_to(source)): sha(p) for p in (source / 'src').rglob('*.xu')}):
        raise ValueError('compiler/source changed during loop-plan gate')
    report = dict(status='PASS', compiler_sha256=compiler_identity, source_sha256=source_identity,
                  generator_sha256=sha(GENERATOR), phi_fixture_sha256=sha(GENERATOR.with_name('mir_latch_loop_phi.xu')),
                  generator_dependencies={str(p.relative_to(ROOT)): sha(p) for p in (
                      ROOT / 'tests/generate_mir_loop_plan_oracle.py', ROOT / 'tests/mir_loop_plan_phi.xu',
                      ROOT / 'tests/data/mir_latch_lower_bound.json')},
                  oracle_sha256=sha(data / 'oracle.json'), support_sha256=sha(data / 'support.xu'),
                  expected_sha256=sha(data / 'expected.txt'), cases=len(oracle['cases']), golden_lines=oracle['output_lines'],
                  semantic_runs=oracle['semantic_runs'], rows=rows,
                  scope='Complete bounded initial-guard/body/latch lower-bound plans, Local/real multi-block Phi destruction and independent algorithm execution. No transformation, RA integration, range/NoTrap proof or runtime improvement claim.')
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(f"PASS: {report['cases']} cases, {report['golden_lines']} golden lines x {len(rows)} modes; {report['semantic_runs']} independent algorithm executions per mode")


if __name__ == '__main__':
    main()
