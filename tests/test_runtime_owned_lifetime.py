#!/usr/bin/env python3
"""Hosted resource gate for borrowed values and completed task records."""
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
FIELDS = {'live_bytes', 'peak_bytes', 'allocs', 'frees', 'unknown_frees',
          'double_frees', 'ledger_overflows'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def boundary():
    p = subprocess.run(['python3', str(ROOT / 'scripts/check_bootstrap_xu_boundary.py'),
                        '--strict-freeze', '--json'], cwd=ROOT, capture_output=True,
                       text=True, check=True, timeout=120)
    return json.loads(p.stdout)['source_manifest']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xu', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--modes', default='-O0,-O1,-O2', help='Comma-separated compiler argument groups')
    args = parser.parse_args()
    compiler = args.xu.resolve()
    identity = digest(compiler)
    source_identity = boundary()
    sidecar = Path(str(compiler) + '.provenance')
    provenance = sidecar.read_text() if sidecar.exists() else None
    report = dict(compiler=str(compiler), compiler_sha256=identity,
                  provenance=provenance, source_manifest=source_identity,
                  wrapper='scripts/run_product_compiler.sh', results=[])
    with tempfile.TemporaryDirectory(prefix='xu-owned-lifetime-') as tmp:
        work = Path(tmp)
        cases = []
        for n in (1, 100, 1000):
            source = (ROOT / 'tests/fixtures/spawn_recycle/main.xu').read_text()
            cases.append((f'spawn-{n}', source.replace('0:1000', f'0:{n}'),
                          f'{n * (n - 1) // 2}\n', 240))
        for n in (1000,):
            source = (ROOT / 'tests/fixtures/spawn_owned_nested/main.xu').read_text().replace('0:100', f'0:{n}')
            golden = sum(len('heap' + str(i)) + 3 * i + 1 for i in range(n))
            cases.append(('spawn_owned_nested-1000', source, f'{golden}\n', 232))
        for name, live in [('runtime_borrow_calls', 0), ('runtime_borrow_buffer_fields', 0), ('runtime_borrow_fixed_fields', 0), ('runtime_ref_layout_scopes', 0), ('runtime_map_algorithms', 0), ('spawn_owned_nested', 232),
                           ('spawn_many_args_unbuffered', 232), ('xu_many_args', 264)]:
            fixture = ROOT / 'tests/fixtures' / name
            cases.append((name, (fixture / 'main.xu').read_text(),
                          (fixture / 'expected.txt').read_text(), live))
        for n in (0, 10000):
            source = f"""
@main
#runtime
fn main() int {{
    s := "abc" + str(12)
    prefix := "a"
    pred := runtime.starts_with
    mut hits := 0
    for i in 0:{n} {{
        if starts_with(s, prefix) {{ hits += 1 }}
        if runtime.starts_with(&s, &prefix) {{ hits += 1 }}
        if pred(&s, &prefix) {{ hits += 1 }}
    }}
    println(hits)
    << 0
}}
"""
            cases.append((f'borrow-loop-{n}', source, f'{n * 3}\n', 0))
            buffer_source = source.replace('fn main() int {', 'struct Box {\n    pad int\n    value string\n}\nfn main() int {')
            buffer_source = buffer_source.replace('    prefix := "a"', '    boxes := [Box{pad: 42, value: "abc" + str(12)}]\n    prefix := "a"')
            buffer_source = buffer_source.replace('        if pred(&s, &prefix) { hits += 1 }', '''        if pred(&s, &prefix) { hits += 1 }
        if starts_with(boxes[0].value, prefix) { hits += 1 }
        if runtime.starts_with(&boxes[0].value, &prefix) { hits += 1 }
        if pred(&boxes[0].value, &prefix) { hits += 1 }''')
            cases.append((f'buffer-loop-{n}', buffer_source, f'{n * 6}\n', 0))
        cases.append(('string_from_fixed_bytes',
                      (ROOT / 'tests/fixtures/string_from_fixed_bytes/main.xu').read_text(),
                      (ROOT / 'tests/fixtures/string_from_fixed_bytes/expected.txt').read_text(), 0))
        for empty in (False, True):
            value = '[]int{}' if empty else '[3]int{65, 66, 67}'
            source = '@main\nfn main() int {\n    mut total := 0\n    for i in 0:1000 {\n        s := string_from_bytes(' + value + ')\n        total += s.len\n    }\n    println(total)\n    << 0\n}\n'
            cases.append(('bytes-copy-loop-' + str(empty), source,
                          '0\n' if empty else '3000\n', 0))
        for opt in args.modes.split(','):
            for name, source, golden, expected_live in cases:
                src = work / f'{name}.xu'
                # A channel rendezvous precedes the sender's return. Let completed
                # peers leave their G stacks before collecting the exit ledger.
                source = source.lstrip().rsplit('<< 0', 1)[0] + 'sleep_ns(50000000)\n    << 0' + source.rsplit('<< 0', 1)[1]
                src.write_text(source)
                binary = work / f'{name}-{opt[1:]}'
                env = dict(os.environ, XU_GEN1_HEAP_LEDGER='1')
                build = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'),
                                        str(compiler), 'build', *shlex.split(opt), str(src), '-o', str(binary)],
                                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
                if build.returncode:
                    raise ValueError(f'{name}/{opt}: build failed: {build.stderr}')
                run = subprocess.run([str(binary)], cwd=work,
                                     env=dict(os.environ, XU_HEAP_STATS='1'),
                                     capture_output=True, text=True, timeout=30)
                stats = {}
                for line in run.stderr.splitlines():
                    match = re.fullmatch(r'xu_heap_stats ([a-z_]+)=([0-9]+)', line)
                    if not match or match[1] in stats:
                        raise ValueError(f'{name}/{opt}: invalid ledger line: {line!r}')
                    stats[match[1]] = int(match[2])
                if stats.keys() != FIELDS or run.returncode or run.stdout != golden:
                    raise ValueError(f'{name}/{opt}: golden/ledger failed: {run}')
                if name.startswith('bytes-copy-loop-'):
                    expected_allocs = 0 if name.endswith('True') else 1000
                    if stats['allocs'] != expected_allocs or stats['frees'] != expected_allocs:
                        raise ValueError(f'{name}/{opt}: constructor allocation count failed: {stats}')
                # Unbuffered peers retain only the bounded 32-node, 64-byte waiter pool.
                remaining = stats['live_bytes'] - expected_live
                pool_ok = (name.startswith('spawn_owned_nested') or name in {'spawn_many_args_unbuffered', 'xu_many_args'}) and 0 <= remaining <= 32 * 64 and remaining % 64 == 0
                retained = (1 if expected_live else 0) + remaining // 64
                if (remaining != 0 and not pool_ok) or stats['allocs'] - stats['frees'] != retained or any(stats[k] for k in
                        ('unknown_frees', 'double_frees', 'ledger_overflows')):
                    raise ValueError(f'{name}/{opt}: resource invariant failed: {stats}')
                report['results'].append(dict(name=name, opt=opt, source=source,
                    source_sha256=digest(src), binary_sha256=digest(binary), stats=stats))
                print(f'PASS {name} {opt} live={stats["live_bytes"]} allocs={stats["allocs"]} frees={stats["frees"]}')
    for opt in args.modes.split(','):
        for prefix in ('borrow-loop-', 'buffer-loop-'):
            pair = [r['stats']['allocs'] for r in report['results']
                    if r['opt'] == opt and r['name'].startswith(prefix)]
            if len(pair) != 2 or pair[0] != pair[1]:
                raise ValueError(f'{opt}/{prefix}: predicates allocated per call: {pair}')
    if digest(compiler) != identity or boundary() != source_identity:
        raise ValueError('compiler/source identity changed during resource gate')
    report['status'] = 'PASS'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
