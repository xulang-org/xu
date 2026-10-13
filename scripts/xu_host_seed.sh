#!/usr/bin/env bash
# Print the hosted xu used to compile the next Gen1.
#
# Product lane (the default) accepts only a hosted product binary:
#   ./bin/xu or developer/bin/xu.<os>.<arch>
#
# `XU_SEED=/path/to/xu` is an explicit seed override.  A path resolving below
# the independent bootstrap checkout is the frozen Rust primer and is
# rejected unless the caller also sets XU_ALLOW_ORACLE_SEED=1.  That escape is
# intentionally loud and is for oracle/recovery work only; it accepts only the
# canonical bootstrap/target/{debug,release}/xu artifacts and must not be used
# as product self-host evidence.
#
# The resolver returns a canonical absolute path so a symlink cannot hide a
# primer behind bin/xu or a relative XU_SEED value.
set -euo pipefail
cd "$(dirname "$0")/.."

# Use the physical repository root for the primer comparison.  Otherwise a
# caller entering through a symlink (for example /tmp/xu -> ~/github/xu) could
# make a real bootstrap executable look like an unrelated external path.
ROOT=$(pwd -P)

# Resolve the independent primer checkout without selecting a compiler.
# Keep lexical paths: oracle provenance rejects symlinked artifacts.
if [ -n "${XU_BOOTSTRAP_ROOT:-}" ]; then
    BOOTSTRAP_ROOT=$(python3 - "$XU_BOOTSTRAP_ROOT" <<'PYROOT'
import os, sys
sys.stdout.write(os.path.abspath(os.path.expanduser(sys.argv[1])).replace('\\', '/'))
PYROOT
    )
else
    BOOTSTRAP_ROOT="$(dirname "$ROOT")/bootstrap"
    if [ ! -d "$BOOTSTRAP_ROOT" ]; then
        if [ -d "$(dirname "$ROOT")/xu-bootstrap" ]; then
            BOOTSTRAP_ROOT="$(dirname "$ROOT")/xu-bootstrap"
        elif [ -d "$ROOT/bootstrap" ]; then
            BOOTSTRAP_ROOT="$ROOT/bootstrap"
        fi
    fi
fi
if command -v cygpath >/dev/null 2>&1; then BOOTSTRAP_ROOT=$(cygpath -u "$BOOTSTRAP_ROOT"); fi
if [ "${1:-}" = --bootstrap-root ]; then
    printf '%s\n' "$BOOTSTRAP_ROOT"
    exit 0
fi
ORACLE_ALLOW=${XU_ALLOW_ORACLE_SEED:-0}
# Internal oracle-consumer mode.  The normal resolver deliberately accepts an
# explicitly supplied *hosted* executable outside bootstrap; callers that are
# already in an oracle lane must opt into this stricter contract so an
# arbitrary external primer cannot be mistaken for the frozen artifact.
ORACLE_REQUIRE_FROZEN=${XU_REQUIRE_FROZEN_PRIMER:-0}

canonical_path() {
    # `realpath` is available on the supported Unix hosts.  Keep a Python
    # fallback for minimal CI images and Git-for-Windows shells; fail closed
    # if neither resolver exists because lexical path checks are not enough
    # to enforce the primer boundary through symlinks.
    if command -v realpath >/dev/null 2>&1; then
        realpath "$1"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$1" <<'PY'
import os
import sys

print(os.path.realpath(sys.argv[1]))
PY
        return
    fi
    echo "xu_host_seed: cannot canonicalize seed (need realpath or python3)" >&2
    return 1
}

