#!/usr/bin/env bash
# Cross-target runtime loud probes for S3 (OOB) + S7 (division fail-loud).
#
# Compiles p17–p19 (index/slice OOB) and p20–p22 (division guards) with Gen1
# for macos-arm64, macos-x64, linux-arm64, linux-x64, windows-x64 (wine),
# linux-loongarch64, and linux-riscv64 (QEMU shims). Each probe must exit 1
# with the expected stderr substring on every lane that runs.
# docker/qemu 125/126/127 (runner cannot exec) degrades to compile+file;
# that is not treated as the probe's exit code (which must be 1).
#
# Usage:
#   scripts/safety_cross_target.sh
#   scripts/safety_cross_target.sh --gen1=/path/to/gen1
set -euo pipefail
# Machine-readable boundary role: cross-target safety oracle evidence.
BOUNDARY_LANE=oracle
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"

GEN1=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --gen1=*) GEN1="${1#*=}" ;;
        *) echo "safety_cross_target: unknown arg $1"; exit 1 ;;
    esac
    shift
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { echo "safety_cross_target: FAIL ($1)"; exit 1; }

if [ -z "$GEN1" ]; then
    cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu --bin xu \
        || fail "bootstrap xu build failed"
    XU="$BOOTSTRAP_ROOT/target/debug/xu"
    XU=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$XU" \
        "$ROOT/scripts/xu_host_seed.sh") || fail "bootstrap compiler is not the canonical frozen primer"
    . ./scripts/gen1_sources.sh || fail "could not load scripts/gen1_sources.sh"
    # Primer -O0: bootstrap auto/O1 still miscompiles the full compiler.
    "$XU" -O0 $GEN1_SRCS -o "$tmp/gen1.xin" || fail "bootstrap could not compile Gen1"
    GEN1="$tmp/gen1.xin"
    echo "safety_cross_target: lane=oracle (frozen bootstrap); generated Gen1 is parity-only, not product evidence" >&2
else
    # An explicitly supplied Gen1 is allowed for parity, but it is not an
    # oracle or product fixed-point artifact.  Keep this distinction visible
    # when the script is used outside the default bootstrap path.
    echo "safety_cross_target: lane=parity (explicit --gen1; not product evidence)" >&2
fi
chmod +x "$GEN1"

ARM64_IMG="${XU_LINUX_ARM64_IMAGE:-postgres:15}"
X64_IMG="${XU_LINUX_X64_IMAGE:-jsbin-wine}"
WINE_IMG="${XU_WINE_IMAGE:-jsbin-wine}"
WINEPREFIX_DIR="$ROOT/target/wineprefix"
mkdir -p "$WINEPREFIX_DIR"

LOONG_OK=0; command -v qemu-system-loongarch64 >/dev/null 2>&1 && LOONG_OK=1
RISCV_OK=0; command -v qemu-system-riscv64 >/dev/null 2>&1 && RISCV_OK=1

docker_ok() { docker image inspect "$1" >/dev/null 2>&1; }
. ./scripts/docker_run_target.sh

TARGETS="macos-arm64 macos-x64 linux-arm64 linux-x64 windows-x64 linux-loongarch64 linux-riscv64"
DEGRADED=""
docker_ok "$ARM64_IMG" || DEGRADED="$DEGRADED linux-arm64(no-image)"
docker_ok "$X64_IMG" || DEGRADED="$DEGRADED linux-x64(no-image)"
HOST_WINE=""
if command -v wine >/dev/null 2>&1; then
    HOST_WINE=$(command -v wine)
    if ! "$HOST_WINE" --version >/dev/null 2>&1; then HOST_WINE=""; fi
fi
if ! docker_ok "$WINE_IMG" && [ -z "$HOST_WINE" ]; then
    DEGRADED="$DEGRADED windows-x64(no-wine)"
fi
[ "$LOONG_OK" = "1" ] || DEGRADED="$DEGRADED linux-loongarch64(no-qemu)"
[ "$RISCV_OK" = "1" ] || DEGRADED="$DEGRADED linux-riscv64(no-qemu)"
MACOS_X64_OK=0
if [ "$(uname -s)" = Darwin ]; then
    if [ "$(uname -m)" = x86_64 ]; then
        MACOS_X64_OK=1
    elif [ "$(uname -m)" = arm64 ]; then
        if /usr/bin/arch -x86_64 /usr/bin/true >/dev/null 2>&1; then MACOS_X64_OK=1; fi
    fi
fi
[ "$MACOS_X64_OK" = 1 ] || DEGRADED="$DEGRADED macos-x64(no-runner)"

pass=0
fail_n=0
ran=0

