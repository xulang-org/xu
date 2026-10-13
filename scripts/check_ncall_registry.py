#!/usr/bin/env python3
"""Verify Gen1 ncall negative markers stay unique and registered.

Reads docs/audit/NCALL_REGISTRY.md (ID column) and every
src/xu/types/check*.xu / src/xu/types/mir*.xu file, so split-out parts of the
checker and MIR lowering are covered too. Fails if:
  - a check*.xu file assigns an unregistered negative id
  - registry lists the same id twice
  - a mir*.xu file compares against an unregistered negative id
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "docs" / "audit" / "NCALL_REGISTRY.md"
TYPES_DIR = ROOT / "src" / "xu" / "types"

# Positive MIR call ids are consumed by the Gen1 emitters. Keep the hosted-net
# mappings under the same registry check as their negative checker markers;
# otherwise a future instruction renumbering can silently route a syscall to
# an unrelated emitter operation.
MIR_CALL_IDS = {
    -81: 104,
    -122: 131,
    -123: 132,
    -124: 133,
    -125: 134,
    -126: 135,
    -127: 136,
    -129: 155,
}

# Allow markdown bold: | **-50** | name |
ID_ROW = re.compile(r"^\|\s*\*{0,2}(-?\d+)\*{0,2}\s*\|")
ASSIGN = re.compile(
    r"(?:ncall\[[^\]]+\]\s*=\s*|checker_set_i\(\s*mut\s*&c\.ncall\s*,\s*[^,]+,\s*)(-?\d+)"
)
COMPARE = re.compile(
    r"(?:ncall\[[^\]]+\]\s*==\s*|fi\s*==\s*|c\.ncall\[[^\]]+\]\s*==\s*)(-?\d+)"
)


def sources(prefix: str) -> list[Path]:
    return sorted(TYPES_DIR.glob(f"{prefix}*.xu"))


def rel(paths: list[Path]) -> str:
    return ", ".join(str(p.relative_to(ROOT)) for p in paths)


def registry_ids() -> list[int]:
    ids: list[int] = []
    for line in REG.read_text().splitlines():
        m = ID_ROW.match(line)
        if not m:
            continue
        n = int(m.group(1))
        if n < 0:
            ids.append(n)
    return ids


def retired_registry_ids() -> set[int]:
    out: set[int] = set()
    for line in REG.read_text().splitlines():
        m = ID_ROW.match(line)
        if m and "retired" in line.lower():
            out.add(int(m.group(1)))
    return out


def scan(paths: list[Path], pattern: re.Pattern[str]) -> set[int]:
    out: set[int] = set()
    for path in paths:
        for m in pattern.finditer(path.read_text()):
            n = int(m.group(1))
            if n < 0:
                out.add(n)
    return out


def main() -> int:
    if not REG.is_file():
        print(f"FAIL: missing {REG}", file=sys.stderr)
        return 1
    check_files = sources("check")
    mir_files = sources("mir")
    if not check_files:
        print(f"FAIL: no check*.xu under {TYPES_DIR}", file=sys.stderr)
        return 1
    if not mir_files:
        print(f"FAIL: no mir*.xu under {TYPES_DIR}", file=sys.stderr)
        return 1
    reg = registry_ids()
    if not reg:
        print("FAIL: registry has no negative IDs", file=sys.stderr)
        return 1
    dup = sorted({n for n in reg if reg.count(n) > 1})
    if dup:
        print(f"FAIL: duplicate registry IDs: {dup}", file=sys.stderr)
        return 1
    reg_set = set(reg)
    assigned = scan(check_files, ASSIGN)
    missing = sorted(assigned - reg_set)
    if missing:
        print(
            f"FAIL: {rel(check_files)} assign unregistered ncall ids: {missing}",
            file=sys.stderr,
        )
        print(f"  add them to {REG}", file=sys.stderr)
        return 1
    unused = sorted(reg_set - assigned - retired_registry_ids())
    # Allow registry to reserve slots not yet assigned? Prefer strict: warn only.
    if unused:
        print(f"WARN: registry IDs not assigned in check*.xu: {unused}")
    mir = scan(mir_files, COMPARE)
    mir_unknown = sorted(mir - reg_set)
    if mir_unknown:
        print(
            f"FAIL: {rel(mir_files)} reference unregistered ids: {mir_unknown}",
            file=sys.stderr,
        )
        return 1
    mir_text = "\n".join(path.read_text() for path in mir_files)
    for marker, want in MIR_CALL_IDS.items():
        m = re.search(
            rf"fi\s*==\s*{marker}.*?ins\.b\s*=\s*(\d+)",
            mir_text,
            flags=re.DOTALL,
        )
        if m is None:
            print(f"FAIL: MIR mapping for ncall {marker} is missing", file=sys.stderr)
            return 1
        got = int(m.group(1))
        if got != want:
            print(
                f"FAIL: MIR mapping for ncall {marker}: b={got}, expected b={want}",
                file=sys.stderr,
            )
            return 1
    print(
        f"ok: {len(reg_set)} registered ncall markers; "
        f"{len(check_files)} check file(s) assign {len(assigned)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
