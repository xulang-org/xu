#!/usr/bin/env python3
"""Record stdlib platform/semantic evidence from a fixture runner log.

Reads PASS/FAIL/SKIP lines produced by ``scripts/run_fixtures.sh`` and maps
them onto packages via ``docs/audit/stdlib_matrix.json`` fixture associations.
Writes ``docs/audit/stdlib_evidence.json`` for ``generate_stdlib_matrix.py``
to merge. Cross-compile targets stay ``not-measured`` unless the log names
them.

Usage::

    python3 scripts/stdlib_evidence_from_fixtures.py --log /tmp/fixtures.log
    python3 scripts/stdlib_evidence_from_fixtures.py --log /tmp/fixtures.log --host macos-arm64
"""

from __future__ import annotations

import argparse
import json
import platform
import re
from datetime import date
from pathlib import Path

from generate_stdlib_matrix import build_matrix, evidence_hash, file_sha256


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "audit" / "stdlib_matrix.json"
DEFAULT_OUTPUT = ROOT / "docs" / "audit" / "stdlib_evidence.json"

RESULT_RE = re.compile(r"^(PASS|FAIL|SKIP|KNOWN-FAIL|FIXED)\s+(\S+)")


def host_target() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        os_name = "macos"
    elif system == "linux":
        os_name = "linux"
    elif system == "windows":
        os_name = "windows"
    else:
        os_name = system
    if machine in {"arm64", "aarch64"}:
        arch = "arm64"
    elif machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"loongarch64", "loong64"}:
        arch = "loongarch64"
    elif machine in {"riscv64"}:
        arch = "riscv64"
    else:
        arch = machine
    return f"{os_name}-{arch}"


def load_fixture_map(matrix: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for package in matrix["packages"]:
        for name in package.get("fixtures") or []:
            out.setdefault(name, []).append(package["package"])
    return out


def parse_log(path: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = RESULT_RE.match(line.strip())
        if not match:
            continue
        kind, name = match.group(1), match.group(2)
        if kind in {"PASS", "FIXED"}:
            results[name] = "pass"
        elif kind in {"FAIL", "KNOWN-FAIL"}:
            results[name] = "fail"
        else:
            results[name] = "skip"
    return results


def package_semantic(states: list[str]) -> str:
    useful = [state for state in states if state != "skip"]
    if not useful:
        return "not-measured"
    if all(state == "pass" for state in useful):
        return "pass"
    if all(state == "fail" for state in useful):
        return "fail"
    return "mixed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--host", default=host_target())
    parser.add_argument("--compiler", default="bin/xu")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    args = parser.parse_args()

    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    current = build_matrix()
    by_name = {p["package"]: p for p in current["packages"]}
    if [(p["package"], p["source_sha256"], p["fixtures"]) for p in matrix["packages"]] != [
        (p["package"], p["source_sha256"], p["fixtures"]) for p in current["packages"]
    ]:
        raise SystemExit("stdlib matrix is stale; regenerate it before recording evidence")
    compiler_hash = file_sha256(ROOT / args.compiler)
    if compiler_hash is None:
        raise SystemExit(f"compiler does not exist: {args.compiler}")
    fixture_map = load_fixture_map(matrix)
    results = parse_log(args.log)
    by_pkg: dict[str, list[str]] = {}
    for fixture, state in results.items():
        pkgs = fixture_map.get(fixture, [])
        if state == "fail":
            # A failing fixture that merely *imports* strings/errors should
            # not mark those packages failed. Attribute FAIL to packages
            # whose path is a prefix of the fixture name (`os_file_rw` → os).
            blamed = [
                pkg
                for pkg in pkgs
                if fixture == pkg.replace("/", "_")
                or fixture.startswith(pkg.replace("/", "_") + "_")
            ]
            pkgs = blamed or pkgs
        for pkg in pkgs:
            by_pkg.setdefault(pkg, []).append(state)

    host = args.host
    packages: dict[str, dict] = {}
    for pkg, states in sorted(by_pkg.items()):
        semantic = package_semantic(states)
        if semantic == "not-measured":
            continue
        platform_state = "native-run" if semantic == "pass" else "failed"
        if semantic == "mixed":
            platform_state = "failed"
        packages[pkg] = {
            "semantic": semantic,
            "platform": {host: platform_state},
            "evidence_sha256": evidence_hash(by_name[pkg], by_name),
            "fixtures": sorted(f for f in results if pkg in fixture_map.get(f, [])),
        }

    evidence = {
        "schema": "xu.stdlib-evidence.v1",
        "host": host,
        "compiler": args.compiler,
        "compiler_sha256": compiler_hash,
        "recorded_at": date.today().isoformat(),
        "fixture_log": args.log.name,
        "packages": packages,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output} packages={len(packages)} host={host}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
