#!/bin/sh
# Rebuild the in-browser Xu playground wasm (parser + check + MIR interpreter).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
SITE_ROOT=$(PYTHONPATH="$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}" python3 -c 'from companion_repos import project_root; print(project_root("site"))')
[ -d "$SITE_ROOT/www" ] || { echo "missing xu-site checkout: $SITE_ROOT" >&2; exit 1; }
cd "$ROOT"
cargo build --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xuplay --target wasm32-unknown-unknown --release
cp -f "$BOOTSTRAP_ROOT/target/wasm32-unknown-unknown/release/xuplay.wasm" \
    "$SITE_ROOT/www/xu-play.wasm"
ls -l "$SITE_ROOT/www/xu-play.wasm"
