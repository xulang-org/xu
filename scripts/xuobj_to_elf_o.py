#!/usr/bin/env python3
"""Convert Xu XUOBJ (linux) → ELF ET_REL .o for static link with libxu_ui_host.a.

Supports linux-x64 (arch=2) and linux-arm64 (arch=1). Host symbol xu_ui_host_run
is left undefined so the C++ archive provides it (no cgo / no second process).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ET_REL = 1
EM_X86_64 = 62
EM_AARCH64 = 183
EV_CURRENT = 1
SHT_NULL = 0
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_RELA = 4
SHF_WRITE = 0x1
SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4
SHF_INFO_LINK = 0x40
STB_GLOBAL = 1
STT_NOTYPE = 0
STT_FUNC = 2
STT_OBJECT = 1
STT_SECTION = 3
SHN_UNDEF = 0
R_X86_64_PC32 = 2
R_X86_64_PLT32 = 4
R_AARCH64_CALL26 = 283
R_AARCH64_JUMP26 = 282
R_AARCH64_ADR_PREL_PG_HI21 = 275
R_AARCH64_ADD_ABS_LO12_NC = 277
R_AARCH64_CONDBR19 = 280
FK_REL32 = 0
FK_RIP32 = 1
FK_B, FK_BL, FK_CBZ, FK_CBNZ, FK_ADRP_ADD = 0, 1, 2, 3, 4
HOST_SYMS = frozenset(
    {
        "xu_ui_host_run",
        # Weak stubs in XUOBJ must stay undefined so pack links strong xu_ui_mem from host.a
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
    return {"os": _os, "arch": arch, "labs": labs, "rels": rels, "code": code, "data": data}


def iat_name(lab: str) -> str:
    # Linux: _iat_foo → foo (dynamic import resolved at final link / unused for static UI)
    if lab.startswith("_iat_"):
        return lab[5:]
    return lab


def realign_data(data: bytearray, labs: list) -> tuple[bytearray, list]:
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
        while len(new) % 8:
            new.append(0)
        old_to_new[off] = len(new)
        cursor = off
    new.extend(data[cursor:])
    out_labs = []
    for name, off, is_data in labs:
        out_labs.append((name, old_to_new[off] if is_data else off, is_data))
    return new, out_labs


def patch32(buf: bytearray, off: int, word: int) -> None:
    struct.pack_into("<I", buf, off, word & 0xFFFFFFFF)


def apply_local_branch_arm64(code: bytearray, kind: int, roff: int, target_off: int) -> None:
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


def elf_hash_strtab(names: list[str]) -> tuple[bytearray, dict[str, int]]:
    st = bytearray(b"\0")
    idx = {"": 0}
    for n in names:
        if n in idx:
            continue
        idx[n] = len(st)
        st.extend(n.encode() + b"\0")
    return st, idx


def convert(xuobj_path: Path, out_path: Path) -> None:
    obj = decode_xuobj(xuobj_path.read_bytes())
    arch = obj["arch"]
    if arch not in (1, 2):
        raise SystemExit(f"unsupported arch={arch} (need arm64=1 or x64=2)")
    is_x64 = arch == 2
    code: bytearray = obj["code"]
    data, labs = realign_data(obj["data"], list(obj["labs"]))
    local = {n: (off, is_data) for n, off, is_data in labs}

    pending: list[tuple[int, int, str]] = []
    for kind, roff, lab in obj["rels"]:
        if lab in HOST_SYMS:
            pending.append((kind, roff, lab))
            continue
        if is_x64 and kind == FK_REL32 and lab in local and not local[lab][1]:
            target = local[lab][0]
            struct.pack_into("<i", code, roff, target - (roff + 4))
            continue
        if (not is_x64) and lab in local and not local[lab][1] and kind in (
            FK_B,
            FK_BL,
            FK_CBZ,
            FK_CBNZ,
        ):
            apply_local_branch_arm64(code, kind, roff, local[lab][0])
            continue
        pending.append((kind, roff, lab))

    defined: list[tuple[str, int, int]] = []  # name, shndx(1=.text 2=.data), value
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
            undef.add(iat_name(lab))
        elif lab not in local:
            undef.add(lab)

    # ELF symbols: [0]=null, then section symbols, then defined, then undef
    # shndx: 1=.text 2=.data
    syms: list[tuple[str, int, int, int, int]] = []  # name, value, size, info, shndx
    syms.append(("", 0, 0, 0, 0))
    syms.append((".text", 0, 0, (STB_GLOBAL << 4) | STT_SECTION, 1))
    syms.append((".data", 0, 0, (STB_GLOBAL << 4) | STT_SECTION, 2))
    for name, shndx, val in defined:
        stt = STT_OBJECT if shndx == 2 else STT_FUNC
        syms.append((name, val, 0, (STB_GLOBAL << 4) | stt, shndx))
    for name in sorted(undef):
        syms.append((name, 0, 0, (STB_GLOBAL << 4) | STT_NOTYPE, SHN_UNDEF))
    sym_index = {n: i for i, (n, *_r) in enumerate(syms)}

    # RELA entries: (offset, sym_idx, type, addend)
    relas: list[tuple[int, int, int, int]] = []
    for kind, roff, lab in pending:
        if lab.startswith("_iat_"):
            sname = iat_name(lab)
        else:
            sname = lab
        si = sym_index[sname]
        if is_x64:
            if kind in (FK_REL32, FK_RIP32):
                # PC-relative; addend -4 for typical call/jmp disp
                relas.append((roff, si, R_X86_64_PLT32 if lab in HOST_SYMS else R_X86_64_PC32, -4))
                struct.pack_into("<i", code, roff, 0)
            else:
                raise SystemExit(f"unknown x64 reloc kind {kind}")
        else:
            if kind in (FK_B, FK_BL):
                rtype = R_AARCH64_CALL26 if kind == FK_BL else R_AARCH64_JUMP26
                relas.append((roff, si, rtype, 0))
            elif kind in (FK_CBZ, FK_CBNZ):
                relas.append((roff, si, R_AARCH64_CONDBR19, 0))
            elif kind == FK_ADRP_ADD:
                relas.append((roff, si, R_AARCH64_ADR_PREL_PG_HI21, 0))
                relas.append((roff + 4, si, R_AARCH64_ADD_ABS_LO12_NC, 0))
            else:
                raise SystemExit(f"unknown arm64 reloc kind {kind}")

    shstr_names = ["", ".text", ".data", ".shstrtab", ".symtab", ".strtab", ".rela.text"]
    shstr, shstr_idx = elf_hash_strtab(shstr_names)
    strtab, str_idx = elf_hash_strtab([n for n, *_ in syms])

    # Layout: Ehdr + Shdr[7] + .text + .data + .shstrtab + .symtab + .strtab + .rela.text
    ehdr_sz = 64
    shdr_sz = 64
    nsh = 7
    text_off = align(ehdr_sz + shdr_sz * nsh, 16)
    data_off = align(text_off + len(code), 16)
    shstr_off = align(data_off + len(data), 8)
    sym_off = align(shstr_off + len(shstr), 8)
    str_off = align(sym_off + 24 * len(syms), 8)
    rela_off = align(str_off + len(strtab), 8)

    def shdr(
        name: str,
        typ: int,
        flags: int,
        addr: int,
        off: int,
        size: int,
        link: int,
        info: int,
        addralign: int,
        entsize: int,
    ) -> bytes:
        return struct.pack(
            "<IIQQQQIIQQ",
            shstr_idx[name],
            typ,
            flags,
            addr,
            off,
            size,
            link,
            info,
            addralign,
            entsize,
        )

    out = bytearray()
    # ELF64 header
    out += b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    out += struct.pack(
        "<HHIQQQIHHHHHH",
        ET_REL,
        EM_X86_64 if is_x64 else EM_AARCH64,
        EV_CURRENT,
        0,  # e_entry
        0,  # e_phoff
        ehdr_sz,  # e_shoff
        0,  # e_flags
        ehdr_sz,
        0,  # e_phentsize
        0,  # e_phnum
        shdr_sz,
        nsh,
        3,  # e_shstrndx = .shstrtab
    )
    # Section headers
    out += shdr("", SHT_NULL, 0, 0, 0, 0, 0, 0, 0, 0)
    out += shdr(".text", SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR, 0, text_off, len(code), 0, 0, 16, 0)
    out += shdr(".data", SHT_PROGBITS, SHF_ALLOC | SHF_WRITE, 0, data_off, len(data), 0, 0, 8, 0)
    out += shdr(".shstrtab", SHT_STRTAB, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0)
    # .symtab link=.strtab(5) info=first non-local (all global → 1)
    out += shdr(".symtab", SHT_SYMTAB, 0, 0, sym_off, 24 * len(syms), 5, 1, 8, 24)
    out += shdr(".strtab", SHT_STRTAB, 0, 0, str_off, len(strtab), 0, 0, 1, 0)
    out += shdr(
        ".rela.text",
        SHT_RELA,
        SHF_INFO_LINK,
        0,
        rela_off,
        24 * len(relas),
        4,  # link = .symtab
        1,  # info = .text
        8,
        24,
    )

    out += b"\0" * (text_off - len(out))
    out += code
    out += b"\0" * (data_off - len(out))
    out += data
    out += b"\0" * (shstr_off - len(out))
    out += shstr
    out += b"\0" * (sym_off - len(out))
    for name, val, size, info, shndx in syms:
        out += struct.pack("<IBBHQQ", str_idx[name], info, 0, shndx, val, size)
    out += b"\0" * (str_off - len(out))
    out += strtab
    out += b"\0" * (rela_off - len(out))
    for off, si, rtype, addend in relas:
        r_info = (si << 32) | rtype
        out += struct.pack("<QQq", off, r_info, addend)

    out_path.write_bytes(out)


def main() -> None:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} in.xuobj out.o", file=sys.stderr)
        sys.exit(2)
    convert(Path(sys.argv[1]), Path(sys.argv[2]))
    print("wrote", sys.argv[2])


if __name__ == "__main__":
    main()
