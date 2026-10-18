#!/usr/bin/env bash
# Product TLS/ECDH cross-compilation gate. This does not claim target runtime
# coverage; scripts/tls_interop_test.sh owns host OpenSSL execution evidence.
set -euo pipefail
cd "$(dirname "$0")/.."

# Product-only TLS target-format gate. Resolve the hosted seed through the
# shared boundary and use the hermetic runner for the actual build; this
# script must never turn a missing hosted seed into a cargo/bootstrap run.
LANE="product"
HOST_SEED_RESOLVER="$PWD/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$PWD/scripts/run_product_compiler.sh"
COMPILER_INPUT=${XU_COMPILER:-${XU:-}}
[ -x "$HOST_SEED_RESOLVER" ] && [ -x "$PRODUCT_COMPILER_RUNNER" ] || {
    echo "tls_cross_compile_test: missing hosted seed/wrapper" >&2
    exit 1
}
if [ -n "$COMPILER_INPUT" ]; then
    case "$COMPILER_INPUT" in
        /*) ;;
        *) COMPILER_INPUT="$PWD/$COMPILER_INPUT" ;;
    esac
    XU=$(XU_SEED="$COMPILER_INPUT" \
        "$HOST_SEED_RESOLVER") || {
        echo "tls_cross_compile_test: compiler rejected by product boundary: $COMPILER_INPUT" >&2
        exit 1
    }
else
    XU=$("$HOST_SEED_RESOLVER") || {
        echo "tls_cross_compile_test: hosted product compiler missing (run make xu)" >&2
        exit 1
    }
fi
[ -x "$XU" ] || { echo "tls_cross_compile_test: compiler is not executable: $XU" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

fixture=tests/fixtures/crypto_tls_ecdhe_interop/main.xu
targets="linux-arm64 linux-x64 windows-x64 windows-arm64"

for target in $targets; do
    out="$work/$target.out"
    case "$target" in
        windows-*) out="$work/$target.exe" ;;
    esac
    "$PRODUCT_COMPILER_RUNNER" "$XU" build "$fixture" --target "$target" -o "$out"
    description=$(file "$out")
    case "$target" in
        linux-arm64) echo "$description" | grep -q "ELF 64-bit LSB executable, ARM aarch64" ;;
        linux-x64) echo "$description" | grep -q "ELF 64-bit LSB executable, x86-64" ;;
        windows-x64) echo "$description" | grep -q "PE32+ executable.*x86-64" ;;
        windows-arm64) echo "$description" | grep -qiE 'PE32\+.*(Aarch64|ARM64|aarch64)' ;;
    esac
    if [ "$target" = "windows-arm64" ]; then
        echo "PASS $target (compile+PE AArch64 only; no ARM64 runner)"
    else
        echo "PASS $target (compile+file)"
    fi
done

echo "tls_cross_compile_test: PASS (4/4 compile targets; runtime evidence is separate)"
