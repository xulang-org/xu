#!/usr/bin/env python3
"""XACP per-frame write deadlines; --stdio-only selects sandbox-safe checks.

The default also requires TCP. Socket EPERM is an explicit failure, never a pass.
Windows pipe/console stdio deadlines are best-effort, so only settings and TCP
checks apply there. All generated fixtures use the hosted product compiler.
"""
import argparse
import errno
import threading
import os
from pathlib import Path
import select
import socket
import subprocess
import tempfile
import time

from xacp_frame import MAGIC, encode, fd_reader, read_frame

ROOT = Path(__file__).resolve().parents[1]
WRITE_MS = 300
DIAGNOSTIC = f"xacp: write timed out after {WRITE_MS} ms".encode()
FIXTURE = '''@main
#xacp

fn main() int {
    limits := xacp.default_limits()
    println(limits.write_timeout_ms)
    println(xacp.write_timeout_from_env())
    << 0
}
'''


def hello(nonce="write-smoke"):
    return encode("id: !i 1\nop: xacp.hello\nargs:\n  ver: !ver 1.0.0\n"
                  f'  nonce: {nonce}\n')


# A 64 KiB decoded nonce expands to over 128 KiB on the wire. This leaves
# enough pending output for the partial-progress check even with a 64 KiB pipe.
# Use the supported tab escape (XUN quoted strings do not decode \xHH).
LARGE_HELLO = hello('"' + r"\t" * 65536 + '"')
STATUS = encode("id: !i 2\nop: proc.status\nargs: {}\n")


def environment(**overrides):
    env = dict(os.environ, XU_XACP_TOKEN="", XU_XACP_ALLOW_RAW="",
               XU_XACP_REQUEST_TIMEOUT_MS="", XU_XACP_HELLO_TIMEOUT_MS="3000",
               XU_XACP_IDLE_TIMEOUT_MS="0", XU_XACP_WRITE_TIMEOUT_MS=str(WRITE_MS),
               XU_XACP_NONCE_CACHE="", XU_XACP_NONCE_REPLAY="0")
    env.update(overrides)
    return env


def stop(child):
    if child.poll() is None:
        child.kill()
        child.wait(timeout=5)
    for stream in (child.stdin, child.stdout, child.stderr):
        if stream and not stream.closed:
            stream.close()


def launch(app, **overrides):
    return subprocess.Popen([str(app), "--xacp-stdio"], cwd=ROOT,
                            env=environment(**overrides), bufsize=0,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)


def send_pipe(child, payload):
    """Bound test input too: a broken implementation must not hang the harness."""
    fd = child.stdin.fileno()
    os.set_blocking(fd, False)
    deadline = time.monotonic() + 3
    offset = 0
    while offset < len(payload):
        _, ready, _ = select.select([], [fd], [], max(0, deadline - time.monotonic()))
        assert ready, "request input stalled"
        try:
            offset += os.write(fd, payload[offset:offset + 4096])
        except BlockingIOError:
            pass


def settings_checks(app):
    cases = [(None, 10000), ("", 10000), ("0", 10000), ("1", 1),
             ("600000", 600000), ("600001", 10000), ("000300", 300)]
    cases += [(v, 10000) for v in ("abc", "-1", "+300", " 300", "300 ",
                                  "300\n", "３００", "9" * 100)]
    for value, expected in cases:
        env = environment()
        if value is None:
            env.pop("XU_XACP_WRITE_TIMEOUT_MS")
        else:
            env["XU_XACP_WRITE_TIMEOUT_MS"] = value
        result = subprocess.run([str(app)], cwd=ROOT, env=env, capture_output=True, timeout=5)
        assert result.returncode == 0 and not result.stderr, result
        assert result.stdout == f"10000\n{expected}\n".encode(), (value, result.stdout)
    print("XACP write timeout settings: PASS", flush=True)


