#!/usr/bin/env python3
"""Execute generic lower-bound loop counterexamples through the product CLI."""
from pathlib import Path
import argparse
import hashlib
import json
import itertools
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODES = dict(O0=['-O0'], O1=['-O1'], O2=['-O2'], O3=['-O3'],
             **{'no-regcache': ['--no-regcache'], 'ra0': ['--ra=0'],
                'ra1': ['--ra=1'], 'ra2': ['--ra=2']})
HELPER = '''@main
fn partition_point(a &[]int, start int, limit int, needle int) int {
 mut lo := start
 mut hi := limit
 while lo < hi {
  mid := lo + ((hi-lo) >> 1)
  if a[mid] < needle { lo=mid+1 } else { hi=mid }
 }
 << lo
}
'''
PAIR = struct.pack('<II', 0x9A88B129, 0x9A88A5CE)
ASR = struct.pack('<I', 0x9341FD08)  # asr x8,x8,#1
CHECK = struct.pack('<I', 0xEB0F011F)  # cmp x8,x15 (mid, length)


def cases():
    # Goldens follow each executed checked Index, rather than an initial
    # interval restriction. Each helper has an unrelated name and no import.
    for name, lo, hi, needle, answer in (
        ('wide-upper-valid', 0, 6, -1, 0),
        ('negative-lower-valid', -1, 4, 10, 4),
        ('ordinary', 0, 4, 4, 2),
        ('empty-outside', 9, 3, 10, 9),
        ('later-negative-index', -1, 4, -1, None),
        ('first-large-index', 0, 12, 4, None),
        ('wrapping-difference', '-9223372036854775807-1',
         '9223372036854775807', 4, None),
    ):
        yield name, HELPER, '[1,3,7,9]', lo, hi, needle, answer, 'checked'
    yield ('proved-length', HELPER.replace('mut lo := start', 'mut lo := 0')
           .replace('mut hi := limit', 'mut hi := a.len'),
           '[1,3,7,9]', 0, 4, 4, 2, 'range')
    yield ('reversed-subtraction', HELPER.replace('hi-lo', 'lo-hi'),
           '[1,3,7,9]', 0, 4, 4, None, 'decline')
    yield ('upper-bound', HELPER.replace(
           'if a[mid] < needle { lo=mid+1 } else { hi=mid }',
           'if needle < a[mid] { hi=mid } else { lo=mid+1 }'),
           '[1,3,3,9]', 0, 4, 3, 3, 'decline')
    yield ('reversed-updates', HELPER.replace(
           '{ lo=mid+1 } else { hi=mid }', '{ hi=mid } else { lo=mid+1 }'),
           '[1,3,7,9]', 0, 4, 4, 4, 'decline')
    yield ('observable-body-store', HELPER.replace(
           ' while lo < hi {', ' mut saved := 0\n while lo < hi {')
           .replace('  if a[mid]', '  saved=needle\n  if a[mid]')
           .replace(' << lo', ' << lo+saved'),
           '[1,3,7,9]', 0, 4, 4, 6, 'decline')
    yield 'empty-slice-skip', HELPER, '[]int{}', 0, 0, 4, 0, 'checked'
    yield 'empty-slice-access', HELPER, '[]int{}', 0, 1, 4, None, 'checked'


