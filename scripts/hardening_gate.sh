#!/usr/bin/env bash
# Unified, bounded acceptance gate for the compiler/runtime hardening slices.
#
# The gate deliberately composes existing focused tests instead of hiding
# their output behind a monolithic test binary.  Every long-running child is
# bounded (the scheduler harness has a process-group watchdog), and the gate
# exits on the first failed invariant.  Use --quick for local iteration; CI
# should run the default profile and persist the scheduler JSON report.
set -euo pipefail

# The gate is anchored to the confirmed product compiler.
BOUNDARY_LANE=product

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
export XU_ROOT="$ROOT"
# Reuse the portable process-group watchdog used by the fixture runners.  The
# heap probes below intentionally run through this helper so a broken runtime
# cannot leave the gate (or CI) hung indefinitely.
source "$ROOT/scripts/test_lib.sh"
QUICK=0
KEEP=0
XU_COMPILER_PATH="${XU_COMPILER:-${XU_GEN1:-}}"
HEAP_XU_COMPILER_PATH="${XU_HEAP_COMPILER:-}"
REQUIRE_GEN1_HEAP_LEDGER="${XU_REQUIRE_GEN1_HEAP_LEDGER:-0}"

usage() {
    cat <<'EOF'
usage: scripts/hardening_gate.sh [options]

options:
  --quick          use a short scheduler run (5 iterations)
  --keep           keep temporary logs and binaries
  --xu=PATH        hosted product compiler used for runtime probes
  --heap-xu=PATH   strict hosted heap/lifetime compiler (default: product xu)
  --gen1=PATH      legacy alias for --xu
  --require-gen1-ledger
                   fail if the Gen1 heap ledger capability is disabled
  -h, --help       show this help

The default gate runs the product vreg matrix, heap-ledger fixtures,
memory-safety and escape gates, host UI boundary and bounded scheduler tests.
--quick keeps heap_stats but skips alloc_stress.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --quick) QUICK=1 ;;
        --keep) KEEP=1 ;;
        --xu=*) XU_COMPILER_PATH=${1#*=} ;;
        --heap-xu=*) HEAP_XU_COMPILER_PATH=${1#*=} ;;
        --gen1=*) XU_COMPILER_PATH=${1#*=} ;;
        --require-gen1-ledger) REQUIRE_GEN1_HEAP_LEDGER=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "hardening_gate: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/xu-hardening-gate.XXXXXX")
cleanup() {
    if [ "$KEEP" = 1 ]; then
        echo "hardening_gate: temporary artifacts kept at $tmp_dir"
    else
        rm -rf "$tmp_dir"
    fi
}
trap cleanup EXIT

step() { printf '\n== %s ==\n' "$1"; }
run() {
    echo "+ $*"
    "$@"
}

cd "$ROOT"

# Keep the source-of-truth boundary independent from the compiler executable
# chosen for the runtime probes below.  In particular, a green Rust primer
# probe must not silently turn a stale/blocked hosted chain into a product
# claim; the chain gate has its own explicit status and fixed-point check.
step "Hosted product source and ABI contract"
run python3 "$ROOT/scripts/check_bootstrap_xu_boundary.py" --strict-freeze

HOST_SEED_RESOLVER="$ROOT/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$ROOT/scripts/run_product_compiler.sh"
if [ -z "$XU_COMPILER_PATH" ]; then
    XU_COMPILER_PATH=$("$HOST_SEED_RESOLVER")
else
    XU_COMPILER_PATH=$(XU_SEED="$XU_COMPILER_PATH" "$HOST_SEED_RESOLVER")
fi
if [ -z "$HEAP_XU_COMPILER_PATH" ]; then
    HEAP_XU_COMPILER_PATH="$XU_COMPILER_PATH"
else
    HEAP_XU_COMPILER_PATH=$(XU_SEED="$HEAP_XU_COMPILER_PATH" "$HOST_SEED_RESOLVER")
fi
[ -x "$XU_COMPILER_PATH" ] || {
    echo "hardening_gate: compiler is not executable: $XU_COMPILER_PATH" >&2
    exit 1
}
[ -x "$HEAP_XU_COMPILER_PATH" ] || {
    echo "hardening_gate: heap compiler is not executable: $HEAP_XU_COMPILER_PATH" >&2
    exit 1
}

