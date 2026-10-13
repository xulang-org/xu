#!/usr/bin/env bash
# Compile-time cross-target contract: every fixture must compile (or fail
# compilation, for err_* fixtures) on every supported target.
set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"

# BOUNDARY: cross-target compile contract is an oracle diagnostic.  It does
# not establish hosted product support or a self-host fixed point.
LANE="oracle"
echo "platform_contract: lane=oracle (bootstrap primer diagnostic; non-product evidence)" >&2

cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu || { echo "xu build failed"; exit 1; }
BIN=""
for primer in \
    "$BOOTSTRAP_ROOT/target/debug/xu" \
    "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
    "$BOOTSTRAP_ROOT/target/release/xu" \
    "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
    if [ -x "$primer" ]; then
        BIN="$primer"
        break
    fi
done
[ -n "$BIN" ] || { echo "platform_contract: bootstrap compiler missing after build" >&2; exit 1; }
if ! BIN=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$BIN" \
    "$ROOT/scripts/xu_host_seed.sh"); then
    echo "platform_contract: bootstrap compiler is not the canonical frozen primer" >&2
    exit 1
fi
TARGETS="macos-arm64 macos-x64 linux-arm64 linux-x64 windows-x64"

pass=0
fail=0
for dir in tests/fixtures/*/; do
    name=$(basename "$dir")
    expect_err=0
    [ -f "$dir/error.txt" ] && expect_err=1
    for target in $TARGETS; do
        tmp=$(mktemp -d)
        inputs="$dir/main.xu"
        for extra in "$dir"/*.xu; do
            [ "$extra" = "$dir/main.xu" ] && continue
            inputs="$inputs $extra"
        done
        if "$BIN" $inputs --target "$target" -o "$tmp/a.out" 2>/dev/null; then
            if [ "$expect_err" -eq 1 ]; then
                echo "FAIL $name/$target (expected compile error, succeeded)"
                fail=$((fail + 1))
            else
                pass=$((pass + 1))
            fi
        else
            if [ "$expect_err" -eq 1 ]; then
                pass=$((pass + 1))
            else
                echo "FAIL $name/$target (compile failed)"
                fail=$((fail + 1))
            fi
        fi
        rm -rf "$tmp"
    done
done
echo "platform contract: lane=$LANE PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
