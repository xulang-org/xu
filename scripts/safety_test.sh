#!/usr/bin/env bash
# Memory-safety gate (extracted from gen1_test §5 + runtime loud probes).
#
#   1. compile-time safety negatives: bootstrap and gen1 both reject every
#      tests/gen1/safety/*.xu with matching diagnostics (M182 COL_DRIFT rules);
#   2. runtime loud probes: p17–p22 (OOB + division guards, hosted default target);
#   3. chan/xu runtime: closed/parked fail-loud (exit 1) + behavior parity probes.
#
# Usage:
#   scripts/safety_test.sh
#   scripts/safety_test.sh --gen1=/path/to/gen1 --xu=/path/to/xu
#
# When --gen1 is omitted, builds Gen1 from bootstrap (same sources as gen1_test).
set -euo pipefail
# Machine-readable boundary role: bootstrap/Gen1 safety parity oracle.
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
        *) echo "safety_test: unknown arg $1"; exit 1 ;;
    esac
    shift
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { echo "safety_test: FAIL ($1)"; exit 1; }

if [ -z "$XU" ]; then
    cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu --bin xu \
        || fail "bootstrap xu build failed"
    XU="$BOOTSTRAP_ROOT/target/debug/xu"
fi

# --xu is the bootstrap/oracle side; --gen1 remains an explicitly supplied
# parity binary and may be a temporary hosted artifact.  Preserve that
# distinction while rejecting symlinked or external oracle aliases.
if ! XU=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$XU" \
    "$ROOT/scripts/xu_host_seed.sh"); then
    fail "bootstrap compiler is not the canonical frozen primer"
fi
if [ -n "$GEN1" ]; then
    echo "safety_test: lane=oracle; gen1_lane=parity (explicit --gen1; not product evidence)" >&2
else
    echo "safety_test: lane=oracle (frozen bootstrap); generated Gen1 is parity-only, not product evidence" >&2
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

