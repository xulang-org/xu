#!/usr/bin/env python3
"""Reject HTTP text/plain POSTs containing an embedded XACP hello on loopback."""
import argparse
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time

from companion_repos import project_root
from xacp_frame import encode, split

ROOT = Path(__file__).resolve().parents[1]


def probe(port, token=""):
    # Even a correct token in the smuggled hello must not rescue a bad envelope.
    auth = f"  token: {token}\n" if token else ""
    body = b"browser-body\n" + encode("id: !i 1\nop: xacp.hello\nargs:\n"
            "  ver: !ver 1.0.0\n  nonce: post-probe\n  permissions: !i 15\n"
            f"{auth}")
    request = (f"POST / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
               "Content-Type: text/plain\r\nOrigin: http://probe.invalid\r\n"
               f"Content-Length: {len(body)}\r\n\r\n").encode() + body
    with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
        peer.sendall(request)
        response = b""
        while True:
            try:
                chunk = peer.recv(4096)
            except ConnectionResetError:
                # A peer may reset after replying while unread POST bytes remain.
                break
            if not chunk:
                break
            response += chunk
            assert len(response) <= 65536, "POST probe response exceeded bound"
    assert len(split(response)) == 1, response
    assert b"code: frame_error\n" in response, response
    assert b"ok: !b true" not in response, response
    assert b"state: OPEN" not in response, response
    assert b"permissions: !i 15" not in response, response
    print(f"XACP POST probe ({'token configured' if token else 'INFO default'}): PASS")


def wait_listener(server, port):
    deadline = time.monotonic() + 5
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            assert server.poll() is None, "TCP listener exited"
            assert time.monotonic() < deadline, "TCP listener did not start"
            time.sleep(0.02)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, help="existing XACP executable")
    parser.add_argument("--port", type=int, help="port compiled into --app")
    parser.add_argument("--xu", type=Path,
                        default=Path(os.environ.get("XU", ROOT / "bin/xu")))
    args = parser.parse_args()
    if args.app and (args.port is None or not 1 <= args.port <= 65535):
        parser.error("--app requires --port in 1..65535")
    with tempfile.TemporaryDirectory(prefix="xu-xacp-post-") as tmp:
        app, port = args.app, args.port
        if app is None:
            with socket.socket() as reserve:
                reserve.bind(("127.0.0.1", 0))
                port = reserve.getsockname()[1]
            app = Path(tmp) / ("app.exe" if os.name == "nt" else "app")
            subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"),
                            str(args.xu.resolve()), "build", f"--xacp-port={port}",
                            str(project_root("examples") / "examples/xacp/main.xu"), "-o", str(app)],
                           cwd=ROOT, check=True, timeout=180)
        for token in ("", secrets.token_hex(24)):
            env = os.environ.copy()
            env["XU_XACP_TOKEN"] = token
            server = subprocess.Popen([str(app.resolve()), "--xacp-tcp"], env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                wait_listener(server, port)
                probe(port, token)
                # Bad HTTP affects only its own peer, not the listener.
                with socket.create_connection(("127.0.0.1", port), timeout=5):
                    pass
                assert server.poll() is None
            finally:
                server.terminate()
                output, errors = server.communicate(timeout=5)
                assert not output, output
                assert not errors, errors


if __name__ == "__main__":
    main()
