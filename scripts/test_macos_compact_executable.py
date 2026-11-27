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
#time

extern "C" fn c_getpid() c_int = "getpid"

fn main() int {
    $pid := 0
    unsafe { pid = int(c_getpid()) }
    if time.now() <= 0 || pid <= 0 { << 1 }
    println("clock and C imports ready")
    << 0
}
"""


def check_macho(binary, page, keep_symbols, dwarf=False):
    image = binary.read_bytes()
    magic, _, _, _, ncmds = struct.unpack_from("<IIIII", image)
    assert magic == 0xFEEDFACF
    segments = {}
    has_code_sig = False
    offset = 32
    for _ in range(ncmds):
        command, size = struct.unpack_from("<II", image, offset)
        if command == 0x19:  # LC_SEGMENT_64
            name, vm, vmsize, file, filesize = struct.unpack_from("<16sQQQQ", image, offset + 8)
            segments[name.rstrip(b"\0")] = (vm, vmsize, file, filesize)
            if name.rstrip(b"\0") == b"__DATA" and not dwarf:
                section = offset + 72
                assert image[section:section + 16].rstrip(b"\0") == b"__bss"
                assert struct.unpack_from("<I", image, section + 48)[0] == 0
                assert struct.unpack_from("<I", image, section + 64)[0] == 1  # S_ZEROFILL
        if command == 0xB:  # LC_DYSYMTAB
            nlocals, _, _, undef, nundef = struct.unpack_from("<IIIII", image, offset + 12)
            assert (nlocals > 0) == keep_symbols and nundef == 4 and undef == nlocals
        if command == 0x1D:  # LC_CODE_SIGNATURE
            has_code_sig = True
        offset += size
    assert has_code_sig == (not dwarf)
    data_vm, data_space, data_off, data_size = segments[b"__DATA"]
    link_vm, _, link_off, _ = segments[b"__LINKEDIT"]
    _, _, text_off, text_size = segments[b"__TEXT"]
    assert data_space == page and link_vm == data_vm + page
    assert text_off + text_size == data_off
    assert data_size == (page if dwarf else 0)
    assert link_off == data_off + data_size
    assert (b"__DWARF" in segments) == dwarf


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
                if platform.system() == "Darwin" and native == arch and mode in ("release", "symbols", "no-opt"):
                    subprocess.run(["codesign", "--verify", "--strict", output], check=True)
                    result = subprocess.check_output([output], text=True, timeout=15)
                    assert result == "clock and C imports ready\n", result
    print("Mach-O release, symbol retention, and debug layouts passed")


if __name__ == "__main__":
    main()
