#!/usr/bin/env bash
# Gen1 multi-target matrix (M12): compile a small fixture set with hosted
# gen1 for every target in the matrix. Real run where the environment allows; otherwise
# compile + `file` verification (same degradation policy as platform_test.sh).
# docker/qemu exit 125/126/127 is a runner miss, not a program FAIL.
set -euo pipefail
# Machine-readable boundary role: cross-target primer/oracle evidence only.
BOUNDARY_LANE=oracle
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"

cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu || {
    echo "xu build failed"; exit 1
}
XU="$BOOTSTRAP_ROOT/target/debug/xu"
XU=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$XU" \
    "$ROOT/scripts/xu_host_seed.sh") || {
    echo "gen1_platform_test: bootstrap compiler is not the canonical frozen primer" >&2
    exit 1
}

# `src/xu/*` packages are loaded via import.
. ./scripts/gen1_sources.sh || { echo "gen1_platform_test: could not load scripts/gen1_sources.sh"; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "gen1_platform_test: building gen1..."
# Primer -O0: bootstrap auto/O1 still miscompiles the full compiler.
"$XU" -O0 $GEN1_SRCS -o "$tmp/gen1.xin" || { echo "FAIL: bootstrap could not compile gen1"; exit 1; }
chmod +x "$tmp/gen1.xin"
GEN1="$tmp/gen1.xin"

FIXTURES="hello_string arith_precedence f64_loop_regcache string_concat exit_builtin fib_recursive atomic_basic channel_blocking_string time_wall crypto_ecdsa crypto_x509_ecdsa crypto_x509_chain crypto_x509_pool crypto_x509_system_pool crypto_tls_pipe crypto_tls_ecdhe_interop net_udp_echo net_udp_connected net_ipv6_loopback net_unix_loopback net_interfaces net_unsupported_contract"
TARGETS="macos-arm64 macos-x64 linux-arm64 linux-x64 windows-x64 windows-arm64 linux-loongarch64 linux-riscv64"

# The semihosting shims do not expose hosted sockets. Keep the network
# regression as a compile/format check on those two lanes.
DOMESTIC_NO_RUN="channel_blocking_string time_wall crypto_ecdsa crypto_x509_ecdsa crypto_x509_chain crypto_x509_pool crypto_x509_system_pool crypto_tls_pipe crypto_tls_ecdhe_interop net_udp_echo net_udp_connected net_ipv6_loopback net_unix_loopback net_interfaces"

ARM64_IMG="${XU_LINUX_ARM64_IMAGE:-postgres:15}"
X64_IMG="${XU_LINUX_X64_IMAGE:-jsbin-wine}"
WINE_IMG="${XU_WINE_IMAGE:-jsbin-wine}"
WINEPREFIX_DIR="$ROOT/target/wineprefix"
mkdir -p "$WINEPREFIX_DIR"
HOST_WINE=""
if command -v wine >/dev/null 2>&1; then
    HOST_WINE=$(command -v wine)
    if ! "$HOST_WINE" --version >/dev/null 2>&1; then HOST_WINE=""; fi
fi

LOONG_OK=0; command -v qemu-system-loongarch64 >/dev/null 2>&1 && LOONG_OK=1
RISCV_OK=0; command -v qemu-system-riscv64 >/dev/null 2>&1 && RISCV_OK=1

docker_ok() { docker image inspect "$1" >/dev/null 2>&1; }
. ./scripts/docker_run_target.sh
DEGRADED=""
docker_ok "$ARM64_IMG" || DEGRADED="$DEGRADED linux-arm64(no-image)"
docker_ok "$X64_IMG" || DEGRADED="$DEGRADED linux-x64(no-image)"
WINE_DOCKER_OK=0
if docker_ok "$WINE_IMG" && docker run --pull=never --rm --platform linux/amd64 \
    --entrypoint wine "$WINE_IMG" --version >/dev/null 2>&1; then
    WINE_DOCKER_OK=1
fi
if [ "$WINE_DOCKER_OK" = 0 ] && [ -z "$HOST_WINE" ]; then
    DEGRADED="$DEGRADED windows-x64(no-runner)"
fi
[ "$LOONG_OK" = "1" ] || DEGRADED="$DEGRADED linux-loongarch64(no-qemu)"
[ "$RISCV_OK" = "1" ] || DEGRADED="$DEGRADED linux-riscv64(no-qemu)"
MACOS_X64_OK=0
if [ "$(uname -s)" = Darwin ]; then
    if [ "$(uname -m)" = x86_64 ] || /usr/bin/arch -x86_64 /usr/bin/true >/dev/null 2>&1; then
        MACOS_X64_OK=1
    fi
fi
[ "$MACOS_X64_OK" = 1 ] || DEGRADED="$DEGRADED macos-x64(no-runner)"

linux_ipv6_ok() {
    local image=$1 platform=$2
    docker_ok "$image" || return 1
    docker run --rm --platform "$platform" --entrypoint sh "$image" -c \
        '[ -r /proc/sys/net/ipv6/conf/all/disable_ipv6 ] && [ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6)" = 0 ] && [ -r /proc/net/if_inet6 ] && grep -q . /proc/net/if_inet6' >/dev/null 2>&1
}
LINUX_ARM64_IPV6_OK=0
LINUX_X64_IPV6_OK=0
if linux_ipv6_ok "$ARM64_IMG" linux/arm64; then LINUX_ARM64_IPV6_OK=1; else
    docker_ok "$ARM64_IMG" && DEGRADED="$DEGRADED linux-arm64(no-ipv6)"
fi
if linux_ipv6_ok "$X64_IMG" linux/amd64; then LINUX_X64_IPV6_OK=1; else
    docker_ok "$X64_IMG" && DEGRADED="$DEGRADED linux-x64(no-ipv6)"
fi

# system_cert_pool returns an empty pool when the image has no CA source.
# Probe that environment independently, rather than weakening its golden.
linux_system_trust_ok() {
    local image=$1 platform=$2
    docker_ok "$image" || return 1
    docker run --pull=never --rm --platform "$platform" --entrypoint sh "$image" -c \
        '[ -s /etc/ssl/cert.pem ] || [ -s /etc/ssl/certs/ca-certificates.crt ] || [ -s /etc/pki/tls/certs/ca-bundle.crt ]' >/dev/null 2>&1
}
LINUX_ARM64_TRUST_OK=0
LINUX_X64_TRUST_OK=0
if linux_system_trust_ok "$ARM64_IMG" linux/arm64; then LINUX_ARM64_TRUST_OK=1; else
    docker_ok "$ARM64_IMG" && DEGRADED="$DEGRADED linux-arm64(no-system-trust-store)"
fi
if linux_system_trust_ok "$X64_IMG" linux/amd64; then LINUX_X64_TRUST_OK=1; else
    docker_ok "$X64_IMG" && DEGRADED="$DEGRADED linux-x64(no-system-trust-store)"
fi

pass=0
fail=0

file_check() {
    local target=$1 out=$2
    case "$target" in
        macos-arm64)
            file "$out" | grep -q "Mach-O 64-bit executable arm64" ;;
        macos-x64)
            file "$out" | grep -q "Mach-O 64-bit executable x86_64" ;;
        linux-arm64)
            file "$out" | grep -q "ELF 64-bit LSB executable, ARM aarch64" ;;
        linux-x64)
            file "$out" | grep -q "ELF 64-bit LSB executable, x86-64" ;;
        linux-loongarch64)
            file "$out" | grep -q "ELF 64-bit LSB executable, LoongArch" ;;
        linux-riscv64)
            file "$out" | grep -q "ELF 64-bit LSB executable, UCB RISC-V" ;;
        windows-x64)
            file "$out" | grep -q "PE32+ executable" ;;
        windows-arm64)
            file "$out" | grep -qiE 'PE32\+.*(Aarch64|ARM64|aarch64)' ;;
        *) return 1 ;;
    esac
}

