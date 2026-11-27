import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPILER = ROOT / "bin" / "xu.exe"

SOURCE = r"""@main
#net

fn test_ipv4_udp() bool {
    $srv := net.listen_udp("udp4", net.resolve_udp_addr("udp4", "127.0.0.1:0") >>>) >>>
    srv_addr := srv.local_addr()
    println("ipv4 srv bound to: " + srv_addr)
    srv_udp := net.resolve_udp_addr("udp4", srv_addr + "") >>>

    $cli := net.listen_udp("udp4", net.resolve_udp_addr("udp4", "127.0.0.1:0") >>>) >>>
    cli_addr := cli.local_addr()
    cli_udp := net.resolve_udp_addr("udp4", cli_addr + "") >>>

    msg := "hello ipv4 udp"
    cli.write_to(&msg, &srv_udp) >>>

    pkt := srv.read_from(128) >>>
    if pkt.data != msg {
        println("srv data mismatch: " + pkt.data)
        << false
    }
    if pkt.addr.port != cli_udp.port {
        println("srv peer port mismatch: expected " + str(cli_udp.port) + " got " + str(pkt.addr.port))
        << false
    }

    reply := "echo ipv4: " + pkt.data
    srv.write_to(&reply, &pkt.addr) >>>

    cli_pkt := cli.read_from(128) >>>
    if cli_pkt.data != reply {
        println("cli data mismatch: " + cli_pkt.data)
        << false
    }
    if cli_pkt.addr.port != srv_udp.port {
        println("cli peer port mismatch: expected " + str(srv_udp.port) + " got " + str(cli_pkt.addr.port))
        << false
    }

    srv.close() >>>
    cli.close() >>>
    println("test_ipv4_udp_passed")
    << true
}

fn test_ipv6_udp() bool {
    $srv := net.listen_udp("udp6", net.resolve_udp_addr("udp6", "[::1]:0") >>>) >>>
    srv_addr := srv.local_addr()
    println("ipv6 srv bound to: " + srv_addr)
    srv_udp := net.resolve_udp_addr("udp6", srv_addr + "") >>>

    $cli := net.listen_udp("udp6", net.resolve_udp_addr("udp6", "[::1]:0") >>>) >>>
    cli_addr := cli.local_addr()
    cli_udp := net.resolve_udp_addr("udp6", cli_addr + "") >>>

    msg := "hello ipv6 udp datagram"
    cli.write_to(&msg, &srv_udp) >>>

    pkt := srv.read_from(128) >>>
    if pkt.data != msg {
        println("ipv6 srv data mismatch: " + pkt.data)
        << false
    }
    if pkt.addr.port != cli_udp.port {
        println("ipv6 srv peer port mismatch: expected " + str(cli_udp.port) + " got " + str(pkt.addr.port))
        << false
    }

    reply := "echo ipv6: " + pkt.data
    srv.write_to(&reply, &pkt.addr) >>>

    cli_pkt := cli.read_from(128) >>>
    if cli_pkt.data != reply {
        println("ipv6 cli data mismatch: " + cli_pkt.data)
        << false
    }
    if cli_pkt.addr.port != srv_udp.port {
        println("ipv6 cli peer port mismatch: expected " + str(srv_udp.port) + " got " + str(cli_pkt.addr.port))
        << false
    }

    srv.close() >>>
    cli.close() >>>
    println("test_ipv6_udp_unconnected_passed")
    << true
}

fn test_ipv6_udp_connected() bool {
    $srv := net.listen_udp("udp6", net.resolve_udp_addr("udp6", "[::1]:0") >>>) >>>
    srv_addr := srv.local_addr()
    srv_udp := net.resolve_udp_addr("udp6", srv_addr + "") >>>

    local_udp := net.resolve_udp_addr("udp6", "[::1]:0") >>>
    $cli := net.dial_udp("udp6", local_udp, srv_udp.clone()) >>>

    msg := "connected ipv6 udp"
    cli.write(&msg) >>>

    pkt := srv.read_from(128) >>>
    if pkt.data != msg {
        println("conn ipv6 srv data mismatch: " + pkt.data)
        << false
    }

    reply := "ack connected ipv6"
    srv.write_to(&reply, &pkt.addr) >>>

    rep := cli.read(128) >>>
    if rep != reply {
        println("conn ipv6 cli read mismatch: " + rep)
        << false
    }

    srv.close() >>>
    cli.close() >>>
    println("test_ipv6_udp_connected_passed")
    << true
}

fn main() int {
    ok1 := test_ipv4_udp() >>> (err) {
        eprintln("ipv4 udp threw: " + err.msg())
        <<< 1
    }
    if !ok1 {
        eprintln("ipv4 udp failed")
        <<< 1
    }
    ok2 := test_ipv6_udp() >>> (err) {
        eprintln("ipv6 udp threw: " + err.msg())
        <<< 2
    }
    if !ok2 {
        eprintln("ipv6 udp failed")
        <<< 2
    }
    ok3 := test_ipv6_udp_connected() >>> (err) {
        eprintln("ipv6 udp connected threw: " + err.msg())
        <<< 3
    }
    if !ok3 {
        eprintln("ipv6 udp connected failed")
        <<< 3
    }
    println("ALL_IPV6_UDP_TESTS_PASSED")
    << 0
}
"""

def main():
    test_src = ROOT / "tmp_test_udp_ipv6.xu"
    test_exe = ROOT / "tmp_test_udp_ipv6.exe"
    try:
        test_src.write_text(SOURCE, encoding="utf-8")
        env = dict(os.environ)
        env["XU_STDLIB_ROOT"] = str(ROOT / "src")
        
        cmd_build = [str(COMPILER), "build", "-o", str(test_exe), str(test_src)]
        print(f"Building {test_src} -> {test_exe}")
        res_build = subprocess.run(cmd_build, env=env, capture_output=True, text=True)
        if res_build.returncode != 0:
            print("Build stdout:", res_build.stdout)
            print("Build stderr:", res_build.stderr)
            sys.exit(1)
        
        print("Running test executable...")
        res_run = subprocess.run([str(test_exe)], capture_output=True, text=True, timeout=15)
        print("Run stdout:\n" + res_run.stdout)
        if res_run.stderr:
            print("Run stderr:\n" + res_run.stderr)
        if res_run.returncode != 0:
            print(f"FAILED with exit code {res_run.returncode}")
            sys.exit(res_run.returncode)
        
        assert "ALL_IPV6_UDP_TESTS_PASSED" in res_run.stdout
        print("SUCCESS: IPv6 and IPv4 UDP tests passed!")
    finally:
        if test_src.exists():
            test_src.unlink(missing_ok=True)
        if test_exe.exists():
            test_exe.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
