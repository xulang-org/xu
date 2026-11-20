#!/usr/bin/env python3
"""Test getsockname, getpeername, dynamic :0 port introspection, and TCP shutdown."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = r'''@main
#net
#strings

fn test_tcp_dynamic_port_and_peer() int {
    $ln := net.listen_on("tcp", "127.0.0.1:0") or >>
    addr := ln.addr()
    if addr.len == 0 || (addr.len >= 2 && addr[addr.len - 2:addr.len] == ":0") {
        println("ERROR: listener addr was not resolved: " + addr)
        << 1
    }
    println("listener bound to: " + addr)

    $client := net.dial_to("tcp", addr) or >>
    $server := ln.accept() or >>

    s_remote := server.remote_addr()
    s_local := server.local_addr()
    c_remote := client.remote_addr()
    c_local := client.local_addr()

    if s_remote.len == 0 {
        println("ERROR: server.remote_addr() is empty")
        << 2
    }
    if c_local.len == 0 {
        println("ERROR: client.local_addr() is empty")
        << 3
    }
    println("server remote: " + s_remote)
    println("client local:  " + c_local)
    if s_remote != c_local {
        println("ERROR: server remote != client local: " + s_remote + " vs " + c_local)
        << 4
    }

    // Test TCP half-close (shutdown write)
    msg := "request before half-close"
    client.write(&msg) or >>
    client.close_write() or >>

    // Server should read the message, then EOF ("")
    buf1 := server.read(128) or >>
    if buf1 != msg {
        println("ERROR: server read mismatch")
        << 5
    }
    buf2 := server.read(128) or >>
    if buf2.len != 0 {
        println("ERROR: expected EOF after close_write, got: " + buf2)
        << 6
    }
    println("half-close write EOF verified")

    // Server can still send data back
    reply := "response after client half-close"
    server.write(&reply) or >>
    server.close() or >>

    buf3 := client.read(128) or >>
    if buf3 != reply {
        println("ERROR: client read reply mismatch: " + buf3)
        << 7
    }

    client.close() or >>
    ln.close() or >>
    println("tcp_dynamic_port_and_shutdown_passed")
    << 0
}

fn test_udp_dynamic_port() int {
    local := net.resolve_udp_addr("udp4", "127.0.0.1:0") or >>
    $c := net.listen_udp("udp4", local) or >>
    addr := c.local_addr()
    if addr.len == 0 || (addr.len >= 2 && addr[addr.len - 2:addr.len] == ":0") {
        println("ERROR: udp local_addr was not resolved: " + addr)
        << 8
    }
    println("udp bound to: " + addr)
    c.close() or >>
    println("udp_dynamic_port_passed")
    << 0
}

fn main() int {
    r1 := test_tcp_dynamic_port_and_peer() or (err) {
        println("tcp error: " + err.msg())
        << 10
    }
    if r1 != 0 { << r1 }

    r2 := test_udp_dynamic_port() or (err) {
        println("udp error: " + err.msg())
        << 20
    }
    if r2 != 0 { << r2 }

    println("ALL_TCP_UDP_STEP2_TESTS_PASSED")
    << 0
}
'''

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    compiler = root / "bin" / ("xu.exe" if os.name == "nt" else "xu")
    env = {k: v for k, v in os.environ.items() if not k.startswith("XU")}
    env.update(XU_ROOT=str(root), XU_STDLIB_ROOT=str(root / "src"), XUPATH="")

    with tempfile.TemporaryDirectory(prefix="xu-test-step2-") as tmp:
        work = Path(tmp)
        src = work / "test_step2.xu"
        out = work / ("test_step2.exe" if os.name == "nt" else "test_step2")
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
        if "ALL_TCP_UDP_STEP2_TESTS_PASSED" not in run_res.stdout:
            print("UNEXPECTED OUTPUT")
            return 3
    print("SUCCESS: Step 2 getsockname, getpeername, and shutdown verified!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
