#!/usr/bin/env bash
# Hosted lifetime-policy regression.
#
# The hosted runtime has two deliberately different lifetime classes:
#
#   * ordinary temporary values (for example strings built by heap_stats),
#     which must return the allocator ledger to zero; and
#   * process-scoped scheduler/channel metadata (G headers/stacks, channel
#     descriptors and the bounded MC waiter pool), which cannot be reclaimed
#     from a still-running G and is therefore retained until process exit.
#
# This gate keeps those classes separate.  It does not weaken the seven-field
# XU_HEAP_STATS ABI and never attempts to free a live G stack.
set -euo pipefail

# Machine-readable boundary role: hosted lifetime-policy oracle evidence.
BOUNDARY_LANE=oracle

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"
source "$ROOT/scripts/test_lib.sh"

XU=${XU:-"$BOOTSTRAP_ROOT/target/debug/xu"}
BUILD_TIMEOUT=${XU_LIFETIME_BUILD_TIMEOUT:-60}
RUN_TIMEOUT=${XU_LIFETIME_RUN_TIMEOUT:-15}
TMP=$(mktemp -d "${TMPDIR:-/tmp}/xu-lifetime-policy.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

if [ ! -x "$XU" ]; then
    cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu --bin xu
fi
if [ ! -x "$XU" ]; then
    echo "runtime lifetime policy: compiler is not executable: $XU" >&2
    exit 1
fi
if ! XU=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$XU" \
    "$ROOT/scripts/xu_host_seed.sh"); then
    echo "runtime lifetime policy: compiler is not the canonical frozen primer" >&2
    exit 1
fi

# Bootstrap accepts `xu input.xu -o out`; the product CLI accepts
# `xu build input.xu -o out`.  Detect the advertised form, retaining the
# direct form as the default for old wrappers.
HELP_TEXT=""
HELP_RC=0
HELP_TEXT=$(run_with_timeout 5 "$XU" --help 2>&1) || HELP_RC=$?
CLI_MODE=direct
if [[ "$HELP_TEXT" == *"build input.xu"* || "$HELP_TEXT" == *"build input"* ]]; then
    CLI_MODE=product
elif [ "$HELP_RC" -ne 0 ] && [[ "$HELP_TEXT" == *"Usage:"* ]]; then
    # A wrapper that failed help is still more likely to expose the historical
    # direct form; leave the conservative default in place.
    CLI_MODE=direct
fi

resolve_binary() {
    local base="$1"
    local candidate
    for candidate in "$base" "$base.exe"; do
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

compile_fixture() {
    local name="$1"
    local source="$ROOT/tests/fixtures/$name/main.xu"
    local base="$TMP/$name"
    local stdout_file="$TMP/$name.compile.stdout"
    local stderr_file="$TMP/$name.compile.stderr"

    if [ "$CLI_MODE" = product ]; then
        run_with_timeout "$BUILD_TIMEOUT" "$XU" build "$source" -o "$base" \
            >"$stdout_file" 2>"$stderr_file"
    else
        run_with_timeout "$BUILD_TIMEOUT" "$XU" "$source" -o "$base" \
            >"$stdout_file" 2>"$stderr_file"
    fi
    local binary
    if ! binary=$(resolve_binary "$base"); then
        echo "runtime lifetime policy: $name produced no executable" >&2
        sed -n '1,120p' "$stderr_file" >&2 || true
        return 1
    fi
    chmod +x "$binary" 2>/dev/null || true
    printf '%s\n' "$binary"
}

# Parse exactly the existing seven-field report.  The parser returns a JSON
# object so the shell can compare fixtures without duplicating field logic.
parse_stats() {
    local file="$1"
    python3 - "$file" <<'PY'
import json
import re
import sys

path = sys.argv[1]
required = (
    "live_bytes",
    "peak_bytes",
    "allocs",
    "frees",
    "unknown_frees",
    "double_frees",
    "ledger_overflows",
)
values = {}
with open(path, encoding="utf-8", newline="") as stream:
    for line_no, raw in enumerate(stream, 1):
        line = raw.rstrip("\r\n")
        fields = line.split()
        if len(fields) == 1:
            pair = fields[0]
        elif len(fields) == 2:
            _label, pair = fields
        else:
            raise SystemExit(f"malformed stats line {line_no}: {line!r}")
        match = re.fullmatch(r"([a-z][a-z0-9_]*)=([0-9]+)", pair)
        if match is None:
            raise SystemExit(f"malformed stats field {line_no}: {pair!r}")
        key, value = match.groups()
        if key not in required:
            raise SystemExit(f"unexpected stats key {key!r}")
        if key in values:
            raise SystemExit(f"duplicate stats key {key!r}")
        values[key] = int(value)
missing = [key for key in required if key not in values]
if missing:
    raise SystemExit("missing stats keys: " + ", ".join(missing))
print(json.dumps(values, sort_keys=True))
PY
}

run_fixture() {
    local name="$1"
    local binary="$2"
    local stdout_file="$TMP/$name.stdout"
    local stderr_file="$TMP/$name.stderr"
    local rc=0
    if (cd "$TMP" && XU_HEAP_STATS=1 run_with_timeout "$RUN_TIMEOUT" "$binary") \
        >"$stdout_file" 2>"$stderr_file"; then
        rc=0
    else
        rc=$?
    fi
    if [ "$rc" -ne 0 ]; then
        echo "runtime lifetime policy: $name exited $rc" >&2
        sed -n '1,120p' "$stderr_file" >&2 || true
        return 1
    fi
    printf '%s\n' "$stdout_file"
}

assert_stdout() {
    local name="$1"
    local actual="$2"
    local expected="$ROOT/tests/fixtures/$name/expected.txt"
    if ! diff -u "$expected" "$actual"; then
        echo "runtime lifetime policy: $name stdout mismatch" >&2
        return 1
    fi
}

assert_stats() {
    local name="$1"
    local stats_file="$2"
    parse_stats "$stats_file"
}

heap_bin=$(compile_fixture heap_stats)
heap_out=$(run_fixture heap_stats "$heap_bin")
assert_stdout heap_stats "$heap_out"
heap_json=$(assert_stats heap_stats "$TMP/heap_stats.stderr")

chan_bin=$(compile_fixture chan_xu_basic)
chan_out=$(run_fixture chan_xu_basic "$chan_bin")
assert_stdout chan_xu_basic "$chan_out"
chan_json=$(assert_stats chan_xu_basic "$TMP/chan_xu_basic.stderr")

recycle_bin=$(compile_fixture chan_waiter_recycle)
recycle_out=$(run_fixture chan_waiter_recycle "$recycle_bin")
assert_stdout chan_waiter_recycle "$recycle_out"
recycle_json=$(assert_stats chan_waiter_recycle "$TMP/chan_waiter_recycle.stderr")

# Consuming interface downcasts are a control-flow lifetime edge: the source
# descriptor is cleared before the downcast frees its box, including when a
# break exits the enclosing loop.  Keep these regressions in the strict hosted
# policy gate so a stale owner cannot silently reappear as a double free.
as_loop_bin=$(compile_fixture as_loop_break)
as_loop_out=$(run_fixture as_loop_break "$as_loop_bin")
assert_stdout as_loop_break "$as_loop_out"
as_loop_json=$(assert_stats as_loop_break "$TMP/as_loop_break.stderr")

as_for_bin=$(compile_fixture as_for_break)
as_for_out=$(run_fixture as_for_break "$as_for_bin")
assert_stdout as_for_break "$as_for_out"
as_for_json=$(assert_stats as_for_break "$TMP/as_for_break.stderr")

# Context cancellation is a coroutine/lifetime boundary: parent propagation
# and explicit child cancellation race through the same one-token guard.  Keep
# this probe in the strict hosted lifetime gate so a watcher that double-closes
# (or leaks an allocator entry) cannot regress unnoticed while channel tests
# remain green.  The fixture deliberately exercises both parent-first and
# child-first cancellation, including repeated cancel calls.
context_bin=$(compile_fixture context_parent)
context_out=$(run_fixture context_parent "$context_bin")
assert_stdout context_parent "$context_out"
context_json=$(assert_stats context_parent "$TMP/context_parent.stderr")

# Timeout cancellation uses the same guard through a sleeping watcher.  Keep a
# separate fixture so a regression that only affects timer-driven wakeups is
# not masked by the parent-watcher case above.
timeout_context_bin=$(compile_fixture context_basic)
timeout_context_out=$(run_fixture context_basic "$timeout_context_bin")
assert_stdout context_basic "$timeout_context_out"
timeout_context_json=$(assert_stats context_basic "$TMP/context_basic.stderr")
python3 - "$heap_json" "$chan_json" "$recycle_json" "$as_loop_json" "$as_for_json" "$context_json" "$timeout_context_json" <<'PY'
import json
import sys
print("REPORT_COUNT", len(sys.argv) - 1, file=sys.stderr)

reports = [json.loads(item) for item in sys.argv[1:]]
if len(reports) != 7:
    raise SystemExit(f"expected 7 reports, got {len(reports)}")
heap, chan, recycle, as_loop, as_for, context, timeout_context = reports
for name, stats in (("heap_stats", heap), ("chan_xu_basic", chan), ("chan_waiter_recycle", recycle)):
    for key in ("unknown_frees", "double_frees", "ledger_overflows"):
        if stats[key] != 0:
            raise SystemExit(f"{name}: {key}={stats[key]} (want 0)")

# Parent/child cancellation must be idempotent and balanced.  The watcher
# goroutine's stack/header are process-scoped, so do not require live_bytes=0;
# only allocator corruption is a hard failure here.  A future runtime may
# reclaim those process-scoped records at exit without changing this contract.
for key in ("unknown_frees", "double_frees", "ledger_overflows"):
    if context[key] != 0:
        raise SystemExit(f"context_parent: {key}={context[key]} (want 0)")
if context["allocs"] < context["frees"]:
    raise SystemExit(
        f"context_parent: frees={context['frees']} exceed allocs={context['allocs']}"
    )

for key in ("unknown_frees", "double_frees", "ledger_overflows"):
    if timeout_context[key] != 0:
        raise SystemExit(f"context_basic: {key}={timeout_context[key]} (want 0)")
if timeout_context["allocs"] < timeout_context["frees"]:
    raise SystemExit(
        f"context_basic: frees={timeout_context['frees']} exceed allocs={timeout_context['allocs']}"
    )

# Temporary owned values have a strict zero-live contract.
if heap["live_bytes"] != 0 or heap["allocs"] != heap["frees"]:
    raise SystemExit(
        "heap_stats: temporary allocation leak "
        f"live={heap['live_bytes']} allocs={heap['allocs']} frees={heap['frees']}"
    )

# These constants mirror xurt's hosted M:N layout.  chan_xu_basic creates one
# G and one cap=1 MC channel; the lower bound intentionally excludes allocator
# class padding and transient runtime values, so harmless implementation
# additions cannot make the policy flaky.  If the G stack/header/channel ABI
# changes, update this bound with the corresponding xurt constants.
g_stack = 131072
g_header = 256
mc_chan_header = 232
one_int_slot = 8
persistent_min = g_stack + g_header + mc_chan_header + one_int_slot
if chan["live_bytes"] < persistent_min:
    raise SystemExit(
        "chan_xu_basic: process-scoped metadata below policy floor "
        f"live={chan['live_bytes']} floor={persistent_min}"
    )
if chan["allocs"] < chan["frees"]:
    raise SystemExit(
        f"chan_xu_basic: frees={chan['frees']} exceed allocs={chan['allocs']}"
    )

# The 200-rendezvous fixture must not allocate one permanent waiter per send.
# Compare against the same scheduler/channel baseline rather than requiring an
# exact count: the bounded pool may legitimately change its initial fill.
live_delta = recycle["live_bytes"] - chan["live_bytes"]
alloc_delta = recycle["allocs"] - chan["allocs"]
if live_delta < 0:
    raise SystemExit(
        f"chan_waiter_recycle: live={recycle['live_bytes']} below baseline "
        f"{chan['live_bytes']} (delta={live_delta})"
    )
if live_delta > 4096 or alloc_delta > 16:
    raise SystemExit(
        "chan_waiter_recycle: waiter retention exceeds bounded policy "
        f"live_delta={live_delta} alloc_delta={alloc_delta}"
    )
if recycle["allocs"] < recycle["frees"]:
    raise SystemExit(
        f"chan_waiter_recycle: frees={recycle['frees']} exceed allocs={recycle['allocs']}"
    )

# The loop downcast probes are temporary-value cases, so they have the same
# strict zero-live/balanced-allocation contract as heap_stats.  Check the
# diagnostic counters separately to make the failure mode explicit.
for name, stats in (("as_loop_break", as_loop), ("as_for_break", as_for)):
    if stats["live_bytes"] != 0 or stats["allocs"] != stats["frees"]:
        raise SystemExit(
            f"{name}: consuming downcast lifetime imbalance "
            f"live={stats['live_bytes']} allocs={stats['allocs']} frees={stats['frees']}"
        )
    for key in ("unknown_frees", "double_frees", "ledger_overflows"):
        if stats[key] != 0:
            raise SystemExit(f"{name}: {key}={stats[key]} (want 0)")

print(
    "runtime lifetime policy: temporary PASS "
    f"live_bytes={heap['live_bytes']} allocs={heap['allocs']} frees={heap['frees']}"
)
print(
    "runtime lifetime policy: process_scoped PASS "
    f"live_bytes={chan['live_bytes']} floor={persistent_min}"
)
print(
    "runtime lifetime policy: waiter_recycle PASS "
    f"live_delta={live_delta} alloc_delta={alloc_delta}"
)
print("runtime lifetime policy: consuming_as_break PASS")
print(
    "runtime lifetime policy: context_cancel PASS "
    f"live_bytes={context['live_bytes']} allocs={context['allocs']} frees={context['frees']}"
)
print(
    "runtime lifetime policy: context_timeout PASS "
    f"live_bytes={timeout_context['live_bytes']} allocs={timeout_context['allocs']} frees={timeout_context['frees']}"
)
PY
