#!/usr/bin/env python3
"""Check or bump module version: fields against a Git revision (default: HEAD)."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ("src", "packages", "developer")
COMPILER_MANIFEST = "src/cmd/compile/xu.xun"
VERSION_LINE = re.compile(r"^version:[^\n]*(?:\n|$)", re.MULTILINE)
XU_LINE = re.compile(r"^xu:[^\n]*(?:\n|$)", re.MULTILINE)
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args]).decode("utf-8")


def read_version(text: str) -> tuple[int, int, int] | None:
    lines = VERSION_LINE.findall(text)
    if not lines:
        return None
    if len(lines) != 1:
        raise ValueError("duplicate version: field")
    value = lines[0].split(":", 1)[1].strip()
    if value.startswith("!ver "):
        value = value[5:].strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    match = SEMVER.fullmatch(value)
    if not match:
        raise ValueError("version: must be a major.minor.patch version")
    return tuple(int(x) for x in match.groups())


def format_version(version: tuple[int, int, int]) -> str:
    return ".".join(map(str, version))


def bump_version(version: tuple[int, int, int], kind: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if kind == "major":
        return major + 1, 0, 0
    if kind == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def read_xu_version(text: str) -> tuple[int, int, int] | None:
    lines = XU_LINE.findall(text)
    try:
        return read_version("".join(re.sub(r"^xu:", "version:", line) for line in lines))
    except ValueError as error:
        raise ValueError(str(error).replace("version:", "xu:").replace("version: field", "xu: field")) from error


def with_version(text: str, version: tuple[int, int, int], key: str = "version") -> str:
    pattern = VERSION_LINE if key == "version" else XU_LINE
    line = f"{key}: !ver {format_version(version)}\n"
    if pattern.search(text):
        return pattern.sub(lambda _: line, text, count=1)
    if key == "xu":
        existing = VERSION_LINE.search(text)
        if existing:
            return text[:existing.end()].rstrip("\r\n") + "\n" + line + text[existing.end():]
    lines = text.splitlines(keepends=True)
    for i, existing in enumerate(lines):
        if existing.startswith("module:"):
            lines[i] = existing.rstrip("\r\n") + "\n" + line
            return "".join(lines)
    raise ValueError("missing module: field")


def owner(path: str, manifests: set[str]) -> str | None:
    for parent in Path(path).parents:
        manifest = (parent / "xu.xun").as_posix()
        if manifest in manifests:
            return manifest
    return None


def process(root: Path, base: str, bump: bool = False, kind: str = "patch") -> list[str]:
    # Git's inventory excludes ignored build products. Limit ownership to real
    # project domains; fixtures, historical audits and dist snapshots are data.
    files = set(git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *DOMAINS).split("\0"))
    manifests = {p for p in files if p.endswith("/xu.xun") and (root / p).is_file()}
    has_head = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                              capture_output=True).returncode == 0
    if base == "HEAD" and not has_head:
        # Fresh independent repositories have no comparison tree. Existing
        # manifests are initial versions; initialize only missing versions.
        baseline = set()
        changed = set(files)
    else:
        baseline = set(git(root, "ls-tree", "-r", "--name-only", "-z", base, "--", *DOMAINS).split("\0"))
        changed = set(git(root, "diff", "--no-renames", "--name-only", "-z", base, "--", *DOMAINS).split("\0"))
    changed.update(git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *DOMAINS).split("\0"))
    old_text = {p: git(root, "show", f"{base}:{p}") for p in manifests if p in baseline}
    changed_modules = set()
    for path in changed:
        manifest = owner(path, manifests)
        if not manifest:
            continue
        # Version metadata alone does not change a module's content. Xu release
        # synchronization must not independently bump every module's version.
        if path == manifest and manifest in old_text:
            current = (root / path).read_text(encoding="utf-8")
            if XU_LINE.sub("", VERSION_LINE.sub("", current)) == XU_LINE.sub("", VERSION_LINE.sub("", old_text[manifest])):
                continue
        changed_modules.add(manifest)
    errors = []
    updates = []
    for manifest in sorted(manifests):
        text = (root / manifest).read_text(encoding="utf-8")
        try:
            current = read_version(text)
            old = read_version(old_text[manifest]) if manifest in old_text else None
            previous = old or (0, 1, 0)
            existing_changed = manifest in old_text and manifest in changed_modules
            if manifest == COMPILER_MANIFEST:
                product = read_version("version: " + (root / "VERSION").read_text().strip() + "\n")
                if current != product:
                    raise ValueError("compiler version: must match root VERSION; run --sync-release")
            if current is not None and old is not None and current < old:
                raise ValueError(f"version regressed from {format_version(old)}")
            if bump:
                target = current or previous
                if existing_changed and target <= previous and manifest != COMPILER_MANIFEST:
                    target = bump_version(previous, kind)
                if current != target:
                    updates.append((manifest, with_version(text, target), target))
            elif current is None:
                raise ValueError("missing version:; run python3 scripts/module_versions.py --bump")
            elif existing_changed and current <= previous:
                raise ValueError(f"module changed but version did not increase past {format_version(previous)}")
        except ValueError as error:
            errors.append(f"{manifest}: {error}")
    # Validate everything before writing any manifest.
    if not errors:
        for manifest, text, target in updates:
            (root / manifest).write_text(text, encoding="utf-8")
            print(f"{manifest}: {format_version(target)}")
    return errors


def release(root: Path, kind: str | None = None, check: bool = False, *, allow_stable: bool = False) -> list[str]:
    """Align xu: and compiler version: to VERSION; other modules stay independent."""
    raw = (root / "VERSION").read_text(encoding="utf-8").strip()
    previous = read_version(f"version: {raw}\n")
    target = bump_version(previous, kind) if kind else previous
    if kind and previous[0] == 0 and target[0] >= 1 and not allow_stable:
        return ["Xu stays in 0.x until an explicit stable release decision; use a minor/patch bump. --allow-stable is reserved for that approved release."]
    value = format_version(target)
    files = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *DOMAINS).split("\0")
    manifests = sorted({p for p in files if p.endswith("/xu.xun") and (root / p).is_file()})
    updates = {}
    errors = []
    if not manifests:
        return ["no module manifests found"]
    for name in manifests:
        text = (root / name).read_text(encoding="utf-8")
        try:
            if read_version(text) is None:
                raise ValueError("missing module version:")
            current = read_xu_version(text)
            if current is not None and current > target:
                raise ValueError(f"release {value} would regress xu: {format_version(current)}; choose a newer release")
            if check and current != target:
                raise ValueError(f"xu: must match release VERSION={value}")
            if current != target:
                updates[name] = with_version(text, target, "xu")
            if name == COMPILER_MANIFEST:
                compiler_version = read_version(text)
                if check and compiler_version != target:
                    raise ValueError(f"compiler version: must match release VERSION={value}")
                if compiler_version != target:
                    updates[name] = with_version(updates.get(name, text), target)
        except ValueError as error:
            errors.append(f"{name}: {error}")
    # Update only the product version fields, not arbitrary version strings.
    fields = (
        ("src/cmd/compile/driver_entry.xu", r"(Xu Compiler Toolchain v)([0-9]+\.[0-9]+\.[0-9]+)"),
        ("src/cmd/desktop/pack_macos.xu", r"(CFBundleShortVersionString</key>[^\n]*?<string>)([0-9]+\.[0-9]+\.[0-9]+)"),
    )
    for name, pattern in fields:
        text = (root / name).read_text(encoding="utf-8")
        matches = list(re.finditer(pattern, text))
        if len(matches) != 1:
            errors.append(f"{name}: expected exactly one product version field")
            continue
        if check and matches[0].group(2) != value:
            errors.append(f"{name}: product version must match VERSION={value}")
        rewritten = re.sub(pattern, lambda m: m.group(1) + value, text)
        if rewritten != text:
            updates[name] = rewritten
    if kind:
        updates["VERSION"] = value + "\n"
    if not errors and not check:
        for name, text in updates.items():
            (root / name).write_text(text, encoding="utf-8")
        print(f"Release {value}: xu: aligned in {len(manifests)} manifests ({len(updates)} files updated)")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD", help="revision to compare with the working tree")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="read-only check (default)")
    mode.add_argument("--bump", action="store_true", help="initialize versions and bump changed modules once")
    mode.add_argument("--sync-release", action="store_true", help="align every manifest's xu: and product source version to VERSION")
    mode.add_argument("--check-release", action="store_true", help="check every manifest's xu: and product source version equals VERSION")
    mode.add_argument("--release-bump", choices=("patch", "minor", "major"), help="bump VERSION and align every release manifest")
    parser.add_argument("--kind", choices=("patch", "minor", "major"), default="patch")
    parser.add_argument("--allow-stable", action="store_true", help="explicitly opt in to a decided stable Xu release (only with --release-bump)")
    args = parser.parse_args()
    if args.allow_stable and not args.release_bump:
        parser.error("--allow-stable requires --release-bump")
    try:
        if args.sync_release or args.check_release or args.release_bump:
            errors = release(ROOT, args.release_bump, args.check_release, allow_stable=args.allow_stable)
        else:
            errors = process(ROOT, args.base, args.bump, args.kind)
    except (subprocess.CalledProcessError, ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print("Module versions OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
