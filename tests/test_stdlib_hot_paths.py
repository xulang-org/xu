#!/usr/bin/env python3
"""Independent integer/search oracles for default and diagnostic product builds."""
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
#os
#strings
#bytes
#strconv
#encoding/hex
#errors

fn show_parse(s &string, base int) {
    value := strconv.parse(s, base) or (err) {
        println("E:" + err.msg())
        <<
    }
    println("V:" + str(value))
}
fn show_builtin(s &string) {
    value := parse_int(*s) or (err) {
        println("E:" + err.msg())
        <<
    }
    println("V:" + str(value))
}
fn show_atoi(s &string) {
    value := strconv.atoi(s) or (err) {
        println("E:" + err.msg())
        <<
    }
    println("V:" + str(value))
}
fn main() int {
    args := os.args()
    input := os.read(args[2]) or (err) { << 1 }
    lines := strings.split(&input, "\n")
    for line in lines {
        if line.len > 0 {
            fields := strings.split(&line, "|")
            if args[1] == "parse" {
                base := parse_int(fields[0]) or (err) { << 2 }
                value := hex.decode_string(fields[1]) or (err) { << 3 }
                show_parse(&value, base)
                if base == 10 {
                    show_builtin(&value)
                    show_atoi(&value)
                }
            } else if args[1] == "find" {
                text := hex.decode_string(fields[0]) or (err) { << 8 }
                needle_byte := parse_int(fields[1]) or (err) { << 9 }
                start := parse_int(fields[2]) or (err) { << 10 }
                println(find_byte(&text, needle_byte, start))
            } else {
                text := hex.decode_string(fields[0]) or (err) { << 4 }
                needle := hex.decode_string(fields[1]) or (err) { << 5 }
                off := parse_int(fields[2]) or (err) { << 6 }
                n := parse_int(fields[3]) or (err) { << 7 }
                view := strings.view_slice(&text, off, n)
                println(strings.index_of(&text, needle + ""))
                println(bytes.index(&text, needle + ""))
                println(view.index(&text, &needle))
            }
        }
    }
    << 0
}
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integer_oracle(token: bytes, base: int) -> str:
    if base not in (2, 8, 10, 16):
        return 'E:strconv: unsupported base'
    negative = token.startswith(b'-')
    digits = token[1:] if negative else token
    if not digits:
        return 'E:parse_int: invalid integer'
    alphabet = b'0123456789abcdef'
    # Arbitrary-precision prefix values independently check error precedence:
    # an overflowing prefix is rejected before a later malformed byte.
    for i, byte in enumerate(digits):
        digit = alphabet.find(bytes([byte]).lower())
        if digit < 0 or digit >= base:
            return 'E:parse_int: invalid integer'
        magnitude = int(digits[:i+1], base)
        if magnitude > (1 << 63)-1:
            if negative and i+1 == len(digits) and magnitude == 1 << 63:
                return 'V:'+str(-(1 << 63))
            return 'E:parse_int: out of range'
    value = int(digits, base)
    return 'V:'+str(-value if negative else value)


