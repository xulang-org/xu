#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 [major|minor|patch]" >&2
    exit 1
fi
case "$1" in
    major|minor|patch) ;;
    *) echo "Error: BUMP must be major, minor, or patch" >&2; exit 1 ;;
esac

# Validate all manifests before changing VERSION or any product source.
"${PYTHON:-python3}" scripts/module_versions.py --release-bump "$1"
# Bump only modules whose content changed, including the product version
# banner/packaging source updates above. Other module versions stay independent.
exec "${PYTHON:-python3}" scripts/module_versions.py --bump
