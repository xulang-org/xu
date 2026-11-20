import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPILER = ROOT / "bin" / "xu.exe"

SOURCE = r"""@main
#net
#context

fn test_listen_config_tcp() bool {
    lc := net.new_listen_config()
    $ctx := context.background()
    $l := lc.listen(&ctx, "tcp4", "127.0.0.1:0") or >>
    loc := l.addr()
    println("ListenConfig tcp bound to: " + loc)
    if loc.len < 10 {
        << false
    }

    $c := net.dial_to("tcp4", loc + "") or >>
    $s := l.accept() or >>

    msg := "testing listen config"
    c.write(&msg) or >>
    rec := s.read(128) or >>
    if rec != msg {
        println("ListenConfig rec mismatch: " + rec)
        << false
    }

    c.close() or >>
    s.close() or >>
    l.close() or >>
    println("test_listen_config_tcp_passed")
    << true
}

fn test_listen_config_udp() bool {
    lc := net.new_listen_config()
    $ctx := context.background()
    $s := lc.listen_packet(&ctx, "udp4", "127.0.0.1:0") or >>
    s_addr := s.local_addr()
    println("ListenConfig udp bound to: " + s_addr)
    s_udp := net.resolve_udp_addr("udp4", s_addr + "") or >>

    $c := net.listen_packet("udp4", "127.0.0.1:0") or >>
    msg := "testing listen_packet udp"
    c.write_to(&msg, &s_udp) or >>

    pkt := s.read_from(128) or >>
    if pkt.data != msg {
        println("ListenConfig udp rec mismatch: " + pkt.data)
        << false
    }

    s.close() or >>
    c.close() or >>
    println("test_listen_config_udp_passed")
    << true
}

fn main() int {
    ok1 := test_listen_config_tcp() or (err) {
        eprintln("listen config tcp error: " + err.msg())
        <<< 1
    }
    if !ok1 { <<< 1 }

    ok2 := test_listen_config_udp() or (err) {
        eprintln("listen config udp error: " + err.msg())
        <<< 2
    }
    if !ok2 { <<< 2 }

    println("ALL_STEP4_TESTS_PASSED")
    << 0
}
"""

def main():
    test_src = ROOT / "tmp_test_step4.xu"
    test_exe = ROOT / "tmp_test_step4.exe"
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
        
        assert "ALL_STEP4_TESTS_PASSED" in res_run.stdout
        print("SUCCESS: Step 4 ListenConfig tests passed!")
    finally:
        if test_src.exists():
            test_src.unlink(missing_ok=True)
        if test_exe.exists():
            test_exe.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
