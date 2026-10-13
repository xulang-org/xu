#!/usr/bin/env python3
"""Patch PE32+ SizeOfStackReserve/Commit so WoA does not skip the 4KB guard page."""
import struct
import sys

RESERVE = 16 * 1024 * 1024
COMMIT = 4 * 1024 * 1024


def patch(path: str) -> None:
    data = bytearray(open(path, "rb").read())
    if data[:2] != b"MZ":
        raise SystemExit(f"not a PE: {path}")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew : e_lfanew + 4] != b"PE\0\0":
        raise SystemExit(f"no PE signature: {path}")
    opt = e_lfanew + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic != 0x20B:
        raise SystemExit(f"not PE32+: {path} magic={magic:#x}")
    old_r = struct.unpack_from("<Q", data, opt + 72)[0]
    old_c = struct.unpack_from("<Q", data, opt + 80)[0]
    struct.pack_into("<Q", data, opt + 72, RESERVE)
    struct.pack_into("<Q", data, opt + 80, COMMIT)
    open(path, "wb").write(data)
    print(f"patched {path}: stack {old_r}/{old_c} -> {RESERVE}/{COMMIT}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: pe_patch_stack.py FILE.exe...")
    for p in sys.argv[1:]:
        patch(p)
