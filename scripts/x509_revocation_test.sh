#!/usr/bin/env bash
# Compile once, then isolate each CRL validation scenario in its own process.
set -euo pipefail

cd "$(dirname "$0")/.."
# Product-only X.509 revocation gate. Resolve the hosted seed canonically and
# route compilation through the hermetic product wrapper; a primer path must
# fail closed rather than silently becoming an oracle run.
LANE="product"
HOST_SEED_RESOLVER="$PWD/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$PWD/scripts/run_product_compiler.sh"
COMPILER_INPUT=${XU_COMPILER:-${XU:-}}
[ -x "$HOST_SEED_RESOLVER" ] && [ -x "$PRODUCT_COMPILER_RUNNER" ] || {
    echo "x509_revocation_test: missing hosted seed/wrapper" >&2
    exit 1
}
if [ -n "$COMPILER_INPUT" ]; then
    case "$COMPILER_INPUT" in
        /*) ;;
        *) COMPILER_INPUT="$PWD/$COMPILER_INPUT" ;;
    esac
    xu_bin=$(XU_ALLOW_ORACLE_SEED=0 XU_SEED="$COMPILER_INPUT" \
        "$HOST_SEED_RESOLVER") || {
        echo "x509_revocation_test: compiler rejected by product boundary: $COMPILER_INPUT" >&2
        exit 1
    }
else
    xu_bin=$(XU_ALLOW_ORACLE_SEED=0 "$HOST_SEED_RESOLVER") || {
        echo "x509_revocation_test: hosted product compiler missing (run make xu)" >&2
        exit 1
    }
fi
[ -x "$xu_bin" ] || { echo "x509_revocation_test: compiler is not executable: $xu_bin" >&2; exit 1; }
work=$(mktemp -d /tmp/xu-x509-revocation.XXXXXX)
trap 'rm -rf "$work"' EXIT
program="$work/revocation.xin"

"$PRODUCT_COMPILER_RUNNER" "$xu_bin" build \
    tests/fixtures/crypto_x509_revocation/main.xu -o "$program"

cases=(
    off_without_crl:true
    if_present_without_crl:true
    require_without_crl:false
    if_present_good_leaf_crl:true
    bad_signature:false
    expired_crl:false
    missing_next_update:false
    issuer_without_crl_sign:false
    unknown_critical_crl:false
    invalid_mode:false
    require_complete_crls:true
    revoked_leaf:false
)

for item in "${cases[@]}"; do
    name=${item%%:*}
    want=${item#*:}
    got=$("$program" "$name")
    if [ "$got" != "$name=$want" ]; then
        echo "x509 revocation: FAIL $name (want $name=$want, got $got)" >&2
        exit 1
    fi
done

echo "x509 revocation: PASS (${#cases[@]} cases)"