def midpoint_reference(lo, hi, needle):
    """Sequential checked execution; no initial interval preconditions."""
    array = [1, 3, 3, 9]
    def signed(v):
        return ((v + (1 << 63)) & ((1 << 64) - 1)) - (1 << 63)
    for _ in range(64):
        if lo >= hi:
            return lo
        mid = signed(lo + (signed(hi - lo) >> 1))
        if mid < 0 or mid >= len(array):
            return None
        if array[mid] < needle:
            lo = signed(mid + 1)
        else:
            hi = mid
    raise ValueError('reference did not terminate')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--source-root', type=Path, default=ROOT)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--modes', default=','.join(MODES))
    ap.add_argument('--expect-red', action='store_true')
    args = ap.parse_args()
    compiler = args.xu.resolve()
    root = args.source_root.resolve()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    identity = sha(compiler)
    labels = args.modes.split(',')
    if any(label not in MODES for label in labels):
        ap.error('unknown mode')
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    for name, helper, array, lo, hi, needle, answer, admission in cases():
        directory = args.out / name
        directory.mkdir()
        source = directory / 'main.xu'
        source.write_text(helper + f'''fn main() int {{
 a := {array}
 println(101)
 println(partition_point(&a,{lo},{hi},{needle}))
 println(202)
 << 0
}}
''')
        for label in labels:
            binary = directory / label
            build = subprocess.run([str(root / 'scripts/run_product_compiler.sh'),
                str(compiler), 'build', *MODES[label], str(source), '-o', str(binary)],
                cwd=root, capture_output=True, timeout=180)
            (directory / (label + '.build.log')).write_bytes(build.stdout + build.stderr)
            if build.returncode:
                raise ValueError(f'{name}/{label}: {build.stderr.decode(errors="replace")}')
            run = subprocess.run([str(binary)], capture_output=True, timeout=10)
            (directory / (label + '.stdout')).write_bytes(run.stdout)
            (directory / (label + '.stderr')).write_bytes(run.stderr)
            expected = f'101\n{answer}\n202\n'.encode()
            semantic = ((run.returncode == 0 and run.stdout == expected and not run.stderr)
                        if answer is not None else
                        (run.returncode == 1 and run.stdout == b'101\n' and
                         run.stderr == b'index out of bounds\n'))
            words = binary.read_bytes()
            fused = PAIR in words
            pair_count = words.count(PAIR)
            assembly = ((fused and ASR in words and (CHECK in words) == (admission == 'checked')
                         and pair_count == (2 if admission == 'checked' else 1))
                        if admission != 'decline' else not fused)
            row = dict(case=name, mode=label, semantic_pass=semantic,
                assembly_pass=assembly, fused=fused, pair_count=pair_count, admission=admission,
                expected_answer=answer, rc=run.returncode,
                stdout=run.stdout.decode(errors='replace'), stderr=run.stderr.decode(errors='replace'),
                source_sha256=sha(source), binary_sha256=sha(binary))
            rows.append(row)
            print('PASS' if semantic and assembly else 'FAIL', name, label,
                  'semantic', semantic, 'assembly', assembly, flush=True)
    directory = args.out / 'parameter-matrix'
    directory.mkdir()
    source = directory / 'main.xu'
    source.write_text(HELPER.replace('@main', '@main\n#strconv') + '''fn main() int {
 av := args()
 l := av[1]
 h := av[2]
 v := av[3]
 lo := strconv.atoi(&l) or (err) { << 2 }
 hi := strconv.atoi(&h) or (err) { << 2 }
 needle := strconv.atoi(&v) or (err) { << 2 }
 a := [1,3,3,9]
 println(101)
 println(partition_point(&a,lo,hi,needle))
 println(202)
 << 0
}
''')
    parameters = list(itertools.product((-7, -1, 0, 1, 3, 4, 5, 8),
        (-3, -1, 0, 1, 3, 4, 5, 7, 12), (-2, 1, 3, 6, 10)))
    parameters += [(-(1 << 63), (1 << 63) - 1, 4)]
    matrix = []
    for label in labels:
        binary = directory / label
        build = subprocess.run([str(root / 'scripts/run_product_compiler.sh'), str(compiler),
            'build', *MODES[label], str(source), '-o', str(binary)],
            cwd=root, capture_output=True, timeout=180)
        (directory / (label + '.build.log')).write_bytes(build.stdout + build.stderr)
        if build.returncode:
            raise ValueError(build.stderr.decode(errors='replace'))
        assert binary.read_bytes().count(PAIR) == 2, 'missing safe/checked loop versions'
        for lo, hi, needle in parameters:
            answer = midpoint_reference(lo, hi, needle)
            run = subprocess.run([str(binary), str(lo), str(hi), str(needle)],
                capture_output=True, timeout=10)
            semantic = ((run.returncode == 0 and not run.stderr and
                         run.stdout == f'101\n{answer}\n202\n'.encode()) if answer is not None else
                        (run.returncode == 1 and run.stdout == b'101\n' and
                         run.stderr == b'index out of bounds\n'))
            matrix.append(dict(mode=label, lo=lo, hi=hi, needle=needle,
                expected_answer=answer, semantic_pass=semantic, rc=run.returncode,
                stdout=run.stdout.decode(errors='replace'), stderr=run.stderr.decode(errors='replace'),
                binary_sha256=sha(binary)))
        print('matrix', label, len(parameters), 'checked executions', flush=True)
    coverage = []
    for name, answer, iterations in (('ordinary', 2, 2), ('wide-upper-valid', 0, 3),
                                     ('negative-lower-valid', 4, 2), ('empty-outside', 9, 0)):
        source = args.out / name / 'main.xu'
        for label in ('O0', 'O3'):
            stem = 'coverage-' + name + '-' + label
            binary = args.out / stem
            build = subprocess.run([str(root / 'scripts/run_product_compiler.sh'), str(compiler),
                'build', *MODES[label], '--cover', str(source), '-o', str(binary)],
                cwd=root, capture_output=True, timeout=180)
            (args.out / (stem + '.build.log')).write_bytes(build.stdout + build.stderr)
            if build.returncode:
                raise ValueError(build.stderr.decode(errors='replace'))
            run = subprocess.run([str(binary)], capture_output=True, timeout=10)
            (args.out / (stem + '.stdout')).write_bytes(run.stdout)
            (args.out / (stem + '.stderr')).write_bytes(run.stderr)
            counts = {int(line): int(count) for line, count in re.findall(
                re.escape(str(source)) + r':(\d+) (\d+)\n', run.stdout.decode())}
            # These MIR layouts have two line-7 blocks per iteration: the
            # comparison and the chosen update. Counters describe MIR blocks,
            # so do not infer a visit for an optimized empty Return label.
            ok = (run.returncode == 0 and not run.stderr and
                  run.stdout.startswith(f'101\n{answer}\n202\n'.encode()) and
                  PAIR not in binary.read_bytes() and counts.get(7) == 2 * iterations)
            coverage.append(dict(case=name, mode=label, passed=ok, counts=counts,
                                 binary_sha256=sha(binary), stdout=run.stdout.decode()))
    assert sha(compiler) == identity, 'compiler changed during gate'
    failures = sum(not (r['semantic_pass'] and r['assembly_pass']) for r in rows)
    failures += sum(not r['semantic_pass'] for r in matrix)
    failures += sum(not r['passed'] for r in coverage)
    report = dict(status='REPRODUCED' if failures else 'PASS', compiler_sha256=identity,
        cases=len(list(cases())), runs=len(rows), failures=failures, rows=rows,
        matrix_runs=len(matrix), matrix=matrix,
        matrix_source_sha256=sha(directory / 'main.xu'), coverage=coverage,
        scope='Actual macOS ARM64 product artifacts. Independent hand-computed scalar/fault goldens, '
              'fault prefix/suffix ordering, and encoded CSEL/CSINC, arithmetic shift and per-mid check. '
              'No foreign runtime, general alias/lifetime or profitability claim.')
    (args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if (args.expect_red and failures == 0) or (not args.expect_red and failures):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
