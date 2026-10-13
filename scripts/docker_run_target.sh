#!/usr/bin/env bash
# Shared linux-arm64 / linux-x64 runner for eval harnesses.
# Source this file (do not execute):  . ./scripts/docker_run_target.sh
#
# After compile, call:
#   xu_linux_run TARGET IMAGE WORKDIR HOST_BIN CONTAINER_BIN STDOUT STDERR [args...]
#   TARGET          linux-arm64 | linux-x64
#   IMAGE           docker image (default in callers is postgres:15 / jsbin-wine)
#   WORKDIR         host dir bind-mounted at /w
#   HOST_BIN        host path of the compiled binary (for qemu + `file`)
#   CONTAINER_BIN   path inside the container, e.g. /w/a.out
#   STDOUT / STDERR host files to capture
#
# Sets:
#   XU_LINUX_RUN_STATUS   ran | degraded
#   XU_LINUX_RUN_CODE     program/container exit when status=ran
#   XU_LINUX_RUN_REASON   short token when degraded
#   XU_LINUX_RUN_DEGRADED_TARGETS  accumulated " linux-arm64(no-runner)" notes
# Optional:
#   XU_LINUX_RUN_SSL_CERT_BASENAME  file already present in WORKDIR; when set,
#                                  expose it as SSL_CERT_FILE to qemu/docker.
#
# Policy (runner failure vs program failure):
#   Docker/qemu exit 125 (cannot start), 126 (cannot invoke), or 127 (not found)
#   — or docker itself failing to start the container (daemon down, platform
#   mismatch, exec format error, OCI runtime exec failed) — is NOT a program
#   FAIL. Callers must PASS with "(compile+file only)" after `file` verifies
#   the ELF, and must not treat empty stdout as a fixture mismatch.
#   A binary that actually runs and prints the wrong stdout or exit still FAILs.
#
# linux-arm64 preference:
#   1. qemu-aarch64 / qemu-aarch64-static if present
#   2. docker run --pull=never --platform linux/arm64 with IMAGE
#   3. already-local linux/arm64 images (inspect only; never pull)
#   4. degrade

xu_docker_ok() { docker image inspect "$1" >/dev/null 2>&1; }

xu_linux_elf_ok() {
    local target=$1 bin=$2
    case "$target" in
        linux-arm64) file "$bin" | grep -q "ELF 64-bit LSB executable, ARM aarch64" ;;
        linux-x64)   file "$bin" | grep -q "ELF 64-bit LSB executable, x86-64" ;;
        *) return 1 ;;
    esac
}

xu_is_runner_exit() {
    case "$1" in
        125|126|127) return 0 ;;
    esac
    return 1
}

xu_stderr_is_docker_failure() {
    local f=$1
    [ -s "$f" ] || return 1
    grep -qiE \
        'Cannot connect to the Docker daemon|Is the docker daemon running|unable to find image|no matching manifest|does not match the specified platform|exec format error|OCI runtime (exec|create) failed|Error response from daemon|failed to create shim|image operating system|permission denied while trying to connect|unknown flag|Cannot start container|error creating container' \
        "$f"
}

XU_LINUX_RUN_STATUS=degraded
XU_LINUX_RUN_CODE=0
XU_LINUX_RUN_REASON=""
XU_LINUX_RUN_VIA=""
XU_LINUX_RUN_DEGRADED_TARGETS="${XU_LINUX_RUN_DEGRADED_TARGETS:-}"

xu_linux_run_mark_degraded() {
    local target=$1 reason=$2
    XU_LINUX_RUN_STATUS=degraded
    XU_LINUX_RUN_CODE=0
    XU_LINUX_RUN_REASON=$reason
    case " $XU_LINUX_RUN_DEGRADED_TARGETS " in
        *" ${target}(no-runner)"*) ;;
        *) XU_LINUX_RUN_DEGRADED_TARGETS="$XU_LINUX_RUN_DEGRADED_TARGETS ${target}(no-runner)" ;;
    esac
}

