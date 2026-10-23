#!/usr/bin/env python3
"""Prove that an ARM32 executable contains no Thumb SVC instruction."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

PT_LOAD = 1
PF_X = 1
SHF_EXECINSTR = 4


def _ranges_from_sections(data: bytes) -> list[tuple[int, int]]:
    if len(data) < 52 or data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        return []
    shoff = struct.unpack_from("<I", data, 32)[0]
    shentsize = struct.unpack_from("<H", data, 46)[0]
    shnum = struct.unpack_from("<H", data, 48)[0]
    if not shoff or shentsize < 40 or shnum == 0 or shoff + shentsize * shnum > len(data):
        return []
    out = []
    for i in range(shnum):
        off = shoff + i * shentsize
        flags = struct.unpack_from("<I", data, off + 8)[0]
        section_off = struct.unpack_from("<I", data, off + 16)[0]
        section_size = struct.unpack_from("<I", data, off + 20)[0]
        if flags & SHF_EXECINSTR and section_size and section_off + section_size <= len(data):
            out.append((section_off, section_off + section_size))
    return out


def _ranges_from_loads(data: bytes) -> list[tuple[int, int]]:
    if len(data) < 52 or data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        return [(0, len(data))]
    phoff = struct.unpack_from("<I", data, 28)[0]
    phentsize = struct.unpack_from("<H", data, 42)[0]
    phnum = struct.unpack_from("<H", data, 44)[0]
    if phentsize < 32 or phoff + phentsize * phnum > len(data):
        return []
    out = []
    for i in range(phnum):
        off = phoff + i * phentsize
        typ, file_off, _, _, file_size = struct.unpack_from("<IIIII", data, off)
        flags = struct.unpack_from("<I", data, off + 24)[0]
        if typ == PT_LOAD and flags & PF_X and file_size and file_off + file_size <= len(data):
            out.append((file_off, file_off + file_size))
    return out


def svc_offsets(data: bytes) -> list[int]:
    ranges = _ranges_from_sections(data) or _ranges_from_loads(data)
    hits = []
    for start, end in ranges:
        # Thumb instructions are halfword aligned. SVC is 0xDFxx in little endian.
        for off in range(start + (start & 1), end - 1, 2):
            if data[off + 1] == 0xDF:
                hits.append(off)
    return hits


def check_file(path: str | Path) -> tuple[bool, str]:
    file_path = Path(path)
    data = file_path.read_bytes()
    hits = svc_offsets(data)
    if hits:
        return False, f"{file_path}: Thumb SVC instruction(s) at file offset(s): " + ", ".join(hex(x) for x in hits[:16])
    return True, f"{file_path}: no executable SVC instructions"


def main(argv: list[str] | None = None) -> int:
    paths = [Path(x) for x in (argv if argv is not None else sys.argv[1:])]
    if not paths:
        print("usage: prove_no_syscalls.py ELF...", file=sys.stderr)
        return 2
    status = 0
    for path in paths:
        ok, message = check_file(path)
        print(("PASS " if ok else "FAIL ") + message)
        status |= 0 if ok else 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
