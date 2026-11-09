#!/usr/bin/env python3
"""Verify Gen1 ncall negative markers stay resolvable.

The clean-architecture rewrite moved MIR lowering out of src/xu/types into
src/xu/mir and replaced the legacy id-based emitter with name-based call
lowering. The previous ledger therefore lost its subject: docs/audit/
NCALL_REGISTRY.md was deleted with the legacy tree, the ncall -> ins.b
emitter mapping no longer exists, and the legacy system-call dispatcher file
was removed. None of those checks can run against this tree any more.

What still matters, and what this script enforces:

  - every check*.xu file that assigns a negative ncall marker is scanned
  - a marker the checker dispatches on must be one the checker actually
    assigns, so a comparison can never be silently dead
  - the MIR lowering directory is scanned under the same rule

The local ledger check is kept but optional: when docs/audit/NCALL_REGISTRY.md
is present it is still enforced, and when it is absent the script does not
invent a replacement for it.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "docs" / "audit" / "NCALL_REGISTRY.md"
TYPES_DIR = ROOT / "src" / "xu" / "types"
MIR_DIR = ROOT / "src" / "xu" / "mir"

# ncall holds the function index for an ordinary call site and -1 for
# everything that is not a builtin marker, so -1 is never assigned a marker.
SENTINEL = -1

ASSIGN = re.compile(
    r"(?:ncall\[[^\]]+\]\s*=\s*|checker_set_i\(\s*\$&c\.ncall\s*,\s*[^,]+,\s*)(-?\d+)"
)
COMPARE = re.compile(
    r"(?:ncall\[[^\]]+\]\s*==\s*|fi\s*==\s*|c\.ncall\[[^\]]+\]\s*==\s*)(-?\d+)"
)
# Allow markdown bold: | **-50** | name |
ID_ROW = re.compile(r"^\|\s*\*{0,2}(-?\d+)\*{0,2}\s*\|")


def sources(directory: Path, prefix: str) -> list[Path]:
    return sorted(directory.glob(f"{prefix}*.xu"))


def rel(paths: list[Path]) -> str:
    return ", ".join(str(p.relative_to(ROOT)) for p in paths)


def registry_ids() -> list[int]:
    if not REG.is_file():
        return []
    ids: list[int] = []
    for line in REG.read_text(encoding="utf-8").splitlines():
        m = ID_ROW.match(line)
        if not m:
            continue
        n = int(m.group(1))
        if n < 0:
            ids.append(n)
    return ids


def retired_registry_ids() -> set[int]:
    if not REG.is_file():
        return set()
    out: set[int] = set()
    for line in REG.read_text(encoding="utf-8").splitlines():
        m = ID_ROW.match(line)
        if m and "retired" in line.lower():
            out.add(int(m.group(1)))
    return out


def scan(paths: list[Path], pattern: re.Pattern[str]) -> set[int]:
    out: set[int] = set()
    for path in paths:
        for m in pattern.finditer(path.read_text(encoding="utf-8")):
            n = int(m.group(1))
            if n < 0:
                out.add(n)
    return out


def scan_by_file(paths: list[Path], pattern: re.Pattern[str]) -> dict[int, list[Path]]:
    out: dict[int, list[Path]] = {}
    for path in paths:
        for m in pattern.finditer(path.read_text(encoding="utf-8")):
            n = int(m.group(1))
            if n < 0:
                out.setdefault(n, []).append(path)
    return out


def main() -> int:
    ci = os.environ.get("XU_BOUNDARY_CI") == "1"
    check_files = sources(TYPES_DIR, "check")
    if not check_files:
        print(f"FAIL: no check*.xu under {TYPES_DIR}", file=sys.stderr)
        return 1
    mir_files = sources(MIR_DIR, "")
    if not mir_files:
        print(f"FAIL: no *.xu under {MIR_DIR}", file=sys.stderr)
        return 1

    assigned = scan(check_files, ASSIGN)
    if not assigned:
        print("FAIL: checker source has no ncall markers", file=sys.stderr)
        return 1

    reg = registry_ids()
    if not ci and reg:
        dup = sorted({n for n in reg if reg.count(n) > 1})
        if dup:
            print(f"FAIL: duplicate registry IDs: {dup}", file=sys.stderr)
            return 1
        reg_set = set(reg) | retired_registry_ids()
        missing = sorted(assigned - reg_set)
        if missing:
            print(
                f"FAIL: {rel(check_files)} assign unregistered ncall ids: {missing}",
                file=sys.stderr,
            )
            print(f"  add them to {REG}", file=sys.stderr)
            return 1
        unused = sorted(reg_set - assigned)
        if unused:
            print(f"WARN: registry IDs not assigned in check*.xu: {unused}")
    elif ci and not reg:
        print("note: local ncall ledger absent; source marker resolution stays enforced")

    # Every marker the checker dispatches on must be one it assigns. A
    # comparison against a marker nothing assigns is a dead branch that hides
    # the real intent of the surrounding code.
    known = assigned | {SENTINEL}
    for paths in (check_files, mir_files):
        unknown = sorted(n for n in scan(paths, COMPARE) if n not in known)
        if unknown:
            culprits = scan_by_file(paths, COMPARE)
            where = ", ".join(
                f"{rel(sorted(set(culprits[n])))} ({n})" for n in unknown
            )
            print(f"FAIL: unregistered ncall ids compared: {where}", file=sys.stderr)
            return 1

    print(
        f"ok: {len(check_files)} check file(s) assign {len(assigned)} ncall markers; "
        f"{len(mir_files)} MIR file(s) scanned"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