xu_linux_run() {
    local target=$1 image=$2 workdir=$3 host_bin=$4 cbin=$5 stdoutf=$6 stderrf=$7
    shift 7
    XU_LINUX_RUN_STATUS=degraded
    XU_LINUX_RUN_CODE=0
    XU_LINUX_RUN_REASON=no-runner
    XU_LINUX_RUN_VIA=""
    : >"$stdoutf"
    : >"$stderrf"

    local platform=linux/amd64 qcode
    local ssl_cert_basename="${XU_LINUX_RUN_SSL_CERT_BASENAME:-}"
    [ "$target" = "linux-arm64" ] && platform=linux/arm64

    # Optional user-mode qemu: runs the ELF directly, no docker --platform.
    if [ "$target" = "linux-arm64" ]; then
        local qemu=""
        if command -v qemu-aarch64 >/dev/null 2>&1; then
            qemu=qemu-aarch64
        elif command -v qemu-aarch64-static >/dev/null 2>&1; then
            qemu=qemu-aarch64-static
        fi
        if [ -n "$qemu" ]; then
            # Callers run with `set -e`; a non-zero program status (for
            # example exit_builtin's expected 42) is test data, not a shell
            # failure.  Capture it inside a conditional before classifying
            # runner-vs-program exits below.
            if [ -n "$ssl_cert_basename" ]; then
                if SSL_CERT_FILE="$workdir/$ssl_cert_basename" "$qemu" "$host_bin" "$@" >"$stdoutf" 2>"$stderrf"; then
                    qcode=0
                else
                    qcode=$?
                fi
            else
                if "$qemu" "$host_bin" "$@" >"$stdoutf" 2>"$stderrf"; then
                    qcode=0
                else
                    qcode=$?
                fi
            fi
            if ! xu_is_runner_exit "$qcode"; then
                XU_LINUX_RUN_STATUS=ran
                XU_LINUX_RUN_CODE=$qcode
                XU_LINUX_RUN_REASON=""
                XU_LINUX_RUN_VIA=$qemu
                return 0
            fi
            : >"$stdoutf"
            : >"$stderrf"
        fi
    fi

    local candidates="$image"
    if [ "$target" = "linux-arm64" ]; then
        # Already-local native arm64 runners (static binaries need nothing from
        # the image). Inspect only — never docker pull.
        candidates="$image hello-world:latest alpine:latest ubuntu:22.04 arm64v8/ubuntu:22.04"
    fi

    local img arch code tried=""
    for img in $candidates; do
        case " $tried " in
            *" $img "*) continue ;;
        esac
        tried="$tried $img"
        xu_docker_ok "$img" || continue
        arch=$(docker image inspect "$img" --format '{{.Architecture}}' 2>/dev/null || true)
        if [ "$img" != "$image" ]; then
            case "$arch" in
                arm64|aarch64) [ "$platform" = "linux/arm64" ] || continue ;;
                amd64|x86_64)  [ "$platform" = "linux/amd64" ] || continue ;;
                *) continue ;;
            esac
        fi
        if [ -n "$ssl_cert_basename" ]; then
            if docker run --rm --pull=never --platform "$platform" \
                -e "SSL_CERT_FILE=/w/$ssl_cert_basename" \
                -v "$workdir":/w -w /w --entrypoint "$cbin" "$img" "$@" \
                >"$stdoutf" 2>"$stderrf"; then
                code=0
            else
                code=$?
            fi
        else
            if docker run --rm --pull=never --platform "$platform" \
                -v "$workdir":/w -w /w --entrypoint "$cbin" "$img" "$@" \
                >"$stdoutf" 2>"$stderrf"; then
                code=0
            else
                code=$?
            fi
        fi
        if xu_is_runner_exit "$code" || xu_stderr_is_docker_failure "$stderrf"; then
            : >"$stdoutf"
            : >"$stderrf"
            continue
        fi
        XU_LINUX_RUN_STATUS=ran
        XU_LINUX_RUN_CODE=$code
        XU_LINUX_RUN_REASON=""
        XU_LINUX_RUN_VIA="docker:$img"
        return 0
    done

    xu_linux_run_mark_degraded "$target" "docker-runner-unavailable"
    return 0
}
