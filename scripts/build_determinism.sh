#!/usr/bin/env bash
# Build-determinism probe: the same compiler, the same sources, a different
# process environment size — the output bytes must not change.
#
# 2026-09-10 finding (OVERALL_OPTIMIZATION_PLAN_2026-09.md §6): compiling the
# compiler unit with `bin/xu` produced 33 differing bytes (one 4-byte word in
# __DATA, 32 bytes in __LINKEDIT) depending only on how many bytes the
# environment block occupied (HOME+LC_ALL, or a 2000-byte dummy variable).
# Small programs were unaffected.  Gen3 == Gen4 still held because every hop
# of build_hosted_chain.sh runs under one fixed environment, so the fixed
# point cannot see this class of defect.  This script makes it visible.
#
# Usage:
#   scripts/build_determinism.sh --xu=bin/xu                    # compiler unit (slow: 2 hops)
#   scripts/build_determinism.sh --xu=bin/xu --unit=tests/fixtures/matmul_tiny/main.xu
#   scripts/build_determinism.sh --xu=bin/xu --pads=0,1500,3000 # more environment sizes
#
# Lane: dual (hosted compiler; primer only with --allow-oracle-seed).  Not a
# fixed-point proof; a PASS says the build did not depend on environment size
# for the tried sizes.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
cd "$ROOT"
LANE=dual
source scripts/test_lib.sh
. ./scripts/gen1_sources.sh

XU_INPUT=""
UNIT="compiler"
PADS="0,2000"
ALLOW_ORACLE=0
HOP_TIMEOUT=${XU_DETERMINISM_HOP_TIMEOUT:-1800}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) XU_INPUT="${1#*=}" ;;
        --unit=*) UNIT="${1#*=}" ;;
        --pads=*) PADS="${1#*=}" ;;
        --allow-oracle-seed) ALLOW_ORACLE=1 ;;
        -h|--help)
            sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "build_determinism: unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done
if [ -z "$XU_INPUT" ]; then
    echo "build_determinism: --xu=<hosted compiler> is required" >&2
    exit 1
fi
if ! XU=$(XU_ALLOW_ORACLE_SEED="$ALLOW_ORACLE" XU_SEED="$XU_INPUT" ./scripts/xu_host_seed.sh); then
    echo "build_determinism: compiler rejected by hosted/oracle boundary: $XU_INPUT" >&2
    exit 1
fi

if [ "$UNIT" = "compiler" ]; then
    # shellcheck disable=SC2086
    set -- $GEN1_SRCS
    UNIT_DESC="compiler unit ($# files)"
else
    [ -f "$UNIT" ] || { echo "build_determinism: no such unit $UNIT" >&2; exit 1; }
    set -- "$UNIT"
    UNIT_DESC="$UNIT"
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/xu-determinism.XXXXXX")
STATUS=FAIL
cleanup() {
    local rc=$?
    if [ "$rc" -eq 0 ]; then rm -rf -- "$WORK"; else echo "build_determinism: artifacts kept in $WORK" >&2; fi
    echo "build_determinism: $STATUS lane=$LANE unit=$UNIT_DESC pads=$PADS"
    return "$rc"
}
trap cleanup EXIT

export LC_ALL=C
export XUPATH=""
export XU_CACHE="$WORK/cache"
export HOME="$WORK/home"
export USERPROFILE="$HOME"
mkdir -p "$XU_CACHE" "$HOME"
unset XUOS XUARCH XU_BOOT_EXTRA XU_HEAP_STATS XU_SEED XU_ALLOW_ORACLE_SEED

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'; else sha256sum "$1" | awk '{print $1}'; fi
}

echo "build_determinism: lane=$LANE xu=$XU"
echo "build_determinism: unit=$UNIT_DESC"
IFS=',' read -r -a PAD_LIST <<< "$PADS"
first=""
first_pad=""
rc_all=0
for pad in "${PAD_LIST[@]}"; do
    [ -n "$pad" ] || continue
    out="$WORK/out_pad$pad"
    padding=""
    if [ "$pad" -gt 0 ]; then
        padding=$(head -c "$pad" /dev/zero | tr '\0' x)
    fi
    set +e
    XU_DETERMINISM_PAD="$padding" run_with_timeout "$HOP_TIMEOUT" "$XU" build "$@" -o "$out" >"$out.log" 2>&1
    rc=$?
    set -e
    if [ "$rc" -ne 0 ]; then
        echo "build_determinism: build failed (pad=$pad rc=$rc):" >&2
        tail -20 "$out.log" >&2
        exit 1
    fi
    if [ ! -f "$out" ]; then
        # The compiler appends .exe for Windows targets.
        [ -f "${out%.xin}.exe" ] && out="${out%.xin}.exe"
    fi
    sha=$(sha256_file "$out")
    echo "build_determinism: pad=$pad bytes sha256=$sha"
    if [ -z "$first" ]; then
        first="$out"
        first_pad="$pad"
        continue
    fi
    if ! cmp -s "$first" "$out"; then
        ndiff=$(cmp -l "$first" "$out" | wc -l | tr -d ' ')
        echo "build_determinism: DIFF pad=$first_pad vs pad=$pad: $ndiff byte(s) differ; first at offset $(cmp "$first" "$out" | awk '{print $5}' | tr -d ',')"
        cmp -l "$first" "$out" | head -8 | sed 's/^/  | /'
        rc_all=1
    fi
done
if [ "$rc_all" -eq 0 ]; then
    STATUS=PASS
    exit 0
fi
exit 1
