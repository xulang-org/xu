#!/usr/bin/env bash
# Build and exercise the Xu server using the hosted product compiler.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
export XU_ROOT="$ROOT_DIR"

if [ -n "${XU_EXAMPLES_ROOT:-}" ]; then
    EXAMPLES_DIR="$XU_EXAMPLES_ROOT"
elif [ -d "$ROOT_DIR/../examples" ]; then
    EXAMPLES_DIR="$ROOT_DIR/../examples"
else
    EXAMPLES_DIR="$ROOT_DIR/../xu-examples"
fi
SOURCE_DEFAULT="$EXAMPLES_DIR/examples/11_http_server/main.xu"
OUT_DIR_DEFAULT="$ROOT_DIR/dist/xu-server"
HEALTH_URL_DEFAULT="http://127.0.0.1:18080/health"

SOURCE=${XU_SERVER_SOURCE:-$SOURCE_DEFAULT}
OUT_DIR=${XU_SERVER_OUT_DIR:-$OUT_DIR_DEFAULT}
LANE=${XU_SERVER_LANE:-product}
COMPILER_INPUT=${XU_COMPILER:-${XU_SEED:-${XU:-}}}
TARGET=${XU_SERVER_TARGET:-}
HEALTH_URL=${XU_SERVER_HEALTH_URL:-$HEALTH_URL_DEFAULT}
HEALTH_TIMEOUT=${XU_SERVER_HEALTH_TIMEOUT:-5}
OPT_LEVEL=${XU_SERVER_OPT_LEVEL:-}
NO_REGCACHE=${XU_SERVER_NO_REGCACHE:-0}

usage() {
    cat <<'EOF'
Usage: scripts/deploy_xu_server.sh <command> [options]

Commands:
  build-local             Build the example for this host (for local run)
  build-linux             Cross-build a Linux x86_64 ELF (linux-x64)
  start                   Build for this host if needed, then run in foreground
  health [URL]            GET a health endpoint (default 127.0.0.1:18080/health)
  smoke-local             Build, start, run 50 lifecycle rounds, then stop
  check-linux             Build linux-x64 and verify the ELF file type
  systemd-unit            Print a hardened systemd unit template (no install)

Options:
  --source PATH           Xu source (default xu-examples/examples/11_http_server/main.xu)
  --output PATH           Output path (default .../<target>; Windows uses .exe)
  --compiler PATH         Hosted Xu compiler (or set XU_COMPILER/XU_SEED/XU)
  --lane product   Select compiler lane (default product)
  --target TARGET         Build target (default host for build-local, linux-x64 for build-linux)
  --opt O0|O1|O2|O3      Select optimization level (default compiler setting)
  --no-regcache          Disable register caching (diagnostic/safe-codegen mode)
  --timeout SECONDS       Health request timeout (default 5)
  -h, --help              Show this help

Examples:
  scripts/deploy_xu_server.sh build-local
  scripts/deploy_xu_server.sh start
  scripts/deploy_xu_server.sh health
  scripts/deploy_xu_server.sh smoke-local
  scripts/deploy_xu_server.sh build-linux --output dist/xu-server/xu-server-linux-x64
EOF
}

die() {
    echo "deploy_xu_server: $*" >&2
    exit 1
}

host_target() {
    local os arch
    os=$(uname -s 2>/dev/null || echo unknown)
    arch=$(uname -m 2>/dev/null || echo unknown)
    case "$os" in
        Darwin) os=macos ;;
        Linux) os=linux ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT) os=windows ;;
        *) die "unsupported host OS: $os" ;;
    esac
    case "$arch" in
        arm64|aarch64) arch=arm64 ;;
        x86_64|amd64) arch=x64 ;;
        *) die "unsupported host architecture: $arch" ;;
    esac
    printf '%s-%s\n' "$os" "$arch"
}

