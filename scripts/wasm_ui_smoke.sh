#!/bin/sh
# Build the site playground (wasm32, UI widgets) with THIS compiler and run its
# Node UI tests. Works on a temp copy of the site; relaxes only the
# final-release semver gate so -dev compilers can be tested. Never writes to the site repo.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
SITE=${SITE_ROOT:-$(PYTHONPATH="$ROOT/scripts" python3 -c 'from companion_repos import project_root; print(project_root("site"))')}
TMP=${WASM_UI_TMP:-/tmp/xu-wasm-ui-smoke}
rm -rf "$TMP"; mkdir -p "$TMP"
cp -r "$SITE/playground" "$SITE/scripts" "$SITE/tests" "$SITE/www" "$TMP/"
cp "$ROOT/VERSION" "$TMP/VERSION"
python3 - "$TMP/scripts/build-xu-playground.py" <<'P'
import sys;p=sys.argv[1];s=open(p).read()
s=s.replace("not re.fullmatch(r'(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)', version) or","")
open(p,'w').write(s)
P
(cd "$TMP" && XU_ROOT="$ROOT" python3 scripts/build-xu-playground.py)
for t in ${WASM_UI_TESTS:-test_playground_ui test_playground_canvas test_playground_widgets test_playground_gallery}; do
  (cd "$TMP" && node "tests/$t.mjs" >"$TMP/$t.log" 2>&1) || { echo "FAIL $t ($TMP/$t.log)"; exit 1; }
  echo "PASS $t: $(grep '^# pass' "$TMP/$t.log")"
done
echo "wasm_ui_smoke: PASS"
