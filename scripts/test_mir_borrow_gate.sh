#!/usr/bin/env bash
# MIR borrow gate vs AST checker comparison (P1.1).
#
# Default compile is shadow (findings printed, not rejected).
# XU_MIR_BORROW_GATE=1 fails the compile on MIR borrow findings.
# AST check_10_borrow still runs first and is authoritative for moves.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT"

XU=${XU:-"$ROOT/bin/xu"}
if [ ! -x "$XU" ]; then
    echo "test_mir_borrow_gate: compiler not executable: $XU" >&2
    exit 1
fi

tmp=$(mktemp -d "${TMPDIR:-/tmp}/xu-mir-borrow-gate.XXXXXX")
trap 'rm -rf "$tmp"' EXIT

pass=0
fail=0

expect_ok() {
    local name=$1 src=$2
    if XU_MIR_BORROW_GATE=1 "$XU" build "$src" -o "$tmp/$name" >"$tmp/$name.out" 2>"$tmp/$name.err"; then
        echo "PASS gate-ok $name"
        pass=$((pass + 1))
    else
        echo "FAIL gate-ok $name (expected compile success)" >&2
        sed -n '1,20p' "$tmp/$name.err" >&2
        fail=$((fail + 1))
    fi
}

expect_ast_reject() {
    local name=$1 src=$2
    # AST rejects before MIR; gate must not turn this into a silent pass.
    set +e
    XU_MIR_BORROW_GATE=1 "$XU" build "$src" -o "$tmp/$name" >"$tmp/$name.out" 2>"$tmp/$name.err"
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
        echo "PASS ast-reject $name"
        pass=$((pass + 1))
    else
        echo "FAIL ast-reject $name (expected compile failure)" >&2
        fail=$((fail + 1))
    fi
}

echo "test_mir_borrow_gate: xu=$XU"

# Positive: clean kernels must pass the mandatory MIR gate.
expect_ok matmul tests/fixtures/matmul_tiny/main.xu
expect_ok alloc tests/fixtures/alloc_stress/main.xu
expect_ok cil tests/fixtures/copy_index_loop/main.xu
expect_ok nbody tests/fixtures/nbody_pair_rmw/main.xu
expect_ok chan_str tests/fixtures/chan_string/main.xu

# Negative: AST ownership errors still fail with gate enabled.
expect_ast_reject uam_arg tests/fixtures/err_use_after_move_arg/main.xu
expect_ast_reject uam_assign tests/fixtures/err_use_after_move_assign/main.xu
expect_ast_reject dmut tests/fixtures/err_double_mut_borrow/main.xu

echo "test_mir_borrow_gate: PASS=$pass FAIL=$fail"
if [ "$fail" -ne 0 ]; then
    exit 1
fi
