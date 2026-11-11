#!/bin/sh
# Focused virtual-register regression matrix on the product compiler.
# Compare register-allocated and unoptimized output for targeted fixtures.
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
    for mode in default no-opt; do
        set --
        if [ "$mode" = no-opt ]; then set -- --no-opt; fi
        program="$tmp_dir/${fixture_name}.${mode}.xin"
        "$PRODUCT_COMPILER_RUNNER" "$compiler" build "$fixture_dir/main.xu" "$@" -o "$program" \
            >"$tmp_dir/${fixture_name}.${mode}.compile.log" 2>&1
        chmod +x "$program"
        actual=$("$program")
        if [ "$actual" != "$expected" ]; then
            printf '%s\n' "$fixture_name $mode output mismatch:" >&2
            printf '%s\n' "$actual" >&2
            exit 1
        fi
    done
done

printf '%s\n' "vreg matrix runtime: default and no-opt outputs match for targeted fixtures"
