#!/usr/bin/env bash
set -euo pipefail

source scripts/test_lib.sh

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

set +e
run_with_timeout 2 python3 -c 'import os, signal; os.kill(os.getpid(), signal.SIGSEGV)' \
    >"$tmp/signal.out" 2>"$tmp/signal.err"
signal_rc=$?
set -e
if [ "$signal_rc" -ne 139 ]; then
    echo "run_with_timeout signal mapping: got $signal_rc, want 139" >&2
    exit 1
fi

printf 'expected\n' >"$tmp/expected.out"
printf 'partial\n' >"$tmp/actual.out"
printf 'expected stderr\n' >"$tmp/expected.err"
printf 'actual stderr\n' >"$tmp/actual.err"

check_kind() {
    local want="$1"
    shift
    local got
    got=$(fixture_runtime_result_kind "$@")
    if [ "$got" != "$want" ]; then
        echo "fixture result kind: got $got, want $want" >&2
        exit 1
    fi
}

# A crash with partial output must report the exit code, not stdout mismatch.
check_kind exit 139 0 "$tmp/expected.out" "$tmp/actual.out"
check_kind timeout 124 0 "$tmp/expected.out" "$tmp/actual.out"
check_kind stdout 0 0 "$tmp/expected.out" "$tmp/actual.out"

cp "$tmp/expected.out" "$tmp/actual.out"
check_kind stderr 0 0 "$tmp/expected.out" "$tmp/actual.out" \
    "$tmp/expected.err" "$tmp/actual.err"

# Non-zero expected exits are valid and still require exact output.
cp "$tmp/expected.err" "$tmp/actual.err"
check_kind pass 7 7 "$tmp/expected.out" "$tmp/actual.out" \
    "$tmp/expected.err" "$tmp/actual.err"

echo "fixture runtime result precedence: PASS"
