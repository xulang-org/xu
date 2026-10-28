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
    local name=$1 src=$2 diagnostic=$3
    # AST rejects before MIR; gate must not turn this into a silent pass.
    set +e
    XU_MIR_BORROW_GATE=1 "$XU" build "$src" -o "$tmp/$name" >"$tmp/$name.out" 2>"$tmp/$name.err"
    rc=$?
    set -e
    if [ "$rc" -ne 0 ] && grep -Fq "$diagnostic" "$tmp/$name.err" && [ ! -e "$tmp/$name" ]; then
        echo "PASS ast-reject $name"
        pass=$((pass + 1))
    else
        echo "FAIL ast-reject $name (expected compile failure)" >&2
        fail=$((fail + 1))
    fi
}

echo "test_mir_borrow_gate: xu=$XU"

# Keep the smoke corpus here: the external tests/fixtures corpus is no longer
# part of this repository. Missing files must never count as AST rejections.
cat >"$tmp/kernel.xu" <<'XU'
@main
fn sum(xs &[]int) int {
    mut result := 0
    for i in 0:xs.len { result += xs[i] }
    << result
}
fn main() {
    mut xs := [1, 2, 3]
    for i in 0:xs.len { xs[i] *= 2 }
    println(sum(&xs))
    ch := chan string{cap: 1}
    ch <- "borrow gate"
    println(<-ch)
}
XU
cat >"$tmp/uam_arg.xu" <<'XU'
@main
fn consume(xs []int) {}
fn main() { xs := [1]
    consume(xs)
    println(xs[0])
}
XU
cat >"$tmp/uam_assign.xu" <<'XU'
@main
fn main() { xs := [1]
    mut ys := [2]
    ys = xs
    println(xs[0])
    println(ys[0])
}
XU
cat >"$tmp/dmut.xu" <<'XU'
@main
fn main() { mut x := 1
    p := mut &x
    q := mut &x
    println(*p)
    println(*q)
}
XU
expect_ok kernel "$tmp/kernel.xu"
expect_ast_reject uam_arg "$tmp/uam_arg.xu" "use of moved value"
expect_ast_reject uam_assign "$tmp/uam_assign.xu" "use of moved value"
expect_ast_reject dmut "$tmp/dmut.xu" "also borrowed"

# P1 includes Phase A/B loan checks, the G31 receiver exceptions and every
# Phase C spelling/automatic-borrow regression; enforce MIR on its positives.
XU_MIR_BORROW_GATE=1 python3 scripts/test_compiler_p1.py --xu "$XU" --front-only

echo "test_mir_borrow_gate: PASS=$pass FAIL=$fail"
if [ "$fail" -ne 0 ]; then
    exit 1
fi
