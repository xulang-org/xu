#!/usr/bin/env bash
# Complex memory-escape gate.
#
# Every tests/gen1/safety/escape/*.xu must be rejected by the product compiler.
# Legal elision / Send paths must compile and run cleanly (exit 0).
#
# Usage:
#   scripts/safety_escape_test.sh
#   scripts/safety_escape_test.sh --xu=/path/to/xu
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
        *) echo "safety_escape_test: unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

if [ -n "$XU" ]; then
    if ! XU=$(XU_SEED="$XU" "$HOST_SEED_RESOLVER"); then
        echo "safety_escape_test: --xu must name a product compiler: $XU" >&2
        exit 1
    fi
else
    if ! XU=$("$HOST_SEED_RESOLVER"); then
        echo "safety_escape_test: no product compiler found; run make xu or pass --xu=..." >&2
        exit 1
    fi
fi
[ -x "$XU" ] || { echo "safety_escape_test: $XU not executable"; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { echo "safety_escape_test: FAIL ($1)"; exit 1; }

compile_product() {
    "$PRODUCT_COMPILER_RUNNER" "$XU" "build" "$@"
}

escape_n=0
for bad in tests/gen1/safety/escape/*.xu; do
    [ -f "$bad" ] || continue
    n=$(basename "$bad" .xu)
    set +e
    compile_product "$bad" -o "$tmp/escape_${n}.xin" >"$tmp/escape_${n}.out" 2>"$tmp/escape_${n}.err"
    rc=$?
    set -e
    [ "$rc" = "1" ] || fail "product compiler accepted escape unsafe program $bad"
    grep -Eq '^.*:[0-9]+:[0-9]+: error: ' "$tmp/escape_${n}.err" \
        || fail "expected a source error diagnostic for $bad (exit $rc)"
    expected="${bad%.xu}.stderr"
    [ -f "$expected" ] || fail "missing diagnostic expectation $expected"
    grep -m 1 -E '^.*:[0-9]+:[0-9]+: error: ' "$tmp/escape_${n}.err" >"$tmp/diagnostic"
    cmp -s "$expected" "$tmp/diagnostic" || fail "diagnostic changed for $bad (expected $expected)"
    escape_n=$((escape_n + 1))
done

[ "$escape_n" -gt 0 ] || fail "no tests/gen1/safety/escape/*.xu found"

# Legal elision / Send paths (must compile and run with exit 0).
ESCAPE_OK="p150_ref_return_struct p153_closure_capture_ref p29_xu_generic p155_match_string_clone p183_if_string_clone p184_while_string_clone p185_select_string_clone"
ok_n=0
for n in $ESCAPE_OK; do
    prog="tests/gen1/programs/${n}.xu"
    [ -f "$prog" ] || fail "missing escape OK probe $prog"
    compile_product "$prog" -o "$tmp/${n}.xin" || fail "could not build OK $prog"
    chmod +x "$tmp/${n}.xin"
    "$tmp/${n}.xin" > "$tmp/${n}.out" 2> "$tmp/${n}.err"; eg=$?
    [ "$eg" = "0" ] || fail "escape OK $n exited non-zero ($eg)"
    ok_n=$((ok_n + 1))
done

echo "safety_escape_test: PASS (${escape_n} escape negatives rejected; ${ok_n} legal elision probes)"