validate_target() {
    case "$1" in
        macos-arm64|macos-x64|linux-arm64|linux-x64|linux-loongarch64|linux-riscv64|windows-x64|windows-arm64|thumbv7em-none|riscv32imac-none)
            ;;
        *)
            die "unsupported target: $1"
            ;;
    esac
}

find_compiler() {
    XU_SEED="$COMPILER_INPUT" "$ROOT_DIR/scripts/xu_host_seed.sh"
}

run_compiler() {
    local compiler=$1
    shift
    "$ROOT_DIR/scripts/run_product_compiler.sh" "$compiler" "$@"
}

default_output() {
    local target=$1 suffix=
    case "$target" in
        windows-*) suffix=.exe ;;
    esac
    printf '%s/xu-server-%s%s\n' "$(resolve_root_path "$OUT_DIR")" "$target" "$suffix"
}

resolve_root_path() {
    case "$1" in
        /*) printf '%s\n' "$1" ;;
        *) printf '%s/%s\n' "$ROOT_DIR" "$1" ;;
    esac
}

check_source() {
    [ -f "$SOURCE" ] || [ -d "$SOURCE" ] || die "source path not found: $SOURCE"
}

compile_target() {
    local target=$1 output=$2 compiler
    local -a build_opts=()
    validate_target "$target"
    compiler=$(find_compiler)
    # Resolve and classify the compiler before touching the source so a
    # product-labelled invocation cannot use a primer even on an invalid
    # input path.
    check_source
    mkdir -p "$(dirname -- "$output")"
    # Default outputs are unsuffixed except Windows .exe. An explicit --output
    # path is preserved as supplied.
    echo "Building $SOURCE"
    echo "  lane: product (hosted compiler)"
    echo "  compiler: $compiler"
    echo "  target: $target"
    echo "  output: $output"
    if [ -n "$OPT_LEVEL" ]; then
        build_opts+=("-$OPT_LEVEL")
    fi
    if [ "$NO_REGCACHE" = 1 ]; then
        build_opts+=("--no-regcache")
    fi
    if [ "${#build_opts[@]}" -gt 0 ]; then
        run_compiler "$compiler" build "$SOURCE" --target "$target" "${build_opts[@]}" -o "$output"
    else
        run_compiler "$compiler" build "$SOURCE" --target "$target" -o "$output"
    fi
    if [ ! -f "$output" ] && [ -f "$output.exe" ]; then
        mv -- "$output.exe" "$output"
    fi
    [ -f "$output" ] || die "compiler did not produce $output"
    chmod +x "$output" 2>/dev/null || true
}

verify_linux_elf() {
    local output=$1 description
    if ! command -v file >/dev/null 2>&1; then
        echo "warning: file(1) unavailable; skipped ELF check" >&2
        return 0
    fi
    description=$(file "$output")
    echo "$description"
    echo "$description" | grep -q 'ELF 64-bit' || die "not an ELF64 binary: $output"
    echo "$description" | grep -Eiq 'x86-64|x86_64' || die "ELF is not x86_64: $output"
}

health_check() {
    local url=$1 body status
    command -v curl >/dev/null 2>&1 || die "curl is required for health checks"
    case "$url" in
        http://*|https://*) ;;
        *) die "health URL must use http:// or https://" ;;
    esac
    body=$(mktemp "${TMPDIR:-/tmp}/xu-server-health.XXXXXX")
    if ! status=$(curl --silent --show-error --max-time "$HEALTH_TIMEOUT" \
        --proto '=http,https' \
        --output "$body" --write-out '%{http_code}' "$url"); then
        rm -f -- "$body"
        echo "health: request failed" >&2
        return 1
    fi
    # Do not echo the URL: callers may accidentally include credentials or
    # query-string tokens.  The request itself still goes to the supplied URL.
    echo "health: HTTP $status"
    if [ "$status" -lt 200 ] || [ "$status" -ge 300 ]; then
        rm -f -- "$body"
        echo "health: unexpected HTTP status" >&2
        return 1
    fi
    # The example's endpoint is deliberately tiny and returns exactly `ok`.
    # Do not log arbitrary response bodies (they may contain application data).
    if [ "$(tr -d '\r\n' < "$body")" != "ok" ]; then
        rm -f -- "$body"
        echo "health: unexpected response body (expected ok)" >&2
        return 1
    fi
    rm -f -- "$body"
    echo "health: OK"
}

# Reproducible local lifecycle gate. It owns both the temporary artifact and
# child process, never reuses a pre-existing server, and never prints response
# bodies. A process that dies while another service owns the port cannot pass:
# every round also checks that the spawned PID is still alive.
local_smoke() (
    set -e
    local tmp_dir output target pid="" base ready=0
    tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/xu-server-smoke.XXXXXX")
    cleanup_smoke() {
        smoke_rc=$?
        trap - EXIT INT TERM
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
        rm -rf -- "$tmp_dir"
        exit "$smoke_rc"
    }
    trap cleanup_smoke EXIT INT TERM

    target=${TARGET:-$(host_target)}
    output="$tmp_dir/xu-server"
    compile_target "$target" "$output"
    base=${HEALTH_URL%/health}

    cd "$ROOT_DIR"
    "$output" >"$tmp_dir/server.log" 2>&1 &
    pid=$!
    for _ in {1..50}; do
        if kill -0 "$pid" 2>/dev/null \
            && [ "$(curl --silent --max-time "$HEALTH_TIMEOUT" --proto '=http' "$HEALTH_URL" 2>/dev/null | tr -d '\r\n')" = ok ]; then
            ready=1
            break
        fi
        sleep 0.1
    done
    if [ "$ready" -ne 1 ]; then
        cat "$tmp_dir/server.log" >&2
        die "local smoke server failed to become healthy"
    fi

    local i health hello echo_body missing
    i=1
    while [ "$i" -le 50 ]; do
        kill -0 "$pid" 2>/dev/null || die "local smoke server exited at iteration $i"
        health=$(curl --fail --silent --max-time "$HEALTH_TIMEOUT" --proto '=http' "$HEALTH_URL" | tr -d '\r\n')
        hello=$(curl --fail --silent --max-time "$HEALTH_TIMEOUT" --proto '=http' "$base/hello" | tr -d '\r\n')
        echo_body=$(curl --fail --silent --max-time "$HEALTH_TIMEOUT" --proto '=http' --request POST --data-binary "xu-$i" "$base/echo" | tr -d '\r\n')
        missing=$(curl --silent --max-time "$HEALTH_TIMEOUT" --proto '=http' --output /dev/null --write-out '%{http_code}' "$base/missing")
        if [ "$health" != ok ] || [ "$hello" != 'hello, xu' ] \
            || [ "$echo_body" != "xu-$i" ] || [ "$missing" != 404 ]; then
            die "local smoke failed at iteration $i"
        fi
        i=$((i + 1))
    done
    echo "local smoke: 50 iterations PASS"
)

print_systemd_unit() {
    cat <<'EOF'
# Copy to /etc/systemd/system/xu-server.service after reviewing paths/user.
# This command only prints the template; the script never writes /etc.
[Unit]
Description=Xu HTTP server
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=xu
Group=xu
WorkingDirectory=/srv/xu-server
ExecStart=/srv/xu-server/xu-server-linux-x64
Restart=on-failure
RestartSec=2s
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true

[Install]
WantedBy=multi-user.target
EOF
}

parse_options() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --source)
                [ "$#" -ge 2 ] || die "--source needs a path"
                SOURCE=$2; shift 2 ;;
            --output)
                [ "$#" -ge 2 ] || die "--output needs a path"
                OUTPUT=$2; shift 2 ;;
            --compiler)
                [ "$#" -ge 2 ] || die "--compiler needs a path"
                COMPILER_INPUT=$2; shift 2 ;;
            --lane)
                [ "$#" -ge 2 ] || die "--lane needs product"
                LANE=$2; shift 2 ;;
            --target)
                [ "$#" -ge 2 ] || die "--target needs a value"
                TARGET=$2; shift 2 ;;
            --opt)
                [ "$#" -ge 2 ] || die "--opt needs O0, O1, O2, or O3"
                OPT_LEVEL=$2; shift 2 ;;
            --no-regcache)
                NO_REGCACHE=1; shift ;;
            --timeout)
                [ "$#" -ge 2 ] || die "--timeout needs seconds"
                HEALTH_TIMEOUT=$2; shift 2 ;;
            -h|--help)
                usage; exit 0 ;;
            --)
                shift; break ;;
            *)
                die "unknown option: $1 (see --help)" ;;
        esac
    done
    [ "$#" -eq 0 ] || die "unexpected argument: $1"
}

main() {
    [ "$#" -ge 1 ] || { usage >&2; exit 2; }
    local command=$1
    shift
    OUTPUT=""
    # health accepts one positional URL; all other commands use options only.
    if [ "$command" = health ] && [ "$#" -gt 0 ] && [[ "$1" != -* ]]; then
        HEALTH_URL=$1
        shift
    fi
    parse_options "$@"

    case "$LANE" in
        product) ;;
        *) die "lane must be product (got $LANE)" ;;
    esac
    case "$OPT_LEVEL" in
        ""|O0|O1|O2|O3) ;;
        *) die "--opt must be O0, O1, O2, or O3" ;;
    esac
    case "$NO_REGCACHE" in
        0|1) ;;
        *) die "XU_SERVER_NO_REGCACHE must be 0 or 1" ;;
    esac

    # Source/output options are repository-relative by convention. Resolve
    # them before `start` changes directory, so invocation cwd cannot alter
    # where a build is read from or where a binary is later executed.
    case "$command" in
        build-local|build-linux|check-linux|start|smoke-local)
            SOURCE=$(resolve_root_path "$SOURCE")
            if [ -n "$OUTPUT" ]; then
                OUTPUT=$(resolve_root_path "$OUTPUT")
            fi
            ;;
    esac

    local target output
    case "$command" in
        build-local)
            target=${TARGET:-$(host_target)}
            output=${OUTPUT:-$(default_output "$target")}
            compile_target "$target" "$output"
            echo "Built local binary: $output"
            ;;
        build-linux)
            target=${TARGET:-linux-x64}
            [ "$target" = linux-x64 ] || die "build-linux only supports --target linux-x64"
            output=${OUTPUT:-$(default_output "$target")}
            compile_target "$target" "$output"
            verify_linux_elf "$output"
            echo "Built Linux x86_64 binary: $output"
            ;;
        check-linux)
            target=${TARGET:-linux-x64}
            [ "$target" = linux-x64 ] || die "check-linux only supports --target linux-x64"
            output=${OUTPUT:-$(default_output "$target")}
            compile_target "$target" "$output"
            verify_linux_elf "$output"
            echo "Linux x86_64 compile/file check: OK"
            ;;
        start)
            target=${TARGET:-$(host_target)}
            output=${OUTPUT:-$(default_output "$target")}
            if [ ! -x "$output" ]; then
                compile_target "$target" "$output"
            fi
            echo "Starting Xu HTTP server (foreground; Ctrl-C to stop)"
            # The example's default document root is repository-relative. Run
            # from the repository root even when this script was invoked via
            # an absolute path from another working directory.
            cd "$ROOT_DIR"
            exec "$output"
            ;;
        health)
            health_check "$HEALTH_URL"
            ;;
        smoke-local)
            local_smoke
            ;;
        systemd-unit)
            print_systemd_unit
            ;;
        help|-h|--help)
            usage
            ;;
        *)
            usage >&2
            die "unknown command: $command"
            ;;
    esac
}

main "$@"
