#!/usr/bin/env python3
"""Exact, independent signed-64-bit sorting oracles across array shapes."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''@main
#sort
#os
#strings
#strconv
fn main() int {
    args := os.args()
    text := os.read(args[1]) or (err) { << 1 }
    rows := strings.split(&text, "\n")
    for row in rows {
        if row.len == 0 { -> }
        parts := strings.split(&row, ",")
        mut a := []int{}
        for j in 1:parts.len {
            v := strconv.parse(&parts[j], 10) or (err) { << 2 }
            a.push(v)
        }
        if parts[0] == "reverse" { sort.reverse_ints(mut &a) }
        else { sort.ints(mut &a) }
        println(a.len)
        for v in a { println(v) }
        // Exercise idempotence after radix, introsort and order detection.
        if parts[0] == "reverse" { sort.reverse_ints(mut &a) }
        else { sort.ints(mut &a) }
        println(a.len)
        for v in a { println(v) }
    }
    << 0
}
'''


def datasets():
    rng = random.Random(20261010)
    result = []
    sizes = (0, 1, 2, 15, 16, 17, 31, 32, 33, 127, 128, 129,
             255, 256, 257, 511, 512, 513, 1024, 4096, 8192)
    low, high = -(1 << 63), (1 << 63)-1
    for n in sizes:
        shapes = {
            'signed64': [rng.randrange(low, high+1) for _ in range(n)],
            'positive31': [rng.randrange(1 << 31) for _ in range(n)],
            'negative': [rng.randrange(low, 0) for _ in range(n)],
            'sorted': list(range(-(n//2), n-n//2)),
            'reverse': list(range(n-1, -1, -1)),
            'equal': [-42]*n,
            'few': [rng.choice((low, -256, -1, 0, 1, 255, high)) for _ in range(n)],
            'organ': [min(i, n-i) for i in range(n)],
            'saw': [i % 257 - 128 for i in range(n)],
            # All keys share upper bytes, or only the signed byte differs.
            'byte_gap': [((i % 16) << 48) | 0x1234 for i in range(n)],
            'sign_gap': [low+7 if i % 2 else 7 for i in range(n)],
            'extremes': [(low, high, low+1, high-1, -1, 0, 1)[i % 7] for i in range(n)],
        }
        almost = list(range(n))
        for _ in range(max(1, n//128)):
            if n: i, j = rng.randrange(n), rng.randrange(n); almost[i], almost[j] = almost[j], almost[i]
        shapes['almost'] = almost
        for shape, values in shapes.items():
            for mode in ('ascending', 'reverse'):
                result.append((f'{shape}/{n}/{mode}', mode, values))
    # Exhaust every short length so leaf cutoff changes cannot hide a boundary
    # or partition corner case behind a few selected lengths.
    for n in range(129):
        values = [rng.getrandbits(64)-(1 << 63) for _ in range(n)]
        for mode in ('ascending', 'reverse'):
            result.append((f'all-short-lengths/{n}/{mode}', mode, values))
    # Cross the large radix boundary with every active signed byte.
    for shift in range(0, 64, 8):
        values = [rng.getrandbits(8) << shift for _ in range(32768)]
        values = [v-(1 << 64) if v >= 1 << 63 else v for v in values]
        result.append((f'active-byte-{shift}', 'ascending', values))
    # Nonadjacent active bytes and bucket-local uniformity: a globally active
    # low byte can still be constant inside one high-byte bucket.
    for lower in range(0, 56, 8):
        for upper in range(lower+16, 64, 8):
            values = [(rng.getrandbits(8) << lower) | (rng.getrandbits(8) << upper)
                      for _ in range(4096)]
            values = [v-(1 << 64) if v >= 1 << 63 else v for v in values]
            for mode in ('ascending', 'reverse'):
                result.append((f'byte-pair-{lower}-{upper}/{mode}', mode, values))
    values = [(i % 256) << 48 | (i % 256) for i in range(32768)]
    result.append(('bucket-local-constant', 'ascending', values))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, default=ROOT/'bin/xu')
    ap.add_argument('--cwd', type=Path, default=ROOT, help='stdlib source root for isolation')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--profiles', default='auto,no-opt,O3')
    ap.add_argument('--target', help='cross build only')
    args = ap.parse_args()
    cases = datasets()
    data = ''.join(mode+','+','.join(map(str, vs))+'\n' if vs else mode+'\n'
                   for _, mode, vs in cases)
    gold = []
    for _, mode, vs in cases:
        ordered = sorted(vs, reverse=mode == 'reverse')
        for _ in range(2): gold += [str(len(vs)), *map(str, ordered)]
    expected = '\n'.join(gold)+'\n'
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    compiler = args.xu.resolve()
    report = {'cases': len(cases), 'values': sum(len(vs) for _, _, vs in cases),
              'checks_per_profile': len(gold), 'profiles': [], 'compiler_sha256': sha(compiler),
              'source_sha256': sha(args.cwd/'src/sort/mod.xu'),
              'dataset_sha256': hashlib.sha256(data.encode()).hexdigest()}
    with tempfile.TemporaryDirectory(prefix='xu-sort-oracle-') as td:
        work = Path(td); source = work/'main.xu'; source.write_text(PROBE)
        input_path = work/'vectors.txt'; input_path.write_text(data)
        for profile in args.profiles.split(','):
            binary = work/('program.exe' if args.target and args.target.startswith('windows') else 'program')
            flags = [] if profile == 'auto' else ['--no-opt' if profile == 'no-opt' else '-'+profile]
            if args.target: flags += ['--target', args.target]
            command = [str(ROOT/'scripts/run_product_compiler.sh'), '--cwd', str(args.cwd.resolve()),
                       str(compiler), 'build', *flags, str(source), '-o', str(binary)]
            p = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if p.returncode: raise RuntimeError(p.stderr)
            if args.target:
                assert binary.read_bytes().startswith(b'MZ' if args.target.startswith('windows') else b'\x7fELF')
                status = 'BUILD_FORMAT_PASS'
            else:
                run = subprocess.run([str(binary), str(input_path)], capture_output=True, text=True, timeout=180)
                if (run.returncode, run.stdout, run.stderr) != (0, expected, ''):
                    actual = run.stdout.splitlines()
                    mismatch = next((i for i, (x, y) in enumerate(zip(actual, gold)) if x != y), None)
                    raise AssertionError((profile, run.returncode, run.stderr, mismatch, len(actual), len(gold)))
                status = 'PASS'
            report['profiles'].append({'profile': profile, 'status': status, 'target': args.target,
                                       'binary_sha256': sha(binary), 'command': command})
            print(profile, status, len(cases), 'cases', len(gold), 'checks', flush=True)
    assert report['compiler_sha256'] == sha(compiler)
    report['status'] = 'PASS'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__': main()
