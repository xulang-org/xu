#!/usr/bin/env python3
"""Check the actual Git index for local development material and build outputs."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOTS = {
    "docs", "tests", "tmp", "temp", "notes", "reports", "artifacts", "bin", "build",
    ".codex", ".claude", ".codex-tmp", ".cache", ".idea", ".vscode", "htmlcov",
}
LOCAL_FILES = {
    "PROGRESS.md", "TODO.md", "TASKS.md", "PLAN.md", "test_main", "test_order",
    "bootstrap/SYNC_DIFF.md", "CLAUDE.md", "AGENTS.md", "REPOSITORIES.md",
    ".impeccable.md", "server.example.md", "server.md", "pytest.ini",
}
CACHE_DIRS = {"target", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
OUTPUT_SUFFIXES = {
    ".log", ".tmp", ".temp", ".partial", ".stdout", ".stderr", ".bak", ".orig",
    ".rej", ".swp", ".swo", ".pyc", ".pyo", ".o", ".a", ".so", ".dylib",
    ".dll", ".exe", ".xin", ".xuobj", ".vsix",
}
MACHO_MAGIC = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}
MAX_BYTES = 10 * 1024 * 1024


def git(root: Path, *args: str, input: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args], input=input, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def local_only_path(name: str) -> bool:
    return (name.split("/", 1)[0] in {"docs", "tests"} or name in LOCAL_FILES
            or name == "xu-site/xu-api-extract.md" or name.lower() == "readme.txt")


def local_reason(name: str) -> str | None:
    path = PurePosixPath(name)
    if path.parts[0] in LOCAL_ROOTS or name in LOCAL_FILES or name == "xu-site/xu-api-extract.md":
        return "本机文档或研发材料"
    if name.lower() == "readme.txt":
        return "根目录使用 README.md"
    if any(part in CACHE_DIRS or part.endswith((".app", ".curves")) for part in path.parts):
        return "缓存或生成目录"
    if path.suffix.lower() in OUTPUT_SUFFIXES or path.name.endswith("~"):
        return "日志、临时文件或编译产物"
    if path.name in {".DS_Store", "Thumbs.db", "Desktop.ini", ".coverage"}:
        return "本机工具文件"
    if (path.name == ".env" or path.name.startswith(".env.")) and path.name not in {
        ".env.example", ".env.sample", ".env.template",
    }:
        return "本机环境配置"
    return None


def compiled_binary(data: bytes) -> bool:
    # A PE header has NUL bytes in its DOS header; Base32 text can start MZ too.
    pe_header = data.startswith(b"MZ") and b"\0" in data[:64]
    return data.startswith(b"\x7fELF") or data[:4] in MACHO_MAGIC or pe_header


def check(root: Path) -> tuple[list[str], int]:
    # Inspect every index path: an unchanged tracked docs file must also fail.
    entries = {}
    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split()
        entries[raw_name.decode("utf-8", "surrogateescape")] = (mode, oid, stage)
    changed = [name.decode("utf-8", "surrogateescape") for name in git(
        root, "diff", "--cached", "--no-renames", "--name-only", "--diff-filter=ACMRT", "-z",
    ).split(b"\0") if name]
    errors = []
    blocked = set()
    # Local-only paths must remain untracked, including unchanged index entries.
    for name in sorted(entries):
        if entries[name][2] != "0":
            errors.append(f"{name!r}: 未解决的合并冲突")
            blocked.add(name)
        if local_only_path(name):
            errors.append(f"{name!r}: 本机材料仍在 Git 跟踪中；使用 git rm --cached 移除跟踪")
            blocked.add(name)
    if changed:
        # Ignore the user's global excludes, which may hide valid project rules.
        result = subprocess.run(
            ["git", "-C", str(root), "-c", "core.excludesFile=/dev/null", "check-ignore",
             "--no-index", "--stdin", "-z"],
            input=b"\0".join(name.encode("utf-8", "surrogateescape") for name in changed) + b"\0",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if result.returncode not in (0, 1):
            raise subprocess.CalledProcessError(result.returncode, result.args, stderr=result.stderr)
        ignored = {name.decode("utf-8", "surrogateescape") for name in result.stdout.split(b"\0") if name}
        for name in changed:
            if name in blocked:
                continue
            reason = local_reason(name)
            if reason or name in ignored:
                errors.append(f"{name!r}: {reason or '被忽略的本机文件，禁止强制提交'}")
                continue
            mode, oid, stage = entries[name]
            if stage != "0":
                errors.append(f"{name!r}: 未解决的合并冲突")
                continue
            if mode == "160000":  # Gitlinks have no blob to inspect.
                continue
            size = int(git(root, "cat-file", "-s", oid))
            if size > MAX_BYTES:
                errors.append(f"{name!r}: 超过 10 MiB；产物应保存在本机")
            elif mode != "120000" and compiled_binary(git(root, "cat-file", "blob", oid)[:64]):
                errors.append(f"{name!r}: ELF、Mach-O 或 PE 编译二进制")
    whitespace = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--check"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if whitespace.returncode:
        errors.append(whitespace.stdout.decode("utf-8", "replace").strip() or "暂存差异检查失败")
    return errors, len(changed)


def check_tree(root: Path, revision: str) -> list[str]:
    """Inspect the exact outgoing tree; staged deletions cannot hide HEAD files."""
    errors = []
    names = git(root, "ls-tree", "-r", "--name-only", "-z", revision).split(b"\0")
    for raw in names:
        if not raw:
            continue
        name = raw.decode("utf-8", "surrogateescape")
        if local_only_path(name):
            errors.append(f"{revision}:{name!r}: 待推送版本仍包含禁止上传的本机文件")
    return errors


def check_push(root: Path, lines: list[str]) -> tuple[list[str], int]:
    errors = []
    revisions = set()
    for line in lines:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("invalid pre-push input")
        local_oid = fields[1]
        if local_oid and set(local_oid) != {"0"}:
            revisions.add(local_oid)
    for revision in sorted(revisions):
        errors.extend(check_tree(root, revision))
    return errors, len(revisions)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="check staged changes (default)")
    parser.add_argument("--pre-push", action="store_true", help="check outgoing ref trees from hook stdin")
    args = parser.parse_args()
    try:
        if args.pre_push:
            errors, count = check_push(ROOT, sys.stdin.read().splitlines())
        else:
            errors, count = check(ROOT)
    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        print(f"Git 提交检查无法完成：{error}", file=sys.stderr)
        return 1
    if errors:
        print("Git 上传范围检查失败：", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    print(f"Git 上传范围检查通过（{count} 个检查对象；本机文件与 tests/ 未进入提交范围）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
