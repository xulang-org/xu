#!/usr/bin/env bash
# Print the hosted xu used to compile the next Gen1.
# Accepts only a hosted product binary:
#   ./bin/xu or developer/bin/xu.<os>.<arch>
# Or an explicit override:
#   XU_SEED=/path/to/xu
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)

if [ "$#" -ne 0 ]; then
    echo "xu_host_seed: unexpected argument: $1" >&2
    exit 2
fi

canonical_path() {
    if command -v realpath >/dev/null 2>&1; then
        realpath "$1"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$1" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
        return
    fi
    echo "xu_host_seed: cannot canonicalize seed (need realpath or python3)" >&2
    return 1
}

validate_product_seed() {
    if [ -f "$1.provenance" ] && ! grep -qx 'lane=product' "$1.provenance"; then
        echo "xu_host_seed: seed provenance must identify the hosted product: $1" >&2
        return 1
    fi
}

select_explicit() {
    local candidate=$1 resolved
    if [ ! -f "$candidate" ] && [ -f "${candidate}.exe" ]; then candidate="${candidate}.exe"; fi
    if [ ! -f "$candidate" ]; then
        echo "xu_host_seed: explicit seed does not exist: $candidate" >&2
        return 1
    fi
    if [ ! -x "$candidate" ]; then
        echo "xu_host_seed: explicit seed is not executable: $candidate" >&2
        return 1
    fi
    resolved=$(canonical_path "$candidate") || return 1
    validate_product_seed "$resolved" || return 1
    printf '%s\n' "$resolved"
}

select_auto() {
    local candidate=$1 resolved
    [ -f "$candidate" ] && [ -x "$candidate" ] || return 1
    resolved=$(canonical_path "$candidate") || return 1
    validate_product_seed "$resolved" || return 2
    printf '%s\n' "$resolved"
}

if [ -n "${XU_SEED:-}" ]; then
    select_explicit "$XU_SEED"
    exit $?
fi

set +e
select_auto "$ROOT/bin/xu"
auto_rc=$?
set -e
[ "$auto_rc" = "0" ] && exit 0
[ "$auto_rc" = "2" ] && exit 1

u=$(uname -s 2>/dev/null || echo unknown)
m=$(uname -m 2>/dev/null || echo unknown)
os=unknown
arch=unknown
case "$u" in
    Darwin) os=macos ;;
    Linux) os=linux ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT) os=windows ;;
esac
case "$m" in
    arm64|aarch64) arch=arm64 ;;
    x86_64|amd64) arch=x64 ;;
    loongarch64) arch=loongarch64 ;;
    riscv64) arch=riscv64 ;;
esac

if [ "$os" = windows ]; then
    set +e
    select_auto "$ROOT/bin/xu.exe"
    auto_rc=$?
    set -e
    [ "$auto_rc" = "0" ] && exit 0
    [ "$auto_rc" = "2" ] && exit 1
fi

snap="developer/bin/xu.${os}.${arch}"
if [ "$os" = windows ]; then
    snap="${snap}.exe"
fi
set +e
select_auto "$ROOT/$snap"
auto_rc=$?
set -e
[ "$auto_rc" = "0" ] && exit 0
[ "$auto_rc" = "2" ] && exit 1

echo "xu_host_seed: no hosted xu found." >&2
echo "  Need ./bin/xu or developer/bin/xu.<os>.<arch> (self-host seed)." >&2
echo "  Or: XU_SEED=/path/to/xu make xu" >&2
seed_destination=bin/xu
if [ "$os" = windows ]; then seed_destination=bin/xu.exe; fi
echo "  Published SDK seed: python3 scripts/restore_product_seed.py --target ${os}-${arch} --destination $seed_destination" >&2
exit 1
