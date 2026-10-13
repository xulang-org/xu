#!/usr/bin/env bash
# Xu CLI cross-platform smoke.
#
# The default is the hosted *product* lane. It resolves only bin/xu (or a
# developer/bin snapshot), runs compiler invocations through the hermetic
# product wrapper, and never builds or silently falls back to the Rust
# primer. The primer is available only through an explicit --oracle
# invocation for recovery/regression work; that lane is not product evidence.
# See docs/audit/CLI_CROSS_PLATFORM.md and bootstrap/BOUNDARY.json.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$(pwd -P)
BOOTSTRAP_ROOT=$("$REPO/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$REPO"

fail() { echo "cli_platform_test: FAIL ($1)" >&2; exit 1; }
pass=0
ok() { pass=$((pass + 1)); echo "  ok: $1"; }

usage() {
  cat <<'EOF'
Usage: scripts/cli_platform_test.sh [options]

Product lane (default):
  --compiler PATH       hosted product compiler (or XU_COMPILER/XU)
  --lane product        require hosted bin/xu/developer/bin snapshot

Oracle/recovery lane (explicit):
  --oracle              use an existing primer/compiler for non-product smoke
  --lane oracle         same as --oracle
  --compiler PATH       primer path (or XU_BOOT); no cargo build is attempted

The oracle lane is intentionally loud and must not be used as self-host or
release evidence.
EOF
}

LANE=${XU_CLI_LANE:-product}
COMPILER_INPUT=${XU_COMPILER:-${XU_SEED:-${XU:-}}}
ORACLE_INPUT=${XU_BOOT:-}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --oracle)
      LANE=oracle; shift ;;
    --lane)
      [ "$#" -ge 2 ] || fail "--lane needs product or oracle"
      LANE=$2; shift 2 ;;
    --compiler|--xu)
      [ "$#" -ge 2 ] || fail "$1 needs a path"
      COMPILER_INPUT=$2; shift 2 ;;
    --help|-h)
      usage; exit 0 ;;
    *)
      fail "unknown option: $1 (see --help)" ;;
  esac
done

case "$LANE" in
  product|oracle) ;;
  *) fail "lane must be product or oracle (got $LANE)" ;;
esac

