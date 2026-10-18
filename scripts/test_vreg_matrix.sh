#!/bin/sh
# Focused virtual-register regression matrix on the product compiler.
# Tests targeted fixtures across RA0..RA3 and no-regcache modes under O0/O1/O2/O3.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
export XU_ROOT="$repo_root"

HOST_SEED_RESOLVER="$repo_root/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$repo_root/scripts/run_product_compiler.sh"

compiler_input=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) compiler_input="${1#*=}" ;;
        *) echo "test_vreg_matrix: unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ -n "$compiler_input" ]; then
    compiler=$(XU_SEED="$compiler_input" "$HOST_SEED_RESOLVER")
else
    compiler=$("$HOST_SEED_RESOLVER")
fi
[ -x "$compiler" ] || {
    echo "test_vreg_matrix: product compiler not found or not executable" >&2
    exit 1
}

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/xu-vreg-matrix.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT

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
            "$PRODUCT_COMPILER_RUNNER" "$compiler" build "$fixture_dir/main.xu" "-$opt" "$ra_arg" \
                -o "$tmp_dir/${fixture_name}.${opt}.${mode}.xin" \
                >"$tmp_dir/${fixture_name}.${opt}.${mode}.compile.log" 2>&1
            chmod +x "$tmp_dir/${fixture_name}.${opt}.${mode}.xin"
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
