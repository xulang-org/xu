#!/usr/bin/env python3
"""Token-based Phase C migration; defaults to this session's source ownership.

Pass explicit files/directories to reuse in another checkout. Only .xu files
are selected, never embedded strings in Python/shell/docs. Review those as code
fixtures separately: negative and compatibility fixtures must keep their input.
Use --exclude for frozen sources or historical/negative .xu fixtures. Dry-run is
the default; --write applies edits. Comments, strings, and diagnostics are opaque.
An exact trailing `// phase-c: keep-legacy` preserves a frozen source line.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    kind: str


def tokens(source: str) -> list[Token]:
    """Mirror Xu's //, non-nesting /* */, escaped double quotes and raw `...`.

    Keep literals as opaque tokens (rather than dropping them), so patterns
    cannot accidentally match across a string. Single quotes are punctuation:
    Xu rejects single-quoted strings and spells lifetimes as `&a T`.
    """
    result = []
    i = 0
    while i < len(source):
        start = i
        c = source[i]
        if c.isspace():
            i += 1
            continue
        if source.startswith("//", i):
            end = source.find("\n", i + 2)
            i = len(source) if end < 0 else end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise ValueError(f"unterminated block comment at offset {i}")
            i = end + 2
            continue
        if c in ('"', '`'):
            i += 1
            while i < len(source):
                if source[i] == c:
                    i += 1
                    break
                if c == '"' and source[i] == "\\":
                    i += 2
                else:
                    i += 1
            else:
                raise ValueError(f"unterminated literal at offset {start}")
            result.append(Token(source[start:i], start, i, "literal"))
            continue
        if c.isascii() and (c.isalpha() or c == "_"):
            i += 1
            while i < len(source) and source[i].isascii() and (source[i].isalnum() or source[i] == "_"):
                i += 1
            kind = "ident"
        elif source.startswith(":=", i):
            i += 2
            kind = "punct"
        else:
            i += 1
            kind = "punct"
        result.append(Token(source[start:i], start, i, kind))
    return result


def trivia(source: str, start: int, end: int) -> str:
    gap = source[start:end]
    return "" if not gap.strip() else gap


def migrate(source: str) -> tuple[str, Counter]:
    ts = tokens(source)
    edits = []
    counts = Counter()
    for i, t in enumerate(ts):
        if t.text != "mut" or t.kind != "ident":
            continue
        line_end = source.find("\n", t.end)
        if line_end < 0:
            line_end = len(source)
        if source[t.end:line_end].rstrip().endswith("// phase-c: keep-legacy"):
            continue
        prev = ts[i - 1] if i else None
        nxt = ts[i + 1] if i + 1 < len(ts) else None
        after = ts[i + 2] if i + 2 < len(ts) else None
        if prev and prev.text == "&":
            # &mut T / &mut a T -> $&T / $&a T. Preserve comment trivia.
            edits.append((prev.start, nxt.start if nxt else t.end,
                          "$&" + trivia(source, prev.end, t.start)
                          + trivia(source, t.end, nxt.start if nxt else t.end)))
            counts["reference_type"] += 1
        elif nxt and nxt.text == "&":
            if after and after.text == "*":
                # Writable expectation at call/type sites supplies exclusivity.
                edits.append((t.start, nxt.start, trivia(source, t.end, nxt.start)))
                counts["explicit_reborrow"] += 1
            elif prev and prev.text == "*":
                raise ValueError(f"review dereference of writable borrow at offset {prev.start}")
            else:
                edits.append((t.start, nxt.start, "$" + trivia(source, t.end, nxt.start)))
                counts["writable_borrow"] += 1
        elif nxt and nxt.kind == "ident" and after and (
            after.text == ":=" or (prev and prev.text == "let" and after.text == ":")
        ):
            edits.append((t.start, nxt.start, "$" + trivia(source, t.end, nxt.start)))
            counts["mutable_binding"] += 1
        else:
            raise ValueError(f"unclassified code token 'mut' at offset {t.start}")
    edits.sort()
    for left, right in zip(edits, edits[1:]):
        if left[1] > right[0]:
            raise ValueError(f"overlapping migrations at offset {right[0]}")
    for start, end, replacement in reversed(edits):
        source = source[:start] + replacement + source[end:]
    return source, counts


def self_test() -> None:
    cases = [
        ("mut x := 1; let mut y: int = 2", "$x := 1; let $y: int = 2"),
        ("fn f(p &mut a T) &mut T { << p }", "fn f(p $&a T) $&T { << p }"),
        ("mut r := mut &x; f(mut &*r)", "$r := $&x; f(&*r)"),
        ('"mut x := \\" &mut T" // mut y := 2\nmut x := 3',
         '"mut x := \\" &mut T" // mut y := 2\n$x := 3'),
        ('`mut x := 1\n&mut T` /* mut &x */ mut x := 2',
         '`mut x := 1\n&mut T` /* mut &x */ $x := 2'),
        ("mut /*binding*/ x := 2", "$ /*binding*/ x := 2"),
        ("& /*type*/ mut /*life*/ a T", "$& /*type*/  /*life*/ a T"),
        ("pub fn f(p $&int) { $x := 1; f(p); f(&*p) }",
         "pub fn f(p $&int) { $x := 1; f(p); f(&*p) }"),
        ('mut "barrier" x := 1', None),
        ("*mut &x", None),
        ("mut anchor := 0 // phase-c: keep-legacy\nmut x := 1",
         "mut anchor := 0 // phase-c: keep-legacy\n$x := 1"),
        ('"unterminated', None),
        ('/* unterminated', None),
    ]
    for source, expected in cases:
        try:
            actual, _ = migrate(source)
        except ValueError:
            assert expected is None, source
        else:
            assert expected is not None and actual == expected, (source, actual, expected)
            assert migrate(actual)[0] == actual
            # Independent protection check: every literal survives verbatim.
            assert [t.text for t in tokens(source) if t.kind == "literal"] == [
                t.text for t in tokens(actual) if t.kind == "literal"]
    print(f"PASS {len(cases)} token migration cases (including idempotence)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 if migrations remain")
    ap.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    ap.add_argument("--report", type=Path, help="write per-file counts as JSON")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.write and args.check:
        ap.error("--write and --check are mutually exclusive")
    paths = args.paths or [Path(p) for p in ("src/xu", "src/cmd", "src/internal", "scripts")]
    files = set()
    for path in paths:
        if not path.exists():
            ap.error(f"path does not exist: {path}")
        files.update(path.rglob("*.xu") if path.is_dir() else [path])
    report = {}
    pending = []
    totals = Counter()
    for path in sorted(files):
        if path.suffix != ".xu" or any(fnmatch.fnmatch(path.as_posix(), g) for g in args.exclude):
            continue
        with path.open(encoding="utf-8", newline="") as f:
            source = f.read()
        try:
            migrated, counts = migrate(source)
        except ValueError as error:
            ap.error(f"{path}: {error}; use --exclude if this is protected test data")
        if migrated == source:
            continue
        # Do not write any files until every candidate has been classified.
        pending.append((path, migrated))
        report[path.as_posix()] = dict(counts)
        totals.update(counts)
    if args.write:
        for path, migrated in pending:
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write(migrated)
    result = {"changed_files": len(pending), "replacements": sum(totals.values()),
              "counts": dict(totals), "files": report}
    if args.report:
        args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, ensure_ascii=False))
    return 1 if args.check and pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
