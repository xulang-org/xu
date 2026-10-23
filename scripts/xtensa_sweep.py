#!/usr/bin/env python3
"""Systematically derive Xtensa (LX6) encodings by sweeping operands.

One oracle data point is not enough to infer a field layout -- SLLI and SRLI
already differ in how the shift amount is biased. So sweep every operand and
print byte/field relationships, then encode the observed rule in the Xu
assembler.

Usage:  xtensa_sweep.py [mnemonic ...]     (default: all supported families)
"""
import subprocess
import sys
import glob
import os
import pathlib


def _find_toolchain():
    roots = [
        pathlib.Path("~/.espressif/tools/xtensa-esp32-elf").expanduser(),
        pathlib.Path("~/esp/esp-idf/tools/xtensa-esp32-elf").expanduser(),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for sub in [root, *sorted(p for p in root.iterdir() if p.is_dir())]:
            b = sub / "xtensa-esp32-elf" / "bin"
            if (b / "xtensa-esp32-elf-as").is_file():
                return str(b) + "/xtensa-esp32-elf-"
    sys.exit("xtensa toolchain not found")


BIN = _find_toolchain()


def enc(src_lines, force_narrow=False):
    """Assemble and return (bytes, mnemonic-shown-by-objdump) or (None, err)."""
    body = "\n".join(src_lines)
    open("/tmp/xt/sweep.S", "w").write(
        "\t.section .text\n\t.global t\nt:\n" +
        "".join(f"\t{l}\n" for l in body.split("\n")))
    r = subprocess.run([BIN + "as", "-o", "/tmp/xt/sweep.o",
                        "/tmp/xt/sweep.S"], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr.strip()
    c = subprocess.run([BIN + "objcopy", "-O", "binary", "-j", ".text",
                        "/tmp/xt/sweep.o", "/tmp/xt/sweep.bin"],
                       capture_output=True, text=True)
    if c.returncode != 0:
        return None, c.stderr.strip()
    data = open("/tmp/xt/sweep.bin", "rb").read()
    d = subprocess.run([BIN + "objdump", "-d", "/tmp/xt/sweep.o"],
                       capture_output=True, text=True).stdout
    mnem = ""
    for line in d.split("\n"):
        if ":\t" in line:
            mnem = line.split(":\t")[1].split("\t")[-1].strip()
            break
    return data, mnem


def hx(b):
    return " ".join(f"{x:02x}" for x in b)


def sweep(title, mk, values, note=""):
    print(f"\n=== {title} ===" + (f"  ({note})" if note else ""))
    print(f"  {'value':<16} {'bytes':<14} mnemonic")
    for v in values:
        data, info = enc(mk(v))
        if data is None:
            print(f"  {str(v):<16} UNSUPPORTED   {info.splitlines()[0][:60] if info else ''}")
        else:
            print(f"  {str(v):<16} {hx(data):<14} {info}")


R = "a10"   # r / dest
S = "a9"    # s / src


def main():
    want = set(sys.argv[1:])

    if not want or "shift" in want:
        sweep("SLLI (variable)", lambda v: [f"slli {R}, {S}, {v}"],
              [1, 2, 3, 4, 5, 6, 7, 8, 12, 15, 16, 17, 20, 24, 30, 31])
        sweep("SRLI", lambda v: [f"srli {R}, {S}, {v}"],
              [1, 2, 3, 4, 5, 6, 7, 8, 12, 15, 16, 17, 20, 24, 30, 31])
        sweep("SRAI", lambda v: [f"srai {R}, {S}, {v}"],
              [1, 2, 3, 4, 5, 6, 7, 8, 12, 15, 16, 17, 20, 24, 30, 31])

    if not want or "addi" in want:
        sweep("ADDI imm range", lambda v: [f"addi {R}, {S}, {v}"],
              [0, 1, 6, 7, 8, 15, 16, 31, 63, 64, 100, 126, 127, -1, -7, -8, -128])

    if not want or "reg" in want:
        sweep("register field (mov.n)", lambda v: [f"mov.n a2, a{v}"],
              [2, 3, 5, 7, 9, 12, 13, 15])

    if not want or "branch" in want:
        sweep("branch offset (beq)", lambda v: [f"beq {S}, a8, .{v}", f".{v}:"],
              [8, 16, 24, 32])
        sweep("branch immediate", lambda v: [f"beqi {S}, {v}, 1f", "1:"],
              [0, 1, 4, 8, 16, 31, 32, 64, 100, 200, 255])

    if not want or "mem" in want:
        sweep("load/store offset", lambda v: [f"l32i {R}, {S}, {v}"],
              [0, 4, 8, 64, 252, 256, 508, 1020])
        sweep("byte/half load", lambda v: [f"l8ui {R}, {S}, {v}"],
              [0, 1, 2, 3, 510])

    if not want or "mul" in want:
        sweep("mul family", lambda v: [f"{v} {R}, {S}, a8"],
              ["mull", "mulsh", "muluh", "mul16u", "mul16s"])

    return 0


if __name__ == "__main__":
    sys.exit(main())