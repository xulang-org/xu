#!/usr/bin/env python3
"""Run independent readonly descriptor provenance against the real MIR reader."""
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
GENERATOR = ROOT / 'tests/generate_mir_readonly_values_oracle.py'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xu', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    compiler = args.xu.resolve()
    compiler_identity = sha(compiler)
    source_identity = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}
    rows = []
    modes = [('O0',['-O0']), ('O1',['-O1']), ('O2',['-O2']), ('O3',['-O3']),
             ('no-regcache',['--no-regcache']), ('ra0',['--ra=0']), ('ra1',['--ra=1']), ('ra2',['--ra=2'])]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='xu-value-plan-') as td:
        work = Path(td)
        data = work / 'data'
        generated = subprocess.run([sys.executable, str(GENERATOR), '--out-dir', str(data)], capture_output=True, text=True, check=True)
        oracle = json.loads((data / 'oracle.json').read_text())
        expected = (data / 'expected.txt').read_bytes()
        shutil.copytree(ROOT / 'src', work / 'src')
        shutil.copytree(ROOT / 'scripts', work / 'scripts')
        # Keep synthetic MIR construction out of product source. The actual
        # reader stays byte-identical to ROOT's implementation in this copy.
        shutil.copy2(data / 'support.xu', work / 'src/xu/types/readonly_value_test.xu')
        shutil.copy2(data / 'main.xu', work / 'main.xu')
        for label, flags in modes:
            binary = work / label
            build_env = dict(os.environ)
            build_env.pop('XU_HEAP_STATS', None)
            if label in ('O0', 'O3'): build_env['XU_GEN1_HEAP_LEDGER'] = '1'
            built = subprocess.run([str(work / 'scripts/run_product_compiler.sh'), str(compiler),
                'build', *flags, str(work / 'main.xu'), '-o', str(binary)], cwd=work, capture_output=True, timeout=180, env=build_env)
            if built.returncode:
                raise ValueError(f'{label}: {built.stderr.decode(errors="replace")}')
            run_env = dict(os.environ)
            run_env.pop('XU_HEAP_STATS', None)
            run = subprocess.run([str(binary)], capture_output=True, timeout=90, env=run_env)
            if run.returncode or run.stderr or run.stdout != expected:
                args.out.with_suffix('.failure.json').write_text(json.dumps(dict(
                    mode=label, rc=run.returncode, stderr=run.stderr.decode(errors='replace'),
                    expected=expected.decode(), actual=run.stdout.decode(errors='replace')), indent=2)+'\n')
                raise ValueError(f'{label}: oracle output/exit mismatch')
            heap = {}
            if label in ('O0', 'O3'):
                heap_env = dict(run_env, XU_HEAP_STATS='1')
                ledger = []
                for arg in ('baseline', 'run_____'):
                    result = subprocess.run([str(binary),arg], capture_output=True, text=True, timeout=90, env=heap_env)
                    stats = {k:int(v) for k,v in re.findall(r'xu_heap_stats (\w+)=(\d+)',result.stderr)}
                    extra = re.sub(r'xu_heap_stats \w+=\d+\n','',result.stderr)
                    stdout = '' if arg=='baseline' else expected.decode()
                    if result.returncode or extra or len(stats)!=7 or result.stdout!=stdout:
                        raise ValueError(f'{label}/{arg}: ledger output mismatch: {result.stderr}')
                    ledger.append(stats)
                baseline,actual=ledger
                if (actual['live_bytes']!=baseline['live_bytes'] or
                    actual['allocs']-actual['frees']!=baseline['allocs']-baseline['frees'] or
                    any(r[k] for r in ledger for k in ('unknown_frees','double_frees','ledger_overflows'))):
                    raise ValueError(f'{label}: ledger mismatch {ledger}')
                heap=dict(baseline=baseline,actual=actual,
                    incremental_live_bytes=actual['live_bytes']-baseline['live_bytes'],
                    incremental_net_allocations=(actual['allocs']-actual['frees'])-(baseline['allocs']-baseline['frees']))
            rows.append(dict(mode=label,status='PASS',golden_lines=len(expected.splitlines()),heap_ledger=heap,
                build_stderr=built.stderr.decode(errors='replace'),binary_sha256=sha(binary),
                stdout_sha256=hashlib.sha256(run.stdout).hexdigest()))
    if sha(compiler)!=compiler_identity or source_identity!={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').rglob('*.xu')}:
        raise ValueError('compiler/source changed during reader gate')
    report = dict(status='PASS',compiler_sha256=compiler_identity,source_sha256=source_identity,
        generator_sha256=sha(GENERATOR),phi_fixture_sha256=sha(GENERATOR.with_name('mir_readonly_values_phi.xu')),cases=len(oracle['cases']),
        golden_lines=oracle['output_lines'],rows=rows,
        scope='Bounded readonly descriptor provenance, exact use points and full Local/deSSA lower-bound input graphs; not LoopPlan equivalence, transformation, bounds elimination or SSA admission.')
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(f"PASS: {report['cases']} cases, {report['golden_lines']} independent golden lines x {len(rows)} modes")

if __name__ == '__main__':
    main()
