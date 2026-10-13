#!/usr/bin/env python3
"""Convert Xu XUOBJ → macOS MH_OBJECT for linking with Swift UI host.

Supports macos-arm64 (arch=1) and macos-x64 (arch=2).
Host symbols xu_ui_host_run / xu_ui_mem_try_* stay undefined so pack links
strong defs from libxu_ui_host.a.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

MH_MAGIC_64 = 0xFEEDFACF
MH_OBJECT = 0x1
CPU_TYPE_ARM64 = 0x0100000C
CPU_SUBTYPE_ARM64_ALL = 0
CPU_TYPE_X86_64 = 0x01000007
CPU_SUBTYPE_X86_64_ALL = 3
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
LC_BUILD_VERSION = 0x32
N_UNDF = 0x0
N_SECT = 0xE
N_EXT = 0x01
# arm64
ARM64_RELOC_UNSIGNED = 0
ARM64_RELOC_BRANCH26 = 2
ARM64_RELOC_PAGE21 = 3
ARM64_RELOC_PAGEOFF12 = 4
ARM64_RELOC_BRANCH19 = 15
# x86_64
X86_64_RELOC_UNSIGNED = 0
X86_64_RELOC_SIGNED = 1
X86_64_RELOC_BRANCH = 2
FK_REL32 = 0
FK_RIP32 = 1
FK_B, FK_BL, FK_CBZ, FK_CBNZ, FK_ADRP_ADD = 0, 1, 2, 3, 4
# Provided by Swift/C host at final link — never keep Xu's weak stub.
HOST_SYMS = frozenset(
    {
        "_xu_ui_host_run",
        "xu_ui_host_run",
        # Weak stubs in XUOBJ must stay undefined so pack links strong xu_ui_mem from host.a
        "xu_ui_mem_try_write",
        "xu_ui_mem_try_read_len",
        "xu_ui_mem_try_read_copy",
        "_xu_ui_mem_try_write",
        "_xu_ui_mem_try_read_len",
        "_xu_ui_mem_try_read_copy",
    }
)


def align(n: int, a: int) -> int:
    return (n + a - 1) & ~(a - 1)


def decode_xuobj(b: bytes) -> dict:
    assert b[:5] == b"XUOBJ"
    o = 8
    _os, arch = b[o], b[o + 1]
    o += 4

    def getstr() -> str:
        nonlocal o
        n = struct.unpack_from("<H", b, o)[0]
        o += 2
        s = b[o : o + n].decode()
        o += n
        return s

    getstr()  # module
    nexp = struct.unpack_from("<I", b, o)[0]
    o += 4
    for _ in range(nexp):
        getstr()
        getstr()
        np = b[o + 1]
        o += 2 + np
    nlab = struct.unpack_from("<I", b, o)[0]
    o += 4
    labs = []
    for _ in range(nlab):
        flags = b[o]
        offv = struct.unpack_from("<I", b, o + 1)[0]
        o += 5
        labs.append((getstr(), offv, flags == 1))
    nrel = struct.unpack_from("<I", b, o)[0]
    o += 4
    rels = []
    for _ in range(nrel):
        kind, _rd = b[o], b[o + 1]
        roff = struct.unpack_from("<I", b, o + 2)[0]
        o += 6
        rels.append((kind, roff, getstr()))
    clen = struct.unpack_from("<I", b, o)[0]
    o += 4
    code = bytes(b[o : o + clen])
    o += clen
    dlen = struct.unpack_from("<I", b, o)[0]
    o += 4
    data = bytes(b[o : o + dlen])
    return {"arch": arch, "labs": labs, "rels": rels, "code": code, "data": data}


def pack_reloc(addr: int, symnum: int, pcrel: int, length: int, extern: int, rtype: int) -> bytes:
    word = (
        (symnum & 0xFFFFFF)
        | ((pcrel & 1) << 24)
        | ((length & 3) << 25)
        | ((extern & 1) << 27)
        | ((rtype & 0xF) << 28)
    )
    return struct.pack("<iI", addr, word)


def iat_target(name: str) -> str:
    if name == "_iat__NSGetEnviron":
        return "__NSGetEnviron"
    rest = name[len("_iat_") :]
    return rest if rest.startswith("_") else "_" + rest


def patch32(buf: bytearray, off: int, word: int) -> None:
    struct.pack_into("<I", buf, off, word)


def apply_local_branch_arm64(code: bytearray, kind: int, roff: int, target_off: int) -> None:
    """Pre-resolve PC-relative branches within __text (same section addr=0)."""
    cur = roff
    delta = (target_off - cur) // 4
    if kind in (FK_B, FK_BL):
        imm26 = delta & 0x3FFFFFF
        opcode = 0x94000000 if kind == FK_BL else 0x14000000
        patch32(code, roff, opcode | imm26)
    elif kind in (FK_CBZ, FK_CBNZ):
        imm19 = delta & 0x7FFFF
        rt = code[roff] & 31
        opcode = 0xB4000000 if kind == FK_CBZ else 0xB5000000
        patch32(code, roff, opcode | (imm19 << 5) | rt)
    else:
        raise AssertionError(kind)


def convert(xuobj_path: Path, out_path: Path) -> None:
    obj = decode_xuobj(xuobj_path.read_bytes())
    arch = obj["arch"]
    if arch not in (1, 2):
        raise SystemExit(f"unsupported arch={arch} (need arm64=1 or x64=2)")
    is_x64 = arch == 2
    code = bytearray(obj["code"])
    data = bytearray(obj["data"])
    labs = [(n, off, is_data) for n, off, is_data in obj["labs"]]

    # IAT pointer slots must be 8-byte aligned.
    # Pad *before the first IAT* only — do not shift earlier data (e.g. _rt_heap_mu
    # must stay 8-byte aligned for PTHREAD_MUTEX_INITIALIZER).
    iat_offs = [off for n, off, d in labs if d and n.startswith("_iat_")]
    if iat_offs:
        min_iat = min(iat_offs)
        pad = (8 - (min_iat % 8)) % 8
        if pad:
            data = bytearray(data[:min_iat]) + bytearray(b"\0" * pad) + bytearray(data[min_iat:])
            labs = [
                (n, off + pad if (is_data and off >= min_iat) else off, is_data)
                for n, off, is_data in labs
            ]

    local = {n: (off, is_data) for n, off, is_data in labs}

    # Pre-resolve local branches / relative calls in __text; keep cross-section
    # and extern refs as Mach-O relocs. Never bind Xu's host/mem weak stubs.
    pending: list[tuple[int, int, str]] = []
    for kind, roff, lab in obj["rels"]:
        if lab in HOST_SYMS:
            pending.append((kind, roff, lab))
            continue
        if is_x64:
            if kind == FK_REL32 and lab in local and not local[lab][1]:
                target = local[lab][0]
                struct.pack_into("<i", code, roff, target - (roff + 4))
                continue
            pending.append((kind, roff, lab))
        else:
            if lab in local and not local[lab][1] and kind in (FK_B, FK_BL, FK_CBZ, FK_CBNZ):
                apply_local_branch_arm64(code, kind, roff, local[lab][0])
            else:
                pending.append((kind, roff, lab))

    undef: set[str] = set(HOST_SYMS)
    for _kind, _roff, lab in pending:
        if lab not in local or lab in HOST_SYMS:
            undef.add(lab)
    for name, _off, is_data in labs:
        if is_data and name.startswith("_iat_"):
            undef.add(iat_target(name))

    defined: list[tuple[str, int, int, int]] = []
    for name, off, is_data in sorted(labs, key=lambda x: (x[2], x[1], x[0])):
        if name in HOST_SYMS:
            continue
        defined.append((name, 2 if is_data else 1, 0, off))
    if "_start" in local and not any(n == "_xu_app_start" for n, *_ in defined):
        defined.append(("_xu_app_start", 1, 0, local["_start"][0]))

    undef_list = sorted(undef - {n for n, *_ in defined})
    syms: list[tuple[str, int, int, int, int]] = []
    for name, sect, desc, val in defined:
        syms.append((name, N_SECT | N_EXT, sect, desc, val))
    for name in undef_list:
        syms.append((name, N_UNDF | N_EXT, 0, 0, 0))
    sym_index = {n: i for i, (n, *_) in enumerate(syms)}
    nextdef = len(defined)
    nundef = len(undef_list)

    text_relocs: list[bytes] = []
    data_relocs: list[bytes] = []
    for kind, roff, lab in pending:
        sym = sym_index[lab]
        if is_x64:
            if kind == FK_REL32:
                # call/jmp disp32
                text_relocs.append(pack_reloc(roff, sym, 1, 2, 1, X86_64_RELOC_BRANCH))
                struct.pack_into("<i", code, roff, 0)
            elif kind == FK_RIP32:
                # RIP-relative load/lea (incl. local _iat_* slots)
                text_relocs.append(pack_reloc(roff, sym, 1, 2, 1, X86_64_RELOC_SIGNED))
                struct.pack_into("<i", code, roff, 0)
            else:
                raise SystemExit(f"unknown x64 reloc kind {kind}")
        else:
            if kind in (FK_B, FK_BL):
                text_relocs.append(pack_reloc(roff, sym, 1, 2, 1, ARM64_RELOC_BRANCH26))
            elif kind in (FK_CBZ, FK_CBNZ):
                text_relocs.append(pack_reloc(roff, sym, 1, 2, 1, ARM64_RELOC_BRANCH19))
            elif kind == FK_ADRP_ADD:
                text_relocs.append(pack_reloc(roff, sym, 1, 2, 1, ARM64_RELOC_PAGE21))
                text_relocs.append(pack_reloc(roff + 4, sym, 0, 2, 1, ARM64_RELOC_PAGEOFF12))
            else:
                raise SystemExit(f"unknown arm64 reloc kind {kind}")
    for name, off, is_data in labs:
        if not is_data or not name.startswith("_iat_"):
            continue
        t = iat_target(name)
        rtype = X86_64_RELOC_UNSIGNED if is_x64 else ARM64_RELOC_UNSIGNED
        data_relocs.append(pack_reloc(off, sym_index[t], 0, 3, 1, rtype))

    # String table
    strings = bytearray(b"\0")
    strx: dict[str, int] = {}
    for name, *_ in syms:
        strx[name] = len(strings)
        strings.extend(name.encode() + b"\0")

    nsects = 2
    seg_cmd = 72 + 80 * nsects
    sizeofcmds = seg_cmd + 24 + 24 + 80  # + BUILD_VER + SYMTAB + DYSYMTAB
    header = 32
    text_off = header + sizeofcmds
    text_off = align(text_off, 8)
    data_off = align(text_off + len(code), 8)
    text_reloff = align(data_off + len(data), 8)
    data_reloff = text_reloff + 8 * len(text_relocs)
    symoff = align(data_reloff + 8 * len(data_relocs), 8)
    stroff = symoff + 16 * len(syms)

    seg_fileoff = text_off
    seg_filesize = (data_off - text_off) + len(data)
    seg_vmsize = align(seg_filesize, 8)

    cpu_type = CPU_TYPE_X86_64 if is_x64 else CPU_TYPE_ARM64
    cpu_subtype = CPU_SUBTYPE_X86_64_ALL if is_x64 else CPU_SUBTYPE_ARM64_ALL

    buf = bytearray()
    buf += struct.pack(
        "<IIIIIIII",
        MH_MAGIC_64,
        cpu_type,
        cpu_subtype,
        MH_OBJECT,
        4,
        sizeofcmds,
        0,
        0,
    )
    # LC_SEGMENT_64
    buf += struct.pack("<II", LC_SEGMENT_64, seg_cmd)
    buf += b"\0" * 16
    buf += struct.pack("<QQQQIIII", 0, seg_vmsize, seg_fileoff, seg_filesize, 7, 7, nsects, 0)
    # __text
    buf += b"__text".ljust(16, b"\0") + b"__TEXT".ljust(16, b"\0")
    buf += struct.pack(
        "<QQIIIIIIii",
        0,
        len(code),
        text_off,
        2,
        text_reloff if text_relocs else 0,
        len(text_relocs),
        0x80000400,
        0,
        0,
        0,
    )
    # __data
    buf += b"__data".ljust(16, b"\0") + b"__DATA".ljust(16, b"\0")
    buf += struct.pack(
        "<QQIIIIIIii",
        0,
        len(data),
        data_off,
        3,
        data_reloff if data_relocs else 0,
        len(data_relocs),
        0,
        0,
        0,
        0,
    )
    # LC_BUILD_VERSION (macOS 11.0)
    buf += struct.pack("<II", LC_BUILD_VERSION, 24)
    buf += struct.pack("<IIII", 1, 0x000B0000, 0x000B0000, 0)
    # LC_SYMTAB
    buf += struct.pack("<II", LC_SYMTAB, 24)
    buf += struct.pack("<IIII", symoff, len(syms), stroff, len(strings))
    # LC_DYSYMTAB
    buf += struct.pack("<II", LC_DYSYMTAB, 80)
    buf += struct.pack(
        "<18I",
        0,
        0,
        0,
        nextdef,
        nextdef,
        nundef,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )

    assert len(buf) == header + sizeofcmds
    while len(buf) < text_off:
        buf.append(0)
    buf.extend(code)
    while len(buf) < data_off:
        buf.append(0)
    buf.extend(data)
    while len(buf) < text_reloff:
        buf.append(0)
    for r in text_relocs:
        buf.extend(r)
    while len(buf) < data_reloff:
        buf.append(0)
    for r in data_relocs:
        buf.extend(r)
    while len(buf) < symoff:
        buf.append(0)
    for name, n_type, n_sect, n_desc, n_value in syms:
        buf += struct.pack("<IBBHQ", strx[name], n_type, n_sect, n_desc, n_value)
    while len(buf) < stroff:
        buf.append(0)
    buf.extend(strings)

    out_path.write_bytes(buf)
    arch_name = "x64" if is_x64 else "arm64"
    print(
        f"wrote {out_path} arch={arch_name} code={len(code)} data={len(data)} "
        f"syms={len(syms)} tr={len(text_relocs)} dr={len(data_relocs)}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} in.xuobj out.o")
    convert(Path(sys.argv[1]), Path(sys.argv[2]))
