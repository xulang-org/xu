#!/usr/bin/env python3
"""Compile the hosted select/cancellation fixture on all eight release targets.

This gate records compile-only evidence; it never claims foreign native runs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ('macos-arm64', 'macos-x64', 'linux-arm64', 'linux-x64',
           'windows-x64', 'windows-arm64', 'linux-loongarch64', 'linux-riscv64')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    return {str(p.relative_to(ROOT)): digest(p)
            for p in sorted((ROOT / 'src').rglob('*.xu'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xu', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    compiler = args.xu.resolve()
    driver = ROOT / 'tests/fixtures/time_cancel_race/main.xu'
    report = dict(compiler=str(compiler), compiler_sha256=digest(compiler),
                  driver_sha256=digest(driver), harness_sha256=digest(__file__),
                  source_sha256=sources(), results=[])
    with tempfile.TemporaryDirectory(prefix='xu-wait-targets-') as tmp:
        for target in TARGETS:
            output = Path(tmp) / target
            run = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                                  'build', str(driver), '--target', target, '-o', str(output)],
                                 cwd=ROOT, capture_output=True, text=True, timeout=90)
            binaries = {p.name: digest(p) for p in Path(tmp).glob(target + '*') if p.is_file()}
            row = dict(target=target, mode='compile-only', passed=run.returncode == 0 and bool(binaries),
                       returncode=run.returncode, stdout=run.stdout, stderr=run.stderr, binaries=binaries)
            report['results'].append(row)
            print(('PASS' if row['passed'] else 'FAIL') + ' ' + target, flush=True)
    report['source_changed'] = report['source_sha256'] != sources()
    report['status'] = 'PASS' if all(x['passed'] for x in report['results']) and not report['source_changed'] else 'FAIL'
    assert digest(compiler) == report['compiler_sha256']
    assert digest(driver) == report['driver_sha256']
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    raise SystemExit(report['status'] != 'PASS')


if __name__ == '__main__':
    main()
