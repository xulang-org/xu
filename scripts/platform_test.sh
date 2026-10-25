#!/usr/bin/env bash
# Cross-platform execution matrix: compile representative fixtures to all
# four targets and run them — native (macos-arm64), Rosetta 2 (macos-x64),
# Docker (linux-arm64 / linux-x64). stdout and exit code are compared
# byte-for-byte with the fixture's expectations.
#
# Linux runners are plain local images (static binaries need nothing):
#   linux/arm64 -> postgres:15, linux/amd64 -> jsbin-wine (override with
#   XU_LINUX_ARM64_IMAGE / XU_LINUX_X64_IMAGE). If a linux image is
#   missing, or docker/qemu cannot exec (exit 125/126/127, no binfmt, wrong
#   image arch), that lane degrades to compile + `file` verification and
#   says so — empty stdout is not a program FAIL. See scripts/docker_run_target.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
export XU_ROOT="$ROOT"
cd "$ROOT"

XU=""
REQUESTED_LANE=""
REQUESTED_TARGETS=""
REQUESTED_FIXTURES=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) XU="${1#*=}" ;;
        --lane=*) REQUESTED_LANE="${1#*=}" ;;
        --targets=*) REQUESTED_TARGETS="${1#*=}" ;;
        --fixtures=*) REQUESTED_FIXTURES="${1#*=}" ;;
        *) echo "platform_test: unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

HOST_SEED_RESOLVER="$ROOT/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$ROOT/scripts/run_product_compiler.sh"

[ "${REQUESTED_LANE:-product}" = product ] || { echo "platform_test: only lane=product is supported" >&2; exit 2; }
BIN=$(XU_SEED="$XU" "$HOST_SEED_RESOLVER")
LANE=product
echo "platform_test: lane=product compiler=$BIN" >&2
compile_source() {
    local subcommand=build
    local arguments=()
    local arg
    for arg in "$@"; do
        if [ "$arg" = "--test" ]; then subcommand=test
        else arguments+=("$arg")
        fi
    done
    "$PRODUCT_COMPILER_RUNNER" "$BIN" "$subcommand" "${arguments[@]}"
}

FIXTURES="arith_precedence f64_loop_regcache string_concat struct_sample generic_struct fib_recursive alloc_stress drop_loop_stress borrow_mut_param result_propagate match_int array_basic array_push_stress array_string_owning str_convert string_bytes file_roundtrip atomic_basic args_basic exit_builtin slice_basic char_builtins parse_int_ok starts_with eprintln_fd multifile chan_xu_basic chan_parallel channel_blocking_string std_os path_os_extra os_b1c time_wall crypto_rand crypto_ecdsa crypto_x509_ecdsa crypto_x509_chain crypto_x509_pool crypto_tls_pipe crypto_tls_ecdhe_interop net_platform_files net_udp_echo net_udp_connected net_ipv6_loopback net_unix_loopback net_interfaces net_unsupported_contract"
TARGETS="macos-arm64 macos-x64 linux-arm64 linux-x64 windows-x64 windows-arm64 linux-loongarch64 linux-riscv64"
if [ -n "$REQUESTED_TARGETS" ]; then
    for requested in $REQUESTED_TARGETS; do
        case " $TARGETS " in
            *" $requested "*) ;;
            *) echo "platform_test: unsupported target $requested" >&2; exit 1 ;;
        esac
    done
    TARGETS=$REQUESTED_TARGETS
fi
if [ -n "$REQUESTED_FIXTURES" ]; then
    for requested in $REQUESTED_FIXTURES; do
        case "$requested" in *[!a-zA-Z0-9_-]*) echo "platform_test: invalid fixture $requested" >&2; exit 1 ;; esac
        [ -f "tests/fixtures/$requested/main.xu" ] && [ -f "tests/fixtures/$requested/expected.txt" ] \
            || { echo "platform_test: fixture missing $requested" >&2; exit 1; }
    done
    FIXTURES=$REQUESTED_FIXTURES
