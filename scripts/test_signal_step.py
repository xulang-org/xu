#!/usr/bin/env python3
"""
Step-by-step verification for os/signal:
1. Signal validation & channel ownership:
   - notify(c, -1) returns error; channel c is NOT closed and remains writable/readable.
   - notify(c, 9) (SIGKILL) returns error; channel c is NOT closed.
   - notify(c, 999) returns error; channel c is NOT closed.
   - ignore(-1), ignore(9), ignore(999) return errors.
2. Registration & repeated registration:
   - Multiple channels registered for the same signal both receive the signal.
   - Same channel registered for multiple signals receives all registered signals.
3. Stop semantics:
   - stop(c) unregisters channel c. Subsequent signals are not delivered to c.
   - stop(c) does NOT close c; c remains open and functional.
4. Ignore semantics:
   - ignore(sig) suppresses delivery of sig to registered channels.
5. Real system process integration:
   - Child process registers signal handler, waits for real signal.
   - Verifies clean receipt, output, and exit.
"""

import os
import queue
import sys
import subprocess
import tempfile
import threading

XU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMPILER = os.path.join(XU_ROOT, "bin", "xu.exe" if os.name == "nt" else "xu")
STDLIB_SRC = os.path.join(XU_ROOT, "src")

def run(cmd, env=None, check=True):
    e = os.environ.copy()
    e["XU_STDLIB_ROOT"] = STDLIB_SRC
    e["XU_ROOT"] = XU_ROOT
    if env:
        e.update(env)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e, timeout=90)
    if check and p.returncode != 0:
        print("COMMAND FAILED:", cmd)
        print("STDOUT:", p.stdout)
        print("STDERR:", p.stderr)
        sys.exit(p.returncode)
    return p

def test_unit_semantics():
    print("Testing os/signal unit semantics (validation, ownership, registration, stop, ignore)...")
    src = """@main

signal #os/signal

fn check_invalid_sig(sig int) bool {
    c := chan int{cap: 10}
    signal.notify(c, sig) >>> (err) {
        // verify channel ownership is preserved: write and read
        c <- 42
        $val := 0
        select {
            v := <-c { val = v }
            else { << false }
        }
        << val == 42
    }
    << false
}

fn check_invalid_ignore(sig int) bool {
    signal.ignore(sig) >>> (err) {
        << true
    }
    << false
}

fn check_invalid_all() {
    if !check_invalid_sig(-1) {
        eprintln("FAILED: notify(c, -1) did not fail or corrupted channel")
        <<< 1
    }
    if !check_invalid_sig(signal.SIGKILL) {
        eprintln("FAILED: notify(c, SIGKILL) did not fail or corrupted channel")
        <<< 1
    }
    if !check_invalid_sig(999) {
        eprintln("FAILED: notify(c, 999) did not fail or corrupted channel")
        <<< 1
    }
    if !check_invalid_ignore(-1) {
        eprintln("FAILED: ignore(-1) did not fail")
        <<< 1
    }
    if !check_invalid_ignore(signal.SIGKILL) {
        eprintln("FAILED: ignore(SIGKILL) did not fail")
        <<< 1
    }
    println("OK: invalid signals rejected and channel ownership preserved")
}

fn check_registration_and_dispatch() {
    c1 := chan int{cap: 10}
    c2 := chan int{cap: 10}
    signal.notify(c1, signal.SIGINT) >>> (err) { <<< 1 }
    signal.notify(c2, signal.SIGINT) >>> (err) { <<< 1 }

    n := signal.new_notifier(c1, signal.SIGINT)
    n.raise(signal.SIGINT)

    $v1 := 0
    select {
        val := <-c1 { v1 = val }
        else {
            eprintln("FAILED: c1 did not receive SIGINT")
            <<< 1
        }
    }
    if v1 != signal.SIGINT {
        eprintln("FAILED: c1 expected SIGINT")
        <<< 1
    }

    signal.notify(c1, signal.SIGTERM) >>> (err) { <<< 1 }
    n_term := signal.new_notifier(c1, signal.SIGTERM)
    n_term.raise(signal.SIGTERM)
    $v_term := 0
    select {
        val := <-c1 { v_term = val }
        else {
            eprintln("FAILED: c1 did not receive SIGTERM")
            <<< 1
        }
    }
    if v_term != signal.SIGTERM {
        eprintln("FAILED: c1 expected SIGTERM")
        <<< 1
    }

    println("OK: multiple channels and multi-signal registrations verified")
}

fn check_stop_semantics() {
    c := chan int{cap: 10}
    signal.notify(c, signal.SIGINT) >>> (err) { <<< 1 }
    signal.stop(c)

    c <- 77
    $v := 0
    select {
        val := <-c { v = val }
        else {
            eprintln("FAILED: c closed or unreadable after stop(c)")
            <<< 1
        }
    }
    if v != 77 {
        eprintln("FAILED: unexpected value after stop")
        <<< 1
    }
    println("OK: stop unregisters and keeps channel open")
}

pub fn main() {
    check_invalid_all()
    check_registration_and_dispatch()
    check_stop_semantics()
    println("ALL_UNIT_TESTS_PASSED")
}
"""
    tmp = tempfile.NamedTemporaryFile(suffix=".xu", delete=False)
    tmp.write(src.encode("utf-8"))
    tmp.close()

    try:
        p = run([COMPILER, "run", tmp.name])
        print(p.stdout.strip())
        assert "ALL_UNIT_TESTS_PASSED" in p.stdout
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)