def blocked_stdio(app, drip=False):
    child = launch(app)
    try:
        send_pipe(child, LARGE_HELLO)
        started = time.monotonic()
        prefix = b""
        if drip:
            # Progress every 50 ms continues for longer than the frame budget.
            # A per-write renewed timer would leave this process running.
            deadline = started + 0.8
            while child.poll() is None and time.monotonic() < deadline:
                ready, _, _ = select.select([child.stdout], [], [], 0.05)
                if ready:
                    prefix += os.read(child.stdout.fileno(), 4096)
                time.sleep(0.05)
        code = child.wait(timeout=max(0.01, 4.5 - (time.monotonic() - started)))
        elapsed = time.monotonic() - started
        assert code != 0 and 0.2 <= elapsed < 5, (code, elapsed)
        errors = child.stderr.read()
        assert DIAGNOSTIC in errors, errors
        # Only inspect stdout after exit: the unread variant never drains it
        # during the frame write. No error/second frame may follow a partial one.
        output = prefix + child.stdout.read()
        assert output.startswith(MAGIC) and output.count(MAGIC) == 1, output[:100]
        header, length, body = output.split(b"\n", 2)
        assert 0 < len(body) < int(length) and int(length) > 65536, (length, len(body))
        print(f"XACP stdio {'partial progress' if drip else 'unread response'}: "
              f"PASS ({elapsed:.3f}s)", flush=True)
    finally:
        stop(child)


def readable_stdio(app):
    child = launch(app, XU_XACP_WRITE_TIMEOUT_MS="150", XU_XACP_HELLO_TIMEOUT_MS="1500",
                   XU_XACP_IDLE_TIMEOUT_MS="1000")
    try:
        # Read-side waits outlast the write budget without a write timeout.
        time.sleep(0.3)
        send_pipe(child, LARGE_HELLO)
        response = read_frame(fd_reader(child.stdout.fileno(), 5))
        assert "ok: !b true\n" in response and len(response) > 65536
        time.sleep(0.3)
        send_pipe(child, STATUS)
        response = read_frame(fd_reader(child.stdout.fileno(), 5))
        assert "id: !i 2\nok: !b true\n" in response, response
        child.stdin.close()
        assert child.wait(timeout=5) == 0
        assert child.stdout.read() == b"" and child.stderr.read() == b""
        print("XACP draining large response and independent read waits: PASS", flush=True)
    finally:
        stop(child)


def fill_pipe(fd):
    os.set_blocking(fd, False)
    count = 0
    try:
        while True:
            count += os.write(fd, b"p" * 4096)
    except BlockingIOError:
        pass
    os.set_blocking(fd, True)
    return count


