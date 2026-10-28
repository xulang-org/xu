#!/usr/bin/env python3
"""Retained Screen + side control integration; all I/O waits have deadlines."""
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import tempfile
import time

from xacp_cross_protocol_probe import probe, wait_listener
from xacp_frame import encode, fd_reader, read_frame

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "screen-smoke-token"


def frame(i, op, args="{}"):
    return encode(f"id: !i {i}\nop: {op}\nargs: {args}\n")


LEGACY = b"--- !xacp\nid: !i 1\nop: proc.status\nargs: {}\n===\n"


def hello(token=TOKEN, permissions=None, nonce="screen-nonce"):
    args = f"\n  ver: !ver 1.0.0\n  nonce: {nonce}"
    if token:
        args += f"\n  token: {token}"
    if permissions is not None:
        args += f"\n  permissions: !i {permissions}"
    return frame(1, "xacp.hello", args)


def read_until(fd, suffix, timeout=10):
    data = b""
    deadline = time.monotonic() + timeout
    while not data.endswith(suffix):
        ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        assert ready, ("attached control stalled", data)
        chunk = os.read(fd.fileno(), 4096)
        assert chunk, ("unexpected EOF", data)
        data += chunk
        assert len(data) <= 1048576, "response exceeds frame budget"
    return data.decode()


def checked(response, i, error=None):
    assert response.startswith(f"id: !i {i}\n"), response
    assert not response.startswith("--- !xacp"), response
    if error:
        assert "ok: !b false\n" in response and f"code: {error}\n" in response, response
        # Every error the transport can describe carries a bounded msg.
        assert "\n  msg: " in response, response
    else:
        assert "ok: !b true\n" in response and "\ndata:\n" in response, response
    return response


class Attached:
    def __init__(self, app, tool=None, mode="", token=TOKEN, port=None,
                 timeout_ms="", no_poll=False, hello_timeout_ms="", idle_timeout_ms="", env_overrides=None):
        env = dict(os.environ, XU_UI_SIM="1", XU_XACP_TOKEN=token,
                   XU_XACP_REQUEST_TIMEOUT_MS=timeout_ms,
                   XU_XACP_HELLO_TIMEOUT_MS=hello_timeout_ms,
                   XU_XACP_IDLE_TIMEOUT_MS=idle_timeout_ms,
                   XU_XACP_NONCE_CACHE="", XU_XACP_NONCE_REPLAY="", XU_XACP_ALLOW_RAW="",
                   XACP_EXAMPLE_NO_POLL="1" if no_poll else "0",
                   XACP_EXAMPLE_LIFECYCLE=mode, XACP_EXAMPLE_TCP=str(port) if port else "")
        env.update(env_overrides or {})
        command = [str(app)] if tool is None else [str(tool), "attach", str(app)]
        self.child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.port = port
        try:
            # No control input has been sent: main must run while stdin is open.
            ready = read_until(self.child.stderr, b"business-main: Screen ready\n")
            assert ready == "business-main: Screen ready\n", ready
            assert self.child.poll() is None
        except BaseException:
            self.stop()
            raise

    def request(self, payload, i, error=None):
        self.child.stdin.write(payload)
        self.child.stdin.flush()
        return checked(read_frame(fd_reader(self.child.stdout.fileno(), 10)), i, error)

    def finish(self):
        self.child.stdin.close()
        self.child.wait(timeout=10)
        assert self.child.returncode == 0, self.child.returncode
        assert self.child.stdout.read() == b""
        assert self.child.stderr.read() == b"business-main: control finished\n"
        self.stop()

    def stop(self):
        if self.child.poll() is None:
            self.child.terminate()
            self.child.wait(timeout=5)
        for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
            if stream and not stream.closed:
                stream.close()


