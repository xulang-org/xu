#!/usr/bin/env python3
"""High-concurrency stress testing and verification for net/http server."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "bin" / "xu.exe"

STRESS_TEST_XU = r'''@main
#net
#net/http
#strconv

fn handle_stress(c http.Context) {
    p := c.path()
    if p == "/static_file.txt" {
        fs := http.file_server(".")
        fs.serve_context(c)
        <<
    }
    if p == "/large" {
        $data := ""
        for i in 0:512 {
            data = data + "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        }
        c.text(200, data) or (err) { << }
        <<
    }
    c.text(200, "ok:" + p) or (err) { << }
}

fn serve_stress(lfd int, srv_done chan int) {
    $opts := http.server_options()
    opts.max_active_handlers = 512
    opts.read_timeout_ns = 10000000000
    opts.write_timeout_ns = 10000000000
    opts.max_buffer_bytes = 67108864
    _ := http.serve_listener_with_options(lfd, handle_stress, opts) or (err) {
        srv_done <- 1
        <<
    }
    srv_done <- 1
}

fn worker_loop(base_url string, worker_id int, reqs_per_worker int, out chan int) {
    $c := http.new_client()
    c.set_timeout(10000000000)
    $success := 0
    for i in 0:reqs_per_worker {
        $path := "/item/" + strconv.itoa(worker_id * 1000 + i)
        mod4 := i % 4
        if mod4 == 1 {
            path = "/large"
        } else if mod4 == 2 {
            path = "/static_file.txt"
        }
        resp := c.get(base_url + path) or (err) {
            out <- success
            <<
        }
        code := resp.status_code()
        if code == 200 {
            success += 1
        }
    }
    out <- success
}

fn worker_burst(base_url string, burst_count int, out chan int) {
    $success := 0
    for i in 0:burst_count {
        $c := http.new_client()
        c.set_timeout(5000000000)
        resp := c.get(base_url + "/ping") or (err) {
            ->
        }
        if resp.status_code() == 200 {
            success += 1
        }
    }
    out <- success
}

fn main() int {
    $port := 22500
    $lfd := -1
    for p in 0:32 {
        addr := "127.0.0.1:" + strconv.itoa(port + p)
        fd := net.listen(addr) or (err) { -> }
        lfd = fd
        port = port + p
        <-
    }
    if lfd < 0 {
        eprintln("stress: failed to bind loopback port")
        << 1
    }
    srv_done := chan int{cap: 1}
    xu serve_stress(lfd, srv_done)
    base_url := "http://127.0.0.1:" + strconv.itoa(port)

    // Stage 1: High concurrency keep-alive test
    // 32 concurrent client workers, each executing 50 requests (1600 total requests)
    num_workers := 32
    reqs_per_worker := 50
    expected_stage1 := num_workers * reqs_per_worker
    out1 := chan int{cap: num_workers}
    for w in 0:num_workers {
        xu worker_loop(base_url + "", w, reqs_per_worker, out1)
    }
    $total1 := 0
    for w in 0:num_workers {
        v := <-out1
        total1 += v
    }
    if total1 != expected_stage1 {
        eprintln("stage 1 failed: expected " + strconv.itoa(expected_stage1) + " got " + strconv.itoa(total1))
        net.conn_close(lfd) or (err) { << 3 }
        << 2
    }
    println("stage 1 (keep-alive 1600 reqs) passed")

    // Stage 2: Rapid new connection burst test
    // 8 concurrent workers creating fresh connections for 25 requests each (200 new conns)
    burst_workers := 8
    burst_each := 25
    expected_stage2 := burst_workers * burst_each
    out2 := chan int{cap: burst_workers}
    for b in 0:burst_workers {
        xu worker_burst(base_url + "", burst_each, out2)
    }
    $total2 := 0
    for b in 0:burst_workers {
        v := <-out2
        total2 += v
    }
    if total2 != expected_stage2 {
        eprintln("stage 2 failed: expected " + strconv.itoa(expected_stage2) + " got " + strconv.itoa(total2))
        net.conn_close(lfd) or (err) { << 3 }
        << 3
    }
    println("stage 2 (burst connection churn 200 conns) passed")

    // Stage 3: Teardown verification
    net.conn_close(lfd) or (err) { << 4 }
    if <-srv_done != 1 {
        eprintln("stage 3 failed: server did not shut down cleanly")
        << 5
    }
    println("stage 3 (graceful server teardown) passed")
    println("ALL HIGH CONCURRENCY STRESS TESTS PASSED")
    << 0
}
'''

def main() -> int:
    env = {k: v for k, v in os.environ.items() if not k.startswith("XU")}
    env.update(XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / "src"), XUPATH="")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "stress.xu"
        exe = Path(td) / "stress.exe"
        static_file = Path(td) / "static_file.txt"
        static_file.write_text("Stress test static asset payload for caching & ranges\n" * 50, encoding="utf-8")
        src.write_text(STRESS_TEST_XU, encoding="utf-8")

        print("Compiling high-concurrency stress test harness...")
        t0 = time.time()
        cmd_build = [str(COMPILER), "build", str(src), "--target", "windows-arm64", "-o", str(exe)]
        res_build = subprocess.run(cmd_build, env=env, capture_output=True, text=True)
        if res_build.returncode != 0:
            print(f"BUILD FAILED:\n{res_build.stderr}\n{res_build.stdout}")
            return 1
        print(f"Compilation took {time.time() - t0:.2f}s")

        print("Executing high-concurrency stress test...")
        t1 = time.time()
        res_run = subprocess.run([str(exe)], env=env, cwd=str(td), capture_output=True, text=True, timeout=60)
        duration = time.time() - t1
        if res_run.returncode != 0 or "ALL HIGH CONCURRENCY STRESS TESTS PASSED" not in res_run.stdout:
            print(f"STRESS RUN FAILED (exit {res_run.returncode}) in {duration:.2f}s:\n{res_run.stdout}\n{res_run.stderr}")
            return 2
        print(f"Stress test finished in {duration:.2f}s:")
        print(res_run.stdout.strip())
        return 0

if __name__ == "__main__":
    sys.exit(main())
