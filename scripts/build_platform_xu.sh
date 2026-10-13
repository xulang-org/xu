#!/usr/bin/env bash
# After self-host: write product `xu` for each hosted --target into
#   bin/platform/<os>-<arch>/xu
# Windows: xu.exe. Native target copies <xu> (the just-installed Gen3);
# the rest are cross-compiled with that compiler.
#
# Usage: scripts/build_platform_xu.sh <xu> [out-root]
#
# Env:
#   XU_SKIP_CROSS=1              no-op
#   XU_PLATFORM_TARGETS="a b …"  override the hosted target list
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${XU_SKIP_CROSS:-}" = "1" ]; then
    echo "build_platform_xu: skip (XU_SKIP_CROSS=1)"
    exit 0
fi

if [ "$#" -lt 1 ]; then
    echo "usage: scripts/build_platform_xu.sh <xu> [out-root]" >&2
    exit 1
fi

XU_INPUT=$1
OUT=${2:-bin/platform}
# Even the native-target branch below must consume a hosted product binary.
# Do not let a direct copy turn an explicitly supplied bootstrap primer into
# a platform product artifact.  Keep this resolver call in this script (rather
# than relying only on callers) because it is a public product entrypoint.
HOST_SEED_RESOLVER="$PWD/scripts/xu_host_seed.sh"
if [ ! -x "$HOST_SEED_RESOLVER" ]; then
    echo "build_platform_xu: missing hosted seed resolver: $HOST_SEED_RESOLVER" >&2
    exit 1
fi
if ! XU=$(XU_ALLOW_ORACLE_SEED=0 XU_SEED="$XU_INPUT" "$HOST_SEED_RESOLVER"); then
    echo "build_platform_xu: compiler must be a hosted product seed (bootstrap is oracle-only): $XU_INPUT" >&2
    exit 1
fi
[ -x "$XU" ] || {
    echo "build_platform_xu: resolved compiler is not executable: $XU" >&2
    exit 1
}
PRODUCT_RUN="$PWD/scripts/run_product_compiler.sh"
if [ ! -x "$PRODUCT_RUN" ]; then
    echo "build_platform_xu: missing product compiler wrapper: $PRODUCT_RUN" >&2
    exit 1
fi

. ./scripts/gen1_sources.sh || {
    echo "build_platform_xu: could not load scripts/gen1_sources.sh" >&2
    exit 1
}

host_target() {
    u=$(uname -s 2>/dev/null || echo unknown)
    m=$(uname -m 2>/dev/null || echo unknown)
    os=unknown
    arch=unknown
    case "$u" in
        Darwin) os=macos ;;
        Linux) os=linux ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT) os=windows ;;
    esac
    case "$m" in
        arm64|aarch64) arch=arm64 ;;
        x86_64|amd64) arch=x64 ;;
        loongarch64) arch=loongarch64 ;;
        riscv64) arch=riscv64 ;;
    esac
    printf '%s-%s' "$os" "$arch"
}

bin_name() {
    case "$1" in
        windows-*) echo xu.exe ;;
        *) echo xu ;;
    esac
}

check_file() {
    local t=$1 f=$2
    command -v file >/dev/null 2>&1 || return 0
    local got
    got=$(file "$f")
    case "$t" in
        macos-arm64)
            # macOS file(1): "Mach-O 64-bit executable arm64"
            # Debian file(1): "Mach-O 64-bit arm64 executable"
            echo "$got" | grep -q "Mach-O" && echo "$got" | grep -qi "arm64" ;;
        macos-x64)
            echo "$got" | grep -q "Mach-O" && echo "$got" | grep -q "x86_64" ;;
        linux-arm64)
            echo "$got" | grep -q "ELF 64-bit LSB executable, ARM aarch64" ;;
        linux-x64)
            echo "$got" | grep -q "ELF 64-bit LSB executable, x86-64" ;;
        linux-loongarch64)
            echo "$got" | grep -q "ELF 64-bit LSB executable, LoongArch" ;;
        linux-riscv64)
            echo "$got" | grep -q "ELF 64-bit LSB executable, UCB RISC-V" ;;
        windows-x64)
            echo "$got" | grep -q "PE32+ executable" && echo "$got" | grep -q "x86-64" ;;
        windows-arm64)
            echo "$got" | grep -q "PE32+ executable" && echo "$got" | grep -qi "Aarch64\|ARM64\|aarch64" ;;
        *)
            return 0 ;;
    esac
}

DEFAULT_TARGETS=(
    macos-arm64
    macos-x64
    linux-arm64
    linux-x64
    linux-loongarch64
    linux-riscv64
    windows-x64
    windows-arm64
)

if [ -n "${XU_PLATFORM_TARGETS:-}" ]; then
    # shellcheck disable=SC2206
    TARGETS=($XU_PLATFORM_TARGETS)
else
    TARGETS=("${DEFAULT_TARGETS[@]}")
fi

HOST=$(host_target)
mkdir -p "$OUT"
echo "build_platform_xu: xu=$XU host=$HOST out=$OUT"

fail=0
for t in "${TARGETS[@]}"; do
    dir="$OUT/$t"
    name=$(bin_name "$t")
    dest="$dir/$name"
    mkdir -p "$dir"
    echo "=== $dest  (--target $t) ==="
    rm -f "$dir/xu" "$dir/xu.exe"
    if [ "$t" = "$HOST" ]; then
        cp "$XU" "$dest"
        chmod +x "$dest"
        echo "build_platform_xu: copied native $XU"
    else
        stem="$dir/xu"
        # bash word-splits GEN1_SRCS; do not quote
        # shellcheck disable=SC2086
        # Keep cross-target product compilation on the same hermetic source
        # and package environment as the sibling-tool recipes.  The target is
        # explicit here; the wrapper clears ambient XUOS/XUARCH overrides.
        if ! "$PRODUCT_RUN" "$XU" build $GEN1_SRCS --target "$t" -o "$stem"; then
            echo "build_platform_xu: FAIL compile $t" >&2
            fail=1
            continue
        fi
        if [ -f "$stem.xin" ]; then
            mv -f "$stem.xin" "$dest"
        elif [ -f "$stem.exe" ]; then
            if [ "$dest" != "$stem.exe" ]; then
                mv -f "$stem.exe" "$dest"
            fi
        elif [ ! -f "$dest" ]; then
            echo "build_platform_xu: missing output for $t" >&2
            ls -la "$dir" >&2 || true
            fail=1
            continue
        fi
        chmod +x "$dest" 2>/dev/null || true
    fi
    if [ ! -f "$dest" ]; then
        echo "build_platform_xu: missing $dest" >&2
        fail=1
        continue
    fi
    ls -la "$dest"
    if command -v file >/dev/null 2>&1; then
        file "$dest"
    fi
    if ! check_file "$t" "$dest"; then
        echo "build_platform_xu: FAIL file(1) for $t" >&2
        fail=1
    fi
done

if [ "$fail" != 0 ]; then
    echo "build_platform_xu: FAIL" >&2
    exit 1
fi
echo "build_platform_xu: done → $OUT/"
ls -la "$OUT"
for t in "${TARGETS[@]}"; do
    ls -la "$OUT/$t"/xu "$OUT/$t"/xu.exe 2>/dev/null || true
done
