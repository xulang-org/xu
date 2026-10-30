#!/usr/bin/env python3
"""Retarget a disposable hosted seed's frozen driver injection to Phase C.

The published seed remains unchanged. Its two live strings retain their byte
lengths, and its self-replicating source uses string_from_byte(36) so the old
payload quoting routine never sees an unescaped dollar. Existing comment
padding absorbs the source edit without moving code, data, or string offsets.
Seeds without this legacy payload pass through unchanged; unfamiliar layouts
fail closed. This bridge changes no parser or instruction bytes.
"""

import argparse
import hashlib
from pathlib import Path
import re
import sys


LEGACY = b"    mut mod_map := types.new_strmap()"
CURRENT = b"    $mod_map := types.new_strmap() //"
CORE_START = b"@main\n#xu/scanner\n#xu/parser\n#xu/ast\n// Generated."
CORE_END = b"\n<<\n}\n"
# Published hosted seed containers: ELF64 LE (Linux), Mach-O 64 LE (macOS),
# and PE/COFF (Windows). The injected payload is identical in all three.
SEED_MAGICS = (b"\x7fELF\x02\x01", b"\xcf\xfa\xed\xfe", b"MZ")


def retarget(data: bytes) -> bytes:
    if LEGACY not in data:
        return data
    if not data.startswith(SEED_MAGICS) or data.count(LEGACY) != 4 or data.count(CORE_START) != 1:
        raise ValueError("unsupported legacy seed injection layout")
    start = data.index(CORE_START)
    end = data.index(CORE_END, start) + len(CORE_END)
    core = data[start:end]
    if core.count(LEGACY) != 2 or len(LEGACY) != len(CURRENT):
        raise ValueError("unsupported legacy seed payload anchors")
    # These occurrences are inside Xu string literals. Construct the dollar
    # at runtime instead of introducing interpolation into the quoted payload.
    quoted = b'    " + string_from_byte(36) + "mod_map := types.new_strmap() //'
    updated = core.replace(LEGACY, quoted)
    padding = re.search(rb"\n//( +)\n<<\n}\n$", updated)
    growth = len(updated) - len(core)
    if padding is None or len(padding[1]) <= growth:
        raise ValueError("missing seed payload comment padding")
    updated = updated[:padding.start(1)] + padding[1][growth:] + updated[padding.end(1):]
    result = data[:start].replace(LEGACY, CURRENT) + updated + data[end:]
    if len(result) != len(data) or LEGACY in result:
        raise ValueError("seed bridge did not preserve layout/replace all anchors")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    seed = args.seed.resolve()
    original = seed.read_bytes()
    updated = retarget(original)
    if updated == original:
        print(seed)
        return
    destination = args.destination.resolve()
    if destination == seed:
        raise ValueError("seed bridge destination must differ from the published seed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(updated)
    destination.chmod(0o755)
    print(destination)
    print("seed_phase_c_bridge: retargeted disposable seed sha256=" + hashlib.sha256(updated).hexdigest(), file=sys.stderr)


if __name__ == "__main__":
    main()
