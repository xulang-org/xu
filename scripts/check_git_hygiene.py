#!/usr/bin/env python3
"""Check the actual Git index for local development material and build outputs."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ROOTS = {
    "docs", "tmp", "temp", "notes", "reports", "artifacts", "bin", "build",
    ".codex", ".claude", ".codex-tmp", ".cache", ".idea", ".vscode", "htmlcov",
}
LOCAL_FILES = {
    "PROGRESS.md", "TODO.md", "TASKS.md", "PLAN.md", "test_main", "test_order",
    "bootstrap/SYNC_DIFF.md",
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


def local_reason(name: str) -> str | None:
    path = PurePosixPath(name)
    if path.parts[0] in LOCAL_ROOTS or name in LOCAL_FILES or name == "xu-site/xu-api-extract.md":
        return "本机文档或研发材料"
    if any(part in CACHE_DIRS or part.endswith((".app", ".curves")) for part in path.parts):
        return "缓存或生成目录"
    golden = path.parts[0] == "tests" and path.name in {"expected.stdout", "expected.stderr"}
    if (path.suffix.lower() in OUTPUT_SUFFIXES and not golden) or path.name.endswith("~"):
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
    # docs and the identified process records must be completely untracked.
    for name in sorted(entries):
        if entries[name][2] != "0":
            errors.append(f"{name!r}: 未解决的合并冲突")
            blocked.add(name)
        if name.startswith("docs/") or name in LOCAL_FILES or name == "xu-site/xu-api-extract.md":
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="check staged changes (default)")
    parser.parse_args()
    try:
        errors, count = check(ROOT)
    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        print(f"Git 提交检查无法完成：{error}", file=sys.stderr)
        return 1
    if errors:
        print("Git 提交检查失败：", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    print(f"Git 提交检查通过（{count} 个新增或修改文件；本机文档未跟踪）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
