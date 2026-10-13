#!/usr/bin/env bash
# Install a complete executable without modifying a live/cached image inode.
set -euo pipefail
if [ "$#" -ne 2 ]; then
    echo "usage: install_product_executable.sh <source> <destination>" >&2
    exit 1
fi
install_source=$1
install_destination=$2
if [ ! -f "$install_source" ] || [ -d "$install_destination" ]; then
    echo "install_product_executable: invalid source or destination" >&2
    exit 1
fi
mkdir -p "$(dirname "$install_destination")"
install_staged=$(mktemp "${install_destination}.install.XXXXXX")
trap 'rm -f "$install_staged"' EXIT
cp -p "$install_source" "$install_staged"
chmod +x "$install_staged"
mv -f "$install_staged" "$install_destination"
