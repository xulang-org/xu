#!/usr/bin/env bash
# Explicit remote deployment adapter for the Xu HTTP server example.
#
# Unlike deploy_xu_server.sh, every command in this file is remote-aware and
# requires an explicit command plus a validated private configuration file.
# The file is parsed as data; it is never sourced or executed.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
LOCAL_DEPLOY="$SCRIPT_DIR/deploy_xu_server.sh"

CONFIG_FILE=${XU_SERVER_CONFIG:-$ROOT_DIR/server.md}
ARTIFACT=${XU_SERVER_ARTIFACT:-$ROOT_DIR/dist/xu-server/xu-server-linux-x64}
SOURCE=${XU_SERVER_SOURCE:-}
COMPILER=${XU_COMPILER:-${XU:-}}
OPT_LEVEL=${XU_SERVER_OPT_LEVEL:-}
NO_REGCACHE=${XU_SERVER_NO_REGCACHE:-0}
HEALTH_TIMEOUT=${XU_SERVER_HEALTH_TIMEOUT:-5}

SERVER_HOST=${XU_SERVER_HOST:-}
SERVER_SSH_PORT=${XU_SERVER_SSH_PORT:-}
SERVER_USER=${XU_SERVER_USER:-}
SERVER_APP_ROOT=${XU_SERVER_APP_ROOT:-}
SERVER_SERVICE=${XU_SERVER_SERVICE:-}
SERVER_TARGET=${XU_SERVER_TARGET:-}
SERVER_HEALTH_URL=${XU_SERVER_HEALTH_URL:-}
SERVER_RUNTIME_USER=${XU_SERVER_RUNTIME_USER:-}
SERVER_IDENTITY_FILE=${XU_SERVER_IDENTITY_FILE:-}
SERVER_KNOWN_HOSTS_FILE=${XU_SERVER_KNOWN_HOSTS_FILE:-}
SERVER_PASSWORD_FILE=${XU_SERVER_PASSWORD_FILE:-}
SERVER_PASSWORD=${XU_SERVER_PASSWORD:-}

PASSWORD_TMP=""
PASSWORD_TMP_OWNED=0
SSH_DEST=""
declare -a SSH_COMMON=()

usage() {
    cat <<'EOF'
Usage: scripts/deploy_xu_remote.sh <command> [options]

Commands:
  check              Validate config and inspect the remote Linux host
  deploy             Build linux-x64, upload, verify, switch, and health-check
  status             Show active release, systemd state, and remote health
  health             Check /health from the remote host without logging body
  smoke              Repeat health/hello/echo/404 checks on the remote host
  restart            Restart the configured systemd service and check health
  stop               Stop the configured systemd service
  rollback           Swap current/previous releases, restart, and health-check

Options:
  --config PATH      Private config (default ./server.md)
  --artifact PATH    Local Linux artifact path
  --source PATH      Xu server source passed to the local build adapter
  --compiler PATH    Xu compiler used for the linux-x64 build
  --opt O0|O1|O2|O3 Optimization level
  --no-regcache      Disable register caching for the server build
  --timeout SECONDS  SSH/curl timeout (default 5)
  -h, --help         Show this help

Remote commands are never selected implicitly by the local deployment script.
The local artifact build is always the hosted product lane; `--compiler` is
resolved by `deploy_xu_server.sh` and a bootstrap primer is rejected. Use the
local adapter's explicit `--oracle` mode for recovery smoke only; this remote
adapter never turns that lane on implicitly.
EOF
}

die() {
    echo "deploy_xu_remote: $*" >&2
    exit 1
}

cleanup() {
    if [ "$PASSWORD_TMP_OWNED" -eq 1 ] && [ -n "$PASSWORD_TMP" ] && [ -f "$PASSWORD_TMP" ]; then
        rm -f -- "$PASSWORD_TMP"
    fi
}
trap cleanup EXIT

set_if_empty() {
    local name=$1 value=$2
    if [ -z "${!name}" ]; then
        printf -v "$name" '%s' "$value"
    fi
}

