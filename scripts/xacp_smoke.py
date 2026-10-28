#!/usr/bin/env python3
"""Product XACP discovery/launcher regression; no external service required."""
import os
import select
import socket
import time
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()
TOOL = XU.with_name("xu-xacp" + XU.suffix)


def run(args, code=0):
    p = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True,
                       text=True, timeout=180)
    assert p.returncode == code, (args, p.returncode, p.stdout, p.stderr)
    return p.stdout


with tempfile.TemporaryDirectory(prefix="xu-xacp-smoke-") as tmp:
    core = Path(tmp) / ("core.exe" if os.name == "nt" else "core")
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build",
         "examples/xacp/core/main.xu", "-o", core])
    assert "XACP core: PASS" in run([core])
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
        return f"--- !xacp\nid: !i {i}\nop: {op}\nargs: {args}\n===\n"

    requests = frame(1, "xacp.hello", "\n  ver: !ver 1.0.0")
    ops = [("proc.status", "{}"), ("proc.output", "\n  stream: stdout"),
           ("ui.tree", "{}"), ("ui.screenshot", "\n  win: !i 1"),
           ("ui.input", "\n  win: !i 1\n  steps: []"),
           ("ui.act", "\n  win: !i 1\n  node: !i 1\n  act: click"),
           ("ui.record", "\n  win: !i 1\n  mode: events")]
    for i, (op, args) in enumerate(ops, 2):
        requests += frame(i, op, args)
    requests += frame(9, "proc.status")
    for prefix in ([app, "--xacp-stdio"], [app, "--xacp-stdio", "--xacp-tcp"],
                   [TOOL, "control", app],
                   [XU, "xacp", "control", app]):
        p = subprocess.run([str(x) for x in prefix], input=requests,
                           capture_output=True, text=True, timeout=30)
        assert p.returncode == 0, (p.stdout, p.stderr)
        assert p.stdout.count("--- !xacp\n") == 9, p.stdout
        for i, response in enumerate(p.stdout.split("--- !xacp\n")[1:], 1):
            assert response.startswith(f"id: !i {i}\n"), response
            assert response.endswith("===\n"), response
        assert p.stdout.count("ok: !b true") == 3, p.stdout
        assert p.stdout.count("code: not_implemented") == 6, p.stdout
        assert "permissions: development" in p.stdout
        assert "business-main" not in p.stdout
    p = subprocess.run([str(app), "--xacp-stdio"],
                       input=frame(1, "proc.status") + "broken\n===\n" + requests,
                       capture_output=True, text=True, timeout=30)
    assert "code: permission_denied" in p.stdout, p.stdout
    assert "code: frame_error" in p.stdout, p.stdout
    assert "permissions: development" in p.stdout, p.stdout
    if os.name != "nt":
        # Read each response while stdin remains open, and fragment writes so
        # framing cannot depend on pipe read boundaries or waiting for EOF.
        child = subprocess.Popen([str(app), "--xacp-stdio"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        try:
            for request in (frame(1, "xacp.hello", "\n  ver: !ver 1.0.0"),
                            frame(2, "proc.status"), frame(3, "ui.tree"),
                            frame(4, "ui.act", "\n  win: !i 1\n  node: !i 1\n  act: click")):
                data = request.encode()
                for start in range(0, len(data), 5):
                    child.stdin.write(data[start:start + 5])
                    child.stdin.flush()
                response = b""
                deadline = time.monotonic() + 5
                while not response.endswith(b"\n===\n"):
                    ready, _, _ = select.select([child.stdout], [], [],
                                                max(0, deadline - time.monotonic()))
                    assert ready, "control response stalled with stdin open"
                    chunk = os.read(child.stdout.fileno(), 4096)
                    assert chunk, response
                    response += chunk
                assert response.startswith(b"--- !xacp\n"), response
            child.stdin.close()
            assert child.wait(timeout=5) == 0
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()
            child.stderr.close()
    for ending in ("", "\r", "\r\n"):
        hello = frame(1, "xacp.hello", "\n  ver: !ver 1.0.0").rstrip("\n") + ending
        p = subprocess.run([str(app), "--xacp-stdio"], input=hello,
                           capture_output=True, text=True, timeout=30)
        assert p.returncode == 0 and "ok: !b true" in p.stdout, (p.stdout, p.stderr)
    # Framing limits, EOF, request ids and schema failures must stay bounded.
    for payload, expected, status in [
        ("--- !xacp\nid:", "truncated_frame", 0),
        ("x" * 1048577, "frame_too_large", 1),
        (frame(1, "unknown"), "schema_error", 0),
        (frame(2, "xacp.hello", "\n  ver: !ver 1.0.0"), "invalid_request_id", 0),
        (frame(1, "xacp.hello", "\n  ver: !ver 1.0.0") +
         frame(1, "proc.status"), "invalid_request_id", 0),
    ]:
        p = subprocess.run([str(app), "--xacp-stdio"], input=payload,
                           capture_output=True, text=True, timeout=30)
        assert p.returncode == status, (p.stdout, p.stderr)
        assert "code: " + expected in p.stdout, p.stdout
    assert "arg: --xacp-stdio" in run([TOOL, "run", app, "--", "--xacp-stdio"])
    assert "business-main" in run([app, "ordinary", "--xacp-help-suffix"])
    assert "capabilities: stdio" in run([app, "ordinary", "--xacp-help"])
    # Explicit TCP mode leaves ordinary business runs and stdio unchanged.
    server = subprocess.Popen([str(app), "--xacp-tcp"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                peer = socket.create_connection(("127.0.0.1", port), timeout=1)
                peer.close()
                break
            except OSError:
                assert server.poll() is None, server.communicate()
                assert time.monotonic() < deadline, "TCP listener did not start"
                time.sleep(0.02)
        for prefix in ([TOOL], [XU, "xacp"]):
            p = subprocess.run([str(x) for x in [*prefix, "connect", port]],
                               input=requests, capture_output=True, text=True, timeout=15)
            assert p.returncode == 0, (p.stdout, p.stderr)
            assert p.stdout.count("--- !xacp\n") == 9, p.stdout
            assert p.stdout.count("ok: !b true") == 3, p.stdout
            assert p.stdout.count("code: not_implemented") == 6, p.stdout
            assert "permissions: development" in p.stdout
            assert f"pid: !i {server.pid}" in p.stdout
            assert "business-main" not in p.stdout
        # Responses must arrive before the client closes its write side.
        with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
            for request in (frame(1, "xacp.hello", "\n  ver: !ver 1.0.0"),
                            frame(2, "proc.status"), frame(3, "ui.tree")):
                data = request.encode()
                for start in range(0, len(data), 5):
                    peer.sendall(data[start:start + 5])
                response = b""
                while not response.endswith(b"\n===\n"):
                    chunk = peer.recv(4096)
                    assert chunk, response
                    response += chunk
                assert response.startswith(b"--- !xacp\n"), response
        run([TOOL, "connect", "0"], code=1)
        run([TOOL, "connect", "65536"], code=1)
        # Fresh connections cannot inherit development permissions; fragment
        # hello and pipeline remaining frames independently of socket reads.
        with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
            payload = (frame(1, "proc.status") + "broken\n===\n" + requests).encode()
            for start in range(0, len(payload), 5):
                peer.sendall(payload[start:start + 5])
            peer.shutdown(socket.SHUT_WR)
            response = b""
            while True:
                chunk = peer.recv(4096)
                if not chunk:
                    break
                response += chunk
            assert b"code: permission_denied" in response, response
            assert b"code: frame_error" in response, response
            assert b"permissions: development" in response, response
        for payload, expected in [(b"incomplete", b"truncated_frame"),
                                  (b"x" * 1048577, b"frame_too_large")]:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
                peer.sendall(payload)
                peer.shutdown(socket.SHUT_WR)
                response = b""
                while not response.endswith(b"\n===\n"):
                    chunk = peer.recv(4096)
                    assert chunk, response
                    response += chunk
                assert expected in response, response
        assert server.poll() is None
    finally:
        server.terminate()
        output, errors = server.communicate(timeout=5)
        assert not output, output
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
print("XACP smoke: PASS")