canonical_path() {
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
  fail "cannot canonicalize compiler path (need realpath or python3)"
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

is_frozen_primer_path() {
  # Keep oracle evidence tied to the reproducible Gen0 debug/release outputs.
  local candidate=$1 resolved=${2:-$1} expected lexical
  case "$candidate" in
    /*) lexical=$candidate ;;
    *) lexical="$REPO/$candidate" ;;
  esac
  for expected in \
    "$BOOTSTRAP_ROOT/target/debug/xu" \
    "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
    "$BOOTSTRAP_ROOT/target/release/xu" \
    "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
    [ "$lexical" = "$expected" ] || continue
    [ -f "$expected" ] || continue
    [ -x "$expected" ] || continue
    has_symlink_component "$expected" "$BOOTSTRAP_ROOT" && continue
    if [ "$resolved" = "$expected" ]; then
      return 0
    fi
  done
  return 1
}

resolve_compiler() {
  local candidate resolved
  if [ "$LANE" = product ]; then
    # The resolver rejects bootstrap paths (including symlinks) unless an
    # explicit oracle override is requested. Keep the override disabled even
    # when a developer exported XU_ALLOW_ORACLE_SEED globally.
    if [ -n "$COMPILER_INPUT" ]; then
      XU_ALLOW_ORACLE_SEED=0 XU_SEED="$COMPILER_INPUT" \
        ./scripts/xu_host_seed.sh || fail "hosted product compiler rejected: $COMPILER_INPUT"
    else
      XU_ALLOW_ORACLE_SEED=0 ./scripts/xu_host_seed.sh \
        || fail "hosted product compiler not found (set --compiler or XU_SEED)"
    fi
    return
  fi

  # Oracle mode is explicit, but still does not run cargo or mutate the
  # bootstrap tree. Prefer an explicitly named path; otherwise use an
  # already-built primer artifact only.
  candidate=${COMPILER_INPUT:-$ORACLE_INPUT}
  if [ -z "$candidate" ]; then
    for primer in \
      "$BOOTSTRAP_ROOT/target/debug/xu" \
      "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
      "$BOOTSTRAP_ROOT/target/release/xu" \
      "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
      if [ -x "$primer" ]; then
        candidate=$primer
        break
      fi
    done
  fi
  [ -n "$candidate" ] || fail "oracle compiler missing (build bootstrap explicitly, then pass --oracle)"
  [ -x "$candidate" ] || fail "oracle compiler is not executable: $candidate"
  resolved=$(canonical_path "$candidate") || fail "cannot resolve oracle compiler: $candidate"
  [ -x "$resolved" ] || fail "resolved oracle compiler is not executable: $resolved"
  is_frozen_primer_path "$candidate" "$resolved" || fail \
    "oracle compiler must be the frozen bootstrap primer (bootstrap/target/{debug,release}/xu[.exe])"
  printf '%s\n' "$resolved"
}

BOOT=$(resolve_compiler)
if [ "$LANE" = oracle ]; then
  echo "cli_platform_test: lane=oracle/recovery (non-product evidence)" >&2
else
  echo "cli_platform_test: lane=product (hosted compiler)"
fi
echo "cli_platform_test: compiler=$BOOT"

run_compiler() {
  if [ "$LANE" = product ]; then
    # Do not call a product compiler directly: XUPATH/XU_CACHE/HOME and target
    # injection must be hermetic for this gate.
    "$REPO/scripts/run_product_compiler.sh" "$BOOT" "$@"
  else
    "$BOOT" "$@"
  fi
}

. ./scripts/gen1_sources.sh || fail "gen1_sources.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "cli_platform_test: building product xu (lane=$LANE)..."
compiler_help=$(run_compiler --help 2>&1 || true)
if [ "$LANE" = product ]; then
  # Product CLI shape is part of the boundary: an executable that only
  # accepts the primer's legacy `xu FILE` form is not a hosted product seed.
  printf '%s\n' "$compiler_help" | grep -E '^[[:space:]]*build[[:space:]]' >/dev/null \
    || fail "hosted compiler does not expose the product 'build' command"
  run_compiler build $GEN1_SRCS -o "$tmp/xu" \
    || fail "compile product xu"
else
  # Explicit oracle/recovery compatibility for the frozen primer. This is
  # deliberately direct and O0; no primer invocation is reachable in the
  # default product lane.
  run_compiler -O0 $GEN1_SRCS -o "$tmp/xu" \
    || fail "compile oracle product candidate"
fi
# Keep the real product name in help's invocation examples. Naming this
# compiler `.xin` made the suffix-policy assertion match argv[0] itself.
if [ -x "$tmp/xu" ]; then
  BUILT_XU="$tmp/xu"
else
  fail "product xu missing after build"
fi
ok "product xu at $BUILT_XU"

run_built() {
  if [ "$LANE" = product ]; then
    "$REPO/scripts/run_product_compiler.sh" --cwd "$PWD" "$BUILT_XU" "$@"
  else
    "$BUILT_XU" "$@"
  fi
}

FIX=$REPO/tests/fixtures/hello_string/main.xu
[ -f "$FIX" ] || fail "missing $FIX"

work=$tmp/work
mkdir -p "$work"
cp -R "$REPO/tests/fixtures/hello_string" "$work/hello_string"
# Product invocations run through run_product_compiler.sh, which deliberately
# clears ambient XUPATH. The package fixture is copied under its isolated
# source root below (the oracle lane still exercises the historical XUPATH
# search contract explicitly).
FIX_LOCAL=$work/hello_string/main.xu
cd "$work" || fail "cd work"

# --- explicit -o / --output (mac host run) ---
run_built build "$FIX_LOCAL" -o out_dash.xin || fail "build -o"
# Must be runnable without an extra chmod (write_file uses 0755).
got=$(./out_dash.xin) || fail "run out_dash (missing +x?)"
[ -n "$got" ] || fail "empty stdout -o"
ok "mac build -o name + run (no chmod)"

run_built build "$FIX_LOCAL" --output out_long.xin || fail "build --output"
got2=$(./out_long.xin) || fail "run out_long"
[ "$got" = "$got2" ] || fail "-o vs --output stdout differ"
ok "mac build --output"

# bare -o name → unsuffixed on non-Windows
run_built build "$FIX_LOCAL" -o bare_name || fail "build bare -o"
[ -f bare_name ] || fail "bare -o did not create bare_name"
[ ! -f bare_name.xin ] || fail "bare -o should not write bare_name.xin"
got3=$(./bare_name) || fail "run bare_name"
[ "$got" = "$got3" ] || fail "bare -o stdout differ"
ok "mac bare -o → unsuffixed"

# default (no -o) → main from main.xu (no extension)
rm -f main.xin main.exe main
run_built build "$FIX_LOCAL" || fail "build default"
[ -f main ] || fail "default out missing main (got: $(ls -1))"
[ ! -f main.xin ] || fail "default should not write main.xin"
got4=$(./main) || fail "run main"
[ "$got" = "$got4" ] || fail "default main stdout differ"
# mode must include owner-execute
mode=$(stat -f '%Lp' main 2>/dev/null || stat -c '%a' main)
case "$mode" in
  *7*|*5*|*1*) ;; # has at least one execute bit in common octal forms
  *) fail "main mode=$mode missing execute bit" ;;
esac
ok "mac default → main +x + run"

# --- linux cross ---
# The product wrapper clears ambient target overrides for reproducibility;
# exercise the same target selection explicitly in the product lane. The
# oracle lane retains the historical environment contract below.
if [ "$LANE" = product ]; then
  run_built build "$FIX_LOCAL" --target linux-x64 -o linux_x64.xin \
    || fail "linux target build"
else
  XUOS=linux XUARCH=x64 run_built build "$FIX_LOCAL" -o linux_x64.xin \
    || fail "XUOS/XUARCH build"
fi
file linux_x64.xin | grep -q "ELF 64-bit LSB executable, x86-64" \
  || fail "linux-x64 target did not produce linux-x64 ELF"
if [ "$LANE" = product ]; then
  ok "linux-x64 via explicit --target (.xin)"
else
  ok "linux-x64 via XUOS/XUARCH (.xin)"
fi

rm -f main main.xin
if [ "$LANE" = product ]; then
  run_built build "$FIX_LOCAL" --target linux-arm64 || fail "linux-arm64 target"
else
  XUOS=linux XUARCH=arm64 run_built build "$FIX_LOCAL" || fail "linux-arm64 default"
fi
[ -f main ] || fail "linux default missing main"
file main | grep -q "ELF 64-bit LSB executable, ARM aarch64" \
  || fail "linux-arm64 target not aarch64 ELF"
if [ "$LANE" = product ]; then
  ok "linux-arm64 explicit --target → main"
else
  ok "linux-arm64 XUOS/XUARCH default → main"
fi

if [ "$LANE" = product ]; then
  run_built build "$FIX_LOCAL" --target linux-arm64 -o ov.xin \
    || fail "--target override"
else
  XUOS=linux XUARCH=x64 run_built build "$FIX_LOCAL" --target linux-arm64 -o ov.xin \
    || fail "--target override"
fi
file ov.xin | grep -q "ELF 64-bit LSB executable, ARM aarch64" \
  || fail "--target did not override XUOS/XUARCH"
ok "--target overrides XUOS/XUARCH"

# windows cross: default / bare → .exe (compile-only)
rm -f main.exe main.xin
if [ "$LANE" = product ]; then
  run_built build "$FIX_LOCAL" --target windows-x64 || fail "windows target"
else
  XUOS=windows XUARCH=x64 run_built build "$FIX_LOCAL" || fail "windows default"
fi
[ -f main.exe ] || fail "windows default missing main.exe"
[ ! -f main.xin ] || fail "windows default should not write .xin"
file main.exe | grep -q "PE32+" || fail "windows default not PE"
ok "windows-x64 default → main.exe (compile-only)"

run_built build "$FIX_LOCAL" --target windows-arm64 -o winbare || fail "windows bare -o"
[ -f winbare.exe ] || fail "windows bare -o missing .exe"
ok "windows bare -o → .exe (compile-only)"

# --- XUPATH (Unix ':') ---
cd "$REPO" || fail "cd repo"
if [ -f tests/fixtures/pkg_import_xupath/main.xu ]; then
  fx=tests/fixtures/pkg_import_xupath
  xp_root=$(head -1 "$fx/xupath.txt" | tr -d '\r')
  if [ "$LANE" = product ]; then
    # XUPATH is intentionally cleared by the product wrapper. The dependency
    # is copied below the isolated source root, so this remains deterministic
    # without allowing an ambient import-root injection into a product gate.
    mkdir -p "$work/pkg_import_xupath/extra"
    cp "$REPO/$fx/main.xu" "$work/pkg_import_xupath/main.xu"
    cp -R "$REPO/tests/pkg_libs/extra/." "$work/pkg_import_xupath/extra/"
    run_built build "$work/pkg_import_xupath/main.xu" -o "$tmp/xupath_app.xin" \
      || fail "package-root build (product wrapper clears ambient XUPATH)"
  else
    XUPATH="$REPO/$fx/$xp_root" run_built build "$REPO/$fx/main.xu" -o "$tmp/xupath_app.xin" \
      || fail "XUPATH build"
  fi
  xgot=$("$tmp/xupath_app.xin") || fail "XUPATH run (missing +x?)"
  exp=$(tr -d '\r' < "$fx/expected.txt")
  [ "$xgot" = "$exp" ] || fail "XUPATH stdout want '$exp' got '$xgot'"
  if [ "$LANE" = product ]; then
    ok "mac package-root search + run (hermetic product lane)"
  else
    ok "mac XUPATH colon search + run"
  fi
fi

# --- help contract ---
help=$(run_built --help 2>&1) || fail "help exit"
echo "$help" | grep -qi 'gen1' && fail "help still mentions gen1"
echo "$help" | grep -q -- '--output' || fail "help missing --output"
echo "$help" | grep -q 'XUOS' || fail "help missing XUOS"
echo "$help" | grep -q '\.xin' && fail "help still mentions .xin"
echo "$help" | grep -q 'default <stem>' || fail "help missing default <stem>"
echo "$help" | grep -q '\.exe' || fail "help missing .exe"
ok "help contract (.xin/.exe)"

echo "cli_platform_test: PASS ($pass checks) [lane=$LANE; mac run + linux/windows cross]"
