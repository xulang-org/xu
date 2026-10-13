#!/usr/bin/env python3
"""Compare StrMap lookup, insertion and ownership against the original table."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'tests/data/strmap'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--source', type=Path, default=ROOT / 'src/xu/types/map.xu')
    ap.add_argument('--expect-zero-lookup-allocs', action='store_true')
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    compiler = args.xu.resolve()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    identity = sha(compiler)
    implementation_identity = sha(args.source)
    source_identity = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}
    fixture_identity = {p.name: sha(p) for p in DATA.glob('*.xu')}
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-strmap-') as td:
        work = Path(td)
        shutil.copytree(ROOT / 'src', work / 'src')
        shutil.copytree(ROOT / 'scripts', work / 'scripts')
        # The selected implementation is copied intact into an isolated module.
        (work / 'src/xu/types/map.xu').write_bytes(args.source.read_bytes())
        hook = work / 'src/xu/types/strmap_test.xu'
        hook.write_text((DATA / 'support.xu').read_text() + '\n' +
                        (DATA / 'reference.xu').read_text().removeprefix('@xu/types\n'))
        main_source = work / 'main.xu'
        main_source.write_bytes((DATA / 'main.xu').read_bytes())
        for opt in ('-O0', '-O1'):
            binary = work / ('test' + opt)
            built = subprocess.run([str(work / 'scripts/run_product_compiler.sh'),
                str(compiler), 'build', opt, str(main_source), '-o', str(binary)],
                cwd=work, capture_output=True, text=True, timeout=180,
                env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'))
            if built.returncode:
                raise ValueError(f'{opt}: {built.stderr}')
            run_env = dict(os.environ)
            run_env.pop('XU_HEAP_STATS', None)
            run = subprocess.run([str(binary), 'run_____'], capture_output=True, text=True, timeout=90,
                                 env=run_env)
            if run.returncode or run.stderr or run.stdout != 'strmap reference ok\n':
                raise ValueError(f'{opt}: {run}')
            baseline_run = subprocess.run([str(binary), 'baseline'], capture_output=True, text=True, timeout=90,
                env=dict(run_env, XU_HEAP_STATS='1'))
            baseline = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', baseline_run.stderr)}
            baseline_extra = re.sub(r'xu_heap_stats \w+=\d+\n', '', baseline_run.stderr)
            ledger_run = subprocess.run([str(binary), 'run_____'], capture_output=True, text=True, timeout=90,
                env=dict(run_env, XU_HEAP_STATS='1'))
            ledger = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', ledger_run.stderr)}
            extra = re.sub(r'xu_heap_stats \w+=\d+\n', '', ledger_run.stderr)
            # Entry-point argument/environment roots survive to the exit hook.
            # Equal-length arguments keep their footprint identical in both
            # modes; compare both bytes and net allocations against that root.
            if (baseline_run.returncode or baseline_run.stdout != run.stdout or baseline_extra or len(baseline) != 7 or
                    ledger_run.returncode or ledger_run.stdout != run.stdout or extra or len(ledger) != 7 or
                    ledger['live_bytes'] != baseline['live_bytes'] or
                    ledger['allocs'] - ledger['frees'] != baseline['allocs'] - baseline['frees'] or
                    any(ledger[k] or baseline[k] for k in ('unknown_frees', 'double_frees', 'ledger_overflows'))):
                args.out.with_suffix('.failure.json').write_text(json.dumps(dict(
                    opt=opt, baseline=baseline, actual=ledger,
                    baseline_stdout=baseline_run.stdout, actual_stdout=ledger_run.stdout,
                    baseline_stderr=baseline_run.stderr, actual_stderr=ledger_run.stderr), indent=2) + '\n')
                raise ValueError(f'{opt}: baseline={baseline}, actual={ledger}')
            lookups = []
            for mode in ('lookup00', 'lookupNN'):
                churn = subprocess.run([str(binary), mode], capture_output=True, text=True, timeout=90,
                    env=dict(run_env, XU_HEAP_STATS='1'))
                stats = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', churn.stderr)}
                noise = re.sub(r'xu_heap_stats \w+=\d+\n', '', churn.stderr)
                if (churn.returncode or churn.stdout != run.stdout or noise or len(stats) != 7 or
                        any(stats[k] for k in ('unknown_frees', 'double_frees', 'ledger_overflows'))):
                    raise ValueError(f'{opt}: {mode}: {churn}')
                lookups.append(stats)
            a, b = lookups
            incremental = b['allocs'] - a['allocs']
            if (a['live_bytes'] != b['live_bytes'] or
                    a['allocs'] - a['frees'] != b['allocs'] - b['frees'] or
                    (args.expect_zero_lookup_allocs and incremental != 0)):
                args.out.with_suffix('.failure.json').write_text(json.dumps(dict(
                    opt=opt, reason='borrowed lookup churn', incremental_lookup_allocs=incremental,
                    lookup_ledgers=lookups), indent=2) + '\n')
                raise ValueError(f'{opt}: lookup allocations={incremental}, ledgers={lookups}')
            rows.append(dict(opt=opt, status='PASS', reference_tables=157, structured_keys=2048,
                incremental_lookup_allocs=incremental, lookup_ledgers=lookups,
                heap_ledger=ledger, baseline_heap_ledger=baseline,
                build_stderr=built.stderr, stdout=run.stdout, binary_sha256=sha(binary)))
    if fixture_identity != {p.name: sha(p) for p in DATA.glob('*.xu')}:
        raise ValueError('fixtures changed during differential gate')
    if sha(args.source) != implementation_identity or sha(compiler) != identity or source_identity != {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}:
        raise ValueError('compiler/source changed during differential gate')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(status='PASS', compiler=str(compiler),
        compiler_sha256=identity, implementation_sha256=implementation_identity, source_sha256=source_identity,
        test_source_sha256=fixture_identity, rows=rows), indent=2) + '\n')
    print('PASS: 157 reference tables, exact lookup/update/growth/reset and balanced ownership at O0 and O1')


if __name__ == '__main__':
    main()
