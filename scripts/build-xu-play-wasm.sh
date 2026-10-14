#!/bin/sh
# Compile the site's Xu runtime with the product wasm32 backend.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
SITE_ROOT=$(PYTHONPATH="$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}" python3 -c 'from companion_repos import project_root; print(project_root("site"))')
[ -d "$SITE_ROOT/playground/runtime" ] || { echo "missing site runtime: $SITE_ROOT" >&2; exit 1; }
XU_ROOT="$ROOT" "$SITE_ROOT/scripts/build-playground.sh"