def datasets():
    rng = random.Random(20261010)
    parses = []
    for base, fmt in ((2, 'b'), (8, 'o'), (10, 'd'), (16, 'x')):
        values = [0, 1, -1, 10**18-1, 10**18, -(10**18),
                  (1 << 63)-1, 1 << 63, -(1 << 63), -(1 << 63)-1]
        values += [rng.randrange(-(1 << 70), 1 << 70) for _ in range(100)]
        for value in values:
            token = (('-' if value < 0 else '')+format(abs(value), fmt)).encode()
            parses += [(token, base), (token.upper(), base)]
            parses.append(((b'-' if value < 0 else b'')+b'000'+token.lstrip(b'-'), base))
        for token in (b'', b'-', b'+1', b' 1', b'1 ', b'1_0', b'0x10', b'--1',
                      b'9223372036854775808x', b'-9223372036854775808x'):
            parses.append((token, base))
    for length in (1, 17, 18, 19, 20, 64):
        for byte in range(256):
            if byte < 48 or byte > 57:
                parses.append((b'0'*(length-1)+bytes([byte]), 10))
    parses += [(b'1', base) for base in (-1, 0, 1, 3, 36)]
    searches = []
    for size in (0, 1, 15, 16, 17, 31, 32, 47, 48, 49, 63, 64, 65, 128, 1024):
        for _ in range(12):
            text = bytes(rng.randrange(8) for _ in range(size))
            needle = bytes(rng.randrange(8) for _ in range(rng.randrange(35)))
            off = rng.randrange(size+1)
            n = rng.randrange(size-off+1)
            searches += [(text, needle, 0, size), (text, needle, off, n)]
    for size in (48, 65, 4096):
        for needle in (b'a', b'aa', b'aaaaab', b'ab'*16, b'a'*32, b'a'*33):
            text = b'a'*size+b'b'
            searches += [(text, needle, 0, len(text)), (text, needle, 1, size-1)]
    # Exact last legal position, SIMD tails, the eight-candidate cutover, binary
    # bytes, and a needle that occurs only outside an interior view.
    for needle in (b'Z', b'ZX', b'Z'+b'x'*31, b'Z'+b'x'*32, b'\0\xff'):
        for padding in (0, 15, 16, 47, 48, 64, 257):
            text = b'a'*padding+needle
            searches += [(text, needle, 0, len(text)), (text, needle, 0, padding)]
    for candidates in (7, 8, 9, 32):
        text = b'ax'*candidates+b'aB'+b'x'*64
        searches.append((text, b'aB', 0, len(text)))
    finds = []
    for size in (0, 1, 7, 8, 15, 16, 17, 31, 32, 33, 47, 48, 49, 64, 65, 128):
        text = bytes((i*17) % 256 for i in range(size))
        for byte in (0, 1, 17, 255, 256, 511, -1):
            for start in sorted({-1, 0, 1, 7, 8, 15, 16, size-1, size, size+1}):
                finds.append((text, byte, start))
    return parses, searches, finds


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, default=ROOT/'bin/xu')
    ap.add_argument('--target', help='optional runnable native/translated target')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    compiler = args.xu.resolve()
    sources = [ROOT/p for p in ('src/strconv/mod.xu', 'src/strings/view.xu',
                               'src/strings/mod.xu', 'src/runtime/str_algo.xu')]
    before = {str(p): sha(p) for p in [compiler, *sources]}
    parses, searches, finds = datasets()
    expected_parse = []
    for token, base in parses:
        expected_parse += [integer_oracle(token, base)]*(3 if base == 10 else 1)
    expected_search = []
    for text, needle, off, n in searches:
        expected_search += list(map(str, (text.find(needle), text.find(needle),
                                         text[off:off+n].find(needle))))
    expected_find = [str(text.find(bytes([byte & 255]), start) if start >= 0 else -1)
                     for text, byte, start in finds]
    report = dict(schema=1, target=args.target or 'host', fingerprints=before, parse_cases=len(parses),
                  search_cases=len(searches), find_cases=len(finds),
                  checks_per_mode=len(expected_parse)+len(expected_search)+len(expected_find),
                  modes=[], status='PASS')
    with tempfile.TemporaryDirectory(prefix='xu-stdlib-hot-paths-') as td:
        work = Path(td)
        source = work/'probe.xu'; source.write_text(PROBE)
        (work/'parse.txt').write_text(''.join(f'{base}|{token.hex()}\n' for token, base in parses))
        (work/'search.txt').write_text(''.join(f'{text.hex()}|{needle.hex()}|{off}|{n}\n'
                                            for text, needle, off, n in searches))
        (work/'find.txt').write_text(''.join(f'{text.hex()}|{byte}|{start}\n' for text, byte, start in finds))
        for mode, flags in (('auto', []), ('no-opt', ['--no-opt']), ('O3', ['-O3'])):
            exe = work/'probe'
            command = [str(ROOT/'scripts/run_product_compiler.sh'), str(compiler),
                       'build', str(source), *flags,
                       *(['--target', args.target] if args.target else []), '-o', str(exe)]
            compiled = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
            if compiled.returncode:
                raise ValueError((mode, 'build', compiled.stderr))
            for kind, expected in (('parse', expected_parse), ('search', expected_search), ('find', expected_find)):
                result = subprocess.run([str(exe), kind, str(work/(kind+'.txt'))],
                                        capture_output=True, text=True, timeout=120)
                if result.returncode or result.stderr or result.stdout.splitlines() != expected:
                    actual = result.stdout.splitlines()
                    mismatch = next((i for i, pair in enumerate(zip(actual, expected))
                                     if pair[0] != pair[1]), min(len(actual), len(expected)))
                    raise ValueError((mode, kind, result.returncode, mismatch, actual[mismatch:mismatch+3],
                                      expected[mismatch:mismatch+3], result.stderr))
            report['modes'].append(dict(mode=mode, command=command, binary_sha256=sha(exe)))
            print('PASS', mode, report['checks_per_mode'], 'oracle checks', flush=True)
    if before != {str(p): sha(p) for p in [compiler, *sources]}:
        raise ValueError('compiler or affected source changed during verification')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