safety_n=0
for bad in tests/gen1/safety/*.xu; do
    n=$(basename "$bad" .xu)
    set +e
    "$XU" "$bad" -o "$tmp/safety_${n}_boot.xin" >"$tmp/safety_${n}_bo" 2>"$tmp/safety_${n}_be"
    boot_rc=$?
    "$GEN1" build "$bad" -o "$tmp/safety_${n}_gen1.xin" >"$tmp/safety_${n}_go" 2>"$tmp/safety_${n}_ge"
    gen1_rc=$?
    set -e
    [ "$boot_rc" != "0" ] || fail "bootstrap accepted unsafe program $bad"
    [ "$gen1_rc" != "0" ] || fail "gen1 accepted unsafe program $bad"
    a=$(head -1 "$tmp/safety_${n}_be" | tr -d '\r' | sed 's/[[:space:]]*$//')
    b=$(head -1 "$tmp/safety_${n}_ge" | tr -d '\r' | sed 's/[[:space:]]*$//')
    if [ "${XU_BOUNDARY_CI:-0}" = 1 ]; then
        # The local column-drift ledger stays out of CI. Require the same
        # file, line and diagnostic while allowing parser column offsets.
        a=$(printf '%s\n' "$a" | sed -E 's/:([0-9]+):[0-9]+: error:/:\1: error:/')
        b=$(printf '%s\n' "$b" | sed -E 's/:([0-9]+):[0-9]+: error:/:\1: error:/')
    fi
    if is_safety_drift "$n"; then
        # Drift list: both must reject the same file; line/col/message may differ.
        apre=${a%: error:*}; apre=${apre%:*}; apre=${apre%:*}
        bpre=${b%: error:*}; bpre=${bpre%:*}; bpre=${bpre%:*}
        [ "$apre" = "$bpre" ] || fail "error file differs on $n ($apre vs $bpre)"
    else
        [ "$a" = "$b" ] || { echo "  bootstrap: $a"; echo "  gen1:      $b"; fail "safety first-line differs on $n (M182)"; }
    fi
    safety_n=$((safety_n + 1))
done

LOUD_PROBES="p17_negative_index p18_slice_negative p19_slice_reverse p20_div_overflow_intmin p21_div_zero_loud p22_div_overflow_intmin_mod p191_as_fail_loud p_array_slice_oob"
loud_n=0
for n in $LOUD_PROBES; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing loud probe $prog"
    "$XU" "$prog" -o "$tmp/${n}_boot.xin" || fail "bootstrap could not compile $prog"
    "$GEN1" build "$prog" -o "$tmp/${n}_gen1.xin" || fail "gen1 could not build $prog"
    chmod +x "$tmp/${n}_boot.xin" "$tmp/${n}_gen1.xin"
    set +e
    "$tmp/${n}_boot.xin" > "$tmp/${n}_ob" 2> "$tmp/${n}_eb"; eb=$?
    "$tmp/${n}_gen1.xin" > "$tmp/${n}_og" 2> "$tmp/${n}_eg"; eg=$?
    set -e
    cmp -s "$tmp/${n}_ob" "$tmp/${n}_og" || fail "output differs on $n"
    [ "$eb" = "$eg" ] || fail "exit code differs on $n ($eb vs $eg)"
    [ "$eg" = "1" ] || fail "$n did not fail loudly"
    [ -s "$tmp/${n}_eg" ] || fail "$n produced no diagnostic on stderr"
    loud_n=$((loud_n + 1))
done

# Chan/xu fail-loud: S7 close/send paths exit(1) without guaranteed stderr text.
CHAN_LOUD_PROBES="p30_chan_send_closed p31_chan_close_parked_sender"
chan_loud_n=0
for n in $CHAN_LOUD_PROBES; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing chan loud probe $prog"
    "$XU" "$prog" -o "$tmp/${n}_boot.xin" || fail "bootstrap could not compile $prog"
    "$GEN1" build "$prog" -o "$tmp/${n}_gen1.xin" || fail "gen1 could not build $prog"
    chmod +x "$tmp/${n}_boot.xin" "$tmp/${n}_gen1.xin"
    set +e
    "$tmp/${n}_boot.xin" > "$tmp/${n}_ob" 2> "$tmp/${n}_eb"; eb=$?
    "$tmp/${n}_gen1.xin" > "$tmp/${n}_og" 2> "$tmp/${n}_eg"; eg=$?
    set -e
    cmp -s "$tmp/${n}_ob" "$tmp/${n}_og" || fail "output differs on $n"
    [ "$eb" = "$eg" ] || fail "exit code differs on $n ($eb vs $eg)"
    [ "$eg" = "1" ] || fail "$n did not fail loudly (exit 1)"
    chan_loud_n=$((chan_loud_n + 1))
done

# Chan/xu behavior parity: S6 multi-waiter + Send closure capture (bootstrap ≡ gen1).
CHAN_BEHAVIOR="p33_chan_multi_sender_unbuffered p34_xu_send_fn_capture p35_select_recv_xu p36_select_string_owning"
chan_beh_n=0
for n in $CHAN_BEHAVIOR; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing chan behavior probe $prog"
    "$XU" "$prog" -o "$tmp/${n}_boot.xin" || fail "bootstrap could not compile $prog"
    "$GEN1" build "$prog" -o "$tmp/${n}_gen1.xin" || fail "gen1 could not build $prog"
    chmod +x "$tmp/${n}_boot.xin" "$tmp/${n}_gen1.xin"
    "$tmp/${n}_boot.xin" > "$tmp/${n}_ob" 2> "$tmp/${n}_eb"; eb=$?
    "$tmp/${n}_gen1.xin" > "$tmp/${n}_og" 2> "$tmp/${n}_eg"; eg=$?
    cmp -s "$tmp/${n}_ob" "$tmp/${n}_og" || fail "output differs on $n"
    [ "$eb" = "$eg" ] || fail "exit code differs on $n ($eb vs $eg)"
    [ "$eg" = "0" ] || fail "$n exited non-zero ($eg)"
    chan_beh_n=$((chan_beh_n + 1))
done

# M34 string payload: derived/index paths must round-trip (bootstrap ≡ gen1).
RESULT_PROBES="p182_result_string_index"
result_n=0
for n in $RESULT_PROBES; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing string-index probe $prog"
    "$XU" "$prog" -o "$tmp/${n}_boot.xin" || fail "bootstrap could not compile $prog"
    "$GEN1" build "$prog" -o "$tmp/${n}_gen1.xin" || fail "gen1 could not build $prog"
    chmod +x "$tmp/${n}_boot.xin" "$tmp/${n}_gen1.xin"
    "$tmp/${n}_boot.xin" > "$tmp/${n}_ob" 2> "$tmp/${n}_eb"; eb=$?
    "$tmp/${n}_gen1.xin" > "$tmp/${n}_og" 2> "$tmp/${n}_eg"; eg=$?
    cmp -s "$tmp/${n}_ob" "$tmp/${n}_og" || fail "string-index probe output differs on $n"
    [ "$eb" = "$eg" ] || fail "string-index probe exit differs on $n ($eb vs $eg)"
    [ "$eg" = "0" ] || fail "$n exited non-zero ($eg)"
    result_n=$((result_n + 1))
done

echo "safety_test: PASS (${safety_n} compile-time negatives rejected; ${loud_n} runtime loud probes; ${chan_loud_n} chan fail-loud; ${chan_beh_n} chan/xu behavior; ${result_n} string-index probes)"

scripts/safety_escape_test.sh --xu="$XU" --gen1="$GEN1" \
    || fail "safety_escape_test failed"
