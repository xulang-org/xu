#!/usr/bin/env python3
"""Audit XU-CT scalar/result code generation on hosted x64 and ARM64.

The hosted seed is resolved through xu_host_seed.sh; every compile uses
run_product_compiler.sh to isolate source roots, caches and host settings.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
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

BLOCKS = {
    "compare-result": (
        "_xu_crypto_subtle_constant_time_compare_bb7",
        "_xu_crypto_subtle_constant_time_compare_bb8",
        {"sub", "or", "sar", "and"},
    ),
    "byte-eq": (
        "_xu_crypto_subtle_constant_time_byte_eq_bb0",
        "_xu_crypto_subtle_constant_time_byte_eq_bb1",
        {"xor", "sub", "or", "sar", "and"},
    ),
    "int-eq": (
        "_xu_crypto_subtle_constant_time_eq_bb0",
        "_xu_crypto_subtle_constant_time_eq_bb1",
        {"xor", "sub", "or", "sar", "and"},
    ),
    "select": (
        "_xu_crypto_subtle_constant_time_select_bb0",
        "_xu_crypto_subtle_constant_time_select_bb1",
        {"and", "xor", "or"},
    ),
}


def is_executable(path: Path) -> bool:
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


def _resolve_hosted_seed(explicit: str | None) -> Path:
    """Resolve a hosted seed without ever falling through to the primer."""

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
    if not is_executable(PRODUCT_COMPILER_RUNNER):
        fail(f"missing executable product compiler wrapper: {PRODUCT_COMPILER_RUNNER}")
    return _resolve_hosted_seed(explicit)


def resolve_product_xu(explicit: str | None) -> Path:
    """Stable product-lane seam for the boundary manifest/checker."""

    return resolve_compiler(explicit, "product")


def compile_argv(compiler: Path, lane: str, target: str, opt: str, xuobj: Path) -> list[str]:
    """Compile through the isolated product wrapper."""
    if lane != "product":
        raise ValueError(f"crypto codegen: invalid compiler lane {lane!r}")
    return [str(PRODUCT_COMPILER_RUNNER), str(compiler), "build", str(FIXTURE),
            "--target", target, f"-{opt}", "--emit-obj", "-o", str(xuobj)]


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
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


def symbol_address(objdump: str, obj: Path, symbol: str) -> int:
    table = run([objdump, "-t", str(obj)])
    match = re.search(rf"^([0-9a-fA-F]+)\s+.*\s{re.escape(symbol)}$", table, re.MULTILINE)
    if match is None:
        fail(f"{obj.name} has no symbol {symbol}")
    return int(match.group(1), 16)


def mnemonics(objdump: str, obj: Path, start: int, stop: int) -> list[str]:
    output = run(
        [
            objdump,
            "-d",
            f"--start-address={start}",
            f"--stop-address={stop}",
            str(obj),
        ]
    )
    out: list[str] = []
    for line in output.splitlines():
        match = re.match(
            r"^\s*[0-9a-fA-F]+:\s+(?:[0-9a-fA-F]{2,8}\s+)+(\S+)", line
        )
        if match:
            out.append(match.group(1).lower())
    if not out:
        fail(f"objdump produced no instructions for {obj.name} [{start:#x}, {stop:#x})")
    return out


def normalized(mnemonic: str) -> str:
    name = mnemonic.lower()
    if name in {"eor", "eorq", "xor", "xorq"}:
        return "xor"
    if name in {"orr", "or", "orq"}:
        return "or"
    if name in {"asr", "sar", "sarq"}:
        return "sar"
    if name in {"and", "andq"}:
        return "and"
    if name in {"sub", "subq"}:
        return "sub"
    return name


def is_conditional_branch(target: str, mnemonic: str) -> bool:
    name = mnemonic.lower()
    if target == "linux-x64":
        return (name.startswith("j") and name not in {"jmp", "jmpq"}) or name.startswith("loop")
    return name in {"cbz", "cbnz", "tbz", "tbnz"} or name.startswith("b.")


def audit_object(objdump: str, target: str, opt: str, obj: Path) -> None:
    for label, (start_symbol, stop_symbol, required) in BLOCKS.items():
        start = symbol_address(objdump, obj, start_symbol)
        stop = symbol_address(objdump, obj, stop_symbol)
        if stop <= start:
            fail(f"{target}/{opt}/{label} has invalid symbol range")
        ops = mnemonics(objdump, obj, start, stop)
        branches = [op for op in ops if is_conditional_branch(target, op)]
        if branches:
            fail(f"{target}/{opt}/{label} has conditional branch instructions: {branches}")
        present = {normalized(op) for op in ops}
        missing = required - present
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
    objdump = shutil.which("objdump")
    if objdump is None:
        fail("objdump is required for the code-generation audit")
    if not CONVERTER.is_file():
        fail(f"missing converter: {CONVERTER.relative_to(ROOT)}")

    with tempfile.TemporaryDirectory(prefix="xu-ct-codegen-") as temp_name:
        temp = Path(temp_name)
        for target in ("linux-x64", "linux-arm64"):
            for opt in ("O0", "O1", "O2", "O3"):
                xuobj = temp / f"{target}-{opt}.xuobj"
                elf = temp / f"{target}-{opt}.o"
                run(compile_argv(xu, lane, target, opt, xuobj))
                if not xuobj.is_file() or xuobj.stat().st_size == 0:
                    fail(f"compiler produced no object for {target}/{opt}: {xuobj}")
                run([sys.executable, str(CONVERTER), str(xuobj), str(elf)])
                audit_object(objdump, target, opt, elf)
                print(f"PASS {target}/{opt}")
    evidence = "product evidence"
    print(f"crypto constant-time codegen: PASS (x64/ARM64 O0-O3; lane={lane}; {evidence})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
