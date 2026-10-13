#!/usr/bin/env python3
"""Compare the real emitter hotspot algorithm with its fixed-point reference."""
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
DATA = ROOT / 'tests/data/loop_hot_cost'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--source', type=Path, default=ROOT / 'src/cmd/compile/emit_ra_ls.xu')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    compiler = args.xu.resolve()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    identity = sha(compiler)
    source_identity = sha(args.source)
    source = args.source.read_text()
    start = source.index('fn natural_loop_hot_blocks(')
    end = source.index('\nfn ', start + 4)
    algorithm = source[start:end].replace('types.', '').replace(
        'natural_loop_hot_blocks', 'loop_hot_current', 1)
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-loop-hot-') as td:
        work = Path(td)
        shutil.copytree(ROOT / 'src', work / 'src')
        shutil.copytree(ROOT / 'scripts', work / 'scripts')
        # Only the test copy exposes private types and the extracted, unaltered
        # algorithm body. Product module/ABI visibility is unchanged.
        hook = work / 'src/xu/types/loop_hot_cost_test.xu'
        hook.write_text((DATA / 'support.xu').read_text() + '\n' +
                        (DATA / 'reference.xu').read_text() + '\n' + algorithm)
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
            if run.returncode or run.stderr or run.stdout != 'loop hotspot reference ok\n':
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
            rows.append(dict(opt=opt, status='PASS', graph_cases=1072, heap_ledger=ledger, baseline_heap_ledger=baseline,
                build_stderr=built.stderr, stdout=run.stdout, binary_sha256=sha(binary)))
    if sha(compiler) != identity or sha(args.source) != source_identity:
        raise ValueError('compiler/algorithm changed during differential gate')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(status='PASS', compiler=str(compiler),
        compiler_sha256=identity, algorithm_source_sha256=source_identity,
        test_source_sha256={p.name: sha(p) for p in DATA.glob('*.xu')}, rows=rows), indent=2) + '\n')
    print('PASS: 1072 exact hotspot graph comparisons at O0 and O1')


if __name__ == '__main__':
    main()
