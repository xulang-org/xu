#!/usr/bin/env python3
"""Product XACP discovery/launcher regression; no external service required."""
import os
import json
import select
import socket
import time
from pathlib import Path
import subprocess
import tempfile

from xacp_cross_protocol_probe import probe, wait_listener
from xacp_screen_marshal_smoke import Attached, checked, run_screen_smoke
from xacp_screen_marshal_smoke import frame as screen_frame, hello as screen_hello
from xacp_frame import encode, split, read_frame, fd_reader

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()
TOOL = XU.with_name("xu-xacp" + XU.suffix)
BASE_ENV = os.environ.copy()
BASE_ENV.pop("XU_XACP_TOKEN", None)
BASE_ENV.pop("XU_XACP_REQUEST_TIMEOUT_MS", None)


def run(args, code=0, env=BASE_ENV):
    p = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True,
                       text=True, timeout=180, env=env)
    assert p.returncode == code, (args, p.returncode, p.stdout, p.stderr)
    return p.stdout


with tempfile.TemporaryDirectory(prefix="xu-xacp-smoke-") as tmp:
    core = Path(tmp) / ("core.exe" if os.name == "nt" else "core")
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build",
         "examples/xacp/core/main.xu", "-o", core])
    assert "XACP core: PASS" in run([core])
    # Parse boundaries, ASCII-only syntax and overflow without waiting 5s each.
    for value, expected in (("", 5000), ("abc", 5000), ("0", 5000), ("-5", 5000),
                            ("+3", 5000), (" 3", 5000), ("3\n", 5000), ("３", 5000),
                            ("600001", 5000), ("9" * 100, 5000), ("1", 1),
                            ("600000", 600000), ("000300", 300)):
        env = dict(BASE_ENV, XU_XACP_REQUEST_TIMEOUT_MS=value, XACP_EXPECT_TIMEOUT_MS=str(expected))
        assert "XACP core: PASS" in run([core], env=env), (value, expected)
    app = Path(tmp) / ("app.exe" if os.name == "nt" else "app")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build", f"--xacp-port={port}",
         "examples/xacp/main.xu", "-o", app])
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp-port=65536",
         "examples/xacp/main.xu", "-o", app], code=1)
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp", "--target", "wasm32",
         "examples/xacp/main.xu", "-o", Path(tmp) / "app.wasm"], code=1)
    assert "record" in run([TOOL, "--help"])
    assert "record" in run([XU, "help", "xacp"])
    for prefix in ([TOOL], [XU, "xacp"]):
        help_text = run([*prefix, "inspect", app])
        assert "capabilities: stdio" in help_text
        assert f"default_port: {port}" in help_text
        assert "tcp: enabled" in help_text
        assert f"bind: 127.0.0.1:{port}" in help_text
        assert "business-main" not in help_text
        assert "XU_XACP_REQUEST_TIMEOUT_MS" in help_text and "default 5000 ms" in help_text
        for mode in ("run", "debug"):
            out = run([*prefix, mode, app, "--", "--xacp-help", "hello world", ""])
            assert "business-main\narg: --\narg: --xacp-help\narg: hello world\narg: \n" in out
            assert out.count("capabilities: stdio") == (mode == "debug")
        run([*prefix, "run", app, "unprotected"], code=1)
        run([*prefix, "inspect", app, "ignored"], code=1)
        run([*prefix, "inspect", Path(tmp) / "missing"], code=1)
        if os.name != "nt":
            assert "arg: --xacp-help" in run([*prefix, "record", app, "--", "--xacp-help"])
    def frame(i, op, args="{}"):
        return encode(f"id: !i {i}\nop: {op}\nargs: {args}\n")

    LEGACY = b"--- !xacp\nid: !i 1\nop: proc.status\nargs: {}\n===\n"

    def nframes(out):
        return len(split(out))

    def hello(token=None, permissions=None, nonce="smoke-nonce", i=1):
        args = f"\n  ver: !ver 1.0.0\n  nonce: {nonce}"
        if token is not None:
            args += f"\n  token: {token}"
        if permissions is not None:
            args += f"\n  permissions: !i {permissions}"
        return frame(i, "xacp.hello", args)

    def environment(token=""):
        return dict(BASE_ENV, XU_XACP_TOKEN=token)

    def stdio(payload, token="", prefix=None, code=0):
        p = subprocess.run([str(x) for x in (prefix or [app, "--xacp-stdio"])],
                           input=payload, capture_output=True, timeout=30,
                           env=environment(token))
        assert p.returncode == code, (p.returncode, p.stdout, p.stderr)
        assert not p.stderr, p.stderr
        out = p.stdout.decode()
        assert "business-main" not in out
        return out

    def granted(response, permissions, nonce="smoke-nonce"):
        assert "ok: !b true" in response and "state: OPEN" in response, response
        assert f"permissions: !i {permissions}\n" in response, response
        assert f"nonce: {json.dumps(nonce, ensure_ascii=False)}\n" in response, response
        label = {0: "none", 1: "info", 15: "development"}.get(permissions, "custom")
        assert f"permission_label: {label}\n" in response, response

    ops = [("proc.status", "{}"), ("proc.output", "\n  stream: stdout"),
           ("ui.tree", "{}"), ("ui.screenshot", "\n  win: !i 1"),
           ("ui.input", "\n  win: !i 1\n  steps: []"),
           ("ui.act", "\n  win: !i 1\n  node: !i 1\n  act: click"),
           ("ui.record", "\n  win: !i 1\n  mode: events")]

    def requests(token=""):
        payload = hello(token=token or None)
        next_id = 2
        for op, args in ops:
            payload += frame(next_id, op, args)
            # Existing lifecycle: permission denial does not reserve an id.
            if token or op == "proc.status":
                next_id += 1
        return payload + frame(next_id, "proc.status")

    def checked_responses(response, token=""):
        assert nframes(response) == 9, response
        assert response.count("ok: !b true") == 3, response
        expected_ids = list(range(1, 10)) if token else [1, 2] + [3] * 7
        for request_id, part in zip(expected_ids, split(response)):
            assert part.startswith(f"id: !i {request_id}\n"), part
        error = "not_implemented" if token else "permission_denied"
        assert response.count("code: " + error) == 6, response
        granted(response, 15 if token else 1)
        assert "business-main" not in response

    prefixes = ([app, "--xacp-stdio"], [app, "--xacp-stdio", "--xacp-tcp"],
                [TOOL, "control", app], [XU, "xacp", "control", app])
    for token in ("", "smoke-host-token"):
        for prefix in prefixes:
            checked_responses(stdio(requests(token), token, prefix), token)

    # Negotiation is an intersection; client-supplied tokens cannot self-grant.
    for token in ("", "smoke-host-token"):
        for permissions in range(16):
            payload = hello(token="smoke-host-token", permissions=permissions)
            granted(stdio(payload, token), permissions if token else permissions & 1)
    granted(stdio(hello(token="ignored", permissions=15)), 1)
    granted(stdio(hello(), ""), 1)
    granted(stdio(hello(token="smoke-host-token"), "smoke-host-token"), 15)
    # XUN encoding must preserve quoting and prevent nonce response injection.
    for nonce in ('quote" and \\ slash', ' leading: value ',
                  'line\n===\ntrailer\r\t', '|\n|\n', "123", "!s tagged", "会话 nonce", "n" * 65536):
        response = stdio(hello(nonce=json.dumps(nonce, ensure_ascii=False)))
        # Body may contain a literal \n===\n: length prefix keeps it one frame.
        assert nframes(response) == 1, response
        granted(response, 1, nonce)

    # Lifecycle errors after OPEN do not close the connection.
    recovery = (hello() + frame(1, "proc.status") + frame(2, "xacp.hello", "\n  ver: !ver 1.0.0\n  nonce: repeat") +
                frame(2, "ui.tree") + frame(2, "proc.status"))
    out = stdio(recovery)
    assert out.count("ok: !b true") == 2 and out.count("code: permission_denied") == 2, out
    assert "code: invalid_request_id" in out, out
    # Business error: echoes request id, stable code and bounded msg.
    assert 'id: !i 1\nok: !b false\nerror:\n  code: invalid_request_id\n  msg: "request id is not monotonic"\n' in split(out), out
    out = stdio(frame(5, "proc.status"))
    assert split(out) == ['id: !i 5\nok: !b false\nerror:\n  code: hello_required\n  msg: "first request must be xacp.hello"\n'], out
    out = stdio(frame(4, "unknown"))
    assert split(out)[0].startswith("id: !i 4\nok: !b false\nerror:\n  code: schema_error\n  msg: "), out
    # Literal envelope bytes inside a body round-trip as data, not framing.
    out = stdio(hello(nonce=json.dumps("a\n===\n--- !xacp\nid: !i 9\n===\nx", ensure_ascii=False)) + frame(2, "proc.status"))
    assert nframes(out) == 2 and "pid: !i " in out, out

    fatal = [
        (b"broken\n===\n", "frame_error", ""),
        (LEGACY, "frame_error", ""),
        (b"XACP/1\n0\n", "frame_error", ""),
        (b"XACP/1\n-3\nabc", "frame_error", ""),
        (b"XACP/2\n3\nabc", "frame_error", ""),
        (frame(1, "unknown"), "schema_error", ""),
        (frame(1, "proc.status"), "hello_required", ""),
        (frame(1, "xacp.hello", "\n  ver: !ver 1.0.0"), "schema_error", ""),
        (hello(nonce='""'), "schema_error", ""),
        (hello(nonce="!i 3"), "schema_error", ""),
        (hello(nonce="n" * 65537), "schema_error", ""),
        (hello(permissions=-1), "schema_error", ""),
        (hello(permissions=16), "schema_error", ""),
        (frame(1, "xacp.hello", "\n  ver: !ver 1.0.0\n  permissions: 3\n  nonce: smoke-nonce"), "schema_error", ""),
        (hello(permissions="bad"), "frame_error", ""),
        (hello(token="wrong"), "auth_failed", "smoke-host-token"),
        (hello(token='""'), "auth_failed", "smoke-host-token"),
        (hello(), "auth_failed", "smoke-host-token"),
    ]
    for payload, error, token in fatal:
        # A second valid hello in the same read must never be processed.
        out = stdio(payload + hello(token=token or None), token)
        assert nframes(out) == 1 and f"code: {error}\n" in out, (error, out)
        assert "state: OPEN" not in out, out
    for payload, error, token in fatal[:2]:
        # Fatal errors after OPEN close too; the following status must not run.
        out = stdio(hello() + payload + frame(2, "proc.status"))
        assert nframes(out) == 2 and f"code: {error}\n" in out, (error, out)
        assert "pid:" not in out, out
    assert "code: frame_error" in stdio(LEGACY)
    assert "code: truncated_frame" in stdio(b"XACP/1\n40\nid:")
    assert "code: truncated_frame" in stdio(b"XACP/1\n4")
    assert "code: frame_too_large" in stdio(b"XACP/1\n1048577\n" + b"x" * 64, code=1)
    # Existing invalid-id errors remain recoverable even before hello succeeds.
    out = stdio(hello(i=2) + hello())
    assert "code: invalid_request_id" in out
    granted(out, 1)
    # Exercise the checked-in control fixture with default INFO permissions.
    out = stdio((ROOT / "examples/xacp/control.xun").read_bytes())
    assert out.count("code: permission_denied") == 2, out

    if os.name != "nt":
        # Keep stdin open: response/termination must not wait for EOF.
        child = subprocess.Popen([str(app), "--xacp-stdio"], env=BASE_ENV,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        try:
            for request in (hello(), frame(2, "proc.status"), frame(3, "ui.tree"),
                            frame(3, "proc.status"), LEGACY):
                data = request
                for start in range(0, len(data), 5):
                    child.stdin.write(data[start:start + 5])
                    child.stdin.flush()
                response = read_frame(fd_reader(child.stdout.fileno()))
                assert response.startswith("id: !i "), response
            assert "code: frame_error" in response
            assert child.wait(timeout=5) == 0
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()
            child.stderr.close()

    assert "arg: --xacp-stdio" in run([TOOL, "run", app, "--", "--xacp-stdio"])
    assert "business-main" in run([app, "ordinary", "--xacp-help-suffix"])
    assert "capabilities: stdio" in run([app, "ordinary", "--xacp-help"])

    def tcp(payload, eof=False):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
            peer.sendall(payload)
            if eof:
                peer.shutdown(socket.SHUT_WR)
            response = b""
            while True:
                try:
                    chunk = peer.recv(4096)
                except ConnectionResetError:
                    break
                if not chunk:
                    break
                response += chunk
                assert len(response) <= 1048576
            return response.decode()

    for token in ("", "smoke-host-token"):
        server = subprocess.Popen([str(app), "--xacp-tcp"], env=environment(token),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            wait_listener(server, port)
            for prefix in ([TOOL], [XU, "xacp"]):
                p = subprocess.run([str(x) for x in [*prefix, "connect", port]],
                                   input=requests(token), capture_output=True,
                                   timeout=15, env=BASE_ENV)
                assert p.returncode == 0, (p.stdout, p.stderr)
                checked_responses(p.stdout.decode(), token)
                assert f"pid: !i {server.pid}" in p.stdout.decode()
            # Fragmented TCP writes must return responses before write-side EOF.
            with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
                for request in (hello(token=token or None), frame(2, "proc.status"),
                                frame(3, "ui.tree")):
                    data = request
                    for start in range(0, len(data), 5):
                        peer.sendall(data[start:start + 5])
                    response = read_frame(peer.recv)
                    assert response.startswith("id: !i "), response
            for payload, error, configured in fatal:
                if configured != token:
                    continue
                out = tcp(payload + hello(token=token or None))
                assert nframes(out) == 1 and f"code: {error}\n" in out, (error, out)
                assert "state: OPEN" not in out, out
            for payload, error in [(b"XACP/1\n99\nincomplete", "truncated_frame"),
                                   (b"XACP/1\n1048577\n" + b"x" * 64, "frame_too_large"),
                                   (LEGACY, "frame_error")]:
                out = tcp(payload, eof=error == "truncated_frame")
                assert nframes(out) == 1 and f"code: {error}\n" in out, (error, out)
            probe(port, token)
            # Both permission and fatal errors remain local to their own peer.
            checked_responses(tcp(requests(token), eof=True), token)
            assert server.poll() is None
        finally:
            server.terminate()
            output, errors = server.communicate(timeout=5)
            assert not output and not errors, (output, errors)
    run([TOOL, "connect", "0"], code=1)
    run([TOOL, "connect", "65536"], code=1)
    disabled = Path(tmp) / ("disabled.exe" if os.name == "nt" else "disabled")
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp-port", "0",
         "examples/xacp/main.xu", "-o", disabled])
    assert "tcp: disabled" in run([disabled, "--xacp-help"])
    run([disabled, "--xacp-tcp"], code=1)
    assert "business-main" in run([disabled])
    # Exit status and record budget are tested with executable local peers.
    if os.name != "nt":
        peer = Path(tmp) / "peer"
        peer.write_text("#!/bin/sh\nexit 7\n")
        peer.chmod(0o755)
        for mode in ("run", "record"):
            run([TOOL, mode, peer], code=7)
        peer.write_text("#!/bin/sh\nhead -c 1048576 /dev/zero\n")
        p = subprocess.run([str(TOOL), "record", str(peer)], capture_output=True, timeout=30)
        assert p.returncode == 0 and len(p.stdout) == 1048576
        peer.write_text("#!/bin/sh\nhead -c 1100000 /dev/zero\n")
        p = subprocess.run([str(TOOL), "record", str(peer)], capture_output=True, timeout=30)
        assert p.returncode != 0 and len(p.stdout) <= 1048576
        assert b"exceeded 1 MiB" in p.stderr
