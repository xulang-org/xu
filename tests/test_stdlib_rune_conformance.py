#!/usr/bin/env python3
"""Compare Xu Rune APIs to fresh, independent Go standard-library output."""
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
    paths += [ROOT / 'tests/oracles/stdlib_runes.go',
              ROOT / 'tests/data/stdlib_rune_vectors.json',
              ROOT / 'scripts/gen_unicode_case_tables.go',
              ROOT / 'scripts/run_product_compiler.sh', Path(__file__)]
    for name in ('strings_unicode_runes', 'unicode_case_full'):
        paths += list((ROOT / 'tests/fixtures' / name).glob('*'))
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths) if p.is_file()}


def run(cmd, timeout=180):
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
        built = run(['go', 'build', '-o', str(oracle), 'tests/oracles/stdlib_runes.go'])
        if built.returncode:
            raise RuntimeError(built.stderr.decode())
        report['go_version'] = run(['go', 'version']).stdout.decode().strip()
        report['unicode_version'] = run([str(oracle), 'version']).stdout.decode().strip()
        if report['unicode_version'] != '15.0.0':
            raise RuntimeError('oracle must use the pinned Unicode 15.0.0 version')
        generated = run(['go', 'run', 'scripts/gen_unicode_case_tables.go', '--check'])
        report['tables_current'] = generated.returncode == 0
        for name, mode in [('strings_unicode_runes', 'text'), ('unicode_case_full', 'case')]:
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
