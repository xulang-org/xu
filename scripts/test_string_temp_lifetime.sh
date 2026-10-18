#!/usr/bin/env bash
# Focused temporary-string ownership gate.
#
# The fixtures exercise three ownership boundaries that used to leak in both
# lowering paths: a discarded str(int), fresh concat operands/results, and a
# concat moved into an array.  Run both unoptimised and O1 MIR so the contract
# covers the optimizer's StoreLocal/Drop rewrites as well as the raw lowering.
set -euo pipefail

# Machine-readable boundary role: temporary-string product evidence.
BOUNDARY_LANE=product

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export XU_ROOT="$ROOT"
cd "$ROOT"
source "$ROOT/scripts/test_lib.sh"

XU=${XU:-}
GEN1=${XU_GEN1:-}
BUILD_TIMEOUT=${XU_STRING_TEMP_BUILD_TIMEOUT:-60}
RUN_TIMEOUT=${XU_STRING_TEMP_RUN_TIMEOUT:-15}
TMP=$(mktemp -d "${TMPDIR:-/tmp}/xu-string-temp.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

while [ "$#" -gt 0 ]; do
    case "$1" in
        --gen1=*) GEN1=${1#*=} ;;
        --gen1)
            if [ "$#" -lt 2 ] || [ -z "$2" ]; then
                echo "string temporary lifetime: --gen1 requires an executable path" >&2
                exit 2
            fi
            GEN1=$2
            shift
            ;;
        -h|--help)
            echo "usage: test_string_temp_lifetime.sh [--gen1=PATH|--gen1 PATH]"
            echo "  XU runs strict heap-ledger checks."
            echo "  --gen1 or XU_GEN1 optionally runs Gen1 O0/O1 parity."
            exit 0
            ;;
        *)
            echo "string temporary lifetime: unknown argument: $1" >&2
            exit 2
            ;;
    esac
    shift
done

if [ -n "$XU" ]; then
    XU=$(XU_SEED="$XU" "$ROOT/scripts/xu_host_seed.sh")
else
    XU=$("$ROOT/scripts/xu_host_seed.sh")
fi
[ -x "$XU" ] || {
    echo "string temporary lifetime: compiler is not executable: $XU" >&2
    exit 1
}

