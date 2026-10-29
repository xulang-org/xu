#!/usr/bin/env python3
"""Run Windows socket-readiness and concurrent HTTP regressions with product Xu."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import subprocess

from test_windows_workers import WindowsTemporaryDirectory


SOURCE = r'''@main
#errors
#net
#net/http
#os
#strings

fn close_quiet(fd int) {
    net.conn_close(fd) or (err) { << }
}

fn exchange(fd int) int {
    request := "GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
    mut sent := 0
    while sent < request.len {
        part := request[sent:request.len]
        n := net.conn_write(fd, &part) or >>
        if n <= 0 || n > part.len { >> errors.new("request write made invalid progress") }
        sent += n
    }
    mut response := ""
    while response.len < 8192 {
        part := net.conn_read(fd, 1024) or >>
        if part.len == 0 { >> errors.new("response ended before body") }
        response = response + part
        if strings.index_of(&response, "\r\n\r\nok") >= 0 { << 1 }
    }
    >> errors.new("response exceeded limit")
}

fn request(addr string) int {
    fd := net.dial_ns(addr, 2000000000) or >>
    os.set_sock_timeout(fd, 2000000000) or (err) {
        close_quiet(fd)
        >> err
    }
    result := exchange(fd) or (err) {
        close_quiet(fd)
        >> err
    }
    net.conn_close(fd) or >>
    << result
}

fn handler(c http.Context) {
    c.text(200, "ok") or (err) { eprintln(err.msg())
        << }
}

fn serve(lfd int) {
    status := http.serve_listener(lfd, handler) or (err) { eprintln(err.msg())
        << }
    if status != 0 { eprintln("HTTP server stopped") }
}

fn worker(addr string, out chan int) {
    mut count := 0
    for i in 0:3 {
        count += request(addr + "") or (err) { eprintln(err.msg())
            out <- -1
            << }
    }
    out <- count
}

fn invalid_socket_rejected() bool {
    _ := os.socket_poll(0, 1) or (err) { << true }
    << false
}

fn probe(addr string) int {
    lfd := net.listen(addr + "") or >>
    // No client exists yet: every readiness result must be exactly zero.
    for i in 0:64 {
        ready := os.socket_poll(lfd, 1) or (err) { close_quiet(lfd)
            >> err }
        if ready != 0 { close_quiet(lfd)
            >> errors.new("idle listener reported ready") }
    }
    if !invalid_socket_rejected() { close_quiet(lfd)
        >> errors.new("invalid SOCKET accepted") }
    xu serve(lfd)
    out := chan int{cap: 2}
    for i in 0:2 { xu worker(addr + "", out) }
    first := <-out
    second := <-out
    if first != 3 || second != 3 { >> errors.new("concurrent requests failed") }
    // The server owns lfd until this process exits, including its worker Gs.
    println("Windows socket poll and concurrent HTTP passed")
    << 0
}

fn main() int {
    arguments := args()
    if arguments.len != 2 { << 2 }
    << probe(arguments[1] + "") or (err) { eprintln(err.msg())
        << 1 }
}
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--target", choices=("windows-arm64", "windows-x64"), required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("requires a Windows host")
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, XU_ROOT=str(root), XU_STDLIB_ROOT=str(root / "src"), XUPATH="")
    expected = b"Windows socket poll and concurrent HTTP passed\n"
    with WindowsTemporaryDirectory(prefix="xu-windows-poll-") as temporary:
        directory = Path(temporary)
        source = directory / "main.xu"
        source.write_text(SOURCE, encoding="utf-8", newline="\n")
        for opt in ("-O0", "-O1", "-O2", "-O3"):
            binary = directory / (opt[1:] + ".exe")
            subprocess.run([str(args.compiler.resolve()), "build", str(source), "--target", args.target,
                            opt, "-o", str(binary)], cwd=root, env=env, check=True, timeout=120)
            for repeat in range(3):
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    address = "127.0.0.1:" + str(reservation.getsockname()[1])
                result = subprocess.run([str(binary), address], env=env, capture_output=True, timeout=15)
                if result.returncode != 0 or result.stdout != expected or result.stderr:
                    raise RuntimeError(f"{args.target} {opt} run {repeat}: exit {result.returncode}; "
                                       f"stdout={result.stdout!r}; stderr={result.stderr!r}")
            print(f"{args.target} {opt}: 3/3 passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