has_symlink_component() {
    local candidate=$1 root=$2 rel current part
    case "$candidate" in
        "$root"/*) rel=${candidate#"$root/"} ;;
        *) return 1 ;;
    esac
    [ -L "$root" ] && return 0
    current=$root
    local components=()
    IFS='/' read -r -a components <<< "$rel"
    for part in "${components[@]}"; do
        [ -n "$part" ] || continue
        current="$current/$part"
        [ -L "$current" ] && return 0
    done
    return 1
}

has_any_symlink_component() {
    # Unlike has_symlink_component (which is intentionally scoped to ROOT),
    # this variant checks an arbitrary absolute candidate one component at a
    # time.  Oracle mode uses it to reject an external symlink alias that
    # resolves to another checkout's seemingly valid bootstrap/xu.
    local candidate=$1 current rel part
    case "$candidate" in
        /*) current=/; rel=${candidate#/} ;;
        *) current=$PWD; rel=$candidate ;;
    esac
    local components=()
    IFS='/' read -r -a components <<< "$rel"
    for part in "${components[@]}"; do
        [ -n "$part" ] || continue
        if [ "$current" = / ]; then
            current="/$part"
        else
            current="$current/$part"
        fi
        [ -L "$current" ] && return 0
    done
    return 1
}

is_primer() {
    # Inspect both the lexical candidate and its resolved target.  Checking
    # only the latter lets a symlink below bootstrap point outside the tree
    # and masquerade as a hosted compiler.
    local candidate=$1 resolved=${2:-$1} lexical
    case "$candidate" in
        /*) lexical=$candidate ;;
        *) lexical="$ROOT/$candidate" ;;
    esac
    case "$lexical" in
        "$BOOTSTRAP_ROOT"|"$BOOTSTRAP_ROOT"/*|"$ROOT/bootstrap"|"$ROOT/bootstrap"/*) return 0 ;;
        *) ;;
    esac
    case "$resolved" in
        "$BOOTSTRAP_ROOT"|"$BOOTSTRAP_ROOT"/*|"$ROOT/bootstrap"|"$ROOT/bootstrap"/*) return 0 ;;
        *) return 1 ;;
    esac
}

is_frozen_primer() {
    local candidate=$1 resolved=${2:-$1} expected lexical
    case "$candidate" in
        /*) lexical=$candidate ;;
        *) lexical="$ROOT/$candidate" ;;
    esac
    for expected in \
        "$BOOTSTRAP_ROOT/target/debug/xu" \
        "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
        "$BOOTSTRAP_ROOT/target/release/xu" \
        "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
        # The lexical spelling itself must be the declared path.  A symlink
        # alias outside bootstrap (or a ``./``/parent alias) cannot redefine
        # the provenance of the frozen artifact.
        [ "$lexical" = "$expected" ] || continue
        # A directory can carry the executable bit too; the frozen primer
        # contract is a regular executable file, never a directory or FIFO.
        [ -f "$expected" ] || continue
        [ -x "$expected" ] || continue
        # The declared artifact and every parent component must be real
        # filesystem entries; a symlink to an external primer is not frozen.
        has_symlink_component "$expected" "$BOOTSTRAP_ROOT" && continue
        [ "$resolved" = "$expected" ] || continue
        return 0
    done
    return 1
}

reject_implicit_primer() {
    local candidate=$1 resolved=$2
    echo "xu_host_seed: refusing bootstrap primer as product seed:" >&2
    echo "  candidate: $candidate" >&2
    echo "  resolves:  $resolved" >&2
    echo "  Product lane requires bin/xu or developer/bin snapshot." >&2
    echo "  Oracle/recovery only: XU_ALLOW_ORACLE_SEED=1 XU_SEED=$candidate" >&2
    return 1
}

reject_unfrozen_primer() {
    local candidate=$1 resolved=$2
    echo "xu_host_seed: refusing non-canonical bootstrap executable:" >&2
    echo "  candidate: $candidate" >&2
    echo "  resolves:  $resolved" >&2
    echo "  Oracle lane accepts only bootstrap/target/{debug,release}/xu[.exe]." >&2
    return 1
}

select_explicit() {
    local candidate=$1 resolved
    if [ ! -x "$candidate" ]; then
        echo "xu_host_seed: XU_SEED=$candidate is not executable" >&2
        return 1
    fi
    if { [ "$ORACLE_ALLOW" = "1" ] || [ "$ORACLE_REQUIRE_FROZEN" = "1" ]; } \
        && has_any_symlink_component "$candidate"; then
        resolved=$(canonical_path "$candidate") || return 1
        reject_unfrozen_primer "$candidate" "$resolved"
        return 1
    fi
    resolved=$(canonical_path "$candidate") || return 1
    if [ "$ORACLE_REQUIRE_FROZEN" = "1" ]; then
        if ! is_frozen_primer "$candidate" "$resolved"; then
            reject_unfrozen_primer "$candidate" "$resolved"
            return 1
        fi
        echo "xu_host_seed: WARNING frozen oracle primer explicitly enabled; this is not product evidence" >&2
        echo "xu_host_seed: oracle seed=$resolved" >&2
        printf '%s\n' "$resolved"
        return 0
    fi
    if is_primer "$candidate" "$resolved"; then
        if [ "$ORACLE_ALLOW" != "1" ]; then
            reject_implicit_primer "$candidate" "$resolved"
            return 1
        fi
        if ! is_frozen_primer "$candidate" "$resolved"; then
            reject_unfrozen_primer "$candidate" "$resolved"
            return 1
        fi
        echo "xu_host_seed: WARNING oracle primer explicitly enabled; this is not product evidence" >&2
        echo "xu_host_seed: oracle seed=$resolved" >&2
    fi
    printf '%s\n' "$resolved"
}

select_auto() {
    local candidate=$1 resolved
    [ -x "$candidate" ] || return 1
    resolved=$(canonical_path "$candidate") || return 1
    # An auto-discovered path must never silently become an oracle lane.  The
    # allow switch only applies when the caller names XU_SEED explicitly.
    if is_primer "$candidate" "$resolved"; then
        reject_implicit_primer "$candidate" "$resolved"
        # Distinguish a present-but-forbidden candidate from a missing one so
        # the caller cannot silently fall through to another lane.
        return 2
    fi
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
echo "  Primer paths require XU_ALLOW_ORACLE_SEED=1 and an explicit canonical XU_SEED." >&2
exit 1