def stdio_checks(app, tool):
    for launcher in (None, tool):
        peer = Attached(app, launcher)
        try:
            response = peer.request(hello(), 1)
            assert "permissions: !i 15\n" in response
            response = peer.request(frame(2, "ui.tree"), 2)
            for field in ('text: "business-main: attached Screen"', 'text: "Control button"',
                          "win: !i 1\n", "x: !f 12\n", "y: !f 24\n", "width: !f 320\n"):
                assert field in response, (field, response)
            assert response.count("    - id: !i ") == 3, response
            for field in ("start: !i 0\n", "count: !i 3\n", "total: !i 3\n",
                          "truncated: !b false\n", "next_start: !i 3\n"):
                assert "  " + field in response, response
            changed = '真实节点 "quote" \\ slash\n===\ntrailer\r\t'
            args = '\n  win: !i 1\n  node: !i 1\n  act: set_text\n  text: ' + json.dumps(changed, ensure_ascii=False)
            assert "actions: []" in peer.request(frame(3, "ui.act", args), 3)
            response = peer.request(frame(4, "ui.tree"), 4)
            assert "text: " + json.dumps(changed, ensure_ascii=False) + "\n" in response, response
            response = peer.request(frame(5, "ui.act", "\n  win: !i 1\n  node: !i 2\n  act: click"), 5)
            assert "actions:\n" in response and "kind: !i 1\n" in response, response
            assert "actions: []" in peer.request(frame(6, "ui.input", "\n  win: !i 1\n  steps: []"), 6)
            # The simulation has no native raster backend. Both a serialized
            # real success and a stable adapter error must produce a full frame.
            peer.child.stdin.write(frame(7, "ui.screenshot", "\n  win: !i 1"))
            peer.child.stdin.flush()
            screenshot = read_frame(fd_reader(peer.child.stdout.fileno(), 10))
            if "ok: !b true\n" in screenshot:
                checked(screenshot, 7)
                assert "pixel_width: !i " in screenshot and "pixel_height: !i " in screenshot
            else:
                checked(screenshot, 7, "adapter_error")
            peer.request(frame(8, "ui.tree", "\n  win: !i 2"), 8, "stale_window")
            first = peer.request(frame(9, "ui.tree", "\n  max_table_rows: !i 1\n  start: !i 0"), 9)
            for field in ("start: !i 0\n", "count: !i 1\n", "total: !i 3\n",
                          "truncated: !b true\n", "next_start: !i 1\n", "  - id: !i 1\n"):
                assert "  " + field in first, first
            assert first.count("    - id: !i ") == 1, first
            next_start = int(next(line.removeprefix("  next_start: !i ")
                                  for line in first.splitlines() if line.startswith("  next_start: !i ")))
            second = peer.request(frame(10, "ui.tree", f"\n  max_table_rows: !i 1\n  start: !i {next_start}"), 10)
            for field in ("start: !i 1\n", "count: !i 1\n", "total: !i 3\n",
                          "truncated: !b true\n", "next_start: !i 2\n", "  - id: !i 2\n"):
                assert "  " + field in second, second
            assert second.count("    - id: !i ") == 1, second
            assert next(line for line in first.splitlines() if line.startswith("  generation:")) == next(
                line for line in second.splitlines() if line.startswith("  generation:"))
            empty = peer.request(frame(11, "ui.tree", "\n  start: !i 3\n  max_table_rows: !i 1"), 11)
            for field in ("start: !i 3\n", "count: !i 0\n", "total: !i 3\n",
                          "truncated: !b false\n", "next_start: !i 3\n", "nodes: []\n"):
                assert "  " + field in empty, empty
            peer.request(frame(12, "ui.tree", "\n  start: !i 4"), 12, "adapter_error")
            peer.request(frame(13, "ui.act", "\n  win: !i 1\n  node: !i 99\n  act: click"), 13, "adapter_error")
            # A valid session limit above the widget node cap is still legal.
            peer.request(frame(14, "ui.tree", "\n  max_table_rows: !i 10000"), 14)
            response = peer.request(frame(15, "proc.status"), 15)
            if launcher is None:
                assert f"pid: !i {peer.child.pid}\n" in response, response
            peer.finish()
        finally:
            peer.stop()

    for token, permissions in (("", None), (TOKEN, 5)):
        peer = Attached(app, token=token)
        try:
            peer.request(hello(token, permissions), 1)
            if token:
                peer.request(frame(2, "ui.act", "\n  win: !i 1\n  node: !i 2\n  act: click"), 2, "permission_denied")
                peer.request(frame(2, "ui.tree"), 2)
            else:
                peer.request(frame(2, "ui.tree"), 2, "permission_denied")
                peer.request(frame(2, "proc.status"), 2)
            peer.finish()
        finally:
            peer.stop()

    for mode in ("unregistered", "unregister", "close", "dispose", "reregister",
                 "pending-unregister", "pending-dispose"):
        peer = Attached(app, mode=mode)
        try:
            peer.request(hello(), 1)
            if mode == "unregistered":
                peer.request(frame(2, "ui.tree"), 2, "not_implemented")
            elif mode.startswith("pending-"):
                peer.request(frame(2, "ui.tree"), 2, "stale_window")
                peer.request(frame(3, "ui.tree"), 3, "not_implemented")
            else:
                peer.request(frame(2, "ui.tree"), 2)
                error = {"unregister": "not_implemented", "close": "stale_window",
                         "dispose": "stale_window", "reregister": None}[mode]
                peer.request(frame(3, "ui.tree"), 3, error)
                if mode in ("close", "dispose"):
                    peer.request(frame(4, "ui.tree"), 4, "not_implemented")
            peer.finish()
        finally:
            peer.stop()

    # Schema failures close the control session and echo the parsed id.
    for args in ("\n  start: !i -1", "\n  start: !b true",
                 "\n  max_table_rows: !i 0", "\n  max_table_rows: !i -1",
                 "\n  max_table_rows: !i 10001"):
        peer = Attached(app)
        try:
            peer.request(hello(), 1)
            peer.request(frame(2, "ui.tree", args), 2, "schema_error")
            peer.finish()
        finally:
            peer.stop()

    # Fatal session errors must terminate attach control without killing main
    # prematurely or dispatching a later request from the same input chunk.
    for payload, error, request_id in (
        (frame(1, "ui.tree"), "hello_required", 1),
        (hello("wrong-token"), "auth_failed", 1),
        (b"broken\n===\n" + hello(), "frame_error", 0),
        (LEGACY + hello(), "frame_error", 0),
        (frame(1, "xacp.hello", "{}"), "schema_error", 1),  # id parsed -> echoed
    ):
        peer = Attached(app)
        try:
            peer.request(payload, request_id, error)
            peer.finish()
        finally:
            peer.stop()


