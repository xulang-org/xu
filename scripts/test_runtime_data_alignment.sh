#!/usr/bin/env bash
# Regression for hosted runtime data alignment (M35/MN): byte-string
# diagnostics/statistics are emitted before the waiter pool and scheduler
# globals.  On arm64 an unaligned LDAR/atomic access can terminate a channel
# program with SIGBUS before it ever reaches user code.
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
export XU_ROOT="$ROOT"
cd "$ROOT"

HOST_SEED_RESOLVER="$ROOT/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$ROOT/scripts/run_product_compiler.sh"

XU=${XU:-}
if [ -n "$XU" ]; then
    XU=$(XU_SEED="$XU" "$HOST_SEED_RESOLVER")
else
    XU=$("$HOST_SEED_RESOLVER")
fi
[ -x "$XU" ] || {
    echo "runtime alignment: compiler not found or not executable: $XU" >&2
    exit 1
}

FIXTURE="$ROOT/tests/fixtures/channel_blocking_string/main.xu"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
OBJ="$TMP/channel.xuobj"

# Keep the object target fixed so this check remains meaningful when invoked
# from a non-macOS host (the executable run below is host-gated).
"$PRODUCT_COMPILER_RUNNER" "$XU" build "$FIXTURE" --target macos-arm64 --emit-obj -o "$OBJ"

python3 - "$OBJ" <<'PY'
from pathlib import Path
import sys

raw = Path(sys.argv[1]).read_bytes()
if raw[:8] != b"XUOBJ\x01\0\0":
    raise SystemExit("runtime alignment: bad XUOBJ magic")
pos = 8

def u8() -> int:
    global pos
    value = raw[pos]
    pos += 1
    return value

def u16() -> int:
    global pos
    value = int.from_bytes(raw[pos:pos + 2], "little")
    pos += 2
    return value

def u32() -> int:
    global pos
    value = int.from_bytes(raw[pos:pos + 4], "little")
    pos += 4
    return value

def string() -> str:
    n = u16()
    global pos
    value = raw[pos:pos + n].decode()
    pos += n
    return value

_os, _arch, _pad = u8(), u8(), u16()
string()  # module
for _ in range(u32()):
    string()  # export name
    string()  # export label
    u8()      # return type
    nparams = u8()
    pos += nparams

labels = {}
for _ in range(u32()):
    is_data = u8() & 1
    offset = u32()
    labels[string()] = (is_data, offset)

required = (
    "_rt_wn_pool",
    "_rt_wn_pool_n",
    "_rt_xu_head",
    "_rt_xu_tail",
    "_rt_xu_len",
    "_rt_xu_wake",
    "_rt_xu_nwork",
    "_rt_ms",
    "_rt_argv_arr",
    "_rt_pagesize_slot",
    "_rt_env_arr",
)
for name in required:
    if name not in labels:
        raise SystemExit(f"runtime alignment: missing data label {name}")
    is_data, offset = labels[name]
    if not is_data or offset % 8:
        raise SystemExit(
            f"runtime alignment: {name} offset={offset} (expected 8-byte alignment)"
        )
print("runtime alignment: PASS", ", ".join(f"{name}={labels[name][1]}" for name in required))
PY

if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
    BIN="$TMP/channel.xin"
    "$PRODUCT_COMPILER_RUNNER" "$XU" build "$FIXTURE" --target macos-arm64 -O1 -o "$BIN"
    chmod +x "$BIN"
    python3 - "$BIN" <<'PY'
import subprocess
import sys

try:
    completed = subprocess.run(
        [sys.argv[1]],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        check=False,
    )
except subprocess.TimeoutExpired as exc:
    raise SystemExit(f"runtime alignment: channel fixture timed out: {exc}")
if completed.returncode != 0:
    raise SystemExit(
        f"runtime alignment: channel fixture exit={completed.returncode} "
        f"stderr={completed.stderr!r}"
    )
if completed.stdout != "ok\n1\n":
    raise SystemExit(
        f"runtime alignment: unexpected stdout={completed.stdout!r}"
    )
print("runtime alignment: arm64 channel run PASS")
PY
else
    echo "runtime alignment: object check PASS (arm64 runtime run skipped on $(uname -s)/$(uname -m))"
fi
