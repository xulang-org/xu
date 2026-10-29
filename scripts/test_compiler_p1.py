#!/usr/bin/env python3
"""Compiler P1 regressions; fixtures and probe builds stay in a temporary directory.

Usage: python3 scripts/test_compiler_p1.py --xu bin/xu
Requires node and qemu-user (ARM32/ARM64/LoongArch64/RV32/RV64).
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

from borrow_phase_c_cases import check_phase_c, check_phase_c_backends

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
fn probe_branch(a $&Assembler, wide bool, cond int, expected bool) {
    ok := "probe_cmp_ok_" + str(a.drop_seq)
    a.drop_seq += 1
    $target := "probe_fail"
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
fn probe_cmp(a $&Assembler, wide bool) {
    $vals := [-2147483648, -1, 0, 1, 2147483647]
    if wide { vals = [-9223372036854775807 - 1, -1, 0, 1, 9223372036854775807] }
    conds := [0, 1, 10, 11, 12, 13, 2, 3]
    for i in 0:vals.len {
        for j in 0:vals.len {
            x := vals[i]
            y := vals[j]
            for ci in 0:conds.len {
                cond := conds[ci]
                $expect := false
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
                    $expected := 0
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
fn probe_loong_cmp(a $&Assembler) {
    a.arch = 4
    vals := [-9223372036854775807 - 1, -1, 0, 1, 9223372036854775807]
    conds := [0, 1, 10, 11, 12, 13, 2]
    for i in 0:vals.len {
        for j in 0:vals.len {
            x := vals[i]
            y := vals[j]
            for ci in 0:conds.len {
                cond := conds[ci]
                $expect := false
                if cond == 0 { expect = x == y }
                if cond == 1 { expect = x != y }
                if cond == 10 { expect = x >= y }
                if cond == 11 { expect = x < y }
                if cond == 12 { expect = x > y }
                if cond == 13 { expect = x <= y }
                if cond == 2 { expect = (x < 0 && y >= 0) || ((x < 0) == (y < 0) && x >= y) }
                for imm in 0:2 {
                    a.lbe_mov_imm64(0, x)
                    a.lbe_mov_imm64(1, y)
                    if imm == 0 { a.lbe_cmp(0, 1) } else { a.lbe_cmp_imm(0, y) }
                    ok := "_probe_l_ok_" + str(a.drop_seq)
                    a.drop_seq += 1
                    $target := "_probe_l_fail"
                    if expect { target = ok + "" }
                    if cond == 0 { a.lbe_jeq(target + "") }
                    if cond == 1 { a.lbe_jne(target + "") }
                    if cond == 10 { a.lbe_jge(target + "") }
                    if cond == 11 { a.lbe_jlt(target + "") }
                    if cond == 12 { a.lbe_jgt(target + "") }
                    if cond == 13 { a.lbe_jle(target + "") }
                    if cond == 2 { a.lbe_jae(target + "") }
                    if expect { a.l_b("_probe_l_fail") }
                    a.label(ok)
                }
            }
        }
    }
    a.lbe_mov_imm(0, 0)
    a.lbe_cbnz(0, "_probe_l_fail")
    a.lbe_cbz(0, "_probe_l_zero")
    a.l_b("_probe_l_fail")
    a.label("_probe_l_zero")
    a.lbe_mov_imm(0, 1)
    a.lbe_cbz(0, "_probe_l_fail")
    a.lbe_cbnz(0, "_probe_l_done")
    a.l_b("_probe_l_fail")
    a.label("_probe_l_done")
    a.l_mov_imm(4, 0)
    a.l_mov_imm(11, 93)
    a.l_syscall()
    a.label("_probe_l_fail")
    a.l_mov_imm(4, 1)
    a.l_mov_imm(11, 93)
    a.l_syscall()
    a.l_fixup_all()
}
fn probe_mem(a $&Assembler) {
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
fn probe_store(a $&Assembler) {
    $toks := []ast.Token{}
    scanner.lex("@main\nfn main() { mut xs := [\"a\"]\n xs[0] = \"b\"\n println(xs[0])\n}\n", $&toks, "probe.xu")
    $p := parser.new_parser(toks)
    p.parse_module()
    $c := types.Checker{}
    $m := types.empty_mir()
    $fs := []types.CFn{}
    types.run_checker($&c, &p, 11, 0, 0, []string{}, []string{}, 1, $&m, []string{}, "", false, false, 1, false, $&fs)
    $ct := CoverTable{files: []int{}, lines: []int{}}
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
    $v := 0
    $sign := 1
    for i in 0:s.len {
        if s[i] == 45 { sign = -1 } else { v = v * 10 + s[i] - 48 }
    }
    << v * sign
}
fn probe_fixup(a $&Assembler, mode string, rel int) {
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
    if mode == "loong_far_eq" { a.arch = 4
        a.lbe_jeq("probe_target") }
    if mode == "loong_far_zero" { a.arch = 4
        a.lbe_cbz(0, "probe_target") }
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
fn probe_atomics(a $&Assembler, thumb bool) {
    if thumb { a.arch = 2 } else { a.arch = 5 }
    a.be_atomic_load(0, 1)
    a.be_atomic_store(1, 2)
    a.be_atomic_xchg(0, 1, 2)
    a.be_atomic_add(0, 1, 2)
    a.be_atomic_cas(0, 1, 2, 3)
}
// Execute the actual freestanding nonblocking runtime under qemu-user.
// Only allocation and process exit are supplied by this standalone harness;
// the channel new/try/close functions below are the production emitters.
fn probe_chan_call(a $&Assembler, lab string, src string) {
    a.load(18, 15, -8)
    a.lea(19, src)
    a.vm_mov_imm(20, 2)
    a.call(lab)
}
fn probe_chan_expect(a $&Assembler, value int) {
    a.vm_cmp_imm(14, value)
    a.jne("_probe_fail")
}
fn probe_chan_exit(a $&Assembler, code int) {
    if a.arch == 2 {
        a.t_mov_imm(0, code)
        a.t_mov_imm(7, 1)
        a.t_svc(0)
    } else {
        a.r_li32(10, code)
        a.r_li32(17, 93)
        a.v_ecall()
    }
}
fn probe_chan(a $&Assembler, thumb bool) {
    a.arch = 3
    if thumb { a.arch = 2 }
    a.os = 3
    a.code_vaddr = 65620
    a.prologue(32)
    a.vm_mov_imm(18, 2)
    a.vm_mov_imm(19, 2)
    a.call("_rt_chan_new")
    a.store(15, -8, 14)
    probe_chan_call(a, "_rt_chan_try_send", "_probe_src")
    probe_chan_expect(a, 1)
    probe_chan_call(a, "_rt_chan_try_send", "_probe_src2")
    probe_chan_expect(a, 1)
    probe_chan_call(a, "_rt_chan_try_send", "_probe_src")
    probe_chan_expect(a, 0)
    for pass in 0:2 {
        probe_chan_call(a, "_rt_chan_try_recv", "_probe_dst")
        probe_chan_expect(a, 1)
        a.lea(0, "_probe_dst")
        $src := "_probe_src"
        if pass == 1 { src = "_probe_src2" }
        a.lea(1, src)
        for word in 0:4 {
            a.load(2, 0, word * 4)
            a.load(3, 1, word * 4)
            a.cmp(2, 3)
            a.jne("_probe_fail")
        }
    }
    probe_chan_call(a, "_rt_chan_try_recv", "_probe_dst")
    probe_chan_expect(a, 0)
    a.load(18, 15, -8)
    a.call("_rt_chan_close")
    probe_chan_call(a, "_rt_chan_try_recv", "_probe_dst")
    probe_chan_expect(a, 2)
    a.lea(0, "_probe_dst")
    for word in 0:4 {
        a.load(2, 0, word * 4)
        a.vm_cmp_imm(2, 0)
        a.jne("_probe_fail")
    }
    probe_chan_exit(a, 0)
    a.label("_rt_al_oom")
    a.label("_rt_exit")
    a.label("_probe_fail")
    probe_chan_exit(a, 1)
    a.label("_rt_alloc")
    a.lea(14, "_probe_arena")
    a.vm_ret()
    a.label("_rt_free")
    a.vm_ret()
    rt_emit_chan_new(a)
    rt_emit_chan_try_send(a)
    rt_emit_chan_try_recv(a)
    rt_emit_chan_close(a)
    a.data_label("_probe_src")
    rt_emit_u64(a, 4294967297)
    rt_emit_u64(a, -8589934597)
    a.data_label("_probe_src2")
    rt_emit_u64(a, -4294967299)
    rt_emit_u64(a, 12884901895)
    a.data_label("_probe_dst")
    rt_emit_zeros(a, 16)
    a.data_label("_probe_arena")
    rt_emit_zeros(a, RT_CHAN_HEADER_BYTES + 32)
    a.data_vaddr = a.code_vaddr + a.code.len
    a.fixup_all()
    for i in 0:a.data.len { a.code.push(a.data[i]) }
}
fn probe_loong_jump(a $&Assembler, cond int, label string) {
    if cond == 0 { a.lbe_jeq(label) }
    if cond == 1 { a.lbe_jne(label) }
    if cond == 10 { a.lbe_jge(label) }
    if cond == 11 { a.lbe_jlt(label) }
    if cond == 12 { a.lbe_jgt(label) }
    if cond == 13 { a.lbe_jle(label) }
    if cond == 2 { a.lbe_jae(label) }
}
fn probe_loong_branches(a $&Assembler) {
    vals := [-1, 0, 1]
    conds := [0, 1, 10, 11, 12, 13, 2]
    $expected := []bool{}
    // The forward targets and backward tests are on the other side of a
    // spacer larger than I16 can encode. Exercise both paths of every jump.
    for i in 0:vals.len { for j in 0:vals.len { for ci in 0:conds.len {
        x := vals[i]
        y := vals[j]
        cond := conds[ci]
        $ok := false
        if cond == 0 { ok = x == y }
        if cond == 1 { ok = x != y }
        if cond == 10 { ok = x >= y }
        if cond == 11 { ok = x < y }
        if cond == 12 { ok = x > y }
        if cond == 13 { ok = x <= y }
        if cond == 2 { ok = (x < 0 && y >= 0) || ((x < 0) == (y < 0) && x >= y) }
        id := str(expected.len)
        expected.push(ok)
        a.l_mov_imm(4, x)
        a.l_mov_imm(5, y)
        probe_loong_jump(a, cond, "forward_" + id)
        if ok { a.l_b("fail") }
        a.label("continue_forward_" + id)
    } } }
    a.l_b("backward_tests")
    for i in 0:expected.len {
        a.label("backward_" + str(i))
        if expected[i] { a.l_b("continue_backward_" + str(i)) } else { a.l_b("fail") }
    }
    for i in 0:40000 { a.l_addi_d(0, 0, 0) }
    for i in 0:expected.len {
        a.label("forward_" + str(i))
        if expected[i] { a.l_b("continue_forward_" + str(i)) } else { a.l_b("fail") }
    }
    a.label("backward_tests")
    for i in 0:vals.len { for j in 0:vals.len { for ci in 0:conds.len {
        index := (i * vals.len + j) * conds.len + ci
        a.l_mov_imm(4, vals[i])
        a.l_mov_imm(5, vals[j])
        probe_loong_jump(a, conds[ci], "backward_" + str(index))
        if expected[index] { a.l_b("fail") }
        a.label("continue_backward_" + str(index))
    } } }
    a.l_mov_imm(4, 0)
    a.l_mov_imm(11, 93)
    a.l_syscall()
    a.label("fail")
    a.l_mov_imm(4, 1)
    a.l_mov_imm(11, 93)
    a.l_syscall()
    a.l_fixup_all()
}
fn main() int {
    args := os.argv()
    mode := args[1]
    $a := Assembler{}
    a.os = 1
    a.arch = 3
    if mode == "chan_rv32" || mode == "chan_thumb" { probe_chan($&a, mode == "chan_thumb") }
    if mode == "loong_long" { a.arch = 4
        a.cmp_a = 4
        a.cmp_b = 5
        probe_loong_branches($&a) }
    if mode == "cmp64" { a.arch = 5 }
    if mode == "cmp32" || mode == "cmp64" { probe_cmp($&a, mode == "cmp64") }
    if mode == "mem32" { probe_mem($&a) }
    if mode == "cmp_loong" { probe_loong_cmp($&a) }
    if mode == "store" { a.arch = 1
        probe_store($&a) }
    if mode == "i12" { a.r_addi(5, 5, 4096) }
    if mode == "atomic_rv" || mode == "atomic_thumb" { probe_atomics($&a, mode == "atomic_thumb") }
    if args.len > 2 { probe_fixup($&a, mode, probe_num(args[2])) }
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


def elf(code, wide, thumb=False, loong=False):
    base = 0x10000
    if wide:
        size = 64 + 56
        hdr = struct.pack('<16sHHIQQQIHHHHHH', b'\x7fELF\x02\x01\x01'+bytes(9), 2, 258 if loong else 243, 1, base+size, 64, 0, 0, 64, 56, 1, 0, 0, 0)
        ph = struct.pack('<IIQQQQQQ', 1, 7, 0, base, base, size+len(code), size+len(code), 4096)
    else:
        size = 52 + 32
        hdr = struct.pack('<16sHHIIIIIHHHHHH', b'\x7fELF\x01\x01\x01'+bytes(9), 2, 40 if thumb else 243, 1, (base+size) | int(thumb), 52, 0, 0x05000200 if thumb else 0, 52, 32, 1, 0, 0, 0)
        ph = struct.pack('<IIIIIIII', 1, 0, base, base, size+len(code), size+len(code), 7, 4096)
    return hdr + ph + code


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--xu', default='bin/xu')
    parser.add_argument('--front-only', action='store_true')
    parser.add_argument('--compare-xu', help='compare fixture acceptance with an unchanged compiler')
    parser.add_argument('--backend-only', action='store_true')
    opts = parser.parse_args()
    xu = (ROOT / opts.xu).resolve()
    env = os.environ.copy()
    env.update(XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / 'src'), XUPATH='')
    native_tag = 'windows' if sys.platform == 'win32' else 'macos' if sys.platform == 'darwin' else 'linux'
    with tempfile.TemporaryDirectory(prefix='xu-p1-test-') as temp:
        tmp = Path(temp)
        env['XU_CACHE'] = str(tmp / 'cache')
        comparisons = 0
        baseline = (ROOT / opts.compare_xu).resolve() if opts.compare_xu else None
        def fixture(name, source, error=None, output=None, extra=(), runner=(), diagnostics=()):
            nonlocal comparisons
            src = tmp / (name + '.xu')
            out = tmp / name
            src.write_text('@main\n' + source)
            if baseline:
                run([baseline, 'build', '-O0', *extra, src, '-o', tmp / (name + '.baseline')],
                    env=env, expected=1 if error else 0)
                comparisons += 1
            result = run([xu, 'build', '-O0', *extra, src, '-o', out], env=env, expected=1 if error else 0, contains=error)
            for diagnostic in diagnostics:
                assert diagnostic in result.stderr, (name, diagnostic, result.stderr)
            if error:
                assert not out.exists(), f'{name}: failed build produced executable'
            elif output is not None:
                assert run([*runner, out], env=env).stdout == output, name
            print('PASS', name, flush=True)
            return out
        if not opts.backend_only:
            check_phase_c(fixture)
            # Keep the legacy-spelled corpus below as Phase C compatibility
            # coverage beside check_phase_c's new markers. In particular,
            # rejection inputs and their expected diagnostics stay unchanged.
            # Spec34 safety prerequisite (E21a/F27/H33): temporary loans
            # of a reference's pointee must retain the writable parent.
            loan_fns = ('fn both(s &int, w &mut int) { *w = 2\n println(*s) }\n'
                        'fn reverse(w &mut int, s &int) { *w = 2\n println(*s) }\n'
                        'fn writes(a &mut int, b &mut int) { *a = 2\n *b = 3 }\n'
                        'fn view(s &int) &int { << s }\n'
                        'fn writable(w &mut int) &mut int { << w }\n'
                        'fn read(s &int) int { << *s }\n'
                        'fn write(w &mut int) int { *w = 2\n << 0 }\n'
                        'fn consume(s &int, n int) { println(*s + n) }\n'
                        'fn consume_w(w &mut int, n int) { *w = n }\n')
            for tag, call in (
                ('shared_first', 'both(&*p, p)'),
                ('writable_first', 'reverse(p, &*p)'),
                ('explicit_writable', 'both(&*p, mut &*p)'),
                ('two_writable', 'writes(p, p)'),
                ('two_explicit_writable', 'writes(mut &*p, mut &*p)'),
                ('nested_result', 'both(view(&*p), p)'),
                ('nested_result_reverse', 'reverse(p, view(&*p))'),
                ('nested_write', 'consume(&*p, write(p))'),
                ('nested_write_arithmetic', 'consume(&*p, 1 + write(p))'),
                ('active_writable_result', 'consume_w(writable(p), write(p))'),
            ):
                fixture('spec34_E21a_F27_H33_temporary_' + tag,
                        loan_fns + 'fn check(p &mut int) { ' + call + ' }\n'
                        'fn main() { mut x := 1\n check(mut &x) }',
                        'conflicting temporary call loans',
                        diagnostics=('note: conflicting temporary loan starts here',))
            fixture('spec34_E19_temporary_shared_siblings',
                    'fn reads(a &int, b &int) { println(*a + *b) }\n'
                    'fn check(p &mut int) { reads(&*p, &*p)\n *p = 3 }\n'
                    'fn main() { mut x := 1\n check(mut &x)\n println(x) }', output='2\n3\n')
            fixture('spec34_F27_temporary_distinct_owners', loan_fns +
                    'fn check(p &mut int, q &mut int) { both(&*p, q)\n writes(p, q) }\n'
                    'fn main() { mut x := 1\n mut y := 4\n check(mut &x, mut &y)\n println(x + y) }', output='1\n5\n')
            fixture('spec34_F27_completed_scalar_reads', loan_fns +
                    'fn calc(w &mut int, n int) { *w = n + 1 }\n'
                    'fn check(p &mut int) { calc(p, read(&*p))\n calc(p, *p) }\n'
                    'fn main() { mut x := 1\n check(mut &x)\n println(x) }', output='3\n')
            for tag, call in (('shared_first', 'both(&p.value, p)'),
                              ('writable_first', 'reverse(p, &p.value)')):
                fixture('spec34_H32_temporary_field_' + tag,
                        'struct Item { value int }\n'
                        'fn both(s &int, w &mut Item) { w.value = 2\n println(*s) }\n'
                        'fn reverse(w &mut Item, s &int) { w.value = 2\n println(*s) }\n'
                        'fn check(p &mut Item) { ' + call + ' }\nfn main() {}',
                        'conflicting temporary call loans')
            # Spec34 Phase B: pair the inserted adjustment with explicit &*p.
            read_fn = 'fn read(r &int) int { << *r }\n'
            fixture('spec34_E19_shared_name_copy', read_fn +
                    'fn main() { x := 3\n p := &x\n let q: &int = p\n println(read(p) + read(q)) }', output='6\n')
            fixture('spec34_E20_F26_call_restores_parent', read_fn +
                    'fn check(p &mut int) { println(read(p))\n *p = 2\n println(read(p)) }\n'
                    'fn main() { mut x := 1\n check(mut &x) }', output='1\n2\n')
            fixture('spec34_F26_generic_body_instances', read_fn +
                    'fn relay#T(tag T, p &mut int) int { << read(p) }\n'
                    'fn check(p &mut int) { println(relay(0, p))\n println(relay(true, p))\n println(relay(0, p))\n *p = 4 }\n'
                    'fn main() { mut x := 3\n check(mut &x) }', output='3\n3\n3\n')
            fixture('spec34_F26_generic_concrete_expectation',
                    'fn read#T(tag T, r &int) int { << *r }\n'
                    'fn check(p &mut int) { println(read(0, p))\n println(read(true, p)) }\n'
                    'fn main() { mut x := 3\n check(mut &x) }', output='3\n3\n')
            fixture('spec34_G29_method_parameter',
                    'struct Item { value int }\nfn (i &Item) add(r &int) int { << i.value + *r }\n'
                    'fn check(p &mut Item, q &mut int) { println(p.add(q))\n *q = 4 }\n'
                    'fn main() { mut i := Item{value: 2}\n mut x := 3\n check(mut &i, mut &x) }', output='5\n')
            fixture('spec34_F28_return_parameter_last_use',
                    'fn view(p &mut int) &int { << p }\n'
                    'fn main() { mut x := 1\n p := mut &x\n q := view(p)\n println(*q)\n *p = 2\n println(*p) }', output='1\n2\n')
            for spelling, label in (('p', 'implicit'), ('&*p', 'explicit')):
                base = 'struct Holder { r &int }\n' + read_fn
                for tag, body, expected in (
                    ('typed_let', 'let q: &int = VIEW\n println(*q)\n *p = 2\n println(*p)', '1\n2\n'),
                    ('assign', 'x := 7\n mut q := &x\n q = VIEW\n println(*q)\n *p = 2', '1\n'),
                    ('struct_init', 'h := Holder{r: VIEW}\n println(*h.r)\n *p = 2', '1\n'),
                    ('field_assign', 'x := 7\n mut h := Holder{r: &x}\n h.r = VIEW\n println(*h.r)\n *p = 2', '1\n'),
                    ('array_fixed', 'a := [1]&int{VIEW}\n println(*a[0])\n *p = 2', '1\n'),
                    ('array_assign', 'x := 7\n mut a := [&x]\n a[0] = VIEW\n println(*a[0])\n *p = 2', '1\n'),
                ):
                    fixture('spec34_E20_C14_H32_' + tag + '_' + label,
                            base + 'fn check(p &mut int) { ' + body.replace('VIEW', spelling) + ' }\n'
                            'fn main() { mut x := 1\n check(mut &x) }', output=expected)
                for tag, body in (
                    ('local', 'let q: &int = VIEW\n *p = 2\n println(*q)'),
                    ('move_parent', 'let q: &int = VIEW\n w := p\n println(*q)\n println(*w)'),
                    ('exclusive_parent', 'let q: &int = VIEW\n w := mut &*p\n println(*q)\n println(*w)'),
                    ('descendant', 'let q: &int = VIEW\n h := &*q\n *p = 2\n println(*h)'),
                    ('nested_struct', 'h := Holder{r: VIEW}\n *p = 2\n println(*h.r)'),
                    ('closure', 'let q: &int = VIEW\n f := fn() int { << *q }\n *p = 2\n println(f())'),
                    ('result', 'q := view(VIEW)\n *p = 2\n println(*q)'),
                    ('array', 'a := [1]&int{VIEW}\n *p = 2\n println(*a[0])'),
                ):
                    fixture('spec34_E20_H33_freeze_' + tag + '_' + label,
                            base + 'fn view(r &int) &int { << r }\nfn check(p &mut int) { ' + body.replace('VIEW', spelling) + ' }\nfn main() {}',
                            'frozen reference' if tag == 'exclusive_parent' else 'mutably borrowed')
                for tag, child in (('shared', '&*p'), ('exclusive', 'mut &*p')):
                    fixture('spec34_H33_frozen_' + tag + '_' + label,
                            read_fn + 'fn check(p &mut int) { r := ' + child + '\n println(read(' + spelling + '))\n println(*r) }\nfn main() {}',
                            'frozen reference')
            for tag, call in (
                ('shared_first', 'both(p, p)'),
                ('writable_first', 'reverse(p, p)'),
                ('nested_result', 'both(view(p), p)'),
                ('nested_result_reverse', 'reverse(p, view(p))'),
                ('nested_write', 'consume(p, write(p))'),
            ):
                fixture('spec34_F26_H33_temporary_implicit_' + tag,
                        loan_fns + 'fn check(p &mut int) { ' + call + ' }\nfn main() {}',
                        'conflicting temporary call loans')
            fixture('spec34_E20_temporary_shared_siblings',
                    'fn reads(a &int, b &int) { println(*a + *b) }\n'
                    'fn check(p &mut int) { reads(p, p)\n *p = 3 }\n'
                    'fn main() { mut x := 1\n check(mut &x)\n println(x) }', output='2\n3\n')
            fixture('spec34_F26_completed_scalar_both_orders', read_fn +
                    'fn calc(w &mut int, a int) { *w = a + 1 }\n'
                    'fn reverse(a int, w &mut int) { *w = a + 1 }\n'
                    'fn check(p &mut int) { calc(p, read(p))\n reverse(read(p), p)\n println(*p) }\n'
                    'fn main() { mut x := 1\n check(mut &x) }', output='3\n')
            for receiver_ty, arg_ty in (('&Item', '&mut Item'), ('&mut Item', '&Item')):
                fixture('spec34_G29_temporary_receiver_' + str(len(receiver_ty)),
                        'struct Item { value int }\n'
                        'fn (p ' + receiver_ty + ') alias(q ' + arg_ty + ') { println(p.value) }\n'
                        'fn check(p &mut Item) { p.alias(p) }\nfn main() {}',
                        'conflicting temporary call loans')
            for tag, expr in (('field', 'h.r'), ('index', 'a[0]'), ('call', 'id(p)'), ('borrow', 'mut &x')):
                fixture('spec34_E24_implicit_' + tag,
                        'struct H { r &mut int }\n' + read_fn +
                        'fn id(r &mut int) &mut int { << r }\n'
                        'fn check(p &mut int, h H, a []&mut int) { mut x := 1\n println(read(' + expr + ')) }\nfn main() {}',
                        'implicit shared reborrow requires a local reference name')
            fixture('spec34_E20_H33_implicit_diagnostic',
                    'fn check(p &mut int) { let q: &int = p\n *p = 2\n println(*q) }\nfn main() {}',
                    'mutably borrowed', diagnostics=('implicit shared reborrow inserted for a read-only expectation',
                        'shared reborrow starts here', 'shared reborrow is last used here'))
            fixture('spec34_D18_no_expected_move',
                    'fn check(p &mut int) { q := p\n println(*p)\n println(*q) }\nfn main() {}', 'moved value')
            fixture('spec34_C12_no_recursive_array',
                    'fn read(a []&int) {}\nfn check(a []&mut int) { read(a) }\nfn main() {}', 'type mismatch')
            fixture('spec34_F28_local_escape',
                    'fn bad(unused &int) &int { mut x := 1\n p := mut &x\n << p }\nfn main() {}', 'cannot return a reference to local data')
            fixture('spec34_H33_branch_implicit_parents',
                    'fn bad(flag bool, p &mut int, q &mut int) { let s: &int = p\n mut r := s\n if flag { r = q }\n h := &*r\n *q = 3\n println(*h) }\nfn main() {}', 'mutably borrowed')
            fixture('spec34_H33_loop_implicit_rebind',
                    'fn bad(p &mut int) { x := 1\n mut r := &x\n for i in 0:2 { r = p }\n println(*r) }\nfn main() {}', 'loop back-edge')
            fixture('spec34_E20_struct_and_slice_pointees',
                    'struct Item { value int }\nfn value(p &Item) int { << p.value }\n'
                    'fn first(p &[]int) int { << p[0] }\n'
                    'fn check(p &mut Item, a &mut []int) { println(value(p) + first(a))\n p.value = 4\n a[0] = 5 }\n'
                    'fn main() { mut x := Item{value: 2}\n mut a := [3]\n check(mut &x, mut &a)\n println(x.value + a[0]) }', output='5\n9\n')
            for spelling, label in (('p', 'implicit'), ('&*p', 'explicit')):
                fixture('spec34_H33_nested_cast_write_' + label,
                        loan_fns + 'fn check(p &mut int) { consume(' + spelling + ', int(i32(write(p)))) }\nfn main() {}',
                        'conflicting temporary call loans')
                fixture('spec34_H33_result_union_' + label,
                        'fn choose(a &view int, b &view int, flag bool) &view int { if flag { << a }\n << b }\n'
                        'fn check(p &mut int, q &mut int) { r := choose(' + spelling + ', &*q, true)\n *q = 4\n println(*r) }\nfn main() {}',
                        'mutably borrowed')
            fixture('spec34_H33_field_store_freezes_parent',
                    'struct Holder { r &int }\nfn check(p &mut int) { x := 7\n mut h := Holder{r: &x}\n h.r = p\n *p = 2\n println(*h.r) }\nfn main() {}',
                    'mutably borrowed')
            # Active explicit writable loans block scalar place reads too;
            # a bare synchronous writable argument remains a reservation.
            for tag, first, error in (('active', 'mut &*p', 'mutably borrowed'), ('reserved', 'p', None)):
                fixture('spec34_F27_H32_scalar_place_' + tag,
                        'struct Item { value int }\nfn use(w &mut Item, n int) { w.value = n + 1 }\n'
                        'fn check(p &mut Item) { use(' + first + ', p.value) }\n'
                        'fn main() { mut x := Item{value: 2}\n check(mut &x)\n println(x.value) }',
                        error, output=None if error else '3\n')
            view_methods = ('struct Item { value int }\n'
                            'fn (p &Item) view() &int { << &p.value }\n'
                            'fn (p &Item) read() int { << p.value }\n')
            fixture('spec34_G29_G31_shared_receiver_result', view_methods +
                    'fn check(p &mut Item) { q := p.view()\n println(p.read())\n println(*q)\n p.value = 4 }\n'
                    'fn main() { mut x := Item{value: 3}\n check(mut &x) }', output='3\n3\n')
            fixture('spec34_G29_H33_shared_receiver_result_freezes', view_methods +
                    'fn check(p &mut Item) { q := p.view()\n p.value = 4\n println(*q) }\nfn main() {}', 'mutably borrowed')
            fixture('spec34_G29_generic_receiver',
                    'struct Item#T { value T }\nfn (p &Item#T) read() T { << p.value }\n'
                    'fn check(p &mut Item#int) { println(p.read())\n p.value = 4 }\n'
                    'fn main() { mut x := Item#int{value: 3}\n check(mut &x) }', output='3\n')
            for spelling, label in (('p', 'implicit'), ('&*p', 'explicit')):
                fixture('spec34_H33_fallback_temporary_' + label,
                        loan_fns + 'fn value() int { << 0 }\n'
                        'fn check(p &mut int) { consume(' + spelling + ', value() or (err) { write(p) }) }\nfn main() {}',
                        'conflicting temporary call loans')
            fixture('spec34_H33_fallback_shared_and_statement_end', loan_fns +
                    'fn value() int { << 0 }\n'
                    'fn check(p &mut int, q &mut int) { consume(p, value() or (err) { read(p)\n r := &*q\n println(*r)\n write(q) }) }\n'
                    'fn main() { mut x := 1\n mut y := 2\n check(mut &x, mut &y) }', output='1\n')
            fixture('spec34_F26_function_value_execution', read_fn +
                    'fn check(p &mut int) { f := read\n println(f(p))\n *p = 2 }\n'
                    'fn main() { mut x := 1\n check(mut &x)\n println(x) }', output='1\n2\n')
            fixture('spec34_F26_generic_no_downgrade_inference',
                    'fn read#T(r &T) {}\nfn check(p &mut int) { read(p) }\nfn main() {}', 'type mismatch')
            fixture('spec34_C12_no_recursive_reference',
                    'fn read(r & &int) {}\nfn check(p & &mut int) { read(p) }\nfn main() {}', 'type mismatch')
            fixture('spec34_H32_implicit_unproven_field_store',
                    'struct H { r &int }\nfn bad(h &mut H, p &mut int) { h.r = p }\nfn main() {}',
                    'without a proven lifetime')
            chain = 'fn check(p &mut int) { r0 := mut &*p\n'
            chain += ''.join(f'r{i} := mut &*r{i-1}\n' for i in range(1, 70))
            fixture('spec34_E20_H33_long_implicit_parent_chain', chain +
                    'let q: &int = r69\n *p = 4\n println(*q) }\nfn main() {}', 'mutably borrowed')
            receiver_eval = ('struct Item { value int }\n'
                             'fn (p &Item) plus(n int) int { << p.value + n }\n'
                             'fn (p &mut Item) set(n int) { p.value = n }\n'
                             'fn read(p &Item) int { << p.value }\n'
                             'fn write(p &mut Item) int { p.value = 2\n << 0 }\n')
            fixture('spec34_G29_H33_receiver_nested_writer', receiver_eval +
                    'fn check(p &mut Item) { println(p.plus(write(p))) }\nfn main() {}',
                    'conflicting temporary call loans')
            fixture('spec34_G29_H33_receiver_nested_shared', receiver_eval +
                    'fn check(p &mut Item, q &mut Item) { println(p.plus(read(p)))\n'
                    ' println(p.plus(write(q)))\n p.set(p.value + 1)\n println(p.value) }\n'
                    'fn main() { mut x := Item{value: 3}\n mut y := Item{value: 7}\n check(mut &x, mut &y) }', output='6\n3\n4\n')
            clone_receiver = ('struct Item { name string }\n'
                              'fn (p &Item) show(name string) { println(name) }\n'
                              'fn use(p &mut Item, name string) { println(name) }\n')
            fixture('spec34_G29_receiver_cloned_argument', clone_receiver +
                    'fn check(p &mut Item) { p.show(p.name) }\n'
                    'fn main() { mut x := Item{name: "xu"}\n check(mut &x) }', output='xu\n')
            fixture('spec34_H32_active_writable_clone_reject', clone_receiver +
                    'fn check(p &mut Item) { use(mut &*p, p.name) }\nfn main() {}', 'mutably borrowed')
            # Spec34 H38: rejected marker permutations stay rejected. Check
            # actionable spelling, source attribution, and no output executable.
            for index, (spelling, hint) in enumerate((
                ('&$x := 1', "use '$name :='"),
                ('$&x := 1', "mutable binding declarations use '$x :='"),
                ('r := &$x', "use '$name :='"),
                ('r := $&*p', "explicit reborrow uses '&*r'"),
                ('r := *$&p', "explicit reborrow uses '&*r'"),
                ('println($x)', "use plain 'name'"),
                ('r := &mut x', "writable borrow expressions use 'mut &x'"),
            )):
                fixture('spec34_H38_expr_' + str(index),
                        'fn main() { mut x := 1\n p := mut &x\n ' + spelling + '\n}',
                        hint, diagnostics=(':4:',) if spelling == 'r := &mut x' else (':4:', 'H38:'))
            for index, spelling in enumerate(('&$int', '$int')):
                fixture('spec34_H38_type_' + str(index),
                        'fn read(p ' + spelling + ') {}\nfn main() {}',
                        "writable reference types use '$&T'",
                        diagnostics=(':2:11:', 'H38:'))
            fixture('spec34_E22_shared_upgrade',
                    'fn bad(r &int) { w := mut &*r }\nfn main() {}',
                    'cannot take address of dereference', diagnostics=(
                        'cannot obtain an exclusive writable borrow from a shared reference',
                        'borrow mutably from the owner',))
            for borrow in ('&*h.r', 'mut &*h.r'):
                fixture('spec34_E24_non_ident_' + str(len(borrow)),
                        'struct Holder { r &mut int }\nfn bad(h Holder) { q := ' + borrow + '\n println(*q) }\nfn main() {}',
                        'cannot take address of dereference', diagnostics=(
                            'requires a local reference name', 'this may move it',))
            fixture('spec34_A6_binding_not_pointee',
                    'fn main() { x := 1\n mut r := &x\n *r = 2\n}',
                    'cannot assign through shared reference', diagnostics=(
                        'cannot write through a shared reference', "'mut r' allows rebinding",))
            fixture('spec34_H33_shared_freeze_notes',
                    'fn bad(p &mut int) { r := &*p\n *p = 2\n println(*r)\n}\nfn main() {}',
                    'mutably borrowed', diagnostics=(
                        'note: shared reborrow starts here',
                        ':4:2: note: shared reborrow is last used here',
                        'move the write or exclusive reborrow after the last use',))
            fixture('spec34_E20_F26_plain_name',
                    'fn read(r &int) int { << *r }\nfn check(p &mut int) { println(read(p)) }\nfn main() {}',
                    output=None)
            fixture('spec34_A1_A2_A6_A7_A8_B9_B10_B11_E19_E21a_compat',
                    'fn write(r &mut int) { *r = 3 }\nfn main() { mut x := 1\n r := mut &x\n write(r)\n println(*r)\n s := &*r\n mut q := s\n println(*q)\n y := 4\n q = &y\n println(*q)\n *r = 5\n println(*r)\n}',
                    output='3\n3\n4\n5\n')
            fixture('spec34_H37_tags_interpolation_pub',
                    '$' + native_tag + '\npub fn visible() int { << 3 }\nfn main() { name := "xu"\n println("$name $$ \\$name")\n println(visible())\n println(3 & 1)\n println(true && true)\n}',
                    output='xu $ $name\n3\n1\ntrue\n')
            fixture('spec34_A1_immutable_assignment',
                    'fn main() { x := 1\n x = 2 }',
                    'cannot assign to immutable variable', diagnostics=("mut x := value",))
            fixture('spec34_D17_immutable_owner',
                    'fn main() { x := 1\n r := mut &x\n println(*r) }',
                    'cannot mutably borrow immutable variable', diagnostics=("mut x := value",))
            for target, setup in (('s.value', 'struct Box { value int }\nfn main() { x := Box{value: 1}\n mut s := &x\n'),
                                  ('s[0]', 'fn main() { x := [1]\n mut s := &x\n')):
                fixture('spec34_A6_shared_place_' + str(len(target)),
                        setup + target + ' = 2\n}', 'cannot assign through shared reference',
                        diagnostics=("'mut s' allows rebinding", 'borrow mutably from the owner'))
            fixture('spec34_E22_readonly_argument',
                    'fn write(r &mut int) {}\nfn main() { x := 1\n write(&x) }',
                    'type mismatch: expected &mut int, found &int',
                    diagnostics=('cannot obtain an exclusive writable borrow from a shared reference',
                                 'borrow mutably from the owner'))
            for name, body in (
                ('fnval', 'f := read\n println(f(p))'),
                ('let', 'let s: &int = p'),
                ('assign', 'x := 1\n mut s := &x\n s = p\n println(*s)'),
            ):
                fixture('spec34_E20_' + name,
                        'fn read(r &int) int { << *r }\nfn bad(p &mut int) { ' + body + ' }\nfn main() {}',
                        output=None)
            fixture('spec34_E20_return',
                    'fn bad(p &mut int) &int { << p }\nfn main() {}',
                    output=None)
            fixture('spec34_F25_automatic_borrow',
                    'fn read(r &int) int { << *r }\nfn main() { x := 1\n println(read(x)) }',
                    output='1\n')
            fixture('spec34_H33_frozen_reborrow_notes',
                    'fn bad(p &mut int) { r := &*p\n q := mut &*p\n println(*r)\n println(*q) }\nfn main() {}',
                    'cannot reborrow a frozen reference', diagnostics=(
                        ':2:22: note: shared reborrow starts here',
                        ':4:2: note: shared reborrow is last used here',))
            fixture('spec34_H33_branch_notes',
                    'fn bad(p &mut int, q &mut int, flag bool) { mut r := &*p\n if flag { r = &*q }\n *q = 9\n println(*r) }\nfn main() {}',
                    'mutably borrowed', diagnostics=('note: shared reborrow starts here',
                                                    ':5:2: note: shared reborrow is last used here',))
            for source in ('fn main() { x := ~1 }', 'fn bad(x ~int) {}\nfn main() {}'):
                fixture('spec34_H38_tilde_' + str(len(source)), source,
                        "unexpected character '~'", diagnostics=("'~' stays unused", 'mut &x'))
            fixture('spec34_C_typed_binding', 'fn main() { let $x: int = 1\n x = 2\n println(x) }',
                    output='2\n')
            fixture('spec34_H33_current_function_notes',
                    'fn first() { println(0)\n println(1)\n println(2) }\nfn bad(p &mut int) { r := &*p\n *p = 9\n println(*r) }\nfn main() {}',
                    'mutably borrowed', diagnostics=(
                        ':5:22: note: shared reborrow starts here',
                        ':7:2: note: shared reborrow is last used here',))
            fixture('spec34_H33_aggregate_holder_notes',
                    'struct View { r &int }\nfn bad(p &mut int) { h := View{r: &*p}\n *p = 9\n println(*h.r) }\nfn main() {}',
                    'mutably borrowed', diagnostics=(
                        ':3:22: note: shared reborrow starts here',
                        ':5:2: note: shared reborrow is last used here',))
            fixture('spec34_H38_borrow_binding', 'fn main() { &x := 1 }',
                    'a borrow is not a mutable binding declaration', diagnostics=('mut x :=',))
            fixture('spec34_H38_nested_legacy_borrow',
                    'fn main() { mut x := 1\n r := &mut &x }')
            fixture('undefined_spawn', 'fn main() { xu missing() }', 'undefined function')
            fixture('invalid_send', 'fn main() { x := 1\n x <- 2\n}', 'send requires a channel')
            fixture('call_loan', 'fn identity(x &int) &int { << x }\nfn main() { mut x := 1\n r := identity(&x)\n x = 2\n println(*r)\n}', 'because it is borrowed')
            fixture('branch_loan', 'fn bad(flag bool) { mut xs := [1]\n ys := [2]\n mut r := &xs[0]\n if flag { r = &ys[0] }\n xs.push(3)\n println(*r)\n}\nfn main() { bad(false) }', 'element is borrowed')
            fixture('branch_safe_rebind', 'fn check(flag bool) { mut xs := [1]\n ys := [2]\n zs := [3]\n mut r := &xs[0]\n if flag { r = &ys[0] } else { r = &zs[0] }\n xs.push(4)\n println(*r)\n}\nfn main() { check(true)\n check(false)\n}', output='2\n3\n')
            fixture('branch_sibling_isolation', 'fn check(flag bool) { mut xs := [1]\n zs := [3]\n mut r := &zs[0]\n if flag { r = &xs[0] } else { xs.push(2) }\n println(*r)\n}\nfn main() { check(true)\n check(false)\n}', output='1\n3\n')
            fixture('branch_call_copy_loan', 'fn identity(x &int) &int { << x }\nfn bad(flag bool) { mut xs := [1]\n ys := [2]\n mut r := identity(&xs[0])\n if flag { r = identity(&ys[0]) }\n q := r\n xs.push(3)\n println(*q)\n}\nfn main() { bad(false) }', 'element is borrowed')
            fixture('branch_call_other_loan', 'fn identity(x &int) &int { << x }\nfn bad(flag bool) { xs := [1]\n mut ys := [2]\n mut r := &xs[0]\n if flag { r = identity(&ys[0]) }\n q := &*r\n ys.push(3)\n println(*q)\n}\nfn main() { bad(true) }', 'element is borrowed')
            fixture('branch_nested_aggregate_loan', 'struct Inner { r &int }\nstruct Outer { inner Inner }\nfn bad(flag bool) { mut x := 1\n y := 2\n mut h := Outer{inner: Inner{r: &x}}\n if flag { h = Outer{inner: Inner{r: &y}} }\n z := h\n x = 3\n println(*z.inner.r)\n}\nfn main() { bad(false) }', 'because it is borrowed')
            fixture('branch_closure_loan', 'fn bad(flag bool) { mut x := 1\n y := 2\n mut r := &x\n if flag { r = &y }\n f := fn() int { << *r }\n x = 3\n println(f())\n}\nfn main() { bad(false) }', 'because it is borrowed')
            fixture('branch_return_edge', 'fn check(flag bool) { mut xs := [1]\n ys := [2]\n mut r := &xs[0]\n if flag { println(*r)\n << } else { r = &ys[0] }\n xs.push(3)\n println(*r)\n}\nfn main() { check(false) }', output='2\n')
            fixture('branch_owner_escape', 'fn bad(flag bool) { x := 1\n mut r := &x\n if flag { y := 2\n r = &y }\n println(*r)\n}\nfn main() { bad(true) }', 'does not outlive')
            fixture('loop_rebind_reject', 'fn main() { x := 1\n y := 2\n mut r := &x\n for i in 0:2 { r = &y }\n println(*r)\n}', 'loop back-edge')
            fixture('linear_rebind_kills_loan', 'fn main() { mut xs := [1]\n ys := [2]\n mut r := &xs[0]\n r = &ys[0]\n xs.push(3)\n println(*r)\n}', output='2\n')
            fixture('branch_local_nll', 'fn check(flag bool) { mut x := 1\n r := &x\n if flag { x = 2 } else { println(*r) }\n}\nfn main() { check(true)\n check(false)\n}', output='1\n')
            fixture('match_safe_rebind', 'fn check(flag int) { mut xs := [1]\n ys := [2]\n zs := [3]\n mut r := &xs[0]\n match flag { 0 { r = &ys[0] } else { r = &zs[0] } }\n xs.push(4)\n println(*r)\n}\nfn main() { check(0)\n check(1)\n}', output='2\n3\n')
            fixture('match_missing_edge_loan', 'fn bad(flag int) { mut xs := [1]\n ys := [2]\n mut r := &xs[0]\n match flag { 0 { r = &ys[0] } }\n xs.push(3)\n println(*r)\n}\nfn main() { bad(1) }', 'element is borrowed')
            fixture('select_safe_rebind', 'fn main() { mut xs := [1]\n ys := [2]\n zs := [3]\n mut r := &xs[0]\n ch := chan int{cap: 1}\n ch <- 1\n select { v := <-ch { r = &ys[0] } else { r = &zs[0] } }\n xs.push(4)\n println(*r)\n}', output='2\n')
            fixture('select_empty_default_loan', 'fn main() { mut xs := [1]\n ys := [2]\n mut r := &xs[0]\n ch := chan int{cap: 0}\n select { v := <-ch { r = &ys[0] } else {} }\n xs.push(3)\n println(*r)\n}', 'element is borrowed')
            fixture('branch_reborrow_freezes_all_parents', 'fn bad(flag bool) { mut x := 1\n mut y := 2\n p := mut &x\n q := mut &y\n mut r := &*p\n if flag { r = &*q }\n h := &*r\n *q = 3\n println(*h)\n}\nfn main() { bad(true) }', 'mutably borrowed')
            fixture('loop_tail_branch_loan', 'fn bad(flag bool) { mut xs := [1]\n r := &xs[0]\n for i in 0:2 { if flag { xs.push(2) } else { println(*r) } }\n}\nfn main() { bad(true) }', 'element is borrowed')
            fixture('nested_loop_tail_branch_loan', 'fn bad(flag bool) { for j in 0:2 { mut xs := [1]\n r := &xs[0]\n for i in 0:2 { if flag { xs.push(2) } else { println(*r) } }\n} }\nfn main() { bad(true) }', 'element is borrowed')
            fixture('fallback_rebind_reject', 'fn value() int { << 1 }\nfn main() { x := 1\n y := 2\n mut r := &x\n v := value() or (err) { r = &y }\n println(*r)\n}', 'error fallback without expression-level loan tracking')
            fixture('nested_branch_safe_rebind', 'fn check(a bool, b bool) { mut xs := [1]\n ys := [2]\n zs := [3]\n mut r := &xs[0]\n if a { if b { r = &ys[0] } else { r = &zs[0] } } else { r = &ys[0] }\n xs.push(4)\n println(*r)\n}\nfn main() { check(true, false)\n check(false, true)\n}', output='3\n2\n')
            fixture('nested_loan', 'struct Inner { r &int }\nstruct Outer { inner Inner }\nfn main() { mut x := 1\n h := Outer{inner: Inner{r: &x}}\n x = 2\n println(*h.inner.r)\n}', 'because it is borrowed')
            fixture('nested_assign_loan', 'struct Inner { r &int }\nstruct Outer { inner Inner }\nfn main() { mut x := 1\n y := 2\n mut h := Outer{inner: Inner{r: &y}}\n h.inner = Inner{r: &x}\n x = 3\n println(*h.inner.r)\n}', 'because it is borrowed')
            fixture('field_escape', 'struct Holder { r &int }\nfn bad(h &mut Holder) { x := 1\n h.r = &x\n}\nfn main() { y := 2\n mut h := Holder{r: &y}\n bad(mut &h)\n println(*h.r)\n}', 'without a proven lifetime')
            fixture('closure_loan', 'fn main() { mut x := 1\n r := &x\n f := fn() int { << *r }\n x = 2\n println(f())\n}', 'because it is borrowed')
            fixture('param_reborrow', 'fn bad(p &mut int) { r := &*p\n *p = 3\n println(*r)\n}\nfn main() { mut x := 1\n bad(mut &x)\n}', 'mutably borrowed')
            chain = 'fn bad(p &mut int) {\n r0 := mut &*p\n' + ''.join(f' r{i} := mut &*r{i-1}\n' for i in range(1, 12)) + ' *p = 2\n println(*r11)\n}\nfn main() { mut x := 1\n bad(mut &x)\n}'
            fixture('long_reborrow', chain, 'mutably borrowed')
            fixture('late_reborrow', 'fn main() { mut xs := [1]\n r := &xs[0]\n xs.push(2)\n q := &*r\n println(*q)\n}', 'element is borrowed')
            fixture('shared_and_last_use', 'struct Item { value int }\nfn shared(p &Item) int { r := &p.value\n << p.value + *r\n}\nfn main() { mut x := 1\n r := &x\n println(*r)\n x = 2\n a := Item{value: 3}\n println(shared(&a))\n}', output='1\n6\n')
            chart = '''struct Point { series int, id int, opacity f64 }
struct Chart { data []Point, selected int }
fn (c &Chart) datum_visible(i int) bool { << c.data[i].opacity > 0.001 }
fn (c &mut Chart) select_point(series int, id int) {
    for i in 0:c.data.len { p := &c.data[i]
        if p.series == series && p.id == id && p.opacity > 0.0 && c.datum_visible(i) {
            c.selected = i
            <<
        }
    }
}
fn main() {
    mut c := Chart{data: [Point{series: 1, id: 2, opacity: 0.0}, Point{series: 1, id: 3, opacity: 1.0}], selected: -1}
    c.select_point(1, 3)
    println(c.selected)
}'''
            fixture('chart_shared_receiver_condition', chart, output='1\n')
            receiver = '''struct Item { value int }
fn (p &Item) read() int { << p.value }
fn (p &mut Item) change() { p.value = 2 }
'''
            fixture('shared_receiver_live_child', receiver + 'fn check(p &mut Item) { r := &p.value\n println(p.read())\n println(*r)\n}\nfn main() { mut v := Item{value: 1}\n check(mut &v)\n}', output='1\n1\n')
            fixture('shared_receiver_local_parent', receiver + 'fn main() { mut v := Item{value: 1}\n p := mut &v\n r := &p.value\n println(p.read())\n println(*r)\n}', output='1\n1\n')
            fixture('shared_receiver_exclusive_child', receiver + 'fn check(p &mut Item) { r := mut &p.value\n println(p.read())\n println(*r)\n}\nfn main() { mut v := Item{value: 1}\n check(mut &v)\n}', 'mutably borrowed')
            fixture('shared_receiver_exclusive_local_child', receiver + 'fn main() { mut v := Item{value: 1}\n p := mut &v\n r := mut &p.value\n println(p.read())\n println(*r)\n}', 'mutably borrowed')
            fixture('mutable_receiver_shared_child', receiver + 'fn check(p &mut Item) { r := &p.value\n p.change()\n println(*r)\n}\nfn main() { mut v := Item{value: 1}\n check(mut &v)\n}', 'mutably borrowed')
            fixture('write_after_shared_receiver', receiver + 'fn check(p &mut Item) { r := &p.value\n println(p.read())\n p.value = 2\n println(*r)\n}\nfn main() { mut v := Item{value: 1}\n check(mut &v)\n}', 'mutably borrowed')
            fixture('exclusive_reborrow_after_shared_receiver', receiver + 'fn check(p &mut Item) { r := &p.value\n println(p.read())\n q := mut &*p\n println(*r)\n println(q.read())\n}\nfn main() { mut v := Item{value: 1}\n check(mut &v)\n}', 'frozen reference')
            reader = 'struct Item { value int }\nfn (p &Item) read() int { << p.value }\nfn (p &mut Item) write() { p.value = 9 }\n'
            fixture('shared_receiver_reborrow', reader + 'fn check(p &mut Item) { r := &p.value\n println(p.read() + *r)\n p.write()\n}\nfn main() { mut x := Item{value: 3}\n check(mut &x)\n println(x.value)\n}', output='6\n9\n')
            fixture('shared_receiver_held', reader + 'struct Holder { r &int }\nfn check(p &mut Item) { h := Holder{r: &p.value}\n println(p.read() + *h.r)\n}\nfn main() { mut x := Item{value: 3}\n check(mut &x)\n}', output='6\n')
            fixture('shared_local_receiver', reader + 'fn main() { mut x := Item{value: 3}\n p := mut &x\n r := &p.value\n println(p.read() + *r)\n}', output='6\n')
            fixture('exclusive_local_receiver', reader + 'fn main() { mut x := Item{value: 3}\n p := mut &x\n r := mut &p.value\n println(p.read())\n println(*r)\n}', 'mutably borrowed')
            fixture('exclusive_receiver_reborrow', reader + 'fn check(p &mut Item) { r := mut &p.value\n println(p.read())\n println(*r)\n}\nfn main() { mut x := Item{value: 3}\n check(mut &x)\n}', 'mutably borrowed')
            fixture('exclusive_receiver_held', reader + 'struct Holder { r &mut int }\nfn check(p &mut Item) { h := Holder{r: mut &p.value}\n println(p.read())\n println(*h.r)\n}\nfn main() { mut x := Item{value: 3}\n check(mut &x)\n}', 'mutably borrowed')
            fixture('shared_receiver_mutation', reader + 'fn check(p &mut Item) { r := &p.value\n p.write()\n println(*r)\n}\nfn main() { mut x := Item{value: 3}\n check(mut &x)\n}', 'mutably borrowed')
            fixture('shared_place_read', 'struct Data { values []int, name string }\nfn check(p &mut Data) { r := &p.values[0]\n println(p.name + "!")\n println(p.values[0] + *r)\n}\nfn main() { mut x := Data{values: [3], name: "chart"}\n check(mut &x)\n}', output='chart!\n6\n')
            fixture('shared_place_write', reader + 'fn check(p &mut Item) { r := &p.value\n p.value = 9\n println(*r)\n}\nfn main() { mut x := Item{value: 3}\n check(mut &x)\n}', 'mutably borrowed')
            fixture('shared_index_write', 'fn check(p &mut []int) { r := &p[0]\n p[0] = 9\n println(*r)\n}\nfn main() { mut xs := [3]\n check(mut &xs)\n}', 'mutably borrowed')
            fixture('shared_field_push', 'struct Data { values []int }\nfn check(p &mut Data) { r := &p.values[0]\n p.values.push(9)\n println(*r)\n}\nfn main() { mut x := Data{values: [3]}\n check(mut &x)\n}', 'element is borrowed')
            fixture('shared_place_move', 'struct Item { name string }\nfn check(p &mut Item) { r := &p.name\n s := p.name\n println(*r)\n println(s)\n}\nfn main() { mut x := Item{name: "chart"}\n check(mut &x)\n}', 'mutably borrowed')
            fixture('exclusive_place_read', reader + 'fn check(p &mut Item) { r := mut &p.value\n println(p.value)\n println(*r)\n}\nfn main() { mut x := Item{value: 3}\n check(mut &x)\n}', 'mutably borrowed')
            fixture('receiver_index_loan', reader + 'fn check(p &mut []Item, i &mut int) { r := mut &*i\n println(p[*i].read())\n println(*r)\n}\nfn main() { mut xs := [Item{value: 3}]\n mut i := 0\n check(mut &xs, mut &i)\n}', 'mutably borrowed')
            fixture('mutable_field', 'struct Inner { x int }\nstruct Outer { inner Inner, y int }\nfn (p &mut Inner) set(v int) { p.x = v }\nfn change(p &mut Outer) { r := mut &p.inner\n r.set(2)\n p.y = 3\n}\nfn main() { mut v := Outer{inner: Inner{x: 1}, y: 0}\n change(mut &v)\n println(v.y)\n}', output='3\n')
        if opts.front_only:
            print('compiler P1 frontend: PASS', flush=True)
            if baseline:
                print(f'compiler P1 acceptance comparison: PASS={comparisons} FAIL=0', flush=True)
            return
        check_phase_c_backends(fixture)
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
        result = run([executable, 'loong_long'], env=env)
        code = bytes(int(s) for s in result.stdout.splitlines())
        image = tmp / 'loong_long'
        image.write_bytes(elf(code, True, loong=True))
        image.chmod(0o755)
        run(['qemu-loongarch64', image], env=env)
        print('PASS loong_long_branches', flush=True)
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
        for mode, emulator, thumb in [('chan_rv32', 'qemu-riscv32', False), ('chan_thumb', 'qemu-arm', True)]:
            result = run([executable, mode], env=env)
            code = bytes(int(s) for s in result.stdout.splitlines())
            artifact = tmp / mode
            artifact.write_bytes(elf(code, False, thumb))
            artifact.chmod(0o755)
            run([emulator, artifact], env=env)
            print('PASS freestanding_channel_runtime', mode, flush=True)
        result = run([executable, 'cmp_loong'], env=env)
        code = bytes(int(s) for s in result.stdout.splitlines())
        artifact = tmp / 'cmp_loong'
        artifact.write_bytes(elf(code, True, loong=True))
        artifact.chmod(0o755)
        run(['qemu-loongarch64', artifact], env=env)
        print('PASS loong_conditional_execution', flush=True)
        for mode in ('loong_far_eq', 'loong_far_zero'):
            result = run([executable, mode, 5000000], env=env)
            code = bytes(int(s) for s in result.stdout.splitlines())
            inverse, branch = struct.unpack('<II', code)
            assert inverse >> 26 == 23 and (inverse >> 10) & 65535 == 2
            assert branch >> 26 == 20
            delta = (((branch >> 10) & 65535) | ((branch & 1023) << 16)) * 4
            assert delta + 4 == 5000000
            print('PASS loong_far_conditional', mode, flush=True)
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
        # These scalar cases were blanket ABI rejections before round 2.
        # Keep both inputs as acceptance regressions for the supported ABI.
        fixture('thumb_channel_pair', channel, output='4294967297\n', extra=('--target', 'linux-arm32'), runner=('qemu-arm',))
        fixture('thumb_spawn_scalar', 'fn worker(a int, b int, c int) {}\nfn main() { xu worker(1, 2, 3) }', output='', extra=('--target', 'linux-arm32'), runner=('qemu-arm',))
        fixture('thumb_atomic64_reject', atomic, 'Thumb int64 atomics require', extra=('--target', 'linux-arm32'))
        fixture('thumb_spawn_aggregate_reject', 'enum Message { Text(string) }\nfn worker(value Message) {}\nfn main() { xu worker(Message.Text("payload")) }', 'Thumb spawn aggregate pair ABI', extra=('--target', 'linux-arm32'))
        fixture('thumb_channel_aggregate_reject', 'struct Payload { left int, right int }\nfn main() { ch := chan Payload{cap: 1}\n ch <- Payload{left: 4294967297, right: -4294967299}\n}', 'Thumb channel aggregate pair ABI', extra=('--target', 'linux-arm32'))
        thumb_spawn = """fn worker(out chan int, a bool, b int, c bool, d int, e int) {
    if a && c { out <- b + d + e }
}
fn main() { out := chan int{cap: 0}
    xu worker(out, true, 4294967297, true, 8589934595, -4294967297)
    println(<-out)
}"""
        thumb_fifo = """fn worker(ch chan int, done chan int) {
    ch <- 4294967297
    ch <- -4294967299
    done <- 1
}
fn main() {
    ch := chan int{cap: 1}
    done := chan int{cap: 0}
    xu worker(ch, done)
    println(<-ch)
    println(<-ch)
    token := <-done
    close(ch)
    println(<-ch)
}"""
        thumb_select = """fn main() { ch := chan int{cap: 1}
    select { ch <- -4294967299 { println(1) } else { println(0) } }
    select { ch <- 99 { println(0) } else { println(2) } }
    select { v := <-ch { println(v) } else { println(0) } }
    select { v := <-ch { println(0) } else { println(3) } }
    close(ch)
    select { v := <-ch { println(v) } else { println(99) } }
}"""
        poison = 'fn poison(n int) int { if n < 0 { << poison(-n) }\n'
        poison += ''.join(f' v{i} := n + {i}\n' for i in range(64))
        poison += ' << ' + ' + '.join(f'v{i}' for i in range(64)) + '\n}\n'
        thumb_status = poison + """fn attempt(ch chan int) int {
    select { ch <- 1 { << 1 } else { << 2 } }
}
fn attempt_recv(ch chan int) int {
    select { v := <-ch { << 1 } else { << 2 } }
}
fn main() { ch := chan int{cap: 0}
    mut total := 0
    for i in 0:20 {
        if poison(4294967297 + i) < 0 { println(99) }
        total += attempt(ch)
        if poison(4294967297 + i) < 0 { println(99) }
        total += attempt_recv(ch)
    }
    println(total)
}"""
        for opt in ('-O0', '-O2'):
            fixture('thumb_spawn_pair' + opt, thumb_spawn, output='8589934595\n', extra=(opt, '--target', 'linux-arm32'), runner=('qemu-arm',))
            fixture('thumb_channel_fifo' + opt, thumb_fifo, output='4294967297\n-4294967299\n0\n', extra=(opt, '--target', 'linux-arm32'), runner=('qemu-arm',))
            fixture('thumb_channel_select' + opt, thumb_select, output='1\n2\n-4294967299\n3\n0\n', extra=(opt, '--target', 'linux-arm32'), runner=('qemu-arm',))
            fixture('thumb_select_status_pair' + opt, thumb_status, output='80\n', extra=(opt, '--target', 'linux-arm32'), runner=('qemu-arm',))
            for capacity in (4294967297, 613566757):
                out = fixture('thumb_capacity_bound_' + str(capacity) + opt, f'fn main() {{ ch := chan int{{cap: {capacity}}}\n close(ch)\n}}', extra=(opt, '--target', 'linux-arm32'))
                run(['qemu-arm', out], env=env, expected=1)
                print('PASS thumb_capacity_bound_execution', capacity, opt, flush=True)
        fixture('thumb_channel_contention', 'fn worker(ch chan int) { for i in 0:100 { ch <- 4294967297 } }\nfn main() { ch := chan int{cap: 0}\n for i in 0:8 { xu worker(ch) }\n mut sum := 0\n for i in 0:800 { sum += <-ch }\n println(sum)\n}', output='3435973837600\n', extra=('-O2', '--target', 'linux-arm32'), runner=('qemu-arm',))
        stack_overflow = """fn recurse(n int) int {
    if n == 0 { << 0 }
    << n + recurse(n - 1)
}
fn worker(out chan int) { out <- recurse(100000) }
fn main() { out := chan int{cap: 0}
    xu worker(out)
    println(<-out)
}"""
        stack_sret = """struct Pair { a int, b int }
