#!/usr/bin/env python3
"""Compare Xu Unicode classification/title APIs to fresh, independent Go standard-library output."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    paths = list((ROOT / 'src').rglob('*.xu'))
    paths += [ROOT / 'tests/oracles/unicode_properties.go',
              ROOT / 'scripts/gen_unicode_tables.go',
              ROOT / 'scripts/gen_unicode_case_tables.go',
              ROOT / 'scripts/run_product_compiler.sh', Path(__file__)]
    for name in ('unicode_properties_edge', 'unicode_properties_full'):
        paths += list((ROOT / 'tests/fixtures' / name).glob('*'))
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths) if p.is_file()}


def run(cmd, timeout=300):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xu', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    compiler = args.xu.resolve()
    report = dict(compiler=str(compiler), compiler_sha256=digest(compiler),
                  input_sha256=inputs(), results=[])
    with tempfile.TemporaryDirectory(prefix='xu-rune-conformance-') as tmp:
        tmp = Path(tmp)
        oracle = tmp / 'oracle'
        built = run(['go', 'build', '-o', str(oracle), 'tests/oracles/unicode_properties.go'])
        if built.returncode:
            raise RuntimeError(built.stderr.decode())
        report['go_version'] = run(['go', 'version']).stdout.decode().strip()
        report['unicode_version'] = run([str(oracle), 'version']).stdout.decode().strip()
        if report['unicode_version'] != '15.0.0':
            raise RuntimeError('oracle must use the pinned Unicode 15.0.0 version')
        generated = run(['go', 'run', 'scripts/gen_unicode_case_tables.go', '--check'])
        classification = run(['go', 'run', 'scripts/gen_unicode_tables.go', '--check'])
        report['tables_current'] = generated.returncode == 0 and classification.returncode == 0
        for name, mode in [('unicode_properties_edge', 'edge'), ('unicode_properties_full', 'full')]:
            expected = run([str(oracle), mode])
            fixture = ROOT / 'tests/fixtures' / name
            frozen_current = expected.returncode == 0 and (fixture / 'expected.txt').read_bytes() == expected.stdout
            for opt in ('O0', 'O3'):
                output = tmp / (name + '-' + opt)
                compiled = run([str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                                'build', str(fixture / 'main.xu'), '-' + opt, '-o', str(output)])
                actual = run([str(output)]) if compiled.returncode == 0 else compiled
                passed = frozen_current and compiled.returncode == 0 and actual.returncode == 0 and actual.stdout == expected.stdout
                row = dict(fixture=name, optimization=opt, passed=passed,
                           expected_current=frozen_current, returncode=actual.returncode,
                           stdout_sha256=hashlib.sha256(actual.stdout).hexdigest(),
                           oracle_sha256=hashlib.sha256(expected.stdout).hexdigest(),
                           oracle_lines=len(expected.stdout.splitlines()),
                           stderr=actual.stderr.decode(errors='replace'))
                if not passed:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.with_suffix('.' + name + '-' + opt + '.actual').write_bytes(actual.stdout)
                report['results'].append(row)
                print(('PASS' if passed else 'FAIL') + ' ' + name + ' ' + opt, flush=True)
    report['input_changed'] = report['input_sha256'] != inputs()
    report['compiler_changed'] = report['compiler_sha256'] != digest(compiler)
    report['status'] = 'PASS' if report['tables_current'] and all(x['passed'] for x in report['results']) and not report['input_changed'] and not report['compiler_changed'] else 'FAIL'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    raise SystemExit(report['status'] != 'PASS')


if __name__ == '__main__':
    main()
