#!/usr/bin/env bash
set -euo pipefail

# Run one fixture with a portable wall-clock limit. macOS CI does not ship
# GNU timeout, so use Python (already required by the test suite) and preserve
# the shell convention 128+signal for crashes. Exit 124 means timeout.
run_with_timeout() {
    local seconds="$1"
    shift
    python3 - "$seconds" "$@" <<'PY'
import os
import signal
import subprocess
import sys

seconds = float(sys.argv[1])
command = sys.argv[2:]
p = subprocess.Popen(command, start_new_session=(os.name != "nt"))
try:
    rc = p.wait(timeout=seconds)
except subprocess.TimeoutExpired:
    if os.name != "nt":
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:
        p.kill()
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    raise SystemExit(124)

if rc < 0:
    rc = 128 + (-rc)
raise SystemExit(rc)
PY
}

# Classify a completed fixture run without hiding abnormal exits behind output
# mismatches. A non-zero expected exit remains a valid fixture contract; only a
# difference from expected_exit takes precedence over stdout/stderr comparison.
fixture_runtime_result_kind() {
    local code="$1"
    local expected_exit="$2"
    local expected_stdout="$3"
    local actual_stdout="$4"
    local expected_stderr="${5-}"
    local actual_stderr="${6-}"

    if [ "$code" -eq 124 ]; then
        printf '%s\n' timeout
    elif [ "$code" -ne "$expected_exit" ]; then
        printf '%s\n' exit
    elif ! diff -q "$expected_stdout" "$actual_stdout" >/dev/null; then
        printf '%s\n' stdout
    elif [ -n "$expected_stderr" ] && ! diff -q "$expected_stderr" "$actual_stderr" >/dev/null; then
        printf '%s\n' stderr
    else
        printf '%s\n' pass
    fi
}

start_http_server() {
    local www_dir="$1"
    local port_file="$2"

    # Try to bind to port 0 to get a random free port
    local port
    port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')

    python3 -m http.server "$port" --bind 127.0.0.1 --directory "$www_dir" >/dev/null 2>&1 &
    local pid=$!

    local ready=0
    local i=0
    while [ "$i" -lt 40 ]; do
        if curl -fsS "http://127.0.0.1:$port/rempkg.xu" >/dev/null 2>&1; then
            ready=1
            break
        fi
        i=$((i + 1))
        sleep 0.05
    done

    if [ "$ready" != "1" ]; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        echo "" > "$port_file"
        return 1
    fi

    echo "$port:$pid" > "$port_file"
    return 0
}

stop_http_server() {
    local port_file="$1"
    if [ -f "$port_file" ]; then
        local pid
        pid=$(cut -d: -f2 < "$port_file")
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
        rm -f "$port_file"
    fi
}
