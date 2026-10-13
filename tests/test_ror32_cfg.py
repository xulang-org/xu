#!/usr/bin/env python3
"""Verify rotate selection with observable high bits and a real indexed CFG."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MODES = (['-O0'], ['-O1'], ['-O2'], ['-O3'],
         ['-O1', '--no-regcache'], ['-O3', '--ra=0'])


def machine_counts(binary, objdump):
    asm = subprocess.check_output([str(objdump), '--macho', '--disassemble',
                                   str(binary)], text=True)
    dwarf = subprocess.check_output(['dwarfdump', '--debug-info', str(binary)], text=True)
    ranges = []
    for block in re.split(r'0x[0-9a-f]+:\s+DW_TAG_subprogram', dwarf)[1:]:
        name = re.search(r'DW_AT_name\s+\("([^"\n]+)"\)', block)
        low = re.search(r'DW_AT_low_pc\s+\(0x([0-9a-f]+)\)', block)
        high = re.search(r'DW_AT_high_pc\s+\(0x([0-9a-f]+)\)', block)
        if name and low and high:
            ranges.append((name[1], int(low[1], 16), int(high[1], 16)))
    instructions = []
    for line in asm.splitlines():
        match = re.match(r'^([0-9a-f]+):\s+(?:[0-9a-f]{2}\s+){4}(\S+)\s*(.*)', line)
        if match:
            instructions.append((int(match[1], 16), match[2], match[3]))
    counts = {}
    for name, low, high in ranges:
        if name not in ('compress_words', 'roll_left', 'roll_right', 'unbounded', 'wide_result', 'bounded_loop', 'invalidated_loop', 'escaped_source', 'shared_intermediate'):
            continue
        # The final DWARF range can include appended runtime code.
        assert high < max(end for _, _, end in ranges), name
        counts[name] = sum(op == 'ror' and re.match(r'w\d+, w\d+, #', args) is not None
                           for address, op, args in instructions if low <= address < high)
    return counts, asm, dwarf


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--source-root', type=Path, default=ROOT)
    ap.add_argument('--objdump', type=Path,
                    default=Path('/opt/homebrew/opt/llvm/bin/llvm-objdump'))
    args = ap.parse_args()
    assert platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native machine-code gate needs macOS arm64'
    root, compiler, out = args.source_root.resolve(), args.xu.resolve(), args.out.resolve()
    identity = hashlib.sha256(compiler.read_bytes()).hexdigest()
    artifacts = out.with_suffix('')
    artifacts.mkdir(parents=True, exist_ok=True)
    h = b'The quick brown fox jumps over the lazy dog'
    for _ in range(100000):
        h = hashlib.md5(h).hexdigest().encode()
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-ror32-') as directory:
        work = Path(directory)
        md5_source = work / 'md5.xu'
        shutil.copy2(ROOT / 'tests/data/compiler_workloads/md5_chain.xu', md5_source)
        fixture = ROOT / 'tests/fixtures/ror32_long_cfg/main.xu'
        for flags in MODES:
            enabled = len(flags) == 1 and flags[0] != '-O0'
            for case, source, golden, plans in (
                    ('md5', md5_source, h.decode() + '\n', 1),
                    ('cfg', fixture, fixture.with_name('expected.txt').read_text(), 4),
                    ('invariant', ROOT / 'tests/fixtures/ror32_invariant_cfg/main.xu',
                     (ROOT / 'tests/fixtures/ror32_invariant_cfg/expected.txt').read_text(), None)):
                binary = artifacts / (case + '-' + '-'.join(flag.lstrip('-') for flag in flags))
                built = subprocess.run([str(root / 'scripts/run_product_compiler.sh'),
                    str(compiler), 'build', *flags, '--debug', '--timings', str(source),
                    '-o', str(binary)], cwd=root, capture_output=True, text=True, timeout=120,
                    env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'))
                row = dict(case=case, flags=flags, build_exit=built.returncode,
                           build_stderr=built.stderr, status='FAIL')
                if not built.returncode:
                    run = subprocess.run([str(binary)], capture_output=True, text=True,
                        timeout=60, env=dict(os.environ, XU_HEAP_STATS='1'))
                    ledger = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', run.stderr)}
                    other = re.sub(r'xu_heap_stats \w+=\d+\n', '', run.stderr)
                    counts, asm, dwarf = machine_counts(binary, args.objdump)
                    binary.with_suffix('.asm').write_text(asm)
                    binary.with_suffix('.dwarf').write_text(dwarf)
                    stats = re.search(r'ra-stats:.*?try=(\d+) vreg=(\d+)', built.stderr)
                    plan_ok = plans is None or bool(stats and int(stats[1]) == int(enabled) * plans
                                   and int(stats[2]) == int(enabled) * plans)
                    wanted = {'compress_words': 64} if case == 'md5' else {
                        'roll_left': 64, 'roll_right': 64, 'unbounded': 0, 'wide_result': 0}
                    if case == 'invariant':
                        wanted = {'bounded_loop': 64, 'invalidated_loop': 63,
                                  'escaped_source': 0, 'shared_intermediate': 0}
                    # Fallback builds must preserve high bits too. Their safe
                    # rotate counts can differ, so only demand positive fixed
                    # selection when the planner is enabled.
                    if enabled:
                        selection_ok = counts == wanted
                    elif case == 'md5':
                        selection_ok = True
                    else:
                        forbidden = ('unbounded', 'wide_result') if case == 'cfg' else ('escaped_source', 'shared_intermediate')
                        selection_ok = all(counts.get(name) == 0 for name in forbidden)
                    ledger_ok = (len(ledger) == 7 and ledger['live_bytes'] == 0
                        and ledger['allocs'] == ledger['frees'] and all(ledger[k] == 0
                        for k in ('unknown_frees', 'double_frees', 'ledger_overflows')))
                    ok = (run.returncode == 0 and run.stdout == golden and not other
                          and ledger_ok and plan_ok and selection_ok)
                    row.update(status='PASS' if ok else 'FAIL', stdout=run.stdout,
                        stderr=run.stderr, ledger=ledger, machine_counts=counts,
                        expected_fixed_counts=wanted if enabled else None,
                        planning=plan_ok, selection=selection_ok,
                        golden_match=run.stdout == golden)
                rows.append(row)
                print(case, flags, row['status'], row.get('machine_counts'), flush=True)
    assert hashlib.sha256(compiler.read_bytes()).hexdigest() == identity
    out.write_text(json.dumps(dict(status='PASS' if all(row['status'] == 'PASS' for row in rows)
        else 'FAIL', compiler_sha256=identity, rows=rows), indent=2) + '\n')
    return any(row['status'] != 'PASS' for row in rows)


if __name__ == '__main__':
    raise SystemExit(main())
