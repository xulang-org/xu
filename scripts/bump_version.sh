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
ALLOW_ARGS=()
if [ "$1" = "minor" ]; then
    if [ "${XU_ALLOW_MINOR:-0}" != "1" ]; then
        echo "Error: The second version node (minor) cannot be incremented without explicit user approval. Set XU_ALLOW_MINOR=1 if approved." >&2
        exit 1
    fi
    ALLOW_ARGS+=(--allow-minor)
fi
if [ "$1" = "major" ]; then
    if [ "${XU_ALLOW_STABLE:-0}" != "1" ]; then
        echo "Error: Xu stays in 0.x until an explicit stable release decision. Set XU_ALLOW_STABLE=1 if approved." >&2
        exit 1
    fi
    ALLOW_ARGS+=(--allow-stable)
fi
"${PYTHON:-python3}" scripts/module_versions.py --release-bump "$1" ${ALLOW_ARGS[@]+"${ALLOW_ARGS[@]}"}
# Bump only modules whose content changed, including the product version
# banner/packaging source updates above. Other module versions stay independent.
exec "${PYTHON:-python3}" scripts/module_versions.py --bump
