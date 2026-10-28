#!/usr/bin/env python3
"""Compiler P1 regressions; fixtures and probe builds stay in a temporary directory.

Usage: python3 scripts/test_compiler_p1.py --xu bin/xu
Requires node and qemu-riscv32/qemu-riscv64 for execution checks.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''@main
#os
#xu/types
#xu/ast
#xu/parser
#xu/scanner

fn probe_dump(a &Assembler) {
    for i in 0:a.code.len { println(a.code[i]) }
}
fn probe_branch(a &mut Assembler, wide bool, cond int, expected bool) {
    ok := "probe_cmp_ok_" + str(a.drop_seq)
    a.drop_seq += 1
    mut target := "probe_fail"
    if expected { target = ok + "" }
    if wide {
        if cond == 0 { a.vbe_jeq(target + "") }
        if cond == 1 { a.vbe_jne(target + "") }
        if cond == 2 { a.vbe_jae(target + "") }
        if cond == 10 { a.vbe_jge(target + "") }
        if cond == 11 { a.vbe_jlt(target + "") }
        if cond == 12 { a.vbe_jgt(target + "") }
        if cond == 13 { a.vbe_jle(target + "") }
    } else {
        if cond == 0 { a.rbe_jeq(target + "") }
        if cond == 1 { a.rbe_jne(target + "") }
        if cond == 2 { a.rbe_jae(target + "") }
        if cond == 10 { a.rbe_jge(target + "") }
        if cond == 11 { a.rbe_jlt(target + "") }
        if cond == 12 { a.rbe_jgt(target + "") }
        if cond == 13 { a.rbe_jle(target + "") }
    }
    if cond == 3 { a.r_bcond_jal(false, 29, 0, target + "") }
    if expected { a.r_j("probe_fail") }
    a.label(ok)
}
fn probe_cmp(a &mut Assembler, wide bool) {
    mut vals := [-2147483648, -1, 0, 1, 2147483647]
    if wide { vals = [-9223372036854775807 - 1, -1, 0, 1, 9223372036854775807] }
    conds := [0, 1, 10, 11, 12, 13, 2, 3]
    for i in 0:vals.len {
        for j in 0:vals.len {
            x := vals[i]
            y := vals[j]
            for ci in 0:conds.len {
                cond := conds[ci]
                mut expect := false
                if cond == 0 { expect = x == y }
                if cond == 1 { expect = x != y }
                if cond == 10 { expect = x >= y }
                if cond == 11 { expect = x < y }
                if cond == 12 { expect = x > y }
                if cond == 13 { expect = x <= y }
                if cond == 2 { expect = (x < 0 && y >= 0) || ((x < 0) == (y < 0) && x >= y) }
                if cond == 3 { expect = (x >= 0 && y < 0) || ((x < 0) == (y < 0) && x < y) }
                for imm in 0:2 {
                    if wide {
                        a.vbe_mov_imm64(0, x)
                        a.vbe_mov_imm64(1, y)
                        if imm == 0 { a.vbe_cmp(0, 1) } else { a.vbe_cmp_imm(0, y) }
                        probe_branch(a, true, cond, expect)
                        a.vbe_cset(2, cond)
                    } else {
                        a.rbe_mov_imm(0, x)
                        a.rbe_mov_imm(1, y)
                        if imm == 0 { a.rbe_cmp(0, 1) } else { a.rbe_cmp_imm(0, y) }
                        probe_branch(a, false, cond, expect)
                        a.rbe_cset(2, cond)
                    }
                    mut expected := 0
                    if expect { expected = 1 }
                    a.r_li32(6, expected)
                    a.r_bcond_jal(false, 7, 6, "probe_fail")
                }
            }
        }
    }
    a.r_li32(10, 0)
    a.r_li32(17, 93)
    a.v_ecall()
    a.label("probe_fail")
    a.r_li32(10, 1)
    a.r_li32(17, 93)
    a.v_ecall()
    if wide { a.v_fixup_all() } else { a.r_fixup_all() }
}
fn probe_mem(a &mut Assembler) {
    a.rbe_prologue(8192)
    a.r_sub(5, 8, 2)
    a.r_li32(6, 8192)
    a.r_bcond_jal(false, 5, 6, "probe_fail")
    a.rbe_mov_imm(0, 12345)
    a.rbe_store(15, -4096, 0)
    a.rbe_load(1, 15, -4096)
    a.r_bcond_jal(false, 5, 6, "probe_fail")
    a.rbe_store(16, 4096, 0)
    a.rbe_load(1, 16, 4096)
    a.r_bcond_jal(false, 5, 6, "probe_fail")
    a.rbe_mov_imm(0, -4096)
    a.rbe_add_imm(1, 0, -4096)
    a.r_li32(7, -8192)
    a.r_bcond_jal(false, 6, 7, "probe_fail")
    a.rbe_sub_imm(1, 0, -4096)
    a.r_bcond_jal(false, 6, 0, "probe_fail")
    for i in 0:256 {
        a.rbe_mov_imm(0, i)
        a.rbe_store_byte(15, -4097, 0)
        a.rbe_load_byte(1, 15, -4097)
        a.r_bcond_jal(false, 5, 6, "probe_fail")
    }
    a.r_li32(10, 0)
    a.r_li32(17, 93)
    a.v_ecall()
    a.label("probe_fail")
    a.r_li32(10, 1)
    a.r_li32(17, 93)
    a.v_ecall()
    a.r_fixup_all()
}
fn probe_store(a &mut Assembler) {
    mut toks := []ast.Token{}
    scanner.lex("@main\nfn main() { mut xs := [\"a\"]\n xs[0] = \"b\"\n println(xs[0])\n}\n", mut &toks, "probe.xu")
    mut p := parser.new_parser(toks)
    p.parse_module()
    mut c := types.Checker{}
    mut m := types.empty_mir()
    mut fs := []types.CFn{}
    types.run_checker(mut &c, &p, 11, 0, 0, []string{}, []string{}, 1, mut &m, []string{}, "", false, false, 1, false, mut &fs)
    mut ct := CoverTable{files: []int{}, lines: []int{}}
    calls := types.new_mir_call_index(&m)
    for fi in 0:m.fns.len {
        for ii in 0:types.mir_nins(&m, fi) {
            if types.mir_ikind(&m, fi, ii) == types.MI_STORE_INDEX {
                ai := emit_store_index_array_id(&m, fi, types.mir_ia(&m, fi, ii))
                m.arrays[ai].elem_bytes = 7
                emit_function(a, &m, fi, &ct, &calls)
                eprintln("probe: invalid StoreIndex was accepted")
                <<< 2
            }
        }
    }
    eprintln("probe: no StoreIndex reached")
    <<< 2
}
fn probe_num(s string) int {
    mut v := 0
    mut sign := 1
    for i in 0:s.len {
        if s[i] == 45 { sign = -1 } else { v = v * 10 + s[i] - 48 }
    }
    << v * sign
}
fn probe_fixup(a &mut Assembler, mode string, rel int) {
    a.code_vaddr = 8589934592
    a.data_vaddr = a.code_vaddr + rel
    a.data_label("probe_target")
    if mode == "a64_b" { a.arch = 0
        a.b("probe_target") }
    if mode == "a64_cb" { a.arch = 0
        a.cbz(0, "probe_target") }
    if mode == "a64_addr" { a.arch = 0
        a.lea_rip_rel(0, "probe_target") }
    if mode == "rv32_b" { a.arch = 3
        a.r_j("probe_target") }
    if mode == "rv32_addr" { a.arch = 3
        a.data_vaddr = rel
        a.r_lea_abs(5, "probe_target") }
    if mode == "rv64_b" { a.arch = 5
        a.r_j("probe_target") }
    if mode == "rv64_addr" { a.arch = 5
        a.v_lea(5, "probe_target") }
    if mode == "rv_imm" { a.arch = 3
        a.r_beq(5, 6, rel) }
    if mode == "loong_b" { a.arch = 4
        a.l_b("probe_target") }
    if mode == "loong_b16" { a.arch = 4
        a.l_beq(4, 5, "probe_target") }
    if mode == "loong_b21" { a.arch = 4
        a.l_beqz(4, "probe_target") }
    if mode == "loong_fp" { a.arch = 4
        a.l_push_fixup(23, "probe_target", 0)
        a.emit32(0) }
    if mode == "loong_addr" { a.arch = 4
        a.l_lea(4, "probe_target") }
    if mode == "x64_b" { a.arch = 1
        a.data_vaddr += 5
        a.x64_jmp("probe_target") }
    a.fixup_all()
}
fn probe_atomics(a &mut Assembler, thumb bool) {
    if thumb { a.arch = 2 } else { a.arch = 5 }
    a.be_atomic_load(0, 1)
    a.be_atomic_store(1, 2)
    a.be_atomic_xchg(0, 1, 2)
    a.be_atomic_add(0, 1, 2)
    a.be_atomic_cas(0, 1, 2, 3)
}
fn main() int {
    args := os.argv()
    mode := args[1]
    mut a := Assembler{}
    a.os = 1
    a.arch = 3
    if mode == "cmp64" { a.arch = 5 }
    if mode == "cmp32" || mode == "cmp64" { probe_cmp(mut &a, mode == "cmp64") }
    if mode == "mem32" { probe_mem(mut &a) }
    if mode == "store" { a.arch = 1
        probe_store(mut &a) }
    if mode == "i12" { a.r_addi(5, 5, 4096) }
    if mode == "atomic_rv" || mode == "atomic_thumb" { probe_atomics(mut &a, mode == "atomic_thumb") }
    if args.len > 2 { probe_fixup(mut &a, mode, probe_num(args[2])) }
    probe_dump(&a)
    << 0
}
'''


def run(cmd, *, env, expected=0, contains=None, timeout=240):
    result = subprocess.run(list(map(str, cmd)), cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    assert result.returncode == expected, f'{cmd[0]}: exit {result.returncode}\n{result.stdout}\n{result.stderr}'
    if contains:
        assert contains in result.stderr, result.stderr
    return result


def elf(code, wide):
    base = 0x10000
    if wide:
        size = 64 + 56
        hdr = struct.pack('<16sHHIQQQIHHHHHH', b'\x7fELF\x02\x01\x01'+bytes(9), 2, 243, 1, base+size, 64, 0, 0, 64, 56, 1, 0, 0, 0)
        ph = struct.pack('<IIQQQQQQ', 1, 7, 0, base, base, size+len(code), size+len(code), 4096)
    else:
        size = 52 + 32
        hdr = struct.pack('<16sHHIIIIIHHHHHH', b'\x7fELF\x01\x01\x01'+bytes(9), 2, 243, 1, base+size, 52, 0, 0, 52, 32, 1, 0, 0, 0)
        ph = struct.pack('<IIIIIIII', 1, 0, base, base, size+len(code), size+len(code), 7, 4096)
    return hdr + ph + code


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--xu', default='bin/xu')
    parser.add_argument('--front-only', action='store_true')
    parser.add_argument('--backend-only', action='store_true')
    opts = parser.parse_args()
    xu = (ROOT / opts.xu).resolve()
    env = os.environ.copy()
    env.update(XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / 'src'), XUPATH='')
    with tempfile.TemporaryDirectory(prefix='xu-p1-test-') as temp:
        tmp = Path(temp)
        env['XU_CACHE'] = str(tmp / 'cache')
        def fixture(name, source, error=None, output=None, extra=(), runner=()):
            src = tmp / (name + '.xu')
            out = tmp / name
            src.write_text('@main\n' + source)
            run([xu, 'build', '-O0', *extra, src, '-o', out], env=env, expected=1 if error else 0, contains=error)
            if error:
                assert not out.exists(), f'{name}: failed build produced executable'
            elif output is not None:
                assert run([*runner, out], env=env).stdout == output, name
            print('PASS', name, flush=True)
            return out
        if not opts.backend_only:
            fixture('undefined_spawn', 'fn main() { xu missing() }', 'undefined function')
            fixture('invalid_send', 'fn main() { x := 1\n x <- 2\n}', 'send requires a channel')
            fixture('call_loan', 'fn identity(x &int) &int { << x }\nfn main() { mut x := 1\n r := identity(&x)\n x = 2\n println(*r)\n}', 'because it is borrowed')
            fixture('branch_loan', 'fn bad(flag bool) { mut xs := [1]\n ys := [2]\n mut r := &xs[0]\n if flag { r = &ys[0] }\n xs.push(3)\n println(*r)\n}\nfn main() { bad(false) }', 'reference-bearing value across control-flow')
            fixture('nested_loan', 'struct Inner { r &int }\nstruct Outer { inner Inner }\nfn main() { mut x := 1\n h := Outer{inner: Inner{r: &x}}\n x = 2\n println(*h.inner.r)\n}', 'because it is borrowed')
            fixture('nested_assign_loan', 'struct Inner { r &int }\nstruct Outer { inner Inner }\nfn main() { mut x := 1\n y := 2\n mut h := Outer{inner: Inner{r: &y}}\n h.inner = Inner{r: &x}\n x = 3\n println(*h.inner.r)\n}', 'because it is borrowed')
            fixture('field_escape', 'struct Holder { r &int }\nfn bad(h &mut Holder) { x := 1\n h.r = &x\n}\nfn main() { y := 2\n mut h := Holder{r: &y}\n bad(mut &h)\n println(*h.r)\n}', 'without a proven lifetime')
            fixture('closure_loan', 'fn main() { mut x := 1\n r := &x\n f := fn() int { << *r }\n x = 2\n println(f())\n}', 'because it is borrowed')
            fixture('param_reborrow', 'fn bad(p &mut int) { r := &*p\n *p = 3\n println(*r)\n}\nfn main() { mut x := 1\n bad(mut &x)\n}', 'mutably borrowed')
            chain = 'fn bad(p &mut int) {\n r0 := mut &*p\n' + ''.join(f' r{i} := mut &*r{i-1}\n' for i in range(1, 12)) + ' *p = 2\n println(*r11)\n}\nfn main() { mut x := 1\n bad(mut &x)\n}'
            fixture('long_reborrow', chain, 'mutably borrowed')
            fixture('late_reborrow', 'fn main() { mut xs := [1]\n r := &xs[0]\n xs.push(2)\n q := &*r\n println(*q)\n}', 'element is borrowed')
            fixture('shared_and_last_use', 'struct Item { value int }\nfn shared(p &Item) int { r := &p.value\n << p.value + *r\n}\nfn main() { mut x := 1\n r := &x\n println(*r)\n x = 2\n a := Item{value: 3}\n println(shared(&a))\n}', output='1\n6\n')
            fixture('mutable_field', 'struct Inner { x int }\nstruct Outer { inner Inner, y int }\nfn (p &mut Inner) set(v int) { p.x = v }\nfn change(p &mut Outer) { r := mut &p.inner\n r.set(2)\n p.y = 3\n}\nfn main() { mut v := Outer{inner: Inner{x: 1}, y: 0}\n change(mut &v)\n println(v.y)\n}', output='3\n')
        if opts.front_only:
            return
        # Keep the real compiler functions; only rename its CLI entry point.
        entry = tmp / 'driver_entry.xu'
        text = (ROOT / 'src/cmd/compile/driver_entry.xu').read_text()
        assert text.count('\nfn main() int {') == 1
        entry.write_text(text.replace('\nfn main() int {', '\nfn compiler_cli_main() int {'))
        probe = tmp / 'probe.xu'
        assembler = (ROOT / 'src/cmd/compile/asm_arm64.xu').read_text().split('struct Assembler {', 1)[1].split('\n}', 1)[0]
        fields = []
        for name, ty in re.findall(r'^    (\w+)\s+(\[\]\w+|int|bool|string)\s*(?://.*)?$', assembler, re.M):
            zero = ty + '{}' if ty.startswith('[]') else {'int': '0', 'bool': 'false', 'string': '""'}[ty]
            fields.append(f'{name}: {zero}')
        probe.write_text(PROBE.replace('Assembler{}', 'Assembler{' + ', '.join(fields) + '}'))
        sources = sorted((ROOT / 'src/cmd/compile').glob('*.xu'))
        sources.remove(ROOT / 'src/cmd/compile/driver_entry.xu')
        for source in sources:
            shutil.copy2(source, tmp / source.name)
        sources = [tmp / source.name for source in sources]
        executable = tmp / 'probe'
        run([xu, 'build', '-O0', probe, entry, *sources, '-o', executable], env=env, timeout=600)
        run([executable, 'store'], env=env, expected=1, contains='malformed StoreIndex owning-element metadata')
        print('PASS invalid_storeindex', flush=True)
        run([executable, 'i12'], env=env, expected=1, contains='12-bit range')
        print('PASS raw_i12_reject', flush=True)
        for mode, wide in [('cmp32', False), ('cmp64', True), ('mem32', False)]:
            result = run([executable, mode], env=env)
            code = bytes(int(s) for s in result.stdout.splitlines())
            image = tmp / mode
            image.write_bytes(elf(code, wide))
            image.chmod(0o755)
            emulator = shutil.which('qemu-riscv64' if wide else 'qemu-riscv32')
            assert emulator, 'qemu-user required'
            run([emulator, image], env=env)
            print('PASS', mode, flush=True)
        bounds = [
            ('a64_b', -134217728, 134217724, 4),
            ('a64_cb', -1048576, 1048572, 4),
            ('a64_addr', -4294967296, 4294963200, 4096),
            ('rv32_b', -1048576, 1048574, 2),
            ('rv32_addr', 0, 4294967295, 1),
            ('rv64_b', -2147485696, 2147481598, 2),
            ('rv64_addr', -2147485696, 2147481599, 1),
            ('rv_imm', -4096, 4094, 2),
            ('loong_b', -134217728, 134217724, 4),
            ('loong_b16', -131072, 131068, 4),
            ('loong_b21', -4194304, 4194300, 4),
            ('loong_fp', -4194304, 4194300, 4),
            ('loong_addr', -2147485696, 2147481599, 1),
            ('x64_b', -2147483648, 2147483647, 1),
        ]
        for mode, lo, hi, step in bounds:
            for value in (lo, hi):
                run([executable, mode, value], env=env)
            for value in (lo-step, hi+step):
                run([executable, mode, value], env=env, expected=1, contains='range')
            if step in (2, 4):
                run([executable, mode, 1], env=env, expected=1, contains='misaligned')
            print('PASS fixup', mode, flush=True)
        result = run([executable, 'atomic_rv'], env=env)
        code = bytes(int(s) for s in result.stdout.splitlines())
        words = struct.unpack('<' + 'I'*(len(code)//4), code)
        amos = [w for w in words if w & 127 == 47]
        assert len(amos) == 4 and all(w & 0x6000000 == 0x6000000 for w in amos)
        assert words.count(0x0330000F) == 10
        result = run([executable, 'atomic_thumb'], env=env)
        code = bytes(int(s) for s in result.stdout.splitlines())
        assert code.count(bytes.fromhex('bff35f8f')) == 10
        print('PASS atomic_order_encodings', flush=True)
        spawn = '''enum Message { Text(string) }
fn worker(gate chan int, out chan string, value Message) {
    token := <-gate
    match value { Message.Text(s) { out <- s } }
}
fn launch(gate chan int, out chan string) {
    value := Message.Text("spawn enum payload")
    xu worker(gate, out, value)
}
fn churn(x int) int { vals := [x, x+1, x+2, x+3, x+4, x+5, x+6, x+7]
    << vals[7]
}
fn main() { gate := chan int{cap: 1}
    out := chan string{cap: 1}
    launch(gate, out)
    for i in 0:100 { churn(i) }
    gate <- 1
    println(<-out)
}'''
        for opt in ('-O0', '-O2'):
            fixture('spawn_enum_host' + opt, spawn, output='spawn enum payload\n', extra=(opt,))
            fixture('spawn_enum_rv' + opt, spawn, output='spawn enum payload\n', extra=(opt, '--target', 'linux-riscv64'), runner=('qemu-riscv64',))
        atomic = '''fn main() { mut value := 0
    atomic_store(mut &value, 42)
    println(atomic_load(mut &value))
    println(atomic_add(mut &value, 5))
    println(atomic_cas(mut &value, 47, 99))
    println(atomic_cas(mut &value, 47, 100))
    println(atomic_load(mut &value))
}'''
        fixture('rv_atomic_values', atomic, output='42\n42\ntrue\nfalse\n99\n', extra=('--target', 'linux-riscv64'), runner=('qemu-riscv64',))
        fixture('rv_channel_contention', '''fn worker(ch chan int) {
    for i in 0:100 { ch <- 1 }
}
fn main() { ch := chan int{cap: 0}
    for i in 0:8 { xu worker(ch) }
    mut sum := 0
    for i in 0:800 { sum += <-ch }
    println(sum)
}''', output='800\n', extra=('--target', 'linux-riscv64'), runner=('qemu-riscv64',))
        channel = 'fn main() { ch := chan int{cap: 1}\n ch <- 4294967297\n println(<-ch)\n}'
        fixture('thumb_channel_reject', channel, 'Thumb spawn/channel ABI', extra=('--target', 'linux-arm32'))
        fixture('thumb_spawn_reject', 'fn worker(a int, b int, c int) {}\nfn main() { xu worker(1, 2, 3) }', 'Thumb spawn/channel ABI', extra=('--target', 'linux-arm32'))
        for target in ('riscv32imac-none', 'thumbv7em-none'):
            fixture('freestanding_reject_' + target, channel.replace('4294967297', '1'), 'require a suspendable scheduler', extra=('--target', target))
        wasm = fixture('casts.wasm', '''pub fn signed(x int) int { << int(i32(x)) }
pub fn unsigned(x int) int { << int(u32(x)) }
pub fn bytecast(x int) int { << int(u8(x)) }
pub fn neg(x int) int { << -x }
pub fn logical(x bool) bool { << !x }
fn main() {}''', extra=('--target', 'wasm32'))
        js = '''const fs = require('fs');
WebAssembly.instantiate(fs.readFileSync(process.argv[1]), {}).then(({instance}) => {
  const e = instance.exports, m = new DataView(e.memory.buffer);
  const values = [-(1n<<63n), -4294967297n, -2147483649n, -257n, -1n, 0n, 1n, 127n, 128n, 255n, 256n, 2147483647n, 2147483648n, 4294967295n, 4294967296n, (1n<<63n)-1n];
  const checks = [['signed', x=>BigInt.asIntN(32,x)], ['unsigned', x=>BigInt.asUintN(32,x)], ['bytecast', x=>BigInt.asUintN(8,x)], ['neg', x=>BigInt.asIntN(64,-x)], ['logical', x=>x===0n?1n:0n]];
  for (const x of values) for (const [fn, expected] of checks) {
    m.setBigInt64(4096, x, true);
    e[fn+'_frame'](4096, 8192);
    if (m.getBigInt64(8192, true) !== expected(x)) throw Error(fn+': '+x);
  }
}).catch(e=>{console.error(e);process.exit(1)});'''
        run(['node', '-e', js, wasm], env=env)
        print('PASS wasm_cast_execution', flush=True)
        fixture('wasm_float_reject', 'pub fn convert(x f64) int { << int(x) }\nfn main() {}', 'floating-point casts are not implemented', extra=('--target', 'wasm32'))
    print('compiler P1: PASS', flush=True)


if __name__ == '__main__':
    main()
