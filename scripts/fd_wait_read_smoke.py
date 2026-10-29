#!/usr/bin/env python3
"""Non-consuming timed stdin/file waits, including Windows anonymous pipes.

Run natively on Windows to exercise GetFileType/PeekNamedPipe; on POSIX this
guards the unchanged poll path. No sockets, console input, or select() needed.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin" / ("xu.exe" if os.name == "nt" else "xu"))).resolve()
SOURCE = '''@main

#os

fn native_pipe() int {
    packed := os_pipe() or >>
    rfd := packed >> 32
    wfd := packed & 4294967295
    empty := os.fd_wait_read(rfd, -1) or >>
    if empty != 0 { << 10 }
    _ := os.fd_write(wfd, "native") or >>
    for _ in 0:2 {
        ready := os.fd_wait_read(rfd, -1) or >>
        if ready != 1 { << 11 }
    }
    data := os.fd_read(rfd, 64) or >>
    if data != "native" { << 12 }
    drained := os.fd_wait_read(rfd, -1) or >>
    if drained != 0 { << 13 }
    _ := os.fd_close(wfd) or >>
    eof := os.fd_wait_read(rfd, -1) or >>
    if eof != 1 { << 14 }
    if xu_target_os() == 2 {
        // Also cover direct builtin lowering, outside the imported os wrapper.
        direct := sys_fd_peek_read(rfd) or >>
        if direct != 1 { << 15 }
    }
    last := os.fd_read(rfd, 64) or >>
    if last != "" { << 16 }
    _ := os.fd_close(rfd) or >>
    println("native:ok")
    << 0
}

fn main() int {
    args := os.args()
    mode := args[1]
    if mode == "native" {
        << native_pipe() or (err) {
            eprintln(err.msg())
            << 9
        }
    }
    if mode == "invalid" {
        _ := os.fd_wait_read(-1, -1) or (err) {
            println(err.msg())
            << 0
        }
        << 1
    }
    mut timeout := 200000000
    if mode == "probe" { timeout = -1 }
    if mode == "infinite" { timeout = 0 }
    mut ready := os.fd_wait_read(0, timeout) or (err) {
        eprintln(err.msg())
        << 2
    }
    if mode == "retry" {
        if ready != 0 { << 7 }
        println(ready)
        ready = os.fd_wait_read(0, 0) or (err) {
            eprintln(err.msg())
            << 8
        }
    }
    println(ready)
    if ready == 1 {
        // A second immediate probe must not have consumed the data/EOF.
        again := os.fd_wait_read(0, -1) or (err) {
            eprintln(err.msg())
            << 3
        }
        if again != 1 { << 4 }
        data := os.fd_read(0, 64) or (err) {
            eprintln(err.msg())
            << 5
        }
        // Exercise the same standard-handle mapping used for XACP frames.
        _ := os.fd_write(1, "read:" + data + "\\n") or (err) {
            eprintln(err.msg())
            << 6
        }
    }
    << 0
}
'''


def finish(child, expected):
    try:
        assert child.wait(timeout=5) == 0
        assert child.stdout.read() == expected
        assert child.stderr.read() == b""
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()


def main():
    with tempfile.TemporaryDirectory(prefix="xu-fd-wait-") as tmp:
        tmp = Path(tmp)
        source = tmp / "main.xu"
        source.write_text(SOURCE)
        app = tmp / ("wait.exe" if os.name == "nt" else "wait")
        compiler = [str(ROOT / "scripts/run_product_compiler.sh"), str(XU)]
        if os.name == "nt":
            compiler = [str(XU)]
        env = dict(os.environ, XU_STDLIB_ROOT=str(ROOT / "src"), XUPATH="",
                   XU_CACHE=str(tmp / "cache"))
        env.pop("XUOS", None)
        env.pop("XUARCH", None)
        subprocess.run([*compiler, "build", str(source), "-o", str(app)],
                       env=env, check=True, timeout=180)

        def pipe(mode):
            return subprocess.Popen([str(app), mode], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        finish(pipe("native"), b"native:ok\n")

        # Keep stdin open while waiting: communicate() would close it and
        # turn an empty pending pipe into readable EOF.
        started = time.monotonic()
        finish(pipe("probe"), b"0\n")
        assert time.monotonic() - started < 2
        started = time.monotonic()
        finish(pipe("timeout"), b"0\n")
        assert 0.15 <= time.monotonic() - started < 3

        # Infinite wait, then data; the writer remains open through the read.
        child = pipe("infinite")
        time.sleep(0.1)
        assert child.poll() is None
        child.stdin.write(b"hello")
        child.stdin.flush()
        finish(child, b"1\nread:hello\n")

        # An expired wait leaves no hidden blocking reader to steal later data.
        child = pipe("retry")
        time.sleep(0.3)
        assert child.poll() is None
        child.stdin.write(b"later")
        child.stdin.flush()
        finish(child, b"0\n1\nread:later\n")

        child = pipe("infinite")
        child.stdin.close()
        finish(child, b"1\nread:\n")
        child = pipe("infinite")
        child.stdin.write(b"last")
        child.stdin.close()
        finish(child, b"1\nread:last\n")
        finish(pipe("invalid"), b"os: fd wait failed\n" if os.name == "nt"
               else b"net: socket error\n")

        # Redirected disk input is ready both before data and at EOF.
        disk = tmp / "input"
        disk.write_bytes(b"disk")
        with disk.open("rb") as stream:
            for expected in (b"1\nread:disk\n", b"1\nread:\n"):
                child = subprocess.Popen([str(app), "probe"], stdin=stream,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                finish(child, expected)
    print("fd_wait_read pipe/file smoke: PASS")


if __name__ == "__main__":
    main()
