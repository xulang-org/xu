#!/usr/bin/env bash
# Unified, bounded acceptance gate for the compiler/runtime hardening slices.
#
# The gate deliberately composes existing focused tests instead of hiding
# their output behind a monolithic test binary.  Every long-running child is
# bounded (the scheduler harness has a process-group watchdog), and the gate
# exits on the first failed invariant.  Use --quick for local iteration; CI
# should run the default profile and persist the scheduler JSON report.
set -euo pipefail

# The default gate is anchored to the frozen primer oracle, even when an
# explicit product compiler is supplied for a parity probe.
BOUNDARY_LANE=oracle

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
# Reuse the portable process-group watchdog used by the fixture runners.  The
# heap probes below intentionally run through this helper so a broken runtime
# cannot leave the gate (or CI) hung indefinitely.
source "$ROOT/scripts/test_lib.sh"
QUICK=0
KEEP=0
XU_COMPILER_PATH="${XU_COMPILER:-}"
HEAP_XU_COMPILER_PATH="${XU_HEAP_COMPILER:-}"
GEN1_PATH="${XU_GEN1:-}"
REQUIRE_GEN1_HEAP_LEDGER="${XU_REQUIRE_GEN1_HEAP_LEDGER:-0}"

usage() {
    cat <<'EOF'
usage: scripts/hardening_gate.sh [options]

options:
  --quick          use a short scheduler run (5 iterations)
  --keep           keep temporary logs and binaries
  --xu=PATH        product/bootstrap compiler used for runtime probes
  --heap-xu=PATH   strict hosted heap/lifetime compiler (default: bootstrap xu)
  --gen1=PATH      parity compiler/runtime used by safety_test
  --require-gen1-ledger
                   fail if the Gen1 heap ledger capability is disabled
  -h, --help       show this help

The default gate runs focused Rust tests, the vreg matrix, hosted heap-ledger
fixtures, memory-safety and escape gates, the host UI boundary test, and a
bounded scheduler matrix.  Unless --xu/--heap-xu is supplied, the compiler
probes use the frozen primer and are labelled oracle evidence; they never
certify the hosted product fixed point.  --quick keeps heap_stats but skips
alloc_stress.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --quick) QUICK=1 ;;
        --keep) KEEP=1 ;;
        --xu=*) XU_COMPILER_PATH=${1#*=} ;;
        --heap-xu=*) HEAP_XU_COMPILER_PATH=${1#*=} ;;
        --gen1=*) GEN1_PATH=${1#*=} ;;
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
step "Bootstrap/Xu boundary contract (strict freeze registration)"
run python3 "$ROOT/scripts/check_bootstrap_xu_boundary.py" --strict-freeze

step "Rust compiler/runtime unit tests"
run cargo test --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" \
    -p xuhir -p xumir -p xuemit -p xurt -p xuplay --quiet

step "LLVM-style virtual-register matrix"
run ./scripts/test_vreg_matrix.sh

# The bootstrap compiler is the authoritative implementation for the strict
# hosted allocator/lifetime ABI.  Keep the product compiler selectable for
# parity/scheduler probes, but do not silently turn a stale product binary into
# the leak detector.  An explicit --xu (or XU_COMPILER) always wins.
BOOTSTRAP_XU="$BOOTSTRAP_ROOT/target/debug/xu"
for candidate in \
    "$BOOTSTRAP_ROOT/target/debug/xu" \
    "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
    "$BOOTSTRAP_ROOT/target/release/xu" \
    "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
    if [ -x "$candidate" ]; then
        BOOTSTRAP_XU="$candidate"
        break
    fi
done
if [ -z "$XU_COMPILER_PATH" ]; then
    if [ -x "$BOOTSTRAP_XU" ]; then
        XU_COMPILER_PATH="$BOOTSTRAP_XU"
    elif [ -x "$ROOT/bin/xu" ]; then
        XU_COMPILER_PATH="$ROOT/bin/xu"
    else
        XU_COMPILER_PATH="$BOOTSTRAP_XU"
    fi
fi
if [ -z "$HEAP_XU_COMPILER_PATH" ]; then
    HEAP_XU_COMPILER_PATH="$BOOTSTRAP_XU"
fi

# Retain the lexical spellings before canonicalisation.  A primer symlink to
# an external executable must remain oracle-owned even after realpath turns
# its target into /bin/echo (or another hosted-looking path).
XU_COMPILER_INPUT="$XU_COMPILER_PATH"
HEAP_XU_COMPILER_INPUT="$HEAP_XU_COMPILER_PATH"

canonical_compiler_path() {
    local candidate=$1
    if [ -x "$candidate" ] && command -v realpath >/dev/null 2>&1; then
        realpath "$candidate"
        return
    fi
    if [ -x "$candidate" ] && command -v python3 >/dev/null 2>&1; then
        python3 - "$candidate" <<'PY'
import os
import sys
print(os.path.realpath(sys.argv[1]))
PY
        return
    fi
    printf '%s\n' "$candidate"
}

is_primer_path() {
    local candidate=$1 resolved=${2:-$1} lexical
    case "$candidate" in
        /*) lexical=$candidate ;;
        *) lexical="$ROOT/$candidate" ;;
    esac
    case "$lexical" in
        "$BOOTSTRAP_ROOT"|"$BOOTSTRAP_ROOT"/*) return 0 ;;
        *) ;;
    esac
    case "$resolved" in
        "$BOOTSTRAP_ROOT"|"$BOOTSTRAP_ROOT"/*) return 0 ;;
        *) return 1 ;;
    esac
}

has_symlink_component() {
    local candidate=$1 root=$2 rel current part
    case "$candidate" in
        "$root"/*) rel=${candidate#"$root/"} ;;
        *) return 1 ;;
    esac
    [ -L "$root" ] && return 0
    current=$root
    local components=()
    IFS='/' read -r -a components <<< "$rel"
    for part in "${components[@]}"; do
        [ -n "$part" ] || continue
        current="$current/$part"
        [ -L "$current" ] && return 0
    done
    return 1
}

is_frozen_primer_path() {
    local candidate=$1 resolved=${2:-$1} lexical expected
    case "$candidate" in
        /*) lexical=$candidate ;;
        *) lexical="$ROOT/$candidate" ;;
    esac
    for expected in \
        "$BOOTSTRAP_ROOT/target/debug/xu" \
        "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
        "$BOOTSTRAP_ROOT/target/release/xu" \
        "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
        [ "$lexical" = "$expected" ] || continue
        [ -f "$expected" ] || continue
        [ -x "$expected" ] || continue
        has_symlink_component "$expected" "$BOOTSTRAP_ROOT" && continue
        [ "$resolved" = "$expected" ] || continue
        return 0
    done
    return 1
}

if [ -x "$XU_COMPILER_PATH" ]; then
    XU_COMPILER_PATH=$(canonical_compiler_path "$XU_COMPILER_PATH")
fi
if [ -x "$HEAP_XU_COMPILER_PATH" ]; then
    HEAP_XU_COMPILER_PATH=$(canonical_compiler_path "$HEAP_XU_COMPILER_PATH")
fi

# The alignment probe below is itself an oracle operation.  Validate the
# bootstrap executable before it can run, even when --xu selects a legal
# external hosted compiler for the product scheduler lane.
if ! BOOTSTRAP_XU=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 \
    XU_SEED="$BOOTSTRAP_XU" "$ROOT/scripts/xu_host_seed.sh"); then
    echo "hardening_gate: bootstrap alignment compiler is not the canonical frozen primer" >&2
    exit 1
fi

if is_primer_path "$XU_COMPILER_INPUT" "$XU_COMPILER_PATH"; then
    is_frozen_primer_path "$XU_COMPILER_INPUT" "$XU_COMPILER_PATH" || {
        echo "hardening_gate: refusing non-canonical bootstrap compiler; oracle accepts only bootstrap/target/{debug,release}/xu[.exe]" >&2
        exit 1
    }
    echo "hardening_gate: probe lane=oracle (primer; not product self-host evidence)"
else
    echo "hardening_gate: probe lane=product (hosted compiler)"
fi
if is_primer_path "$HEAP_XU_COMPILER_INPUT" "$HEAP_XU_COMPILER_PATH"; then
    is_frozen_primer_path "$HEAP_XU_COMPILER_INPUT" "$HEAP_XU_COMPILER_PATH" || {
        echo "hardening_gate: refusing non-canonical bootstrap heap compiler; oracle accepts only bootstrap/target/{debug,release}/xu[.exe]" >&2
        exit 1
    }
    echo "hardening_gate: heap/lifetime lane=oracle (primer; strict ABI probe only)"
else
    echo "hardening_gate: heap/lifetime lane=product (hosted compiler)"
fi

# scheduler_stress.py now fail-closes its oracle selector to the frozen Gen0
# artifact.  Preserve the documented explicit-hosted use of --xu by selecting
# its product lane when the probe compiler is hosted; this keeps an explicit
# product probe from being mislabeled as a primer oracle (and still routes the
# hosted build through run_product_compiler.sh inside the harness).
SCHEDULER_LANE=oracle
if ! is_frozen_primer_path "$XU_COMPILER_INPUT" "$XU_COMPILER_PATH"; then
    SCHEDULER_LANE=product
fi

if [ ! -x "$XU_COMPILER_PATH" ] || [ ! -x "$HEAP_XU_COMPILER_PATH" ]; then
    step "Bootstrap compiler build"
    run cargo build --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu --bin xu --quiet
fi
if [ ! -x "$XU_COMPILER_PATH" ]; then
    echo "hardening_gate: compiler is not executable: $XU_COMPILER_PATH" >&2
    exit 1
fi
if [ ! -x "$HEAP_XU_COMPILER_PATH" ]; then
    echo "hardening_gate: heap/lifetime compiler is not executable: $HEAP_XU_COMPILER_PATH" >&2
    exit 1
fi

step "Gen1 heap-ledger capability"
if rg -q 'const[[:space:]]+gen1_heap_ledger_enabled[[:space:]]*=[[:space:]]*1' \
    "$ROOT/src/cmd/compile/rt_heap_sync.xu"; then
    echo "hardening_gate: Gen1 heap ledger capability=enabled"
else
    echo "hardening_gate: Gen1 heap ledger capability=disabled (strict hosted checks use $HEAP_XU_COMPILER_PATH)"
    if [ "$REQUIRE_GEN1_HEAP_LEDGER" = 1 ]; then
        echo "hardening_gate: --require-gen1-ledger requested; refusing capability-off state" >&2
        exit 1
    fi
fi

# The alignment probe intentionally uses the bootstrap compiler: its direct
# CLI and XUOBJ labels let us inspect the emitted data segment on every host,
# while the optional Darwin arm64 execution catches the SIGBUS failure mode.
# Keep this independent from the product wrapper selected for heap/scheduler
# probes (which may expose a different `xu build` command dialect).
step "Hosted runtime data alignment"
run env XU="$BOOTSTRAP_XU" \
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

# Resolve the command dialect from the compiler's own help.  A wrapper
# that does not implement --help is treated as unknown and gets the guarded
# two-form fallback in compile_heap_fixture; once a dialect is advertised, a
# real source/build failure is never hidden by trying the other command.
detect_heap_cli() {
    local help_text help_rc=0
    help_text=$(run_with_timeout "${XU_HEAP_GATE_HELP_TIMEOUT:-5}" \
        "$HEAP_XU_COMPILER_PATH" --help 2>&1) || help_rc=$?
    if [[ "$help_text" == *"build input.xu"* || "$help_text" == *"build input"* ]]; then
        printf '%s\n' product
    elif [ "$help_rc" -eq 0 ] && [[
        "$help_text" == *"xu <file.xu|dir>"* ||
        "$help_text" == *"Compile into an executable"*
    ]]; then
        printf '%s\n' direct
    else
        printf '%s\n' unknown
    fi
}

# Compile one fixture without baking a CLI flavor into the gate.  The
# self-hosted product takes `xu build input.xu -o out`, whereas bootstrap xu
# accepts `xu input.xu -o out`; separate output bases keep a failed fallback
# attempt from being mistaken for a successful binary.
compile_heap_fixture() {
    local fixture="$1"
    local out_dir="$2"
    local source="$ROOT/tests/fixtures/$fixture/main.xu"
    local product_base="$out_dir/$fixture.product"
    local bootstrap_base="$out_dir/$fixture.bootstrap"
    local cli_mode product_rc bootstrap_rc binary build_timeout

    cli_mode=$(detect_heap_cli)
    build_timeout="${XU_HEAP_GATE_BUILD_TIMEOUT:-60}"
    echo "hardening_gate: heap compiler CLI mode=$cli_mode" >&2

    if [ "$cli_mode" = direct ]; then
        printf '+ %q %q -o %q\n' "$HEAP_XU_COMPILER_PATH" "$source" "$bootstrap_base" >&2
        if run_with_timeout "$build_timeout" "$HEAP_XU_COMPILER_PATH" "$source" -o "$bootstrap_base" \
            >"$out_dir/compile.bootstrap.stdout" 2>"$out_dir/compile.bootstrap.stderr"; then
            if binary=$(resolve_heap_binary "$bootstrap_base"); then
                printf '%s\n' "$binary"
                return 0
            fi
            echo "hardening_gate: direct CLI returned success but emitted no executable" >&2
        else
            bootstrap_rc=$?
            echo "hardening_gate: direct CLI failed (rc=$bootstrap_rc)" >&2
        fi
    elif [ "$cli_mode" = product ]; then
        printf '+ %q build %q -o %q\n' "$HEAP_XU_COMPILER_PATH" "$source" "$product_base" >&2
        if run_with_timeout "$build_timeout" "$HEAP_XU_COMPILER_PATH" build "$source" -o "$product_base" \
            >"$out_dir/compile.product.stdout" 2>"$out_dir/compile.product.stderr"; then
            if binary=$(resolve_heap_binary "$product_base"); then
                printf '%s\n' "$binary"
                return 0
            fi
            echo "hardening_gate: product CLI returned success but emitted no executable" >&2
        else
            product_rc=$?
            echo "hardening_gate: product CLI failed (rc=$product_rc)" >&2
        fi
    else
        # A nonstandard launcher may not expose help.  Preserve compatibility
        # by trying both forms, but only in this explicitly unknown case.
        printf '+ %q build %q -o %q\n' "$HEAP_XU_COMPILER_PATH" "$source" "$product_base" >&2
        if run_with_timeout "$build_timeout" "$HEAP_XU_COMPILER_PATH" build "$source" -o "$product_base" \
            >"$out_dir/compile.product.stdout" 2>"$out_dir/compile.product.stderr"; then
            if binary=$(resolve_heap_binary "$product_base"); then
                printf '%s\n' "$binary"
                return 0
            fi
            echo "hardening_gate: product CLI returned success but emitted no executable" >&2
        else
            product_rc=$?
            echo "hardening_gate: unknown CLI product form failed (rc=$product_rc); trying direct form" >&2
        fi

        printf '+ %q %q -o %q\n' "$HEAP_XU_COMPILER_PATH" "$source" "$bootstrap_base" >&2
        if run_with_timeout "$build_timeout" "$HEAP_XU_COMPILER_PATH" "$source" -o "$bootstrap_base" \
            >"$out_dir/compile.bootstrap.stdout" 2>"$out_dir/compile.bootstrap.stderr"; then
            if binary=$(resolve_heap_binary "$bootstrap_base"); then
                printf '%s\n' "$binary"
                return 0
            fi
            echo "hardening_gate: direct CLI returned success but emitted no executable" >&2
        else
            bootstrap_rc=$?
            echo "hardening_gate: direct CLI failed (rc=$bootstrap_rc)" >&2
        fi
    fi

    echo "hardening_gate: unable to compile heap fixture: $fixture" >&2
    for candidate in \
        "$out_dir/compile.product.stderr" \
        "$out_dir/compile.bootstrap.stderr"; do
        if [ -s "$candidate" ]; then
            echo "--- $candidate ---" >&2
            sed -n '1,120p' "$candidate" >&2
        fi
    done
    return 1
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
    if [ "$run_rc" -eq 0 ]; then
        echo "hardening_gate: overflow fixture unexpectedly succeeded with diagnostics enabled" >&2
        return 1
    fi
    if ! grep -Fqx "xu heap: ledger capacity exceeded" "$work_dir/on.stderr"; then
        echo "hardening_gate: overflow fixture missing exact ledger diagnostic" >&2
        sed -n '1,120p' "$work_dir/on.stderr" >&2
        return 1
    fi
    echo "hardening_gate: heap ledger overflow contract PASS (off=continue, on=fail-closed)"
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
if [ -n "$GEN1_PATH" ]; then
    run ./scripts/safety_test.sh --xu="$XU_COMPILER_PATH" --gen1="$GEN1_PATH"
else
    # safety_test builds/locates its own Gen1 peer when --gen1 is omitted.
    run ./scripts/safety_test.sh --xu="$XU_COMPILER_PATH"
fi

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
