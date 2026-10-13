#!/usr/bin/env python3
"""Audit XU-CT scalar/result code generation on hosted x64 and ARM64.

This is a product-lane code-generation audit by default.  The hosted seed is
resolved through ``xu_host_seed.sh`` and every product compile crosses the
hermetic ``run_product_compiler.sh`` seam.  ``--lane oracle`` is an explicit
diagnostic escape that invokes an already-built bootstrap primer directly;
the oracle result is never reported as product evidence.  No cargo/bootstrap
fallback is performed here.
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

from companion_repos import project_root

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "crypto_subtle" / "main.xu"
CONVERTER = ROOT / "scripts" / "xuobj_to_elf_o.py"
_BOOT_CANDIDATES = (
    project_root("bootstrap", core_root=ROOT) / "target" / "debug" / "xu",
    project_root("bootstrap", core_root=ROOT) / "target" / "debug" / "xu.exe",
    project_root("bootstrap", core_root=ROOT) / "target" / "release" / "xu",
    project_root("bootstrap", core_root=ROOT) / "target" / "release" / "xu.exe",
)
BOOT_XU = next((candidate for candidate in _BOOT_CANDIDATES if candidate.is_file()), _BOOT_CANDIDATES[0])
# Canonical Gen0 artifacts accepted by the explicit oracle lane.
FROZEN_PRIMER_PATHS = frozenset(
    {
        (project_root("bootstrap", core_root=ROOT) / "target" / "debug" / "xu").absolute(),
        (project_root("bootstrap", core_root=ROOT) / "target" / "debug" / "xu.exe").absolute(),
        (project_root("bootstrap", core_root=ROOT) / "target" / "release" / "xu").absolute(),
        (project_root("bootstrap", core_root=ROOT) / "target" / "release" / "xu.exe").absolute(),
    }
)
HOST_SEED_RESOLVER = ROOT / "scripts" / "xu_host_seed.sh"
PRODUCT_RUNNER = ROOT / "scripts" / "run_product_compiler.sh"
# Keep the canonical name visible to the boundary checker and to consumers
# that audit the product compiler seam.
PRODUCT_COMPILER_RUNNER = PRODUCT_RUNNER
ORACLE_SEED_OFF = "XU_ALLOW_ORACLE_SEED=0"
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


def _lexical_path(path: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.absolute()


def _has_symlink_component(path: Path) -> bool:
    candidate = _lexical_path(path)
    owner = project_root("bootstrap", core_root=ROOT)
    if not candidate.is_relative_to(owner):
        owner = ROOT
    try:
        relative = candidate.relative_to(owner)
    except ValueError:
        return False
    if owner.is_symlink():
        return True
    current = owner
    for part in relative.parts:
        current /= part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def is_primer(path: Path, resolved: Path | None = None) -> bool:
    """Classify lexical and resolved bootstrap provenance."""

    lexical = _lexical_path(path)
    if resolved is None:
        try:
            target = lexical.resolve()
        except (OSError, RuntimeError):
            target = lexical
    else:
        target = _lexical_path(resolved)
    bootstrap = project_root("bootstrap", core_root=ROOT)
    for candidate in (lexical, target):
        try:
            candidate.relative_to(bootstrap)
        except (OSError, RuntimeError, ValueError):
            continue
        return True
    return False


def is_frozen_primer(path: Path) -> bool:
    """Return true only for an exact, non-symlink Gen0 artifact."""

    lexical = _lexical_path(path)
    if (
        lexical not in FROZEN_PRIMER_PATHS
        or _has_symlink_component(lexical)
        or not lexical.is_file()
        or not os.access(lexical, os.X_OK)
    ):
        return False
    try:
        return lexical.resolve() == lexical
    except (OSError, RuntimeError):
        return False


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
    env["XU_ALLOW_ORACLE_SEED"] = ORACLE_SEED_OFF.split("=", 1)[1]
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
    # Keep a second guard here so replacing/mocking the resolver cannot turn a
    # primer into product evidence.
    if is_primer(compiler):
        fail(
            "bootstrap primer is oracle-only; use --lane oracle for explicit "
            "direct diagnostics"
        )
    return compiler


def resolve_compiler(explicit: str | None, lane: str = LANE) -> Path:
    """Resolve the compiler for an explicitly selected lane.

    Product uses the canonical resolver.  Oracle requires an existing primer
    and intentionally does not invoke cargo; callers own that build step.
    """

    if lane not in {"product", "oracle"}:
        raise SystemExit(f"crypto codegen: invalid compiler lane {lane!r}")
    if lane == "product":
        if not is_executable(PRODUCT_COMPILER_RUNNER):
            fail(f"missing executable product compiler wrapper: {PRODUCT_COMPILER_RUNNER}")
        return _resolve_hosted_seed(explicit)

    raw = Path(explicit).expanduser() if explicit else BOOT_XU
    compiler = raw.resolve()
    if not is_executable(compiler):
        fail(
            "bootstrap primer missing or not executable: "
            f"{compiler}; build it explicitly (`make bootstrap`) and pass "
            "--lane oracle --xu PATH"
        )
    if not is_frozen_primer(raw):
        fail(
            "oracle lane requires the frozen bootstrap primer; "
            "use --lane product for a hosted compiler"
        )
    return compiler


def resolve_product_xu(explicit: str | None) -> Path:
    """Stable product-lane seam for the boundary manifest/checker."""

    return resolve_compiler(explicit, "product")


def compile_argv(
    compiler: Path,
    lane: str,
    target: str,
    opt: str,
    xuobj: Path,
) -> list[str]:
    """Build a lane-correct compiler command.

    Hosted product uses the ``build`` subcommand through the hermetic wrapper;
    Gen0's Rust primer uses its direct file-first CLI.  Keeping the two forms
    separate prevents a path-based heuristic from silently crossing lanes.
    """

    if lane == "product":
        if not is_executable(PRODUCT_COMPILER_RUNNER):
            raise ValueError(
                f"crypto codegen: missing product compiler wrapper: {PRODUCT_COMPILER_RUNNER}"
            )
        if is_primer(compiler):
            raise ValueError(
                "crypto codegen: bootstrap primer cannot be used in product lane"
            )
        return [
            str(PRODUCT_COMPILER_RUNNER),
            str(compiler),
            "build",
            str(FIXTURE),
            "--target",
            target,
            f"-{opt}",
            "--emit-obj",
            "-o",
            str(xuobj),
        ]
    if lane == "oracle":
        if not is_frozen_primer(compiler):
            raise ValueError(
                "crypto codegen: oracle compile requires the frozen bootstrap primer"
            )
        return [
            str(compiler),
            str(FIXTURE),
            "--target",
            target,
            f"-{opt}",
            "--emit-obj",
            "-o",
            str(xuobj),
        ]
    raise ValueError(f"crypto codegen: invalid compiler lane {lane!r}")


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
    parser.add_argument(
        "--lane",
        choices=("product", "oracle"),
        default=LANE,
        help="compiler lane (default: product; oracle is explicit direct primer diagnostics)",
    )
    parser.add_argument(
        "--oracle",
        action="store_true",
        help="alias for --lane oracle",
    )
    args = parser.parse_args()
    if args.oracle and args.lane != LANE:
        fail("use either --oracle or --lane oracle")
    lane = "oracle" if args.oracle else args.lane
    xu = (
        resolve_product_xu(args.xu)
        if lane == "product"
        else resolve_compiler(args.xu, lane)
    )
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
    evidence = (
        "product evidence"
        if lane == "product"
        else "oracle diagnostic (not product evidence)"
    )
    print(f"crypto constant-time codegen: PASS (x64/ARM64 O0-O3; lane={lane}; {evidence})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