def timeout_checks():
    if os.name == "nt":
        print("XACP request timeout smoke: SKIP (POSIX pipe readiness required by this harness)")
        return
    with tempfile.TemporaryDirectory(prefix="xu-xacp-timeout-") as tmp:
        app = Path(tmp) / "attach"
        run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp",
             "examples/xacp/attach/main.xu", "-o", app])
        for launcher in (None, TOOL):
            peer = Attached(app, launcher, timeout_ms="300", no_poll=True)
            try:
                peer.request(screen_hello(), 1)
                for i in (2, 4):
                    started = time.monotonic()
                    response = peer.request(screen_frame(i, "ui.tree"), i, "request_timeout")
                    elapsed = time.monotonic() - started
                    assert 0.25 <= elapsed < 2, elapsed
                    assert 'msg: "request exceeded 300 ms"' in response, response
                    assert "state: OPEN" in peer.request(screen_frame(i + 1, "proc.status"), i + 1)
                # EOF checks that no extra response was emitted for an expired id.
                peer.finish()
            finally:
                peer.stop()
        # Slow regression: invalid env must actually use the default deadline.
        peer = Attached(app, timeout_ms="abc", no_poll=True)
        try:
            peer.request(screen_hello(), 1)
            started = time.monotonic()
            response = peer.request(screen_frame(2, "ui.tree"), 2, "request_timeout")
            elapsed = time.monotonic() - started
            assert 4.5 <= elapsed < 7, elapsed
            assert 'msg: "request exceeded 5000 ms"' in response, response
            peer.request(screen_frame(3, "proc.status"), 3)
            peer.finish()
        finally:
            peer.stop()
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        server = Attached(app, port=port, timeout_ms="300", no_poll=True)
        try:
            wait_listener(server.child, port)
            # Expiry keeps this peer OPEN, and leaves no job for the next peer.
            for _ in range(2):
                with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                    sock.sendall(screen_hello())
                    checked(read_frame(sock.recv), 1)
                    for i, op, args in ((2, "ui.tree", "{}"),
                                        (4, "ui.screenshot", "\n  win: !i 1"),
                                        (6, "ui.act", "\n  win: !i 1\n  node: !i 2\n  act: click"),
                                        (8, "ui.input", "\n  win: !i 1\n  steps: []"),
                                        (10, "ui.record", "\n  win: !i 1\n  mode: events")):
                        started = time.monotonic()
                        sock.sendall(screen_frame(i, op, args))
                        checked(read_frame(sock.recv), i, "request_timeout")
                        assert 0.25 <= time.monotonic() - started < 2
                        sock.sendall(screen_frame(i + 1, "proc.status"))
                        checked(read_frame(sock.recv), i + 1)
            assert server.child.poll() is None
        finally:
            server.stop()
    print("XACP request timeout smoke: PASS")


timeout_checks()
run_screen_smoke(XU, TOOL)
print("XACP smoke: PASS")
