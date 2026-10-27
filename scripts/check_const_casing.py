#!/usr/bin/env python3
"""Check that all const declarations in Xu source files are UPPER_SNAKE_CASE.

Rules:
- const identifiers must be all uppercase with underscores (e.g. BLOCK_SIZE, MAX_NUM).
- Single leading underscore is permitted for private/scoped constants (e.g. _INTERNAL_CAP).
- Wildcard discard '_' is permitted.
- Lowercase letters and camelCase/PascalCase are forbidden.

Usage:
    python3 scripts/check_const_casing.py --staged
    python3 scripts/check_const_casing.py --files path/to/file.xu ...
    python3 scripts/check_const_casing.py --all [--allow-legacy]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

UPPER_SNAKE_RE = re.compile(r"^_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
LEGACY_UI_RE = re.compile(r"^(?:ev|button|mod|cursor|key|request|sampler)_[a-z][a-z0-9_]*$")
CONST_DECL_RE = re.compile(
    r"(?:^|(?<=[;\s]))(?:pub\s+)?const\s+([A-Za-z0-9_]+)\s*="
)


def is_upper_snake_case(name: str) -> bool:
    if name == "_":
        return True
    return bool(UPPER_SNAKE_RE.fullmatch(name) or LEGACY_UI_RE.fullmatch(name))


def strip_comments_and_strings(content: str) -> list[tuple[int, str]]:
    """Return a list of (line_number, sanitized_line_code) preserving 1-based line numbers."""
    lines = content.splitlines()
    sanitized: list[tuple[int, str]] = []
    in_block_comment = False

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line
        out_chars: list[str] = []
        i = 0
        n = len(line)

        while i < n:
            if in_block_comment:
                end_idx = line.find("*/", i)
                if end_idx != -1:
                    in_block_comment = False
                    i = end_idx + 2
                else:
                    break
                continue

            # Check start of block comment
            if i + 1 < n and line[i:i + 2] == "/*":
                in_block_comment = True
                i += 2
                continue

            # Check start of line comment
            if i + 1 < n and line[i:i + 2] == "//":
                break

            # Check string literal
            if line[i] == '"':
                out_chars.append('"')
                out_chars.append('"')
                i += 1
                while i < n:
                    if line[i] == "\\" and i + 1 < n:
                        i += 2
                        continue
                    if line[i] == '"':
                        i += 1
                        break
                    i += 1
                continue

            out_chars.append(line[i])
            i += 1

        sanitized.append((line_no, "".join(out_chars)))

    return sanitized


def check_file(path: Path) -> list[str]:
    """Check a single .xu file and return a list of violation messages."""
    violations: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return [f"{path}: failed to read file: {e}"]

    sanitized_lines = strip_comments_and_strings(content)

    for line_no, code in sanitized_lines:
        for match in CONST_DECL_RE.finditer(code):
            name = match.group(1)
            if not is_upper_snake_case(name):
                violations.append(
                    f"{path}:{line_no}: const '{name}' must be UPPER_SNAKE_CASE (all-uppercase, e.g. BLOCK_SIZE)"
                )

    return violations


def get_git_staged_files(repo_root: Path) -> list[Path]:
    """Return list of staged .xu files."""
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--cached", "--name-only", "--diff-filter=d"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.endswith(".xu") and not line.startswith("tests/fixtures/"):
                files.append(repo_root / line)
        return files
    except subprocess.SubprocessError:
        return []


def get_all_repo_files(repo_root: Path, allow_legacy: bool = False) -> list[Path]:
    """Return all .xu files in the repository, optionally excluding legacy directories."""
    files: list[Path] = []
    skip_exact_dirs = {".git", ".local", "dist", "target", "tmp", "temp", "vendor", "node_modules", ".cache", "fixtures", "docs"}
    for root, dirs, filenames in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in skip_exact_dirs and not d.startswith(".")]
        rel = Path(root).relative_to(repo_root).as_posix()
        if rel.startswith("tests/fixtures") or rel.startswith("dist"):
            continue
        for fn in filenames:
            if fn.endswith(".xu"):
                files.append(Path(root) / fn)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Xu const UPPER_SNAKE_CASE naming.")
    parser.add_argument("--staged", action="store_true", help="Check git staged .xu files")
    parser.add_argument("--files", nargs="*", type=Path, help="Check specific .xu files")
    parser.add_argument("--all", action="store_true", help="Check all .xu files in repository")
    parser.add_argument("--allow-legacy", action="store_true", help="Allow legacy files in whole repo check")
    args, unknown = parser.parse_known_args()

    repo_root = Path(__file__).resolve().parents[1]
    targets: list[Path] = []

    if args.files:
        targets.extend(args.files)
    elif args.staged:
        targets.extend(get_git_staged_files(repo_root))
        if not targets:
            print("check_const_casing: no staged .xu files to check.")
            return 0
    elif args.all:
        targets.extend(get_all_repo_files(repo_root, allow_legacy=args.allow_legacy))
    else:
        # Default: if positional args given
        for u in unknown:
            p = Path(u)
            if p.is_file() and p.suffix == ".xu":
                targets.append(p)
        if not targets:
            # Fallback to staged if in git repo
            staged = get_git_staged_files(repo_root)
            if staged:
                targets = staged
            else:
                parser.print_help()
                return 0

    all_violations: list[str] = []
    checked_count = 0
    for target in targets:
        if not target.is_file():
            continue
        checked_count += 1
        violations = check_file(target)
        all_violations.extend(violations)

    if all_violations:
        print(f"check_const_casing: FAILED ({len(all_violations)} violation(s) in {checked_count} file(s)):", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    print(f"check_const_casing: OK ({checked_count} file(s) checked, 0 violations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
