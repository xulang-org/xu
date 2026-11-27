#!/usr/bin/env python3
"""Check standalone Mach-O layout, local symbols, and native loader bindings."""

import argparse
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile


SOURCE = """@main
#ffi
#time

extern "C" {
    fn c_getpid() c_int = "getpid"
    fn c_qsort(base c_ptr, nmemb c_size, size c_size, cmp fn(c_ptr, c_ptr) c_int) = "qsort"
}

fn cmp_i32(a c_ptr, b c_ptr) c_int {
    $va := i32(0)
    $vb := i32(0)
    unsafe {
        va = ffi.read_i32(a, 0)
        vb = ffi.read_i32(b, 0)
    }
    if va < vb { << i32(-1) }
    if va > vb { << i32(1) }
    << i32(0)
}

fn main() int {
    $pid := 0
    $s0 := 0
    $s3 := 0
    unsafe {
        pid = int(c_getpid())
        buf := ffi.malloc(16)
        if ffi.is_null(buf) { << 2 }
        ffi.write_i32(buf, 0, i32(30))
        ffi.write_i32(buf, 4, i32(10))
        ffi.write_i32(buf, 8, i32(40))
        ffi.write_i32(buf, 12, i32(20))
        c_qsort(buf, u64(4), u64(4), cmp_i32)
        s0 = int(ffi.read_i32(buf, 0))
        s3 = int(ffi.read_i32(buf, 12))
        ffi.free(buf)
    }
    if time.now() <= 0 || pid <= 0 || s0 != 10 || s3 != 40 { << 1 }
    println("clock and C imports ready")
    << 0
}
"""


