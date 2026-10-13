#!/usr/bin/env python3
"""Check bounded string copies, medium reuse, and codec semantics on product Xu."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'macos-arm64': 'Mach-O 64-bit executable arm64',
    'macos-x64': 'Mach-O 64-bit executable x86_64',
    'linux-arm64': 'ELF 64-bit LSB executable, ARM aarch64',
    'linux-x64': 'ELF 64-bit LSB executable, x86-64',
    'windows-x64': 'PE32+ executable',
    'windows-arm64': 'PE32+ executable',
    'linux-loongarch64': 'ELF 64-bit LSB executable, LoongArch',
    'linux-riscv64': 'ELF 64-bit LSB executable, UCB RISC-V',
}
FIELDS = {'live_bytes', 'peak_bytes', 'allocs', 'frees', 'unknown_frees',
          'double_frees', 'ledger_overflows'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def closure():
    return json.loads(subprocess.check_output([
        'python3', 'scripts/check_bootstrap_xu_boundary.py',
        '--strict-freeze', '--json'], cwd=ROOT))['source_manifest']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--modes', default='-O0,-O3')
    ap.add_argument('--targets', default=','.join(TARGETS))
    args = ap.parse_args()
    compiler = args.xu.resolve()
    identity, source_identity = sha(compiler), closure()
    report = dict(compiler=str(compiler), compiler_sha256=identity,
                  source_manifest=source_identity, native=[], cross=[])
    names = ['character_copy_boundaries', 'medium_buffer_reuse',
             'character_condition_ownership', 'character_search_prepared',
             'character_repeat_edges', 'character_lookup_table', 'base64_decode_matrix', 'base64_bulk_edges', 'hex_byte_matrix', 'hex_lookup_boundaries', 'character_split_byte_edges', 'character_count_byte_edges']
    with tempfile.TemporaryDirectory(prefix='xu-character-runtime-') as tmp:
        work = Path(tmp)
        for mode in args.modes.split(','):
            for name in names:
                src = ROOT / 'tests/fixtures' / name / 'main.xu'
                if not src.exists():
                    raise ValueError(f'missing required fixture: {name}')
                exe = work / name
                p = subprocess.run(['scripts/run_product_compiler.sh', str(compiler),
                                    'build', str(src), *shlex.split(mode), '-o', str(exe)],
                                   cwd=ROOT, env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'),
                                   capture_output=True, text=True, timeout=120)
                if p.returncode:
                    raise ValueError((name, mode, p.stderr))
                p = subprocess.run([str(exe)], cwd=work,
                                   env=dict(os.environ, XU_HEAP_STATS='1'),
                                   capture_output=True, text=True, timeout=60)
                stats = {}
                for line in p.stderr.splitlines():
                    match = re.fullmatch(r'xu_heap_stats ([a-z_]+)=([0-9]+)', line)
                    if not match or match[1] in stats:
                        raise ValueError((name, mode, line))
                    stats[match[1]] = int(match[2])
                if p.returncode or p.stdout != (src.parent/'expected.txt').read_text():
                    raise ValueError((name, mode, p))
                if stats.keys() != FIELDS or stats['allocs'] != stats['frees'] or any(
                        stats[k] for k in ('live_bytes', 'unknown_frees', 'double_frees', 'ledger_overflows')):
                    raise ValueError((name, mode, stats))
                report['native'].append(dict(name=name, mode=mode, stats=stats,
                                             source_sha256=sha(src), binary_sha256=sha(exe)))
                print('PASS ledger', name, mode, stats, flush=True)
            # Rendezvous can precede task-record cleanup; use the existing
            # fixture contract (golden/exit) for concurrent allocation stress.
            name = 'medium_buffer_concurrent'
            src = ROOT / 'tests/fixtures' / name / 'main.xu'
            exe = work / name
            p = subprocess.run(['scripts/run_product_compiler.sh', str(compiler), 'build',
                                str(src), *shlex.split(mode), '-o', str(exe)], cwd=ROOT,
                               capture_output=True, text=True, timeout=120)
            if p.returncode:
                raise ValueError((name, mode, p.stderr))
            for run in range(5):
                p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
                if p.returncode or p.stdout != (src.parent/'expected.txt').read_text() or p.stderr:
                    raise ValueError((name, mode, run, p))
            report['native'].append(dict(name=name, mode=mode, repetitions=5,
                                         source_sha256=sha(src), binary_sha256=sha(exe)))
            print('PASS concurrent', mode, flush=True)
            for target in args.targets.split(','):
                for name in ['character_copy_boundaries', 'medium_buffer_reuse',
                             'medium_buffer_concurrent', 'character_repeat_edges',
                             'character_lookup_table', 'base64_decode_matrix', 'base64_bulk_edges', 'hex_byte_matrix', 'hex_lookup_boundaries', 'character_split_byte_edges', 'character_count_byte_edges']:
                    src = ROOT / 'tests/fixtures' / name / 'main.xu'
                    exe = work / (name+'-'+target+('.exe' if target.startswith('windows-') else ''))
                    p = subprocess.run(['scripts/run_product_compiler.sh', str(compiler), 'build',
                                        str(src), *shlex.split(mode), '--target', target, '-o', str(exe)],
                                       cwd=ROOT, capture_output=True, text=True, timeout=120)
                    fmt = subprocess.check_output(['file', str(exe)], text=True) if not p.returncode else ''
                    if p.returncode or TARGETS[target] not in fmt:
                        raise ValueError((name, mode, target, p.stderr, fmt))
                    report['cross'].append(dict(name=name, mode=mode, target=target,
                                                binary_sha256=sha(exe), format=fmt.strip(),
                                                validation='compile/format'))
                print('PASS cross compile/format', target, mode, flush=True)
    if identity != sha(compiler) or source_identity != closure():
        raise ValueError('compiler/source changed during verification')
    report['status'] = 'PASS'
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print('PASS:', len(report['native']), 'native cases;', len(report['cross']), 'cross builds')


if __name__ == '__main__':
    main()
