#!/usr/bin/env bash
# Normalize the macOS SDK used by repository build/test gates.
# CLT 27.0 advertises arm64e.x1 in TAPI files that the installed linker cannot
# parse. Respect explicit SDK choices; otherwise use the installed 26.5 SDK
# only when xcrun's default resolves to that incompatible CLT SDK.

if [ "$(uname -s 2>/dev/null || true)" = Darwin ] &&
   [ -z "${SDKROOT:-}" ] && [ -z "${XU_TEST_SYSROOT:-}" ] &&
   command -v xcrun >/dev/null 2>&1; then
    sdk_path=$(xcrun --show-sdk-path 2>/dev/null || true)
    resolved_sdk=$(cd "$sdk_path" 2>/dev/null && pwd -P || true)
    if [ "$(basename "$resolved_sdk")" = MacOSX27.0.sdk ]; then
        fallback=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk
        if [ -d "$fallback" ]; then
            export SDKROOT="$fallback"
        fi
    fi
fi
