#!/usr/bin/env python3
"""Run Windows trust-store, socket readiness/error and execution-manifest regressions."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import subprocess
import threading

from test_windows_workers import WindowsTemporaryDirectory


CERTIFICATES = '''@main
#crypto/x509
fn main() int {
    blob := sys_security_store("ROOT") or (err) { << 1 }
    mut offset := 0
    mut entries := 0
    while offset < blob.len {
        if offset + 4 > blob.len { << 2 }
        size := (blob[offset] & 255) | ((blob[offset + 1] & 255) << 8) | ((blob[offset + 2] & 255) << 16) | ((blob[offset + 3] & 255) << 24)
        offset += 4
        if size <= 0 || size > blob.len - offset { << 3 }
        offset += size
        entries += 1
    }
    pool := x509.system_cert_pool() or (err) { << 4 }
    if entries > 0 && pool.certs.len == 0 { << 5 }
    println("certificate entries=" + str(entries) + " parsed=" + str(pool.certs.len))
    << 0
}
'''

SOCKET_ERRORS = '''@main
#net
#os
fn write_rejected(fd int) bool {
    text := "probe"
    _ := net.conn_write(fd, &text) or (err) { << true }
    << false
}
fn read_rejected(fd int) bool {
    _ := net.conn_read(fd, 8) or (err) { << true }
    << false
}
fn main() int {
    fd := net.dial(os.getenv("XU_TEST_ENDPOINT")) or (err) { << 1 }
    net.conn_close(fd) or (err) { << 2 }
    if !write_rejected(fd) { << 3 }
    if !read_rejected(fd) { << 4 }
    println("closed socket read/write errors preserved")
    << 0
}
'''


SOCKET_READINESS = '''@main
#os
#net
fn probe() int {
 fd := net.dial(os.getenv("XU_TEST_ENDPOINT")) or >>
 mut i := 0
 while i < 4 {
  writable := os.socket_wait(fd,2,1000000000) or >>
  if (writable & 2) == 0 { << 1 }
  i += 1
 }
 timeout := os.socket_wait(fd,1,1000000) or >>
 if timeout != 0 { << 2 }
 request := "R"
 _ := net.conn_write(fd,&request) or >>
 readable := os.socket_wait(fd,1,5000000000) or >>
 if (readable & 1) == 0 { << 3 }
 data := net.conn_read(fd,5) or >>
 if data != "hello" { << 4 }
 ack := "A"
 _ := net.conn_write(fd,&ack) or >>
 ended := os.socket_wait(fd,1,5000000000) or >>
 if (ended & 8) == 0 || (ended & 4) != 0 { << 5 }
 net.conn_close(fd) or >>
 println("socket readiness: repeat, timeout, non-consuming read, hangup passed")
 << 0
}
fn main() int { << probe() or (err) { eprintln(err.msg())
 << 99 } }
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--target", choices=("windows-arm64", "windows-x64"), required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("requires Windows")
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, XU_ROOT=str(root), XU_STDLIB_ROOT=str(root / "src"), XUPATH="")
    compiler = args.compiler.resolve()
    with WindowsTemporaryDirectory(prefix="xu windows runtime ") as folder:
        work = Path(folder)

        def build(name: str, source: str) -> Path:
            path = work / (name + ".xu")
            path.write_text(source, encoding="utf-8")
            exe = work / (name + ".exe")
            subprocess.run([str(compiler), "build", str(path), "--target", args.target, "-o", str(exe)], env=env, check=True, timeout=180)
            return exe

        def execute(exe: Path) -> None:
            subprocess.run([str(exe)], env=env, check=True, timeout=30)

        execute(build("certificates", CERTIFICATES))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            env["XU_TEST_ENDPOINT"] = "127.0.0.1:" + str(listener.getsockname()[1])
            execute(build("socket-errors", SOCKET_ERRORS))
        readiness = build("socket-readiness", SOCKET_READINESS)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(20)
            env["XU_TEST_ENDPOINT"] = "127.0.0.1:" + str(listener.getsockname()[1])
            failures = []

            def serve():
                try:
                    with listener.accept()[0] as peer:
                        peer.settimeout(15)
                        assert peer.recv(1) == b"R"
                        peer.sendall(b"hello")
                        assert peer.recv(1) == b"A"
                except Exception as exc:
                    failures.append(exc)

            server = threading.Thread(target=serve, daemon=True)
            server.start()
            try:
                execute(readiness)
            finally:
                server.join(21)
            if failures:
                raise failures[0]
            if server.is_alive():
                raise RuntimeError("readiness server did not finish")
        # These names trigger Windows installer detection without an explicit
        # requestedExecutionLevel resource. No elevation or installation occurs.
        for name in ("probe-setup", "probe-update"):
            execute(build(name, '@main\nfn main() int { println("asInvoker")\n << 0 }\n'))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
