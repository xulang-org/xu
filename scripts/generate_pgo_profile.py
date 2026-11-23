#!/usr/bin/env python3
"""
generate_pgo_profile.py: Utility to generate, merge, and inspect .xupgo Profile-Guided Optimization files for Xu.

Format specification:
fn <function_label>
<bb0_count> <bb1_count> <bb2_count> ...
fn <next_function_label>
...
"""

import sys
import os
import argparse
from typing import Dict, List

def parse_pgo_file(path: str) -> Dict[str, List[int]]:
    profiles = {}
    if not os.path.exists(path):
        return profiles
    current_fn = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("fn "):
                parts = line.split()
                if len(parts) >= 2:
                    current_fn = parts[1]
                    profiles[current_fn] = []
            elif current_fn is not None:
                counts = [int(x) for x in line.split() if x.isdigit()]
                profiles[current_fn].extend(counts)
                current_fn = None
    return profiles

def write_pgo_file(path: str, profiles: Dict[str, List[int]]):
    with open(path, "w", encoding="utf-8") as f:
        for fn_name, counts in profiles.items():
            f.write(f"fn {fn_name}\n")
            f.write(" ".join(str(c) for c in counts) + "\n")

def merge_pgo_profiles(p1: Dict[str, List[int]], p2: Dict[str, List[int]]) -> Dict[str, List[int]]:
    merged = dict(p1)
    for fn_name, counts2 in p2.items():
        if fn_name not in merged:
            merged[fn_name] = list(counts2)
        else:
            counts1 = merged[fn_name]
            max_len = max(len(counts1), len(counts2))
            res = []
            for i in range(max_len):
                c1 = counts1[i] if i < len(counts1) else 0
                c2 = counts2[i] if i < len(counts2) else 0
                res.append(c1 + c2)
            merged[fn_name] = res
    return merged

def main():
    parser = argparse.ArgumentParser(description="Xu PGO Profile Generator & Tool")
    parser.add_argument("--out", "-o", default="profile.xupgo", help="Output .xupgo file")
    parser.add_argument("--fn", help="Function label to set counts for")
    parser.add_argument("--counts", nargs="+", type=int, help="Basic block execution counts")
    parser.add_argument("--merge", nargs="+", help="Merge multiple .xupgo files")
    parser.add_argument("--dump", help="Dump and inspect a .xupgo file")
    args = parser.parse_args()

    if args.dump:
        p = parse_pgo_file(args.dump)
        print(f"PGO Profile: {args.dump} ({len(p)} functions)")
        for fn_name, counts in p.items():
            total = sum(counts)
            print(f"  {fn_name}: {counts} (total={total})")
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
        profiles[args.fn] = args.counts
        write_pgo_file(args.out, profiles)
        print(f"Updated {args.fn} with counts {args.counts} in {args.out}")
    elif not args.merge and not args.dump:
        # Default demo profile for testing
        profiles["_xu_main"] = [1000, 50, 950, 1000]
        write_pgo_file(args.out, profiles)
        print(f"Generated sample profile with _xu_main in {args.out}")

if __name__ == "__main__":
    main()
