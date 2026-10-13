#!/usr/bin/env bash
# Cross-compile hosted product xu into developer/bin/xu.<os>.<arch>
# (Windows: xu.windows.<arch>.exe).
# Local make xu writes the same compilers under bin/platform/<os>-<arch>/;
# this script is the flat snapshot for developer/bin.
set -euo pipefail
cd "$(dirname "$0")/.."

XU="${XU:-./bin/xu}"
if [[ ! -x "$XU" ]]; then
  echo "pack_developer_xu: missing $XU — run 'make xu' first" >&2
  exit 1
fi
PRODUCT_RUN="$PWD/scripts/run_product_compiler.sh"
if [[ ! -x "$PRODUCT_RUN" ]]; then
  echo "pack_developer_xu: missing product compiler wrapper: $PRODUCT_RUN" >&2
  exit 1
fi

. ./scripts/gen1_sources.sh
mkdir -p developer/bin

TARGETS=(
  macos-arm64
  macos-x64
  linux-arm64
  linux-x64
  linux-loongarch64
  linux-riscv64
  windows-x64
  windows-arm64
)

for t in "${TARGETS[@]}"; do
  os="${t%%-*}"
  arch="${t#*-}"
  out="developer/bin/xu.${os}.${arch}"
  if [[ "$os" == "windows" ]]; then
    rm -f "$out" # drop the old suffix-less name
    out="${out}.exe"
  fi
  echo "=== $out  (--target $t) ==="
  # bash word-splits GEN1_SRCS; do not quote
  # shellcheck disable=SC2086
  # RA tier auto (arch + MIR); no -O*.
  # Keep snapshot generation on the same hermetic product seam as all other
  # cross-target consumers; a bootstrap path is rejected by the wrapper.
  "$PRODUCT_RUN" "$XU" build $GEN1_SRCS --target "$t" -o "$out"
  # Unix outputs are created 0755 by write_file; keep chmod for odd hosts.
  chmod +x "$out" 2>/dev/null || true
  ls -la "$out"
done

echo "pack_developer_xu: done → developer/bin/"
ls -la developer/bin/xu.*
