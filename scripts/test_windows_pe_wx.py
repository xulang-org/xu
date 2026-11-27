#!/usr/bin/env python3
"""Verify Windows PE32+ W^X section separation (.text RX, .rdata R, .data RW),
static headers, manifest embedding, C FFI, and live VirtualQuery protections
on both windows-arm64 and windows-x64 targets.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from pack_release_bundle import validate_binary
from test_windows_workers import WindowsTemporaryDirectory
from windows_setup_manifest import embed_invoker_manifest


SOURCE = r'''@main
#ffi
#os

extern "C" link "kernel32" {
    fn c_get_current_process_id() u32 = "GetCurrentProcessId"
    fn c_get_module_handle_a(name c_ptr) u64 = "GetModuleHandleA"
    fn c_virtual_query(addr u64, buf c_ptr, length c_size) c_size = "VirtualQuery"
}

extern "C" {
    fn c_abs(v c_int) c_int = "abs"
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

fn query_prot(base int, rva int) int {
    unsafe {
        buf := ffi.calloc(64)
        n := int(c_virtual_query(u64(base + rva), buf, u64(48)))
        $prot := -1
        if n >= 40 {
            prot = int(ffi.read_u32(buf, 36))
        }
        ffi.free(buf)
        << prot
    }
}

fn main() int {
    av := os.argv()
    if av.len != 4 {
        eprintln("usage: probe text_rva rdata_rva data_rva")
        << 2
    }
    text_rva := parse_dec(&av[1])
    rdata_rva := parse_dec(&av[2])
    data_rva := parse_dec(&av[3])

    $pid := 0
    $abs_val := 0
    $base := 0
    unsafe {
        pid = int(c_get_current_process_id())
        abs_val = int(c_abs(i32(-42)))
        base = int(c_get_module_handle_a(ffi.null()))
    }
    if pid <= 0 || abs_val != 42 || base == 0 {
        eprintln("FFI/base check failed")
        << 3
    }

    p_text := query_prot(base, text_rva)
    p_rdata := query_prot(base, rdata_rva)
    p_data := query_prot(base, data_rva)
    // PAGE_EXECUTE_READ=0x20, PAGE_READONLY=0x02, PAGE_READWRITE=0x04
    if p_text != 0x20 || p_rdata != 0x02 || p_data != 0x04 {
        eprintln("unexpected protections: text=" + str(p_text) + " rdata=" + str(p_rdata) + " data=" + str(p_data))
        << 4
    }
    println("WX_OK:" + str(p_text) + ":" + str(p_rdata) + ":" + str(p_data) + ":" + str(abs_val))
    << 0
}
'''


def parse_pe(path: Path) -> dict:
    raw = path.read_bytes()
    assert raw[:2] == b"MZ", f"bad DOS magic in {path}"
    e_lfanew = struct.unpack_from("<I", raw, 0x3C)[0]
    assert raw[e_lfanew:e_lfanew + 4] == b"PE\0\0", f"bad PE signature in {path}"
    machine, nsec, _, _, _, opt_size, _ = struct.unpack_from("<HHIIIHH", raw, e_lfanew + 4)
    opt = e_lfanew + 24
    magic = struct.unpack_from("<H", raw, opt)[0]
    assert magic == 0x20B, f"not PE32+: {hex(magic)}"
    entry_rva = struct.unpack_from("<I", raw, opt + 16)[0]
    dll_chars = struct.unpack_from("<H", raw, opt + 70)[0]
    ndirs = struct.unpack_from("<I", raw, opt + 108)[0]
    assert ndirs >= 13
    imp_rva, imp_sz = struct.unpack_from("<II", raw, opt + 112 + 1 * 8)
    iat_rva, iat_sz = struct.unpack_from("<II", raw, opt + 112 + 12 * 8)
    tbl = opt + opt_size
    sections = []
    for i in range(nsec):
        at = tbl + i * 40
        name = raw[at:at + 8].split(b"\0", 1)[0].decode("ascii", "replace")
        vsize, vaddr, rsize, rptr, _, _, _, _, chars = struct.unpack_from("<IIIIIIHHI", raw, at + 8)
        sections.append({
            "name": name,
            "vsize": vsize,
            "vaddr": vaddr,
            "rsize": rsize,
            "rptr": rptr,
            "chars": chars,
        })
    return {
        "machine": machine,
        "entry_rva": entry_rva,
        "dll_chars": dll_chars,
        "imp": (imp_rva, imp_sz),
        "iat": (iat_rva, iat_sz),
        "sections": sections,
    }


def check_wx_headers(pe: dict, expect_rsrc: bool = False) -> tuple[int, int, int]:
    secs = pe["sections"]
    expected_names = [".text", ".rdata", ".data"] + ([".rsrc"] if expect_rsrc else [])
    assert [s["name"] for s in secs] == expected_names, (expected_names, [s["name"] for s in secs])

    for s in secs:
        chars = s["chars"]
        # IMAGE_SCN_MEM_EXECUTE (0x20000000) and IMAGE_SCN_MEM_WRITE (0x80000000) must never both be set.
        assert (chars & 0xA0000000) != 0xA0000000, f"W^X violation in {s['name']}: {hex(chars)}"

    text, rdata, data = secs[0], secs[1], secs[2]
    assert text["chars"] == 0x60000020, hex(text["chars"])
    assert rdata["chars"] == 0x40000040, hex(rdata["chars"])
    assert data["chars"] == 0xC0000040, hex(data["chars"])
    if expect_rsrc:
        assert secs[3]["chars"] == 0x40000040, hex(secs[3]["chars"])

    # NX_COMPAT (0x100) | DYNAMIC_BASE (0x40) | HIGH_ENTROPY_VA (0x20)
    assert (pe["dll_chars"] & 0x0160) == 0x0160, hex(pe["dll_chars"])

    entry = pe["entry_rva"]
    assert text["vaddr"] <= entry < text["vaddr"] + text["vsize"], (hex(entry), text)

    imp_rva, imp_sz = pe["imp"]
    iat_rva, iat_sz = pe["iat"]
    assert imp_sz > 0 and iat_sz > 0, (pe["imp"], pe["iat"])
    assert rdata["vaddr"] <= imp_rva and imp_rva + imp_sz <= rdata["vaddr"] + rdata["vsize"], (pe["imp"], rdata)
    assert rdata["vaddr"] <= iat_rva and iat_rva + iat_sz <= rdata["vaddr"] + rdata["vsize"], (pe["iat"], rdata)
    return text["vaddr"], rdata["vaddr"], data["vaddr"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("requires a Windows host")

    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, XU_ROOT=str(root), XU_STDLIB_ROOT=str(root / "src"), XUPATH="")

    with WindowsTemporaryDirectory(prefix="xu-pe-wx-") as td:
        work = Path(td)
        src = work / "wx_probe.xu"
        src.write_text(SOURCE, encoding="utf-8", newline="\n")

        for target in ("windows-arm64", "windows-x64"):
            for mode, flags in (("default", ()), ("no-opt", ("--no-opt",))):
                exe = work / f"probe-{target}-{mode}.exe"
                subprocess.run(
                    [str(compiler), "build", str(src), "--target", target, *flags, "-o", str(exe)],
                    cwd=root,
                    env=env,
                    check=True,
                    timeout=120,
                )
                validate_binary(exe, target)
                pe = parse_pe(exe)
                t_rva, r_rva, d_rva = check_wx_headers(pe, expect_rsrc=False)

                run_env = dict(env, XU_DEBUG_FREE="1")
                res = subprocess.run(
                    [str(exe), str(t_rva), str(r_rva), str(d_rva)],
                    env=run_env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert res.returncode == 0, (target, mode, res.returncode, res.stdout, res.stderr)
                assert res.stdout.strip() == "WX_OK:32:2:4:42", (target, mode, res.stdout, res.stderr)

                # Verify manifest embedding preserves W^X and adds .rsrc cleanly.
                mexe = work / f"probe-{target}-{mode}-rsrc.exe"
                shutil.copy2(exe, mexe)
                embed_invoker_manifest(mexe)
                pe_m = parse_pe(mexe)
                mt_rva, mr_rva, md_rva = check_wx_headers(pe_m, expect_rsrc=True)
                res_m = subprocess.run(
                    [str(mexe), str(mt_rva), str(mr_rva), str(md_rva)],
                    env=run_env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert res_m.returncode == 0 and res_m.stdout.strip() == "WX_OK:32:2:4:42", (target, mode, res_m)
                print(f"  [PASS] {target} {mode}: W^X static + live VirtualQuery + FFI + manifest")

    print("Windows PE W^X verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