fn make_pair(x int) Pair {
    if x < 0 { << make_pair(-x) }
    << Pair{a: x, b: x + 1}
}
fn worker(out chan int) { value := make_pair(41)
    out <- value.a + value.b
}
fn main() { out := chan int{cap: 0}
    xu worker(out)
    println(<-out)
}"""
        for target, emulator in (('linux-arm64', 'qemu-aarch64'), ('linux-loongarch64', 'qemu-loongarch64'), ('linux-riscv64', 'qemu-riscv64')):
            for opt in ('-O0', '-O2'):
                out = fixture('stack_guard_' + target + opt, stack_overflow, extra=(opt, '--target', target))
                run([emulator, out], env=env, expected=1, contains='coroutine stack overflow')
                print('PASS stack_overflow_execution', target, opt, flush=True)
                fixture('stack_args_' + target + opt, spawn, output='spawn enum payload\n', extra=(opt, '--target', target), runner=(emulator,))
                fixture('stack_sret_' + target + opt, stack_sret, output='83\n', extra=(opt, '--target', target), runner=(emulator,))
        for target in ('riscv32imac-none', 'thumbv7em-none'):
            fixture('freestanding_reject_' + target, channel.replace('4294967297', '1'), 'require a suspendable scheduler', extra=('--target', target))
        nonblocking = """fn main() { ch := chan int{cap: 2}
    select { ch <- 17 {} else {} }
    select { v := <-ch { println(v) } else {} }
    close(ch)
}"""
        for target in ('riscv32imac-none', 'thumbv7em-none'):
            fixture('freestanding_nonblocking_' + target, nonblocking, extra=('--target', target))
            fixture('freestanding_spawn_reject_' + target, 'fn worker() {}\nfn main() { xu worker() }', 'require a suspendable scheduler', extra=('--target', target))
        # Spec34 B adjustments must retain the pointer ABI through optimization
        # and across native backends, for scalar, struct and slice pointees.
        for spelling, label in (('p', 'implicit'), ('&*p', 'explicit')):
            phase_b = ('struct Item { value int }\n'
                       'fn view(s &int) &int { << s }\n'
                       'fn read(s &int) int { << *s }\n'
                       'fn sum(a &[]int, i &Item) int { << a[0] + i.value }\n'
                       'fn check(p &mut int, a &mut []int, i &mut Item) int { q := view(VIEWP)\n'
                       ' total := *q + sum(VIEWA, VIEWI)\n *p = total\n << read(VIEWP) }\n'
                       'fn main() { mut x := 1\n mut a := [2]\n mut i := Item{value: 3}\n'
                       ' println(check(mut &x, mut &a, mut &i))\n println(x) }')
            phase_b = phase_b.replace('VIEWP', spelling).replace('VIEWA', spelling.replace('p', 'a')).replace('VIEWI', spelling.replace('p', 'i'))
            for target, runner in (('host', ()), ('linux-arm64', ('qemu-aarch64',)),
                                   ('linux-arm32', ('qemu-arm',)), ('linux-loongarch64', ('qemu-loongarch64',)),
                                   ('linux-riscv64', ('qemu-riscv64',))):
                for opt in ('-O0', '-O2'):
                    extra = (opt,) if target == 'host' else (opt, '--target', target)
                    fixture('spec34_E20_F26_C14_backend_' + label + '_' + target + opt,
                            phase_b, output='6\n6\n', extra=extra, runner=runner)
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
        if baseline:
            print(f'compiler P1 acceptance comparison: PASS={comparisons} FAIL=0', flush=True)
    print('compiler P1: PASS', flush=True)


if __name__ == '__main__':
    main()
