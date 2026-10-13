#!/usr/bin/env bash
# Complex memory-escape gate (S1 / M2b / M10 / M150 / M153 / M167).
#
# Every tests/gen1/safety/escape/*.xu must be rejected by bootstrap and Gen1
# with identical first-line diagnostics (same rules as safety_test / M182).
#
# Usage:
#   scripts/safety_escape_test.sh
#   scripts/safety_escape_test.sh --gen1=/path/to/gen1 --xu=/path/to/xu
set -euo pipefail
# Machine-readable boundary role: escape/lifetime oracle evidence.
BOUNDARY_LANE=oracle
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"

XU=""
GEN1=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) XU="${1#*=}" ;;
        --gen1=*) GEN1="${1#*=}" ;;
        *) echo "safety_escape_test: unknown arg $1"; exit 1 ;;
    esac
    shift
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { echo "safety_escape_test: FAIL ($1)"; exit 1; }

if [ -z "$XU" ]; then
    cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu --bin xu \
        || fail "bootstrap xu build failed"
    XU="$BOOTSTRAP_ROOT/target/debug/xu"
fi

# The bootstrap side is oracle evidence; only the exact physical Gen0 output
# is admissible.  --gen1 remains an explicit parity binary and is not
# classified here.
if ! XU=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$XU" \
    "$ROOT/scripts/xu_host_seed.sh"); then
    fail "bootstrap compiler is not the canonical frozen primer"
fi
if [ -n "$GEN1" ]; then
    echo "safety_escape_test: lane=oracle; gen1_lane=parity (explicit --gen1; not product evidence)" >&2
else
    echo "safety_escape_test: lane=oracle (frozen bootstrap); generated Gen1 is parity-only, not product evidence" >&2
fi

if [ -z "$GEN1" ]; then
    . ./scripts/gen1_sources.sh || fail "could not load scripts/gen1_sources.sh"
    # Primer -O0: bootstrap auto/O1 still miscompiles the full compiler.
    "$XU" -O0 $GEN1_SRCS -o "$tmp/gen1.xin" || fail "bootstrap could not compile Gen1"
    GEN1="$tmp/gen1.xin"
fi

SAFETY_DRIFT_LIST="$PWD/docs/audit/SAFETY_DIAG_COL_DRIFT.txt"
is_safety_drift() {
    local n="$1"
    [ -f "$SAFETY_DRIFT_LIST" ] || return 1
    grep -qxF "$n" "$SAFETY_DRIFT_LIST"
}

escape_n=0
for bad in tests/gen1/safety/escape/*.xu; do
    [ -f "$bad" ] || continue
    n=$(basename "$bad" .xu)
    set +e
    "$XU" "$bad" -o "$tmp/escape_${n}_boot.xin" >"$tmp/escape_${n}_bo" 2>"$tmp/escape_${n}_be"
    boot_rc=$?
    "$GEN1" build "$bad" -o "$tmp/escape_${n}_gen1.xin" >"$tmp/escape_${n}_go" 2>"$tmp/escape_${n}_ge"
    gen1_rc=$?
    set -e
    [ "$boot_rc" != "0" ] || fail "bootstrap accepted escape unsafe program $bad"
    [ "$gen1_rc" != "0" ] || fail "gen1 accepted escape unsafe program $bad"
    a=$(head -1 "$tmp/escape_${n}_be" | tr -d '\r' | sed 's/[[:space:]]*$//')
    b=$(head -1 "$tmp/escape_${n}_ge" | tr -d '\r' | sed 's/[[:space:]]*$//')
    if is_safety_drift "$n"; then
        # Drift list: both must reject the same file; line/col/message may differ.
        apre=${a%: error:*}; apre=${apre%:*}; apre=${apre%:*}
        bpre=${b%: error:*}; bpre=${bpre%:*}; bpre=${bpre%:*}
        [ "$apre" = "$bpre" ] || fail "error file differs on escape/$n ($apre vs $bpre)"
    else
        [ "$a" = "$b" ] || { echo "  bootstrap: $a"; echo "  gen1:      $b"; fail "escape first-line differs on $n (M182)"; }
    fi
    escape_n=$((escape_n + 1))
done

[ "$escape_n" -gt 0 ] || fail "no tests/gen1/safety/escape/*.xu found"

# Legal elision / Send paths (must compile, run, and match bootstrap ≡ gen1).
ESCAPE_OK="p150_ref_return_struct p153_closure_capture_ref p29_xu_generic p155_match_string_clone p183_if_string_clone p184_while_string_clone p185_select_string_clone"
ok_n=0
for n in $ESCAPE_OK; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing escape OK probe $prog"
    "$XU" "$prog" -o "$tmp/${n}_boot.xin" || fail "bootstrap could not compile OK $prog"
    "$GEN1" build "$prog" -o "$tmp/${n}_gen1.xin" || fail "gen1 could not build OK $prog"
    chmod +x "$tmp/${n}_boot.xin" "$tmp/${n}_gen1.xin"
    "$tmp/${n}_boot.xin" > "$tmp/${n}_ob" 2> "$tmp/${n}_eb"; eb=$?
    "$tmp/${n}_gen1.xin" > "$tmp/${n}_og" 2> "$tmp/${n}_eg"; eg=$?
    cmp -s "$tmp/${n}_ob" "$tmp/${n}_og" || fail "escape OK output differs on $n"
    [ "$eb" = "$eg" ] || fail "escape OK exit differs on $n ($eb vs $eg)"
    [ "$eg" = "0" ] || fail "escape OK $n exited non-zero"
    ok_n=$((ok_n + 1))
done

echo "safety_escape_test: PASS (${escape_n} escape negatives rejected; ${ok_n} legal elision probes)"
