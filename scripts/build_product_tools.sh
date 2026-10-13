#!/usr/bin/env bash
# Build product sibling tools with a hosted `xu` (`xu build <dir>`).
# Call after a self-host hop so xu-fmt / xu-doctor / xu-map / xu-doc / xu-desktop
# match the new compiler. xu.xun lives in each dir; do not pass it on the CLI.
#
# Usage: scripts/build_product_tools.sh <xu> [out-dir] [tool-name]
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$#" -lt 1 ]; then
    echo "usage: scripts/build_product_tools.sh <xu> [out-dir]" >&2
    exit 1
fi

XU=$1
OUT=${2:-bin}
tool_only=${3:-}
case "$tool_only" in
    ""|xu-doctor|xu-fmt|xu-map|xu-doc|xu-desktop) ;;
    *) echo "build_product_tools: unknown tool: $tool_only" >&2; exit 1 ;;
esac
PRODUCT_RUN="$PWD/scripts/run_product_compiler.sh"
[ -x "$PRODUCT_RUN" ] || {
    echo "build_product_tools: missing product compiler wrapper: $PRODUCT_RUN" >&2
    exit 1
}
mkdir -p "$OUT"
tools_staged=$(mktemp -d "$OUT/.product-tools.XXXXXX")
trap 'rm -rf "$tools_staged"' EXIT

install_one() {
    bash ./scripts/install_product_executable.sh "$1" "$2"
}

build_one() {
    src=$1
    name=$2
    if [ -n "$tool_only" ] && [ "$name" != "$tool_only" ]; then return; fi
    if [ "${OS:-}" = Windows_NT ]; then name="$name.exe"; fi
    echo "build_product_tools: $name"
    # After gen1/gen2/gen3 the compiler hop can sit near 6GiB RSS. The next
    # `xu build` is a new process; macOS may still SIGKILL it (137). Retry once.
    if ! "$PRODUCT_RUN" "$XU" build "$src" -o "$tools_staged/$name"; then
        echo "build_product_tools: retry $name" >&2
        "$PRODUCT_RUN" "$XU" build "$src" -o "$tools_staged/$name"
    fi
    install_one "$tools_staged/$name" "$OUT/$name"
}

build_one src/cmd/doctor xu-doctor
build_one src/cmd/fmt xu-fmt
build_one src/cmd/map xu-map
build_one src/cmd/doc xu-doc
build_one src/cmd/desktop xu-desktop
