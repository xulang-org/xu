#!/usr/bin/env bash
# Oracle-seeded self-host chain for a platform that has no hosted seed yet
# (A1 in OVERALL_OPTIMIZATION_PLAN_2026-09.md; .github/workflows/platforms.yml).
#
# The frozen Rust primer compiles Gen1 (-O0), then Gen1 -> Gen2 (warm-up)
# -> Gen3 -> Gen4 run on *this* OS/ISA and Gen3 must equal Gen4 byte for
# byte.  This is run evidence for the hosted compiler code on the current
# platform.  It is NOT product/release evidence: the seed is the primer
# (bootstrap/FROZEN.md), nothing is installed into bin/, and the sidecar says
# lane=oracle.  build_hosted_chain.sh cannot be used here because the primer
# has no `build` subcommand; that script is the product lane with a hosted
# seed.
#
# Usage:
#   scripts/oracle_platform_chain.sh <dest-dir>            # writes <dest-dir>/xu[.exe] + chain.env
#   scripts/oracle_platform_chain.sh <dest-dir> --keep     # keep gen1..gen4 and logs in <dest-dir>
#
# Environment: XU_CI_LANE is set to oracle for the duration; TMPDIR is honoured.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"

# Machine-readable boundary role: frozen-primer oracle evidence only.
BOUNDARY_LANE=oracle
export XU_CI_LANE=oracle
source scripts/test_lib.sh
. ./scripts/gen1_sources.sh

if [ "$#" -lt 1 ]; then
    echo "usage: scripts/oracle_platform_chain.sh <dest-dir> [--keep]" >&2
    exit 1
fi
DEST_DIR=$1
shift
KEEP=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --keep) KEEP=1 ;;
        *) echo "oracle_platform_chain: unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
case "$(cd "$(dirname "$DEST_DIR")" 2>/dev/null && pwd -P)/$(basename "$DEST_DIR")" in
    "$ROOT/bin"|"$ROOT/bin/"*|"$ROOT/developer/bin"|"$ROOT/developer/bin/"*|"$BOOTSTRAP_ROOT"|"$BOOTSTRAP_ROOT/"*)
        echo "oracle_platform_chain: refusing product/primer destination $DEST_DIR (oracle artifacts stay outside bin/, developer/bin/, bootstrap/)" >&2
        exit 1
        ;;
esac
mkdir -p "$DEST_DIR"
DEST_DIR=$(cd "$DEST_DIR" && pwd -P)

HOP_EXT=".xin"
PRIMER_NAME="xu"
host_os=""
host_arch=""
case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin) host_os=macos ;;
    Linux) host_os=linux ;;
    MINGW*|MSYS*|CYGWIN*) host_os=windows; HOP_EXT=".exe"; PRIMER_NAME="xu.exe" ;;
esac
if [ "${OS-}" = "Windows_NT" ]; then host_os=windows; HOP_EXT=".exe"; PRIMER_NAME="xu.exe"; fi
native_machine=$(python3 -c 'import platform, sys; sys.stdout.write(platform.machine().lower())')
case "$native_machine" in
    arm64|aarch64) host_arch=arm64 ;;
    x86_64|amd64) host_arch=x64 ;;
    loongarch64) host_arch=loongarch64 ;;
    riscv64) host_arch=riscv64 ;;
esac
if [ -z "$host_os" ] || [ -z "$host_arch" ]; then
    echo "oracle_platform_chain: unsupported host $(uname -s)/$(uname -m)" >&2
    exit 1
fi
# The primer's default target is not guaranteed to be this host (windows.yml
# passes it explicitly); the hosted hops default to their own build target.
HOST_TARGET="$host_os-$host_arch"

# Only the canonical frozen primer of this checkout may seed the chain.
PRIMER="$BOOTSTRAP_ROOT/target/debug/$PRIMER_NAME"
[ -x "$PRIMER" ] || PRIMER="$BOOTSTRAP_ROOT/target/release/$PRIMER_NAME"
if [ ! -x "$PRIMER" ]; then
    echo "oracle_platform_chain: frozen primer not built (cargo build -p xu --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml")" >&2
    exit 1
fi
PRIMER=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$PRIMER" ./scripts/xu_host_seed.sh) || {
    echo "oracle_platform_chain: bootstrap compiler is not the canonical frozen primer" >&2
    exit 1
}

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'; else sha256sum "$1" | awk '{print $1}'; fi
}
file_size() {
    if s=$(stat -f '%z' "$1" 2>/dev/null); then echo "$s"; else stat -c '%s' "$1"; fi
}
pick_bin() {
    for cand in "$1" "${1}.exe"; do
        if [ -x "$cand" ]; then echo "$cand"; return 0; fi
    done
    echo "oracle_platform_chain: missing artifact $1" >&2
    return 1
}

WORK="$DEST_DIR/chain"
rm -rf -- "$WORK"
mkdir -p "$WORK"
STAGE="setup"
STATUS=BLOCKED
cleanup() {
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "oracle_platform_chain: chain BLOCKED lane=oracle stage=$STAGE exit=$rc" >&2
    fi
    if [ "$KEEP" = 0 ] && [ "$rc" -eq 0 ]; then
        rm -rf -- "$WORK"
    fi
    echo "oracle_platform_chain: $STATUS lane=$BOUNDARY_LANE host=$(uname -s)/$(uname -m)"
    return "$rc"
}
trap cleanup EXIT

