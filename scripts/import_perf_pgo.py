#!/usr/bin/env python3
"""Import Linux x86-64 user-mode all-branch stacks into a Xu edge profile.

On the sampling host, save the ELF digest and absolute path at recording time:
    sha256sum "$(realpath ./program)" > sampled.sha256
    perf record -e cycles:u -j any,u -o perf.data -- "$(realpath ./program)"
    perf script --show-kernel-path -i perf.data -F brstack,dso > stacks.txt
Then run:
    python3 scripts/import_perf_pgo.py program program.xumap sampled.sha256 stacks.txt -o run.xupgo

Each nonempty line is one sample, newest branch first. ET_EXEC raw IPs are
linked virtual addresses. The DSO on each endpoint comes from perf's thread
mapping. Use all user branches; call-only or conditional-only stacks cannot
establish straight-line execution between records. Counts are sample weights.
"""
import argparse
from bisect import bisect_left
from collections import Counter
import hashlib
from pathlib import Path
import re
import struct

from generate_pgo_profile import Record, write_pgo_file
from resolve_pgo_edges import executable_segments, read_layout


ENTRY = re.compile(
    r"\s*0x([0-9a-fA-F]+)\s*\(([^()]*)\)/0x([0-9a-fA-F]+)\s*\(([^()]*)\)"
    r"/([^\s]+)"
)


def entries(line, dso):
    pos = 0
    while pos < len(line):
        match = ENTRY.match(line, pos)
        if match is None:
            raise ValueError("expected perf script -F brstack,dso with full DSO paths")
        src, src_dso, dst, dst_dso, flags = match.groups()
        fields = flags.split("/")
        if len(fields) < 4:
            raise ValueError("incomplete perf branch flags")
        valid = (fields[0] in {"-", "M", "P"} and fields[1:3] == ["-", "-"]
                 and (len(fields) < 6 or fields[5] in {"-", "CORRECT_PATH", "NON_SPEC_CORRECT_PATH", "SPEC_CORRECT_PATH"}))
        yield (int(src, 16) if src_dso == dso else None,
               int(dst, 16) if dst_dso == dso else None, valid)
        pos = match.end()


def import_stacks(stream, dso, image, layout):
    taken, falls, cfg = layout
    sites = sorted(falls)
    segments = executable_segments(image)
    counts = Counter()
    stats = Counter()
    for number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        newer = None
        try:
            for older in entries(line.rstrip(), dso):
                if newer is not None and older[2] and newer[2]:
                    start, end = older[1], newer[0]
                    # Count a whole interval or discard it. Excluding the
                    # oldest transfer avoids counting taken edges without
                    # equal coverage of preceding fall-through opportunities.
                    if (start is not None and end is not None and 0 <= end - start <= 16384
                            and any(lo <= start <= end < hi for lo, hi, _ in segments)):
                        stats["intervals"] += 1
                        edge = taken.get((end, newer[1]))
                        if edge:
                            counts[edge] += 1
                            stats["taken"] += 1
                        for pc in sites[bisect_left(sites, start):bisect_left(sites, end)]:
                            counts[falls[pc]] += 1
                            stats["fallthrough"] += 1
                newer = older
        except ValueError as exc:
            raise ValueError(f"sample line {number}: {exc}") from exc
    profiles = {}
    for (label, ordinal, direction), count in counts.items():
        if label not in profiles:
            branches = sum(b.startswith("b") for b in cfg[label].split("-"))
            profiles[label] = Record(cfg[label], [0] * (2 * branches))
        profiles[label].counts[2 * ordinal + (direction == "false")] += count
    return profiles, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for arg in ("elf", "mapping", "manifest", "stacks"):
        parser.add_argument(arg, type=Path)
    parser.add_argument("-o", required=True, type=Path)
    args = parser.parse_args()
    image = args.elf.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    checksum, dso = args.manifest.read_text().rstrip("\n").split(maxsplit=1)
    if checksum != digest or not dso.startswith("/"):
        raise ValueError("recording manifest must contain the sampled ELF SHA-256 and absolute path")
    layout = read_layout(image, args.mapping, digest)
    with args.stacks.open() as stream:
        profiles, stats = import_stacks(stream, dso, image, layout)
    if not profiles:
        raise ValueError("no attributable MIR edges in complete sample intervals")
    write_pgo_file(args.o, profiles)
    print(f"{stats['intervals']} intervals, {stats['taken']} taken, {stats['fallthrough']} fall-through")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, struct.error) as exc:
        raise SystemExit(str(exc))
