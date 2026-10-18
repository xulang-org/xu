#!/usr/bin/env bash
# Product-compiler regression for hosted X64 algorithm lowering and stdlib.
set -euo pipefail
cd "$(dirname "$0")/.."

# Product-only regression: resolve the hosted seed through the canonical
# boundary and invoke it through the isolated product wrapper.  A primer path
# is rejected instead of silently becoming oracle evidence.
LANE="product"
HOST_SEED_RESOLVER="$PWD/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$PWD/scripts/run_product_compiler.sh"
COMPILER_INPUT=${XU_COMPILER:-${XU_PRODUCT:-${XU:-}}}
if [ ! -x "$HOST_SEED_RESOLVER" ] || [ ! -x "$PRODUCT_COMPILER_RUNNER" ]; then
    echo "product_algorithm_x64_test: missing hosted seed/wrapper" >&2
    exit 1
fi
if [ -n "$COMPILER_INPUT" ]; then
    case "$COMPILER_INPUT" in
        /*) ;;
        *) COMPILER_INPUT="$PWD/$COMPILER_INPUT" ;;
    esac
    XU_PRODUCT=$(XU_SEED="$COMPILER_INPUT" \
        "$HOST_SEED_RESOLVER") || {
        echo "product_algorithm_x64_test: compiler rejected by product boundary: $COMPILER_INPUT" >&2
        exit 1
    }
else
    XU_PRODUCT=$("$HOST_SEED_RESOLVER") || {
        echo "product_algorithm_x64_test: hosted product compiler missing (run make xu)" >&2
        exit 1
    }
fi
[ -x "$XU_PRODUCT" ] || { echo "product_algorithm_x64_test: compiler is not executable: $XU_PRODUCT" >&2; exit 1; }
if [ "$(uname -s)" != "Darwin" ]; then
    echo "product_algorithm_x64_test: macOS or Rosetta execution is required" >&2
    exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for name in std_sort sort_ints_partition sort_slice sort_slice_func slices_sort_extra std_slice container_heap; do
    dir="tests/fixtures/$name"
    out="$tmp/$name"
    "$PRODUCT_COMPILER_RUNNER" "$XU_PRODUCT" build "$dir/main.xu" --target macos-x64 -o "$out"
    chmod +x "$out"
    file "$out" | grep -q "Mach-O 64-bit executable x86_64"
    "$out" > "$tmp/$name.out"
    cmp "$dir/expected.txt" "$tmp/$name.out"
    echo "PASS $name/macos-x64 (product xu)"
done

out="$tmp/algorithm_search"
"$PRODUCT_COMPILER_RUNNER" "$XU_PRODUCT" build tests/data/compiler_workloads/algorithm_search.xu --target macos-x64 -o "$out"
chmod +x "$out"
file "$out" | grep -q "Mach-O 64-bit executable x86_64"
"$out" > "$tmp/algorithm_search.out"
printf '393215066828\n' > "$tmp/algorithm_search.expected"
cmp "$tmp/algorithm_search.expected" "$tmp/algorithm_search.out"
echo "PASS algorithm_search/macos-x64 (product xu)"

echo "product_algorithm_x64_test: PASS (8/8)"