# Run a built probe; sets globals: run_ok, code, work/out/err already set by caller.
run_built_probe() {
    local target=$1 work=$2 out=$3
    run_ok=0
    code=-1
    case "$target" in
        macos-arm64|macos-x64)
            if [ "$target" = macos-x64 ] && [ "$MACOS_X64_OK" = 0 ]; then
                if file "$out" | grep -q "Mach-O 64-bit executable x86_64"; then
                    echo "PASS ${probe}/${target} (compile+file only: no native runner)"
                    pass=$((pass + 1))
                else
                    echo "FAIL ${probe}/${target} (degraded check failed)"
                    fail_n=$((fail_n + 1))
                fi
            else
                if "$out" >"$work/out" 2>"$work/err"; then code=0; else code=$?; fi
                run_ok=1
            fi
            ;;
        linux-arm64)
            xu_linux_run linux-arm64 "$ARM64_IMG" "$work" "$out" /w/a.out "$work/out" "$work/err"
            if [ "$XU_LINUX_RUN_STATUS" = "degraded" ]; then
                if xu_linux_elf_ok linux-arm64 "$out"; then
                    echo "PASS ${probe}/${target} (compile+file only)"
                    pass=$((pass + 1))
                else
                    echo "FAIL ${probe}/${target} (degraded check failed)"
                    fail_n=$((fail_n + 1))
                fi
            else
                code=$XU_LINUX_RUN_CODE
                run_ok=1
            fi
            ;;
        linux-x64)
            xu_linux_run linux-x64 "$X64_IMG" "$work" "$out" /w/a.out "$work/out" "$work/err"
            if [ "$XU_LINUX_RUN_STATUS" = "degraded" ]; then
                if xu_linux_elf_ok linux-x64 "$out"; then
                    echo "PASS ${probe}/${target} (compile+file only)"
                    pass=$((pass + 1))
                else
                    echo "FAIL ${probe}/${target} (degraded check failed)"
                    fail_n=$((fail_n + 1))
                fi
            else
                code=$XU_LINUX_RUN_CODE
                run_ok=1
            fi
            ;;
        windows-x64)
            if docker_ok "$WINE_IMG"; then
                if docker run --rm --platform linux/amd64 -e WINEPREFIX=/wineprefix \
                    -v "$WINEPREFIX_DIR":/wineprefix -v "$work":/w \
                    -w /w --entrypoint wine "$WINE_IMG" /w/a.exe >"$work/out" 2>"$work/err"; then code=0; else code=$?; fi
                run_ok=1
            elif [ -n "$HOST_WINE" ]; then
                if WINEPREFIX="$WINEPREFIX_DIR" "$HOST_WINE" "$out" >"$work/out" 2>"$work/err"; then code=0; else code=$?; fi
                run_ok=1
            else
                if file "$out" | grep -q "PE32+ executable"; then
                    echo "PASS ${probe}/${target} (compile+file only: no wine runner)"
                    pass=$((pass + 1))
                else
                    echo "FAIL ${probe}/${target} (degraded check failed)"
                    fail_n=$((fail_n + 1))
                fi
            fi
            ;;
        linux-loongarch64)
            if [ "$LOONG_OK" = "1" ]; then
                if python3 scripts/loong64_qemu_run.py "$out" >"$work/out" 2>"$work/err"; then code=0; else code=$?; fi
                if grep -q '__EXIT_CODE__=' "$work/err" 2>/dev/null; then
                    code=$(sed -n 's/.*__EXIT_CODE__=//p' "$work/err" | head -1)
                fi
                run_ok=1
            else
                echo "SKIP ${probe}/${target} (compile-only; no qemu-system-loongarch64)"
                pass=$((pass + 1))
            fi
            ;;
        linux-riscv64)
            if [ "$RISCV_OK" = "1" ]; then
                if python3 scripts/riscv64_qemu_run.py "$out" >"$work/out" 2>"$work/err"; then code=0; else code=$?; fi
                if grep -q '__EXIT_CODE__=' "$work/err" 2>/dev/null; then
                    code=$(sed -n 's/.*__EXIT_CODE__=//p' "$work/err" | head -1)
                fi
                run_ok=1
            else
                echo "SKIP ${probe}/${target} (compile-only; no qemu-system-riscv64)"
                pass=$((pass + 1))
            fi
            ;;
        *)
            echo "FAIL ${probe}/${target} (unknown target)"
            fail_n=$((fail_n + 1))
            ;;
    esac
}

for entry in \
    "p17_negative_index:index out of bounds" \
    "p18_slice_negative:slice out of bounds" \
    "p19_slice_reverse:slice out of bounds" \
    "p20_div_overflow_intmin:division overflow" \
    "p21_div_zero_loud:division by zero" \
    "p22_div_overflow_intmin_mod:division overflow"
do
    probe=${entry%%:*}
    want=${entry#*:}
    prog="tests/gen1/programs/${probe}.xu"
    [ -f "$prog" ] || fail "missing probe $prog"
    for target in $TARGETS; do
        work=$(mktemp -d)
        out="$work/a.out"
        [ "$target" = "windows-x64" ] && out="$work/a.exe"
        if ! "$GEN1" build "$prog" --target "$target" -o "$out" 2>"$work/compile.err"; then
            echo "FAIL $probe/$target (compile)"
            sed 's/^/  /' "$work/compile.err"
            fail_n=$((fail_n + 1))
            rm -rf "$work"
            continue
        fi
        chmod +x "$out" 2>/dev/null || true
        run_built_probe "$target" "$work" "$out"
        if [ "${run_ok:-0}" = "1" ]; then
            ran=$((ran + 1))
            if [ "$code" != "1" ]; then
                echo "FAIL $probe/$target (exit $code, want 1)"
                fail_n=$((fail_n + 1))
            elif ! grep -qF "$want" "$work/err" && ! grep -qF "$want" "$work/out"; then
                echo "FAIL $probe/$target (output missing '$want')"
                echo "  stderr tail: $(tail -3 "$work/err" | tr '\n' ' ')"
                echo "  stdout tail: $(tail -3 "$work/out" | tr '\n' ' ')"
                fail_n=$((fail_n + 1))
            else
                echo "PASS $probe/$target"
                pass=$((pass + 1))
            fi
        fi
        rm -rf "$work"
    done
done

echo
[ -n "${XU_LINUX_RUN_DEGRADED_TARGETS:-}" ] && DEGRADED="$DEGRADED$XU_LINUX_RUN_DEGRADED_TARGETS"
[ -n "$DEGRADED" ] && echo "degraded lanes:$DEGRADED"
echo "safety_cross_target: PASS=$pass FAIL=$fail_n (ran=$ran runtime checks)"
[ "$fail_n" -eq 0 ] || fail "$fail_n runtime lane(s) failed"
