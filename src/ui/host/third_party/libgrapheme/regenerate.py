#!/usr/bin/env python3
"""Regenerate the C++17 character-only adapter from unpacked libgrapheme 3.0.0.
Run upstream `make gen/character.h` first. No network or build-time dependency.
"""
from pathlib import Path
import hashlib
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: regenerate.py PATH_TO_UNPACKED_LIBGRAPHEME_3_0_0")
root = Path(sys.argv[1])
destination = Path(__file__).resolve().parent
source = (root / "src/character.c").read_text()
if "UNICODE_VERSION = 17.0.0" not in (root / "Makefile").read_text():
    raise SystemExit("expected libgrapheme 3.0.0 / Unicode 17.0.0")
original_hash = hashlib.sha256(source.encode()).hexdigest()
if original_hash != "9c5df056356b89af6fa10ddfb278efca320e4fd686924fd6b7c0db6053290de8":
    raise SystemExit("upstream character.c does not match the pinned source")
table_data = (root / "gen/character.h").read_text().encode()
if hashlib.sha256(table_data).hexdigest() != "7b99193052892cdb7cc005a9465c17b9798649df2bde7f37c45ffdd17156b218":
    raise SystemExit("generated Unicode character table does not match")
source = source[:source.index("\nstatic size_t\nnext_character_break")]
source = re.sub(r"^#include.*\n", "", source, flags=re.M)

def table(match):
    name, size, body = match.groups()
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    result = f"static constexpr auto {name} = [] {{\n  std::array<uint_least32_t, {size}> result{{}};\n"
    for item in body.split(","):
        if not item.strip():
            continue
        entry = re.fullmatch(r"\s*\[([^\]]+)\]\s*=\s*(.*?)\s*", item, re.S)
        if not entry:
            raise SystemExit("unexpected upstream table syntax")
        result += f"  result[{entry[1]}] = {entry[2]};\n"
    return result + "  return result;\n}();"

source, count = re.subn(r"static const uint_least32_t (\w+)\[([^\]]+)\] = \{(.*?)\n\};", table, source, flags=re.S)
if count != 5:
    raise SystemExit("unexpected upstream character table count")
source = source.replace("cp0_prop = state.prop;", "cp0_prop = (enum char_break_property)state.prop;")
source = source.replace("bool\ngrapheme_is_character_break", "static inline bool\ncharacter_break")
source = source.replace("likely(", "XU_GRAPHEME_LIKELY(")
source = "\n".join(line.rstrip() for line in source.splitlines()) + "\n"
(destination / "character.inc").write_text("// Generated C++17 character-only adapter; see SOURCE and regenerate.py.\n" + source)
(destination / "character_data.h").write_bytes(table_data)
for name, target in [("LICENSE", "LICENSE"), ("data/LICENSE", "UNICODE-LICENSE")]:
    (destination / target).write_bytes((root / name).read_bytes())
notice = (destination / "LICENSE").read_text() + "\n" + (destination / "UNICODE-LICENSE").read_text()
if ")XULICENSE" in notice:
    raise SystemExit("unexpected license delimiter")
(destination / "notice.inc").write_text('R"XULICENSE(' + notice + ')XULICENSE"\n')
print("upstream character.c sha256=" + original_hash)
print("generated table sha256=" + hashlib.sha256((destination / "character_data.h").read_bytes()).hexdigest())
