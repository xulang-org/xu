#!/usr/bin/env python3
"""Check source declaration order, DWARF ranges and object labels at emission."""
from pathlib import Path
import argparse
import json
import re
import shutil
import struct
import sys
import subprocess
import tempfile

from test_large_f64_cfg import MODES, ROOT, build, sha


def text_address(path):
    data = path.read_bytes()
    pos = 32
    assert data[:4] == b'\xcf\xfa\xed\xfe'
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        command, size = struct.unpack_from('<II', data, pos)
        if command == 25:
            for i in range(struct.unpack_from('<I', data, pos + 64)[0]):
                section = pos + 72 + i * 80
                if data[section:section + 16].rstrip(b'\0') == b'__text':
                    return struct.unpack_from('<Q', data, section + 32)[0]
        pos += size
    raise AssertionError('missing Mach-O text section')


def emitted(diagnostics):
    rows = []
    for line in diagnostics.splitlines():
        match = re.fullmatch(r'\[TEST-EMIT-ORDER\] src=(\d+) start=(\d+)', line)
        if match:
            rows.append(dict(src=int(match[1]), start=int(match[2])))
    assert rows
    assert [x['src'] for x in rows] == sorted(x['src'] for x in rows), rows
    assert all(a['start'] < b['start'] for a, b in zip(rows, rows[1:])), rows
    return rows


def dwarf_ranges(binary, starts, log):
    result = subprocess.run(['dwarfdump', '--debug-info', str(binary)],
                            capture_output=True, text=True, timeout=30, check=True)
    log.write_text(result.stdout + result.stderr)
    blocks = re.split(r'0x[0-9a-f]+:\s+DW_TAG_subprogram', result.stdout)[1:]
    ranges = []
    for block in blocks:
        low = re.search(r'DW_AT_low_pc\s+\(0x([0-9a-f]+)\)', block)
        high = re.search(r'DW_AT_high_pc\s+\(0x([0-9a-f]+)\)', block)
        assert low and high, block
        ranges.append((int(low[1], 16), int(high[1], 16)))
    expected = [text_address(binary) + x['start'] for x in starts]
    assert [x[0] for x in ranges] == expected, (ranges, expected)
    assert all(low < high for low, high in ranges), ranges
    assert all(a[1] == b[0] for a, b in zip(ranges, ranges[1:])), ranges
    return len(ranges)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--modes', default='O3,O0,O1,O2,no-regcache,ra0')
    args = ap.parse_args()
    compiler, out = args.xu.resolve(), args.out.resolve()
    data = out.with_suffix('')
    data.mkdir(parents=True, exist_ok=True)
    identity = sha(compiler)
    source_ids = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}
    cases = [
        ('binarytrees', ROOT / 'tests/data/compiler_workloads/game/binarytrees.xu', ['6'],
         b'stretch tree of depth 7\t check: 255\n64\t trees of depth 4\t check: 1984\n16\t trees of depth 6\t check: 2032\nlong lived tree of depth 6\t check: 127\n'),
        ('fannkuch', ROOT / 'tests/data/compiler_workloads/game/fannkuchredux.xu', ['7'],
         b'228\nPfannkuchen(7) = 16\n'),
    ]
    for name in ('fn_value_basic', 'generic_multi_use'):
        fixture = ROOT / 'tests/fixtures' / name
        cases.append((name, fixture / 'main.xu', [], (fixture / 'expected.txt').read_bytes()))
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-emission-order-') as td:
        work = Path(td)
        shutil.copytree(ROOT / 'src', work / 'src')
        shutil.copytree(ROOT / 'scripts', work / 'scripts')
        source = work / 'src/cmd/compile/emit_function.xu'
        text = source.read_text()
        seam = '\n    a.label(types.mir_fn_label(m, fi))'
        assert text.count(seam) == 1
        source.write_text(text.replace(seam, seam +
            '\n    eprintln("[TEST-EMIT-ORDER] src=" + str(m.fns[fi].src_fi) + " start=" + str(a.code.len))'))
        srcs = [work / 'src/cmd/compile/main.xu', *sorted(p for p in
                (work / 'src/cmd/compile').glob('*.xu') if p.name != 'main.xu')]
        observer = data / 'observer'
        result = subprocess.run([str(work / 'scripts/run_product_compiler.sh'), str(compiler),
            'build', *map(str, srcs), '-o', str(observer)], cwd=work,
            capture_output=True, timeout=300)
        (data / 'observer.build.log').write_bytes(result.stderr)
        assert result.returncode == 0, result.stderr.decode()
        for name, source, inputs, expected in cases:
            for mode in args.modes.split(','):
                for debug in (False, True):
                    stem = f'{name}-{mode}-' + ('debug' if debug else 'plain')
                    binary, observed = data / stem, data / (stem + '-observed')
                    flags = MODES[mode] + (['--debug'] if debug else [])
                    build(compiler, source, binary, flags)
                    diagnostics = build(observer, source, observed, flags)
                    (data / (stem + '.log')).write_text(diagnostics)
                    assert binary.read_bytes() == observed.read_bytes(), stem
                    run = subprocess.run([str(binary), *inputs], capture_output=True, timeout=30)
                    assert run.returncode == 0 and run.stdout == expected and not run.stderr, (stem, run)
                    starts = emitted(diagnostics)
                    dwarf = dwarf_ranges(binary, starts, data / (stem + '.dwarf')) if debug else 0
                    rows.append(dict(case=name, mode=mode, debug=debug, functions=len(starts),
                                     dwarf_functions=dwarf, sha256=sha(binary), status='PASS'))
        # The same numeric declaration order must drive object symbol offsets.
        # These are format/relocation checks; foreign executables are not run.
        for target in ('macos-arm64', 'macos-x64', 'linux-arm64', 'linux-x64',
                       'windows-arm64', 'windows-x64', 'linux-loongarch64', 'linux-riscv64'):
            source = ROOT / 'tests/fixtures/fn_value_basic/main.xu'
            binary, observed = data / (target + '.xuo'), data / (target + '-observed.xuo')
            flags = ['-O3', '--target', target, '--emit-obj']
            build(compiler, source, binary, flags)
            diagnostics = build(observer, source, observed, flags)
            assert binary.read_bytes() == observed.read_bytes(), target
            starts = emitted(diagnostics)
            sys.path.insert(0, str(ROOT / 'scripts'))
            from xuobj_to_macho_o import decode_xuobj
            labels = decode_xuobj(binary.read_bytes())['labs']
            offsets = {offset for _, offset, is_data in labels if not is_data}
            assert all(x['start'] in offsets for x in starts), (target, starts)
            rows.append(dict(case='object', target=target, functions=len(starts),
                             sha256=sha(binary), status='PASS'))
    assert sha(compiler) == identity
    assert source_ids == {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / 'src').rglob('*.xu')}
    out.write_text(json.dumps(dict(status='PASS', compiler_sha256=identity,
        source_sha256=source_ids, rows=rows), indent=2) + '\n')
    print(f'PASS: {len(rows)} configurations, declaration order, DWARF ranges, object labels')


if __name__ == '__main__':
    main()