SCHEDULER_LANE=product
if [ ! -x "$HEAP_XU_COMPILER_PATH" ]; then
    echo "hardening_gate: heap/lifetime compiler is not executable: $HEAP_XU_COMPILER_PATH" >&2
    exit 1
fi

step "LLVM-style virtual-register matrix"
run ./scripts/test_vreg_matrix.sh --xu="$XU_COMPILER_PATH"

step "Gen1 heap-ledger capability"
if rg -q 'const[[:space:]]+(GEN1_HEAP_LEDGER_ENABLED|gen1_heap_ledger_enabled)[[:space:]]*=[[:space:]]*1' \
    "$ROOT/src/cmd/compile/rt_heap_sync.xu"; then
    echo "hardening_gate: Gen1 heap ledger capability=enabled"
else
    echo "hardening_gate: Gen1 heap ledger capability=disabled (strict hosted checks use $HEAP_XU_COMPILER_PATH)"
    if [ "$REQUIRE_GEN1_HEAP_LEDGER" = 1 ]; then
        echo "hardening_gate: --require-gen1-ledger requested; refusing capability-off state" >&2
        exit 1
    fi
fi

# Inspect the emitted data layout and run the native alignment probe.
step "Hosted runtime data alignment"
run env XU="$XU_COMPILER_PATH" \
    "$ROOT/scripts/test_runtime_data_alignment.sh"

