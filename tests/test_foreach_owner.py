#!/usr/bin/env python3
"""Execute real array ForEach ownership paths with the allocator ledger."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def source(body, helpers=''):
    return ('@main\n' + helpers + '\nfn main() int {\n' + body + '\n    << 0\n}\n').replace(';', '\n').replace('break', '<-').replace('continue', '->')


CASES = {
    'literal': (source('mut s := 0\nfor _ in 0:100 { for x in [1,2,3] { s += x } }\nprintln(s)'), '600\n'),
    'empty': (source('mut s := 0\nfor _ in 0:100 { for x in []int{} { s += x } }\nprintln(s)'), '0\n'),
    'break': (source('mut s := 0\nfor _ in 0:100 { for x in [1,2,3] { s += x; break } }\nprintln(s)'), '100\n'),
    'continue': (source('mut s := 0\nfor _ in 0:100 { for x in [1,2,3] { if x == 2 { continue }; s += x } }\nprintln(s)'), '400\n'),
    'return': (source('mut s := 0\nfor _ in 0:100 { s += first() }\nprintln(s)', 'fn first() int { for x in [1,2,3] { << x }; << 0 }'), '100\n'),
    'nested': (source('mut s := 0\nfor _ in 0:100 { for x in [1,2] { for y in [3,4] { s += x*y } } }\nprintln(s)'), '2100\n'),
    'call': (source('mut s := 0\nfor _ in 0:100 { for x in values() { s += x } }\nprintln(s)', 'fn values() []int { << [1,2,3] }'), '600\n'),
    'call_break': (source('mut s := 0\nfor _ in 0:100 { for x in values() { s += x; break } }\nprintln(s)', 'fn values() []int { << [1,2,3] }'), '100\n'),
    'call_once': (source('mut count := 0\nmut s := 0\nfor x in values(mut &count) { s += x }\nprintln(count)\nprintln(s)', 'fn values(count &mut int) []int { *count += 1; << [1,2,3] }'), '1\n6\n'),
    'method': (source('h := Holder{n: 2}\nmut s := 0\nfor _ in 0:100 { for x in h.values() { s += x } }\nprintln(s)', 'struct Holder { n int }\nfn (h &Holder) values() []int { << [h.n,3] }'), '500\n'),
    'empty_call': (source('mut s := 0\nfor _ in 0:100 { for x in values() { s += x } }\nprintln(s)', 'fn values() []int { << []int{} }'), '0\n'),
    'ref_call': (source('a := [1,2,3]\nmut s := 0\nfor _ in 0:100 { for x in view(&a) { s += x } }\nprintln(s)\nprintln(a[2])', 'fn view(a &[]int) &[]int { << a }'), '600\n3\n'),
    'slice': (source('a := [1,2,3,4]\nmut s := 0\nfor _ in 0:100 { for x in a[1:3] { s += x } }\nprintln(s)\nprintln(a[0])'), '500\n1\n'),
    'named': (source('a := [1,2,3]\nmut s := 0\nfor _ in 0:100 { for x in a { s += x } }\nprintln(s)\nprintln(a[2])'), '600\n3\n'),
    'reference': (source('a := [1,2,3]\nprintln(sum(&a))\nprintln(a[2])', 'fn sum(a &[]int) int { mut s := 0; for x in a { s += x }; << s }'), '6\n3\n'),
    'mutable_reference': (source('mut a := [1,2,3]\nprintln(sum(mut &a))\nprintln(a[2])', 'fn sum(a &mut []int) int { mut s := 0; for x in a { s += x }; << s }'), '6\n3\n'),
    'field': (source('h := Holder{items: [1,2,3]}\nmut s := 0\nfor _ in 0:100 { for x in h.items { s += x } }\nprintln(s)\nprintln(h.items[2])', 'struct Holder { items []int }'), '600\n3\n'),
    'fixed': (source('mut s := 0\nfor _ in 0:100 { for x in [3]int{1,2,3} { s += x } }\nprintln(s)'), '600\n'),
    'fixed_named': (source('a := [3]int{1,2,3}\nmut s := 0\nfor x in a { s += x }\nprintln(s)\nprintln(a[2])'), '6\n3\n'),
    'fixed_reference': (source('a := [3]int{1,2,3}\nprintln(sum(&a))\nprintln(a[2])', 'fn sum(a &[3]int) int { mut s := 0; for x in a { s += x }; << s }'), '6\n3\n'),
    'fixed_call': (source('mut s := 0\nfor _ in 0:100 { for x in values() { s += x } }\nprintln(s)', 'fn values() [3]int { << [3]int{1,2,3} }'), '600\n'),
    'strings': (source('mut s := 0\nfor _ in 0:100 { for x in ["a"+str(1),"b"+str(2)] { s += x.len } }\nprintln(s)'), '400\n'),
    'strings_break': (source('mut s := 0\nfor _ in 0:100 { for x in ["a"+str(1),"b"+str(2)] { s += x.len; break } }\nprintln(s)'), '200\n'),
    'strings_return': (source('mut s := 0\nfor _ in 0:100 { s += first().len }\nprintln(s)', 'fn first() string { for x in ["a"+str(1),"b"+str(2)] { << x }; << "" }'), '200\n'),
    'fixed_strings': (source('mut s := 0\nfor _ in 0:100 { for x in [2]string{"a"+str(1),"b"+str(2)} { s += x.len } }\nprintln(s)'), '400\n'),
    'fixed_strings_break': (source('mut s := 0\nfor _ in 0:100 { for x in [2]string{"a"+str(1),"b"+str(2)} { s += x.len; break } }\nprintln(s)'), '200\n'),
    'strings_continue': (source('mut s := 0\nfor _ in 0:100 { for x in ["a"+str(1),"b"+str(2)] { if x == "a1" { continue }; s += x.len } }\nprintln(s)'), '200\n'),
    'fixed_strings_call': (source('mut s := 0\nfor _ in 0:100 { for x in values() { s += x.len } }\nprintln(s)', 'fn values() [2]string { << [2]string{"a"+str(1),"b"+str(2)} }'), '400\n'),
    'or_success': (source('mut s := 0\nfor _ in 0:100 { for x in values(1) or (err) { << 1 } { s += x } }\nprintln(s)', '#errors\nfn values(flag int) []int { if flag == 0 { >> errors.new("bad") }; << [1,2,3] }'), '600\n'),
    'or_failure': (source('println(first(0))', '#errors\nfn values(flag int) []int { if flag == 0 { >> errors.new("bad") }; << [1,2,3] }\nfn first(flag int) int { for x in values(flag) or (err) { << 7 } { << x }; << 0 }'), '7\n'),
    'propagate': (source('mut s := 0\nfor _ in 0:100 { s += sum(1) or (err) { << 1 } }\nprintln(s)', '#errors\nfn values(flag int) []int { if flag == 0 { >> errors.new("bad") }; << [1,2,3] }\nfn sum(flag int) int { mut s := 0; for x in values(flag) or >> { s += x }; << s }'), '600\n'),
    'propagate_failure': (source('_ := sum(0) or (err) { println("caught"); << 0 }', '#errors\nfn values(flag int) []int { if flag == 0 { >> errors.new("bad") }; << [1,2,3] }\nfn sum(flag int) int { mut s := 0; for x in [1,2,3] { for y in values(flag) or >> { s += x+y } }; << s }'), 'caught\n'),
    'implicit_propagate': (source('mut s := 0\nfor _ in 0:100 { s += sum(1) or (err) { << 1 } }\nprintln(s)', '#errors\nfn values(flag int) []int { if flag == 0 { >> errors.new("bad") }; << [1,2,3] }\nfn sum(flag int) int { mut s := 0; for x in values(flag) { s += x }; << s }'), '600\n'),
    'range': (source('mut s := 0\nfor _ in 0:100 { for x in 1:4 { s += x } }\nprintln(s)'), '600\n'),
    'resource_named_break': (source('xs := [Token{id:3},Token{id:4}]\nfor x in xs { println(x.id); break }\nprintln(9)',
        'struct Token { id int }\nfn (r &mut Token) drop() { println(r.id) }'), '3\n9\n3\n4\n'),
    'resource_named': (source('xs := [Token{id:3},Token{id:4}]\nfor x in xs { println(x.id) }\nprintln(xs.len)\nprintln(9)',
        'struct Token { id int }\nfn (r &mut Token) drop() { println(r.id) }'), '3\n4\n2\n9\n3\n4\n'),
    'resource_named_return': (source('println(first())\nprintln(9)',
        'struct Token { id int }\nfn (r &mut Token) drop() { println(r.id) }\nfn first() int { xs := [Token{id:3},Token{id:4}]; for x in xs { << x.id }; << 0 }'), '3\n4\n3\n9\n'),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--case', choices=CASES)
    args = ap.parse_args()
    compiler = args.xu.resolve()
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    identity = sha(compiler)
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-foreach-owner-') as td:
        work = Path(td)
        for name, (src, expected) in CASES.items():
            if args.case and args.case != name:
                continue
            path = work / (name + '.xu')
            path.write_text(src)
            for flags in (['-O0'], ['-O1'], ['-O2'], ['-O3'], ['-O1', '--no-regcache']):
                binary = work / 'test'
                built = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                    'build', *flags, str(path), '-o', str(binary)], cwd=ROOT, capture_output=True,
                    text=True, timeout=60, env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'))
                row = dict(name=name, flags=flags, source=src, expected_stdout=expected,
                           build_exit=built.returncode, build_stderr=built.stderr)
                if not built.returncode:
                    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15,
                        env=dict(os.environ, XU_HEAP_STATS='1'))
                    ledger = {k: int(v) for k,v in re.findall(r'xu_heap_stats (\w+)=(\d+)', run.stderr)}
                    extra = re.sub(r'xu_heap_stats \w+=\d+\n', '', run.stderr)
                    row.update(run_exit=run.returncode, stdout=run.stdout, stderr=run.stderr,
                               ledger=ledger, binary_sha256=sha(binary))
                    row['status'] = 'PASS' if (not run.returncode and run.stdout == expected and not extra and
                        len(ledger) == 7 and ledger['live_bytes'] == 0 and ledger['allocs'] == ledger['frees'] and
                        not any(ledger[k] for k in ('unknown_frees','double_frees','ledger_overflows'))) else 'FAIL'
                else:
                    row['status'] = 'FAIL'
                rows.append(row)
                if row['status'] != 'PASS':
                    print(name, flags, row.get('ledger', built.stderr[:250]), flush=True)
    if sha(compiler) != identity:
        raise ValueError('compiler changed during test')
    failed = sum(row['status'] != 'PASS' for row in rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(status='FAIL' if failed else 'PASS', compiler=str(compiler),
        compiler_sha256=identity, test_sha256=sha(Path(__file__)), rows=rows), indent=2) + '\n')
    print(f'foreach owner: {len(rows)-failed} pass, {failed} fail')
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