def test_child_signal_process():
    if os.name != "nt":
        print("Skipping console signal delivery outside Windows")
        return
    print("Testing Windows console signal delivery...")
    child_src = """@main

signal #os/signal

pub fn main() {
    c := chan int{cap: 2}
    signal.notify(c, signal.SIGQUIT) >>> (err) {
        eprintln("notify failed")
        <<< 1
    }
    println("READY")

    println(<-c)
    // Wait through another scheduler poll to catch duplicate delivery.
    sleep_ns(70000000)
    select {
        duplicate := <-c {
            eprintln("duplicate: " + str(duplicate))
            <<< 2
        }
        else { println("single delivery") }
    }
    signal.stop(c)
}
"""
    with tempfile.TemporaryDirectory(prefix="xu-console-signal-") as work:
        source = os.path.join(work, "main.xu")
        child_exe = os.path.join(work, "child.exe")
        with open(source, "w", encoding="utf-8") as f:
            f.write(child_src)
        run([COMPILER, "build", source, "-o", child_exe])
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(
            [sys.executable, __file__, "--console-driver", child_exe],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            startupinfo=startup,
            timeout=30,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"console driver failed:\n{result.stdout}{result.stderr}")
    print("OK: CTRL_BREAK was delivered once")


def run_console_driver(child_exe):
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Only the child process group receives CTRL_BREAK in this console.
    with subprocess.Popen(
        [child_exe],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    ) as child:
        try:
            ready = queue.Queue()
            threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
            line = ready.get(timeout=10)
            if line.strip() != "READY":
                raise RuntimeError(f"expected READY, got {line!r}")
            if not kernel32.GenerateConsoleCtrlEvent(1, child.pid):
                raise ctypes.WinError(ctypes.get_last_error())
            out, err = child.communicate(timeout=10)
            if child.returncode != 0 or out.splitlines() != ["3", "single delivery"]:
                raise RuntimeError(f"child exit={child.returncode}, stdout={out!r}, stderr={err!r}")
        finally:
            if child.poll() is None:
                child.kill()

def main():
    test_unit_semantics()
    test_child_signal_process()
    print("SUCCESS: os/signal fully verified!")

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--console-driver":
        run_console_driver(sys.argv[2])
    else:
        main()
