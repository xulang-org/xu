#!/usr/bin/env python3
"""Verify hardened Linux ELF64 output (W^X, PIE, Full RELRO, NX stack, section headers).

Covers both static Linux PIE (!uses_ffi) and dynamic Linux PIE (uses_ffi + C FFI
calls + C-to-Xu callbacks) across all four Linux 64-bit targets, plus live
execution and /proc/self/maps verification when Docker is available.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

PT_LOAD = 1
PT_DYNAMIC = 2
PT_INTERP = 3
PT_NOTE = 4
PT_PHDR = 6
PT_GNU_STACK = 0x6474E551
PT_GNU_RELRO = 0x6474E552
PT_GNU_PROPERTY = 0x6474E553

SHT_NOTE = 7
NT_GNU_BUILD_ID = 3
NT_GNU_PROPERTY_TYPE_0 = 5

PF_X = 1
PF_W = 2
PF_R = 4

ET_EXEC = 2
ET_DYN = 3

DT_NULL = 0
DT_FLAGS = 30
DT_FLAGS_1 = 0x6FFFFFFB

DF_BIND_NOW = 8
DF_1_NOW = 1
DF_1_PIE = 0x08000000

LINUX_TARGETS = (
    ("linux-x64", 62, 4096),
    ("linux-arm64", 183, 65536),
    ("linux-riscv64", 243, 4096),
    ("linux-loongarch64", 258, 65536),
)

STATIC_SOURCE = r'''@main
#os
fn main() int {
    maps := os.read("/proc/self/maps") >>> (err) {
        println("NO_MAPS")
        << 0
    }
    println("STATIC_OK")
    println(maps)
    << 0
}
'''

FFI_SOURCE = r'''@main
#ffi
#os

extern "C" {
    fn c_abs(v c_int) c_int = "abs"
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
    $abs_val := 0
    $s0 := 0
    $s1 := 0
    $s2 := 0
    $s3 := 0
    unsafe {
        abs_val = int(c_abs(i32(-42)))
        buf := ffi.malloc(16)
        if ffi.is_null(buf) { << 2 }
        ffi.write_i32(buf, 0, i32(30))
        ffi.write_i32(buf, 4, i32(10))
        ffi.write_i32(buf, 8, i32(40))
        ffi.write_i32(buf, 12, i32(20))
        c_qsort(buf, u64(4), u64(4), cmp_i32)
        s0 = int(ffi.read_i32(buf, 0))
        s1 = int(ffi.read_i32(buf, 4))
        s2 = int(ffi.read_i32(buf, 8))
        s3 = int(ffi.read_i32(buf, 12))
        ffi.free(buf)
    }
    if abs_val != 42 { << 3 }
    if s0 != 10 || s1 != 20 || s2 != 30 || s3 != 40 { << 4 }
    println("FFI_OK " + str(abs_val) + " " + str(s0) + "," + str(s1) + "," + str(s2) + "," + str(s3))
    maps := os.read("/proc/self/maps") >>> (err) { << 5 }
    println(maps)
    << 0
}
'''

BAREMETAL_SOURCE = r'''@main
fn main() int {
    << 0
}
'''


def find_compiler() -> Path:
    env_xu = os.environ.get("XU", "").strip()
    if env_xu:
        return Path(env_xu).resolve()
    return (ROOT / "bin" / "xu").resolve()


def find_readelf() -> str | None:
    for cand in (
        shutil.which("llvm-readelf"),
        shutil.which("readelf"),
        "/opt/homebrew/opt/llvm/bin/llvm-readelf",
    ):
        if cand and Path(cand).is_file():
            return cand
    cellar = Path("/opt/homebrew/Cellar/llvm")
    if cellar.is_dir():
        for bin_path in sorted(cellar.glob("*/bin/llvm-readelf"), reverse=True):
            return str(bin_path)
    return None


def parse_elf64(data: bytes) -> dict:
    assert len(data) >= 64 and data[:6] == b"\x7fELF\x02\x01", "not ELF64 LE"
    (
        e_type,
        e_machine,
        e_version,
        e_entry,
        e_phoff,
        e_shoff,
        e_flags,
        e_ehsize,
        e_phentsize,
        e_phnum,
        e_shentsize,
        e_shnum,
        e_shstrndx,
    ) = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    assert e_version == 1 and e_ehsize == 64 and e_phentsize == 56 and e_shentsize == 64

    phdrs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from(
            "<IIQQQQQQ", data, off
        )
        phdrs.append(
            {
                "type": p_type,
                "flags": p_flags,
                "offset": p_offset,
                "vaddr": p_vaddr,
                "paddr": p_paddr,
                "filesz": p_filesz,
                "memsz": p_memsz,
                "align": p_align,
            }
        )

    shdrs = []
    if e_shnum > 0:
        assert e_shoff > 0 and e_shoff + e_shnum * e_shentsize <= len(data)
        assert 0 < e_shstrndx < e_shnum
        raw_shdrs = []
        for i in range(e_shnum):
            off = e_shoff + i * e_shentsize
            raw_shdrs.append(struct.unpack_from("<IIQQQQIIQQ", data, off))
        shstr_off = raw_shdrs[e_shstrndx][4]
        shstr_sz = raw_shdrs[e_shstrndx][5]
        shstr = data[shstr_off : shstr_off + shstr_sz]
        for sh in raw_shdrs:
            name_off = sh[0]
            end = shstr.index(b"\x00", name_off)
            shdrs.append(
                {
                    "name": shstr[name_off:end].decode("ascii"),
                    "type": sh[1],
                    "flags": sh[2],
                    "addr": sh[3],
                    "offset": sh[4],
                    "size": sh[5],
                    "link": sh[6],
                    "info": sh[7],
                    "align": sh[8],
                    "entsize": sh[9],
                }
            )

    dyn = []
    for p in phdrs:
        if p["type"] == PT_DYNAMIC:
            for pos in range(p["offset"], p["offset"] + p["filesz"], 16):
                tag, val = struct.unpack_from("<QQ", data, pos)
                dyn.append((tag, val))
                if tag == DT_NULL:
                    break

    return {
        "type": e_type,
        "machine": e_machine,
        "entry": e_entry,
        "phoff": e_phoff,
        "shoff": e_shoff,
        "flags": e_flags,
        "phdrs": phdrs,
        "shdrs": shdrs,
        "dyn": dyn,
    }


def docker_image_available(image: str, platform: str) -> bool:
    if not shutil.which("docker"):
        return False
    res = subprocess.run(
        ["docker", "run", "--rm", "--pull=never", "--platform", platform, image, "/bin/true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return res.returncode == 0


class ElfHardeningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compiler = find_compiler()
        cls.readelf = find_readelf()

    def build(self, work: Path, source: str, target: str, name: str, extra: list[str] | None = None) -> Path:
        src = work / f"{name}.xu"
        out = work / name
        src.write_text(source)
        env = {k: v for k, v in os.environ.items() if not k.startswith("XU")}
        env.update(XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / "src"), XUPATH="", XU_CACHE=str(work / "cache"))
        cmd = [str(self.compiler), "build", str(src), "--target", target, *(extra or []), "-o", str(out)]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"build failed for {target}/{name}:\n{res.stdout}\n{res.stderr}")
        return out

    def check_common_hardening(self, path: Path, machine: int, page: int, dynamic: bool, dwarf: bool) -> dict:
        data = path.read_bytes()
        info = parse_elf64(data)
        self.assertEqual(info["type"], ET_DYN, f"{path}: expected ET_DYN (PIE)")
        self.assertEqual(info["machine"], machine)
        self.assertEqual(info["phoff"], 64)

        loads = [p for p in info["phdrs"] if p["type"] == PT_LOAD]
        self.assertEqual(len(loads), 3 if dynamic else 2)

        # Strictly ascending vaddrs, page congruence, no RWX, no virtual page overlap.
        prev_page_end = -1
        for seg in loads:
            self.assertFalse((seg["flags"] & PF_W) and (seg["flags"] & PF_X), f"RWX PT_LOAD: {seg}")
            self.assertEqual(seg["align"], page)
            self.assertEqual(seg["offset"] % page, seg["vaddr"] % page, f"bad congruence: {seg}")
            self.assertLessEqual(seg["filesz"], seg["memsz"])
            self.assertLessEqual(seg["offset"] + seg["filesz"], len(data))
            seg_page_start = seg["vaddr"] & ~(page - 1)
            seg_page_end = (seg["vaddr"] + seg["memsz"] + page - 1) & ~(page - 1)
            self.assertGreaterEqual(seg_page_start, prev_page_end, f"overlapping PT_LOAD pages: {loads}")
            prev_page_end = seg_page_end

        self.assertEqual(loads[0]["flags"], PF_R)
        self.assertEqual(loads[1]["flags"], PF_R | PF_X)
        self.assertGreaterEqual(info["entry"], loads[1]["vaddr"])
        self.assertLess(info["entry"], loads[1]["vaddr"] + loads[1]["memsz"])

        # Non-executable GNU_STACK.
        stacks = [p for p in info["phdrs"] if p["type"] == PT_GNU_STACK]
        self.assertEqual(len(stacks), 1)
        self.assertEqual(stacks[0]["flags"], PF_R | PF_W)

        # PT_GNU_RELRO + Full RELRO dynamic flags (DF_BIND_NOW, DF_1_NOW | DF_1_PIE).
        relros = [p for p in info["phdrs"] if p["type"] == PT_GNU_RELRO]
        self.assertEqual(len(relros), 1)
        relro = relros[0]
        self.assertEqual((relro["vaddr"] + relro["memsz"]) % page, 0, "PT_GNU_RELRO end must be page-aligned")
        # PT_GNU_RELRO must be strictly contained within a PT_LOAD segment (eu-elflint / ld.so invariant).
        self.assertTrue(
            any(
                seg["vaddr"] <= relro["vaddr"]
                and relro["vaddr"] + relro["memsz"] <= seg["vaddr"] + seg["memsz"]
                for seg in loads
            ),
            f"PT_GNU_RELRO {relro} not strictly contained in any PT_LOAD {loads}",
        )
        dyn_map = dict(info["dyn"])
        self.assertEqual(dyn_map.get(DT_FLAGS, 0) & DF_BIND_NOW, DF_BIND_NOW)
        self.assertEqual(dyn_map.get(DT_FLAGS_1, 0) & (DF_1_NOW | DF_1_PIE), DF_1_NOW | DF_1_PIE)

        sec_by_name = {s["name"]: s for s in info["shdrs"]}
        self.assertGreater(len(info["shdrs"]), 0, "expected Section Header Table")
        self.assertIn(".note.gnu.build-id", sec_by_name)
        self.assertIn(".text", sec_by_name)
        self.assertIn(".dynamic", sec_by_name)
        self.assertIn(".shstrtab", sec_by_name)

        # Deterministic 20-byte GNU Build-ID (PT_NOTE + SHT_NOTE).
        notes = [p for p in info["phdrs"] if p["type"] == PT_NOTE]
        self.assertEqual(len(notes), 1)
        note_ph = notes[0]
        note_sec = sec_by_name[".note.gnu.build-id"]
        self.assertEqual(note_ph["flags"], PF_R)
        self.assertEqual(note_ph["align"], 4)
        self.assertEqual(note_ph["filesz"], 36)
        self.assertEqual(note_ph["memsz"], 36)
        self.assertEqual(note_sec["type"], SHT_NOTE)
        self.assertEqual(note_sec["addr"], note_ph["vaddr"])
        self.assertEqual(note_sec["offset"], note_ph["offset"])
        self.assertEqual(note_sec["size"], 36)
        namesz, descsz, ntype = struct.unpack_from("<III", data, note_sec["offset"])
        self.assertEqual((namesz, descsz, ntype), (4, 20, NT_GNU_BUILD_ID))
        self.assertEqual(data[note_sec["offset"] + 12 : note_sec["offset"] + 16], b"GNU\x00")
        build_id = data[note_sec["offset"] + 16 : note_sec["offset"] + 36]
        self.assertTrue(any(build_id), "expected non-zero Build-ID")

        # Hardware CFI: Intel CET IBT (x86_64) & ARM64 BTI (aarch64) via PT_GNU_PROPERTY.
        props = [p for p in info["phdrs"] if p["type"] == PT_GNU_PROPERTY]
        if machine in (62, 183):
            self.assertEqual(len(props), 1)
            prop_ph = props[0]
            self.assertEqual(prop_ph["flags"], PF_R)
            self.assertEqual(prop_ph["align"], 8)
            self.assertEqual(prop_ph["filesz"], 32)
            self.assertIn(".note.gnu.property", sec_by_name)
            prop_sec = sec_by_name[".note.gnu.property"]
            self.assertEqual(prop_sec["type"], SHT_NOTE)
            self.assertEqual(prop_sec["align"], 8)
            self.assertEqual(prop_sec["offset"], prop_ph["offset"])
            p_nsz, p_dsz, p_type = struct.unpack_from("<III", data, prop_sec["offset"])
            self.assertEqual((p_nsz, p_dsz, p_type), (4, 16, NT_GNU_PROPERTY_TYPE_0))
            self.assertEqual(data[prop_sec["offset"] + 12 : prop_sec["offset"] + 16], b"GNU\x00")
            pr_type, pr_datasz, pr_val = struct.unpack_from("<III", data, prop_sec["offset"] + 16)
            expected_pr_type = 0xC0000002 if machine == 62 else 0xC0000000
            self.assertEqual((pr_type, pr_datasz, pr_val), (expected_pr_type, 4, 1))
            entry_file_off = loads[1]["offset"] + (info["entry"] - loads[1]["vaddr"])
            expected_pad = b"\xf3\x0f\x1e\xfa" if machine == 62 else b"\xdf\x24\x03\xd5"
            self.assertEqual(data[entry_file_off : entry_file_off + 4], expected_pad, "missing CET/BTI landing pad at e_entry")
        else:
            self.assertEqual(len(props), 0)

        if dwarf:
            for dsec in (".debug_line", ".debug_info", ".debug_abbrev", ".debug_str"):
                self.assertIn(dsec, sec_by_name)
        else:
            self.assertNotIn(".debug_info", sec_by_name)

        if dynamic:
            self.assertEqual(loads[2]["flags"], PF_R | PF_W)
            self.assertEqual(relro["vaddr"], loads[2]["vaddr"])
            self.assertGreater(loads[2]["memsz"], relro["memsz"], ".bss must follow PT_GNU_RELRO")
            for req in (".interp", ".hash", ".dynsym", ".dynstr", ".rela.dyn", ".got", ".bss"):
                self.assertIn(req, sec_by_name)
            got = sec_by_name[".got"]
            bss = sec_by_name[".bss"]
            dyn_sec = sec_by_name[".dynamic"]
            relro_end = relro["vaddr"] + relro["memsz"]
            self.assertGreaterEqual(dyn_sec["addr"], relro["vaddr"])
            self.assertLessEqual(dyn_sec["addr"] + dyn_sec["size"], relro_end)
            self.assertGreaterEqual(got["addr"], relro["vaddr"])
            self.assertLessEqual(got["addr"] + got["size"], relro_end)
            # __xu_ffi_state (.bss) MUST start on/after relro_end so runtime stores do not SIGSEGV.
            self.assertGreaterEqual(bss["addr"], relro_end)
            # Every GLOB_DAT relocation target must land inside .got (covered by RELRO).
            rela = sec_by_name[".rela.dyn"]
            self.assertEqual(rela["size"], 3 * 24)
            for i in range(3):
                r_off, r_info, r_addend = struct.unpack_from("<QQq", data, rela["offset"] + i * 24)
                self.assertEqual(r_off, got["addr"] + i * 8)
                self.assertEqual(r_info >> 32, i + 1)
                self.assertEqual(r_addend, 0)

        if self.readelf:
            res = subprocess.run([self.readelf, "-h", "-l", "-S", "-d", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("Build ID:", res.stdout)
            if machine == 62:
                self.assertIn("IBT", res.stdout)
            elif machine == 183:
                self.assertIn("BTI", res.stdout)
            self.assertNotIn("Warning:", res.stderr)

        return info

    def test_all_linux_targets_static_and_dynamic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            for target, machine, page in LINUX_TARGETS:
                for dwarf in (False, True):
                    flags = ["-g"] if dwarf else []
                    suffix = "dbg" if dwarf else "rel"
                    st = self.build(work, STATIC_SOURCE, target, f"static_{target}_{suffix}", flags)
                    self.check_common_hardening(st, machine, page, dynamic=False, dwarf=dwarf)
                    dy = self.build(work, FFI_SOURCE, target, f"ffi_{target}_{suffix}", flags)
                    self.check_common_hardening(dy, machine, page, dynamic=True, dwarf=dwarf)

    def test_baremetal_stays_et_exec(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            bm = self.build(work, BAREMETAL_SOURCE, "x64-none", "bm_x64")
            info = parse_elf64(bm.read_bytes())
            self.assertEqual(info["type"], ET_EXEC)

    def assert_proc_maps_hardened(self, maps_text: str, bin_name: str, expect_rw_bss: bool) -> None:
        bin_lines = [line for line in maps_text.splitlines() if line.endswith("/" + bin_name)]
        self.assertGreaterEqual(len(bin_lines), 2, f"missing mappings for {bin_name}:\n{maps_text}")
        bases = []
        perms = []
        for line in bin_lines:
            parts = line.split()
            start = int(parts[0].split("-")[0], 16)
            perm = parts[1]
            bases.append(start)
            perms.append(perm)
            self.assertNotIn("rwx", perm, f"RWX mapping found: {line}")
        # PIE ASLR: must not load at legacy fixed 0x400000.
        self.assertNotEqual(min(bases), 0x400000, f"loaded at fixed 0x400000:\n{maps_text}")
        self.assertIn("r--p", perms, f"missing R-- mapping:\n{maps_text}")
        self.assertIn("r-xp", perms, f"missing R-X mapping:\n{maps_text}")
        if expect_rw_bss:
            rx_idx = perms.index("r-xp")
            self.assertIn("r--p", perms[rx_idx + 1 :], f"RELRO page not mprotected R--:\n{maps_text}")

    def test_docker_linux_execution_and_maps(self) -> None:
        if platform.system() == "Linux":
            mach = platform.machine().lower()
            host_target = "linux-x64" if mach in ("x86_64", "amd64") else ("linux-arm64" if mach in ("aarch64", "arm64") else "")
            if host_target:
                with tempfile.TemporaryDirectory() as td:
                    work = Path(td)
                    st = self.build(work, STATIC_SOURCE, host_target, f"run_static_{host_target}")
                    st_res = subprocess.run([str(st)], capture_output=True, text=True, timeout=30)
                    self.assertEqual(st_res.returncode, 0, f"{host_target} static failed:\n{st_res.stdout}\n{st_res.stderr}")
                    self.assertIn("STATIC_OK", st_res.stdout)
                    self.assert_proc_maps_hardened(st_res.stdout, st.name, expect_rw_bss=False)

                    dy = self.build(work, FFI_SOURCE, host_target, f"run_ffi_{host_target}")
                    dy_res = subprocess.run([str(dy)], capture_output=True, text=True, timeout=30)
                    self.assertEqual(dy_res.returncode, 0, f"{host_target} ffi failed:\n{dy_res.stdout}\n{dy_res.stderr}")
                    self.assertIn("FFI_OK 42 10,20,30,40", dy_res.stdout)
                    self.assert_proc_maps_hardened(dy_res.stdout, dy.name, expect_rw_bss=True)
                return

        lanes = [
            ("linux-x64", "linux/amd64", "ubuntu:22.04"),
            ("linux-arm64", "linux/arm64", "ubuntu:latest"),
        ]
        ran_any = False
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            for target, docker_platform, image in lanes:
                if not docker_image_available(image, docker_platform):
                    continue
                ran_any = True
                st = self.build(work, STATIC_SOURCE, target, f"run_static_{target}")
                st_res = subprocess.run(
                    ["docker", "run", "--rm", "--pull=never", "--platform", docker_platform, "-v", f"{work}:/w", image, f"/w/{st.name}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(st_res.returncode, 0, f"{target} static failed:\n{st_res.stdout}\n{st_res.stderr}")
                self.assertIn("STATIC_OK", st_res.stdout)
                self.assert_proc_maps_hardened(st_res.stdout, st.name, expect_rw_bss=False)

                dy = self.build(work, FFI_SOURCE, target, f"run_ffi_{target}")
                dy_res = subprocess.run(
                    ["docker", "run", "--rm", "--pull=never", "--platform", docker_platform, "-v", f"{work}:/w", image, f"/w/{dy.name}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(dy_res.returncode, 0, f"{target} ffi failed:\n{dy_res.stdout}\n{dy_res.stderr}")
                self.assertIn("FFI_OK 42 10,20,30,40", dy_res.stdout)
                self.assert_proc_maps_hardened(dy_res.stdout, dy.name, expect_rw_bss=True)

        if not ran_any:
            self.skipTest("no Linux Docker runner available")


if __name__ == "__main__":
    unittest.main()
