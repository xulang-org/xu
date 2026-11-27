#!/usr/bin/env python3
"""Verify binary format standardization across ALL non-desktop/server Xu targets:

  1. UEFI PE32+ applications (x64-uefi, arm64-uefi): W^X, .reloc + Data Dir #5,
     DYNAMIC_BASE | HIGH_ENTROPY_VA | NX_COMPAT, EFI_APPLICATION subsystem.
  2. Bare-metal ELF64 executables (x64-none, arm64-none, riscv64-none): ET_EXEC,
     PT_LOAD + PT_GNU_STACK (RW), Section Headers always present, non-ALLOC
     deterministic GNU Build-ID, machine e_flags, optional DWARF.
  3. Bare-metal ELF64 relocatable objects (--emit-obj): ET_REL, machine e_flags,
     .text, .symtab, .strtab, .shstrtab, .note.GNU-stack.
  4. Embedded ELF32 executables (xtensa-esp32-none, riscv32imac-none,
     thumbv7em-none): ELFCLASS32, ET_EXEC, PT_LOAD + PT_GNU_STACK (RW),
     Section Headers (.text, non-ALLOC .note.gnu.build-id, .shstrtab), plus
     Thumb SVC check via prove_no_syscalls.
  5. WebAssembly modules (wasm32, wasm32-wasi): valid magic/version, ordered
     sections, standard "name" and "producers" custom sections, plus V8
     WebAssembly.validate check when Node.js is available.
  6. App relocatable object converters (built-in _macho_o, _ios_o, _ios_sim_o,
     _elf_o, _coff_o + scripts/xuobj_to_{macho,elf,coff}_o.py): Mach-O 16B
     __text align & contiguous __data.addr, ELF .note.GNU-stack & STB_LOCAL
     section symbols, COFF VirtualSize==0 & ALIGN_16/ALIGN_8 & function dtype.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prove_no_syscalls  # noqa: E402

PT_LOAD = 1
PT_GNU_STACK = 0x6474E551
PF_W = 2
PF_R = 4
ET_REL = 1
ET_EXEC = 2
SHT_PROGBITS = 1
SHT_SYMTAB = 2
SHT_STRTAB = 3
SHT_NOTE = 7
SHF_ALLOC = 2
NT_GNU_BUILD_ID = 3

MINIMAL_SOURCE = """@main
fn main() int {
    << 0
}
"""

WASM_SOURCE = """@main
fn main() int {
    println("wasm ok")
    << 0
}
"""

APP_SOURCE = """@main
fn main() int {
    println("app obj ok")
    << 0
}
"""


def find_compiler() -> Path:
    env_xu = os.environ.get("XU", "").strip()
    if env_xu:
        return Path(env_xu).resolve()
    return (ROOT / "bin" / "xu").resolve()


def find_llvm_tool(name: str) -> str | None:
    for cand in (shutil.which(name), f"/opt/homebrew/opt/llvm/bin/{name}"):
        if cand and Path(cand).is_file():
            return cand
    cellar = Path("/opt/homebrew/Cellar/llvm")
    if cellar.is_dir():
        for bin_path in sorted(cellar.glob(f"*/bin/{name}"), reverse=True):
            return str(bin_path)
    return None


def parse_elf32(data: bytes) -> dict:
    assert len(data) >= 52 and data[:6] == b"\x7fELF\x01\x01", "not ELF32 LE"
    (
        e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags,
        e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx,
    ) = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    assert e_version == 1 and e_ehsize == 52 and e_shentsize == 40
    phdrs = []
    for i in range(e_phnum):
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from(
            "<IIIIIIII", data, e_phoff + i * e_phentsize
        )
        phdrs.append(dict(type=p_type, offset=p_offset, vaddr=p_vaddr, filesz=p_filesz,
                          memsz=p_memsz, flags=p_flags, align=p_align))
    assert e_shnum > 0 and e_shoff > 0 and 0 < e_shstrndx < e_shnum
    raw_shdrs = [struct.unpack_from("<IIIIIIIIII", data, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    shstr_off, shstr_sz = raw_shdrs[e_shstrndx][4], raw_shdrs[e_shstrndx][5]
    shstr = data[shstr_off:shstr_off + shstr_sz]
    shdrs = []
    for sh in raw_shdrs:
        end = shstr.index(b"\x00", sh[0])
        shdrs.append(dict(name=shstr[sh[0]:end].decode("ascii"), type=sh[1], flags=sh[2],
                          addr=sh[3], offset=sh[4], size=sh[5], link=sh[6], info=sh[7],
                          align=sh[8], entsize=sh[9]))
    return dict(type=e_type, machine=e_machine, entry=e_entry, flags=e_flags, phdrs=phdrs, shdrs=shdrs)


def parse_elf64(data: bytes) -> dict:
    assert len(data) >= 64 and data[:6] == b"\x7fELF\x02\x01", "not ELF64 LE"
    (
        e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags,
        e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx,
    ) = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    assert e_version == 1 and e_ehsize == 64 and e_shentsize == 64
    phdrs = []
    for i in range(e_phnum):
        p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from(
            "<IIQQQQQQ", data, e_phoff + i * e_phentsize
        )
        phdrs.append(dict(type=p_type, flags=p_flags, offset=p_offset, vaddr=p_vaddr,
                          filesz=p_filesz, memsz=p_memsz, align=p_align))
    assert e_shnum > 0 and e_shoff > 0 and 0 < e_shstrndx < e_shnum
    raw_shdrs = [struct.unpack_from("<IIQQQQIIQQ", data, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    shstr_off, shstr_sz = raw_shdrs[e_shstrndx][4], raw_shdrs[e_shstrndx][5]
    shstr = data[shstr_off:shstr_off + shstr_sz]
    shdrs = []
    for sh in raw_shdrs:
        end = shstr.index(b"\x00", sh[0])
        shdrs.append(dict(name=shstr[sh[0]:end].decode("ascii"), type=sh[1], flags=sh[2],
                          addr=sh[3], offset=sh[4], size=sh[5], link=sh[6], info=sh[7],
                          align=sh[8], entsize=sh[9]))
    return dict(type=e_type, machine=e_machine, entry=e_entry, flags=e_flags, phdrs=phdrs, shdrs=shdrs)


def read_leb_u32(data: bytes, pos: int) -> tuple[int, int]:
    val = shift = 0
    while True:
        b = data[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return val, pos
        shift += 7


def parse_wasm_sections(data: bytes) -> list[tuple[int, str | None, bytes]]:
    assert data[:8] == b"\x00asm\x01\x00\x00\x00", "invalid wasm header"
    pos = 8
    out = []
    while pos < len(data):
        sec_id = data[pos]
        pos += 1
        sec_len, pos = read_leb_u32(data, pos)
        payload = data[pos:pos + sec_len]
        pos += sec_len
        cname = None
        if sec_id == 0:
            nlen, npos = read_leb_u32(payload, 0)
            cname = payload[npos:npos + nlen].decode("utf-8")
            payload = payload[npos + nlen:]
        out.append((sec_id, cname, payload))
    assert pos == len(data)
    return out


class BinaryFormatsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compiler = find_compiler()
        cls.readelf = find_llvm_tool("llvm-readelf") or shutil.which("readelf")
        cls.readobj = find_llvm_tool("llvm-readobj")
        cls.node = shutil.which("node")

    def clean_env(self, work: Path) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("XU")}
        env.update(XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / "src"), XUPATH="", XU_CACHE=str(work / "cache"))
        return env

    def build(self, work: Path, source: str, target: str, name: str, extra: list[str] | None = None) -> Path:
        src = work / f"{name}.xu"
        out = work / name
        src.write_text(source, encoding="utf-8")
        cmd = [str(self.compiler), "build", str(src), "--target", target, *(extra or []), "-o", str(out)]
        res = subprocess.run(cmd, env=self.clean_env(work), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"build failed for {target}/{name}:\n{res.stdout}\n{res.stderr}")
        return out

    def assert_build_id_note(self, data: bytes, note_sec: dict) -> None:
        self.assertEqual(note_sec["type"], SHT_NOTE)
        self.assertEqual(note_sec["flags"] & SHF_ALLOC, 0, "baremetal/embedded build-id must be non-ALLOC")
        self.assertEqual(note_sec["size"], 36)
        namesz, descsz, ntype = struct.unpack_from("<III", data, note_sec["offset"])
        self.assertEqual((namesz, descsz, ntype), (4, 20, NT_GNU_BUILD_ID))
        self.assertEqual(data[note_sec["offset"] + 12:note_sec["offset"] + 16], b"GNU\x00")
        self.assertTrue(any(data[note_sec["offset"] + 16:note_sec["offset"] + 36]))

    def test_uefi_pe32_plus(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            for target, expected_mach in (("x64-uefi", 0x8664), ("arm64-uefi", 0xAA64)):
                efi = self.build(work, MINIMAL_SOURCE, target, f"app_{target}.efi")
                raw = efi.read_bytes()
                self.assertEqual(raw[:2], b"MZ")
                pe_off = struct.unpack_from("<I", raw, 0x3C)[0]
                self.assertEqual(raw[pe_off:pe_off + 4], b"PE\0\0")
                mach, nsec, _, _, _, opt_sz, chars = struct.unpack_from("<HHIIIHH", raw, pe_off + 4)
                self.assertEqual(mach, expected_mach)
                self.assertEqual(chars, 0x0022)
                opt = pe_off + 24
                self.assertEqual(struct.unpack_from("<H", raw, opt)[0], 0x20B)
                subsys, dll_chars = struct.unpack_from("<HH", raw, opt + 68)
                self.assertEqual(subsys, 10)  # IMAGE_SUBSYSTEM_EFI_APPLICATION
                self.assertEqual(dll_chars, 0x0160)  # DYNAMIC_BASE | HIGH_ENTROPY_VA | NX_COMPAT
                reloc_rva, reloc_sz = struct.unpack_from("<II", raw, opt + 112 + 5 * 8)
                self.assertGreater(reloc_rva, 0)
                self.assertGreaterEqual(reloc_sz, 12)
                secs = []
                for i in range(nsec):
                    at = opt + opt_sz + i * 40
                    nm = raw[at:at + 8].split(b"\0", 1)[0].decode("ascii")
                    vsize, vaddr, rsize, rptr, _, _, _, _, schars = struct.unpack_from("<IIIIIIHHI", raw, at + 8)
                    self.assertNotEqual(schars & 0xA0000000, 0xA0000000, f"W^X violation in UEFI {nm}")
                    secs.append((nm, vsize, vaddr, schars))
                sec_map = {s[0]: s for s in secs}
                self.assertIn(".text", sec_map)
                self.assertIn(".reloc", sec_map)
                self.assertEqual(sec_map[".text"][3], 0x60000020)
                self.assertEqual(sec_map[".reloc"][3], 0x42000040)
                self.assertEqual(reloc_rva, sec_map[".reloc"][2])
                self.assertEqual(reloc_sz, sec_map[".reloc"][1])
                if self.readobj:
                    res = subprocess.run(
                        [self.readobj, "--file-headers", "--sections", "--coff-basereloc", str(efi)],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(res.returncode, 0, res.stderr)
                    self.assertIn("BaseRelocationTableRVA", res.stdout)

    def test_baremetal_elf64_exec_and_obj(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            for target, mach, expected_flags in (
                ("x64-none", 62, 0),
                ("arm64-none", 183, 0),
                ("riscv64-none", 243, 5),
            ):
                for dwarf in (False, True):
                    out = self.build(work, MINIMAL_SOURCE, target, f"bm_{target}_{int(dwarf)}",
                                     ["-g"] if dwarf else [])
                    raw = out.read_bytes()
                    info = parse_elf64(raw)
                    self.assertEqual(info["type"], ET_EXEC)
                    self.assertEqual(info["machine"], mach)
                    self.assertEqual(info["flags"], expected_flags)
                    stacks = [p for p in info["phdrs"] if p["type"] == PT_GNU_STACK]
                    self.assertEqual(len(stacks), 1)
                    self.assertEqual(stacks[0]["flags"], PF_R | PF_W)
                    secs = {s["name"]: s for s in info["shdrs"]}
                    self.assertIn(".text", secs)
                    self.assertIn(".note.gnu.build-id", secs)
                    self.assertIn(".shstrtab", secs)
                    self.assert_build_id_note(raw, secs[".note.gnu.build-id"])
                    if dwarf:
                        self.assertIn(".debug_info", secs)
                    if self.readelf:
                        res = subprocess.run([self.readelf, "-h", "-l", "-S", "-n", str(out)],
                                             capture_output=True, text=True)
                        self.assertEqual(res.returncode, 0, res.stderr)
                        self.assertIn("Build ID:", res.stdout)
                        self.assertNotIn("Warning:", res.stderr)

                obj = self.build(work, MINIMAL_SOURCE, target, f"bm_{target}.o", ["--emit-obj"])
                oinfo = parse_elf64(obj.read_bytes())
                self.assertEqual(oinfo["type"], ET_REL)
                self.assertEqual(oinfo["machine"], mach)
                self.assertEqual(oinfo["flags"], expected_flags)
                osecs = {s["name"]: s for s in oinfo["shdrs"]}
                for req in (".text", ".symtab", ".strtab", ".shstrtab", ".note.GNU-stack"):
                    self.assertIn(req, osecs)
                self.assertEqual(osecs[".note.GNU-stack"]["flags"], 0)
                if self.readelf:
                    res = subprocess.run([self.readelf, "-h", "-S", "-s", "-r", str(obj)],
                                         capture_output=True, text=True)
                    self.assertEqual(res.returncode, 0, res.stderr)
                    self.assertNotIn("Warning:", res.stderr)

    def test_embedded_elf32(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            for target, mach, expected_flags in (
                ("xtensa-esp32-none", 94, 0x300),
                ("riscv32imac-none", 243, 0),
                ("thumbv7em-none", 40, 0x05000000),
            ):
                out = self.build(work, MINIMAL_SOURCE, target, f"emb_{target}.elf")
                raw = out.read_bytes()
                info = parse_elf32(raw)
                self.assertEqual(info["type"], ET_EXEC)
                self.assertEqual(info["machine"], mach)
                self.assertEqual(info["flags"], expected_flags)
                stacks = [p for p in info["phdrs"] if p["type"] == PT_GNU_STACK]
                self.assertEqual(len(stacks), 1)
                self.assertEqual(stacks[0]["flags"], PF_R | PF_W)
                secs = {s["name"]: s for s in info["shdrs"]}
                self.assertEqual([s["name"] for s in info["shdrs"]], ["", ".text", ".note.gnu.build-id", ".shstrtab"])
                self.assert_build_id_note(raw, secs[".note.gnu.build-id"])
                if target == "thumbv7em-none":
                    ok, msg = prove_no_syscalls.check_file(out)
                    self.assertTrue(ok, msg)
                if self.readelf:
                    res = subprocess.run([self.readelf, "-h", "-l", "-S", "-n", str(out)],
                                         capture_output=True, text=True)
                    self.assertEqual(res.returncode, 0, res.stderr)
                    self.assertIn("Build ID:", res.stdout)
                    self.assertNotIn("Warning:", res.stderr)

    def test_wasm_modules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            for target, src in (("wasm32", MINIMAL_SOURCE), ("wasm32-wasi", WASM_SOURCE)):
                out = self.build(work, src, target, f"mod_{target}.wasm")
                raw = out.read_bytes()
                secs = parse_wasm_sections(raw)
                std_ids = [sid for sid, _, _ in secs if sid != 0]
                self.assertEqual(std_ids, sorted(std_ids), f"out-of-order wasm sections: {std_ids}")
                custom_names = [nm for sid, nm, _ in secs if sid == 0]
                self.assertIn("name", custom_names)
                self.assertIn("producers", custom_names)
                prod_payload = next(p for sid, nm, p in secs if sid == 0 and nm == "producers")
                self.assertIn(b"language", prod_payload)
                self.assertIn(b"Xu", prod_payload)
                self.assertIn(b"processed-by", prod_payload)
                if self.node:
                    js = (
                        "const fs = require('fs');"
                        "const b = fs.readFileSync(process.argv[1]);"
                        "if (!WebAssembly.validate(b)) process.exit(2);"
                        "const m = new WebAssembly.Module(b);"
                        "if (WebAssembly.Module.customSections(m, 'name').length !== 1) process.exit(3);"
                        "if (WebAssembly.Module.customSections(m, 'producers').length !== 1) process.exit(4);"
                    )
                    res = subprocess.run([self.node, "-e", js, str(out)], capture_output=True, text=True)
                    self.assertEqual(res.returncode, 0, f"V8 WebAssembly.validate failed: {res.stderr}")

    def test_app_object_converters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            env = self.clean_env(work)

            # 1. Linux ELF .o (built-in _elf_o + scripts/xuobj_to_elf_o.py)
            for target in ("linux-x64", "linux-arm64"):
                xuobj = self.build(work, APP_SOURCE, target, f"app_{target}.xuobj", ["--emit-obj"])
                for label, cmd in (
                    ("builtin", [str(self.compiler), "_elf_o", str(xuobj)]),
                    ("script", [sys.executable, str(ROOT / "scripts/xuobj_to_elf_o.py"), str(xuobj)]),
                ):
                    out_o = work / f"app_{target}_{label}.o"
                    subprocess.run([*cmd, str(out_o)], env=env, check=True, capture_output=True, text=True)
                    raw = out_o.read_bytes()
                    info = parse_elf64(raw)
                    self.assertEqual(info["type"], ET_REL)
                    secs = {s["name"]: s for s in info["shdrs"]}
                    self.assertIn(".note.GNU-stack", secs, f"{target}/{label} missing .note.GNU-stack")
                    self.assertEqual(secs[".note.GNU-stack"]["flags"], 0)
                    symtab = secs[".symtab"]
                    if label == "script":
                        # STT_SECTION symbols (.text/.data) must be STB_LOCAL (< sh_info == 3).
                        self.assertEqual(symtab["info"], 3)
                        for si in (1, 2):
                            st_info = raw[symtab["offset"] + si * 24 + 4]
                            self.assertEqual(st_info >> 4, 0, f"section sym {si} not STB_LOCAL")
                    if self.readelf:
                        res = subprocess.run([self.readelf, "-h", "-S", "-s", "-r", str(out_o)],
                                             capture_output=True, text=True)
                        self.assertEqual(res.returncode, 0, res.stderr)
                        self.assertNotIn("Warning:", res.stderr)

            # 2. Windows COFF .o (built-in _coff_o + scripts/xuobj_to_coff_o.py)
            for target in ("windows-x64", "windows-arm64"):
                xuobj = self.build(work, APP_SOURCE, target, f"app_{target}.xuobj", ["--emit-obj"])
                for label, cmd in (
                    ("builtin", [str(self.compiler), "_coff_o", str(xuobj)]),
                    ("script", [sys.executable, str(ROOT / "scripts/xuobj_to_coff_o.py"), str(xuobj)]),
                ):
                    out_o = work / f"app_{target}_{label}.obj"
                    subprocess.run([*cmd, str(out_o)], env=env, check=True, capture_output=True, text=True)
                    raw = out_o.read_bytes()
                    _mach, nsecs, _ts, symoff, nsyms, optsz, _fchars = struct.unpack_from("<HHIIIHH", raw, 0)
                    self.assertEqual(optsz, 0)
                    for si in range(nsecs):
                        at = 20 + si * 40
                        nm = raw[at:at + 8].split(b"\0", 1)[0].decode("ascii")
                        vsize, vaddr, _rsize, _rptr, _, _, _, _, chars = struct.unpack_from("<IIIIIIHHI", raw, at + 8)
                        self.assertEqual(vsize, 0, f"{target}/{label} {nm} COFF .obj VirtualSize must be 0")
                        if nm == ".text":
                            self.assertEqual(chars, 0x60500020, f"{target}/{label} .text chars {hex(chars)}")
                        elif nm == ".data":
                            self.assertEqual(chars, 0xC0400040, f"{target}/{label} .data chars {hex(chars)}")
                    # At least one .text function symbol must carry IMAGE_SYM_DTYPE_FUNCTION (0x20).
                    fn_types = []
                    for si in range(nsyms):
                        _, secnum, stype = struct.unpack_from("<IHH", raw, symoff + si * 18 + 8)
                        if secnum == 1:
                            fn_types.append(stype)
                    self.assertIn(0x20, fn_types, f"{target}/{label} missing IMAGE_SYM_DTYPE_FUNCTION")
                    if self.readobj:
                        res = subprocess.run([self.readobj, "--file-headers", "--sections", "--symbols", str(out_o)],
                                             capture_output=True, text=True)
                        self.assertEqual(res.returncode, 0, res.stderr)

            # 3. macOS / iOS Mach-O .o (built-in _macho_o, _ios_o, _ios_sim_o + scripts/xuobj_to_macho_o.py)
            for target in ("macos-arm64", "macos-x64"):
                xuobj = self.build(work, APP_SOURCE, target, f"app_{target}.xuobj", ["--emit-obj"])
                cmds = [
                    ("builtin", [str(self.compiler), "_macho_o", str(xuobj)], 1),
                    ("script", [sys.executable, str(ROOT / "scripts/xuobj_to_macho_o.py"), str(xuobj)], 1),
                ]
                if target == "macos-arm64":
                    cmds.append(("ios", [str(self.compiler), "_ios_o", str(xuobj)], 2))
                    cmds.append(("ios_sim", [str(self.compiler), "_ios_sim_o", str(xuobj)], 7))
                for label, cmd, expected_plat in cmds:
                    out_o = work / f"app_{target}_{label}.o"
                    subprocess.run([*cmd, str(out_o)], env=env, check=True, capture_output=True, text=True)
                    raw = out_o.read_bytes()
                    magic, _, _, ftype, ncmds = struct.unpack_from("<IIIII", raw, 0)
                    self.assertEqual(magic, 0xFEEDFACF)
                    self.assertEqual(ftype, 1)  # MH_OBJECT
                    off = 32
                    seen_build = None
                    sects = {}
                    for _ in range(ncmds):
                        cmd_id, cmd_sz = struct.unpack_from("<II", raw, off)
                        if cmd_id == 0x19:
                            nsects = struct.unpack_from("<I", raw, off + 64)[0]
                            for si in range(nsects):
                                so = off + 72 + si * 80
                                sname = raw[so:so + 16].split(b"\0", 1)[0].decode("ascii")
                                addr, size, foff, align_p2 = struct.unpack_from("<QQII", raw, so + 32)
                                sects[sname] = (addr, size, foff, align_p2)
                        elif cmd_id == 0x32:
                            seen_build = struct.unpack_from("<IIII", raw, off + 8)
                        off += cmd_sz
                    self.assertIsNotNone(seen_build)
                    self.assertEqual(seen_build[0], expected_plat)
                    self.assertEqual(sects["__text"][3], 4, f"{target}/{label} __text should be 16B aligned (2^4)")
                    self.assertEqual(sects["__text"][2] % 16, 0)
                    if "__data" in sects:
                        self.assertEqual(sects["__data"][0], sects["__data"][2] - sects["__text"][2])
                    if self.readobj:
                        res = subprocess.run([self.readobj, "--file-headers", "--sections", "--symbols", str(out_o)],
                                             capture_output=True, text=True)
                        self.assertEqual(res.returncode, 0, res.stderr)


if __name__ == "__main__":
    unittest.main()
