#!/usr/bin/env python3
"""Convert Xu XUOBJ (windows-x64 / windows-arm64) → PE-COFF .o for linking with mingw UI host."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

MACHINE_AMD64 = 0x8664
MACHINE_ARM64 = 0xAA64
SCN_CNT_CODE = 0x00000020
SCN_CNT_INIT_DATA = 0x00000040
SCN_MEM_EXECUTE = 0x20000000
SCN_MEM_READ = 0x40000000
SCN_MEM_WRITE = 0x80000000
SCN_ALIGN_1 = 0x00100000
SCN_ALIGN_8 = 0x00D00000
C_EXT = 2
IMAGE_REL_AMD64_REL32 = 4
FK_REL32 = 0
FK_RIP32 = 1
HOST_SYMS = frozenset(
    {
        "xu_ui_host_run",
        "xu_ui_mem_try_write",
        "xu_ui_mem_try_read_len",
        "xu_ui_mem_try_read_copy",
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

    getstr()
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
    code = bytearray(b[o : o + clen])
    o += clen
    dlen = struct.unpack_from("<I", b, o)[0]
    o += 4
    data = bytearray(b[o : o + dlen])
    return {"arch": arch, "labs": labs, "rels": rels, "code": code, "data": data}


def iat_imp_name(lab: str) -> str:
    return "__imp_" + lab[len("_iat_") :]


def realign_data(data: bytearray, labs: list[tuple[str, int, bool]], align_n: int = 8) -> tuple[bytearray, list[tuple[str, int, bool]]]:
    """Pad .data so every data label is align_n-byte aligned (pointer slots / IAT)."""
    data_labs = sorted(((off, name) for name, off, is_data in labs if is_data), key=lambda x: x[0])
    if not data_labs:
        return data, labs
    new = bytearray()
    old_to_new: dict[int, int] = {}
    cursor = 0
    for off, _name in data_labs:
        if off < cursor:
            raise SystemExit(f"overlapping data labels at {off}")
        new.extend(data[cursor:off])
        while len(new) % align_n:
            new.append(0)
        old_to_new[off] = len(new)
        cursor = off
    new.extend(data[cursor:])
    out_labs: list[tuple[str, int, bool]] = []
    for name, off, is_data in labs:
        if is_data:
            out_labs.append((name, old_to_new[off], True))
        else:
            out_labs.append((name, off, False))
    return new, out_labs


def apply_local_branch_arm64(code: bytearray, kind: int, roff: int, target_off: int) -> None:
    delta = (target_off - roff) // 4
    if kind in (0, 1):
        imm26 = delta & 0x03FFFFFF
        opcode = 0x14000000 if kind == 0 else 0x94000000
        struct.pack_into("<I", code, roff, opcode | imm26)
    elif kind in (2, 3):
        imm19 = delta & 0x0007FFFF
        rt = code[roff] & 0x1F
        opcode = 0xB4000000 if kind == 2 else 0xB5000000
        struct.pack_into("<I", code, roff, opcode | (imm19 << 5) | rt)


def convert(xuobj_path: Path, out_path: Path) -> None:
    obj = decode_xuobj(xuobj_path.read_bytes())
    is_arm64 = obj["arch"] == 1
    if obj["arch"] not in (1, 2):
        raise SystemExit(f"only arm64=1 or x64=2 xuobj supported (arch={obj['arch']})")
    code: bytearray = obj["code"]
    data, labs = realign_data(obj["data"], list(obj["labs"]))
    local = {n: (off, is_data) for n, off, is_data in labs}

    pending: list[tuple[int, int, str]] = []
    for kind, roff, lab in obj["rels"]:
        if lab in HOST_SYMS:
            pending.append((kind, roff, lab))
            continue
        if is_arm64:
            if kind in (0, 1, 2, 3) and lab in local and not local[lab][1]:
                target = local[lab][0]
                apply_local_branch_arm64(code, kind, roff, target)
                continue
        else:
            if kind == FK_REL32 and lab in local and not local[lab][1]:
                target = local[lab][0]
                struct.pack_into("<i", code, roff, target - (roff + 4))
                continue
        pending.append((kind, roff, lab))

    defined: list[tuple[str, int, int]] = []
    for name, off, is_data in sorted(labs, key=lambda x: (x[2], x[1], x[0])):
        if name in HOST_SYMS:
            continue
        defined.append((name, 2 if is_data else 1, off))
    if "_start" in local:
        defined.append(("xu_app_start", 1, local["_start"][0]))

    undef: set[str] = set(HOST_SYMS)
    for _kind, _roff, lab in pending:
        if lab in HOST_SYMS:
            undef.add(lab)
        elif lab.startswith("_iat_"):
            undef.add(iat_imp_name(lab))
        elif lab not in local:
            undef.add(lab)

    undef_list = sorted(undef)
    syms: list[tuple[str, int, int, int, int]] = []
    for name, sect, val in defined:
        syms.append((name, val, sect, 0, C_EXT))
    for name in undef_list:
        syms.append((name, 0, 0, 0, C_EXT))
    sym_index = {n: i for i, (n, *_) in enumerate(syms)}

    text_relocs: list[tuple[int, int, int]] = []
    for kind, roff, lab in pending:
        sym_name = iat_imp_name(lab) if lab.startswith("_iat_") else lab
        if is_arm64:
            if kind in (0, 1):
                text_relocs.append((roff, sym_index[sym_name], 3))
            elif kind in (2, 3):
                text_relocs.append((roff, sym_index[sym_name], 15))
            elif kind == 4:
                text_relocs.append((roff, sym_index[sym_name], 4))
                text_relocs.append((roff + 4, sym_index[sym_name], 6))
            else:
                raise SystemExit(f"unknown arm64 reloc kind {kind}")
        else:
            if kind == FK_REL32:
                text_relocs.append((roff, sym_index[lab], IMAGE_REL_AMD64_REL32))
            elif kind == FK_RIP32:
                text_relocs.append((roff, sym_index[sym_name], IMAGE_REL_AMD64_REL32))
            else:
                raise SystemExit(f"unknown x64 reloc kind {kind}")

    strings = bytearray()
    str_index: dict[str, int] = {}
    name_fields: list[bytes] = []
    for n, *_rest in syms:
        enc = n.encode("ascii")
        if len(enc) <= 8:
            name_fields.append(enc.ljust(8, b"\0"))
        else:
            if n not in str_index:
                str_index[n] = 4 + len(strings)
                strings.extend(enc + b"\0")
            name_fields.append(struct.pack("<II", 0, str_index[n]))
    string_table = struct.pack("<I", 4 + len(strings)) + bytes(strings)

    nsections = 2
    file_hdr_sz = 20
    sec_hdr_sz = 40
    text_off = align(file_hdr_sz + sec_hdr_sz * nsections, 16)
    data_off = align(text_off + len(code), 16)
    text_reloc_off = align(data_off + len(data), 4) if text_relocs else 0
    reloc_bytes = 10 * len(text_relocs)
    symtab_off = align((text_reloc_off or data_off + len(data)) + reloc_bytes, 4)

    text_chars = SCN_CNT_CODE | SCN_MEM_EXECUTE | SCN_MEM_READ | SCN_ALIGN_1
    data_chars = SCN_CNT_INIT_DATA | SCN_MEM_READ | SCN_MEM_WRITE | SCN_ALIGN_8

    def sec_hdr(name: str, size: int, raw_off: int, reloc_off: int, nreloc: int, chars: int) -> bytes:
        return name.encode().ljust(8, b"\0")[:8] + struct.pack(
            "<IIIIIIHHI",
            size,
            0,
            size,
            raw_off,
            reloc_off,
            0,
            nreloc if nreloc < 65535 else 0xFFFF,
            0,
            chars,
        )

    out = bytearray()
    out += struct.pack(
        "<HHIIIHH",
        MACHINE_ARM64 if is_arm64 else MACHINE_AMD64,
        nsections,
        0,
        symtab_off,
        len(syms),
        0,
        0,
    )
    out += sec_hdr(".text", len(code), text_off, text_reloc_off, len(text_relocs), text_chars)
    out += sec_hdr(".data", len(data), data_off, 0, 0, data_chars)
    out += b"\0" * (text_off - len(out))
    out += code
    out += b"\0" * (data_off - len(out))
    out += data
    if text_relocs:
        out += b"\0" * (text_reloc_off - len(out))
        for vaddr, symidx, rtype in text_relocs:
            out += struct.pack("<IIH", vaddr, symidx, rtype)
    out += b"\0" * (symtab_off - len(out))
    for nf, (_n, val, sect, typ, storage) in zip(name_fields, syms):
        out += nf + struct.pack("<IHHBB", val, sect, typ, storage, 0)
    out += string_table
    out_path.write_bytes(out)


def main() -> None:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} in.xuobj out.o", file=sys.stderr)
        sys.exit(2)
    convert(Path(sys.argv[1]), Path(sys.argv[2]))
    print("wrote", sys.argv[2])


if __name__ == "__main__":
    main()
