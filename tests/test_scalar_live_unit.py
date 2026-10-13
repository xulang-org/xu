#!/usr/bin/env python3
"""Regress scalar promotion when optimizer tombstones cross the small-unit cap."""
from pathlib import Path
import argparse
import json
import re
import shutil
import subprocess
import tempfile

from test_large_f64_cfg import MODES, ROOT, build, sha

# Fixed checksum/max-flip goldens, also cross-checked with the repository's
# independent C implementation. No candidate output is used as an oracle.
GOLDENS = [(0, 0), (-1, 1), (2, 2), (4, 4), (11, 7), (49, 10), (228, 16)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--modes', default=','.join(MODES))
    args = ap.parse_args()
    compiler, out = args.xu.resolve(), args.out.resolve()
    data = out.with_suffix('')
    data.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'tests/data/compiler_workloads/game/fannkuchredux.xu'
    identity = sha(compiler)
    source_ids = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-live-unit-') as td:
        work = Path(td)
        shutil.copytree(ROOT / 'src', work / 'src')
        shutil.copytree(ROOT / 'scripts', work / 'scripts')
        mir = work / 'src/xu/types/mir.xu'
        text = mir.read_text()
        call = re.search(r'        mir_each_promote_scalar_locals\(m, ([a-z_]+)\)', text)
        assert call
        observer_call = ('        eprintln("[TEST-LIVE-UNIT] records=" + str(m.fns.len) + '
                        '" live=" + str(mir_nfn_live(&*m)) + " admit=" + str(' + call[1] + '))\n')
        mir.write_text(text.replace(call[0], observer_call + call[0]))
        promote = work / 'src/xu/types/mir_17_opt_promote.xu'
        text = promote.read_text()
        seam = '            npromoted := mir_promote_scalar_locals_ssa_f(mut &f)'
        assert text.count(seam) == 1
        promote.write_text(text.replace(seam, seam + '\n            eprintln("[TEST-LIVE-PROMOTE] " + f.name + " count=" + str(npromoted))'))
        srcs = [work / 'src/cmd/compile/main.xu', *sorted(p for p in (work / 'src/cmd/compile').glob('*.xu') if p.name != 'main.xu')]
        observer = data / 'observer'
        result = subprocess.run([str(work / 'scripts/run_product_compiler.sh'), str(compiler),
            'build', *map(str, srcs), '-o', str(observer)], cwd=work, capture_output=True, timeout=300)
        (data / 'observer.build.log').write_bytes(result.stderr)
        assert result.returncode == 0, result.stderr.decode()
        large = data / 'large-unit.xu'
        text = source.read_text()
        calls = '\n'.join(f'    println(live_helper_{i}(1))' for i in range(35))
        assert text.count('    print_pk(n, checksum, max_flips)') == 1
        text = text.replace('    print_pk(n, checksum, max_flips)', '    print_pk(n, checksum, max_flips)\n' + calls)
        text += '\n' + '\n'.join(f'fn live_helper_{i}(n int) int {{\n'
            f'    if n <= 0 {{ << {i} }}\n    << live_helper_{i}(n - 1) + 1\n}}' for i in range(35))
        large.write_text(text)
        extra = ('\n'.join(str(i + 1) for i in range(35)) + '\n').encode()
        for case, input_source, expected_admission, suffix in (
                ('tombstones-only', source, True, b''), ('genuine-large-unit', large, False, extra)):
            for mode in args.modes.split(','):
                binary, observed = data / (case + '-' + mode), data / (case + '-' + mode + '-observed')
                build(compiler, input_source, binary, MODES[mode])
                diagnostics = build(observer, input_source, observed, MODES[mode])
                (data / (case + '-' + mode + '.log')).write_text(diagnostics)
                assert binary.read_bytes() == observed.read_bytes(), (mode, 'observer changes emitted program')
                for n, (checksum, max_flips) in enumerate(GOLDENS, 1):
                    expected = f'{checksum}\nPfannkuchen({n}) = {max_flips}\n'.encode() + suffix
                    result = subprocess.run([str(binary), str(n)], capture_output=True, timeout=30)
                    assert result.returncode == 0 and result.stdout == expected and not result.stderr, (mode, n, result)
                row = dict(case=case, mode=mode, binary_sha256=sha(binary), executions=len(GOLDENS), status='PASS')
                if mode != 'O0':
                    match = re.search(r'\[TEST-LIVE-UNIT\] records=(\d+) live=(\d+) admit=(true|false)', diagnostics)
                    assert match
                    records, live, admitted = match.groups()
                    row.update(records=int(records), live=int(live), admitted=admitted)
                    assert (int(live) < 64) == expected_admission, (mode, row)
                    assert admitted == ('true' if expected_admission else 'false'), (mode, row)
                    if expected_admission and mode in ('O3', 'ra0'):
                        assert int(records) >= 64, (mode, 'does not cross tombstone cap', row)
                    promoted = re.findall(r'\[TEST-LIVE-PROMOTE\] flips_of count=(\d+)', diagnostics)
                    if expected_admission:
                        assert promoted and int(promoted[-1]) > 0, (mode, 'hot loop not promoted')
                        row['flips_of_promoted_locals'] = int(promoted[-1])
                    else:
                        assert not promoted, (mode, 'large integer unit admitted')
                rows.append(row)
    assert sha(compiler) == identity
    assert source_ids == {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}
    out.write_text(json.dumps(dict(status='PASS', compiler_sha256=identity, source_sha256=source_ids,
        fixture_sha256=sha(source), rows=rows, scope='Actual scalar promotion at the source pipeline boundary; live-vs-record count and promoted hot-loop locals observed only in a private compiler; emitted program bytes equal product output; fixed mathematical checksum/flip goldens.'), indent=2) + '\n')
    print(f'PASS: {len(rows)} modes, {len(rows) * len(GOLDENS)} executions')


if __name__ == '__main__':
    main()
