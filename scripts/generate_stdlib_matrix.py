#!/usr/bin/env python3
"""Generate a deterministic inventory for the XU standard library.

Package/API discovery is static. Platform and semantic fields start as
``not-measured``. When ``docs/audit/stdlib_evidence.json`` is present it is
merged in so a host runner can record ``native-run`` / ``failed`` /
``compile-only`` / ``unsupported`` without pretending untested targets ran.

Usage::

    python3 scripts/generate_stdlib_matrix.py
    python3 scripts/generate_stdlib_matrix.py --output /tmp/stdlib_matrix.json
    python3 scripts/generate_stdlib_matrix.py --check
    python3 scripts/stdlib_evidence_from_fixtures.py --log /tmp/fixtures.log
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DEFAULT_OUTPUT = ROOT / "docs" / "audit" / "stdlib_matrix.json"
DEFAULT_EVIDENCE = ROOT / "docs" / "audit" / "stdlib_evidence.json"

TARGETS = (
    "macos-arm64",
    "macos-x64",
    "linux-arm64",
    "linux-x64",
    "windows-x64",
    "windows-arm64",
    "linux-loongarch64",
    "linux-riscv64",
)

# Compiler/frontend/runtime sources are product implementation, not importable
# standard-library packages for this inventory.
EXCLUDED_TOP_LEVEL = {"cmd", "xu", "runtime"}
# Methods put the receiver between ``fn`` and the method name.  Capture the
# receiver-less name so ``pub fn (r &Reader) read`` is indexed as ``read``.
PUBLIC_RE = re.compile(
    r"^[ \t]*pub[ \t]+(?P<kind>fn|struct|const|type)\b"
    r"@?[ \t]*(?:\([^\n)]*\)[ \t]*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)?",
    re.MULTILINE,
)
IMPORT_RE = re.compile(r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?#([A-Za-z0-9_./-]+)\s*$", re.MULTILINE)


def iter_package_dirs() -> Iterable[Path]:
    for mod in sorted(SRC.rglob("mod.xu")):
        rel = mod.parent.relative_to(SRC)
        if rel.parts and rel.parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        yield mod.parent


def package_id(package_dir: Path) -> str:
    return package_dir.relative_to(SRC).as_posix()


def package_scope(pkg: str) -> str:
    if pkg == "ui" or pkg.startswith("ui/"):
        return "xu-extension"
    if pkg.startswith("crypto/") and pkg.split("/")[1] in {
        "gmtls",
        "sm2",
        "sm3",
        "sm4",
        "sm9",
        "zuc",
    }:
        return "xu-extension"
    return "stdlib"


def source_hash(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def public_symbols(files: list[Path]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in PUBLIC_RE.finditer(text):
            kind = match.group("kind")
            name = match.group("name") or "<anonymous>"
            found.append(
                {
                    "kind": kind,
                    "name": name,
                    "file": path.relative_to(ROOT).as_posix(),
                    "line": str(text[: match.start()].count("\n") + 1),
                }
            )
    found.sort(key=lambda item: (item["name"], item["kind"], item["file"], item["line"]))
    return found


def fixture_names(pkg: str) -> list[str]:
    fixtures_root = ROOT / "tests" / "fixtures"
    if not fixtures_root.is_dir():
        return []
    # A fixture is associated when any Xu source explicitly imports this
    # package.  This avoids guessing from names and remains deterministic.
    needle = re.compile(
        r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?#" + re.escape(pkg) + r"\s*$",
        re.MULTILINE,
    )
    out: list[str] = []
    for directory in sorted(p for p in fixtures_root.iterdir() if p.is_dir()):
        for source in sorted(directory.rglob("*.xu")):
            if needle.search(source.read_text(encoding="utf-8")):
                out.append(directory.name)
                break
    return out


def load_evidence(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "xu.stdlib-evidence.v1":
        raise SystemExit(f"invalid stdlib evidence schema: {path}")
    return data


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_hash(package: dict, by_name: dict[str, dict]) -> str:
    """Bind a package verdict to its import closure and fixture contracts."""
    closure: set[str] = set()
    pending = [package["package"]]
    while pending:
        name = pending.pop()
        if name in closure or name not in by_name:
            continue
        closure.add(name)
        pending.extend(by_name[name]["imports"])
    digest = hashlib.sha256()
    for name in sorted(closure):
        digest.update(name.encode() + b"\0")
        digest.update(by_name[name]["source_sha256"].encode() + b"\0")
    # Runtime source helpers are injected by the compiler, so they do not
    # necessarily occur in the package's explicit #imports.
    runtime_files = sorted((ROOT / "src/runtime").rglob("*.xu"))
    digest.update(source_hash(runtime_files).encode() + b"\0")
    for fixture in sorted(package["fixtures"]):
        directory = ROOT / "tests" / "fixtures" / fixture
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
                digest.update(path.read_bytes() + b"\0")
    # Shared binary/certificate/format vectors can live outside fixtures.
    for path in sorted((ROOT / "tests/data").rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def apply_evidence(matrix: dict, evidence: dict) -> None:
    if not evidence:
        return
    by_name = {item["package"]: item for item in matrix["packages"]}
    recorded = evidence.get("packages") or {}
    if not isinstance(recorded, dict):
        raise SystemExit("stdlib evidence packages must be an object")
    allowed_semantic = {"pass", "fail", "mixed", "not-measured"}
    allowed_platform = set(matrix["evidence_states"])
    compiler = evidence.get("compiler")
    compiler_hash = file_sha256(ROOT / compiler) if isinstance(compiler, str) else None
    compiler_current = compiler_hash is not None and compiler_hash == evidence.get("compiler_sha256")
    rejected: dict[str, str] = {}
    for pkg, entry in recorded.items():
        if pkg not in by_name or not isinstance(entry, dict):
            continue
        if not compiler_current:
            rejected[pkg] = "compiler provenance missing or changed"
            continue
        if entry.get("evidence_sha256") != evidence_hash(by_name[pkg], by_name):
            rejected[pkg] = "source/import/fixture provenance missing or changed"
            continue
        status = by_name[pkg]["status"]
        semantic = entry.get("semantic")
        if semantic in allowed_semantic:
            status["semantic"] = semantic
        platform = entry.get("platform") or {}
        if isinstance(platform, dict):
            for target, state in platform.items():
                if target in status["platform"] and state in allowed_platform:
                    status["platform"][target] = state
    matrix["evidence"] = {
        "file": "docs/audit/stdlib_evidence.json",
        "host": evidence.get("host"),
        "compiler": evidence.get("compiler"),
        "recorded_at": evidence.get("recorded_at"),
        "packages": len(recorded),
        "rejected": rejected,
    }


def git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and revision else None


def build_matrix() -> dict:
    packages: list[dict] = []
    for directory in iter_package_dirs():
        pkg = package_id(directory)
        files = sorted(directory.rglob("*.xu"))
        symbols = public_symbols(files)
        imports = sorted(
            {
                imported
                for path in files
                for imported in IMPORT_RE.findall(path.read_text(encoding="utf-8"))
            }
        )
        packages.append(
            {
                "package": pkg,
                "scope": package_scope(pkg),
                "source_files": len(files),
                "source_sha256": source_hash(files),
                "public_symbol_count": len(symbols),
                "public_symbols": symbols,
                "imports": imports,
                "fixtures": fixture_names(pkg),
                "status": {
                    "source": "present",
                    "api": "inventory-only",
                    "semantic": "not-measured",
                    "platform": {target: "not-measured" for target in TARGETS},
                },
            }
        )

    packages.sort(key=lambda item: item["package"])
    matrix = {
        "schema": "xu.stdlib-matrix.v1",
        "generated_by": "scripts/generate_stdlib_matrix.py",
        "source_root": "src",
        "targets": list(TARGETS),
        "evidence_states": ["native-run", "compile-only", "unsupported", "failed", "not-measured"],
        "scope": {
            "included": "src/<package> with mod.xu",
            "excluded": ["src/cmd", "src/xu", "src/runtime"],
            "extension_scopes": ["xu-extension"],
        },
        "revision": git_revision(),
        "counts": {
            "packages": len(packages),
            "stdlib_packages": sum(item["scope"] == "stdlib" for item in packages),
            "extension_packages": sum(item["scope"] == "xu-extension" for item in packages),
            "source_files": sum(item["source_files"] for item in packages),
            "public_symbols": sum(item["public_symbol_count"] for item in packages),
        },
        "packages": packages,
    }
    apply_evidence(matrix, load_evidence(DEFAULT_EVIDENCE))
    return matrix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail when output differs from generated content")
    args = parser.parse_args()

    matrix = build_matrix()
    encoded = json.dumps(matrix, ensure_ascii=False, indent=2) + "\n"
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != encoded:
            print(f"stdlib matrix is stale: {output}")
            return 1
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
        print(f"wrote {output}")
    print(json.dumps(matrix["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
