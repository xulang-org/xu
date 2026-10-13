#!/usr/bin/env python3
"""Exercise the compiler's symbol registry through its real Xu implementation."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = '''@main
fn main() int {
    argv := args()
    mut a := Assembler{arch: 0}
    if argv.len > 1 && argv[1] == "baseline" {
        println("symbols ok")
        << 0
    }
    if argv.len > 1 && argv[1] == "duplicate" {
        a.label("same")
        a.emit32(0)
        a.data_label("same")
        << 99
    }
    if argv.len > 1 && argv[1] == "unknown" {
        a.b("never_defined")
        a.fixup_all()
        << 99
    }
    a.b("weohjrvxjgxo")
    a.label("bbtplmxsqwul")
    a.emit32(0)
    a.label("weohjrvxjgxo")
    // Grow the probing table after recording a forward relocation.
    for i in 0:2000 { a.label("other_" + str(i)) }
    a.data_label("_xus_9")
    a.emit_data([65, 66])
    for i in 0:10 { a.xus_off.push(0) }
    a.lea_xus(8, 9)
    a.code_vaddr = 4096
    a.data_vaddr = 8192
    a.fixup_all()
    // The branch must target byte 8, not the colliding label at byte 4.
    word := a.code[0] | (a.code[1] << 8) | (a.code[2] << 16) | (a.code[3] << 24)
    if word != 335544322 { << 2 }
    // Object serialization keeps the external relocation ABI (full names).
    object := a.snapshot_xuobj("test", []XuExport{}, 0, 0)
    bytes := xuobj_encode(&object)
    decoded := xuobj_decode(bytes)
    mut linked := Assembler{arch: 0}
    linked.b("weohjrvxjgxo")
    linked.merge_xuobj(&decoded)
    linked.code_vaddr = 4096
    linked.data_vaddr = 8192
    linked.fixup_all()
    first := linked.code[0] | (linked.code[1] << 8) | (linked.code[2] << 16) | (linked.code[3] << 24)
    second := linked.code[4] | (linked.code[5] << 8) | (linked.code[6] << 16) | (linked.code[7] << 24)
    if first != 335544323 || second != 335544322 { << 3 }
    literal_word := linked.code[12] | (linked.code[13] << 8) | (linked.code[14] << 16) | (linked.code[15] << 24)
    if literal_word != 2952790024 { << 5 }
    mut objects := []XuObject{}
    objects.push(decoded)
    options := BuildOpts{names: []string{}, filter: "", verbose: false, cover: false,
        test: false, debug: false, timings: false, no_regcache: false,
        opt_level: 0, ra_level: 0, lib: false, shared: false, emit_obj: false,
        objs: objects, failfast: false, count: 1, list: false, short: false, bench: ""}
    mut driver_linked := Assembler{arch: 0}
    driver_linked.b("weohjrvxjgxo")
    build_link_static_objs(mut &driver_linked, &options)
    driver_linked.code_vaddr = 4096
    driver_linked.data_vaddr = 8192
    driver_linked.fixup_all()
    driver_first := driver_linked.code[0] | (driver_linked.code[1] << 8) | (driver_linked.code[2] << 16) | (driver_linked.code[3] << 24)
    if driver_first != 335544323 { << 4 }
    // Compiler block labels share long prefixes and numeric/_ht suffixes.
    // Force several table growths, then check every stable symbol/offset
    // through the borrowed lookup and the legacy owning lookup.
    stress_start := a.code.len
    for i in 0:16384 {
        a.label("_xu_compile_fn_" + str(i / 512) + "_bb" + str(i % 512) + "_ht")
        a.emit32(0)
    }
    for i in 0:16384 {
        name := "_xu_compile_fn_" + str(i / 512) + "_bb" + str(i % 512) + "_ht"
        sym := a.label_index_ref(&name)
        if sym < 0 || lab_off(&a.labels, sym) != stress_start + i * 4 { << 6 }
    }
    first_name := "_xu_compile_fn_0_bb0_ht"
    last_name := "_xu_compile_fn_31_bb511_ht"
    if a.label_index(first_name) != a.label_index_ref(&"_xu_compile_fn_0_bb0_ht") { << 7 }
    if a.label_index(last_name) != a.label_index_ref(&"_xu_compile_fn_31_bb511_ht") { << 8 }
    println("symbols ok")
    << 0
}
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    compiler = args.xu.resolve()
    identity = sha(compiler)
    source_paths = subprocess.check_output(['bash', '-c',
        '. scripts/gen1_sources.sh; printf "%s\\n" "$GEN1_SRCS"'], cwd=ROOT, text=True).split()
    source_identity = {p: sha(ROOT / p) for p in source_paths}
    rows = []
    with tempfile.TemporaryDirectory(prefix='xu-symbols-') as td:
        work = Path(td) / "main"
        work.mkdir()
        driver = work / 'driver_entry.xu'
        source = (ROOT / 'src/cmd/compile/driver_entry.xu').read_text()
        if source.count('fn main() int {') != 1:
            raise ValueError('compiler entry point changed')
        driver.write_text(source.replace('fn main() int {', 'fn compiler_entry() int {'))
        driver_identity = sha(driver)
        harness = work / 'symbol_test.xu'
        defaults = re.search(r"mut a := (Assembler\{.*?^    \})", (ROOT / 'src/cmd/compile/driver_build.xu').read_text(), re.S | re.M)
        if defaults is None:
            raise ValueError('missing assembler defaults')
        harness_source = HARNESS.replace('Assembler{arch: 0}', defaults[1])
        harness.write_text(harness_source)
        paths = [str(driver) if p == 'src/cmd/compile/driver_entry.xu' else p for p in source_paths]
        for opt in ('-O0', '-O1'):
            binary = work / opt
            build = subprocess.run([str(ROOT / 'scripts/run_product_compiler.sh'), str(compiler),
                'build', opt, *paths, str(harness), '-o', str(binary)], cwd=ROOT,
                capture_output=True, text=True, timeout=240,
                env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'))
            if build.returncode:
                raise ValueError(build.stderr)
            for mode, code, stdout, stderr in (
                ('ok', 0, 'symbols ok\n', ''),
                ('duplicate', 1, '', 'duplicate assembly label: same\n'),
                ('unknown', 1, '', 'ERROR: Unknown label: never_defined\n'),
            ):
                run = subprocess.run([str(binary), mode], capture_output=True,
                                     text=True, timeout=30)
                if (run.returncode, run.stdout, run.stderr) != (code, stdout, stderr):
                    raise ValueError(f'{opt}/{mode}: {run}')
                rows.append(dict(opt=opt, mode=mode, exit=code, stdout=stdout, stderr=stderr,
                                 binary_sha256=sha(binary)))
            baseline = None
            for mode in ('baseline', 'ok______'):
                run = subprocess.run([str(binary), mode], capture_output=True, text=True,
                    timeout=30, env=dict(os.environ, XU_HEAP_STATS='1'))
                ledger = {}
                for line in run.stderr.splitlines():
                    item = re.fullmatch(r'xu_heap_stats ([a-z_]+)=([0-9]+)', line)
                    if not item or item[1] in ledger:
                        raise ValueError(f'invalid symbol ledger: {line}')
                    ledger[item[1]] = int(item[2])
                if run.returncode or run.stdout != 'symbols ok\n' or len(ledger) != 7:
                    raise ValueError(f'{opt}/{mode}: ledger golden mismatch: {run}')
                if any(ledger[k] for k in ('unknown_frees', 'double_frees', 'ledger_overflows')):
                    raise ValueError(f'{opt}/{mode}: invalid ownership: {ledger}')
                if baseline is None:
                    baseline = ledger
                if ledger['live_bytes'] != baseline['live_bytes'] or ledger['allocs'] - ledger['frees'] != baseline['allocs'] - baseline['frees']:
                    raise ValueError(f'{opt}: symbol operations retain allocations: {baseline}, {ledger}')
                rows.append(dict(opt=opt, mode=mode, ledger=ledger,
                                 binary_sha256=sha(binary)))
    if sha(compiler) != identity or source_identity != {p: sha(ROOT / p) for p in source_paths}:
        raise ValueError('compiler/source changed during symbol registry gate')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(status='PASS', compiler=str(compiler),
        compiler_sha256=identity, input_source_sha256=source_identity,
        driver_sha256=driver_identity,
        harness_sha256=hashlib.sha256(harness_source.encode()).hexdigest(),
        results=rows), indent=2) + '\n')
    print('PASS: exact symbols, forward fixups, table growth, duplicate and unknown rejection')


if __name__ == '__main__':
    main()