def check_macho(binary, page, keep_symbols, dwarf=False):
    image = binary.read_bytes()
    magic, _, _, _, ncmds, _, hdr_flags = struct.unpack_from("<IIIIIII", image)
    assert magic == 0xFEEDFACF
    assert hdr_flags == 0x01200084, hex(hdr_flags)  # MH_DYLDLINK | MH_TWOLEVEL | MH_PIE | MH_NO_HEAP_EXECUTION
    segments = {}
    uuid_bytes = None
    build_ver = None
    code_sig = None
    chained_fixups = None
    exports_trie = None
    has_legacy_dyld_info = False
    offset = 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", image, offset)
        if command == 0x19:  # LC_SEGMENT_64
            name, vm, vmsize, file, filesize, maxprot, initprot, nsects, flags = struct.unpack_from(
                "<16sQQQQIIII", image, offset + 8
            )
            seg_name = name.rstrip(b"\0")
            segments[seg_name] = (vm, vmsize, file, filesize, maxprot, initprot, nsects, flags)
            if seg_name == b"__DATA_CONST":
                assert flags == 0x10, hex(flags)  # SG_READ_ONLY
                section = offset + 72
                assert image[section:section + 16].rstrip(b"\0") == b"__got"
                assert struct.unpack_from("<I", image, section + 48)[0] == file
                assert struct.unpack_from("<I", image, section + 64)[0] == 0  # regular file-backed slots
            if seg_name == b"__DATA":
                assert flags == 0, hex(flags)
                section = offset + 72
                if not dwarf:
                    assert image[section:section + 16].rstrip(b"\0") == b"__bss"
                    assert struct.unpack_from("<I", image, section + 48)[0] == 0
                    assert struct.unpack_from("<I", image, section + 64)[0] == 1  # S_ZEROFILL
                else:
                    assert image[section:section + 16].rstrip(b"\0") == b"__data"
        if command == 0xB:  # LC_DYSYMTAB
            nlocals, _, _, undef, nundef = struct.unpack_from("<IIIII", image, offset + 12)
            assert (nlocals > 0) == keep_symbols and nundef == 4 and undef == nlocals
        if command == 0x80000022:  # LC_DYLD_INFO_ONLY (legacy)
            has_legacy_dyld_info = True
        if command == 0x80000034:  # LC_DYLD_CHAINED_FIXUPS
            chained_fixups = struct.unpack_from("<II", image, offset + 8)
        if command == 0x80000033:  # LC_DYLD_EXPORTS_TRIE
            exports_trie = struct.unpack_from("<II", image, offset + 8)
        if command == 0x1B:  # LC_UUID
            uuid_bytes = image[offset + 8:offset + 24]
        if command == 0x32:  # LC_BUILD_VERSION
            build_ver = struct.unpack_from("<IIII", image, offset + 8)
        if command == 0x1D:  # LC_CODE_SIGNATURE
            code_sig = struct.unpack_from("<II", image, offset + 8)
        offset += size

    assert not has_legacy_dyld_info, "expected LC_DYLD_CHAINED_FIXUPS instead of legacy LC_DYLD_INFO_ONLY"
    assert chained_fixups is not None and chained_fixups[1] > 0, "missing LC_DYLD_CHAINED_FIXUPS"
    assert exports_trie is not None and exports_trie[1] > 0, "missing LC_DYLD_EXPORTS_TRIE"
    assert uuid_bytes is not None and any(uuid_bytes), "missing or zero LC_UUID"
    assert (uuid_bytes[6] & 0xF0) == 0x50 and (uuid_bytes[8] & 0xC0) == 0x80, uuid_bytes.hex()
    assert build_ver == (1, 0x000C0000, 0x000E0000, 0), build_ver
    assert code_sig is not None, "missing LC_CODE_SIGNATURE"
    assert code_sig[0] + code_sig[1] == len(image), (code_sig, len(image))

    _, _, text_off, text_size, text_max, text_init, _, _ = segments[b"__TEXT"]
    assert text_max == 5 and text_init == 5
    dc_vm, dc_space, dc_off, dc_size, dc_max, dc_init, _, _ = segments[b"__DATA_CONST"]
    assert dc_max == 3 and dc_init == 3 and dc_space == page and dc_size == page
    data_vm, data_space, data_off, data_size, data_max, data_init, _, _ = segments[b"__DATA"]
    assert data_max == 3 and data_init == 3 and data_space == page
    link_vm, _, link_off, link_size, link_max, link_init, _, _ = segments[b"__LINKEDIT"]
    assert link_max == 1 and link_init == 1
    assert link_off + link_size == len(image)

    assert text_off + text_size == dc_off
    assert data_vm == dc_vm + page
    assert data_off == dc_off + dc_size
    assert data_size == (page if dwarf else 0)
    assert (b"__DWARF" in segments) == dwarf
    if dwarf:
        dw_vm, dw_space, dw_off, dw_size, dw_max, dw_init, dw_nsects, _ = segments[b"__DWARF"]
        assert dw_max == 0 and dw_init == 0 and dw_nsects == 4
        assert dw_vm == data_vm + page and link_vm == dw_vm + dw_space
        assert dw_off == data_off + data_size
        assert link_off == dw_off + dw_size
    else:
        assert link_vm == data_vm + page
        assert link_off == data_off


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiler", type=Path)
    compiler = parser.parse_args().compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        src = work / "main.xu"
        src.write_text(SOURCE)
        for arch, page in (("arm64", 16384), ("x64", 4096)):
            for mode, flags in (("release", []), ("symbols", []), ("no-opt", ["--no-opt"]), ("debug", ["-g"])):
                output = work / f"probe-{arch}-{mode}"
                env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                           XU_KEEP_SYMBOLS=str(int(mode == "symbols")), XU_SYMMAP=str(work / "symbols"))
                subprocess.run([compiler, "build", src, "--target", f"macos-{arch}", *flags, "-o", output],
                               env=env, check=True)
                assert " _xu_main\n" in (work / "symbols").read_text()
                check_macho(output, page, mode != "release", dwarf=mode == "debug")
                native = "x64" if platform.machine() == "x86_64" else platform.machine()
                if platform.system() == "Darwin" and native == arch:
                    subprocess.run(["codesign", "--verify", "--strict", output], check=True)
                    dyld_out = subprocess.check_output(["dyld_info", "-fixups", "-exports", output], text=True)
                    assert "__mh_execute_header" in dyld_out and "_clock_gettime" in dyld_out and "_dlopen" in dyld_out, dyld_out
                    result = subprocess.check_output([output], text=True, timeout=15)
                    assert result == "clock and C imports ready\n", result
            # Verify deterministic LC_UUID + chained fixups + ad-hoc code signature across rebuilds.
            output_b = work / f"probe-{arch}-release-b"
            env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                       XU_KEEP_SYMBOLS="0")
            subprocess.run([compiler, "build", src, "--target", f"macos-{arch}", "-o", output_b],
                           env=env, check=True)
            assert (work / f"probe-{arch}-release").read_bytes() == output_b.read_bytes()
    print("Mach-O hardened layout (__DATA_CONST, chained fixups, exports trie, LC_UUID, LC_BUILD_VERSION, debug codesign) passed")


if __name__ == "__main__":
    main()
