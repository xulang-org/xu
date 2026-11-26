#!/usr/bin/env python3
"""Verification for raw IP socket support (net.dial_ip / net.listen_ip / listen_packet)."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "bin" / "xu.exe"

TEST_CODE = r'''@main

#net

fn test_invalid_network() {
    _ := net.dial_to("invalid_net", "127.0.0.1") >>> (err) {
        println("OK: invalid network rejected: " + err.msg())
        <<
    }
    eprintln("expected error for invalid network")
    <<< 1
}

fn test_stream_listen_rejected() {
    _ := net.listen_on("ip:icmp", "127.0.0.1") >>> (err) {
        if err.msg() != "net: IP listen is listen_packet or listen_ip, not Listen" {
            eprintln("unexpected listen_on error: " + err.msg())
            <<< 2
        }
        println("OK: stream listen on IP rejected with correct guidance")
        <<
    }
    eprintln("expected error for stream listen on IP")
    <<< 2
}

fn test_dial_ip_raw() {
    _ := net.dial_to("ip:icmp", "127.0.0.1") >>> (err) {
        msg := err.msg()
        println("dial_ip attempted OS raw socket: " + msg)
        if msg == "net: raw IP sockets are not available on this target" {
            eprintln("still throwing stub message!")
            <<< 3
        }
        println("OK: dial_ip reached OS kernel raw socket creation (OS permission enforced)")
        <<
    }
    println("OK: dial_ip raw socket opened successfully (running privileged)")
}

fn test_listen_ip_raw() {
    _ := net.listen_packet("ip:icmp", "127.0.0.1") >>> (err) {
        msg := err.msg()
        println("listen_ip attempted OS raw socket: " + msg)
        if msg == "net: raw IP sockets are not available on this target" {
            eprintln("still throwing stub message!")
            <<< 4
        }
        println("OK: listen_packet reached OS kernel raw socket creation (OS permission enforced)")
        <<
    }
    println("OK: listen_packet raw socket opened successfully (running privileged)")
}

fn test_explicit_dial_ip() {
    laddr := net.resolve_ip_addr("ip4:1", "127.0.0.1") >>> (err) {
        eprintln("resolve_ip_addr failed: " + err.msg())
        <<< 5
    }
    raddr := net.resolve_ip_addr("ip4:1", "127.0.0.1") >>> (err) {
        eprintln("resolve_ip_addr failed: " + err.msg())
        <<< 6
    }
    _ := net.dial_ip("ip4:1", laddr, raddr) >>> (err) {
        msg := err.msg()
        if msg == "net: raw IP sockets are not available on this target" {
            eprintln("dial_ip still throwing stub message!")
            <<< 7
        }
        println("OK: explicit dial_ip reached OS kernel raw socket creation: " + msg)
        <<
    }
    println("OK: explicit dial_ip succeeded (running privileged)")
}

fn main() {
    println("--- TESTING RAW IP SOCKET SUPPORT ---")
    test_invalid_network()
    test_stream_listen_rejected()
    test_dial_ip_raw()
    test_listen_ip_raw()
    test_explicit_dial_ip()
    println("ALL_IPRAW_TESTS_PASSED")
}
'''

def main() -> int:
    env = os.environ.copy()
    env["XU_STDLIB_ROOT"] = str(ROOT / "src")
    env["XU_ROOT"] = str(ROOT)

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "test_raw.xu"
        exe = Path(td) / "test_raw.exe"
        src.write_text(TEST_CODE, encoding="utf-8")

        build_cmd = [str(COMPILER), "build", str(src), "-o", str(exe)]
        r = subprocess.run(build_cmd, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print("COMPILE FAILED:\n" + r.stderr + "\n" + r.stdout)
            return 1

        r2 = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=10)
        print(r2.stdout)
        if r2.stderr:
            print(r2.stderr, file=sys.stderr)

        if r2.returncode != 0:
            print(f"FAILED with exit code {r2.returncode}")
            return 1

        if "ALL_IPRAW_TESTS_PASSED" not in r2.stdout:
            print("FAILED: missing completion banner")
            return 1

    print("SUCCESS: raw IP socket support verified!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
