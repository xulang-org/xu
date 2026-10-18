#!/usr/bin/env bash
# Product compiler memory-safety gate.
#
# Every tests/gen1/safety/*.xu must be rejected by the product compiler
# with an error diagnostic on stderr.
# Runtime loud-fail probes must exit 1 with a diagnostic.
#
# Usage:
#   scripts/safety_test.sh
#   scripts/safety_test.sh --xu=/path/to/xu
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
export XU_ROOT="$ROOT"
cd "$ROOT"

HOST_SEED_RESOLVER="$PWD/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$PWD/scripts/run_product_compiler.sh"

XU=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) XU="${1#*=}" ;;
        --gen1=*) XU="${1#*=}" ;; # legacy flag alias
        *) echo "safety_test: unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

if [ -n "$XU" ]; then
    if ! XU=$(XU_SEED="$XU" "$HOST_SEED_RESOLVER"); then
        echo "safety_test: --xu must name a product compiler: $XU" >&2
        exit 1
    fi
else
    if ! XU=$("$HOST_SEED_RESOLVER"); then
        echo "safety_test: no product compiler found; run make xu or pass --xu=..." >&2
        exit 1
    fi
fi
[ -x "$XU" ] || { echo "safety_test: $XU not executable"; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { echo "safety_test: FAIL ($1)"; exit 1; }

compile_product() {
    "$PRODUCT_COMPILER_RUNNER" "$XU" "build" "$@"
}

safety_n=0
for bad in tests/gen1/safety/*.xu; do
    n=$(basename "$bad" .xu)
    set +e
    compile_product "$bad" -o "$tmp/safety_${n}.xin" >"$tmp/safety_${n}.out" 2>"$tmp/safety_${n}.err"
    rc=$?
    set -e
    [ "$rc" = "1" ] || fail "product compiler accepted unsafe program $bad"
    grep -Eq '^.*:[0-9]+:[0-9]+: error: ' "$tmp/safety_${n}.err" \
        || fail "expected a source error diagnostic for $bad (exit $rc)"
    expected="${bad%.xu}.stderr"
    [ -f "$expected" ] || fail "missing diagnostic expectation $expected"
    grep -m 1 -E '^.*:[0-9]+:[0-9]+: error: ' "$tmp/safety_${n}.err" >"$tmp/diagnostic"
    cmp -s "$expected" "$tmp/diagnostic" || fail "diagnostic changed for $bad (expected $expected)"
    safety_n=$((safety_n + 1))
done

LOUD_PROBES="p17_negative_index p18_slice_negative p19_slice_reverse p20_div_overflow_intmin p21_div_zero_loud p22_div_overflow_intmin_mod p191_as_fail_loud p_array_slice_oob"
loud_n=0
for n in $LOUD_PROBES; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing loud probe $prog"
    compile_product "$prog" -o "$tmp/${n}.xin" || fail "could not build $prog"
    chmod +x "$tmp/${n}.xin"
    set +e
    "$tmp/${n}.xin" > "$tmp/${n}.out" 2> "$tmp/${n}.err"; eg=$?
    set -e
    [ "$eg" = "1" ] || fail "$n did not fail loudly (exit $eg)"
    [ -s "$tmp/${n}.err" ] || fail "$n produced no diagnostic on stderr"
    loud_n=$((loud_n + 1))
done

# Chan/xu fail-loud: S7 close/send paths exit(1) without guaranteed stderr text.
CHAN_LOUD_PROBES="p30_chan_send_closed p31_chan_close_parked_sender"
chan_loud_n=0
for n in $CHAN_LOUD_PROBES; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing chan loud probe $prog"
    compile_product "$prog" -o "$tmp/${n}.xin" || fail "could not build $prog"
    chmod +x "$tmp/${n}.xin"
    set +e
    "$tmp/${n}.xin" > "$tmp/${n}.out" 2> "$tmp/${n}.err"; eg=$?
    set -e
    [ "$eg" = "1" ] || fail "$n did not fail loudly (exit 1, got $eg)"
    chan_loud_n=$((chan_loud_n + 1))
done

# Chan/xu behavior: S6 multi-waiter + Send closure capture.
CHAN_BEHAVIOR="p33_chan_multi_sender_unbuffered p34_xu_send_fn_capture p35_select_recv_xu p36_select_string_owning"
chan_beh_n=0
for n in $CHAN_BEHAVIOR; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing chan behavior probe $prog"
    compile_product "$prog" -o "$tmp/${n}.xin" || fail "could not build $prog"
    chmod +x "$tmp/${n}.xin"
    "$tmp/${n}.xin" > "$tmp/${n}.out" 2> "$tmp/${n}.err"; eg=$?
    [ "$eg" = "0" ] || fail "$n exited non-zero ($eg)"
    chan_beh_n=$((chan_beh_n + 1))
done

# M34 string payload: derived/index paths must round-trip.
RESULT_PROBES="p182_result_string_index"
result_n=0
for n in $RESULT_PROBES; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing string-index probe $prog"
    compile_product "$prog" -o "$tmp/${n}.xin" || fail "could not build $prog"
    chmod +x "$tmp/${n}.xin"
    "$tmp/${n}.xin" > "$tmp/${n}.out" 2> "$tmp/${n}.err"; eg=$?
    [ "$eg" = "0" ] || fail "$n exited non-zero ($eg)"
    result_n=$((result_n + 1))
done

echo "safety_test: PASS (${safety_n} compile-time negatives rejected; ${loud_n} runtime loud probes; ${chan_loud_n} chan fail-loud; ${chan_beh_n} chan/xu behavior; ${result_n} string-index probes)"

scripts/safety_escape_test.sh --xu="$XU" \
    || fail "safety_escape_test failed"
