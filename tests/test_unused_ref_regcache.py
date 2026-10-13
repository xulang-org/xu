#!/usr/bin/env python3
"""Verify fixed FP homes for scalar loops and unused borrowed parameters.

The planner owns the same registers as RegCache, so positive fixed-home
admission requires vreg=1 and rc=0, not a legacy rc counter. A diagnostic
compiler copy verifies the named kernel's actual FP home and must produce
byte-identical executables to the unmodified compiler. Single-accumulator
self-loops retain their existing proven FP cache; multi-carried self-loops
still require whole-CFG homes.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'tests/data/unused_ref_regcache'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--source-root', type=Path, default=ROOT,
                    help='Matching compiler source snapshot for the diagnostic observer')
    args = ap.parse_args()
    compiler = args.xu.resolve()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    identity = sha(compiler)
    cases = json.loads((DATA / 'cases.json').read_text())
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-unused-ref-') as td:
        work = Path(td)
        shutil.copytree(args.source_root.resolve() / 'src', work / 'src')
        shutil.copytree(ROOT / 'scripts', work / 'scripts')
        emit = work / 'src/cmd/compile/emit_function.xu'
        text = emit.read_text()
        seam = '    ra_note_fn(a, try_vregs, has_vreg, a.rc_on, scalar_spills)'
        assert text.count(seam) == 1
        emit.write_text(text.replace(seam, seam + '''
    mut fp_name := ""
    for fp_i in 0:types.mir_fn_name_len(m, fi) { fp_name.push_byte(types.mir_fn_name_byte(m, fi, fp_i)) }
    eprintln("[TEST-PURE-FP] " + fp_name + " try=" + str(try_vregs) + " vreg=" + str(has_vreg) + " fp=" + str(frame_plan_uses_fp(&fr)) + " cache=" + str(rc_fp_on(&*a)))
'''))
        observer = work / 'observer'
        sources = [work / 'src/cmd/compile/main.xu', *sorted(p for p in
                   (work / 'src/cmd/compile').glob('*.xu') if p.name != 'main.xu')]
        built_observer = subprocess.run([str(work / 'scripts/run_product_compiler.sh'),
            str(compiler), 'build', *map(str, sources), '-o', str(observer)],
            cwd=work, capture_output=True, text=True, timeout=300)
        if built_observer.returncode:
            raise ValueError(built_observer.stderr)
        for case in cases:
            for flags in (['-O0'], ['-O1'], ['-O2'], ['-O3'], ['--no-regcache'], ['-O3', '--ra=0']):
                binary = work / 'program'
                cmd = [str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                       'build', *flags, '--timings', str(DATA / (case['name'] + '.xu')),
                       '-o', str(binary)]
                build_env = dict(os.environ, XU_GEN1_HEAP_LEDGER='1')
                built = subprocess.run(cmd, env=build_env, capture_output=True, text=True, timeout=90)
                if built.returncode:
                    raise ValueError(f"{case['name']} {flags}: {built.stderr}")
                match = re.search(r'ra-stats: ([^\n]+)', built.stderr)
                if not match:
                    raise ValueError(f'missing RA stats: {built.stderr}')
                stats = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', match[1])}
                enabled = flags[0] in ('-O1', '-O2', '-O3') and '--ra=0' not in flags
                # Read-only indexed kernels already had whole-CFG plans. The
                # write case must retain its conservative frame fallback.
                expected_plan = enabled and (case['admit'] or case['name'] in
                                              ('used_array', 'used_array_alias'))
                observed_binary = work / 'observed-program'
                observed = subprocess.run([str(work / 'scripts/run_product_compiler.sh'),
                    str(observer), 'build', *flags, str(DATA / (case['name'] + '.xu')),
                    '-o', str(observed_binary)], env=build_env, cwd=work,
                    capture_output=True, text=True, timeout=90)
                if observed.returncode or sha(observed_binary) != sha(binary):
                    raise ValueError(f'observer changed program bytes: {observed.stderr}')
                kernel = re.search(r'\[TEST-PURE-FP\] ' + re.escape(case.get('function', 'kernel')) + r' try=(true|false) vreg=(true|false) fp=(true|false) cache=(true|false)', observed.stderr)
                if not kernel:
                    raise ValueError(f'missing kernel observation: {observed.stderr}')
                expected_cache = enabled and case.get('cache', False)
                expected_flags = (('true',) * 3 if expected_plan else ('false',) * 3) + (('true' if expected_cache else 'false'),)
                run = subprocess.run([str(binary)], env=dict(os.environ, XU_HEAP_STATS='1',
                    XU_HEAP_CHECK='1'), capture_output=True, text=True, timeout=30)
                ledger = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', run.stderr)}
                other_stderr = re.sub(r'xu_heap_stats \w+=\d+\n', '', run.stderr)
                ledger_ok = (len(ledger) == 7 and ledger['live_bytes'] == 0 and
                    ledger['allocs'] == ledger['frees'] and all(ledger[k] == 0 for k in
                    ('unknown_frees', 'double_frees', 'ledger_overflows')))
                ok = (run.returncode == 0 and run.stdout == case['expect'] and
                      not other_stderr and ledger_ok and stats['rc'] == int(expected_cache) and
                      stats['try'] == stats['vreg'] == int(expected_plan) and
                      kernel.groups() == expected_flags)
                rows.append(dict(case=case['name'], flags=flags, status='PASS' if ok else 'FAIL',
                    stats=stats, expected_vreg=int(expected_plan), expected_rc=int(expected_cache),
                    kernel=dict(zip(('try', 'vreg', 'fp', 'cache'), kernel.groups())),
                    observer_byte_identical=True, ledger=ledger, build_stderr=built.stderr,
                    stdout=run.stdout, stderr=run.stderr, exit=run.returncode,
                    binary_sha256=sha(binary)))
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps(dict(status='PASS' if all(r['status'] == 'PASS' for r in rows) else 'FAIL',
                    compiler=str(compiler), compiler_sha256=identity, rows=rows,
                    sources={p.name: sha(p) for p in DATA.glob('*') if p.is_file()}), indent=2) + '\n')
                if not ok:
                    raise ValueError(rows[-1])
    if sha(compiler) != identity:
        raise ValueError('compiler changed during test')
    print(f'PASS: {len(rows)} actual kernel FP plans, identical observer bytes, golden and heap ledger')


if __name__ == '__main__':
    main()