resolve_binary() {
    local base="$1"
    local candidate
    for candidate in "$base" "$base.xin" "$base.exe"; do
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

compile_fixture() {
    local opt="$1"
    local name="$2"
    local source="$ROOT/tests/fixtures/$name/main.xu"
    local base="$TMP/${name}_${opt}"
    local stderr_file="$TMP/${name}_${opt}.compile.stderr"
    local stdout_file="$TMP/${name}_${opt}.compile.stdout"
    XU_GEN1_HEAP_LEDGER=1 run_with_timeout "$BUILD_TIMEOUT" "$ROOT/scripts/run_product_compiler.sh" "$XU" build "$source" "-$opt" -o "$base" \
        >"$stdout_file" 2>"$stderr_file"

    local binary
    if ! binary=$(resolve_binary "$base"); then
        echo "string temporary lifetime: $name/$opt produced no executable" >&2
        sed -n '1,120p' "$stderr_file" >&2 || true
        return 1
    fi
    chmod +x "$binary" 2>/dev/null || true
    printf '%s\n' "$binary"
}

parse_stats() {
    local file="$1"
    python3 - "$file" <<'PY'
import json
import re
import sys

required = (
    "live_bytes", "peak_bytes", "allocs", "frees",
    "unknown_frees", "double_frees", "ledger_overflows",
)
values = {}
with open(sys.argv[1], encoding="utf-8", newline="") as stream:
    for line_no, raw in enumerate(stream, 1):
        fields = raw.rstrip("\r\n").split()
        if len(fields) == 1:
            pair = fields[0]
        elif len(fields) == 2:
            pair = fields[1]
        else:
            raise SystemExit(f"malformed stats line {line_no}")
        match = re.fullmatch(r"([a-z][a-z0-9_]*)=([0-9]+)", pair)
        if match is None:
            raise SystemExit(f"malformed stats field {line_no}")
        key, value = match.groups()
        if key not in required or key in values:
            raise SystemExit(f"unexpected/duplicate stats key {key}")
        values[key] = int(value)
missing = [key for key in required if key not in values]
if missing:
    raise SystemExit("missing stats keys: " + ", ".join(missing))
print(json.dumps(values, sort_keys=True))
PY
}

check_stats() {
    local name="$1"
    local stats_file="$2"
    local json_stats
    json_stats=$(parse_stats "$stats_file")
    python3 - "$name" "$json_stats" <<'PY'
import json
import sys

name, stats = sys.argv[1], json.loads(sys.argv[2])
if stats["live_bytes"] != 0 or stats["allocs"] != stats["frees"]:
    raise SystemExit(
        f"{name}: temporary string imbalance live={stats['live_bytes']} "
        f"allocs={stats['allocs']} frees={stats['frees']}"
    )
for key in ("unknown_frees", "double_frees", "ledger_overflows"):
    if stats[key] != 0:
        raise SystemExit(f"{name}: {key}={stats[key]}")
print(
    f"{name}: live={stats['live_bytes']} peak={stats['peak_bytes']} "
    f"allocs={stats['allocs']} frees={stats['frees']}"
)
PY
}

for opt in O0 O1; do
    for name in string_temp_discard string_concat_discard string_push_temp string_temp_lifetime string_alias_preserve; do
        binary=$(compile_fixture "$opt" "$name")
        out_file="$TMP/${name}_${opt}.out"
        err_file="$TMP/${name}_${opt}.stderr"
        rc=0
        if (cd "$TMP" && XU_HEAP_STATS=1 run_with_timeout "$RUN_TIMEOUT" "$binary") \
            >"$out_file" 2>"$err_file"; then
            rc=0
        else
            rc=$?
        fi
        if [ "$rc" -ne 0 ]; then
            echo "string temporary lifetime: $name/$opt exited $rc" >&2
            sed -n '1,120p' "$err_file" >&2 || true
            exit 1
        fi
        if ! diff -u "$ROOT/tests/fixtures/$name/expected.txt" "$out_file"; then
            echo "string temporary lifetime: $name/$opt stdout mismatch" >&2
            exit 1
        fi
        check_stats "$name/$opt" "$err_file"
    done
done

echo "string temporary lifetime: PASS (product O0/O1 strict ledger)"

# Gen1 keeps the heap-ledger capability disabled by default.  When a caller
# supplies a product/Gen1 compiler, still exercise both optimization levels
# and compare observable output; strict accounting remains the product
# contract above and is never enabled by mutating the shared source tree.
if [ -n "$GEN1" ]; then
    if [ ! -x "$GEN1" ]; then
        echo "string temporary lifetime: Gen1 compiler is not executable: $GEN1" >&2
        exit 1
    fi
    for opt in O0 O1; do
        for name in string_temp_discard string_concat_discard string_push_temp string_temp_lifetime string_alias_preserve; do
            source="$ROOT/tests/fixtures/$name/main.xu"
            base="$TMP/gen1_${name}_${opt}"
            compile_err="$TMP/gen1_${name}_${opt}.compile.stderr"
            if ! run_with_timeout "$BUILD_TIMEOUT" "$ROOT/scripts/run_product_compiler.sh" "$GEN1" build "-$opt" "$source" -o "$base" \
                >"$TMP/gen1_${name}_${opt}.compile.stdout" 2>"$compile_err"; then
                echo "string temporary lifetime: Gen1 $name/$opt compile failed" >&2
                sed -n '1,120p' "$compile_err" >&2 || true
                exit 1
            fi
            binary=$(resolve_binary "$base") || {
                echo "string temporary lifetime: Gen1 $name/$opt produced no executable" >&2
                exit 1
            }
            chmod +x "$binary" 2>/dev/null || true
            out_file="$TMP/gen1_${name}_${opt}.out"
            if ! run_with_timeout "$RUN_TIMEOUT" "$binary" >"$out_file" 2>"$TMP/gen1_${name}_${opt}.stderr"; then
                echo "string temporary lifetime: Gen1 $name/$opt run failed" >&2
                sed -n '1,120p' "$TMP/gen1_${name}_${opt}.stderr" >&2 || true
                exit 1
            fi
            if ! diff -u "$ROOT/tests/fixtures/$name/expected.txt" "$out_file"; then
                echo "string temporary lifetime: Gen1 $name/$opt stdout mismatch" >&2
                exit 1
            fi
            echo "Gen1 $name/$opt: PASS (parity; ledger capability remains off)"
        done
    done
fi