for name in $FIXTURES; do
    dir="tests/fixtures/$name"
    [ -f "$dir/main.xu" ] || continue
    [ -f "$dir/error.txt" ] && continue
    expected_exit=0
    [ -f "$dir/expected.exit" ] && expected_exit=$(tr -d '[:space:]' <"$dir/expected.exit")
    for target in $TARGETS; do
        work=$(mktemp -d)
        out="$work/a.out"
        case "$target" in
            windows-x64|windows-arm64) out="$work/a.exe" ;;
        esac
        XU_LINUX_RUN_SSL_CERT_BASENAME=""
        if [ "$name" = "crypto_x509_pool" ]; then
            cp "$dir/test-root.pem" "$work/test-root.pem"
            XU_LINUX_RUN_SSL_CERT_BASENAME="test-root.pem"
        fi
        if ! "$GEN1" build "$dir/main.xu" --target "$target" -o "$out" 2>"$work/err"; then
            echo "FAIL $name/$target (compile)"
            sed 's/^/  /' "$work/err"
            fail=$((fail + 1))
            rm -rf "$work"
            continue
        fi
        chmod +x "$out" 2>/dev/null || true
        if ! file_check "$target" "$out"; then
            echo "FAIL $name/$target (file format: $(file "$out"))"
            fail=$((fail + 1))
            rm -rf "$work"
            continue
        fi
        extra_args=""
        [ -f "$dir/args.txt" ] && extra_args=$(cat "$dir/args.txt")
        run_ok=0
        case "$target" in
            macos-arm64|macos-x64)
                if [ "$target" = macos-x64 ] && [ "$MACOS_X64_OK" != 1 ]; then
                    echo "PASS $name/$target (compile+file only)"
                    pass=$((pass + 1))
                else
                if [ "$name" = "crypto_x509_pool" ]; then
                    run_env="SSL_CERT_FILE=$work/test-root.pem"
                else
                    run_env=""
                fi
                if (cd "$work" && env $run_env "./$(basename "$out")" $extra_args) >"$work/stdout" 2>/dev/null; then
                    code=0
                else
                    code=$?
                fi
                run_ok=1
                fi
                ;;
            linux-arm64)
                if [ "$name" = "crypto_x509_system_pool" ] && [ "$LINUX_ARM64_TRUST_OK" = 0 ] && docker_ok "$ARM64_IMG"; then
                    echo "PASS $name/$target (compile+file only: no system trust store)"
                    pass=$((pass + 1))
                    continue
                fi
                if [ "$name" = "net_ipv6_loopback" ] && [ "$LINUX_ARM64_IPV6_OK" = "0" ]; then
                    echo "PASS $name/$target (compile+file only: runner IPv6 disabled)"
                    pass=$((pass + 1))
                    continue
                fi
                xu_linux_run linux-arm64 "$ARM64_IMG" "$work" "$out" /w/a.out "$work/stdout" "$work/stderr" $extra_args
                if [ "$XU_LINUX_RUN_STATUS" = "degraded" ]; then
                    echo "PASS $name/$target (compile+file only)"
                    pass=$((pass + 1))
                else
                    code=$XU_LINUX_RUN_CODE
                    run_ok=1
                fi
                ;;
            linux-x64)
                if [ "$name" = "crypto_x509_system_pool" ] && [ "$LINUX_X64_TRUST_OK" = 0 ] && docker_ok "$X64_IMG"; then
                    echo "PASS $name/$target (compile+file only: no system trust store)"
                    pass=$((pass + 1))
                    continue
                fi
                if [ "$name" = "net_ipv6_loopback" ] && [ "$LINUX_X64_IPV6_OK" = "0" ]; then
                    echo "PASS $name/$target (compile+file only: runner IPv6 disabled)"
                    pass=$((pass + 1))
                    continue
                fi
                xu_linux_run linux-x64 "$X64_IMG" "$work" "$out" /w/a.out "$work/stdout" "$work/stderr" $extra_args
                if [ "$XU_LINUX_RUN_STATUS" = "degraded" ]; then
                    echo "PASS $name/$target (compile+file only)"
                    pass=$((pass + 1))
                else
                    code=$XU_LINUX_RUN_CODE
                    run_ok=1
                fi
                ;;
            windows-x64)
                if [ "$name" = "net_unix_loopback" ]; then
                    echo "PASS $name/$target (compile+file only: Unix sockets unsupported)"
                    pass=$((pass + 1))
                    continue
                fi
                if [ "$WINE_DOCKER_OK" = 1 ]; then
                    if [ "$name" = "crypto_x509_pool" ]; then
                        if docker run --rm --platform linux/amd64 -e WINEPREFIX=/wineprefix \
                            -e 'SSL_CERT_FILE=Z:\w\test-root.pem' \
                            -v "$WINEPREFIX_DIR":/wineprefix -v "$work":/w \
                            -w /w --entrypoint wine "$WINE_IMG" /w/a.exe $extra_args >"$work/stdout" 2>/dev/null; then
                            code=0
                        else
                            code=$?
                        fi
                    else
                        if docker run --rm --platform linux/amd64 -e WINEPREFIX=/wineprefix \
                            -v "$WINEPREFIX_DIR":/wineprefix -v "$work":/w \
                            -w /w --entrypoint wine "$WINE_IMG" /w/a.exe $extra_args >"$work/stdout" 2>/dev/null; then
                            code=0
                        else
                            code=$?
                        fi
                    fi
                    run_ok=1
                elif [ -n "$HOST_WINE" ]; then
                    wine_cert=""
                    if [ "$name" = "crypto_x509_pool" ]; then
                        wine_cert="Z:${work//\//\\}\\test-root.pem"
                    fi
                    if WINEDEBUG=-all WINEPREFIX="$WINEPREFIX_DIR" SSL_CERT_FILE="$wine_cert" "$HOST_WINE" "$out" $extra_args >"$work/stdout" 2>"$work/stderr"; then
                        code=0
                    else
                        code=$?
                    fi
                    run_ok=1
                else
                    echo "PASS $name/$target (compile+file only)"
                    pass=$((pass + 1))
                fi
                ;;
            windows-arm64)
                # No local WoA runner: this lane is intentionally compile +
                # PE machine verification until a real ARM64 runner exists.
                echo "PASS $name/$target (compile+file only)"
                pass=$((pass + 1))
                ;;
            linux-loongarch64)
                if echo " $DOMESTIC_NO_RUN " | grep -q " $name "; then
                    echo "PASS $name/$target (compile+file only)"
                    pass=$((pass + 1))
                elif [ "$LOONG_OK" = "1" ]; then
                    if python3 scripts/loong64_qemu_run.py "$out" >"$work/stdout" 2>"$work/stderr"; then
                        code=0
                    else
                        code=$?
                    fi
                    if grep -q '__EXIT_CODE__=' "$work/stderr" 2>/dev/null; then
                        code=$(sed -n 's/.*__EXIT_CODE__=//p' "$work/stderr" | head -1)
                    fi
                    run_ok=1
                else
                    echo "PASS $name/$target (compile+file only)"
                    pass=$((pass + 1))
                fi
                ;;
            linux-riscv64)
                if echo " $DOMESTIC_NO_RUN " | grep -q " $name "; then
                    echo "PASS $name/$target (compile+file only)"
                    pass=$((pass + 1))
                elif [ "$RISCV_OK" = "1" ]; then
                    if python3 scripts/riscv64_qemu_run.py "$out" >"$work/stdout" 2>"$work/stderr"; then
                        code=0
                    else
                        code=$?
                    fi
                    if grep -q '__EXIT_CODE__=' "$work/stderr" 2>/dev/null; then
                        code=$(sed -n 's/.*__EXIT_CODE__=//p' "$work/stderr" | head -1)
                    fi
                    run_ok=1
                else
                    echo "PASS $name/$target (compile+file only)"
                    pass=$((pass + 1))
                fi
                ;;
        esac
        if [ "$run_ok" = "1" ]; then
            if [ "$code" = "-1" ]; then
                echo "FAIL $name/$target (qemu hang/no-exit)"
                fail=$((fail + 1))
            elif [ -f "$dir/expected.txt" ] && ! diff -q "$dir/expected.txt" "$work/stdout" >/dev/null; then
                echo "FAIL $name/$target (stdout)"; diff "$dir/expected.txt" "$work/stdout" | sed 's/^/  /' || true
                fail=$((fail + 1))
            elif [ "$code" -ne "$expected_exit" ]; then
                echo "FAIL $name/$target (exit $code != $expected_exit)"
                fail=$((fail + 1))
            else
                echo "PASS $name/$target"
                pass=$((pass + 1))
            fi
        fi
        rm -rf "$work"
    done
done

echo
[ -n "${XU_LINUX_RUN_DEGRADED_TARGETS:-}" ] && DEGRADED="$DEGRADED$XU_LINUX_RUN_DEGRADED_TARGETS"
[ -n "$DEGRADED" ] && echo "degraded lanes:$DEGRADED"
echo "gen1 platform matrix: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