# Same hermetic environment as the product chain: no ambient search roots,
# package caches or target overrides may leak into a hop.
export LC_ALL=C
export XUPATH=""
export XU_STDLIB_ROOT="$(python3 -c 'from pathlib import Path; import sys; sys.stdout.write(Path("src").resolve().as_posix())')"
export XU_CACHE="$WORK/xu-cache"
export HOME="$WORK/home"
export USERPROFILE="$HOME"
mkdir -p "$XU_CACHE" "$HOME"
unset XUOS XUARCH XU_BOOT_EXTRA XU_HEAP_STATS XU_SEED XU_ALLOW_ORACLE_SEED

HOP_TIMEOUT=${XU_ORACLE_CHAIN_HOP_TIMEOUT:-3600}
hop() {
    local xu="$1" out="$2" rc
    shift 2
    set +e
    # shellcheck disable=SC2086
    run_with_timeout "$HOP_TIMEOUT" "$xu" "$@" $GEN1_SRCS -o "$out" >"$out.log" 2>&1
    rc=$?
    set -e
    if [ "$rc" -eq 124 ]; then
        echo "oracle_platform_chain: hop timed out after ${HOP_TIMEOUT}s ($xu)" >&2
        return 124
    fi
    if [ "$rc" -ne 0 ]; then
        echo "oracle_platform_chain: hop failed rc=$rc ($xu):" >&2
        tail -30 "$out.log" | sed 's/^/  | /' >&2
        return "$rc"
    fi
    pick_bin "$out" >/dev/null
}

echo "oracle_platform_chain: lane=oracle (frozen primer seed; not product evidence)"
echo "oracle_platform_chain: primer=$PRIMER"
echo "oracle_platform_chain: host=$(uname -s)/$(uname -m) target=$HOST_TARGET hop_ext=$HOP_EXT"

STAGE="primer_to_gen1"
t0=$(date +%s)
# The primer's CLI is `xu [flags] files -o out`; it stays at -O0 (see
# gen1_test.sh: primer auto/O1 is not on the oracle path).
hop "$PRIMER" "$WORK/gen1$HOP_EXT" -O0 --target "$HOST_TARGET"
G1=$(pick_bin "$WORK/gen1$HOP_EXT")
echo "oracle_platform_chain: gen1=$G1 wall=$(( $(date +%s) - t0 ))s"

STAGE="gen1_smoke"
"$G1" --version >"$WORK/gen1.version" 2>&1 || "$G1" --ver >"$WORK/gen1.version" 2>&1 || true
# `--version` prints a banner; report the first line carrying a version number.
echo "oracle_platform_chain: gen1 runs: $(tr -d '\r' <"$WORK/gen1.version" | grep -m1 -E '[0-9]+\.[0-9]+' || head -1 "$WORK/gen1.version")"

STAGE="gen1_to_gen2"
t0=$(date +%s)
hop "$G1" "$WORK/gen2$HOP_EXT" build --timings
G2=$(pick_bin "$WORK/gen2$HOP_EXT")
echo "oracle_platform_chain: gen2=$G2 wall=$(( $(date +%s) - t0 ))s $(grep '^timings:' "$WORK/gen2$HOP_EXT.log" | tail -1 || true)"

STAGE="gen2_to_gen3"
t0=$(date +%s)
hop "$G2" "$WORK/gen3$HOP_EXT" build --timings
G3=$(pick_bin "$WORK/gen3$HOP_EXT")
echo "oracle_platform_chain: gen3=$G3 wall=$(( $(date +%s) - t0 ))s $(grep '^timings:' "$WORK/gen3$HOP_EXT.log" | tail -1 || true)"

STAGE="gen3_to_gen4"
t0=$(date +%s)
hop "$G3" "$WORK/gen4$HOP_EXT" build --timings
G4=$(pick_bin "$WORK/gen4$HOP_EXT")
echo "oracle_platform_chain: gen4=$G4 wall=$(( $(date +%s) - t0 ))s $(grep '^timings:' "$WORK/gen4$HOP_EXT.log" | tail -1 || true)"

STAGE="fixed_point_cmp"
if cmp -s "$G2" "$G3"; then
    echo "oracle_platform_chain: warm-up already stable (Gen2 == Gen3)"
else
    echo "oracle_platform_chain: warm-up transition recorded (Gen2 != Gen3; the check is Gen3 == Gen4)"
fi
cmp "$G3" "$G4"

STAGE="export"
OUT="$DEST_DIR/$PRIMER_NAME"
cp "$G4" "$OUT"
chmod +x "$OUT"
cat >"$DEST_DIR/chain.env" <<EOF
schema=1
status=PASS
lane=oracle
seed=frozen-primer
host_os=$(uname -s)
host_arch=$(uname -m)
repo_head=$(git rev-parse HEAD 2>/dev/null || echo unknown)
primer_sha256=$(sha256_file "$PRIMER")
gen1_sha256=$(sha256_file "$G1")
gen2_sha256=$(sha256_file "$G2")
gen3_sha256=$(sha256_file "$G3")
gen4_sha256=$(sha256_file "$G4")
gen3_size=$(file_size "$G3")
gen4_size=$(file_size "$G4")
gen2_gen3_cmp=$(cmp -s "$G2" "$G3" && echo PASS || echo DIFFERENT)
gen3_gen4_cmp=PASS
product_evidence=false
EOF
STATUS=PASS
STAGE=""
echo "oracle_platform_chain: artifact=$OUT"
echo "oracle_platform_chain: sidecar=$DEST_DIR/chain.env"
echo "oracle_platform_chain: chain PASS lane=oracle (Gen3 == Gen4 on $(uname -s)/$(uname -m); not product evidence)"
