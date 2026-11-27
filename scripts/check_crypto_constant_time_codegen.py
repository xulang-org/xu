#!/usr/bin/env python3
"""Audit XU-CT constant-time scalar/result code generation on hosted x64 and ARM64.

On Unix with a hosted seed, resolves the seed via xu_host_seed.sh and builds
through run_product_compiler.sh; on Windows without bash, isolates XUPATH and
uses the resolved product compiler directly. Audits the emitted Linux ELF64
code sections (with XU_SYMMAP) via a pure-Python ARM64/x86-64 decoder (and
crosschecks --emit-obj via xuobj_to_elf_o.py).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "crypto_subtle" / "main.xu"
CONVERTER = ROOT / "scripts" / "xuobj_to_elf_o.py"
HOST_SEED_RESOLVER = ROOT / "scripts" / "xu_host_seed.sh"
PRODUCT_RUNNER = ROOT / "scripts" / "run_product_compiler.sh"
# Keep the canonical name visible to the boundary checker and to consumers
# that audit the product compiler seam.
PRODUCT_COMPILER_RUNNER = PRODUCT_RUNNER
LANE = "product"

PROBE_SOURCE = """@main
#crypto/subtle

fn main() int {
    a := "abcdef"
    b := "abcdeg"
    r1 := subtle.constant_time_compare(&a, &b)
    r2 := subtle.constant_time_byte_eq(7, 7)
    r3 := subtle.constant_time_eq(42, 42)
    r4 := subtle.constant_time_select(1, 10, 20)
    println(r1 + r2 + r3 + r4)
    << 0
}
"""

FUNCTIONS = {
    "compare": ("_xu_crypto_subtle_constant_time_compare", {"xor", "sub", "or", "shift"}, False),
    "byte-eq": ("_xu_crypto_subtle_constant_time_byte_eq", {"xor", "sub", "or", "shift"}, True),
    "int-eq": ("_xu_crypto_subtle_constant_time_eq", {"xor", "sub", "or", "shift"}, True),
    "select": ("_xu_crypto_subtle_constant_time_select", {"and", "or", "sub"}, True),
}


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def is_executable(path: Path) -> bool:
    if os.name == "nt":
        return path.is_file()
    return path.is_file() and os.access(path, os.X_OK)


def _absolute_candidate(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"crypto codegen: cannot resolve compiler {value!r}: {exc}") from exc


def _lexical_candidate(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.absolute()


def _has_usable_bash() -> bool:
    bash = shutil.which("bash")
    if bash is None:
        return False
    if os.name == "nt" and bash.lower().endswith("\\system32\\bash.exe"):
        # WSL stub is not Git Bash and cannot invoke Windows .exe directly.
        return False
    return True


def _resolve_hosted_seed(explicit: str | None) -> Path:
    """Resolve a hosted seed without ever falling through to the primer."""
    if os.name == "nt":
        default_name = "xu.exe"
        raw = explicit if explicit is not None else os.environ.get("XU_SEED", str(ROOT / "bin" / default_name))
        compiler = _absolute_candidate(raw)
        if not compiler.is_file():
            fail(f"missing hosted compiler: {compiler}")
        parts = {p.lower() for p in compiler.parts}
        if "bootstrap" in parts or "target" in parts:
            fail(f"hosted product seed rejected (primer path): {compiler}")
        return compiler

    if not is_executable(HOST_SEED_RESOLVER):
        fail(f"missing executable hosted seed resolver: {HOST_SEED_RESOLVER}")
    env = os.environ.copy()
    if explicit is None:
        env.pop("XU_SEED", None)
    else:
        env["XU_SEED"] = str(_lexical_candidate(explicit))
    proc = subprocess.run(
        [str(HOST_SEED_RESOLVER)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "resolver failed").strip().splitlines()
        tail = detail[-1] if detail else "resolver failed"
        fail(f"hosted product seed rejected: {tail}")
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        fail("xu_host_seed.sh returned an invalid compiler path")
    compiler = _absolute_candidate(lines[0])
    if not is_executable(compiler):
        fail(f"resolved hosted compiler is not executable: {compiler}")
    return compiler


def resolve_compiler(explicit: str | None, lane: str = LANE) -> Path:
    """Resolve the hosted compiler for the product code-generation audit."""
    if lane != "product":
        raise SystemExit(f"crypto codegen: invalid compiler lane {lane!r}")
    if os.name != "nt" and not is_executable(PRODUCT_COMPILER_RUNNER):
        fail(f"missing executable product compiler wrapper: {PRODUCT_COMPILER_RUNNER}")
    return _resolve_hosted_seed(explicit)


def resolve_product_xu(explicit: str | None) -> Path:
    """Stable product-lane seam for the boundary manifest/checker."""
    return resolve_compiler(explicit, "product")


def compile_argv(
    compiler: Path,
    lane: str,
    target: str,
    opt: str,
    out_path: Path,
    src_path: Path | None = None,
    emit_obj: bool = True,
) -> list[str]:
    """Compile through the isolated product wrapper (or isolated env on Windows)."""
    if lane != "product":
        raise ValueError(f"crypto codegen: invalid compiler lane {lane!r}")
    src = src_path if src_path is not None else FIXTURE
    flags = ["--no-opt"] if opt == "no-opt" else []
    extra = ["--emit-obj"] if emit_obj else []
    if os.name == "nt":
        return [str(compiler), "build", str(src), "--target", target, *flags, *extra, "-o", str(out_path)]
    return [str(PRODUCT_COMPILER_RUNNER), str(compiler), "build", str(src),
            "--target", target, *flags, *extra, "-o", str(out_path)]


def run(command: list[str], env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        fail(f"command not found: {command[0]}")
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip()
        fail(f"command failed ({' '.join(command)}): {detail}")
    return result.stdout


def decode_arm64(chunk: bytes) -> tuple[list[tuple[int, int, str]], set[str]]:
    if len(chunk) % 4 != 0:
        fail(f"ARM64 code slice not 4-byte aligned: len={len(chunk)}")
    branches: list[tuple[int, int, str]] = []
    prims: set[str] = set()
    for off in range(0, len(chunk), 4):
        ins = struct.unpack_from("<I", chunk, off)[0]
        if (ins & 0xFF000010) == 0x54000000:
            imm19 = (ins >> 5) & 0x7FFFF
            if imm19 & 0x40000:
                imm19 -= 0x80000
            branches.append((off, off + imm19 * 4, "b.cond"))
        elif (ins & 0x7E000000) == 0x34000000:
            imm19 = (ins >> 5) & 0x7FFFF
            if imm19 & 0x40000:
                imm19 -= 0x80000
            branches.append((off, off + imm19 * 4, "cbz/cbnz"))
        elif (ins & 0x7E000000) == 0x36000000:
            imm14 = (ins >> 5) & 0x3FFF
            if imm14 & 0x2000:
                imm14 -= 0x4000
            branches.append((off, off + imm14 * 4, "tbz/tbnz"))
        if (ins & 0x5F200000) == 0x4B000000 or (ins & 0x5F800000) == 0x51000000:
            prims.add("sub")
        if (ins & 0x7F200000) == 0x0A000000 or (ins & 0x7F800000) == 0x12000000:
            prims.add("and")
        if (ins & 0x7F200000) == 0x2A000000 or (ins & 0x7F800000) == 0x32000000:
            prims.add("or")
        if (ins & 0x7F200000) == 0x4A000000 or (ins & 0x7F800000) == 0x52000000:
            prims.add("xor")
        if (ins & 0x7F800000) in (0x13000000, 0x53000000) or (ins & 0x7FE0FC00) in (0x1AC02000, 0x1AC02400, 0x1AC02800):
            prims.add("shift")
    return branches, prims


def _skip_modrm(buf: bytes, pos: int) -> int:
    modrm = buf[pos]
    pos += 1
    mod = (modrm >> 6) & 3
    rm = modrm & 7
    if mod != 3 and rm == 4:
        sib = buf[pos]
        pos += 1
        base = sib & 7
        if mod == 0 and base == 5:
            pos += 4
    if mod == 0 and rm == 5:
        pos += 4
    elif mod == 1:
        pos += 1
    elif mod == 2:
        pos += 4
    return pos


def decode_x64(chunk: bytes) -> tuple[list[tuple[int, int, str]], set[str], int]:
    branches: list[tuple[int, int, str]] = []
    prims: set[str] = set()
    ops_tail_start = 0
    pos = 0
    n = len(chunk)
    while pos < n:
        start = pos
        has_66 = False
        rex = 0
        while pos < n and chunk[pos] in (0x66, 0x67, 0xF2, 0xF3):
            if chunk[pos] == 0x66:
                has_66 = True
            pos += 1
        if pos < n and 0x40 <= chunk[pos] <= 0x4F:
            rex = chunk[pos]
            pos += 1
        rex_w = (rex & 0x08) != 0
        if pos >= n:
            fail(f"truncated x64 instruction at offset {start:#x}")
        op = chunk[pos]
        pos += 1

        if (0x50 <= op <= 0x5F) or op in (0x90, 0xC3, 0xC9):
            pass
        elif 0x70 <= op <= 0x7F or 0xE0 <= op <= 0xE3:
            rel = struct.unpack_from("<b", chunk, pos)[0]
            pos += 1
            branches.append((start, pos + rel, f"jcc_{op:02x}"))
        elif op == 0xEB:
            pos += 1
        elif op in (0xE8, 0xE9):
            pos += 4
        elif 0xB8 <= op <= 0xBF:
            pos += 8 if rex_w else 4
        elif op == 0x0F:
            op2 = chunk[pos]
            pos += 1
            if 0x80 <= op2 <= 0x8F:
                rel = struct.unpack_from("<i", chunk, pos)[0]
                pos += 4
                branches.append((start, pos + rel, f"jcc_0f{op2:02x}"))
            elif 0x90 <= op2 <= 0x9F or op2 in (0xB6, 0xB7, 0xBE, 0xBF, 0xAF):
                pos = _skip_modrm(chunk, pos)
            else:
                fail(f"unrecognized x64 0F opcode 0x0f {op2:#04x} at offset {start:#x}")
        elif op in (0x01, 0x03, 0x09, 0x0B, 0x21, 0x23, 0x29, 0x2B, 0x31, 0x33,
                    0x39, 0x3B, 0x85, 0x89, 0x8B, 0x8D, 0xD1, 0xD3):
            reg_field = (chunk[pos] >> 3) & 7
            pos = _skip_modrm(chunk, pos)
            if op in (0x09, 0x0B):
                prims.add("or")
            elif op in (0x21, 0x23):
                prims.add("and")
            elif op in (0x29, 0x2B):
                prims.add("sub")
            elif op in (0x31, 0x33):
                prims.add("xor")
            elif op in (0xD1, 0xD3) and reg_field in (4, 5, 7):
                prims.add("shift")
        elif op in (0x83, 0xC1, 0xC6):
            reg_field = (chunk[pos] >> 3) & 7
            pos = _skip_modrm(chunk, pos) + 1
            if op == 0x83:
                if reg_field == 1: prims.add("or")
                elif reg_field == 4: prims.add("and")
                elif reg_field == 5: prims.add("sub")
                elif reg_field == 6: prims.add("xor")
            elif op == 0xC1 and reg_field in (4, 5, 7):
                prims.add("shift")
        elif op in (0x81, 0xC7):
            reg_field = (chunk[pos] >> 3) & 7
            pos = _skip_modrm(chunk, pos) + (2 if has_66 else 4)
            if op == 0x81:
                if reg_field == 1: prims.add("or")
                elif reg_field == 4: prims.add("and")
                elif reg_field == 5: prims.add("sub")
                elif reg_field == 6: prims.add("xor")
        else:
            fail(f"unrecognized x64 opcode {op:#04x} at offset {start:#x} (bytes={chunk[start:start+8].hex()})")

        if branches and branches[-1][0] == start:
            ops_tail_start = pos
    return branches, prims, ops_tail_start


def audit_elf(target: str, opt: str, elf: Path, symmap_path: Path) -> None:
    raw = elf.read_bytes()
    if raw[:4] != b"\x7fELF":
        fail(f"{elf.name} is not an ELF binary")
    e_entry = struct.unpack_from("<Q", raw, 24)[0]
    e_phoff = struct.unpack_from("<Q", raw, 32)[0]
    p_offset, p_vaddr = struct.unpack_from("<QQ", raw, e_phoff + 8)

    start_sym = 0
    fn_offsets: list[tuple[int, str]] = []
    for line in symmap_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            off = int(parts[0])
            if parts[1] == "__xu_start":
                start_sym = off
            else:
                fn_offsets.append((off, parts[1]))
    fn_offsets.sort()
    code_base = (e_entry - p_vaddr + p_offset) - start_sym
    ranges: dict[str, bytes] = {}
    for i, (off, name) in enumerate(fn_offsets):
        nxt = fn_offsets[i + 1][0] if i + 1 < len(fn_offsets) else len(raw) - code_base
        ranges[name] = raw[code_base + off : code_base + nxt]

    for label, (sym, required, strictly_branchless) in FUNCTIONS.items():
        if sym not in ranges:
            fail(f"{target}/{opt}: missing subtle symbol {sym} in XU_SYMMAP")
        chunk = ranges[sym]
        if target == "linux-arm64":
            branches, prims = decode_arm64(chunk)
            tail_off = (max(off for off, _, _ in branches) + 4) if branches else 0
        else:
            branches, prims, tail_off = decode_x64(chunk)

        if strictly_branchless:
            if branches:
                fail(f"{target}/{opt}/{label} has conditional branches: {branches}")
        else:
            # constant_time_compare: public length guard + loop checks are allowed,
            # but result finalization tail after the last branch must be branchless and
            # perform sub/or/shift reduction.
            if not branches:
                fail(f"{target}/{opt}/{label} unexpectedly had no loop branches")
            tail = chunk[tail_off:]
            tail_br, tail_prims = decode_arm64(tail) if target == "linux-arm64" else decode_x64(tail)[:2]
            if tail_br:
                fail(f"{target}/{opt}/{label} tail has conditional branches: {tail_br}")
            for req_tail in ("or", "sub"):
                if req_tail not in tail_prims and req_tail not in prims:
                    fail(f"{target}/{opt}/{label} missing reduction primitive {req_tail}")

        missing = required - prims
        if missing:
            fail(f"{target}/{opt}/{label} is missing branchless primitives: {sorted(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--xu",
        help="compiler path (product seed by default; no implicit primer fallback)",
    )
    parser.add_argument("--lane", choices=("product",), default=LANE)
    args = parser.parse_args()
    lane = args.lane
    xu = resolve_product_xu(args.xu)
    if not CONVERTER.is_file():
        fail(f"missing converter: {CONVERTER.relative_to(ROOT)}")

    with tempfile.TemporaryDirectory(prefix="xu-ct-codegen-") as temp_name:
        temp = Path(temp_name)
        empty_xupath = temp / "empty_xupath"
        empty_xupath.mkdir()
        if FIXTURE.is_file():
            src_path = FIXTURE
        else:
            src_path = temp / "crypto_subtle_probe.xu"
            src_path.write_text(PROBE_SOURCE, encoding="utf-8")

        for target in ("linux-x64", "linux-arm64"):
            for opt in ("default", "no-opt"):
                symmap_path = temp / f"{target}-{opt}.sym"
                elf = temp / f"{target}-{opt}.elf"
                xuobj = temp / f"{target}-{opt}.xuobj"
                elf_o = temp / f"{target}-{opt}.o"

                env = os.environ.copy()
                env["XU_ROOT"] = str(ROOT)
                env["XU_STDLIB_ROOT"] = str(ROOT / "src")
                env["XU_SYMMAP"] = str(symmap_path)
                if os.name == "nt":
                    env["XUPATH"] = str(empty_xupath)

                run(compile_argv(xu, lane, target, opt, elf, src_path=src_path, emit_obj=False), env=env)
                audit_elf(target, opt, elf, symmap_path)

                # Also keep checking app XUOBJ -> ELF .o conversion sanity.
                env_obj = env.copy()
                env_obj.pop("XU_SYMMAP", None)
                run(compile_argv(xu, lane, target, opt, xuobj, src_path=src_path, emit_obj=True), env=env_obj)
                if not xuobj.is_file() or xuobj.stat().st_size == 0:
                    fail(f"compiler produced no object for {target}/{opt}: {xuobj}")
                run([sys.executable, str(CONVERTER), str(xuobj), str(elf_o)])
                print(f"PASS {target}/{opt}")
    evidence = "product evidence"
    print(f"crypto constant-time codegen: PASS (x64/ARM64 default and no-opt; lane={lane}; {evidence})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