fi

# M39: loong64 / riscv64 run under qemu-system-* via semihosting shims
# (scripts/loong64_qemu_run.py, scripts/riscv64_qemu_run.py). File IO /
# threads / env fixtures are not supported by the shim — those lanes
# degrade to compile+file checks.
LOONG_RUN="${XU_LOONG_QEMU:-qemu-system-loongarch64}"
LOONG_OK=0
command -v "$LOONG_RUN" >/dev/null 2>&1 && LOONG_OK=1
RISCV_RUN="${XU_RISCV_QEMU:-qemu-system-riscv64}"
RISCV_OK=0
command -v "$RISCV_RUN" >/dev/null 2>&1 && RISCV_OK=1
# Shared no-run set: shim has sync-clone (buffered xu ok) + a single-file
# ramdisk, but not true parallelism, host env/args, a directory hierarchy,
# system files such as /etc/services, hosted sockets, or a kernel entropy
# source.  Keep those fixtures as target compile/ELF checks; real Linux
# machines remain the execution authority for the corresponding APIs.
DOMESTIC_NO_RUN="alloc_stress args_basic chan_parallel channel_blocking_string std_os eprintln_fd path_os_extra os_b1c time_wall crypto_rand crypto_ecdsa crypto_x509_ecdsa crypto_x509_chain crypto_x509_pool crypto_tls_pipe crypto_tls_ecdhe_interop net_platform_files net_udp_echo net_udp_connected net_ipv6_loopback net_unix_loopback net_interfaces"
LOONG_NO_RUN="$DOMESTIC_NO_RUN"
RISCV_NO_RUN="$DOMESTIC_NO_RUN"

ARM64_IMG="${XU_LINUX_ARM64_IMAGE:-postgres:15}"
X64_IMG="${XU_LINUX_X64_IMAGE:-jsbin-wine}"
WINE_IMG="${XU_WINE_IMAGE:-jsbin-wine}"
# Persistent wine prefix (first run creates it; later runs are fast).
WINEPREFIX_DIR="$ROOT/target/wineprefix"
mkdir -p "$WINEPREFIX_DIR"
HOST_WINE=""
if command -v wine >/dev/null 2>&1; then
    HOST_WINE=$(command -v wine)
    # Installed x64 Wine may itself be unexecutable on an ARM host. Probe the
    # runner independently, never reinterpret a fixture's bad exit as success.
    if ! "$HOST_WINE" --version >/dev/null 2>&1; then HOST_WINE=""; fi
fi

docker_ok() { docker image inspect "$1" >/dev/null 2>&1; }
. ./scripts/docker_run_target.sh
DEGRADED=""
MACOS_ARM64_OK=0
MACOS_X64_OK=0
if [ "$(uname -s)" = Darwin ]; then
    if [ "$(uname -m)" = arm64 ]; then MACOS_ARM64_OK=1; fi
    if /usr/bin/arch -x86_64 /usr/bin/true >/dev/null 2>&1; then MACOS_X64_OK=1; fi
fi
[ "$MACOS_ARM64_OK" = 1 ] || DEGRADED="$DEGRADED macos-arm64(no-runner)"
[ "$MACOS_X64_OK" = 1 ] || DEGRADED="$DEGRADED macos-x64(no-runner)"
WINE_DOCKER_OK=0
if docker_ok "$WINE_IMG" && docker run --pull=never --rm --platform linux/amd64 \
    --entrypoint wine "$WINE_IMG" --version >/dev/null 2>&1; then
    WINE_DOCKER_OK=1
fi
docker_ok "$ARM64_IMG" || DEGRADED="$DEGRADED linux-arm64(no-image)"
docker_ok "$X64_IMG" || DEGRADED="$DEGRADED linux-x64(no-image)"
if [ "$WINE_DOCKER_OK" = 0 ] && [ -z "$HOST_WINE" ]; then
    DEGRADED="$DEGRADED windows-x64(no-runner)"
fi

