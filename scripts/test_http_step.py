import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPILER = ROOT / "bin" / "xu.exe"

SOURCE = r"""@main
#net/http
#net/url
#strings

fn test_url_helpers() bool {
    u := url.parse("http://example.com:8080/path/test?q=xulang&name=test#section")
    if u.scheme() != "http" {
        println("scheme mismatch: " + u.scheme())
        << false
    }
    if u.host() != "example.com:8080" {
        println("host mismatch: " + u.host())
        << false
    }
    if u.path() != "/path/test" {
        println("path mismatch: " + u.path())
        << false
    }
    q := u.query()
    if q.get("q") != "xulang" {
        println("query q mismatch: " + q.get("q"))
        << false
    }

    q2 := url.parse_query("user=alice&action=login&page=1")
    if q2.get("user") != "alice" || q2.get("action") != "login" || q2.get("page") != "1" {
        println("parse_query mismatch")
        << false
    }

    println("test_url_helpers_passed")
    << true
}

fn handle_req(c http.Context) {
    rem := c.remote_addr()
    println("handler got remote_addr: " + rem)
    qv := c.query_value("item")
    fv := c.form_value("user")
    reply := "ack: " + rem + " item=" + qv + " user=" + fv
    _ := c.text(200, reply) or (err) { << }
}

fn run_server(s http.Server) {
    s.serve(handle_req)
}

fn test_http_server() bool {
    $s := http.new_server()
    s.listen("127.0.0.1:0") or (err) {
        eprintln("listen error: " + err.msg())
        << false
    }
    addr := s.addr()
    println("server bound to: " + addr)
    if addr.len < 10 || !strings.has_prefix(&addr, "127.0.0.1:") {
        println("bad server addr: " + addr)
        << false
    }

    // Run server in background
    xu run_server(s.clone())

    // Make request from client
    $client := http.new_client()
    url_str := "http://" + addr + "/test?item=book"
    $form := url.new_query()
    form.set("user", "bob")
    form.set("extra", "123")
    
    resp := client.post_form(url_str + "", &form) or (err) {
        eprintln("client post_form error: " + err.msg())
        << false
    }
    
    println("client got body: " + resp.body)
    if !strings.contains(&resp.body, "item=book") || !strings.contains(&resp.body, "user=bob") {
        println("response body missing expected fields: " + resp.body)
        << false
    }

    // Shutdown server
    s.shutdown()
    println("test_http_server_passed")
    << true
}

fn main() int {
    if !test_url_helpers() {
        eprintln("url helpers failed")
        <<< 1
    }
    if !test_http_server() {
        eprintln("http server failed")
        <<< 2
    }
    println("ALL_HTTP_STEP_TESTS_PASSED")
    << 0
}
"""

def main():
    test_src = ROOT / "tmp_test_http_step.xu"
    test_exe = ROOT / "tmp_test_http_step.exe"
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
        
        assert "ALL_HTTP_STEP_TESTS_PASSED" in res_run.stdout
        print("SUCCESS: Module 1 HTTP & URL tests passed!")
    finally:
        if test_src.exists():
            test_src.unlink(missing_ok=True)
        if test_exe.exists():
            test_exe.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
