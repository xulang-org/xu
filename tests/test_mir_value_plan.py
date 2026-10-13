#!/usr/bin/env python3
"""Run independent ordered-definition/storage semantics against the real MIR reader."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / 'tests/generate_mir_value_plan_oracle.py'

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
        shutil.copy2(data / 'support.xu', work / 'src/xu/types/value_plan_test.xu')
        shutil.copy2(data / 'main.xu', work / 'main.xu')
        for label, flags in modes:
            binary = work / label
            built = subprocess.run([str(work / 'scripts/run_product_compiler.sh'), str(compiler),
                'build', *flags, str(work / 'main.xu'), '-o', str(binary)], cwd=work, capture_output=True, timeout=180)
            if built.returncode:
                raise ValueError(f'{label}: {built.stderr.decode(errors="replace")}')
            run = subprocess.run([str(binary)], capture_output=True, timeout=90)
            if run.returncode or run.stderr or run.stdout != expected:
                args.out.with_suffix('.failure.json').write_text(json.dumps(dict(
                    mode=label, rc=run.returncode, stderr=run.stderr.decode(errors='replace'),
                    expected=expected.decode(), actual=run.stdout.decode(errors='replace')), indent=2)+'\n')
                raise ValueError(f'{label}: oracle output/exit mismatch')
            rows.append(dict(mode=label,status='PASS',golden_lines=len(expected.splitlines()),
                build_stderr=built.stderr.decode(errors='replace'),binary_sha256=sha(binary),
                stdout_sha256=hashlib.sha256(run.stdout).hexdigest()))
    if sha(compiler)!=compiler_identity or source_identity!={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').rglob('*.xu')}:
        raise ValueError('compiler/source changed during reader gate')
    report = dict(status='PASS',compiler_sha256=compiler_identity,source_sha256=source_identity,
        generator_sha256=sha(GENERATOR),cases=len(oracle['cases']),definition_queries=oracle['definition_queries'],
        golden_lines=oracle['output_lines'],rows=rows,
        scope='Direct reader/storage semantics and bounded refusal; not cross-block dominance, whole-loop fusion, or SSA admission evidence.')
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(f"PASS: {report['cases']} cases, {report['golden_lines']} independent golden lines x {len(rows)} modes")

if __name__ == '__main__':
    main()
