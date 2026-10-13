#!/usr/bin/env python3
"""Run real CPU dispatch paths, including x86 binaries with capabilities off.

The fallback copy changes only the private CPUID cache's initial data, then
re-signs the Mach-O. It adds no test switch or instruction exception to Xu.
Optional Docker runners execute Linux ARM64 and x86-64 ELF files. The x86
runner uses QEMU's qemu64 and max CPU models; ARM64 additionally runs a copy
whose five feature queries return zero. Images are supplied explicitly and
containers use no network and a read-only artifact mount. Other targets are
compilation checks.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import struct
import subprocess

from test_cross_target_correctness import pe_imports

ROOT = Path(__file__).resolve().parents[1]
MODES = {'O0': ['-O0'], 'O1': ['-O1'], 'O2': ['-O2'], 'O3': ['-O3'],
         'no-regcache': ['-O3', '--no-regcache'], 'ra0': ['-O3', '--ra=0']}
FIXTURES = ['math_bits_cpu_dispatch', 'math_bits', 'math_bits_extra',
            'math_bits_scalar_cfg', 'math_bits_peep_chain', 'math_bits_rotate_var',
            'math_bits_len_clz_fusion', 'std_math', 'crypto_aes', 'crypto_aes_conformance',
            'crypto_sha1', 'crypto_sha256', 'hash_crc32', 'crc32_digest',
            'hex_byte_matrix']


def zero_x64_capabilities(binary, destination):
    data = bytearray(binary.read_bytes())
    assert struct.unpack_from('<II', data) == (0xfeedfacf, 0x1000007)
    segments, text = [], None
    pos = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        command, size = struct.unpack_from('<II', data, pos)
        assert size >= 8
        if command == 0x19:
            vm, vm_size, offset, file_size = struct.unpack_from('<QQQQ', data, pos + 24)
            segments.append((vm, vm_size, offset, file_size))
            if bytes(data[pos + 8:pos + 24]).rstrip(b'\0') == b'__TEXT':
                text = (vm, offset, file_size)
        pos += size
    assert text is not None
    vm, offset, size = text
    # lea rax,[rip+cache]; mov rax,[rax]; cmp rax,-1; jne cached.
    matches = list(re.finditer(rb'\x48\x8d\x05....\x48\x8b\x00\x48\x83\xf8\xff\x0f\x85',
                               bytes(data[offset:offset + size]), re.DOTALL))
    assert len(matches) == 1, 'CPU cache query must be uniquely identified'
    query = offset + matches[0].start()
    address = vm + query - offset + 7 + struct.unpack_from('<i', data, query + 3)[0]
    slots = [file_offset + address - base for base, _, file_offset, file_size in segments
             if base <= address and address + 8 <= base + file_size]
    assert len(slots) == 1
    slot = slots[0]
    assert slot % 8 == 0 and data[slot:slot + 8] == b'\xff' * 8
    data[slot:slot + 8] = b'\0' * 8
    destination.write_bytes(data)
    destination.chmod(0o755)
    subprocess.run(['codesign', '--force', '--sign', '-', str(destination)],
                   check=True, capture_output=True)
    return slot


def zero_arm64_queries(binary, destination):
    data = bytearray(binary.read_bytes())
    assert data[:6] == b'\x7fELF\x02\x01'
    assert struct.unpack_from('<H', data, 18)[0] == 183
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phcount = struct.unpack_from('<HH', data, 54)
    patches = []
    # ldr x0,[x8]; lsr x0,x0,#bit; and x0,x0,#1; ret. Restrict
    # matching to executable PT_LOAD segments, with exact query counts.
    for bit, count in ((3, 1), (5, 1), (6, 1), (7, 2)):
        signature = struct.pack('<IIII', 0xf9400100,
                                0xd3400000 | (bit << 16) | (63 << 10),
                                0x92400000, 0xd65f03c0)
        matches = []
        for i in range(phcount):
            kind, flags, offset, _, _, size, _, _ = struct.unpack_from('<IIQQQQQQ', data, phoff + i * phsize)
            if kind == 1 and flags & 1:
                matches += [p for p in range(offset, offset + size - 15, 4)
                            if data[p:p + 16] == signature]
        assert len(matches) == count, (bit, matches)
        patches += [p + 4 for p in matches]
    for offset in patches:
        struct.pack_into('<I', data, offset, 0xd2800000)  # mov x0,#0
    destination.write_bytes(data)
    destination.chmod(0o755)
    return patches


def run(binary, expected, command=None):
    result = subprocess.run(command or [str(binary)], capture_output=True, timeout=60)
    assert result.returncode == 0, (binary, result.returncode, result.stdout.decode(errors='replace'),
                                    result.stderr.decode(errors='replace'))
    assert result.stdout == expected, (binary, result.stdout[:500], expected[:500])
    assert result.stderr == b'', (binary, result.stderr)


def alter_hardware_instruction(binary, destination, arm64):
    data = bytearray(binary.read_bytes())
    if arm64:
        phoff = struct.unpack_from('<Q', data, 32)[0]
        phsize, phcount = struct.unpack_from('<HH', data, 54)
        offsets = []
        for i in range(phcount):
            kind, flags, offset, _, _, size, _, _ = struct.unpack_from('<IIQQQQQQ', data, phoff + i * phsize)
            if kind == 1 and flags & 1:
                offsets += [p for p in range(offset, offset + size - 3, 4)
                            if struct.unpack_from('<I', data, p)[0] & 0xfffffc00 == 0x4e284800]
        assert offsets, 'Expected AESE instructions'
        for offset in offsets:
            struct.pack_into('<I', data, offset, 0xd503201f)  # NOP in place of AESE
    else:
        opcode = bytes.fromhex('f3480fb8c7')  # popcnt rax,rdi
        assert data.count(opcode) == 1
        offsets = [data.index(opcode)]
        data[offsets[0]:offsets[0] + len(opcode)] = bytes.fromhex('31c0909090')  # xor eax,eax; NOPs
    destination.write_bytes(data)
    destination.chmod(0o755)
    return offsets


def expect_hardware_change(command, expected):
    result = subprocess.run(command, capture_output=True, timeout=60)
    assert result.returncode == 0 and not result.stderr and result.stdout != expected, (
        result.returncode, result.stdout, result.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xu', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--targets', default='native')
    parser.add_argument('--compile-only-targets', default='',
                        help='Explicit target list to compile without execution')
    parser.add_argument('--modes', default=','.join(MODES))
    parser.add_argument('--fixtures', default=','.join(FIXTURES))
    parser.add_argument('--x64-qemu-image', help='Local Docker image containing /usr/bin/qemu-x86_64')
    parser.add_argument('--arm64-image', help='Local linux/arm64 Docker image for native ELF execution')
    args = parser.parse_args()
    compiler, output = args.xu.resolve(), args.out.resolve()
    compiler_identity = hashlib.sha256(compiler.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for target in args.targets.split(','):
        for mode in args.modes.split(','):
            for fixture in args.fixtures.split(','):
                source = ROOT / 'tests/fixtures' / fixture / 'main.xu'
                expected = source.with_name('expected.txt').read_bytes()
                suffix = '.exe' if target.startswith('windows') else ''
                binary = output / f'{fixture}-{target}-{mode}{suffix}'
                command = [str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                           'build', str(source), *MODES[mode], '-o', str(binary)]
                if target != 'native':
                    command += ['--target', target]
                result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=90)
                assert result.returncode == 0, (command, result.stderr.decode(errors='replace'))
                row = dict(target=target, mode=mode, fixture=fixture, binary=str(binary),
                           status='compiled', executions=0, fallback_executions=0,
                           binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                           golden_sha256=hashlib.sha256(expected).hexdigest())
                if target.startswith('windows'):
                    machine = 0xaa64 if target == 'windows-arm64' else 0x8664
                    imports = pe_imports(binary, machine)
                    if target == 'windows-arm64':
                        assert 'IsProcessorFeaturePresent' in imports.get('kernel32.dll', []), imports
                    row['status'] = 'compiled+PE-imports'
                compile_only = target in args.compile_only_targets.split(',')
                executable = not compile_only and (target == 'native' or
                             (target == 'macos-x64' and platform.system() == 'Darwin'))
                if executable:
                    run(binary, expected)
                    row['status'] = 'ran'
                    row['executions'] += 1
                    if target == 'macos-x64':
                        masked = binary.with_name(binary.name + '-no-features')
                        row['cache_file_offset'] = zero_x64_capabilities(binary, masked)
                        run(masked, expected)
                        row['fallback'] = 'ran'
                        row['fallback_executions'] += 1
                elif not compile_only and target == 'linux-x64' and args.x64_qemu_image:
                    def qemu_command(cpu, path):
                        return ['docker', 'run', '--rm', '--pull=never', '--network=none',
                                   '--ulimit', 'core=0',
                                   '-v', f'{output}:/w:ro', '--entrypoint', '/usr/bin/qemu-x86_64',
                                   args.x64_qemu_image, '-cpu', cpu, '/w/' + path.name]
                    for cpu in ('qemu64', 'max'):
                        run(binary, expected, qemu_command(cpu, binary))
                        row['executions'] += 1
                    if fixture == 'math_bits_cpu_dispatch' and mode == 'O0':
                        altered = binary.with_name(binary.name + '-alter-popcnt')
                        row['hardware_probe_offsets'] = alter_hardware_instruction(binary, altered, False)
                        expect_hardware_change(qemu_command('max', altered), expected)
                        run(altered, expected, qemu_command('qemu64', altered))
                        row['hardware_probe'] = 'max depends on POPCNT result; qemu64 uses software'
                    row['cpu_models'] = ['qemu64', 'max']
                    row['status'] = 'ran'
                elif not compile_only and target == 'linux-arm64' and args.arm64_image:
                    def arm_command(path):
                        return ['docker', 'run', '--rm', '--pull=never', '--network=none',
                                '--ulimit', 'core=0',
                                '--platform', 'linux/arm64', '-v', f'{output}:/w:ro',
                                '--entrypoint', '/w/' + path.name, args.arm64_image]
                    run(binary, expected, arm_command(binary))
                    row['executions'] += 1
                    masked = binary.with_name(binary.name + '-no-features')
                    row['query_file_offsets'] = zero_arm64_queries(binary, masked)
                    run(masked, expected, arm_command(masked))
                    row['fallback_executions'] += 1
                    if fixture == 'crypto_aes' and mode == 'O0':
                        altered = binary.with_name(binary.name + '-omit-aese')
                        row['hardware_probe_offsets'] = alter_hardware_instruction(binary, altered, True)
                        expect_hardware_change(arm_command(altered), expected)
                        altered_fallback = binary.with_name(binary.name + '-omit-aese-no-features')
                        zero_arm64_queries(altered, altered_fallback)
                        run(altered_fallback, expected, arm_command(altered_fallback))
                        row['hardware_probe'] = 'native depends on AESE; capabilities=0 uses software'
                    row['fallback'] = 'ran'
                    row['status'] = 'ran'
                rows.append(row)
                print(f'PASS {fixture}/{target}/{mode} {row["status"]}' +
                      (' + capabilities=0' if row.get('fallback') else ''), flush=True)
    assert hashlib.sha256(compiler.read_bytes()).hexdigest() == compiler_identity, 'Compiler changed during matrix'
    report = {'compiler': str(compiler), 'compiler_sha256': compiler_identity,
              'rows': rows, 'runs': sum(row['executions'] for row in rows),
              'fallback_runs': sum(row['fallback_executions'] for row in rows)}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS {len(rows)} builds, {report["runs"]} executions, {report["fallback_runs"]} forced fallbacks')


if __name__ == '__main__':
    main()