load_config() {
    [ -r "$CONFIG_FILE" ] || die "config is not readable: $CONFIG_FILE"

    local line key value saw_key=0
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%$'\r'}
        case "$line" in
            SERVER_*=*)
                saw_key=1
                key=${line%%=*}
                value=${line#*=}
                case "$key" in
                    SERVER_HOST|SERVER_SSH_PORT|SERVER_USER|SERVER_APP_ROOT|SERVER_SERVICE|SERVER_TARGET|SERVER_HEALTH_URL|SERVER_RUNTIME_USER|SERVER_IDENTITY_FILE|SERVER_KNOWN_HOSTS_FILE|SERVER_PASSWORD_FILE|SERVER_PASSWORD)
                        set_if_empty "$key" "$value"
                        ;;
                esac
                ;;
        esac
    done < "$CONFIG_FILE"

    # Backward-compatible private format used by the existing server.md:
    # endpoint on line 1, user on line 3, password on line 4. It is supported
    # for migration only and is never printed.
    if [ "$saw_key" -eq 0 ] && [ -z "$SERVER_HOST" ]; then
        local endpoint legacy_user legacy_password
        endpoint=$(sed -n '1{s/\r$//;p;}' "$CONFIG_FILE")
        legacy_user=$(sed -n '3{s/\r$//;p;}' "$CONFIG_FILE")
        legacy_password=$(sed -n '4{s/\r$//;p;}' "$CONFIG_FILE")
        case "$endpoint" in
            *:*)
                SERVER_HOST=${endpoint%:*}
                SERVER_SSH_PORT=${endpoint##*:}
                ;;
            *) die "legacy config line 1 must be host:port" ;;
        esac
        SERVER_USER=$legacy_user
        SERVER_PASSWORD=$legacy_password
        echo "deploy_xu_remote: warning: legacy plaintext-password server.md; migrate to SSH key/agent" >&2
    fi

    set_if_empty SERVER_SSH_PORT 22
    set_if_empty SERVER_USER root
    set_if_empty SERVER_APP_ROOT /srv/xu-server
    set_if_empty SERVER_SERVICE xu-server.service
    set_if_empty SERVER_TARGET linux-x64
    set_if_empty SERVER_HEALTH_URL http://127.0.0.1:18080/health
    set_if_empty SERVER_RUNTIME_USER xu

    [ -n "$SERVER_HOST" ] || die "SERVER_HOST is required"
    case "$SERVER_HOST" in *[!A-Za-z0-9._-]*) die "SERVER_HOST contains unsupported characters" ;; esac
    case "$SERVER_SSH_PORT" in ''|*[!0-9]*) die "SERVER_SSH_PORT must be numeric" ;; esac
    [ "$SERVER_SSH_PORT" -ge 1 ] && [ "$SERVER_SSH_PORT" -le 65535 ] || die "SERVER_SSH_PORT out of range"
    case "$SERVER_USER" in ''|*[!A-Za-z0-9._-]*) die "SERVER_USER is invalid" ;; esac
    case "$SERVER_RUNTIME_USER" in ''|*[!A-Za-z0-9._-]*) die "SERVER_RUNTIME_USER is invalid" ;; esac
    case "$SERVER_APP_ROOT" in /*) ;; *) die "SERVER_APP_ROOT must be absolute" ;; esac
    case "$SERVER_APP_ROOT" in *[!A-Za-z0-9._/-]*) die "SERVER_APP_ROOT contains unsupported characters" ;; esac
    case "$SERVER_SERVICE" in *.service) ;; *) die "SERVER_SERVICE must end in .service" ;; esac
    case "$SERVER_SERVICE" in *[!A-Za-z0-9@_.-]*) die "SERVER_SERVICE is invalid" ;; esac
    [ "$SERVER_TARGET" = linux-x64 ] || die "remote adapter currently requires SERVER_TARGET=linux-x64"
    # The URL is passed as an argument to a remote shell. Restrict it to a
    # loopback origin, decimal port, and URL-path characters before it crosses
    # that boundary; a broad shell glob here would permit command injection.
    if [[ ! "$SERVER_HEALTH_URL" =~ ^http://(127\.0\.0\.1|localhost):([0-9]{1,5})/[A-Za-z0-9._~/-]+$ ]]; then
        die "SERVER_HEALTH_URL must be loopback HTTP with a safe explicit path"
    fi
    local health_port=${BASH_REMATCH[2]}
    [ "$health_port" -ge 1 ] && [ "$health_port" -le 65535 ] || die "SERVER_HEALTH_URL port out of range"

    if [ -n "$SERVER_IDENTITY_FILE" ]; then
        case "$SERVER_IDENTITY_FILE" in
            /*) ;;
            *) SERVER_IDENTITY_FILE="$(dirname -- "$CONFIG_FILE")/$SERVER_IDENTITY_FILE" ;;
        esac
        [ -r "$SERVER_IDENTITY_FILE" ] || die "SERVER_IDENTITY_FILE is not readable"
    fi
    if [ -n "$SERVER_KNOWN_HOSTS_FILE" ]; then
        case "$SERVER_KNOWN_HOSTS_FILE" in
            /*) ;;
            *) SERVER_KNOWN_HOSTS_FILE="$(dirname -- "$CONFIG_FILE")/$SERVER_KNOWN_HOSTS_FILE" ;;
        esac
        [ -r "$SERVER_KNOWN_HOSTS_FILE" ] || die "SERVER_KNOWN_HOSTS_FILE is not readable"
    fi
    if [ -n "$SERVER_PASSWORD_FILE" ]; then
        case "$SERVER_PASSWORD_FILE" in
            /*) ;;
            *) SERVER_PASSWORD_FILE="$(dirname -- "$CONFIG_FILE")/$SERVER_PASSWORD_FILE" ;;
        esac
        [ -r "$SERVER_PASSWORD_FILE" ] || die "SERVER_PASSWORD_FILE is not readable"
    fi
}

prepare_transport() {
    SSH_DEST="$SERVER_USER@$SERVER_HOST"
    # Fail closed on host-key changes. First-time TOFU remains possible only
    # through an explicit, temporary opt-in.
    if [ "${XU_SERVER_ACCEPT_NEW_HOST:-0}" = 1 ]; then
        SSH_COMMON=(-o "ConnectTimeout=$HEALTH_TIMEOUT" -o StrictHostKeyChecking=accept-new)
    elif [ -n "$SERVER_KNOWN_HOSTS_FILE" ]; then
        SSH_COMMON=(-o "ConnectTimeout=$HEALTH_TIMEOUT" -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$SERVER_KNOWN_HOSTS_FILE")
    else
        SSH_COMMON=(-o "ConnectTimeout=$HEALTH_TIMEOUT" -o StrictHostKeyChecking=yes)
    fi
    if [ -n "$SERVER_IDENTITY_FILE" ]; then
        SSH_COMMON+=(-i "$SERVER_IDENTITY_FILE" -o BatchMode=yes)
    elif [ -n "$SERVER_PASSWORD_FILE" ]; then
        command -v sshpass >/dev/null 2>&1 || die "sshpass is required for SERVER_PASSWORD_FILE"
        PASSWORD_TMP=$SERVER_PASSWORD_FILE
    elif [ -n "$SERVER_PASSWORD" ]; then
        command -v sshpass >/dev/null 2>&1 || die "sshpass is required for the legacy password config"
        umask 077
        PASSWORD_TMP=$(mktemp "${TMPDIR:-/tmp}/xu-server-pass.XXXXXX")
        PASSWORD_TMP_OWNED=1
        printf '%s\n' "$SERVER_PASSWORD" > "$PASSWORD_TMP"
    else
        SSH_COMMON+=(-o BatchMode=yes)
    fi
}

remote_ssh() {
    if [ -n "$PASSWORD_TMP" ]; then
        sshpass -f "$PASSWORD_TMP" ssh "${SSH_COMMON[@]}" -p "$SERVER_SSH_PORT" "$SSH_DEST" "$@"
    else
        ssh "${SSH_COMMON[@]}" -p "$SERVER_SSH_PORT" "$SSH_DEST" "$@"
    fi
}

remote_copy() {
    local local_path=$1 remote_path=$2
    if [ -n "$PASSWORD_TMP" ]; then
        sshpass -f "$PASSWORD_TMP" scp "${SSH_COMMON[@]}" -P "$SERVER_SSH_PORT" -- "$local_path" "$SSH_DEST:$remote_path"
    else
        scp "${SSH_COMMON[@]}" -P "$SERVER_SSH_PORT" -- "$local_path" "$SSH_DEST:$remote_path"
    fi
}

local_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        die "sha256sum or shasum is required"
    fi
}

remote_check() {
    remote_ssh bash -s -- "$SERVER_APP_ROOT" "$SERVER_SERVICE" <<'REMOTE'
set -eu
app_root=$1
service=$2
printf 'os='; uname -srm
printf 'arch='; uname -m
[ "$(uname -s)" = Linux ] || { echo 'remote host is not Linux' >&2; exit 1; }
case "$(uname -m)" in x86_64|amd64) ;; *) echo 'remote host is not x86_64' >&2; exit 1 ;; esac
for tool in bash file curl sha256sum systemctl install; do
    command -v "$tool" >/dev/null 2>&1 || { echo "missing remote tool: $tool" >&2; exit 1; }
done
printf 'user='; id -un
printf 'app_root='; if [ -d "$app_root" ]; then echo present; else echo absent; fi
printf 'service='; if systemctl cat "$service" >/dev/null 2>&1; then echo installed; else echo absent; fi
echo 'remote check: OK'
REMOTE
}

remote_health() {
    remote_ssh bash -s -- "$SERVER_HEALTH_URL" "$HEALTH_TIMEOUT" <<'REMOTE'
set -eu
url=$1
timeout=$2
body=$(curl --fail --silent --show-error --max-time "$timeout" --proto '=http' "$url") || {
    echo 'remote health: request failed' >&2
    exit 1
}
[ "$(printf '%s' "$body" | tr -d '\r\n')" = ok ] || {
    echo 'remote health: unexpected response body' >&2
    exit 1
}
echo 'remote health: OK'
REMOTE
}

build_linux_artifact() {
    local -a args=(build-linux --output "$ARTIFACT")
    [ -n "$SOURCE" ] && args+=(--source "$SOURCE")
    [ -n "$COMPILER" ] && args+=(--compiler "$COMPILER")
    [ -n "$OPT_LEVEL" ] && args+=(--opt "$OPT_LEVEL")
    [ "$NO_REGCACHE" = 1 ] && args+=(--no-regcache)
    "$LOCAL_DEPLOY" "${args[@]}"
}

remote_deploy() {
    build_linux_artifact
    [ -f "$ARTIFACT" ] || die "artifact missing after build: $ARTIFACT"
    local checksum release_name incoming
    checksum=$(local_sha256 "$ARTIFACT")
    release_name="xu-server-${checksum:0:16}"
    incoming="$SERVER_APP_ROOT/.incoming-${checksum:0:16}-$$"

    remote_ssh bash -s -- "$SERVER_APP_ROOT" <<'REMOTE'
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'remote deploy requires root (or a dedicated sudo adapter)' >&2; exit 1; }
install -d -m 0755 "$1" "$1/releases"
REMOTE
    remote_copy "$ARTIFACT" "$incoming"

    remote_ssh bash -s -- \
        "$SERVER_APP_ROOT" "$SERVER_SERVICE" "$SERVER_RUNTIME_USER" \
        "$SERVER_HEALTH_URL" "$HEALTH_TIMEOUT" "$checksum" "$incoming" "$release_name" <<'REMOTE'
set -eu
app_root=$1
service=$2
runtime_user=$3
health_url=$4
health_timeout=$5
expected=$6
incoming=$7
release_name=$8
release="$app_root/releases/$release_name"
current="$app_root/current"
previous="$app_root/previous"

[ "$(id -u)" -eq 0 ] || { echo 'remote deploy requires root' >&2; exit 1; }
actual=$(sha256sum "$incoming" | awk '{print $1}')
[ "$actual" = "$expected" ] || { echo 'remote checksum mismatch' >&2; exit 1; }
file "$incoming" | grep -Eq 'ELF 64-bit.*(x86-64|x86_64)' || { echo 'remote artifact is not Linux x86_64 ELF' >&2; exit 1; }

if ! id "$runtime_user" >/dev/null 2>&1; then
    useradd --system --home-dir "$app_root" --shell /usr/sbin/nologin "$runtime_user"
fi
install -d -m 0755 -o root -g root "$app_root" "$app_root/releases"
install -m 0755 -o root -g root "$incoming" "$release"
rm -f -- "$incoming"

old_target=$(readlink "$current" 2>/dev/null || true)
restore_old() {
    trap - ERR
    if [ -n "$old_target" ]; then
        ln -sfn "$old_target" "$current.next"
        mv -Tf "$current.next" "$current"
        systemctl restart "$service" >/dev/null 2>&1 || true
    else
        systemctl stop "$service" >/dev/null 2>&1 || true
        rm -f -- "$current"
    fi
}
trap restore_old ERR
if [ -n "$old_target" ]; then
    ln -sfn "$old_target" "$previous.next"
    mv -Tf "$previous.next" "$previous"
fi
ln -sfn "releases/$release_name" "$current.next"
mv -Tf "$current.next" "$current"

unit_tmp=$(mktemp)
{
    echo '[Unit]'
    echo 'Description=Xu HTTP server'
    echo 'Wants=network-online.target'
    echo 'After=network-online.target'
    echo
    echo '[Service]'
    echo 'Type=simple'
    echo "User=$runtime_user"
    echo "Group=$runtime_user"
    echo "WorkingDirectory=$app_root"
    echo "ExecStart=$current"
    echo 'Restart=on-failure'
    echo 'RestartSec=2s'
    echo 'NoNewPrivileges=true'
    echo 'PrivateTmp=true'
    echo 'PrivateDevices=true'
    echo 'ProtectSystem=strict'
    echo 'ProtectHome=true'
    echo 'ProtectKernelTunables=true'
    echo 'ProtectKernelModules=true'
    echo 'ProtectControlGroups=true'
    echo 'RestrictSUIDSGID=true'
    echo 'LockPersonality=true'
    echo 'MemoryDenyWriteExecute=true'
    echo
    echo '[Install]'
    echo 'WantedBy=multi-user.target'
} > "$unit_tmp"
install -m 0644 -o root -g root "$unit_tmp" "/etc/systemd/system/$service"
rm -f -- "$unit_tmp"
systemctl daemon-reload
systemctl enable "$service" >/dev/null
trap - ERR

if ! systemctl restart "$service"; then
    restore_old
    echo 'remote service restart failed; previous release restored' >&2
    exit 1
fi

healthy=0
i=0
while [ "$i" -lt 20 ]; do
    body=$(curl --fail --silent --max-time "$health_timeout" --proto '=http' "$health_url" 2>/dev/null || true)
    if [ "$(printf '%s' "$body" | tr -d '\r\n')" = ok ]; then
        healthy=1
        break
    fi
    sleep 0.25
    i=$((i + 1))
done
if [ "$healthy" -ne 1 ]; then
    restore_old
    echo 'remote health failed; previous release restored' >&2
    exit 1
fi
echo "remote deploy: active=$release_name sha256=$expected"
REMOTE
}

remote_status() {
    remote_ssh bash -s -- "$SERVER_APP_ROOT" "$SERVER_SERVICE" "$SERVER_HEALTH_URL" "$HEALTH_TIMEOUT" <<'REMOTE'
set -eu
app_root=$1
service=$2
health_url=$3
health_timeout=$4
target=$(readlink "$app_root/current" 2>/dev/null || true)
printf 'current=%s\n' "${target:-none}"
if [ -n "$target" ] && [ -f "$app_root/$target" ]; then
    printf 'sha256='; sha256sum "$app_root/$target" | awk '{print $1}'
fi
printf 'enabled='; systemctl is-enabled "$service" 2>/dev/null || true
printf 'active='; systemctl is-active "$service" 2>/dev/null || true
body=$(curl --fail --silent --max-time "$health_timeout" --proto '=http' "$health_url" 2>/dev/null || true)
if [ "$(printf '%s' "$body" | tr -d '\r\n')" = ok ]; then
    echo 'health=ok'
else
    echo 'health=failed'
    exit 1
fi
REMOTE
}

remote_smoke() {
    remote_ssh bash -s -- "$SERVER_HEALTH_URL" "$HEALTH_TIMEOUT" <<'REMOTE'
set -eu
health_url=$1
timeout=$2
base=${health_url%/health}
i=1
while [ "$i" -le 50 ]; do
    health=$(curl --fail --silent --max-time "$timeout" "$health_url" | tr -d '\r\n')
    hello=$(curl --fail --silent --max-time "$timeout" "$base/hello" | tr -d '\r\n')
    echo_body=$(curl --fail --silent --max-time "$timeout" --request POST --data "xu-$i" "$base/echo" | tr -d '\r\n')
    missing=$(curl --silent --max-time "$timeout" --output /dev/null --write-out '%{http_code}' "$base/missing")
    if [ "$health" != ok ] || [ "$hello" != 'hello, xu' ] || [ "$echo_body" != "xu-$i" ] || [ "$missing" != 404 ]; then
        echo "remote smoke failed at iteration $i" >&2
        exit 1
    fi
    i=$((i + 1))
done
echo 'remote smoke: 50 iterations PASS'
REMOTE
}

remote_service_action() {
    local action=$1
    remote_ssh systemctl "$action" "$SERVER_SERVICE"
}

remote_rollback() {
    remote_ssh bash -s -- "$SERVER_APP_ROOT" "$SERVER_SERVICE" <<'REMOTE'
set -eu
app_root=$1
service=$2
current="$app_root/current"
previous="$app_root/previous"
cur=$(readlink "$current" 2>/dev/null || true)
prev=$(readlink "$previous" 2>/dev/null || true)
[ -n "$cur" ] || { echo 'no current release' >&2; exit 1; }
[ -n "$prev" ] || { echo 'no previous release' >&2; exit 1; }
[ -f "$app_root/$prev" ] || { echo 'previous release is missing' >&2; exit 1; }
ln -sfn "$cur" "$previous.next"
ln -sfn "$prev" "$current.next"
mv -Tf "$previous.next" "$previous"
mv -Tf "$current.next" "$current"
if ! systemctl restart "$service"; then
    ln -sfn "$cur" "$current.next"
    ln -sfn "$prev" "$previous.next"
    mv -Tf "$current.next" "$current"
    mv -Tf "$previous.next" "$previous"
    systemctl restart "$service" >/dev/null 2>&1 || true
    echo 'rollback restart failed; original release restored' >&2
    exit 1
fi
echo "remote rollback: active=$prev"
REMOTE
    remote_health
}

parse_options() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --config) [ "$#" -ge 2 ] || die "--config needs a path"; CONFIG_FILE=$2; shift 2 ;;
            --artifact) [ "$#" -ge 2 ] || die "--artifact needs a path"; ARTIFACT=$2; shift 2 ;;
            --source) [ "$#" -ge 2 ] || die "--source needs a path"; SOURCE=$2; shift 2 ;;
            --compiler) [ "$#" -ge 2 ] || die "--compiler needs a path"; COMPILER=$2; shift 2 ;;
            --opt) [ "$#" -ge 2 ] || die "--opt needs O0, O1, O2, or O3"; OPT_LEVEL=$2; shift 2 ;;
            --no-regcache) NO_REGCACHE=1; shift ;;
            --timeout) [ "$#" -ge 2 ] || die "--timeout needs seconds"; HEALTH_TIMEOUT=$2; shift 2 ;;
            -h|--help) usage; exit 0 ;;
            *) die "unknown option: $1" ;;
        esac
    done
}

main() {
    [ "$#" -ge 1 ] || { usage >&2; exit 2; }
    local command=$1
    shift
    parse_options "$@"
    case "$command" in
        help|-h|--help) usage; exit 0 ;;
    esac
    case "$OPT_LEVEL" in ''|O0|O1|O2|O3) ;; *) die "--opt must be O0, O1, O2, or O3" ;; esac
    case "$NO_REGCACHE" in 0|1) ;; *) die "XU_SERVER_NO_REGCACHE must be 0 or 1" ;; esac
    case "$HEALTH_TIMEOUT" in ''|*[!0-9]*) die "--timeout must be a positive integer" ;; esac
    [ "$HEALTH_TIMEOUT" -gt 0 ] || die "--timeout must be positive"

    case "$ARTIFACT" in /*) ;; *) ARTIFACT="$ROOT_DIR/$ARTIFACT" ;; esac
    load_config
    prepare_transport

    case "$command" in
        check) remote_check ;;
        deploy) remote_deploy ;;
        status) remote_status ;;
        health) remote_health ;;
        smoke) remote_smoke ;;
        restart) remote_service_action restart; remote_health ;;
        stop) remote_service_action stop ;;
        rollback) remote_rollback ;;
        *) usage >&2; die "unknown command: $command" ;;
    esac
}

main "$@"
