#!/usr/bin/env bash
# Xu CLI cross-platform smoke using the hosted compiler and isolated wrapper.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$(pwd -P)
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

EOF
}

LANE=${XU_CLI_LANE:-product}
COMPILER_INPUT=${XU_COMPILER:-${XU_SEED:-${XU:-}}}
while [ "$#" -gt 0 ]; do
  case "$1" in
    --lane)
      [ "$#" -ge 2 ] || fail "--lane needs product"
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
  product) ;;
  *) fail "lane must be product (got $LANE)" ;;
esac

resolve_compiler() {
  XU_SEED="$COMPILER_INPUT" ./scripts/xu_host_seed.sh
}

BOOT=$(resolve_compiler)
echo "cli_platform_test: lane=product (hosted compiler)"
echo "cli_platform_test: compiler=$BOOT"

run_compiler() {
  "$REPO/scripts/run_product_compiler.sh" "$BOOT" "$@"
}

. ./scripts/gen1_sources.sh || fail "gen1_sources.sh"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "cli_platform_test: building product xu (lane=$LANE)..."
compiler_help=$(run_compiler --help 2>&1 || true)
printf '%s\n' "$compiler_help" | grep -E '^[[:space:]]*build[[:space:]]' >/dev/null \
  || fail "hosted compiler does not expose the product build command"
run_compiler build $GEN1_SRCS -o "$tmp/xu" || fail "compile product xu"
# Keep the real product name in help's invocation examples. Naming this
# compiler `.xin` made the suffix-policy assertion match argv[0] itself.
if [ -x "$tmp/xu" ]; then
  BUILT_XU="$tmp/xu"
else
  fail "product xu missing after build"
fi
ok "product xu at $BUILT_XU"

run_built() {
  "$REPO/scripts/run_product_compiler.sh" --cwd "$PWD" "$BUILT_XU" "$@"
}

FIX=$REPO/tests/fixtures/hello_string/main.xu
[ -f "$FIX" ] || fail "missing $FIX"

work=$tmp/work
mkdir -p "$work"
cp -R "$REPO/tests/fixtures/hello_string" "$work/hello_string"
# Product invocations run through run_product_compiler.sh, which deliberately
# clears ambient XUPATH. The package fixture is copied under its isolated
# source root below.
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
# exercise target selection explicitly in the product lane.
run_built build "$FIX_LOCAL" --target linux-x64 -o linux_x64.xin \
  || fail "linux target build"
file linux_x64.xin | grep -q "ELF 64-bit LSB executable, x86-64" \
  || fail "linux-x64 target did not produce linux-x64 ELF"
ok "linux-x64 via explicit --target (.xin)"

rm -f main main.xin
run_built build "$FIX_LOCAL" --target linux-arm64 || fail "linux-arm64 target"
[ -f main ] || fail "linux default missing main"
file main | grep -q "ELF 64-bit LSB executable, ARM aarch64" \
  || fail "linux-arm64 target not aarch64 ELF"
ok "linux-arm64 explicit --target → main"

run_built build "$FIX_LOCAL" --target linux-arm64 -o ov.xin \
  || fail "--target override"
file ov.xin | grep -q "ELF 64-bit LSB executable, ARM aarch64" \
  || fail "--target did not override XUOS/XUARCH"
ok "--target overrides XUOS/XUARCH"

# windows cross: default / bare → .exe (compile-only)
rm -f main.exe main.xin
run_built build "$FIX_LOCAL" --target windows-x64 || fail "windows target"
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
  # XUPATH is intentionally cleared by the product wrapper. The dependency
  # is copied below the isolated source root, so this remains deterministic
  # without allowing an ambient import-root injection into a product gate.
  mkdir -p "$work/pkg_import_xupath/extra"
  cp "$REPO/$fx/main.xu" "$work/pkg_import_xupath/main.xu"
  cp -R "$REPO/tests/pkg_libs/extra/." "$work/pkg_import_xupath/extra/"
  run_built build "$work/pkg_import_xupath/main.xu" -o "$tmp/xupath_app.xin" \
    || fail "package-root build (product wrapper clears ambient XUPATH)"
  xgot=$("$tmp/xupath_app.xin") || fail "XUPATH run (missing +x?)"
  exp=$(tr -d '\r' < "$fx/expected.txt")
  [ "$xgot" = "$exp" ] || fail "XUPATH stdout want '$exp' got '$xgot'"
  ok "mac package-root search + run (hermetic product lane)"
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