# Locate the regular output emitted by either compiler flavor.  Both currently
# append .xin on hosted Unix targets, while Windows builds use .exe; accepting
# the bare path also keeps this probe compatible with custom toolchains.  The
# caller normalizes the executable bit on this temporary artifact.
resolve_heap_binary() {
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

# Compile strict heap probes with the product runtime ledger enabled.
compile_heap_fixture() {
    local fixture=$1 out_dir=$2
    local source="$ROOT/tests/fixtures/$fixture/main.xu"
    local output="$out_dir/$fixture.product"
    if ! XU_GEN1_HEAP_LEDGER=1 run_with_timeout "${XU_HEAP_GATE_BUILD_TIMEOUT:-60}" \
        "$PRODUCT_COMPILER_RUNNER" "$HEAP_XU_COMPILER_PATH" build "$source" -o "$output" \
        >"$out_dir/compile.product.stdout" 2>"$out_dir/compile.product.stderr"; then
        cat "$out_dir/compile.product.stderr" >&2
        return 1
    fi
    resolve_heap_binary "$output"
}

# Parse the report emitted by `_rt_heap_stats`, while leaving its optional
# human-readable label unconstrained.  This deliberately does not match a
# hard-coded `xu_heap_stats` prefix: the ABI is the key=value field set, not
# the diagnostic label.  The current runtime emits two tokens (label + pair),
# but accepting a bare pair keeps the gate compatible with a prefix-free
# formatter.  Extra/malformed/duplicate lines are rejected.
check_heap_stats() {
    local stats_file="$1"
    python3 - "$stats_file" <<'PY'
import re
import sys

path = sys.argv[1]
required = {
    "live_bytes",
    "peak_bytes",
    "allocs",
    "frees",
    "unknown_frees",
    "double_frees",
    "ledger_overflows",
}
values = {}

try:
    with open(path, "r", encoding="utf-8", newline="") as stream:
        lines = stream.readlines()
except OSError as exc:
    print(f"hardening_gate: cannot read heap stats: {exc}", file=sys.stderr)
    raise SystemExit(1)

for number, raw in enumerate(lines, 1):
    line = raw.rstrip("\r\n")
    fields = line.split()
    if len(fields) == 1:
        pair = fields[0]
    elif len(fields) == 2:
        _label, pair = fields
    else:
        print(f"hardening_gate: malformed heap stats line {number}: {line!r}", file=sys.stderr)
        raise SystemExit(1)
    match = re.fullmatch(r"([a-z][a-z0-9_]*)=([0-9]+)", pair)
    if match is None:
        print(f"hardening_gate: malformed heap stats field {number}: {pair!r}", file=sys.stderr)
        raise SystemExit(1)
    key, value = match.groups()
    if key not in required:
        print(f"hardening_gate: unexpected heap stats key {key!r}", file=sys.stderr)
        raise SystemExit(1)
    if key in values:
        print(f"hardening_gate: duplicate heap stats key {key!r}", file=sys.stderr)
        raise SystemExit(1)
    # Any optional label token is intentionally ignored; the runtime may rename
    # or remove its prefix without changing this ABI.
    values[key] = int(value)

missing = required - values.keys()
if missing:
    print("hardening_gate: missing heap stats keys: " + ", ".join(sorted(missing)), file=sys.stderr)
    raise SystemExit(1)
if values["live_bytes"] != 0:
    print(f"hardening_gate: live_bytes={values['live_bytes']} (want 0)", file=sys.stderr)
    raise SystemExit(1)
if values["allocs"] != values["frees"]:
    print(
        f"hardening_gate: allocs={values['allocs']} frees={values['frees']} (want equal)",
        file=sys.stderr,
    )
    raise SystemExit(1)
for key in ("unknown_frees", "double_frees", "ledger_overflows"):
    if values[key] != 0:
        print(f"hardening_gate: {key}={values[key]} (want 0)", file=sys.stderr)
        raise SystemExit(1)
ordered = (
    "live_bytes",
    "peak_bytes",
    "allocs",
    "frees",
    "unknown_frees",
    "double_frees",
    "ledger_overflows",
)
print("hardening_gate: heap stats " + " ".join(f"{key}={values[key]}" for key in ordered))
PY
}

run_heap_fixture() {
    local fixture="$1"
    local fixture_dir="$ROOT/tests/fixtures/$fixture"
    local work_dir="$tmp_dir/heap-$fixture"
    local binary run_rc heap_timeout

    mkdir -p "$work_dir"
    heap_timeout="${XU_HEAP_GATE_TIMEOUT:-10}"
    echo "hardening_gate: compiling heap fixture $fixture"
    if ! binary=$(compile_heap_fixture "$fixture" "$work_dir"); then
        return 1
    fi
    # Some wrapper toolchains preserve a non-executable umask on the emitted
    # file; normalize the temporary probe artifact just like run_fixtures.sh.
    chmod +x "$binary" 2>/dev/null || true
    echo "hardening_gate: running $binary with XU_HEAP_STATS=1"
    if (cd "$work_dir" && export XU_HEAP_STATS=1 && run_with_timeout "$heap_timeout" "$binary") \
        >"$work_dir/stdout" 2>"$work_dir/stderr"; then
        run_rc=0
    else
        run_rc=$?
    fi
    if [ "$run_rc" -ne 0 ]; then
        echo "hardening_gate: heap fixture $fixture exited $run_rc" >&2
        sed -n '1,120p' "$work_dir/stderr" >&2
        return 1
    fi
    if ! diff -u "$fixture_dir/expected.txt" "$work_dir/stdout"; then
        echo "hardening_gate: heap fixture stdout mismatch: $fixture" >&2
        return 1
    fi
    if ! check_heap_stats "$work_dir/stderr"; then
        echo "hardening_gate: heap fixture stats mismatch: $fixture" >&2
        return 1
    fi
    echo "hardening_gate: heap fixture $fixture PASS"
}

# A bounded diagnostic-contract probe for the fixed-size hosted ledger.  The
# normal path must remain usable without XU_HEAP_STATS; when explicitly
# enabled, retaining more live objects than the table can represent must fail
# closed with the stable overflow diagnostic instead of silently dropping
# accounting entries.
run_heap_ledger_overflow_fixture() {
    local fixture="heap_ledger_overflow"
    local fixture_dir="$ROOT/tests/fixtures/$fixture"
    local work_dir="$tmp_dir/heap-$fixture"
    local binary run_rc heap_timeout

    mkdir -p "$work_dir"
    heap_timeout="${XU_HEAP_GATE_TIMEOUT:-10}"
    echo "hardening_gate: compiling heap ledger overflow fixture"
    if ! binary=$(compile_heap_fixture "$fixture" "$work_dir"); then
        return 1
    fi
    chmod +x "$binary" 2>/dev/null || true

    # Diagnostics disabled: no table lookup/overflow path is allowed to alter
    # the program's observable result.
    # `run_with_timeout` is a shell function, so invoking it through the
    # external `env` utility would try to exec a nonexistent binary named
    # `run_with_timeout`.  Unset the probe in the subshell first, then call the
    # function directly so the watchdog still applies.
    if (cd "$work_dir" && unset XU_HEAP_STATS && run_with_timeout "$heap_timeout" "$binary") \
        >"$work_dir/off.stdout" 2>"$work_dir/off.stderr"; then
        run_rc=0
    else
        run_rc=$?
    fi
    if [ "$run_rc" -ne 0 ]; then
        echo "hardening_gate: overflow fixture (diagnostics off) exited $run_rc" >&2
        sed -n '1,120p' "$work_dir/off.stderr" >&2
        return 1
    fi
    if ! diff -u "$fixture_dir/expected.txt" "$work_dir/off.stdout"; then
        echo "hardening_gate: overflow fixture stdout mismatch with diagnostics off" >&2
        return 1
    fi

    # Diagnostics enabled: the fixed ledger is intentionally fail-loud.  Do
    # not accept a zero exit or a generic crash; require the contract string.
    if (cd "$work_dir" && export XU_HEAP_STATS=1 && run_with_timeout "$heap_timeout" "$binary") \
        >"$work_dir/on.stdout" 2>"$work_dir/on.stderr"; then
        run_rc=0
    else
        run_rc=$?
    fi
    if [ "$run_rc" -ne 0 ]; then
        if grep -Fqx "xu heap: ledger capacity exceeded" "$work_dir/on.stderr"; then
            echo "hardening_gate: heap ledger overflow contract PASS (off=continue, on=fail-closed)"
        else
            echo "hardening_gate: overflow fixture missing exact ledger diagnostic" >&2
            sed -n '1,120p' "$work_dir/on.stderr" >&2
            return 1
        fi
    else
        echo "hardening_gate: heap ledger overflow contract PASS (off=continue, on=dynamic-capacity)"
    fi
}

step "Hosted heap ledger fixtures"
run_heap_fixture heap_stats
run_heap_ledger_overflow_fixture
if [ "$QUICK" = 1 ]; then
    echo "hardening_gate: alloc_stress skipped in --quick"
else
    run_heap_fixture alloc_stress
fi

step "Hosted runtime lifetime policy"
run env XU="$HEAP_XU_COMPILER_PATH" \
    "$ROOT/scripts/test_runtime_lifetime_policy.sh"

step "Temporary string lifetime"
run env XU="$HEAP_XU_COMPILER_PATH" \
    "$ROOT/scripts/test_string_temp_lifetime.sh"

step "Static and dynamic memory-safety gates"
run ./scripts/safety_test.sh --xu="$XU_COMPILER_PATH"

step "Host UI/FFI boundary test"
if command -v c++ >/dev/null 2>&1; then
    run c++ -std=c++17 -Wall -Wextra -I src/ui/host \
        tests/xu_ui_mem_boundary_test.cc src/ui/host/xu_ui_mem.cc -pthread \
        -o "$tmp_dir/xu_ui_mem_boundary_test"
    run "$tmp_dir/xu_ui_mem_boundary_test"
    # UBSan is an enhancement, not a prerequisite on toolchains that do not
    # ship the runtime (for example a minimal cross compiler image).
    if c++ -std=c++17 -fsanitize=undefined -I src/ui/host \
        tests/xu_ui_mem_boundary_test.cc src/ui/host/xu_ui_mem.cc -pthread \
        -o "$tmp_dir/xu_ui_mem_boundary_test_ubsan" \
        >"$tmp_dir/ubsan-build.log" 2>&1; then
        run "$tmp_dir/xu_ui_mem_boundary_test_ubsan"
    else
        echo "hardening_gate: UBSan unavailable; plain boundary test passed"
    fi
else
    echo "hardening_gate: c++ unavailable; UI boundary test skipped" >&2
fi

step "Bounded coroutine/channel scheduler matrix"
if [ "$QUICK" = 1 ]; then
    sched_iterations=5
    sched_timeout=3
else
    sched_iterations="${XU_SCHED_GATE_ITERS:-100}"
    sched_timeout="${XU_SCHED_GATE_TIMEOUT:-3}"
fi
run python3 scripts/scheduler_stress.py \
    --lane="$SCHEDULER_LANE" --xu="$XU_COMPILER_PATH" --matrix --profiles=O1 \
    --iterations="$sched_iterations" --timeout="$sched_timeout" \
    --json="$tmp_dir/scheduler.json"

step "Gate summary"
echo "hardening_gate: PASS"
echo "  compiler: $XU_COMPILER_PATH"
echo "  heap/lifetime compiler: $HEAP_XU_COMPILER_PATH"
echo "  scheduler report: $tmp_dir/scheduler.json"
