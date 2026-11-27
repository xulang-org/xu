#!/usr/bin/env python3
"""Verify Windows PE32+ .pdata/.xdata unwind tables (static + live OS stack walk)
and x64 constant-multiply / MADD-MSUB codegen parity on windows-arm64 and windows-x64.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys

from test_windows_pe_wx import check_wx_headers, parse_pe
from test_windows_workers import WindowsTemporaryDirectory


UNWIND_PROBE_SOURCE = r'''@main
#ffi
#os

extern "C" link "kernel32" {
    fn c_get_module_handle_a(name c_ptr) u64 = "GetModuleHandleA"
    fn c_capture_bt(skip u32, max_frames u32, buf c_ptr, hash_out c_ptr) u16 = "RtlCaptureStackBackTrace"
    fn c_lookup_fn_entry(pc u64, img_base_out c_ptr, history c_ptr) u64 = "RtlLookupFunctionEntry"
}

extern "C" {
    fn c_qsort(base c_ptr, count c_size, size c_size, cmp fn(c_ptr, c_ptr) c_int) = "qsort"
}

fn leaf_helper(a int, b int) int {
    << a * 3 + b * 5 + 7
}

fn frame_capture(out_buf c_ptr) int {
    unsafe {
        << int(c_capture_bt(u32(0), u32(32), out_buf, ffi.null()))
    }
}

fn frame_compact(n int) int {
    unsafe {
        buf := ffi.calloc(256)
        cnt := frame_capture(buf)
        $line := "BT:" + str(cnt) + ":"
        for i in 0:cnt {
            addr := int(ffi.read_u64(buf, i * 8))
            if i > 0 { line.push_str(",") }
            line.push_str(str(addr))
        }
        println(line)
        ffi.free(buf)
        << cnt + leaf_helper(n, 1)
    }
}

fn frame_shrinkwrap(n int) int {
    if n <= 0 {
        << 7
    }
    if n == 1 {
        << frame_compact(n - 1) + 1
    }
    << frame_shrinkwrap(n - 1) + n
}

fn frame_callee_saves(n int, fx f64, fy f64) int {
    a0 := n + 1
    a1 := n + 2
    a2 := n + 3
    a3 := n + 4
    a4 := n + 5
    a5 := n + 6
    a6 := n + 7
    a7 := n + 8
    f0 := fx + 1.25
    f1 := fy * 2.5
    f2 := fx - fy + 3.0
    f3 := f0 + f1
    r1 := frame_shrinkwrap(n)
    r2 := leaf_helper(a0 + a1 + a2 + a3, a4 + a5 + a6 + a7)
    s := int(f0 + f1 + f2 + f3)
    << r1 + r2 + s
}

fn frame_big(n int) int {
    $big := [700]int{''' + ", ".join(["0"] * 700) + r'''}
    for i in 0:700 {
        big[i] = n + i
    }
    $k := (n * 17) % 700
    if k < 0 { k = 0 - k }
    r := frame_callee_saves(n, 2.5, 1.5)
    << r + big[k] + big[699 - k]
}

fn qsort_cmp(pa c_ptr, pb c_ptr) c_int {
    unsafe {
        bt := ffi.calloc(256)
        cnt := int(c_capture_bt(u32(0), u32(32), bt, ffi.null()))
        $line := "CB_BT:" + str(cnt) + ":"
        for i in 0:cnt {
            addr := int(ffi.read_u64(bt, i * 8))
            if i > 0 { line.push_str(",") }
            line.push_str(str(addr))
        }
        println(line)
        ffi.free(bt)
        va := int(ffi.read_i64(pa, 0))
        vb := int(ffi.read_i64(pb, 0))
        if va < vb { << i32(-1) }
        if va > vb { << i32(1) }
        << i32(0)
    }
}

fn parse_dec(s &string) int {
    $v := 0
    for i in 0:s.len {
        c := s[i]
        if c >= 48 && c <= 57 {
            v = v * 10 + (c - 48)
        }
    }
    << v
}

fn main() int {
    av := os.argv()
    if av.len < 2 {
        eprintln("usage: probe <rva1> ...")
        << 2
    }
    $base := 0
    unsafe {
        base = int(c_get_module_handle_a(ffi.null()))
    }
    if base == 0 {
        eprintln("GetModuleHandleA returned 0")
        << 3
    }
    println("BASE:" + str(base))

    // Verify RtlLookupFunctionEntry on every passed RVA inside .text.
    unsafe {
        img_out := ffi.calloc(16)
        for i in 1:av.len {
            rva := parse_dec(&av[i])
            ffi.write_u64(img_out, 0, u64(0))
            rf := c_lookup_fn_entry(u64(base + rva), img_out, ffi.null())
            ib := int(ffi.read_u64(img_out, 0))
            if rf == u64(0) || ib != base {
                eprintln("RtlLookupFunctionEntry failed at index " + str(i) + " rva=" + str(rva) + " rf=" + str(int(rf)) + " ib=" + str(ib))
                ffi.free(img_out)
                << 4
            }
        }
        ffi.free(img_out)
    }
    println("LOOKUP_OK:" + str(av.len - 1))

    res := frame_big(3)
    println("CHAIN_RES:" + str(res))

    // Bidirectional C callback unwind across ucrtbase/msvcrt qsort.
    unsafe {
        arr := ffi.calloc(32)
        ffi.write_i64(arr, 0, 40)
        ffi.write_i64(arr, 8, 10)
        ffi.write_i64(arr, 16, 30)
        ffi.write_i64(arr, 24, 20)
        c_qsort(arr, u64(4), u64(8), qsort_cmp)
        s0 := int(ffi.read_i64(arr, 0))
        s1 := int(ffi.read_i64(arr, 8))
        s2 := int(ffi.read_i64(arr, 16))
        s3 := int(ffi.read_i64(arr, 24))
        ffi.free(arr)
        if s0 != 10 || s1 != 20 || s2 != 30 || s3 != 40 {
            eprintln("qsort failed: " + str(s0) + "," + str(s1) + "," + str(s2) + "," + str(s3))
            << 5
        }
    }
    println("QSORT_OK")
    << 0
}
'''

MUL_PARITY_SOURCE = r'''@main

fn mul_suite(x int, y int) int {
    $acc := 0
    // Cover x64_emit_mul_const special cases + imul imm8 + imul imm32 + madd/msub idioms
    $v0 := x * 0
    $v1 := x * 1
    $vm1 := x * -1
    $v2 := x * 2
    $v3 := x * 3
    $v5 := x * 5
    $v6 := x * 6
    $v7 := x * 7
    $v9 := x * 9
    $v10 := x * 10
    $v12 := x * 12
    $v15 := x * 15
    $v18 := x * 18
    $v20 := x * 20
    $v24 := x * 24
    $v25 := x * 25
    $v27 := x * 27
    $v36 := x * 36
    $v40 := x * 40
    $v45 := x * 45
    $v48 := x * 48
    $v72 := x * 72
    $v81 := x * 81
    $v100 := x * 100
    $v127 := x * 127
    $vm128 := x * -128
    $v128 := x * 128
    $vm129 := x * -129
    $v1000 := x * 1000
    $vm100k := x * -100000
    $vmax := x * 2147483647
    $vmin := x * -2147483648
    acc = v0 + v1 + vm1 + v2 + v3 + v5 + v6 + v7 + v9 + v10 + v12 + v15
    acc = acc + v18 + v20 + v24 + v25 + v27 + v36 + v40 + v45 + v48 + v72 + v81
    acc = acc + v100 + v127 + vm128 + v128 + vm129 + v1000 + vm100k + vmax + vmin
    // Self-aliasing forms
    $z := x + y
    z = z * 3
    z = z * 5
    z = z * 6
    z = z * 15
    z = z * 27
    z = z * 45
    z = z * 72
    z = z * -1
    z = z * 13
    // MADD / MSUB shaped expressions
    madd1 := x * y + acc
    msub1 := madd1 - x * 17
    << msub1 + z
}

fn main() int {
    $h := 0
    inputs := [0, 1, -1, 7, -19, 12345, -98765]
    for i in 0:inputs.len {
        for j in 0:inputs.len {
            r := mul_suite(inputs[i], inputs[j])
            h = h * 31 + r
            if i == j {
                println("M:" + str(i) + ":" + str(r))
            }
        }
    }
    println("HASH:" + str(h))
    << 0
}
'''


def audit_pe_unwind(path: Path, target: str) -> dict:
    raw = path.read_bytes()
    pe = parse_pe(path)
    t_rva, r_rva, d_rva, p_rva = check_wx_headers(pe, expect_rsrc=False)
    secs = pe["sections"]
    text_s, rdata_s, _, pdata_s = secs[0], secs[1], secs[2], secs[3]
    text_end = text_s["vaddr"] + max(text_s["vsize"], text_s["rsize"])
    rdata_end = rdata_s["vaddr"] + max(rdata_s["vsize"], rdata_s["rsize"])

    def rva_to_off(rva: int, size: int) -> int:
        for s in secs:
            if s["vaddr"] <= rva and rva + size <= s["vaddr"] + max(s["vsize"], s["rsize"]):
                return s["rptr"] + (rva - s["vaddr"])
        raise AssertionError(f"RVA {hex(rva)}+{size} outside sections in {path}")

    p_off = pdata_s["rptr"]
    p_len = pdata_s["vsize"]
    prev_end = -1
    if target == "windows-x64":
        assert p_len % 12 == 0 and p_len > 0, (path, p_len)
        count = p_len // 12
        for i in range(count):
            beg, end, unw = struct.unpack_from("<III", raw, p_off + i * 12)
            assert text_s["vaddr"] <= beg < end <= text_end, (path, i, hex(beg), hex(end))
            assert beg >= prev_end, f"Unsorted/overlapping .pdata at {i}: {hex(beg)} < {hex(prev_end)}"
            prev_end = end
            assert rdata_s["vaddr"] <= unw and unw + 4 <= rdata_end, (path, i, hex(unw))
            xoff = rva_to_off(unw, 4)
            ver_flags, prolog_sz, codes_cnt, frame_reg = raw[xoff:xoff + 4]
            assert (ver_flags & 7) == 1, (path, i, ver_flags)
            assert (ver_flags >> 3) == 0, (path, i, ver_flags)
            total_x = 4 + ((codes_cnt + 1) // 2) * 4
            assert unw + total_x <= rdata_end, (path, i, hex(unw), total_x)
    else:
        assert p_len % 8 == 0 and p_len > 0, (path, p_len)
        count = p_len // 8
        for i in range(count):
            beg, unw = struct.unpack_from("<II", raw, p_off + i * 8)
            assert (beg & 3) == 0, (path, i, hex(beg))
            flag = unw & 3
            assert flag == 0, f"Unexpected packed flag {flag} at {i}"
            assert rdata_s["vaddr"] <= unw and unw + 8 <= rdata_end, (path, i, hex(unw))
            xoff = rva_to_off(unw, 8)
            hdr = struct.unpack_from("<I", raw, xoff)[0]
            fn_len = (hdr & 0x3FFFF) * 4
            vers = (hdr >> 18) & 3
            xbit = (hdr >> 20) & 1
            ebit = (hdr >> 21) & 1
            ep_cnt = (hdr >> 22) & 0x1F
            cw = (hdr >> 27) & 0x1F
            words_hdr = 1
            if ep_cnt == 0 and cw == 0:
                hdr1 = struct.unpack_from("<I", raw, xoff + 4)[0]
                ep_cnt = hdr1 & 0xFFFF
                cw = (hdr1 >> 16) & 0xFF
                words_hdr = 2
            assert vers == 0 and xbit == 0 and cw >= 1, (path, i, vers, xbit, cw)
            total_x = 4 * (words_hdr + (0 if ebit else ep_cnt) + cw)
            assert unw + total_x <= rdata_end, (path, i, hex(unw), total_x)
            end = beg + fn_len
            assert text_s["vaddr"] <= beg < end <= text_end, (path, i, hex(beg), hex(end))
            assert beg >= prev_end, f"Unsorted/overlapping .pdata at {i}: {hex(beg)} < {hex(prev_end)}"
            prev_end = end

    return {"count": count, "text_rva": t_rva, "text_end": text_end}


def load_symmap(sym_path: Path) -> list[tuple[int, str]]:
    items = []
    for line in sym_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            off = int(parts[0])
            if off >= 0:
                items.append((off, parts[1]))
    items.sort()
    return items


def find_fn_range(items: list[tuple[int, str]], text_rva: int, text_end: int, exact_or_suffix: str) -> tuple[int, int]:
    for i, (off, name) in enumerate(items):
        if name == exact_or_suffix or name.endswith("_" + exact_or_suffix):
            beg = text_rva + off
            nxt = (text_rva + items[i + 1][0]) if (i + 1 < len(items)) else text_end
            # Clamp in case stubs sit beyond symmap entries
            return beg, max(beg + 4, nxt)
    raise KeyError(f"Symbol {exact_or_suffix} not found in symmap: {[n for _, n in items[:20]]}")


def verify_backtrace_chain(
    addrs: list[int],
    base: int,
    text_rva: int,
    text_end: int,
    ranges: dict[str, tuple[int, int]],
    expected_names: list[str],
    label: str,
) -> None:
    rvas = [a - base for a in addrs]
    pos = 0
    for nm in expected_names:
        beg, end = ranges[nm]
        found = -1
        for k in range(pos, len(rvas)):
            if beg <= rvas[k] < end:
                found = k
                break
        assert found >= 0, (
            f"{label}: frame '{nm}' ([{hex(beg)}, {hex(end)})) missing from captured stack "
            f"after idx {pos}: {[hex(r) for r in rvas]}"
        )
        pos = found + 1

    # Also verify stack walk escaped Xu code into OS frames (BaseThreadInitThunk / RtlUserThreadStart).
    has_os_frame = any(rva < text_rva or rva >= text_end for rva in rvas[pos:])
    assert has_os_frame, f"{label}: unwind did not reach OS frame past __xu_start: {[hex(r) for r in rvas]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("requires a Windows host")

    compiler = args.compiler.resolve()
    host_arch = os.environ.get("PROCESSOR_ARCHITECTURE", "")
    # Static audit of the compiler binary itself
    comp_target = "windows-x64" if "64" in host_arch and "ARM" not in host_arch.upper() else "windows-arm64"
    comp_pe = parse_pe(compiler)
    comp_target = "windows-x64" if comp_pe["machine"] == 0x8664 else "windows-arm64"
    comp_info = audit_pe_unwind(compiler, comp_target)
    print(f"  [PASS] compiler ({comp_target}) .pdata audit: {comp_info['count']} entries valid")

    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, XU_ROOT=str(root), XU_STDLIB_ROOT=str(root / "src"), XUPATH="")

    with WindowsTemporaryDirectory(prefix="xu-pe-unwind-", ignore_cleanup_errors=True) as td:
        work = Path(td)
        probe_src = work / "unwind_probe.xu"
        probe_src.write_text(UNWIND_PROBE_SOURCE, encoding="utf-8", newline="\n")
        mul_src = work / "mul_parity.xu"
        mul_src.write_text(MUL_PARITY_SOURCE, encoding="utf-8", newline="\n")

        # Part 1: Live PE unwind tests on all 4 combinations
        wanted = [
            "__xu_start",
            "_xu_main",
            "frame_big",
            "frame_callee_saves",
            "frame_shrinkwrap",
            "frame_compact",
            "frame_capture",
            "leaf_helper",
            "qsort_cmp",
        ]
        for target in ("windows-arm64", "windows-x64"):
            for mode, flags in (("default", ()), ("no-opt", ("--no-opt",))):
                exe = work / f"unwind-{target}-{mode}.exe"
                sym_path = work / f"unwind-{target}-{mode}.sym"
                build_env = dict(env, XU_SYMMAP=str(sym_path))
                subprocess.run(
                    [str(compiler), "build", str(probe_src), "--target", target, *flags, "-o", str(exe)],
                    cwd=root,
                    env=build_env,
                    check=True,
                    timeout=120,
                )
                info = audit_pe_unwind(exe, target)
                items = load_symmap(sym_path)
                ranges = {nm: find_fn_range(items, info["text_rva"], info["text_end"], nm) for nm in wanted}
                # Check start of each function + 4 bytes into leaf_helper/frame_big if inside text
                lookup_rvas = [str(ranges[nm][0]) for nm in wanted]

                res = subprocess.run(
                    [str(exe), *lookup_rvas],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert res.returncode == 0, (target, mode, res.returncode, res.stdout, res.stderr)
                lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
                base_line = next(l for l in lines if l.startswith("BASE:"))
                base = int(base_line.split(":", 1)[1])
                assert f"LOOKUP_OK:{len(wanted)}" in lines, (target, mode, lines)
                assert "QSORT_OK" in lines, (target, mode, lines)

                bt_line = next(l for l in lines if l.startswith("BT:"))
                _, _, raw_addrs = bt_line.split(":", 2)
                bt_addrs = [int(x) for x in raw_addrs.split(",") if x]
                verify_backtrace_chain(
                    bt_addrs,
                    base,
                    info["text_rva"],
                    info["text_end"],
                    ranges,
                    ["frame_capture", "frame_compact", "frame_shrinkwrap", "frame_callee_saves", "frame_big", "_xu_main", "__xu_start"],
                    f"{target}/{mode} direct-bt",
                )

                cb_line = next(l for l in lines if l.startswith("CB_BT:"))
                _, _, raw_cb = cb_line.split(":", 2)
                cb_addrs = [int(x) for x in raw_cb.split(",") if x]
                verify_backtrace_chain(
                    cb_addrs,
                    base,
                    info["text_rva"],
                    info["text_end"],
                    ranges,
                    ["qsort_cmp", "_xu_main", "__xu_start"],
                    f"{target}/{mode} qsort-cb-bt",
                )
                print(
                    f"  [PASS] {target} {mode}: {info['count']} .pdata entries, "
                    f"RtlLookupFunctionEntry({len(wanted)}/{len(wanted)}), "
                    f"RtlCaptureStackBackTrace({len(bt_addrs)} frames direct + {len(cb_addrs)} frames via qsort C callback)"
                )

        # Part 2: x64 mul-const / MADD-MSUB parity across arm64, x64 default, x64 no-opt
        ref_out = None
        for target, mode, flags in (
            ("windows-arm64", "default", ()),
            ("windows-x64", "default", ()),
            ("windows-x64", "no-opt", ("--no-opt",)),
        ):
            mexe = work / f"mul-{target}-{mode}.exe"
            subprocess.run(
                [str(compiler), "build", str(mul_src), "--target", target, *flags, "-o", str(mexe)],
                cwd=root,
                env=env,
                check=True,
                timeout=120,
            )
            res = subprocess.run([str(mexe)], env=env, capture_output=True, text=True, timeout=30)
            assert res.returncode == 0 and not res.stderr, (target, mode, res.returncode, res.stderr)
            if ref_out is None:
                ref_out = res.stdout
            else:
                assert res.stdout == ref_out, f"mul parity mismatch for {target} {mode}:\ngot:\n{res.stdout}\nexpected:\n{ref_out}"
        print("  [PASS] mul-const & MADD/MSUB parity bit-exact across windows-arm64, windows-x64 default, windows-x64 --no-opt")

    print("Windows PE unwind & x64 parity verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
