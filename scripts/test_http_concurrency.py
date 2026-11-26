#!/usr/bin/env python3
"""Concurrency and performance tests for net/http server."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "bin" / "xu.exe"

CONCURRENCY_TEST_XU = r'''@main
#net
#net/http
#strconv

fn handle_request(c http.Context) {
    if c.path() == "/static_test.txt" {
        fs := http.file_server(".")
        fs.serve_context(c)
        <<
    }
    if c.path() == "/large" {
        $big := ""
        for i in 0:256 {
            big = big + "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        }
        c.text(200, big) >>> (err) { << }
        <<
    }
    c.text(200, "pong:" + c.path()) >>> (err) { << }
}

fn serve_task(lfd int, srv_done chan int) {
    $opts := http.server_options()
    opts.max_active_handlers = 512
    opts.read_timeout_ns = 5000000000
    opts.write_timeout_ns = 5000000000
    _ := http.serve_listener_with_options(lfd, handle_request, opts) >>> (err) {
        srv_done <- 1
        <<
    }
    srv_done <- 1
}

fn client_worker(base_url string, base_seq int, out chan int) {
    $c := http.new_client()
    c.set_timeout(5000000000)
    $ok := 0
    for i in 0:16 {
        $path := "/r/" + strconv.itoa(base_seq + i)
        if i == 0 { path = "/large" }
        resp := c.get(base_url + path) >>> (err) {
            out <- ok
            <<
        }
        if resp.status_code() == 200 {
            ok = ok + 1
        }
    }
    out <- ok
}

fn test_static_caching(base_url string) int {
    $c := http.new_client()
    c.set_timeout(5000000000)
    // 1. Regular GET
    r1 := c.get(base_url + "/static_test.txt") >>> (err) { << 1 }
    if r1.status_code() != 200 {
        eprintln("status was " + strconv.itoa(r1.status_code()) + ": " + r1.body())
        << 2
    }
    etag := r1.header("ETag")
    if etag.len == 0 { << 3 }
    if r1.header("Accept-Ranges") != "bytes" { << 4 }

    // 2. If-None-Match with matching ETag -> 304
    r2 := c.get_extra(base_url + "/static_test.txt", "If-None-Match: " + etag + "\r\n") >>> (err) { << 5 }
    if r2.status_code() != 304 { << 6 }

    // 3. Range request: bytes=0-9 -> 206
    r3 := c.get_extra(base_url + "/static_test.txt", "Range: bytes=0-9\r\n") >>> (err) { << 7 }
    if r3.status_code() != 206 { << 8 }
    if r3.body().len != 10 { << 9 }

    // 4. Invalid Range -> 416
    r4 := c.get_extra(base_url + "/static_test.txt", "Range: bytes=99999-999999\r\n") >>> (err) { << 10 }
    if r4.status_code() != 416 { << 11 }

    << 0
}

fn test_validation() int {
    $bad_opts1 := http.server_options()
    bad_opts1.max_active_handlers = 0
    _ := http.serve_listener_with_options(-1, handle_request, bad_opts1) >>> (err) {
        $bad_opts2 := http.server_options()
        bad_opts2.workers = 0
        _ := http.serve_listener_with_options(-1, handle_request, bad_opts2) >>> (err2) {
            << 0
        }
        << 2
    }
    << 1
}

fn main() int {
    val_res := test_validation()
    if val_res != 0 {
        eprintln("validation test failed: " + strconv.itoa(val_res))
        << val_res
    }
    $port := 21450
    $lfd := -1
    for p in 0:32 {
        addr := "127.0.0.1:" + strconv.itoa(port + p)
        fd := net.listen(addr) >>> (err) { -> }
        lfd = fd
        port = port + p
        <-
    }
    if lfd < 0 {
        eprintln("no loopback port")
        << 1
    }
    srv_done := chan int{cap: 1}
    xu serve_task(lfd, srv_done)
    base_url := "http://127.0.0.1:" + strconv.itoa(port)

    cache_res := test_static_caching(base_url + "")
    if cache_res != 0 {
        eprintln("static caching test failed: " + strconv.itoa(cache_res))
        net.conn_close(lfd) >>> (err) { << 3 }
        << cache_res + 100
    }

    // Launch 16 client workers in parallel (256 total requests)
    out := chan int{cap: 16}
    for w in 0:16 {
        xu client_worker(base_url + "", w * 16, out)
    }
    $total := 0
    for w in 0:16 {
        v := <-out
        total += v
    }
    net.conn_close(lfd) >>> (err) { << 3 }
    if <-srv_done != 1 { << 4 }
    if total != 256 {
        eprintln("expected 256 successful requests, got " + strconv.itoa(total))
        << 5
    }
    println("http concurrency test passed")
    << 0
}
'''

def main() -> int:
    env = {k: v for k, v in os.environ.items() if not k.startswith("XU")}
    env.update(XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / "src"), XUPATH="")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "test.xu"
        exe = Path(td) / "test.exe"
        static_file = Path(td) / "static_test.txt"
        static_file.write_text("Hello, this is static content for HTTP concurrency and caching test! 1234567890\n", encoding="utf-8")
        src.write_text(CONCURRENCY_TEST_XU, encoding="utf-8")

        cmd_build = [str(COMPILER), "build", str(src), "--target", "windows-arm64", "-o", str(exe)]
        res_build = subprocess.run(cmd_build, env=env, capture_output=True, text=True)
        if res_build.returncode != 0:
            print(f"BUILD FAILED:\n{res_build.stderr}\n{res_build.stdout}")
            return 1

        res_run = subprocess.run([str(exe)], env=env, cwd=str(td), capture_output=True, text=True, timeout=30)
        if res_run.returncode != 0 or "http concurrency test passed" not in res_run.stdout:
            print(f"RUN FAILED (exit {res_run.returncode}):\n{res_run.stdout}\n{res_run.stderr}")
            return 2
        print(res_run.stdout.strip())
        return 0

if __name__ == "__main__":
    sys.exit(main())
