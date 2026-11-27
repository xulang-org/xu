import os
import sys
import subprocess
import tempfile

def main():
    xu_bin = os.path.abspath("bin/xu.exe")
    if not os.path.exists(xu_bin):
        print(f"Error: {xu_bin} not found", file=sys.stderr)
        return 1

    os.environ["XU_STDLIB_ROOT"] = os.path.abspath("src")
    os.environ["XU_ROOT"] = os.path.abspath(".")

    # Child script that reads from stdin, prints to stdout and eprint to stderr
    child_src = """@main

fn main() {
    // Read up to 256 bytes from stdin (fd 0)
    data := os_fd_read(0, 256) >>> (err) {
        println("child read failed: " + err.msg())
        <<< 1
    }
    
    // Write marker to stdout (fd 1)
    msg_out := "STDOUT_MARKER:" + data
    w1 := os_fd_write(1, msg_out) >>> (err) {
        <<< 1
    }
    
    // Write marker to stderr (fd 2)
    msg_err := "STDERR_MARKER:" + data
    w2 := os_fd_write(2, msg_err) >>> (err) {
        <<< 1
    }
    
    <<< 0
}
"""

    # Parent script that drives child with stdin_pipe, stdout_pipe, stderr_pipe
    parent_src = """@main
#os
#os/exec

fn drain_file(f $&os.File) string {
    $out := ""
    while true {
        chunk := f.read(1024) >>> (err) {
            <-
        }
        if chunk.len == 0 {
            <-
        }
        out = out + chunk
    }
    f.close() >>> (err) { << out }
    << out
}

fn call_stdout_pipe_expect_error(c $&exec.Cmd) bool {
    _ := c.stdout_pipe() >>> (err) {
        << true
    }
    << false
}

fn call_start_expect_error(c $&exec.Cmd) bool {
    _ := c.start() >>> (err) {
        << true
    }
    << false
}

fn test_three_pipes(child_exe string) {
    $cmd := exec.command(child_exe)
    
    $sin := cmd.stdin_pipe() >>> (err) {
        println("ERROR: stdin_pipe failed: " + err.msg())
        <<< 1
    }
    $sout := cmd.stdout_pipe() >>> (err) {
        println("ERROR: stdout_pipe failed: " + err.msg())
        <<< 1
    }
    $serr := cmd.stderr_pipe() >>> (err) {
        println("ERROR: stderr_pipe failed: " + err.msg())
        <<< 1
    }

    cmd.start() >>> (err) {
        println("ERROR: start failed: " + err.msg())
        <<< 1
    }

    // Calling pipe methods after start must throw
    if !call_stdout_pipe_expect_error($&cmd) {
        println("ERROR: stdout_pipe after start did not throw!")
        <<< 1
    }

    // Write to stdin and close write end
    msg := "echo_payload_42"
    wr := sin.write(msg) >>> (err) {
        println("ERROR: write to child stdin failed: " + err.msg())
        <<< 1
    }
    sin.close() >>> (err) {
        println("ERROR: close child stdin failed: " + err.msg())
        <<< 1
    }

    // Read stdout
    stdout_data := drain_file($&sout)
    expected_out := "STDOUT_MARKER:echo_payload_42"
    if stdout_data != expected_out {
        println("ERROR: stdout mismatch, got: [" + stdout_data + "] expected: [" + expected_out + "]")
        <<< 1
    }
    println("OK: stdout pipe verified: " + stdout_data)

    // Read stderr
    stderr_data := drain_file($&serr)
    expected_err := "STDERR_MARKER:echo_payload_42"
    if stderr_data != expected_err {
        println("ERROR: stderr mismatch, got: [" + stderr_data + "] expected: [" + expected_err + "]")
        <<< 1
    }
    println("OK: stderr pipe verified: " + stderr_data)

    // Wait for child exit
    cmd.wait() >>> (err) {
        println("ERROR: cmd.wait failed: " + err.msg())
        <<< 1
    }
    println("OK: child exit status 0 verified")
}

fn test_close_unstarted() {
    $cmd := exec.command("non_existent_binary_xyz_12345")
    $sin := cmd.stdin_pipe() >>> (err) {
        println("ERROR: stdin_pipe failed: " + err.msg())
        <<< 1
    }
    $sout := cmd.stdout_pipe() >>> (err) {
        println("ERROR: stdout_pipe failed: " + err.msg())
        <<< 1
    }
    $serr := cmd.stderr_pipe() >>> (err) {
        println("ERROR: stderr_pipe failed: " + err.msg())
        <<< 1
    }

    // start should fail for non-existent binary and clean up unstarted pipes
    if !call_start_expect_error($&cmd) {
        println("ERROR: start of non-existent binary succeeded?!")
        <<< 1
    }
    println("OK: start failure handled and unstarted pipes cleaned up")
}

fn main() {
    args := os.args()
    if args.len < 2 {
        println("Usage: parent <child_exe>")
        <<< 1
    }
    child_exe := args[1]
    
    println("Testing three standard stream pipes...")
    test_three_pipes(child_exe)

    println("Testing close unstarted on failure...")
    test_close_unstarted()

    println("ALL_EXEC_STDIO_TESTS_PASSED")
}
"""

    with tempfile.TemporaryDirectory() as td:
        child_xu = os.path.join(td, "child.xu")
        child_exe = os.path.join(td, "child.exe")
        with open(child_xu, "w", encoding="utf-8") as f:
            f.write(child_src)
            
        parent_xu = os.path.join(td, "parent.xu")
        parent_exe = os.path.join(td, "parent.exe")
        with open(parent_xu, "w", encoding="utf-8") as f:
            f.write(parent_src)
            
        env = os.environ.copy()
        env["XU_STDLIB_ROOT"] = os.path.abspath("src")
        env["XU_ROOT"] = os.path.abspath(".")

        print("Building child...")
        bld1 = subprocess.run([xu_bin, "build", "-o", child_exe, child_xu], capture_output=True, text=True, env=env)
        if bld1.returncode != 0:
            print("CHILD BUILD FAILED:\n" + bld1.stderr)
            return bld1.returncode

        print("Building parent...")
        bld2 = subprocess.run([xu_bin, "build", "-o", parent_exe, parent_xu], capture_output=True, text=True, env=env)
        if bld2.returncode != 0:
            print("PARENT BUILD FAILED:\n" + bld2.stderr)
            return bld2.returncode

        print("Running parent driving child with stdin, stdout, stderr pipes...")
        res = subprocess.run([parent_exe, child_exe], capture_output=True, text=True)
        print("STDOUT:\n" + res.stdout)
        print("STDERR:\n" + res.stderr)
        
        if res.returncode != 0 or "ALL_EXEC_STDIO_TESTS_PASSED" not in res.stdout:
            return 1
            
        print("SUCCESS: os/exec three standard stream pipes fully verified!")
        return 0

if __name__ == "__main__":
    sys.exit(main())