def blocked_fatal(app, idle=False):
    # Keep the write end to fill the pipe while the server is waiting for input.
    # No competing writer runs while the server attempts its fatal response.
    read_fd, write_fd = os.pipe()
    child = None
    try:
        child = subprocess.Popen([str(app), "--xacp-stdio"], cwd=ROOT,
                                 env=environment(XU_XACP_HELLO_TIMEOUT_MS="200",
                                                 XU_XACP_IDLE_TIMEOUT_MS="1000"),
                                 bufsize=0, stdin=subprocess.PIPE, stdout=write_fd,
                                 stderr=subprocess.PIPE)
        if idle:
            send_pipe(child, hello())
            assert "ok: !b true\n" in read_frame(fd_reader(read_fd, 3))
        filled = fill_pipe(write_fd)
        started = time.monotonic()
        assert child.wait(timeout=4.5) != 0
        elapsed = time.monotonic() - started
        assert elapsed < 5 and DIAGNOSTIC in child.stderr.read()
        # The failed fatal response did not append bytes or a second frame.
        os.close(write_fd)
        write_fd = -1
        output = b""
        while True:
            chunk = os.read(read_fd, 65536)
            if not chunk:
                break
            output += chunk
        assert output == b"p" * filled
        print(f"XACP blocked {'idle' if idle else 'hello'} fatal response: PASS", flush=True)
    finally:
        if child:
            stop(child)
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def tcp_checks(app, port):
    server = subprocess.Popen([str(app), "--xacp-tcp"], cwd=ROOT, env=environment(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    peer = None
    errors = bytearray()
    diagnosed = threading.Event()

    def collect_errors():
        while True:
            line = server.stderr.readline()
            if not line:
                return
            errors.extend(line)
            if DIAGNOSTIC in errors:
                diagnosed.set()

    reader = threading.Thread(target=collect_errors, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 4
        while True:
            try:
                peer = socket.socket()
                # Set before connect so the advertised receive window stays
                # small; many status replies fill even large server send buffers.
                peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                peer.settimeout(1)
                peer.connect(("127.0.0.1", port))
                break
            except OSError as err:
                if peer:
                    peer.close()
                if err.errno in (errno.EPERM, errno.EACCES):
                    raise RuntimeError("TCP unavailable: EPERM/EACCES (test FAILED)") from err
                assert server.poll() is None, ("TCP server exited", server.stderr.read())
                assert time.monotonic() < deadline, "TCP listener did not start"
                time.sleep(0.02)
        peer.sendall(LARGE_HELLO)
        peer.setblocking(False)
        # Do not recv from this peer. Duplicate id errors are recoverable and
        # produce responses larger than their requests, amplifying backpressure.
        pending = STATUS * 4096
        offset = 0
        started = time.monotonic()
        while time.monotonic() - started < 4:
            if diagnosed.is_set():
                break
            try:
                sent = peer.send(pending[offset:])
                offset = (offset + sent) % len(pending)
            except BlockingIOError:
                time.sleep(0.001)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                break
        # Probe a second peer before closing the first: closing the blocked
        # client must not be what releases the sequential server.
        with socket.create_connection(("127.0.0.1", port), timeout=1) as recovered:
            recovered.settimeout(1)
            recovered.sendall(hello("recovered"))
            result = read_frame(recovered.recv)
            assert "ok: !b true\n" in result, result
        assert server.poll() is None and time.monotonic() - started < 5
        server.terminate()
        server.wait(timeout=5)
        reader.join(timeout=1)
        assert not reader.is_alive(), "stderr collector did not stop"
        out = server.stdout.read()
        assert not out and DIAGNOSTIC in errors, (out, errors)
        print("XACP TCP unread peer and listener recovery: PASS", flush=True)
    finally:
        if peer:
            peer.close()
        if server.poll() is None:
            server.kill()
            server.wait(timeout=5)
        reader.join(timeout=1)
        stop(server)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio-only", action="store_true",
                        help="explicitly omit TCP checks (e.g. sandbox EPERM)")
    args = parser.parse_args()
    # Fail explicitly before building fixtures when the required TCP capability
    # is unavailable. Sandbox users select --stdio-only rather than a false pass.
    port = None
    if not args.stdio_only:
        try:
            with socket.socket() as reserve:
                reserve.bind(("127.0.0.1", 0))
                port = reserve.getsockname()[1]
        except OSError as err:
            if err.errno in (errno.EPERM, errno.EACCES):
                raise RuntimeError("TCP unavailable: EPERM/EACCES (test FAILED)") from err
            raise
    xu = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()
    with tempfile.TemporaryDirectory(prefix="xu-xacp-write-") as directory:
        directory = Path(directory)
        source = directory / "main.xu"
        source.write_text(FIXTURE, encoding="utf-8")
        app = directory / ("app.exe" if os.name == "nt" else "app")
        subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), str(xu),
                        "build", "--xacp" if port is None else f"--xacp-port={port}",
                        str(source), "-o", str(app)],
                       cwd=ROOT, check=True, timeout=180)
        settings_checks(app)
        if os.name == "nt":
            print("XACP stdio blocking checks: SKIP (Windows stdio is best-effort)", flush=True)
        else:
            blocked_stdio(app)
            blocked_stdio(app, drip=True)
            readable_stdio(app)
            blocked_fatal(app)
            blocked_fatal(app, idle=True)
        if args.stdio_only:
            print("XACP TCP checks: NOT RUN (--stdio-only)", flush=True)
        else:
            tcp_checks(app, port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
