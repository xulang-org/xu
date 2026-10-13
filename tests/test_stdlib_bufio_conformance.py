#!/usr/bin/env python3
"""Compare buffered I/O with Go and verify Xu-specific capacity/error contracts."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ('bufio_boundaries', 'bufio_file_errors')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    paths = list((ROOT / 'src').rglob('*.xu'))
    paths += [ROOT / 'tests/oracles/stdlib_bufio.go',
              ROOT / 'tests/data/stdlib_bufio_vectors.json',
              ROOT / 'scripts/run_product_compiler.sh', Path(__file__)]
    for name in FIXTURES:
        paths += list((ROOT / 'tests/fixtures' / name).glob('*'))
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths) if p.is_file()}


def run(cmd, cwd=ROOT, timeout=180):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xu', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    compiler = args.xu.resolve()
    report = dict(compiler=str(compiler), compiler_sha256=digest(compiler),
                  input_sha256=inputs(), results=[])
    with tempfile.TemporaryDirectory(prefix='xu-bufio-conformance-') as tmp:
        tmp = Path(tmp)
        oracle = run(['go', 'run', 'tests/oracles/stdlib_bufio.go'])
        if oracle.returncode:
            raise RuntimeError(oracle.stderr.decode())
        report['go_version'] = run(['go', 'version']).stdout.decode().strip()
        vectors = json.loads((ROOT / 'tests/data/stdlib_bufio_vectors.json').read_text())
        report['rune_vectors'] = len(vectors['hex']) * len(vectors['sizes'])
        for name in FIXTURES:
            fixture = ROOT / 'tests/fixtures' / name
            expected = oracle.stdout if name == 'bufio_boundaries' else (fixture / 'expected.txt').read_bytes()
            frozen_current = (fixture / 'expected.txt').read_bytes() == expected
            for opt in ('O0', 'O3'):
                output = tmp / (name + '-' + opt)
                compiled = run([str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                                'build', str(fixture / 'main.xu'), '-' + opt, '-o', str(output)])
                # Each execution gets an empty directory for its real file I/O.
                work = tmp / (name + '-' + opt + '-work')
                work.mkdir()
                actual = run([str(output)], cwd=work) if compiled.returncode == 0 else compiled
                passed = frozen_current and compiled.returncode == 0 and actual.returncode == 0 and actual.stdout == expected
                row = dict(fixture=name, optimization=opt, passed=passed,
                           oracle='Go bufio' if name == 'bufio_boundaries' else 'Xu explicit capacity/error contract',
                           expected_current=frozen_current, returncode=actual.returncode,
                           stdout_sha256=hashlib.sha256(actual.stdout).hexdigest(),
                           expected_sha256=hashlib.sha256(expected).hexdigest(),
                           expected_lines=len(expected.splitlines()),
                           stderr=actual.stderr.decode(errors='replace'))
                if not passed:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.with_suffix('.' + name + '-' + opt + '.actual').write_bytes(actual.stdout)
                report['results'].append(row)
                print(('PASS' if passed else 'FAIL') + ' ' + name + ' ' + opt, flush=True)
    report['input_changed'] = report['input_sha256'] != inputs()
    report['compiler_changed'] = report['compiler_sha256'] != digest(compiler)
    report['status'] = 'PASS' if all(x['passed'] for x in report['results']) and not report['input_changed'] and not report['compiler_changed'] else 'FAIL'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    raise SystemExit(report['status'] != 'PASS')


if __name__ == '__main__':
    main()
