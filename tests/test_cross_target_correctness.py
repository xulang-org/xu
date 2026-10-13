#!/usr/bin/env python3
"""Compiler regressions for compare fusion and Windows fd import closure."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODES = {'O0': ['-O0'], 'O1': ['-O1'], 'O2': ['-O2'], 'O3': ['-O3'],
         'no-regcache': ['-O3', '--no-regcache'], 'ra0': ['-O3', '--ra=0']}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pe_imports(path, machine):
    data = path.read_bytes()
    assert data[:2] == b'MZ'
    pe = struct.unpack_from('<I', data, 60)[0]
    assert data[pe:pe + 4] == b'PE\0\0'
    assert struct.unpack_from('<H', data, pe + 4)[0] == machine
    count, optional_size = (struct.unpack_from('<H', data, pe + off)[0] for off in (6, 20))
    optional = pe + 24
    assert struct.unpack_from('<H', data, optional)[0] == 0x20b
    sections = []
    for i in range(count):
        pos = optional + optional_size + i * 40
        virtual_size, virtual, raw_size, raw = struct.unpack_from('<IIII', data, pos + 8)
        sections.append((virtual, max(virtual_size, raw_size), raw, raw_size))

    def offset(rva):
        for virtual, size, raw, raw_size in sections:
            if virtual <= rva < virtual + size:
                assert rva - virtual < raw_size
                return raw + rva - virtual
        raise AssertionError(f'unmapped PE RVA {rva:#x}')

    def string(rva):
        pos = offset(rva)
        return data[pos:data.index(b'\0', pos)].decode('ascii')

    import_rva, import_size = struct.unpack_from('<II', data, optional + 112 + 8)
    assert import_rva and import_size
    result, slots = {}, set()
    for index in range(128):
        descriptor = struct.unpack_from('<IIIII', data, offset(import_rva + index * 20))
        if not any(descriptor):
            break
        lookup, _, _, dll_rva, first_thunk = descriptor
        dll = string(dll_rva).lower()
        lookup = lookup or first_thunk
        names = []
        for j in range(1024):
            thunk = struct.unpack_from('<Q', data, offset(lookup + 8 * j))[0]
            if not thunk:
                break
            assert not thunk & (1 << 63), 'unexpected ordinal import'
            names.append(string(thunk + 2))
            slot = first_thunk + 8 * j
            assert slot % 8 == 0 and slot not in slots
            offset(slot)
            slots.add(slot)
        else:
            raise AssertionError('unterminated import thunks')
        assert len(names) == len(set(names)), names
        result[dll] = names
    else:
        raise AssertionError('unterminated import descriptors')
    return result


def cases():
    values = [0, 7, 228, -16, 9223372036854775807, -9223372036854775808]
    expressions = ['(0 - 9223372036854775807 - 1)' if v == -(1 << 63) else str(v) for v in values]
    strings = '@main\nfn main() {\n' + '\n'.join(f'println(str({v}))' for v in expressions) + '\n}\n'
    init = '''@main
fn observe(p &mut [12]int) { for i in 0:7 { println(p[i]) } }
fn main() {
    n := 7
    mut p := [12]int{}
    mut i := 0
    while i < n { p[i] = i
        i += 1 }
    observe(mut &p)
}
'''
    fann = (ROOT / 'tests/data/compiler_workloads/game/fannkuchredux.xu').read_text()
    assert fann.count('n := parse_n(12)') == 1
    fann = fann.replace('n := parse_n(12)', 'n := 7')
    return [('str', strings, ('\n'.join(map(str, values)) + '\n').encode()),
            ('init', init, b'0\n1\n2\n3\n4\n5\n6\n'),
            ('fannkuch', fann, b'228\nPfannkuchen(7) = 16\n')]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--modes', default=','.join(MODES))
    ap.add_argument('--targets', default='native,linux-riscv64,linux-loongarch64,windows-x64,windows-arm64')
    args = ap.parse_args()
    compiler, report = args.xu.resolve(), args.out.resolve()
    lane = report.with_suffix('')
    lane.mkdir(parents=True, exist_ok=True)
    identity = sha(compiler)
    rows = []

    def build(name, source, target, mode):
        suffix = '.exe' if target.startswith('windows') else ''
        binary = lane / f'{name}-{target}-{mode}{suffix}'
        command = [str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                   'build', str(source), *MODES[mode], '-o', str(binary)]
        if target != 'native':
            command += ['--target', target]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=90)
        (lane / f'{binary.name}.build.log').write_bytes(result.stdout + result.stderr)
        return binary, result

    targets = args.targets.split(',')
    for name, content, expected in cases():
        source = lane / (name + '.xu')
        source.write_text(content)
        for target in targets:
            if target.startswith('windows'):
                continue
            runner = {'linux-riscv64': 'riscv64', 'linux-loongarch64': 'loong64'}.get(target)
            if runner and not shutil.which('qemu-system-' + ('riscv64' if runner == 'riscv64' else 'loongarch64')):
                raise RuntimeError(f'QEMU required for {target}; select explicit --targets to omit it')
            for mode in args.modes.split(','):
                binary, result = build(name, source, target, mode)
                row = dict(case=name, target=target, mode=mode, build_rc=result.returncode)
                if result.returncode == 0:
                    command = ([sys.executable, str(ROOT / f'scripts/{runner}_qemu_run.py'), str(binary), '2']
                               if runner else [str(binary)])
                    run = subprocess.run(command, capture_output=True, timeout=30)
                    passed = (run.returncode == 0 and run.stdout == expected and
                              (b'__EXIT_CODE__=0\n' == run.stderr if runner else not run.stderr))
                    row.update(rc=run.returncode, stdout=run.stdout.decode('utf8', 'replace'),
                               stderr=run.stderr.decode('utf8', 'replace'), sha256=sha(binary))
                else:
                    passed = False
                    row['stderr'] = result.stderr.decode('utf8', 'replace')
                row['status'] = 'PASS' if passed else 'FAIL'
                rows.append(row)
                print(f"{row['status']}: {name} {target} {mode}", flush=True)

    fd_calls = {'open': 'os_open("file", 0)', 'read': 'os_fd_read(0, 1)',
                'write': 'os_fd_write(1, "hello")', 'close': 'os_fd_close(0)'}
    windows_cases = []
    for name, call in fd_calls.items():
        source = lane / f'fd-{name}.xu'
        source.write_text('@main\n#errors\nfn main() {\n' + call + ' or (err) { <<< 1 }\n}\n')
        windows_cases.append(('fd-' + name, source, True))
    windows_cases.append(('mandelbrot', ROOT / 'tests/data/compiler_workloads/game/mandelbrot.xu', True))
    plain = lane / 'plain.xu'
    plain.write_text('@main\nfn main() { println(7) }\n')
    windows_cases.append(('plain', plain, False))
    for target in targets:
        if not target.startswith('windows'):
            continue
        for name, source, needs_file in windows_cases:
            for mode in args.modes.split(','):
                binary, result = build(name, source, target, mode)
                row = dict(case=name, target=target, mode=mode, build_rc=result.returncode)
                try:
                    assert result.returncode == 0, result.stderr.decode()
                    imports = pe_imports(binary, 0x8664 if target == 'windows-x64' else 0xaa64)
                    kernel = set(imports['kernel32.dll'])
                    if needs_file:
                        assert {'CreateFileA', 'ReadFile', 'WriteFile', 'CloseHandle'} <= kernel, imports
                    else:
                        assert 'ReadFile' not in kernel, imports
                    row.update(status='PASS', imports=imports, sha256=sha(binary))
                except (AssertionError, KeyError, ValueError) as error:
                    row.update(status='FAIL', error=str(error))
                rows.append(row)
                print(f"{row['status']}: {name} {target} {mode}", flush=True)
    assert sha(compiler) == identity
    failures = sum(row['status'] != 'PASS' for row in rows)
    report.write_text(json.dumps(dict(status='FAIL' if failures else 'PASS', compiler_sha256=identity,
        configurations=len(rows), failures=failures, rows=rows), indent=2) + '\n')
    print(f'{len(rows) - failures} PASS, {failures} FAIL')
    return int(failures != 0)


if __name__ == '__main__':
    raise SystemExit(main())
