#!/usr/bin/env python3
"""Exercise byte-to-int loads in long kernels and retain array descriptor fallback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--source-root', type=Path, default=ROOT)
    args = ap.parse_args()
    root = args.source_root.resolve()
    xu = args.xu.resolve()
    identity = hashlib.sha256(xu.read_bytes()).hexdigest()
    source = ROOT / 'tests/fixtures/int_index_long_alu/main.xu'
    golden = source.with_name('expected.txt').read_text()
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-long-integer-') as td:
        for flags in (['-O0'], ['-O1'], ['-O2'], ['-O3'],
                      ['-O1', '--no-regcache'], ['-O3', '--ra=0']):
            binary = Path(td) / 'test'
            built = subprocess.run([str(root / 'scripts/run_product_compiler.sh'), str(xu),
                'build', *flags, '--timings', str(source), '-o', str(binary)], cwd=root,
                capture_output=True, text=True, timeout=120,
                env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'))
            row = dict(flags=flags, build_exit=built.returncode, build_stderr=built.stderr)
            row['status'] = 'FAIL'
            if not built.returncode:
                run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60,
                    env=dict(os.environ, XU_HEAP_STATS='1'))
                ledger = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', run.stderr)}
                extra = re.sub(r'xu_heap_stats \w+=\d+\n', '', run.stderr)
                stats = re.search(r'ra-stats:.*?try=(\d+) vreg=(\d+)', built.stderr)
                # The borrowed string kernel plans; the borrowed []int kernel
                # keeps its three-word array descriptor on the legacy path.
                expected = 1 if len(flags) == 1 and flags[0] != '-O0' else 0
                plan_ok = bool(stats and int(stats[1]) == expected and int(stats[2]) == expected)
                row.update(stdout=run.stdout, stderr=run.stderr, ledger=ledger,
                           expected_plans=expected, planning=plan_ok)
                if (run.returncode == 0 and run.stdout == golden and not extra and plan_ok
                    and len(ledger) == 7 and ledger['live_bytes'] == 0
                    and ledger['allocs'] == ledger['frees']
                    and not any(ledger[k] for k in ('unknown_frees', 'double_frees', 'ledger_overflows'))):
                    row['status'] = 'PASS'
            rows.append(row)
            print(flags, row['status'], row.get('ledger'), flush=True)
    assert hashlib.sha256(xu.read_bytes()).hexdigest() == identity
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(status='PASS' if all(r['status']=='PASS' for r in rows)
        else 'FAIL', compiler_sha256=identity, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        rows=rows), indent=2)+'\n')
    return any(r['status'] != 'PASS' for r in rows)


if __name__ == '__main__':
    raise SystemExit(main())
