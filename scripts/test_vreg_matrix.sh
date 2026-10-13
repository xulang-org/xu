#!/bin/sh
# Focused virtual-register regression matrix.  This intentionally avoids the
# full fixture/cross-target benchmark suites so allocator work can iterate
# quickly and deterministically.
set -eu

# Machine-readable boundary role: allocator/SSA oracle evidence.
BOUNDARY_LANE=oracle

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
BOOTSTRAP_ROOT=$("$repo_root/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$repo_root"
cargo_bin=${CARGO:-cargo}

cd "$BOOTSTRAP_ROOT"
"$cargo_bin" test -p xuemit --test vreg_matrix -- "$@"

# A tiny hosted execution check complements the plan/assembly assertions: the
# branch-value fixture exercises a comparison result that remains live on both
# CFG successors.  Run both disabled and fixed-home tiers and require exactly
# the same observable output.
if [ "${VREG_MATRIX_SKIP_RUNTIME:-0}" = 1 ]; then
    exit 0
fi

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/xu-vreg-matrix.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT

"$cargo_bin" build -q -p xu --bin xu
compiler="$BOOTSTRAP_ROOT/target/debug/xu"
for candidate in \
    "$BOOTSTRAP_ROOT/target/debug/xu" \
    "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
    "$BOOTSTRAP_ROOT/target/release/xu" \
    "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
    if [ -x "$candidate" ]; then
        compiler="$candidate"
        break
    fi
done
compiler=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$compiler" \
    "$repo_root/scripts/xu_host_seed.sh") || {
    echo "vreg matrix: bootstrap compiler is not the canonical frozen primer" >&2
    exit 1
}

for fixture_name in vreg_branch_value vreg_call_live vreg_local_cfg vreg_search_loop vreg_fwd_exit vreg_f64_temp vreg_f64_call_split; do
    fixture_dir="$repo_root/tests/fixtures/$fixture_name"
    expected=$(sed '/^[[:space:]]*$/d' "$fixture_dir/expected.txt")
    opts=O0
    if [ "$fixture_name" = vreg_search_loop ]; then
        opts="O1 O2 O3"
    elif [ "$fixture_name" = vreg_local_cfg ] || [ "$fixture_name" = vreg_fwd_exit ] || [ "$fixture_name" = vreg_f64_temp ] || [ "$fixture_name" = vreg_f64_call_split ]; then
        opts=O1
    fi

    for opt in $opts; do
        for mode in ra0 ra1 ra2 ra3 nrc; do
            case "$mode" in
                ra0) ra_arg=--ra=0 ;;
                ra1) ra_arg=--ra=1 ;;
                ra2) ra_arg=--ra=2 ;;
                ra3) ra_arg=--ra=3 ;;
                nrc) ra_arg=--no-regcache ;;
            esac
            "$compiler" "$fixture_dir/main.xu" "-$opt" "$ra_arg" \
                -o "$tmp_dir/${fixture_name}.${opt}.${mode}.xin" \
                >"$tmp_dir/${fixture_name}.${opt}.${mode}.compile.log" 2>&1
            actual=$("$tmp_dir/${fixture_name}.${opt}.${mode}.xin")
            if [ "$actual" != "$expected" ]; then
                printf '%s\n' "$fixture_name $opt $mode output mismatch:" >&2
                printf '%s\n' "$actual" >&2
                exit 1
            fi
        done
    done
done

printf '%s\n' "vreg matrix runtime: RA0/RA1/RA2/RA3/no-regcache outputs match for targeted fixtures"
