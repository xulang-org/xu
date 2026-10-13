#!/usr/bin/env bash
# Product-compiler regression for hosted X64 math lowering and f64 runtime IO.
set -euo pipefail
cd "$(dirname "$0")/.."

# This is a product-only regression.  Resolve the hosted seed through the
# canonical boundary and route every compiler invocation through the
# hermetic product wrapper; a bootstrap path must fail instead of becoming a
# silent oracle fallback.
LANE="product"
HOST_SEED_RESOLVER="$PWD/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$PWD/scripts/run_product_compiler.sh"
COMPILER_INPUT=${XU_COMPILER:-${XU_PRODUCT:-${XU:-}}}
if [ ! -x "$HOST_SEED_RESOLVER" ] || [ ! -x "$PRODUCT_COMPILER_RUNNER" ]; then
    echo "product_math_x64_test: missing hosted seed/wrapper" >&2
    exit 1
fi
if [ -n "$COMPILER_INPUT" ]; then
    case "$COMPILER_INPUT" in
        /*) ;;
        *) COMPILER_INPUT="$PWD/$COMPILER_INPUT" ;;
    esac
    XU_PRODUCT=$(XU_ALLOW_ORACLE_SEED=0 XU_SEED="$COMPILER_INPUT" \
        "$HOST_SEED_RESOLVER") || {
        echo "product_math_x64_test: compiler rejected by product boundary: $COMPILER_INPUT" >&2
        exit 1
    }
else
    XU_PRODUCT=$(XU_ALLOW_ORACLE_SEED=0 "$HOST_SEED_RESOLVER") || {
        echo "product_math_x64_test: hosted product compiler missing (run make xu)" >&2
        exit 1
    }
fi
[ -x "$XU_PRODUCT" ] || { echo "product_math_x64_test: compiler is not executable: $XU_PRODUCT" >&2; exit 1; }
if [ "$(uname -s)" != "Darwin" ]; then
    echo "product_math_x64_test: macOS or Rosetta execution is required" >&2
    exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for name in math_bits math_bits_extra f64_basic std_math; do
    dir="tests/fixtures/$name"
    out="$tmp/$name"
    "$PRODUCT_COMPILER_RUNNER" "$XU_PRODUCT" build "$dir/main.xu" --target macos-x64 -o "$out"
    chmod +x "$out"
    file "$out" | grep -q "Mach-O 64-bit executable x86_64"
    "$out" > "$tmp/$name.out"
    cmp "$dir/expected.txt" "$tmp/$name.out"
    echo "PASS $name/macos-x64 (product xu)"
done

echo "product_math_x64_test: PASS (4/4)"
