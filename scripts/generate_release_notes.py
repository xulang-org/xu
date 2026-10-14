#!/usr/bin/env python3
"""Generate structured release notes with categorized commit logs and packaging metadata.

Usage:
    python3 scripts/generate_release_notes.py [options]

Options:
    --tag TAG              Target release tag (e.g., v0.8.9). Defaults to 'v' + VERSION.
    --prev-tag PREV_TAG    Previous tag to compare against. Auto-detected if omitted.
    --custom-notes FILE    Path to optional custom markdown notes/summary to prepend.
    --manifest FILE        Path to RELEASE_MANIFEST.md to extract package table & install guides.
    --output FILE          Destination file path. Prints to stdout if omitted.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CATEGORY_RULES = [
    (r"^(?:feat|feature)(?:\([^)]+\))?!?:", "🚀 新增特性 (Features)"),
    (r"^fix(?:\([^)]+\))?!?:", "🐛 问题修复 (Bug Fixes)"),
    (r"^perf(?:\([^)]+\))?!?:", "⚡ 性能优化 (Performance)"),
    (r"^refactor(?:\([^)]+\))?!?:", "♻️ 代码重构 (Refactoring)"),
    (r"^docs?(?:\([^)]+\))?!?:", "📝 文档与注释 (Documentation)"),
    (r"^test(?:\([^)]+\))?!?:", "🧪 测试验证 (Tests)"),
    (r"^(?:build|ci|chore)(?:\([^)]+\))?!?:", "🔧 构建与工程 (Build & CI)"),
]


def git(*args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.stdout.strip()


def get_current_version() -> str:
    version_file = REPO_ROOT / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


def find_previous_tag(current_tag: str) -> str | None:
    # Try finding the closest ancestor tag
    tag_ref = current_tag if git("rev-parse", "--verify", f"refs/tags/{current_tag}") else "HEAD"
    prev = git("describe", "--tags", "--abbrev=0", f"{tag_ref}^")
    if prev and prev != current_tag:
        return prev

    # Fallback to listing tags by creator date
    all_tags = [t.strip() for t in git("tag", "--sort=-creatordate").splitlines() if t.strip()]
    for t in all_tags:
        if t != current_tag:
            return t
    return None


def parse_commits(prev_tag: str | None, current_ref: str) -> dict[str, list[dict[str, str]]]:
    revision_range = f"{prev_tag}..{current_ref}" if prev_tag else current_ref
    raw_log = git("log", revision_range, "--pretty=format:%H|%h|%s|%an")
    if not raw_log:
        return {}

    categorized: dict[str, list[dict[str, str]]] = {}
    for line in raw_log.splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        full_hash, short_hash, subject, author = parts
        subject_stripped = subject.strip()

        matched_category = "📌 其他变更 (Other Changes)"
        clean_subject = subject_stripped
        for pattern, cat_name in CATEGORY_RULES:
            match = re.match(pattern, subject_stripped, re.IGNORECASE)
            if match:
                matched_category = cat_name
                clean_subject = subject_stripped[match.end():].strip()
                break

        categorized.setdefault(matched_category, []).append({
            "hash": full_hash,
            "short": short_hash,
            "subject": clean_subject,
            "original_subject": subject_stripped,
            "author": author,
        })

    return categorized


def build_release_notes(
    tag: str,
    prev_tag: str | None,
    custom_notes: str | None,
    manifest_path: Path | None,
) -> str:
    sections: list[str] = []
    version = tag.lstrip("v")
    is_prerelease = bool(re.search(r"-(dev|rc|alpha|beta)", tag, re.IGNORECASE))

    # Header
    sections.append(f"# Xu {tag} {'（开发调试版）' if is_prerelease else '正式发布'}\n")

    # Custom highlights if present
    if custom_notes and custom_notes.strip():
        sections.append("## 📝 版本更新概述\n")
        sections.append(custom_notes.strip() + "\n")

    # What's Changed
    current_ref = tag if git("rev-parse", "--verify", f"refs/tags/{tag}") else "HEAD"
    categorized_commits = parse_commits(prev_tag, current_ref)

    sections.append("## 🌟 更新内容 (What's Changed)\n")
    if categorized_commits:
        # Sort categories in defined order
        order = [cat for _, cat in CATEGORY_RULES] + ["📌 其他变更 (Other Changes)"]
        for cat in order:
            if cat in categorized_commits:
                sections.append(f"### {cat}")
                for c in categorized_commits[cat]:
                    commit_link = f"[{c['short']}](https://github.com/xulang-org/xu/commit/{c['hash']})"
                    sections.append(f"- {c['subject']} ({commit_link}) - @{c['author']}")
                sections.append("")
    else:
        sections.append("- 包含日常维护、性能优化与标准库更新。\n")

    # Compare link
    if prev_tag:
        compare_url = f"https://github.com/xulang-org/xu/compare/{prev_tag}...{tag}"
        sections.append(f"**完整提交历史对比**: [{prev_tag}...{tag}]({compare_url})\n")

    # Manifest inclusion (Packages & Checksums & Installation)
    if manifest_path and manifest_path.is_file():
        manifest_text = manifest_path.read_text(encoding="utf-8")
        # Strip header from manifest if present
        if manifest_text.startswith("#"):
            lines = manifest_text.splitlines()
            # Find the first H2 section
            start_idx = 0
            for idx, line in enumerate(lines):
                if line.startswith("## "):
                    start_idx = idx
                    break
            manifest_text = "\n".join(lines[start_idx:])
        sections.append(manifest_text)

    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate structured release notes for Xu releases")
    parser.add_argument("--tag", help="Release tag name (e.g. v0.8.9)")
    parser.add_argument("--prev-tag", help="Previous release tag to compare with")
    parser.add_argument("--custom-notes", help="Path or text of custom notes to prepend")
    parser.add_argument("--manifest", help="Path to RELEASE_MANIFEST.md")
    parser.add_argument("--output", help="Output file path (default stdout)")

    args = parser.parse_args()

    version = get_current_version()
    tag = args.tag or f"v{version}"
    prev_tag = args.prev_tag or find_previous_tag(tag)

    custom_notes_content: str | None = None
    if args.custom_notes:
        notes_path = Path(args.custom_notes)
        if notes_path.is_file():
            custom_notes_content = notes_path.read_text(encoding="utf-8")
        else:
            custom_notes_content = args.custom_notes

    manifest_path = Path(args.manifest) if args.manifest else None

    notes = build_release_notes(tag, prev_tag, custom_notes_content, manifest_path)

    if args.output:
        out_file = Path(args.output)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(notes, encoding="utf-8")
        print(f"Generated release notes saved to: {out_file}")
    else:
        print(notes)


if __name__ == "__main__":
    main()
