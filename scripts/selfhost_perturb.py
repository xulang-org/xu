#!/usr/bin/env python3
"""Produce a semantically neutral perturbation of the hosted compiler sources.

The hosted compiler has repeatedly been broken by *adding* a function or a
counter to one of its own source files (RUNTIME_EFFICIENCY_PLAN.md p27/p40/
p41/p47: struct intern or the checker's integer loops miscompile).  Such a
failure depends on the number/order of declarations, not on their meaning,
so it hides from the fixed-point gate: a deterministic miscompile is
self-consistent (Gen3 == Gen4 still holds).

This module copies ``src/`` into an output root and applies declaration-count
and declaration-order perturbations that must not change the behaviour of any
live code:

* append unused functions (each with a distinct string literal, shifting the
  intern pool and function numbering);
* append unused structs (shifting struct tag numbering; see the 101st-struct
  collision fixed in 2026-08-31);
* swap two adjacent top-level ``fn`` blocks (declaration order is not
  significant in Xu).

Everything is driven by ``--random-seed`` so a failing round is reproducible
from the printed manifest.  ``scripts/selfhost_perturb.sh`` is the driver that
compiles the perturbed tree and checks the resulting compiler.

Lane: dual (hosted seed only; never installs bin/xu; not fixed-point proof).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from pathlib import Path

LANE = "dual"

FN_START = re.compile(r"^(?:pub\s+)?fn\s")
TOP_CLOSE = "}"
SKIP_BASENAMES = {"main.xu"}
MIN_LINES = 120


def top_level_fn_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Return (start, end) inclusive line indexes of top-level fn blocks.

    Sources are `xu fmt` formatted: a top-level function opens on a line that
    starts with ``fn``/``pub fn`` and closes on the first later line that is
    exactly ``}`` at column 0.  Single-line bodies (``fn f() int { << 1 }``)
    close on their own line.
    """

    blocks: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if FN_START.match(line):
            stripped = line.rstrip()
            if stripped.endswith("}") and stripped.count("{") == stripped.count("}"):
                blocks.append((i, i))
                i += 1
                continue
            j = i + 1
            while j < n and lines[j].rstrip("\n") != TOP_CLOSE:
                j += 1
            if j >= n:
                break
            blocks.append((i, j))
            i = j + 1
            continue
        i += 1
    return blocks


def candidate_files(src_root: Path) -> list[Path]:
    files: list[Path] = []
    for sub in ("cmd/compile", "xu/types", "xu/parser", "xu/scanner", "xu/ast"):
        d = src_root / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.xu")):
            if p.name in SKIP_BASENAMES:
                continue
            try:
                count = sum(1 for _ in p.open(encoding="utf-8"))
            except OSError:
                continue
            if count >= MIN_LINES:
                files.append(p)
    return files


def unused_fn(tag: str, k: int) -> str:
    lit = f"xu_perturb_{tag}_{k}"
    return (
        f"fn xu_perturb_{tag}_{k}(x int) int {{\n"
        f'    s := "{lit}"\n'
        f"    if x > {k} {{\n"
        f"        << x + s.len\n"
        f"    }}\n"
        f"    << x - {k}\n"
        f"}}\n"
    )


def unused_struct(tag: str, k: int) -> str:
    return (
        f"struct XuPerturb{tag}S{k} {{\n"
        f"    a int\n"
        f"    b string\n"
        f"    c bool\n"
        f"}}\n"
    )


