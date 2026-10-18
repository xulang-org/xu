#!/usr/bin/env bash
# Behavior cross-check of tests/gen1/programs on the product compiler (bin/xu).
#
# When a single compiler is checked (default), this runs a self-cross check
# between unoptimized (--no-opt) and default optimized builds: stdout and exit
# code must match byte-for-byte per program.
# Alternatively, if --baseline=path is supplied, it compares baseline against
# target.
#
# In both modes, loud-fail probes must exit 1 with a runtime diagnostic on stderr.
#
# Usage:
#   scripts/programs_cross_check.sh                 # bin/xu (--no-opt vs opt)
#   scripts/programs_cross_check.sh --xu=path       # any compiler binary
#   scripts/programs_cross_check.sh --baseline=path --xu=path
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
export XU_ROOT="$ROOT"
cd "$ROOT"

HOST_SEED_RESOLVER="$PWD/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$PWD/scripts/run_product_compiler.sh"

TARGET_INPUT=""
BASELINE_INPUT=""
SUB="build"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) TARGET_INPUT="${1#*=}" ;;
        --baseline=*) BASELINE_INPUT="${1#*=}" ;;
        --sub=*) SUB="${1#*=}" ;;
        *) echo "programs_cross_check: unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

if [ -n "$TARGET_INPUT" ]; then
    if ! TARGET=$(XU_SEED="$TARGET_INPUT" "$HOST_SEED_RESOLVER"); then
        echo "programs_cross_check: --xu must name a product compiler: $TARGET_INPUT" >&2
        exit 1
    fi
else
    if ! TARGET=$("$HOST_SEED_RESOLVER"); then
        echo "programs_cross_check: no product compiler found; run make xu or pass --xu=..." >&2
        exit 1
    fi
fi
[ -x "$TARGET" ] || { echo "programs_cross_check: $TARGET not executable"; exit 1; }

BASELINE=""
if [ -n "$BASELINE_INPUT" ]; then
    if ! BASELINE=$(XU_SEED="$BASELINE_INPUT" "$HOST_SEED_RESOLVER"); then
        echo "programs_cross_check: --baseline must name an executable product compiler: $BASELINE_INPUT" >&2
        exit 1
    fi
    [ -x "$BASELINE" ] || { echo "programs_cross_check: $BASELINE not executable"; exit 1; }
    echo "programs_cross_check: cross-checking baseline ($BASELINE) vs target ($TARGET)" >&2
else
    echo "programs_cross_check: self-cross check on $TARGET (--no-opt vs default opt)" >&2
fi

compile_a() {
    if [ -n "$BASELINE" ]; then
        "$PRODUCT_COMPILER_RUNNER" "$BASELINE" "$SUB" "$@"
    else
        "$PRODUCT_COMPILER_RUNNER" "$TARGET" "$SUB" "--no-opt" "$@"
    fi
}

compile_b() {
    "$PRODUCT_COMPILER_RUNNER" "$TARGET" "$SUB" "$@"
}

. ./scripts/lang_gate_skip.sh

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

n=0
fail=0
skipped=0
for prog in tests/gen1/programs/*.xu; do
    name=$(basename "$prog" .xu)
    if lang_gate_skip_program "$prog"; then
        echo "SKIP $name (net package; not language-compiler gate)"
        skipped=$((skipped + 1))
        continue
    fi
    if ! compile_a "$prog" -o "$tmp/${name}_a.xin" 2> "$tmp/${name}_ea_err"; then
        echo "FAIL $name (compiler A compile failed)"
        fail=$((fail + 1))
        continue
    fi
    if ! compile_b "$prog" -o "$tmp/${name}_b.xin" 2> "$tmp/${name}_eb_err"; then
        echo "FAIL $name (compiler B compile failed)"
        fail=$((fail + 1))
        continue
    fi
    chmod +x "$tmp/${name}_a.xin" "$tmp/${name}_b.xin"
    run_arg=""
    [ "$name" = "p14_args" ] && run_arg="probe"
    if "$tmp/${name}_a.xin" $run_arg > "$tmp/${name}_oa" 2> "$tmp/${name}_ea"; then
        ea=0
    else
        ea=$?
    fi
    if "$tmp/${name}_b.xin" $run_arg > "$tmp/${name}_ob" 2> "$tmp/${name}_eb"; then
        eb=0
    else
        eb=$?
    fi
    n=$((n + 1))
    if ! cmp -s "$tmp/${name}_oa" "$tmp/${name}_ob"; then
        echo "FAIL $name (stdout differs between modes)"
        fail=$((fail + 1))
        continue
    fi
    if [ "$ea" != "$eb" ]; then
        echo "FAIL $name (exit $ea vs $eb)"
        fail=$((fail + 1))
        continue
    fi
    case "$name" in
        p17_negative_index|p18_slice_negative|p19_slice_reverse|p20_div_overflow_intmin|p21_div_zero_loud|p22_div_overflow_intmin_mod)
            if [ "$eb" != "1" ]; then
                echo "FAIL $name (expected loud exit 1, got $eb)"
                fail=$((fail + 1))
                continue
            fi
            if [ ! -s "$tmp/${name}_eb" ]; then
                echo "FAIL $name (no runtime diagnostic on stderr)"
                fail=$((fail + 1))
                continue
            fi
            ;;
        p30_chan_send_closed|p31_chan_close_parked_sender)
            if [ "$eb" != "1" ]; then
                echo "FAIL $name (expected loud exit 1, got $eb)"
                fail=$((fail + 1))
                continue
            fi
            ;;
    esac
done

status=PASS
[ "$fail" -eq 0 ] && [ "$n" -gt 0 ] || status=FAIL
echo "programs_cross_check: $status compared=$n fail=$fail skip-net=$skipped (target $TARGET)"
[ "$status" = PASS ]
