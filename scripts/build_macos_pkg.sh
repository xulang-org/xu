#!/usr/bin/env bash
# Build a macOS graphical installer using the same verified SDK transaction.
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "usage: scripts/build_macos_pkg.sh <sdk-stage-dir> <output-pkg-path> [version]" >&2
    exit 1
fi

SDK_DIR=$1
OUT_PKG=$2
VERSION=${3:-$(cat "$(dirname "$0")/../VERSION")}

if ! command -v pkgbuild >/dev/null 2>&1; then
    echo "build_macos_pkg: pkgbuild command not found (macOS only)" >&2
    exit 1
fi

TMP_ROOT=$(mktemp -d "/tmp/xu-pkg-root.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT

# Package resources are extracted privately by Installer. Do not let pkgbuild
# overlay the live SDK before its complete replacement has been validated.
mkdir -p "$TMP_ROOT/scripts/sdk"
cp -R "$SDK_DIR/." "$TMP_ROOT/scripts/sdk/"
cat > "$TMP_ROOT/scripts/postinstall" <<'POSTINSTALL'
#!/bin/bash
set -euo pipefail
RESOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
VOLUME="${3:-/}"
PREFIX="${VOLUME%/}/usr/local/xu"
"$RESOURCE_DIR/sdk/xu-setup" --yes --prefix "$PREFIX" --no-modify-path
# The system SDK must be readable by non-root users.
chmod 755 "$PREFIX"
mkdir -p "${VOLUME%/}/etc/paths.d"
printf '%s\n' '/usr/local/xu/bin' > "${VOLUME%/}/etc/paths.d/xu"
chmod 644 "${VOLUME%/}/etc/paths.d/xu"
POSTINSTALL
chmod 755 "$TMP_ROOT/scripts/postinstall"

mkdir -p "$(dirname "$OUT_PKG")"
pkgbuild --nopayload --scripts "$TMP_ROOT/scripts" \
    --identifier "org.xulang.xu" --version "$VERSION" "$OUT_PKG"

echo "build_macos_pkg: successfully created $OUT_PKG"
