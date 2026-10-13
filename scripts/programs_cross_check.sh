#!/usr/bin/env bash
# Behavior cross-check of tests/gen1/programs between the Rust bootstrap and
# another compiler binary (default: bin/xu, the gen3 product).
# stdout and exit code must match per program; loud-fail probes must exit 1
# with a runtime diagnostic (same rules as gen1_test.sh step 6).
#
# Usage:
#   scripts/programs_cross_check.sh                 # bin/xu (gen3)
#   scripts/programs_cross_check.sh --xu=path       # any compiler binary
#   scripts/programs_cross_check.sh --xu=path --sub=build
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"

# BOUNDARY: dual lane.  Every result compares the frozen bootstrap oracle
# against an explicitly selected hosted product compiler; neither side alone
# is a product fixed-point proof.  The oracle is called directly, while the
# product side goes through the canonical resolver/hermetic wrapper.
LANE="dual"
HOST_SEED_RESOLVER="$PWD/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$PWD/scripts/run_product_compiler.sh"

OTHER_INPUT=""
SUB="build"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) OTHER_INPUT="${1#*=}" ;;
        --sub=*) SUB="${1#*=}" ;;
        *) echo "programs_cross_check: unknown arg $1"; exit 1 ;;
    esac
    shift
done

cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu \
    || { echo "programs_cross_check: bootstrap build failed"; exit 1; }
BOOT="$BOOTSTRAP_ROOT/target/debug/xu"
for candidate in \
    "$BOOTSTRAP_ROOT/target/debug/xu" \
    "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
    "$BOOTSTRAP_ROOT/target/release/xu" \
    "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
    if [ -x "$candidate" ]; then
        BOOT="$candidate"
        break
    fi
done
if ! BOOT=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$BOOT" \
    "$ROOT/scripts/xu_host_seed.sh"); then
    echo "programs_cross_check: bootstrap compiler is not the canonical frozen primer" >&2
    exit 1
fi
if [ -n "$OTHER_INPUT" ]; then
    if ! OTHER=$(XU_ALLOW_ORACLE_SEED=0 XU_SEED="$OTHER_INPUT" "$HOST_SEED_RESOLVER"); then
        echo "programs_cross_check: --xu must name a hosted product compiler (primer is oracle-only)" >&2
        exit 1
    fi
else
    if ! OTHER=$(XU_ALLOW_ORACLE_SEED=0 "$HOST_SEED_RESOLVER"); then
        echo "programs_cross_check: no hosted product compiler; run make xu or pass --xu=..." >&2
        exit 1
    fi
fi
[ -x "$OTHER" ] || { echo "programs_cross_check: $OTHER not found or not executable (make xu?)"; exit 1; }
echo "programs_cross_check: lane=dual (bootstrap=oracle, other=product)" >&2

compile_product() {
    "$PRODUCT_COMPILER_RUNNER" "$OTHER" "$SUB" "$@"
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
    if ! "$BOOT" "$prog" -o "$tmp/${name}_boot.xin"; then
        echo "FAIL $name (bootstrap compile)"
        fail=$((fail + 1))
        continue
    fi
    if ! compile_product "$prog" -o "$tmp/${name}_other.xin"; then
        echo "FAIL $name (other compile)"
        fail=$((fail + 1))
        continue
    fi
    chmod +x "$tmp/${name}_boot.xin" "$tmp/${name}_other.xin"
    run_arg=""
    [ "$name" = "p14_args" ] && run_arg="probe"
    if "$tmp/${name}_boot.xin" $run_arg > "$tmp/${name}_ob" 2> "$tmp/${name}_eb"; then
        eb=0
    else
        eb=$?
    fi
    if "$tmp/${name}_other.xin" $run_arg > "$tmp/${name}_og" 2> "$tmp/${name}_eg"; then
        eg=0
    else
        eg=$?
    fi
    n=$((n + 1))
    if ! cmp -s "$tmp/${name}_ob" "$tmp/${name}_og"; then
        echo "FAIL $name (stdout differs)"
        fail=$((fail + 1))
        continue
    fi
    if [ "$eb" != "$eg" ]; then
        echo "FAIL $name (exit $eb vs $eg)"
        fail=$((fail + 1))
        continue
    fi
    case "$name" in
        p17_negative_index|p18_slice_negative|p19_slice_reverse|p20_div_overflow_intmin|p21_div_zero_loud|p22_div_overflow_intmin_mod)
            if [ "$eg" != "1" ]; then
                echo "FAIL $name (expected loud exit 1, got $eg)"
                fail=$((fail + 1))
                continue
            fi
            if [ ! -s "$tmp/${name}_eg" ]; then
                echo "FAIL $name (no runtime diagnostic on stderr)"
                fail=$((fail + 1))
                continue
            fi
            ;;
        p30_chan_send_closed|p31_chan_close_parked_sender)
            if [ "$eg" != "1" ]; then
                echo "FAIL $name (expected loud exit 1, got $eg)"
                fail=$((fail + 1))
                continue
            fi
            ;;
    esac
done

echo "programs_cross_check: lane=dual compared=$n fail=$fail skip-net=$skipped (bootstrap=oracle vs product $OTHER)"
[ "$fail" -eq 0 ]
