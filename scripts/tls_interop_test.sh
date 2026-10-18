#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

command -v openssl >/dev/null 2>&1 || {
    echo "tls_interop_test: SKIP (openssl unavailable)"
    exit 0
}
# Product-only OpenSSL interoperability gate. Resolve the hosted seed through
# the canonical boundary and compile through the hermetic product wrapper;
# no cargo/bootstrap fallback is permitted here.
LANE="product"
HOST_SEED_RESOLVER="$PWD/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$PWD/scripts/run_product_compiler.sh"
COMPILER_INPUT=${XU_COMPILER:-${XU:-}}
[ -x "$HOST_SEED_RESOLVER" ] && [ -x "$PRODUCT_COMPILER_RUNNER" ] || {
    echo "tls_interop_test: missing hosted seed/wrapper" >&2
    exit 1
}
if [ -n "$COMPILER_INPUT" ]; then
    case "$COMPILER_INPUT" in
        /*) ;;
        *) COMPILER_INPUT="$PWD/$COMPILER_INPUT" ;;
    esac
    XU=$(XU_SEED="$COMPILER_INPUT" \
        "$HOST_SEED_RESOLVER") || {
        echo "tls_interop_test: compiler rejected by product boundary: $COMPILER_INPUT" >&2
        exit 1
    }
else
    XU=$("$HOST_SEED_RESOLVER") || {
        echo "tls_interop_test: hosted product compiler missing (run make xu)" >&2
        exit 1
    }
fi
[ -x "$XU" ] || {
    echo "tls_interop_test: missing product compiler: $XU" >&2
    exit 1
}

work=$(mktemp -d)
server_pid=""
cleanup() {
    if [ -n "$server_pid" ]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    if [ "${XU_TLS_KEEP_WORK:-0}" = "1" ]; then
        echo "tls_interop_test: kept $work" >&2
    else
        rm -rf "$work"
    fi
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj /CN=localhost -addext subjectAltName=DNS:localhost \
    -keyout "$work/key.pem" -out "$work/cert.pem" >/dev/null 2>&1
"$PRODUCT_COMPILER_RUNNER" "$XU" build \
    tests/fixtures/crypto_tls_ecdhe_interop/main.xu -o "$work/xu-tls"
if [ -f "$work/xu-tls.xin" ]; then
    mv "$work/xu-tls.xin" "$work/xu-tls"
fi
chmod +x "$work/xu-tls"

port1=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
openssl s_server -accept "$port1" -cert "$work/cert.pem" -key "$work/key.pem" \
    -tls1_2 -cipher ECDHE-RSA-AES128-GCM-SHA256 -www -naccept 1 \
    >"$work/openssl-server.out" 2>"$work/openssl-server.err" &
server_pid=$!
sleep 1
"$work/xu-tls" client "127.0.0.1:$port1" >"$work/xu-client.out"
wait "$server_pid"
server_pid=""
grep -qx true "$work/xu-client.out"

port2=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
"$work/xu-tls" server "127.0.0.1:$port2" "$work/cert.pem" "$work/key.pem" \
    >"$work/xu-server.out" 2>"$work/xu-server.err" &
server_pid=$!
sleep 1
printf 'ping\n' | openssl s_client -connect "127.0.0.1:$port2" \
    -tls1_2 -cipher ECDHE-RSA-AES128-GCM-SHA256 -quiet \
    >"$work/openssl-client.out" 2>"$work/openssl-client.err"
wait "$server_pid"
server_pid=""
grep -qx true "$work/xu-server.out"
grep -q '^pong$' "$work/openssl-client.out"

port3=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
openssl s_server -accept "$port3" -cert "$work/cert.pem" -key "$work/key.pem" \
    -tls1_3 -ciphersuites TLS_AES_128_GCM_SHA256 -groups P-256 -www -naccept 1 \
    >"$work/openssl-server13.out" 2>"$work/openssl-server13.err" &
server_pid=$!
sleep 1
"$work/xu-tls" client "127.0.0.1:$port3" >"$work/xu-client13.out"
wait "$server_pid"
server_pid=""
grep -qx true "$work/xu-client13.out"

port4=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
"$work/xu-tls" server "127.0.0.1:$port4" "$work/cert.pem" "$work/key.pem" \
    >"$work/xu-server13.out" 2>"$work/xu-server13.err" &
server_pid=$!
sleep 1
printf 'ping\n' | openssl s_client -connect "127.0.0.1:$port4" \
    -tls1_3 -ciphersuites TLS_AES_128_GCM_SHA256 -groups P-256 -quiet \
    >"$work/openssl-client13.out" 2>"$work/openssl-client13.err"
wait "$server_pid"
server_pid=""
grep -qx true "$work/xu-server13.out"
grep -q '^pong$' "$work/openssl-client13.out"

echo "tls_interop_test: PASS (TLS 1.2 ECDHE_RSA + TLS 1.3 P-256/AES_128_GCM, both directions)"
