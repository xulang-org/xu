#!/usr/bin/env sh
# Copy the primer dump of generated extra (inspection only; not a compile input).
#
# Usage: scripts/emit_xu_extra.sh <out.xu>
# Exit 0 if written, 2 if no cargo artifact.
set -euo pipefail
cd "$(dirname "$0")/.."
BOOTSTRAP_ROOT=$(./scripts/xu_host_seed.sh --bootstrap-root)

if [ "$#" -lt 1 ]; then
    echo "usage: emit_xu_extra.sh <out.xu>" >&2
    exit 1
fi
out=$1

src=
if [ -f "$BOOTSTRAP_ROOT/target/debug/rt_xu_mark.xu" ]; then
    src=$BOOTSTRAP_ROOT/target/debug/rt_xu_mark.xu
elif [ -f "$BOOTSTRAP_ROOT/target/release/rt_xu_mark.xu" ]; then
    src=$BOOTSTRAP_ROOT/target/release/rt_xu_mark.xu
fi
if [ -z "$src" ]; then
    echo "emit_xu_extra: no primer artifact (cargo build -p xu; bootstrap/target/*/rt_xu_mark.xu)" >&2
    exit 2
fi

mkdir -p "$(dirname "$out")"
cp "$src" "$out"
echo "emit_xu_extra: wrote $out (from $src)"
