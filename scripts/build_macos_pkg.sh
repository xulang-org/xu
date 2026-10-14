#!/usr/bin/env bash
# Build an authentic macOS .pkg graphical installer package for Xu SDK.
# Installs to /usr/local/xu and writes /etc/paths.d/xu for global system PATH.
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "usage: scripts/build_macos_pkg.sh <sdk-stage-dir> <output-pkg-path> [version]" >&2
    exit 1
fi

SDK_DIR=$1
OUT_PKG=$2
VERSION=${3:-0.8.8-dev.2}

if ! command -v pkgbuild >/dev/null 2>&1; then
    echo "build_macos_pkg: pkgbuild command not found (macOS only)" >&2
    exit 1
fi

TMP_ROOT=$(mktemp -d "/tmp/xu-pkg-root.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT

# 1. Payload in /usr/local/xu
mkdir -p "$TMP_ROOT/usr/local/xu"
cp -Rf "$SDK_DIR/." "$TMP_ROOT/usr/local/xu/"

# 2. Global PATH configuration via /etc/paths.d/xu
mkdir -p "$TMP_ROOT/etc/paths.d"
echo "/usr/local/xu/bin" > "$TMP_ROOT/etc/paths.d/xu"
chmod 644 "$TMP_ROOT/etc/paths.d/xu"

# 3. Create .pkg using pkgbuild
mkdir -p "$(dirname "$OUT_PKG")"
pkgbuild --root "$TMP_ROOT" \
    --identifier "org.xulang.xu" \
    --version "$VERSION" \
    "$OUT_PKG"

echo "build_macos_pkg: successfully created $OUT_PKG"