def perturb_file(path: Path, rng: random.Random, tag: str, fns: int, structs: int,
                 reorder: bool) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    record: dict = {"file": str(path), "fns": fns, "structs": structs, "swaps": []}

    if reorder:
        blocks = top_level_fn_blocks(lines)
        if len(blocks) >= 2:
            idx = rng.randrange(len(blocks) - 1)
            (a0, a1), (b0, b1) = blocks[idx], blocks[idx + 1]
            # Only swap when the two blocks are adjacent apart from blank /
            # comment lines, so no unrelated declaration is displaced.
            between = lines[a1 + 1:b0]
            if all(s.strip() == "" or s.lstrip().startswith("//") for s in between):
                first = lines[a0:a1 + 1]
                second = lines[b0:b1 + 1]
                # Comments between the blocks belong to the second block;
                # keep them in front of it so only declaration order moves.
                lines = lines[:a0] + between + second + ["\n"] + first + lines[b1 + 1:]
                record["swaps"].append([a0 + 1, a1 + 1, b0 + 1, b1 + 1])

    if lines and not lines[-1].endswith("\n"):
        lines[-1] = lines[-1] + "\n"
    appended = []
    for k in range(structs):
        appended.append("\n" + unused_struct(tag, k))
    for k in range(fns):
        appended.append("\n" + unused_fn(tag, k))
    path.write_text("".join(lines) + "".join(appended), encoding="utf-8")
    return record


def inject_syntax_error(path: Path) -> int:
    """Append an unparsable declaration; return its 1-based line number."""
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    line_no = text.count("\n") + 2
    text += "\nfn xu_perturb_self_test( {\n"
    path.write_text(text, encoding="utf-8")
    return line_no


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src-root", required=True, help="repository root containing src/")
    ap.add_argument("--out-root", required=True, help="output root; src/ is copied below it")
    ap.add_argument("--random-seed", type=int, required=True)
    ap.add_argument("--files", default="", help="comma-separated src-relative files (default: random sample)")
    ap.add_argument("--nfiles", type=int, default=3, help="files to perturb when --files is empty")
    ap.add_argument("--fns", type=int, default=4, help="unused functions appended per file")
    ap.add_argument("--structs", type=int, default=2, help="unused structs appended per file")
    ap.add_argument("--no-reorder", action="store_true", help="do not swap adjacent top-level fn blocks")
    ap.add_argument("--self-test", action="store_true",
                    help="also inject a syntax error so the driver can prove it compiles the perturbed tree")
    ap.add_argument("--manifest", default="", help="write the perturbation manifest (JSON) here")
    args = ap.parse_args(argv)

    src_root = Path(args.src_root).resolve()
    out_root = Path(args.out_root).resolve()
    src = src_root / "src"
    if not (src / "cmd" / "compile" / "main.xu").is_file():
        print(f"selfhost_perturb: {src} is not the Xu source tree", file=sys.stderr)
        return 2
    if out_root == src_root:
        print("selfhost_perturb: --out-root must differ from --src-root", file=sys.stderr)
        return 2

    dest = out_root / "src"
    if dest.exists():
        shutil.rmtree(dest)
    out_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, symlinks=False,
                    ignore=shutil.ignore_patterns("*.xin", "*.exe", "*.o", "*.a"))

    rng = random.Random(args.random_seed)
    if args.files:
        chosen = [dest / rel.strip().removeprefix("src/") for rel in args.files.split(",") if rel.strip()]
        for p in chosen:
            if not p.is_file():
                print(f"selfhost_perturb: no such source file {p}", file=sys.stderr)
                return 2
    else:
        pool = candidate_files(dest)
        if not pool:
            print("selfhost_perturb: no candidate files", file=sys.stderr)
            return 2
        chosen = rng.sample(pool, min(args.nfiles, len(pool)))

    tag = f"r{args.random_seed}"
    records = []
    for i, path in enumerate(sorted(chosen)):
        rec = perturb_file(path, rng, f"{tag}f{i}", args.fns, args.structs, not args.no_reorder)
        rec["file"] = str(path.relative_to(out_root))
        records.append(rec)
    self_test: dict | None = None
    if args.self_test:
        target = sorted(chosen)[0]
        self_test = {
            "file": str(target.relative_to(out_root)),
            "line": inject_syntax_error(target),
        }

    manifest = {
        "lane": LANE,
        "random_seed": args.random_seed,
        "src_root": str(src_root),
        "out_root": str(out_root),
        "reorder": not args.no_reorder,
        "self_test": self_test,
        "files": records,
    }
    text = json.dumps(manifest, indent=2, sort_keys=True)
    if args.manifest:
        Path(args.manifest).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
