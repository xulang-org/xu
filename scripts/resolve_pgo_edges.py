#!/usr/bin/env python3
"""Resolve normalized linux-x64 branch records against the exact sampled ELF.

Build with XU_PGO_MAP=1, then pass ELF, ELF.xumap, and a normalized trace.
The trace starts with 'sha256 HEX' from the sampled executable, followed by
'FROM TO' linked virtual addresses in hexadecimal, one taken transfer per row.
Output counts represent observed taken transfers only. LBR omits fall-through.
"""
import argparse
import hashlib
import struct
from collections import Counter
from pathlib import Path


def executable_segments(image):
    if image[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<HH", image, 16) != (2, 62):
        raise ValueError("expected a little-endian x86-64 ELF executable")
    offset = struct.unpack_from("<Q", image, 32)[0]
    size, count = struct.unpack_from("<HH", image, 54)
    segments = []
    for i in range(count):
        kind, flags, pos, va, _, length = struct.unpack_from("<IIQQQQ", image, offset + size * i)
        if kind == 1 and flags & 1 and pos + length <= len(image):
            segments.append((va, va + length, pos))
    return segments


def read_layout(image, mapping, digest):
    segments = executable_segments(image)

    def instruction(pc, size):
        for start, end, pos in segments:
            if start <= pc and pc + size <= end:
                offset = pos + pc - start
                return image[offset:offset + size]
        raise ValueError(f"address outside executable segment: {pc:#x}")

    edges = {}
    fallthrough = {}
    signatures = {}
    label = None
    with mapping.open() as stream:
        if stream.readline().split() != ["xupgo-map-v1", digest]:
            raise ValueError("map does not match the sampled executable")
        for line in stream:
            fields = line.split()
            if fields[:1] == ["fn"] and len(fields) == 3:
                _, label, cfg = fields
                signatures[label] = cfg
                branches = [b for b in cfg.split("-") if b.startswith("b")]
                continue
            ordinal, pc, yes, no = map(int, fields)
            if label is None or not 0 <= ordinal < len(branches):
                raise ValueError("invalid branch ordinal")
            code = instruction(pc, 6)
            if code[0] != 15 or not 128 <= code[1] < 144:
                raise ValueError(f"expected Jcc at {pc:#x}")
            following = pc + 6
            target = following + int.from_bytes(code[2:], "little", signed=True)
            if target not in (yes, no):
                raise ValueError(f"unexpected conditional target at {pc:#x}")
            if yes == no:
                continue
            edges[pc, target] = (label, ordinal, "true" if target == yes else "false")
            other = no if target == yes else yes
            if following == other:
                fallthrough[pc] = (label, ordinal, "false" if target == yes else "true")
            else:
                jump = instruction(following, 5)
                if jump[0] != 233 or following + 5 + int.from_bytes(jump[1:], "little", signed=True) != other:
                    raise ValueError(f"unexpected alternate successor at {pc:#x}")
                edges[following, other] = (label, ordinal, "false" if target == yes else "true")
    return edges, fallthrough, signatures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("elf", "mapping", "trace"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    image = args.elf.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    edges, _, _ = read_layout(image, args.mapping, digest)
    counts = Counter()
    unmatched = 0
    with args.trace.open() as stream:
        if stream.readline().split() != ["sha256", digest]:
            raise ValueError("trace does not match the sampled executable")
        for line in stream:
            source, target = (int(field, 16) for field in line.split())
            edge = edges.get((source, target))
            if edge is None:
                unmatched += 1
            else:
                counts[edge] += 1
    for edge, count in sorted(counts.items()):
        print(*edge, count)
    print("unmatched", unmatched)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, struct.error) as exc:
        raise SystemExit(str(exc))
