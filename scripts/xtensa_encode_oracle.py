#!/usr/bin/env python3
"""Extract Xtensa (ESP32 LX6) encodings from the official GNU assembler.

Two things make this fiddly and both matter for the backend:

  * GNU as silently narrows wide instructions (`addi` -> `addi.n`,
    `retw` -> `retw.n`). To see the wide form we must force it with `.insn`.
  * objdump prints 16-bit *words*, not a byte stream. A 3-byte instruction
    shows as six hex digits and straddles a word boundary.

Output is the exact byte sequence (little-endian), which is what the Xu
assembler must reproduce.
"""
import subprocess
import sys

import glob
import os


def _find_toolchain():
    """Locate xtensa-esp32-elf-{as,objdump}.

    Note: glob() skips dot-prefixed path components, so ~/.espressif never
    matches a pattern -- walk explicitly instead.
    """
    import pathlib
    roots = [
        pathlib.Path("~/.espressif/tools/xtensa-esp32-elf").expanduser(),
        pathlib.Path("~/esp/esp-idf/tools/xtensa-esp32-elf").expanduser(),
        pathlib.Path("~/.espressif/tools").expanduser(),
        pathlib.Path("~/esp/esp-idf/tools").expanduser(),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for sub in [root, *sorted(p for p in root.iterdir() if p.is_dir())]:
            bindir = sub / "xtensa-esp32-elf" / "bin"
            if (bindir / "xtensa-esp32-elf-as").is_file():
                return str(bindir) + "/xtensa-esp32-elf-"
    from shutil import which
    w = which("xtensa-esp32-elf-as")
    if w:
        return w[:-len("as")]
    sys.exit("xtensa toolchain not found; source esp-idf/export.sh first")


BIN = _find_toolchain()
AS = BIN + "as"
OBJDUMP = BIN + "objdump"

WIDE = True   # force the 3-byte form via .insn


def run(body, force_wide):
    src = "\t.section .text\n\t.global t\nt:\n"
    for line in body.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":"):
            src += line + "\n"
        else:
            src += "\t" + line + "\n"
    open("/tmp/xt/one.S", "w").write(src)
    r = subprocess.run([AS, "-o", "/tmp/xt/one.o", "/tmp/xt/one.S"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        msg = [l for l in r.stderr.strip().split("\n") if "Error" in l]
        return None, (msg[0].split("Error: ")[-1] if msg else "error")
    d = subprocess.run([OBJDUMP, "-d", "/tmp/xt/one.o"],
                       capture_output=True, text=True).stdout
    data = bytearray()
    seen = False
    for line in d.split("\n"):
        if ":\t" not in line:
            continue
        seen = True
        for tok in line.split(":\t", 1)[1].split("\t")[0].split():
            if tok and len(tok) in (2, 4, 6) and \
               all(c in "0123456789abcdef" for c in tok):
                data += int(tok, 16).to_bytes(len(tok) // 2, "little")
    if not seen:
        return None, "no instructions"
    return bytes(data), None


def probe(label, body):
    data, err = run(body, WIDE)
    if data is None:
        return (label, None, err)
    return (label, " ".join(f"{b:02x}" for b in data), None)


# (label, source, want_wide)
CASES = [
    ("addi.n a5, a4, 12",        "addi.n a5, a4, 12", False),
    ("addi a5, a4, 12",          "addi a5, a4, 12", True),
    ("addi a2, a1, -1",          "addi a2, a1, -1", True),
    ("addmi a2, a1, 32",         "addmi a2, a1, 32", True),
    ("add.n a3, a2, a1",         "add.n a3, a2, a1", False),
    ("add a4, a2, a3",           "add a4, a2, a3", True),
    ("sub a4, a3, a2",           "sub a4, a3, a2", True),
    ("and a4, a2, a3",           "and a4, a2, a3", True),
    ("or a4, a2, a3",            "or a4, a2, a3", True),
    ("xor a4, a2, a3",           "xor a4, a2, a3", True),
    ("andi a2, a3, 0x0f",        "andi a2, a3, 0x0f", True),
    ("ori a2, a3, 0x3c",         "ori a2, a3, 0x3c", True),
    ("xori a2, a3, 0xff",        "xori a2, a3, 0xff", True),
    ("movi a2, 0x1234",          "movi a2, 0x1234", True),
    ("movi.n a2, 5",             "movi.n a2, 5", False),
    ("mov.n a2, a1",             "mov.n a2, a1", False),
    ("slli a2, a3, 4",           "slli a2, a3, 4", True),
    ("srli a2, a3, 8",           "srli a2, a3, 8", True),
    ("srai a2, a3, 2",           "srai a2, a3, 2", True),
    ("sll a2, a3, a4",           "sll a2, a3, a4", True),
    ("srl a2, a3, a4",           "srl a2, a3, a4", True),
    ("sra a2, a3, a4",           "sra a2, a3, a4", True),
    ("slli a2, a3, 31",          "slli a2, a3, 31", True),
    ("mull a3, a2, a1",          "mull a3, a2, a1", False),
    ("mulsh a3, a2, a1",         "mulsh a3, a2, a1", True),
    ("muluh a3, a2, a1",         "muluh a3, a2, a1", True),
    ("div32 a3, a2, a1",         "div32 a3, a2, a1", True),
    ("rem32 a3, a2, a1",         "rem32 a3, a2, a1", True),
    ("l32i.n a3, a2, 0",         "l32i.n a3, a2, 0", False),
    ("s32i.n a3, a2, 0",         "s32i.n a3, a2, 0", False),
    ("l32i a5, a2, 16",          "l32i a5, a2, 16", True),
    ("s32i a6, a2, 32",          "s32i a6, a2, 32", True),
    ("l8ui a7, a3, 0",           "l8ui a7, a3, 0", True),
    ("l16ui a8, a3, 4",          "l16ui a8, a3, 4", True),
    ("s8i a9, a3, 8",            "s8i a9, a3, 8", True),
    ("s16i a10, a3, 12",         "s16i a10, a3, 12", True),
    ("add.lt a2, a3, a4",        "add.lt a2, a3, a4", True),
    ("add.ge a2, a3, a4",        "add.ge a2, a3, a4", True),
    ("add.eq a2, a3, a4",        "add.eq a2, a3, a4", True),
    ("add.ne a2, a3, a4",        "add.ne a2, a3, a4", True),
    ("add.ltu a2, a3, a4",       "add.ltu a2, a3, a4", True),
    ("add.geu a2, a3, a4",       "add.geu a2, a3, a4", True),
    ("beqz.n a2, 1f\n1:",       "beqz.n a2, 1f\n1:", False),
    ("bnez.n a2, 1f\n1:",       "bnez.n a2, 1f\n1:", False),
    ("beq a2, a3, 1f\n1:",      "beq a2, a3, 1f\n1:", True),
    ("bne a2, a3, 1f\n1:",      "bne a2, a3, 1f\n1:", True),
    ("blt a2, a3, 1f\n1:",      "blt a2, a3, 1f\n1:", True),
    ("bge a2, a3, 1f\n1:",      "bge a2, a3, 1f\n1:", True),
    ("bltu a2, a3, 1f\n1:",     "bltu a2, a3, 1f\n1:", True),
    ("bgeu a2, a3, 1f\n1:",     "bgeu a2, a3, 1f\n1:", True),
    ("beqi a2, 5, 1f\n1:",      "beqi a2, 5, 1f\n1:", True),
    ("bnei a3, 7, 1f\n1:",      "bnei a3, 7, 1f\n1:", True),
    ("blti a4, -3, 1f\n1:",     "blti a4, -3, 1f\n1:", True),
    ("bgei a4, 9, 1f\n1:",      "bgei a4, 9, 1f\n1:", True),
    ("bltui a4, 3, 1f\n1:",     "bltui a4, 3, 1f\n1:", True),
    ("bgeui a4, 3, 1f\n1:",     "bgeui a4, 3, 1f\n1:", True),
    ("beqz a2, 1f\n1:",         "beqz a2, 1f\n1:", True),
    ("bnez a2, 1f\n1:",         "bnez a2, 1f\n1:", True),
    ("j 1f\n1:",                "j 1f\n1:", False),
    ("j 1f\n1: (wide .insn)",   "j 1f\n1:", True),
    ("jx a2",                   "jx a2", True),
    ("callx0 a2",               "callx0 a2", True),
    ("retw.n",                  "retw.n", False),
    ("retw",                    "retw", True),
    ("entry a1, 16",            "entry a1, 16", False),
    ("entry a1, 32",            "entry a1, 32", False),
    ("movf a3",                 "movf a3", False),
    ("movf.n a3",               "movf.n a3", False),
    ("nop",                     "nop", False),
    ("rsil a2, 5",              "rsil a2, 5", True),
    ("wsr.psr a2",              "wsr.psr a2", True),
    ("rsr.psr a2",              "rsr.psr a2", True),
    ("l32r a2, lit\n.lit",      "l32r a2, lit\n.literal lit", True),
    ("ret0 (NOT on LX6)",       "ret0", False),
    ("sub.n (NOT on LX6)",      "sub.n a2, a1, a3", False),
    ("abs (NOT on LX6)",        "abs a2", False),
]


def main():
    w = max(len(c[0]) for c in CASES) + 2
    print(f"{'instruction':<{w}} {'encoding (LE bytes)':<26}")
    print("-" * (w + 28))
    ok = 0
    for label, body, wide in CASES:
        global WIDE
        WIDE = wide
        data, err = run(body, wide)
        if data is None:
            print(f"{label:<{w}} UNSUPPORTED  {err}")
        else:
            ok += 1
            print(f"{label:<{w}} {' '.join(f'{b:02x}' for b in data):<26}")
    print(f"\n{ok}/{len(CASES)} assembled successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())