#!/usr/bin/env python3
"""Loopback HTTP deadline/resource gate, using an independent host socket server.

Run: python3 tests/test_http_client_deadline.py --xu bin/xu --out /tmp/http.json
The daemon observes EOF while the Xu process is still alive, so an error
cannot pass this gate merely because process exit closes a leaked descriptor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import socket
import socketserver
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests/drivers/http_client_deadline.xu"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(self, case):
        super().__init__(("127.0.0.1", 0), Handler)
        self.case = case
        self.lock = threading.Lock()
        self.requests = []
        self.peers_closed = threading.Event()
        self.connections = 0
        self.stop = threading.Event()


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        s = self.server
        with s.lock:
            s.connections += 1
            identity = s.connections
        self.request.settimeout(3)
        try:
            if s.case == "tls-handshake":
                self.request.recv(4096)
                self.observe_close()
                return
            while True:
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = self.request.recv(65536)
                    if not chunk:
                        return
                    data += chunk
                method, path, _ = data.split(b"\r\n", 1)[0].decode().split(" ")
                with s.lock:
                    s.requests.append((identity, method, path))
                if s.case == "write":
                    # Deliberately stop draining a large request body.
                    self.observe_close(drain=False)
                    return
                if path == "/warm":
                    self.send(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nwarm")
                    if s.case in {"stale", "post-stale"}:
                        return
                    continue
                if s.case in {"headers", "drip-headers"}:
                    if s.case == "drip-headers":
                        for char in b"HTTP/1.1 200 OK\r\n":
                            self.send(bytes([char]))
                            if s.stop.wait(.025):
                                return
                    self.observe_close()
                    return
                if s.case in {"body", "chunked"}:
                    if s.case == "body":
                        self.send(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nx")
                        for _ in range(3):
                            if s.stop.wait(.045):
                                return
                            self.send(b"x")
                    else:
                        self.send(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
                        for _ in range(5):
                            self.send(b"1\r\nx\r\n")
                            if s.stop.wait(.04):
                                return
                    self.observe_close()
                    return
                if s.case in {"redirect", "redirect-success"}:
                    if s.stop.wait(.065):
                        return
                    hop = int(path[1:] or "0")
                    if hop < 3:
                        self.send(f"HTTP/1.1 302 Found\r\nLocation: /{hop + 1}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
                    else:
                        self.send(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
                    self.observe_close()
                    return
                if s.case == "malformed":
                    self.send(b"INVALID 200 OK\r\nContent-Length: 0\r\n\r\n")
                    self.observe_close()
                    return
                if s.case == "reuse" and s.stop.wait(.18):
                    return
                self.send(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
                self.observe_close()
                return
        except (OSError, ValueError):
            # Peer reset/closed is observable cleanup too.
            s.peers_closed.set()

    def send(self, data):
        self.request.sendall(data)

    def observe_close(self, drain=True):
        if not drain:
            # SO_SNDTIMEO handles write blockage; cleanup is checked by the
            # other cases, since draining here would invalidate that test.
            self.server.stop.wait(3)
            return
        while self.request.recv(65536):
            pass
        self.server.peers_closed.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xu", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--modes", default="-O0,-O3")
    args = parser.parse_args()
    compiler = args.xu.resolve()
    report = {"compiler": str(compiler), "compiler_sha256": digest(compiler),
              "host": platform.platform(), "driver_sha256": digest(DRIVER),
              "harness_sha256": digest(__file__), "source_sha256": {
                  str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "src").rglob("*.xu"))},
              "results": []}
    cases = [("success", 100_000_000, "get"), ("unbounded", 0, "get"),
             ("headers", 100_000_000, "get"), ("drip-headers", 100_000_000, "get"),
             ("body", 100_000_000, "get"), ("chunked", 100_000_000, "get"),
             ("redirect", 150_000_000, "get"), ("redirect-success", 400_000_000, "get"),
             ("tls-handshake", 100_000_000, "get"),
             ("reuse", 100_000_000, "reuse"), ("stale", 400_000_000, "stale"),
             ("post-stale", 400_000_000, "post-stale"), ("malformed", 400_000_000, "get"),
             ("write", 500_000_000, "write")]
    failures = []
    with tempfile.TemporaryDirectory(prefix="xu-http-deadline-") as tmp:
        for mode in args.modes.split(","):
            binary = Path(tmp) / "driver.xin"
            compiled = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), str(compiler),
                            "build", str(DRIVER), mode, "-o", str(binary)],
                           cwd=ROOT, timeout=120, capture_output=True, text=True)
            if compiled.returncode:
                raise SystemExit(compiled.stdout + compiled.stderr)
            for case, ns, action in cases:
                with Server(case) as server:
                    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
                    thread.start()
                    scheme = "https" if case == "tls-handshake" else "http"
                    url = f"{scheme}://127.0.0.1:{server.server_address[1]}"
                    started = time.monotonic()
                    proc = subprocess.Popen([str(binary), url, str(ns), action], stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, text=True)
                    closed_while_alive = False
                    # Poll EOF until the process exits, with a bounded test deadline.
                    while proc.poll() is None and time.monotonic() - started < 3:
                        if server.peers_closed.wait(.005):
                            closed_while_alive = proc.poll() is None
                            break
                    try:
                        out, err = proc.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        out, err = proc.communicate()
                    elapsed = time.monotonic() - started
                    lines = out.splitlines()
                    ok = proc.returncode == 0 and closed_while_alive
                    if case in {"headers", "drip-headers", "body", "chunked", "redirect", "tls-handshake"}:
                        ok = ok and lines == ["error:net/http: request timeout", "idle:false"] and elapsed < .8
                    elif case == "write":
                        ok = proc.returncode == 0 and lines == ["error:net/http: request timeout", "idle:false"]
                        ok = ok and len(server.requests) == 1 and elapsed < 1.3
                    elif case == "malformed":
                        ok = ok and lines == ["error:net/http: bad status line", "idle:false"]
                    elif case == "post-stale":
                        ok = proc.returncode == 0 and any(x.startswith("error:") for x in lines)
                        ok = ok and lines[-1:] == ["idle:false"] and len(server.requests) == 1
                    elif case in {"reuse", "stale"}:
                        ok = ok and lines == ["ok:200:warm", "ok:200:ok"]
                        ok = ok and len(server.requests) == 2
                        expected_connections = 1 if case == "reuse" else 2
                        ok = ok and server.connections == expected_connections
                    elif case == "redirect-success":
                        ok = ok and lines == ["ok:200:ok"] and len(server.requests) == 4
                    else:
                        ok = ok and lines == ["ok:200:ok"]
                    entry = dict(mode=mode, case=case, pass_=ok, stdout=out, stderr=err,
                                 elapsed_seconds=round(elapsed, 4), peer_closed_before_exit=closed_while_alive,
                                 requests=server.requests, connections=server.connections)
                    report["results"].append(entry)
                    print(f"{'PASS' if ok else 'FAIL'} {mode} {case} {elapsed:.3f}s", flush=True)
                    if not ok:
                        failures.append(entry)
                        print(out + err, flush=True)
                    server.stop.set()
                    server.shutdown()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if failures:
        raise SystemExit(f"{len(failures)} HTTP deadline cases failed")


if __name__ == "__main__":
    main()