def tcp_checks(app):
    for token in ("", TOKEN):
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        server = Attached(app, token=token, port=port)
        try:
            wait_listener(server.child, port)
            probe(port, token)
            for index in range(2):
                with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                    for payload, i, error in ((hello(token, nonce=f"screen-peer-{index}"), 1, None),
                                              (frame(2, "ui.tree"), 2, None if token else "permission_denied")):
                        data = payload
                        for start in range(0, len(data), 5):
                            sock.sendall(data[start:start + 5])
                        response = read_frame(sock.recv)
                        checked(response, i, error)
                        if i == 2 and token:
                            assert 'text: "business-main: attached Screen"' in response
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                sock.sendall(hello(token, nonce="screen-peer-0") + frame(2, "proc.status"))
                checked(read_frame(sock.recv), 1, "nonce_replay")
                try:
                    assert sock.recv(1) == b"", "replayed hello did not close attached peer"
                except ConnectionResetError:
                    pass
            assert server.child.poll() is None
        finally:
            server.stop()


def run_screen_smoke(xu, tool):
    if os.name == "nt":
        print("XACP Screen marshal smoke: SKIP (POSIX pipe readiness required by this harness)")
        return
    with tempfile.TemporaryDirectory(prefix="xu-xacp-screen-") as tmp:
        app = Path(tmp) / "attach"
        result = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), str(xu),
                                 "build", "--xacp", "examples/xacp/attach/main.xu", "-o", str(app)],
                                cwd=ROOT, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, (result.stdout, result.stderr)
        stdio_checks(app, tool)
        tcp_checks(app)
    print("XACP Screen marshal smoke: PASS")


if __name__ == "__main__":
    xu = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()
    run_screen_smoke(xu, xu.with_name("xu-xacp" + xu.suffix))
