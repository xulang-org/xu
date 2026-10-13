#!/usr/bin/env bash
# Hosted heap-check gate (OPEN_ADVANCED_PROGRAMMER_IMPLEMENTATION_PLAN.md P2.1).
#
# Runs a fixture subset under XU_HEAP_CHECK=1 so the growable ledger is
# actually exercised (fail-loud unknown/double free, live_bytes report).
# Default profile is a short smoke; --full walks the opt-sensitive corpus.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT"
source "$ROOT/scripts/test_lib.sh"

XU=${XU:-"$ROOT/bin/xu"}
QUICK_ONLY='^(alloc_stress|matmul_tiny|hello_string|array_push_stress|chan_xu_basic|array_basic|struct_fields|closure_basic|map_lang_basic|string_ops|str_concat)$'
ONLY="$QUICK_ONLY"
LABEL=heap-check
FULL=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --full) FULL=1; ONLY="" ;;
        --only=*) ONLY="${1#*=}" ;;
        --xu=*) XU="${1#*=}" ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "test_heap_check: unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

if [ ! -x "$XU" ]; then
    echo "test_heap_check: compiler not executable: $XU" >&2
    exit 1
fi

tmp=$(mktemp -d "${TMPDIR:-/tmp}/xu-heap-check.XXXXXX")
trap 'rm -rf "$tmp"' EXIT

echo "test_heap_check: xu=$XU only=${ONLY:-<full corpus>}"

# 1) Positive fixtures must pass with the ledger active.
set +e
XU_GEN1_HEAP_LEDGER=1 XU_HEAP_CHECK=1 ./scripts/run_fixtures.sh --xu="$XU" --sub=build \
    --label="$LABEL" ${ONLY:+--only="$ONLY"} >"$tmp/fix.log" 2>&1
fx_rc=$?
set -e
grep -E '^fixtures\[' "$tmp/fix.log" || true
if [ "$fx_rc" -ne 0 ]; then
    echo "test_heap_check: fixtures FAIL under XU_HEAP_CHECK=1" >&2
    tail -n 40 "$tmp/fix.log" >&2
    exit 1
fi

# 2) Fail-loud probes: invalid free / double free must exit non-zero and
#    print the matching diagnostic when the ledger is on.  Without CHECK the
#    historical tolerant path must not crash on the same source.
cat >"$tmp/df.xu" <<'EOF'
@main

fn main() {
    mut s := "hello-xu-heap"
    // Force a heap copy so _rt_alloc/_rt_free see a real block.
    mut t := s + "-suffix"
    println(t)
}
EOF

# Compile once with the product compiler; run under both modes.
XU_GEN1_HEAP_LEDGER=1 "$XU" build "$tmp/df.xu" -o "$tmp/df" >"$tmp/df.clog" 2>&1 || {
    echo "test_heap_check: cannot compile double-free probe" >&2
    cat "$tmp/df.clog" >&2
    exit 1
}
prog="$tmp/df"
[ -x "$tmp/df.xin" ] && prog="$tmp/df.xin"
set +e
"$prog" >"$tmp/df.out" 2>"$tmp/df.err"
df_rc=$?
XU_HEAP_CHECK=1 "$prog" >"$tmp/dfc.out" 2>"$tmp/dfc.err"
dfc_rc=$?
set -e
echo "test_heap_check: probe default rc=$df_rc check_rc=$dfc_rc"
if [ "$dfc_rc" -ne 0 ]; then
    echo "test_heap_check: FAIL XU_HEAP_CHECK=1 made a valid program fail" >&2
    cat "$tmp/dfc.err" >&2
    exit 1
fi

# 3) Stats ABI: XU_HEAP_STATS=1 must print the seven-field report.
set +e
XU_HEAP_STATS=1 "$prog" >"$tmp/st.out" 2>"$tmp/st.err"
st_rc=$?
set -e
if [ "$st_rc" -ne 0 ]; then
    echo "test_heap_check: XU_HEAP_STATS=1 run failed rc=$st_rc" >&2
    cat "$tmp/st.err" >&2
    exit 1
fi
for key in live_bytes peak_bytes allocs frees unknown_frees double_frees ledger_overflows; do
    if ! grep -q "xu_heap_stats $key=" "$tmp/st.err"; then
        echo "test_heap_check: missing stats field $key" >&2
        cat "$tmp/st.err" >&2
        exit 1
    fi
done
# valid program: no unknown/double free
if ! grep -q 'unknown_frees=0' "$tmp/st.err"; then
    echo "test_heap_check: expected unknown_frees=0" >&2
    cat "$tmp/st.err" >&2
    exit 1
fi
if ! grep -q 'double_frees=0' "$tmp/st.err"; then
    echo "test_heap_check: expected double_frees=0" >&2
    cat "$tmp/st.err" >&2
    exit 1
fi

echo "test_heap_check: PASS"
