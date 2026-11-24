#!/usr/bin/env python3
"""
generate_pgo_profile.py: Utility to generate, merge, and inspect .xupgo Profile-Guided Optimization files for Xu.

Format specification:
fn <function_label>
<bb0_count> <bb1_count> <bb2_count> ...
fn <function_label> <cfg>
<true_count> <false_count> ... (one pair per branch, in pre-layout block order)

Obtain <cfg> by building with XU_DUMP_PGO_CFG=<function_label>.
"""

from dataclasses import dataclass
from itertools import zip_longest
import re
import os
import argparse
from typing import Dict, List

@dataclass
class Record:
    cfg: str
    counts: List[int]

    def validate(self):
        if any(value < 0 for value in self.counts):
            raise ValueError("counts must be nonnegative")
        if self.cfg:
            blocks = self.cfg.split("-")
            if not all(re.fullmatch(r"b[0-9]+\.[0-9]+|j[0-9]+|r|o", block) for block in blocks):
                raise ValueError("invalid CFG signature")
            if len(self.counts) != 2 * sum(block.startswith("b") for block in blocks):
                raise ValueError("expected a true/false count pair for each branch")


def parse_pgo_file(path: str) -> Dict[str, Record]:
    profiles = {}
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            header = line.split()
            if not header:
                continue
            if len(header) not in (2, 3) or header[0] != "fn":
                raise ValueError(f"{path}: invalid profile header")
            line = next(stream, None)
            if line is None:
                raise ValueError(f"{path}: missing counts")
            record = Record(header[2] if len(header) == 3 else "", list(map(int, line.split())))
            record.validate()
            profiles.setdefault(header[1], record)
    return profiles


def write_pgo_file(path: str, profiles: Dict[str, Record]):
    with open(path, "w", encoding="utf-8") as stream:
        for label, record in profiles.items():
            header = f"fn {label}"
            if record.cfg:
                header += " " + record.cfg
            print(header, file=stream)
            print(*record.counts, file=stream)


def merge_pgo_profiles(first, second):
    merged = dict(first)
    for label, record in second.items():
        if label in merged:
            previous = merged[label]
            if previous.cfg != record.cfg:
                raise ValueError(f"{label}: incompatible profile formats or CFG signatures")
            counts = [a + b for a, b in zip_longest(previous.counts, record.counts, fillvalue=0)]
            record = Record(record.cfg, counts)
        merged[label] = record
    return merged

def main():
    parser = argparse.ArgumentParser(description="Xu PGO Profile Generator & Tool")
    parser.add_argument("--out", "-o", default="profile.xupgo", help="Output .xupgo file")
    parser.add_argument("--fn", help="Function label to set counts for")
    parser.add_argument("--counts", nargs="+", type=int, help="Basic block execution counts")
    parser.add_argument("--merge", nargs="+", help="Merge multiple .xupgo files")
    parser.add_argument("--dump", help="Dump and inspect a .xupgo file")
    parser.add_argument("--cfg", help="Pre-layout CFG signature for true/false edge counts")
    args = parser.parse_args()
    if args.cfg and not (args.fn and args.counts):
        parser.error("--cfg requires --fn and --counts")

    if args.dump:
        p = parse_pgo_file(args.dump)
        print(f"PGO Profile: {args.dump} ({len(p)} functions)")
        for fn_name, record in p.items():
            counts = record.counts
            total = sum(counts)
            print(f"  {fn_name}: {counts} (total={total}, cfg={record.cfg or 'legacy'})")
        return

    if args.merge:
        merged = {}
        for f in args.merge:
            p = parse_pgo_file(f)
            merged = merge_pgo_profiles(merged, p)
        write_pgo_file(args.out, merged)
        print(f"Merged {len(args.merge)} profiles into {args.out} ({len(merged)} functions)")
        return

    profiles = {}
    if os.path.exists(args.out):
        profiles = parse_pgo_file(args.out)

    if args.fn and args.counts:
        record = Record(args.cfg or "", args.counts)
        record.validate()
        profiles[args.fn] = record
        write_pgo_file(args.out, profiles)
        print(f"Updated {args.fn} with counts {args.counts} in {args.out}")
    elif not args.merge and not args.dump:
        # Default demo profile for testing
        profiles["_xu_main"] = Record("", [1000, 50, 950, 1000])
        write_pgo_file(args.out, profiles)
        print(f"Generated sample profile with _xu_main in {args.out}")

if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))