# IPv6 loopback is a host/container capability, not an architecture compile
# property. Some Docker Desktop images disable IPv6 in the network namespace;
# keep that lane honest by recording compile+file evidence instead of turning
# an otherwise valid IPv6 implementation into a false program failure.
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

pass=0
fail=0

# Execute an explicitly built artifact. Both user programs and test harnesses
# use this path, so every target produces exactly one verdict and checks the
# same runner availability, expected stdout and exit status.
run_fixture_target() {
    case "$target" in
        macos-arm64|macos-x64)
            local mac_runner=$MACOS_ARM64_OK mac_format="Mach-O 64-bit executable arm64"
            if [ "$target" = macos-x64 ]; then mac_runner=$MACOS_X64_OK; mac_format="Mach-O 64-bit executable x86_64"; fi
            if [ "$mac_runner" = 0 ]; then
                if file "$out" | grep -q "$mac_format"; then
                    echo "PASS $name/$target (compile+file only: no native runner)"
                    pass=$((pass + 1))
                else
                    echo "FAIL $name/$target (degraded check failed)"
                    fail=$((fail + 1))
                fi
                rm -rf "$tmp"; return
            fi
            if [ "$name" = "crypto_x509_pool" ]; then
                run_env="SSL_CERT_FILE=$tmp/test-root.pem"
            else
                run_env=""
            fi
            if (cd "$tmp" && env $run_env "./$(basename "$out")" $extra_args) >"$tmp/stdout" 2>/dev/null; then
                code=0
            else
                code=$?
            fi ;;
        linux-loongarch64)
            # M39: QEMU semihosting runner (syscall shim); no-run fixtures
            # (file IO/threads/env) degrade to compile+file.
            if [ "$LOONG_OK" = "0" ]; then
                file "$out" | grep -q "ELF 64-bit LSB executable, LoongArch" \
                    && { echo "PASS $name/$target (compile+file only)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            if echo " $LOONG_NO_RUN " | grep -q " $name "; then
                file "$out" | grep -q "ELF 64-bit LSB executable, LoongArch" \
                    && { echo "PASS $name/$target (compile+file only)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            if python3 scripts/loong64_qemu_run.py "$out" >"$tmp/stdout" 2>"$tmp/stderr"; then
                code=0
            else
                code=$?
            fi
            if grep -q '__EXIT_CODE__=' "$tmp/stderr" 2>/dev/null; then
                code=$(sed -n 's/.*__EXIT_CODE__=//p' "$tmp/stderr" | head -1)
            fi
            if [ "$code" = "-1" ]; then
                echo "FAIL $name/$target (qemu hang/no-exit)"; sed 's/^/  /' "$tmp/stderr" | head -3
                fail=$((fail + 1)); rm -rf "$tmp"; return
            fi ;;
        linux-riscv64)
            # M39: QEMU virt + M-mode ecall shim (scripts/riscv64_qemu_run.py).
            if [ "$RISCV_OK" = "0" ]; then
                file "$out" | grep -q "ELF 64-bit LSB executable, UCB RISC-V" \
                    && { echo "PASS $name/$target (compile+file only)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            if echo " $RISCV_NO_RUN " | grep -q " $name "; then
                file "$out" | grep -q "ELF 64-bit LSB executable, UCB RISC-V" \
                    && { echo "PASS $name/$target (compile+file only)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            if python3 scripts/riscv64_qemu_run.py "$out" >"$tmp/stdout" 2>"$tmp/stderr"; then
                code=0
            else
                code=$?
            fi
            if grep -q '__EXIT_CODE__=' "$tmp/stderr" 2>/dev/null; then
                code=$(sed -n 's/.*__EXIT_CODE__=//p' "$tmp/stderr" | head -1)
            fi
            if [ "$code" = "-1" ]; then
                echo "FAIL $name/$target (qemu hang/no-exit)"; sed 's/^/  /' "$tmp/stderr" | head -3
                fail=$((fail + 1)); rm -rf "$tmp"; return
            fi ;;
        linux-arm64)
            if [ "$name" = "net_ipv6_loopback" ] && [ "$LINUX_ARM64_IPV6_OK" = "0" ]; then
                file "$out" | grep -q "ELF 64-bit LSB executable, ARM aarch64" \
                    && { echo "PASS $name/$target (compile+file only: runner IPv6 disabled)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            xu_linux_run linux-arm64 "$ARM64_IMG" "$tmp" "$out" /w/a.out "$tmp/stdout" "$tmp/stderr" $extra_args
            if [ "$XU_LINUX_RUN_STATUS" = "degraded" ]; then
                file "$out" | grep -q "ELF 64-bit LSB executable, ARM aarch64" \
                    && { echo "PASS $name/$target (compile+file only)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            code=$XU_LINUX_RUN_CODE ;;
        linux-x64)
            if [ "$name" = "net_ipv6_loopback" ] && [ "$LINUX_X64_IPV6_OK" = "0" ]; then
                file "$out" | grep -q "ELF 64-bit LSB executable, x86-64" \
                    && { echo "PASS $name/$target (compile+file only: runner IPv6 disabled)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            xu_linux_run linux-x64 "$X64_IMG" "$tmp" "$out" /w/a.out "$tmp/stdout" "$tmp/stderr" $extra_args
            if [ "$XU_LINUX_RUN_STATUS" = "degraded" ]; then
                file "$out" | grep -q "ELF 64-bit LSB executable, x86-64" \
                    && { echo "PASS $name/$target (compile+file only)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            code=$XU_LINUX_RUN_CODE ;;
        windows-x64)
            if [ "$name" = "net_unix_loopback" ]; then
                file "$out" | grep -q "PE32+ executable" \
                    && { echo "PASS $name/$target (compile+file only: Unix sockets unsupported)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            # The test lane uses `test-harness.exe`, while ordinary fixtures
            # use `a.exe`. Execute the artifact that was actually compiled;
            # hard-coding a.exe made a missing-file error look like a stdout
            # regression in the Windows test runner.
            win_exe="/w/$(basename "$out")"
                if [ "$WINE_DOCKER_OK" = 1 ]; then
                if [ "$name" = "crypto_x509_pool" ]; then
                    if docker run --rm --platform linux/amd64 -e WINEPREFIX=/wineprefix \
                        -e 'SSL_CERT_FILE=Z:\w\test-root.pem' \
                        -v "$WINEPREFIX_DIR":/wineprefix -v "$tmp":/w \
                        -w /w --entrypoint wine "$WINE_IMG" "$win_exe" $extra_args >"$tmp/stdout" 2>/dev/null; then
                        code=0
                    else
                        code=$?
                    fi
                else
                    if docker run --rm --platform linux/amd64 -e WINEPREFIX=/wineprefix \
                        -v "$WINEPREFIX_DIR":/wineprefix -v "$tmp":/w \
                        -w /w --entrypoint wine "$WINE_IMG" "$win_exe" $extra_args >"$tmp/stdout" 2>/dev/null; then
                        code=0
                    else
                        code=$?
                    fi
                fi
            elif [ -n "$HOST_WINE" ]; then
                wine_cert=""
                if [ "$name" = "crypto_x509_pool" ]; then
                    wine_cert="Z:${tmp//\//\\}\\test-root.pem"
                fi
                if WINEDEBUG=-all WINEPREFIX="$WINEPREFIX_DIR" SSL_CERT_FILE="$wine_cert" "$HOST_WINE" "$out" $extra_args >"$tmp/stdout" 2>"$tmp/stderr"; then
                    code=0
                else
                    code=$?
                fi
            else
                file "$out" | grep -q "PE32+ executable" \
                    && { echo "PASS $name/$target (compile+file only)"; pass=$((pass + 1)); rm -rf "$tmp"; return; }
                echo "FAIL $name/$target (degraded check failed)"; fail=$((fail + 1)); rm -rf "$tmp"; return
            fi
            # wine logs first-run noise on stderr; drop a null-prefix note
            ;;
        windows-arm64)
            # No local WoA runner; compile + PE ARM64 machine check.
            if file "$out" | grep -qiE 'PE32\+.*(Aarch64|ARM64|aarch64)'; then
                echo "PASS $name/$target (compile+file only)"
                pass=$((pass + 1)); rm -rf "$tmp"; return
            fi
            echo "FAIL $name/$target (degraded check failed)"; file "$out" | sed 's/^/  /'
            fail=$((fail + 1)); rm -rf "$tmp"; return
            ;;
    esac
    if ! diff -q "$dir/expected.txt" "$tmp/stdout" >/dev/null; then
        echo "FAIL $name/$target (stdout)"; diff "$dir/expected.txt" "$tmp/stdout" | sed 's/^/  /' || true
        fail=$((fail + 1))
    elif [ "$code" -ne "$expected_exit" ]; then
        echo "FAIL $name/$target (exit $code != $expected_exit)"
        fail=$((fail + 1))
    else
        echo "PASS $name/$target"
        pass=$((pass + 1))
    fi
    rm -rf "$tmp"
}

for name in $FIXTURES; do
    dir="tests/fixtures/$name"
    [ -f "$dir/error.txt" ] && continue
    expected_exit=0
    [ -f "$dir/expected.exit" ] && expected_exit=$(tr -d '[:space:]' <"$dir/expected.exit")
    for target in $TARGETS; do
        tmp=$(mktemp -d)
        out="$tmp/a.out"
        if [ "$target" = "windows-x64" ] || [ "$target" = "windows-arm64" ]; then
            out="$tmp/a.exe"
        fi
        XU_LINUX_RUN_SSL_CERT_BASENAME=""
        if [ "$name" = "crypto_x509_pool" ]; then
            cp "$dir/test-root.pem" "$tmp/test-root.pem"
            XU_LINUX_RUN_SSL_CERT_BASENAME="test-root.pem"
        fi
        # multi-file fixtures: main.xu first, then other .xu files sorted
        inputs="$dir/main.xu"
        for extra in "$dir"/*.xu; do
            [ "$extra" = "$dir/main.xu" ] && continue
            inputs="$inputs $extra"
        done
        if ! compile_source $inputs --target "$target" -o "$out" 2>"$tmp/err"; then
            echo "FAIL $name/$target (compile)"; sed 's/^/  /' "$tmp/err"; fail=$((fail + 1)); rm -rf "$tmp"; continue
        fi
        extra_args=""
        if [ -f "$dir/args.txt" ]; then
            extra_args=$(cat "$dir/args.txt")
        fi
        run_fixture_target
    done
done

# Test subcommand is build-only in the product lane. Use an explicit output,
# then execute through the same eight-target fixture contract above. The
# frozen primer still receives --test, with -o selecting build-only output.
for target in $TARGETS; do
    tmp=$(mktemp -d)
    name=test.ok
    dir="$tmp/expected"
    mkdir -p "$dir"
    cp tests/lang/test.ok.expected.txt "$dir/expected.txt"
    expected_exit=0
    extra_args=""
    XU_LINUX_RUN_SSL_CERT_BASENAME=""
    out="$tmp/test-harness"
    case "$target" in windows-*) out="$out.exe" ;; esac
    if ! compile_source tests/lang/test.ok.xu --test --target "$target" -o "$out" > "$tmp/compile.out" 2> "$tmp/err"; then
        echo "FAIL test.ok/$target (compile)"; sed 's/^/  /' "$tmp/err"
        fail=$((fail + 1)); rm -rf "$tmp"; continue
    fi
    run_fixture_target
done

echo
[ -n "${XU_LINUX_RUN_DEGRADED_TARGETS:-}" ] && DEGRADED="$DEGRADED$XU_LINUX_RUN_DEGRADED_TARGETS"
[ -n "$DEGRADED" ] && echo "degraded lanes:$DEGRADED"
echo "platform matrix: lane=$LANE PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
