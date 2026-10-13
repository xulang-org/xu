#!/usr/bin/env bash
# Run a hosted product compiler with a hermetic source/package search policy.
#
# Usage:
#   scripts/run_product_compiler.sh [--cwd ABSOLUTE_DIRECTORY] <hosted-xu> <xu-arguments...>
#
# This wrapper is for the product lane (sibling tools and cross-target
# compiler copies). It deliberately does not build anything with cargo. A
# primer path is always rejected here; oracle/recovery scripts must invoke the
# primer directly and are never product evidence.
set -euo pipefail
cd "$(dirname "$0")/.."

working_directory=$PWD
if [ "${1:-}" = --cwd ]; then
    if [ "$#" -lt 3 ]; then
        echo "run_product_compiler: --cwd needs an absolute existing directory and compiler" >&2
        exit 1
    fi
    case "$2" in
        /*) ;;
        *) echo "run_product_compiler: --cwd must be absolute" >&2; exit 1 ;;
    esac
    [ -d "$2" ] || { echo "run_product_compiler: --cwd directory does not exist: $2" >&2; exit 1; }
    working_directory=$2
    shift 2
fi

if [ "$#" -lt 2 ]; then
    echo "usage: scripts/run_product_compiler.sh [--cwd ABSOLUTE_DIRECTORY] <hosted-xu> <xu-arguments...>" >&2
    exit 1
fi

COMPILER_INPUT=$1
shift

# Reuse the canonical seed resolver so direct wrapper calls cannot hide the
# primer behind a symlink or a relative path. Product wrappers force the
# oracle opt-in off even when a developer has it set globally; recovery runs
# must call the primer explicitly, outside this product-only wrapper.
# The resolver's stdout is only the canonical executable path; diagnostics
# stay on stderr.
if ! COMPILER=$(XU_ALLOW_ORACLE_SEED=0 XU_SEED="$COMPILER_INPUT" ./scripts/xu_host_seed.sh); then
    echo "run_product_compiler: compiler rejected by hosted/oracle boundary: $COMPILER_INPUT" >&2
    exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cache="$tmp/cache"
home="$tmp/home"
mkdir -p "$cache" "$home"

# Product consumers occasionally need an explicit package root (for example
# the fixture corpus exercises XUPATH resolution).  Accept that input only
# through the named seam below, canonicalise every root, and require it to be
# a real directory inside this checkout.  Ambient XUPATH remains rejected;
# callers must opt in by setting XU_PRODUCT_XUPATH for that one invocation.
normalize_product_xupath() {
    python3 - "$PWD" "${XU_PRODUCT_XUPATH:-}" <<'PY'
import os
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
bootstrap = root / "bootstrap"
raw = sys.argv[2]
if not raw:
    sys.stdout.write("")
    raise SystemExit(0)

sep = os.pathsep
values = []
for item in raw.split(sep):
    if not item:
        continue
    candidate = Path(item).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    # Check lexical components before resolving so a symlink cannot smuggle
    # an outside source tree back into the checkout.
    lexical = candidate.absolute()
    try:
        lexical.relative_to(root)
    except ValueError:
        raise SystemExit(f"XU_PRODUCT_XUPATH escapes repository: {item}")
    cur = root
    for part in lexical.relative_to(root).parts:
        cur = cur / part
        if cur.is_symlink():
            raise SystemExit(f"XU_PRODUCT_XUPATH contains symlink: {item}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise SystemExit(f"XU_PRODUCT_XUPATH resolves outside repository: {item}")
    try:
        resolved.relative_to(bootstrap)
    except ValueError:
        pass
    else:
        # Product compiles must never import the frozen Rust workspace through
        # the opt-in search-root seam.  A path such as ``src/../bootstrap``
        # is caught after resolution even when its lexical spelling looked
        # like an ordinary in-repo directory.
        raise SystemExit(f"XU_PRODUCT_XUPATH points into frozen bootstrap: {item}")
    if not resolved.is_dir():
        raise SystemExit(f"XU_PRODUCT_XUPATH is not a directory: {item}")
    values.append(str(resolved))
sys.stdout.write(sep.join(dict.fromkeys(values)))
PY
}

if ! normalized_xupath=$(normalize_product_xupath); then
    echo "run_product_compiler: invalid XU_PRODUCT_XUPATH (must be an in-repo directory list)" >&2
    exit 1
fi

# XUPATH can shadow compiler imports with arbitrary source trees. XU_CACHE
# and HOME can do the same through `require:` package roots. XUOS/XUARCH are
# target overrides; product callers pass --target explicitly when needed.
# Keep only the ordinary process environment (PATH, TMPDIR, linker settings,
# etc.) while removing these source/target injection channels.
export LC_ALL=C
export XUPATH="$normalized_xupath"
native_path() {
    python3 -c 'from pathlib import Path; import sys; sys.stdout.write(Path(sys.argv[1]).resolve().as_posix())' "$1"
}
export XU_STDLIB_ROOT="$(native_path "$PWD/src")"
export XU_CACHE="$(native_path "$cache")"
export HOME="$(native_path "$home")"
export USERPROFILE="$HOME"
unset XUOS XUARCH XU_BOOT_EXTRA XU_HEAP_STATS XU_SEED XU_ALLOW_ORACLE_SEED XU_PRODUCT_XUPATH

# Resolve compiler and opt-in import roots against the repository first. Only
# the explicitly selected invocation directory changes; cache/home isolation
# and rejection of ambient package/target injection remain identical.
cd "$working_directory"

# Do not `exec` here: replacing the shell would skip the EXIT trap on some
# Bash versions and leave the per-invocation cache/home behind. Preserve the
# hosted compiler's status while allowing the trap to reclaim temporary state.
set +e
"$COMPILER" "$@"
status=$?
set -e
exit "$status"
