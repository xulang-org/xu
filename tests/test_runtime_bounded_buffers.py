#!/usr/bin/env python3
"""Golden and allocation-count gate for bounded int-buffer string conversion."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {'live_bytes', 'peak_bytes', 'allocs', 'frees', 'unknown_frees', 'double_frees', 'ledger_overflows'}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--old', type=Path)
    ap.add_argument('--old-runtime', type=Path)
    ap.add_argument('--modes', default='-O0,-O1,-O3,-O3 --target macos-x64')
    args = ap.parse_args()
    compiler = args.xu.resolve()
    identity = sha(compiler)
    closure = json.loads(subprocess.check_output(['python3', 'scripts/check_bootstrap_xu_boundary.py', '--strict-freeze', '--json'], cwd=ROOT))['source_manifest']
    loop = '''@main
#runtime
fn main() int {
    f := runtime.itoa
    mut total := 0
    for i in 0:1000 {
        a := str(i + 1)
        b := runtime.itoa(0 - (i + 1))
        c := f(i + 1)
        total += a.len + b.len + c.len
    }
    total += str(9223372036854775807).len
    total += str(0 - 9223372036854775807 - 1).len
    println(total)
    << 0
}
'''
    cases = [('itoa-loop', loop, '9718\n', 3002),
             ('zero-itoa', '@main\n#runtime\nfn main() int {\n f := runtime.itoa\n println(str(0).len + runtime.itoa(0).len + f(0).len)\n << 0\n}\n', '3\n', 0)]
    for empty in (False, True):
        bounds = '3, 3' if empty else '2, 6'
        source = '@main\nfn main() int {\n b := [8]int{65,66,67,68,69,70,71,72}\n mut total := 0\n for i in 0:1000 {\n s := string_from_bytes(b, ' + bounds + ')\n total += s.len\n }\n println(total)\n << 0\n}\n'
        cases.append(('range-loop-' + str(empty), source, '0\n' if empty else '4000\n', 0 if empty else 1000))
    alias_cases = [
        ('dynamic-direct', '@main\nfn grow(a &mut []int) int { a.push(90); << 0 }\nfn main() int { mut b := [65,66,67]; println(string_from_bytes(b, grow(mut &b), 3)); << 0 }\n'),
        ('dynamic-nested', '@main\nfn grow(a &mut []int) int { a.push(90); << 0 }\nfn main() int { mut b := [65,66,67]; println(string_from_bytes(b, 0 + grow(mut &b), 3)); << 0 }\n'),
        ('fixed-container', '@main\nstruct Box { data [3]int }\nfn grow(a &mut []Box) int { for i in 0:100 { a.push(Box{data: [3]int{90,90,90}}) }; << 0 }\nfn main() int { mut boxes := []Box{}; boxes.push(Box{data: [3]int{65,66,67}}); println(string_from_bytes(boxes[0].data, grow(mut &boxes), 3)); << 0 }\n'),
        ('fixed-fnval', '@main\nfn bound() int { << 0 }\nfn main() int { b := [3]int{65,66,67}; f := bound; println(string_from_bytes(b, f(), 3)); << 0 }\n'),
    ]
    alias_rows = []
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-bounded-buffer-') as tmp:
        work = Path(tmp)
        for opt in args.modes.split(','):
            for name, source, golden, allocations in cases:
                src = work / 'main.xu';src.write_text(source)
                binary = work / 'program'
                build = subprocess.run(['scripts/run_product_compiler.sh', str(compiler), 'build', *shlex.split(opt), str(src), '-o', str(binary)], cwd=ROOT, env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'), capture_output=True, text=True, timeout=120)
                if build.returncode: raise ValueError((name, opt, build.stderr))
                run = subprocess.run([str(binary)], env=dict(os.environ, XU_HEAP_STATS='1'), capture_output=True, text=True, timeout=30)
                stats = {}
                for line in run.stderr.splitlines():
                    match = re.fullmatch(r'xu_heap_stats ([a-z_]+)=([0-9]+)', line)
                    if not match or match[1] in stats: raise ValueError(line)
                    stats[match[1]] = int(match[2])
                if run.returncode or run.stdout != golden or stats.keys() != FIELDS: raise ValueError((name, opt, run, stats))
                if stats['allocs'] != allocations or stats['frees'] != allocations or any(stats[x] for x in ('live_bytes', 'unknown_frees', 'double_frees', 'ledger_overflows')):
                    raise ValueError((name, opt, 'allocation contract', stats))
                rows.append(dict(name=name,opt=opt,source=source,source_sha256=sha(src),binary_sha256=sha(binary),stats=stats))
                print('PASS',name,opt,stats,flush=True)
        for opt in args.modes.split(','):
            for name, source in alias_cases:
                source = source.replace(';', '\n')
                src = work / 'main.xu'; src.write_text(source)
                build = subprocess.run(['scripts/run_product_compiler.sh', str(compiler), 'build', *shlex.split(opt), str(src), '-o', str(work/'rejected')], cwd=ROOT, capture_output=True, text=True, timeout=120)
                diagnostic = 'string_from_bytes bounds must be evaluated before borrowing the buffer'
                if build.returncode == 0 or diagnostic not in build.stderr:
                    raise ValueError((name, opt, 'alias call was not rejected', build))
                alias_rows.append(dict(name=name, opt=opt, source=source, source_sha256=sha(src), exit=build.returncode, stderr=build.stderr))
                print('PASS alias guard', name, opt, flush=True)
        # A baseline must provide its own runtime source: both compiler and
        # algorithm changed, and old checker cannot consume the new overload.
        baseline = None
        if args.old:
            if not args.old_runtime: raise ValueError('--old requires --old-runtime')
            (work/'main').mkdir();(work/'runtime').mkdir()
            (work/'main/main.xu').write_text(loop)
            (work/'runtime/mod.xu').write_text(args.old_runtime.read_text())
            b=work/'old-program'
            build=subprocess.run(['scripts/run_product_compiler.sh',str(args.old.resolve()),'build','-O1',str(work/'main/main.xu'),str(work/'runtime/mod.xu'),'-o',str(b)],cwd=ROOT,env=dict(os.environ,XU_GEN1_HEAP_LEDGER='1'),capture_output=True,text=True,timeout=120)
            if build.returncode:raise ValueError(build.stderr)
            run=subprocess.run([str(b)],env=dict(os.environ,XU_HEAP_STATS='1'),capture_output=True,text=True,timeout=30)
            if run.returncode or run.stdout!='9718\n':raise ValueError(run)
            stats={m[1]:int(m[2]) for line in run.stderr.splitlines() if (m:=re.fullmatch(r'xu_heap_stats ([a-z_]+)=([0-9]+)',line))}
            if stats.keys()!=FIELDS or stats['allocs']!=stats['frees'] or any(stats[x] for x in ('live_bytes','unknown_frees','double_frees','ledger_overflows')):raise ValueError(stats)
            baseline=dict(compiler=str(args.old.resolve()),compiler_sha256=sha(args.old),runtime_sha256=sha(args.old_runtime),source=loop,binary_sha256=sha(b),stats=stats)
    assert sha(compiler)==identity
    assert closure==json.loads(subprocess.check_output(['python3','scripts/check_bootstrap_xu_boundary.py','--strict-freeze','--json'],cwd=ROOT))['source_manifest']
    args.out.write_text(json.dumps(dict(status='PASS',compiler=str(compiler),compiler_sha256=identity,source_manifest=closure,results=rows,alias_guard_results=alias_rows,baseline=baseline),indent=2)+'\n')
    print('PASS:',len(rows),'bounded-buffer cases;',len(alias_rows),'alias guards')

if __name__ == '__main__':main()
