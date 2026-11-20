#!/usr/bin/env python3
"""Test TCP and UDP socket options and PacketConn deadlines."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = r'''@main
#net

fn test_tcp_options() int {
    $ln := net.listen_on("tcp", "127.0.0.1:0") or >>
    // Even if ln.addr is :0, we can dial directly to loopback with known port or accept
    ln.close() or >>
    << 0
}

fn test_udp_deadline() int {
    local := net.resolve_udp_addr("udp4", "127.0.0.1:0") or >>
    $c := net.listen_udp("udp4", local) or >>
    c.set_read_buffer(65536) or >>
    c.set_write_buffer(65536) or >>
    c.set_broadcast(true) or >>

    // Set 50ms read deadline in the future
    start := now_ns()
    deadline := start + 50000000 // 50ms
    c.set_read_deadline(deadline) or >>

    pkt := c.read_from(128) or (err) {
        c.close() or (e2) { << 0 }
        msg := err.msg()
        if msg == "i/o timeout" || msg == "recvfrom: connection timed out" || msg == "recvfrom: Resource temporarily unavailable" {
            println("udp_deadline_passed")
            << 0
        }
        println("unexpected error: " + err.msg())
        << 1
    }
    c.close() or >>
    println("ERROR: read_from did not timeout")
    << 2
}

fn test_conn_options() int {
    $ln := net.listen_on("tcp", "127.0.0.1:19876") or >>
    $client := net.dial_to("tcp", "127.0.0.1:19876") or >>
    $server := ln.accept() or >>

    client.set_nodelay(true) or >>
    client.set_keepalive(true) or >>
    client.set_read_buffer(65536) or >>
    client.set_write_buffer(65536) or >>

    server.set_nodelay(true) or >>
    server.set_keepalive(true) or >>

    msg := "hello socket options"
    client.write(&msg) or >>
    recv := server.read(128) or >>
    if recv != msg {
        println("ERROR: echo mismatch")
        << 2
    }

    client.close() or >>
    server.close() or >>
    ln.close() or >>
    println("tcp_options_passed")
    << 0
}

fn main() int {
    r1 := test_udp_deadline() or (err) {
        println("udp error: " + err.msg())
        << 10
    }
    if r1 != 0 { << r1 }

    r2 := test_conn_options() or (err) {
        println("tcp error: " + err.msg())
        << 20
    }
    if r2 != 0 { << r2 }

    println("ALL_TCP_UDP_STEP1_TESTS_PASSED")
    << 0
}
'''

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    compiler = root / "bin" / ("xu.exe" if os.name == "nt" else "xu")
    env = {k: v for k, v in os.environ.items() if not k.startswith("XU")}
    env.update(XU_ROOT=str(root), XU_STDLIB_ROOT=str(root / "src"), XUPATH="")

    with tempfile.TemporaryDirectory(prefix="xu-test-options-") as tmp:
        work = Path(tmp)
        src = work / "test_options.xu"
        out = work / ("test_options.exe" if os.name == "nt" else "test_options")
        src.write_text(SOURCE, encoding="utf-8")
        
        build_cmd = [str(compiler), "build", str(src), "-o", str(out)]
        res = subprocess.run(build_cmd, env=env, capture_output=True, text=True)
        if res.returncode != 0:
            print("BUILD FAILED:", res.stderr)
            return 1
            
        run_res = subprocess.run([str(out)], capture_output=True, text=True, timeout=10)
        print(run_res.stdout)
        if run_res.returncode != 0:
            print("RUN FAILED:", run_res.stderr)
            return 2
        if "ALL_TCP_UDP_STEP1_TESTS_PASSED" not in run_res.stdout:
            print("UNEXPECTED OUTPUT")
            return 3
    print("SUCCESS: Step 1 options & deadlines verified!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
