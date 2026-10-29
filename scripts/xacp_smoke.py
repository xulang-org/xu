#!/usr/bin/env python3
"""Product XACP discovery/launcher regression; no external service required."""
import os
import json
from contextlib import contextmanager
import select
import socket
import time
from pathlib import Path
import subprocess
import sys
import tempfile

from xacp_cross_protocol_probe import probe, wait_listener
from xacp_screen_marshal_smoke import Attached, checked, example_path, run_screen_smoke, stdio_checks
from xacp_screen_marshal_smoke import frame as screen_frame, hello as screen_hello
from companion_repos import project_root
from xacp_frame import encode, split, read_frame, fd_reader
from xacp_frame_fuzz import run_frame_fuzz

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", ROOT / "bin/xu")).resolve()
TOOL = XU.with_name("xu-xacp" + XU.suffix)
BASE_ENV = os.environ.copy()
BASE_ENV.pop("XU_XACP_TOKEN", None)
BASE_ENV.pop("XU_XACP_ALLOW_RAW", None)
BASE_ENV.pop("XU_XACP_REQUEST_TIMEOUT_MS", None)
BASE_ENV.pop("XU_XACP_WRITE_TIMEOUT_MS", None)
BASE_ENV.pop("XU_XACP_HELLO_TIMEOUT_MS", None)
BASE_ENV.pop("XU_XACP_IDLE_TIMEOUT_MS", None)
BASE_ENV.pop("XU_XACP_NONCE_CACHE", None)
BASE_ENV.pop("XU_XACP_NONCE_REPLAY", None)


def run(args, code=0, env=BASE_ENV):
    p = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True,
                       text=True, timeout=180, env=env)
    assert p.returncode == code, (args, p.returncode, p.stdout, p.stderr)
    return p.stdout


@contextmanager
def deadline_stdio(app, **overrides):
    env = dict(BASE_ENV, XU_XACP_HELLO_TIMEOUT_MS="200", XU_XACP_IDLE_TIMEOUT_MS="1000")
    env.update(overrides)
    child = subprocess.Popen([str(app), "--xacp-stdio"], env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        yield child
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            try:
                stream.close()
            except OSError:
                # Closing a pipe can flush bytes after the timed-out child exits.
                pass


def request_id_checks(app):
    if os.name == "nt":
        print("XACP request id smoke: SKIP (POSIX pipe readiness required)")
        return
    cases = (
        ((screen_hello(token=""), 1, None),
         (screen_frame(2, "proc.status"), 2, None),
         (screen_frame(2, "proc.status"), 2, "invalid_request_id"),
         (screen_frame(1, "proc.status"), 1, "invalid_request_id"),
         (screen_frame(4, "proc.status"), 4, "invalid_request_id"),
         (screen_frame(3, "proc.status"), 3, None),
         (screen_frame(0, "proc.status"), 0, "invalid_request_id"),
         (screen_frame(-1, "proc.status"), -1, "invalid_request_id"),
         (screen_frame(4, "proc.status"), 4, None)),
        ((screen_frame(2, "xacp.hello", "\n  ver: !ver 1.0.0\n  nonce: id-smoke"),
          2, "invalid_request_id"),
         (screen_hello(token=""), 1, None),
         (screen_frame(2, "proc.status"), 2, None)),
    )
    for requests in cases:
        with deadline_stdio(app) as child:
            for payload, request_id, error in requests:
                child.stdin.write(payload)
                child.stdin.flush()
                response = checked(read_frame(fd_reader(child.stdout.fileno())), request_id, error)
                if error:
                    assert 'msg: "request id is not monotonic"\n' in response, response
                assert child.poll() is None, "request id error closed the session"
            child.stdin.close()
            assert child.wait(timeout=5) == 0
            assert child.stdout.read() == b"" and child.stderr.read() == b""
    with deadline_stdio(app) as child:
        child.stdin.write(screen_frame(-1, "unknown"))
        child.stdin.flush()
        checked(read_frame(fd_reader(child.stdout.fileno())), -1, "schema_error")
        assert child.wait(timeout=5) == 0
        assert child.stdout.read() == b"" and child.stderr.read() == b""
    print("XACP request id smoke: PASS")


def session_stdio_timeout_checks(app):
    if os.name == "nt":
        print("XACP session stdio timeout smoke: SKIP (POSIX descriptor waits required)")
        return

    def send(child, data):
        try:
            child.stdin.write(data)
            child.stdin.flush()
        except BrokenPipeError:
            # The deadline may close stdin before either write or flush finishes.
            # Callers still verify the expected response and session termination.
            pass

    def response(child, request_id, error=None):
        return checked(read_frame(fd_reader(child.stdout.fileno())), request_id, error)

    def eof(child):
        assert fd_reader(child.stdout.fileno())(1) == b"", "expected EOF after session timeout"
        assert child.wait(timeout=5) == 0
        assert child.stderr.read() == b""

    # Stdin remains open. Neither a partial header nor body renews hello time.
    for payload in (b"", b"XACP/1\n", screen_hello(token="")[:-1]):
        with deadline_stdio(app) as child:
            started = time.monotonic()
            send(child, payload[:len(payload) // 2])
            time.sleep(0.1)
            send(child, payload[len(payload) // 2:])
            result = response(child, 0, "hello_timeout")
            assert 'msg: "hello not completed within 200 ms"' in result, result
            assert 0.15 <= time.monotonic() - started < 2
            eof(child)

    # A recoverable failed hello also leaves the original deadline in place.
    with deadline_stdio(app) as child:
        send(child, screen_frame(2, "xacp.hello", "\n  ver: !ver 1.0.0\n  nonce: late"))
        response(child, 2, "invalid_request_id")
        response(child, 0, "hello_timeout")
        eof(child)

    # Complete business frames renew idle time; hello time no longer applies.
    with deadline_stdio(app) as child:
        send(child, screen_hello(token=""))
        response(child, 1)
        for request_id in (2, 3):
            time.sleep(0.6)
            send(child, screen_frame(request_id, "proc.status"))
            response(child, request_id)
        started = time.monotonic()
        result = response(child, 0, "session_idle")
        assert 'msg: "no complete frame for 1000 ms"' in result, result
        assert 0.9 <= time.monotonic() - started < 2.5
        eof(child)

    # Partial input cannot keep OPEN alive, including a nearly complete body.
    for partial in (b"XACP/1\n", screen_frame(2, "proc.status")[:-1]):
        with deadline_stdio(app) as child:
            send(child, screen_hello(token=""))
            response(child, 1)
            started = time.monotonic()
            time.sleep(0.65)
            send(child, partial)
            response(child, 0, "session_idle")
            assert 0.9 <= time.monotonic() - started < 1.6
            eof(child)

    with deadline_stdio(app, XU_XACP_IDLE_TIMEOUT_MS="0") as child:
        send(child, screen_hello(token=""))
        response(child, 1)
        time.sleep(1.1)
        send(child, screen_frame(2, "proc.status"))
        response(child, 2)
        child.stdin.close()
        eof(child)
    # Redirected regular files are readable too (Linux epoll would reject them).
    with tempfile.TemporaryFile() as source:
        source.write(screen_hello(token="") + screen_frame(2, "proc.status"))
        source.seek(0)
        result = subprocess.run([str(app), "--xacp-stdio"], stdin=source,
                                capture_output=True, timeout=5, env=BASE_ENV)
        assert result.returncode == 0 and not result.stderr, result
        responses = split(result.stdout)
        assert len(responses) == 2, responses
        checked(responses[0], 1)
        checked(responses[1], 2)
    print("XACP session stdio timeout smoke: PASS")


def session_request_timeout_checks(app):
    if os.name == "nt":
        return
    peer = Attached(app, timeout_ms="1400", idle_timeout_ms="1000", no_poll=True)
    try:
        peer.request(screen_hello(), 1)
        started = time.monotonic()
        peer.request(screen_frame(2, "ui.tree"), 2, "request_timeout")
        assert 1.3 <= time.monotonic() - started < 3
        checked(read_frame(fd_reader(peer.child.stdout.fileno())), 0, "session_idle")
        # The idle clock uses frame arrival, so it expires immediately after
        # the longer active request; no second full idle interval is granted.
        assert time.monotonic() - started < 2
        peer.finish()
    finally:
        peer.stop()
    peer = Attached(app, timeout_ms="700", idle_timeout_ms="1000", no_poll=True)
    try:
        peer.request(screen_hello(), 1)
        started = time.monotonic()
        # Both bodies arrive in one read. Dispatching the queued status after
        # the UI timeout must not give those old bytes a later arrival time.
        peer.request(screen_frame(2, "ui.tree") + screen_frame(3, "proc.status"), 2, "request_timeout")
        checked(read_frame(fd_reader(peer.child.stdout.fileno())), 3)
        checked(read_frame(fd_reader(peer.child.stdout.fileno())), 0, "session_idle")
        assert 0.9 <= time.monotonic() - started < 1.6
        peer.finish()
    finally:
        peer.stop()
    print("XACP request/idle timeout priority smoke: PASS")


def session_tcp_timeout_checks(app, port):
    env = dict(BASE_ENV, XU_XACP_HELLO_TIMEOUT_MS="200", XU_XACP_IDLE_TIMEOUT_MS="1000")
    server = subprocess.Popen([str(app), "--xacp-tcp"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        wait_listener(server, port)
        # Expiry is peer-local; the same listener then accepts normal traffic.
        for mode in ("hello", "idle", "normal"):
            with socket.create_connection(("127.0.0.1", port), timeout=3) as peer:
                if mode != "hello":
                    peer.sendall(screen_hello(token="", nonce=f"timeout-{mode}"))
                    checked(read_frame(peer.recv), 1)
                if mode == "normal":
                    peer.sendall(screen_frame(2, "proc.status"))
                    checked(read_frame(peer.recv), 2)
                    peer.shutdown(socket.SHUT_WR)
                else:
                    error = "hello_timeout" if mode == "hello" else "session_idle"
                    checked(read_frame(peer.recv), 0, error)
                assert peer.recv(1) == b""
            assert server.poll() is None
    finally:
        server.terminate()
        output, errors = server.communicate(timeout=5)
        assert not output and not errors, (output, errors)
    print("XACP session TCP timeout smoke: PASS")


def nonce_tcp_checks(app, port):
    """Each attempt uses a new peer on the same listener/process registry."""
    for policy in ({}, {"XU_XACP_NONCE_CACHE": "2"}, {"XU_XACP_NONCE_REPLAY": "0"}):
        env = dict(BASE_ENV, XU_XACP_TOKEN="nonce-token", **policy)
        server = subprocess.Popen([str(app), "--xacp-tcp"], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            wait_listener(server, port)

            def attempt(nonce, error=None, token="nonce-token", permissions=15):
                with socket.create_connection(("127.0.0.1", port), timeout=3) as peer:
                    payload = screen_hello(token, permissions, nonce)
                    # Coalesced later requests must never run after a fatal hello.
                    peer.sendall(payload + screen_frame(2, "proc.status"))
                    checked(read_frame(peer.recv), 1, error)
                    if error is None:
                        checked(read_frame(peer.recv), 2)
                        peer.shutdown(socket.SHUT_WR)
                    try:
                        assert peer.recv(1) == b"", "fatal hello left peer open or dispatched status"
                    except ConnectionResetError:
                        pass
                assert server.poll() is None

            if policy.get("XU_XACP_NONCE_REPLAY") == "0":
                attempt("reusable")
                attempt("reusable")
            elif policy.get("XU_XACP_NONCE_CACHE") == "2":
                attempt("oldest")
                attempt("second")
                attempt("oldest", "nonce_replay")
                attempt("failed", "auth_failed", token="wrong")
                attempt("failed", "schema_error", permissions=32)
                attempt("oldest", "nonce_replay")
                attempt("third")
                attempt("second", "nonce_replay")
                attempt("oldest")  # FIFO evicted it; rejected replay did not refresh it.
            else:
                attempt("same")
                attempt("same", "nonce_replay")
                attempt("different")
                attempt("auth-retry", "auth_failed", token="wrong")
                attempt("auth-retry")
                attempt("schema-retry", "schema_error", permissions=32)
                attempt("schema-retry")
                attempt("Case")
                attempt("case")
        finally:
            server.terminate()
            output, errors = server.communicate(timeout=5)
            assert not output and not errors, (output, errors)
    print("XACP cross-connection nonce replay smoke: PASS")


# The full example lives in https://github.com/xulang-org/examples/tree/main/examples/xacp.
# Keep only the launcher fixture and core session checks here so standalone Xu
# checkouts can still exercise control/TCP without fetching a companion repo.
FALLBACK_MAIN = """@main
#os

fn main() int {
    println("business-main")
    args := os.args()
    for i in 1:args.len {
        println("arg: " + args[i])
    }
    << 0
}
"""
FALLBACK_CORE = r"""@main
#xacp
#os
#strconv
#errors

fn check_setting(name string, actual int) int {
    text := os.getenv(name)
    if text.len == 0 { << 0 }
    expected := strconv.parse(&text, 10) or >>
    if actual != expected { >> errors.new("unexpected XACP setting") }
    << 0
}

fn check_core() int {
    limits := xacp.default_limits()
    $nonces := xacp.new_nonce_registry(xacp.DEFAULT_NONCE_CACHE, true)
    check_setting("XACP_EXPECT_TIMEOUT_MS", xacp.request_timeout_from_env()) or >>
    check_setting("XACP_EXPECT_HELLO_TIMEOUT_MS", xacp.hello_timeout_from_env()) or >>
    check_setting("XACP_EXPECT_IDLE_TIMEOUT_MS", xacp.idle_timeout_from_env()) or >>
    check_setting("XACP_EXPECT_NONCE_CACHE", xacp.nonce_cache_from_env()) or >>
    replay := os.getenv("XACP_EXPECT_NONCE_REPLAY")
    if replay.len > 0 && xacp.nonce_replay_from_env() != (replay == "1") { << 7 }
    $session := xacp.open_session()
    hello := xacp.parse_frame("id: !i 1\nop: xacp.hello\nargs:\n  ver: !ver 1.0.0\n  nonce: fallback-core\n") or (err) {
        eprintln(err.msg())
        << 1
    }
    opened := xacp.dispatch($&session, &hello, &limits, $&nonces)
    if !opened.ok {
        eprintln(opened.err_msg)
        << 2
    }
    status := xacp.parse_frame("id: !i 2\nop: proc.status\nargs: {}\n") or (err) {
        eprintln(err.msg())
        << 3
    }
    unimplemented := xacp.dispatch($&session, &status, &limits, $&nonces)
    if unimplemented.ok || unimplemented.err_code != "not_implemented" { << 4 }
    if xacp.enable_development($&session) { << 5 }
    xacp.close_session($&session)
    closed := xacp.dispatch($&session, &status, &limits, $&nonces)
    if closed.ok || closed.err_code != "session_closed" { << 6 }
    println("XACP core: PASS")
    << 0
}

fn main() int {
    << check_core() or (err) {
        eprintln(err.msg())
        << 1
    }
}
"""


def example_sources(tmp):
    main = example_path("main.xu")
    core = example_path("core/main.xu")
    if main.is_file() and core.is_file():
        print(f"XACP smoke sources: {main.parent}", flush=True)
        return main, core
    if os.environ.get("XU_EXAMPLES_ROOT"):
        raise FileNotFoundError(
            f"XU_EXAMPLES_ROOT needs examples/xacp/main.xu and core/main.xu: {project_root('examples')}")
    fixture = Path(tmp) / "fixture"
    (fixture / "core").mkdir(parents=True)
    main = fixture / "main.xu"
    core = fixture / "core/main.xu"
    main.write_text(FALLBACK_MAIN, encoding="utf-8")
    core.write_text(FALLBACK_CORE, encoding="utf-8")
    print("XACP smoke sources: embedded temporary fixture (full example moved to xulang-org/examples)", flush=True)
    return main, core


with tempfile.TemporaryDirectory(prefix="xu-xacp-smoke-") as tmp:
    main_source, core_source = example_sources(tmp)
    core = Path(tmp) / ("core.exe" if os.name == "nt" else "core")
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build",
         core_source, "-o", core])
    assert "XACP core: PASS" in run([core])
    # Parse boundaries, ASCII-only syntax and overflow without waiting 5s each.
    for value, expected in (("", 5000), ("abc", 5000), ("0", 5000), ("-5", 5000),
                            ("+3", 5000), (" 3", 5000), ("3\n", 5000), ("３", 5000),
                            ("600001", 5000), ("9" * 100, 5000), ("1", 1),
                            ("600000", 600000), ("000300", 300)):
        env = dict(BASE_ENV, XU_XACP_REQUEST_TIMEOUT_MS=value, XACP_EXPECT_TIMEOUT_MS=str(expected))
        assert "XACP core: PASS" in run([core], env=env), (value, expected)
    for name, cases in (
        ("HELLO", (("", 5000), ("0", 5000), ("1", 1), ("600000", 600000),
                   ("600001", 5000), ("000300", 300))),
        ("IDLE", (("", 60000), ("0", 0), ("000", 0), ("1", 60000),
                  ("999", 60000), ("1000", 1000), ("3600000", 3600000),
                  ("3600001", 60000), ("001000", 1000))),
    ):
        fallback = 5000 if name == "HELLO" else 60000
        invalid = ("abc", "-1", "+1000", " 1000", "1000 ", "1000\n", "１０００", "9" * 100)
        for value, expected in (*cases, *((v, fallback) for v in invalid)):
            env = dict(BASE_ENV, **{f"XU_XACP_{name}_TIMEOUT_MS": value,
                                    f"XACP_EXPECT_{name}_TIMEOUT_MS": str(expected)})
            assert "XACP core: PASS" in run([core], env=env), (name, value, expected)
    for value, expected in (("", 1024), ("0", 1024), ("1", 1), ("65536", 65536),
                            ("65537", 1024), ("0002", 2), ("abc", 1024), ("-1", 1024),
                            ("+2", 1024), (" 2", 1024), ("2 ", 1024), ("2\n", 1024),
                            ("２", 1024), ("9" * 100, 1024)):
        env = dict(BASE_ENV, XU_XACP_NONCE_CACHE=value, XACP_EXPECT_NONCE_CACHE=str(expected))
        assert "XACP core: PASS" in run([core], env=env), (value, expected)
    for value in ("", "0", "1", "00", "false", "0 "):
        env = dict(BASE_ENV, XU_XACP_NONCE_REPLAY=value,
                   XACP_EXPECT_NONCE_REPLAY="0" if value == "0" else "1")
        assert "XACP core: PASS" in run([core], env=env), value
    app = Path(tmp) / ("app.exe" if os.name == "nt" else "app")
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp",
         main_source, "-o", app])
    help_text = run([app, "--xacp-help"])
    assert "hello starts at 1" in help_text and "id not consumed" in help_text
    assert "ui.tree_data: win generation start count total truncated next_start nodes" in help_text
    assert all(text in help_text for text in ("nonce_replay", "XU_XACP_NONCE_CACHE",
                                             "XU_XACP_NONCE_REPLAY=0")), help_text
    run_frame_fuzz(app, BASE_ENV)
    request_id_checks(app)
    if sys.argv[1:] == ["--stdio-pagination-id-only"]:
        attached = Path(tmp) / ("attach.exe" if os.name == "nt" else "attach")
        run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp",
             example_path("attach/main.xu"), "-o", attached])
        stdio_checks(attached, TOOL)
        print("XACP pagination/id stdio smoke: PASS")
        sys.exit(0)
    session_stdio_timeout_checks(app)
    # Permit deterministic session coverage in sandboxes that prohibit sockets.
    if sys.argv[1:] == ["--stdio-timeouts-only"]:
        attached = Path(tmp) / ("attach.exe" if os.name == "nt" else "attach")
        run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp",
             example_path("attach/main.xu"), "-o", attached])
        session_request_timeout_checks(attached)
        sys.exit(0)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build", f"--xacp-port={port}",
         main_source, "-o", app])
    session_tcp_timeout_checks(app, port)
    nonce_tcp_checks(app, port)
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp-port=65536",
         main_source, "-o", app], code=1)
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp", "--target", "wasm32",
         main_source, "-o", Path(tmp) / "app.wasm"], code=1)
    assert "record" in run([TOOL, "--help"])
    assert "record" in run([XU, "help", "xacp"])
    for prefix in ([TOOL], [XU, "xacp"]):
        help_text = run([*prefix, "inspect", app])
        assert "capabilities: stdio" in help_text
        assert f"default_port: {port}" in help_text
        assert "tcp: enabled" in help_text
        assert f"bind: 127.0.0.1:{port}" in help_text
        assert "business-main" not in help_text
        assert "XU_XACP_REQUEST_TIMEOUT_MS" in help_text and "default 5000 ms" in help_text
        for mode in ("run", "debug"):
            out = run([*prefix, mode, app, "--", "--xacp-help", "hello world", ""])
            assert "business-main\narg: --\narg: --xacp-help\narg: hello world\narg: \n" in out
            assert out.count("capabilities: stdio") == (mode == "debug")
        run([*prefix, "run", app, "unprotected"], code=1)
        run([*prefix, "inspect", app, "ignored"], code=1)
        run([*prefix, "inspect", Path(tmp) / "missing"], code=1)
        if os.name != "nt":
            assert "arg: --xacp-help" in run([*prefix, "record", app, "--", "--xacp-help"])
    def frame(i, op, args="{}"):
        return encode(f"id: !i {i}\nop: {op}\nargs: {args}\n")

    LEGACY = b"--- !xacp\nid: !i 1\nop: proc.status\nargs: {}\n===\n"

    def nframes(out):
        return len(split(out))

    def hello(token=None, permissions=None, nonce="smoke-nonce", i=1):
        args = f"\n  ver: !ver 1.0.0\n  nonce: {nonce}"
        if token is not None:
            args += f"\n  token: {token}"
        if permissions is not None:
            args += f"\n  permissions: !i {permissions}"
        return frame(i, "xacp.hello", args)

    def environment(token=""):
        return dict(BASE_ENV, XU_XACP_TOKEN=token)

    def stdio(payload, token="", prefix=None, code=0):
        p = subprocess.run([str(x) for x in (prefix or [app, "--xacp-stdio"])],
                           input=payload, capture_output=True, timeout=30,
                           env=environment(token))
        assert p.returncode == code, (p.returncode, p.stdout, p.stderr)
        assert not p.stderr, p.stderr
        out = p.stdout.decode()
        assert "business-main" not in out
        return out

    def granted(response, permissions, nonce="smoke-nonce"):
        assert "ok: !b true" in response and "state: OPEN" in response, response
        assert f"permissions: !i {permissions}\n" in response, response
        assert f"nonce: {json.dumps(nonce, ensure_ascii=False)}\n" in response, response
        label = {0: "none", 1: "info", 31: "development"}.get(permissions, "custom")
        assert f"permission_label: {label}\n" in response, response

    ops = [("proc.status", "{}"), ("proc.output", "\n  stream: stdout"),
           ("ui.tree", "{}"), ("ui.screenshot", "\n  win: !i 1"),
           ("ui.input", "\n  win: !i 1\n  steps: []"),
           ("ui.act", "\n  win: !i 1\n  node: !i 1\n  act: click"),
           ("ui.record", "\n  win: !i 1\n  mode: events")]

    def requests(token="", nonce="smoke-nonce"):
        payload = hello(token=token or None, nonce=nonce)
        next_id = 2
        for op, args in ops:
            payload += frame(next_id, op, args)
            # Existing lifecycle: permission denial does not reserve an id.
            if token or op == "proc.status":
                next_id += 1
        return payload + frame(next_id, "proc.status")

    def checked_responses(response, token="", nonce="smoke-nonce"):
        assert nframes(response) == 9, response
        captured = bool(token) and os.name != "nt" and sys.maxsize > 2**32
        assert response.count("ok: !b true") == (4 if captured else 3), response
        expected_ids = list(range(1, 10)) if token else [1, 2] + [3] * 7
        for request_id, part in zip(expected_ids, split(response)):
            assert part.startswith(f"id: !i {request_id}\n"), part
        error = "not_implemented" if token else "permission_denied"
        assert response.count("code: " + error) == (5 if captured else 6), response
        granted(response, 15 if token else 1, nonce)
        assert "business-main" not in response

    prefixes = ([app, "--xacp-stdio"], [app, "--xacp-stdio", "--xacp-tcp"],
                [TOOL, "control", app], [XU, "xacp", "control", app])
    for token in ("", "smoke-host-token"):
        for prefix in prefixes:
            checked_responses(stdio(requests(token), token, prefix), token)

    # Negotiation is an intersection; client-supplied tokens cannot self-grant.
    for token in ("", "smoke-host-token"):
        for permissions in range(16):
            payload = hello(token="smoke-host-token", permissions=permissions)
            granted(stdio(payload, token), permissions if token else permissions & 1)
    granted(stdio(hello(token="ignored", permissions=15)), 1)
    granted(stdio(hello(), ""), 1)
    granted(stdio(hello(token="smoke-host-token"), "smoke-host-token"), 15)
    # XUN encoding must preserve quoting and prevent nonce response injection.
    for nonce in ('quote" and \\ slash', ' leading: value ',
                  'line\n===\ntrailer\r\t', '|\n|\n', "123", "!s tagged", "会话 nonce", "relative/path", "https://example.test/control", "n" * 65536):
        response = stdio(hello(nonce=json.dumps(nonce, ensure_ascii=False)))
        # Body may contain a literal \n===\n: length prefix keeps it one frame.
        assert nframes(response) == 1, response
        granted(response, 1, nonce)

    # Lifecycle errors after OPEN do not close the connection.
    recovery = (hello() + frame(1, "proc.status") + frame(2, "xacp.hello", "\n  ver: !ver 1.0.0\n  nonce: repeat") +
                frame(2, "ui.tree") + frame(2, "proc.status"))
    out = stdio(recovery)
    assert out.count("ok: !b true") == 2 and out.count("code: permission_denied") == 2, out
    assert "code: invalid_request_id" in out, out
    # Business error: echoes request id, stable code and bounded msg.
    assert 'id: !i 1\nok: !b false\nerror:\n  code: invalid_request_id\n  msg: "request id is not monotonic"\n' in split(out), out
    out = stdio(frame(5, "proc.status"))
    assert split(out) == ['id: !i 5\nok: !b false\nerror:\n  code: hello_required\n  msg: "first request must be xacp.hello"\n'], out
    out = stdio(frame(4, "unknown"))
    assert split(out)[0].startswith("id: !i 4\nok: !b false\nerror:\n  code: schema_error\n  msg: "), out
    # Literal envelope bytes inside a body round-trip as data, not framing.
    out = stdio(hello(nonce=json.dumps("a\n===\n--- !xacp\nid: !i 9\n===\nx", ensure_ascii=False)) + frame(2, "proc.status"))
    assert nframes(out) == 2 and "pid: !i " in out, out

    fatal = [
        (b"broken\n===\n", "frame_error", ""),
        (LEGACY, "frame_error", ""),
        (b"XACP/1\n0\n", "frame_error", ""),
        (b"XACP/1\n-3\nabc", "frame_error", ""),
        (b"XACP/2\n3\nabc", "frame_error", ""),
        (frame(1, "unknown"), "schema_error", ""),
        (frame(1, "proc.status"), "hello_required", ""),
        (frame(1, "xacp.hello", "\n  ver: !ver 1.0.0"), "schema_error", ""),
        (hello(nonce='""'), "schema_error", ""),
        (hello(nonce="!i 3"), "schema_error", ""),
        (hello(nonce="n" * 65537), "schema_error", ""),
        (hello(permissions=-1), "schema_error", ""),
        (hello(permissions=32), "schema_error", ""),
        (frame(1, "xacp.hello", "\n  ver: !ver 1.0.0\n  permissions: 3\n  nonce: smoke-nonce"), "schema_error", ""),
        (hello(permissions="bad"), "frame_error", ""),
        (hello(token="wrong"), "auth_failed", "smoke-host-token"),
        (hello(token='""'), "auth_failed", "smoke-host-token"),
        (hello(), "auth_failed", "smoke-host-token"),
    ]
    for payload, error, token in fatal:
        # A second valid hello in the same read must never be processed.
        out = stdio(payload + hello(token=token or None), token)
        assert nframes(out) == 1 and f"code: {error}\n" in out, (error, out)
        assert "state: OPEN" not in out, out
    for payload, error, token in fatal[:2]:
        # Fatal errors after OPEN close too; the following status must not run.
        out = stdio(hello() + payload + frame(2, "proc.status"))
        assert nframes(out) == 2 and f"code: {error}\n" in out, (error, out)
        assert "pid:" not in out, out
    assert "code: frame_error" in stdio(LEGACY)
    assert "code: truncated_frame" in stdio(b"XACP/1\n40\nid:")
    assert "code: truncated_frame" in stdio(b"XACP/1\n4")
    assert "code: frame_too_large" in stdio(b"XACP/1\n1048577\n" + b"x" * 64, code=1)
    # Existing invalid-id errors remain recoverable even before hello succeeds.
    out = stdio(hello(i=2) + hello())
    assert "code: invalid_request_id" in out
    granted(out, 1)
    # Exercise the checked-in control fixture with default INFO permissions.
    out = stdio(example_path("control.xun").read_bytes())
    assert out.count("code: permission_denied") == 2, out

    if os.name != "nt":
        # Keep stdin open: response/termination must not wait for EOF.
        child = subprocess.Popen([str(app), "--xacp-stdio"], env=BASE_ENV,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        try:
            for request in (hello(), frame(2, "proc.status"), frame(3, "ui.tree"),
                            frame(3, "proc.status"), LEGACY):
                data = request
                for start in range(0, len(data), 5):
                    child.stdin.write(data[start:start + 5])
                    child.stdin.flush()
                response = read_frame(fd_reader(child.stdout.fileno()))
                assert response.startswith("id: !i "), response
            assert "code: frame_error" in response
            assert child.wait(timeout=5) == 0
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()
            child.stderr.close()

    assert "arg: --xacp-stdio" in run([TOOL, "run", app, "--", "--xacp-stdio"])
    assert "business-main" in run([app, "ordinary", "--xacp-help-suffix"])
    assert "capabilities: stdio" in run([app, "ordinary", "--xacp-help"])

    def tcp(payload, eof=False):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
            peer.sendall(payload)
            if eof:
                peer.shutdown(socket.SHUT_WR)
            response = b""
            while True:
                try:
                    chunk = peer.recv(4096)
                except ConnectionResetError:
                    break
                if not chunk:
                    break
                response += chunk
                assert len(response) <= 1048576
            return response.decode()

    for token in ("", "smoke-host-token"):
        server = subprocess.Popen([str(app), "--xacp-tcp"], env=environment(token),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            wait_listener(server, port)
            for index, prefix in enumerate(([TOOL], [XU, "xacp"])):
                nonce = f"connect-{index}"
                p = subprocess.run([str(x) for x in [*prefix, "connect", port]],
                                   input=requests(token, nonce), capture_output=True,
                                   timeout=15, env=BASE_ENV)
                assert p.returncode == 0, (p.stdout, p.stderr)
                checked_responses(p.stdout.decode(), token, nonce)
                assert f"pid: !i {server.pid}" in p.stdout.decode()
            # Fragmented TCP writes must return responses before write-side EOF.
            with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
                for request in (hello(token=token or None, nonce="fragmented"), frame(2, "proc.status"),
                                frame(3, "ui.tree")):
                    data = request
                    for start in range(0, len(data), 5):
                        peer.sendall(data[start:start + 5])
                    response = read_frame(peer.recv)
                    assert response.startswith("id: !i "), response
            for payload, error, configured in fatal:
                if configured != token:
                    continue
                out = tcp(payload + hello(token=token or None))
                assert nframes(out) == 1 and f"code: {error}\n" in out, (error, out)
                assert "state: OPEN" not in out, out
            for payload, error in [(b"XACP/1\n99\nincomplete", "truncated_frame"),
                                   (b"XACP/1\n1048577\n" + b"x" * 64, "frame_too_large"),
                                   (LEGACY, "frame_error")]:
                out = tcp(payload, eof=error == "truncated_frame")
                assert nframes(out) == 1 and f"code: {error}\n" in out, (error, out)
            probe(port, token)
            # Both permission and fatal errors remain local to their own peer.
            checked_responses(tcp(requests(token, "recovered"), eof=True), token, "recovered")
            assert server.poll() is None
        finally:
            server.terminate()
            output, errors = server.communicate(timeout=5)
            assert not output and not errors, (output, errors)
    run([TOOL, "connect", "0"], code=1)
    run([TOOL, "connect", "65536"], code=1)
    disabled = Path(tmp) / ("disabled.exe" if os.name == "nt" else "disabled")
    run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp-port", "0",
         main_source, "-o", disabled])
    assert "tcp: disabled" in run([disabled, "--xacp-help"])
    run([disabled, "--xacp-tcp"], code=1)
    assert "business-main" in run([disabled])
    # Exit status and record budget are tested with executable local peers.
    if os.name != "nt":
        peer = Path(tmp) / "peer"
        peer.write_text("#!/bin/sh\nexit 7\n")
        peer.chmod(0o755)
        for mode in ("run", "record"):
            run([TOOL, mode, peer], code=7)
        peer.write_text("#!/bin/sh\nhead -c 1048576 /dev/zero\n")
        p = subprocess.run([str(TOOL), "record", str(peer)], capture_output=True, timeout=30)
        assert p.returncode == 0 and len(p.stdout) == 1048576
        peer.write_text("#!/bin/sh\nhead -c 1100000 /dev/zero\n")
        p = subprocess.run([str(TOOL), "record", str(peer)], capture_output=True, timeout=30)
        assert p.returncode != 0 and len(p.stdout) <= 1048576
        assert b"exceeded 1 MiB" in p.stderr
def timeout_checks():
    if os.name == "nt":
        print("XACP request timeout smoke: SKIP (POSIX pipe readiness required by this harness)")
        return
    with tempfile.TemporaryDirectory(prefix="xu-xacp-timeout-") as tmp:
        app = Path(tmp) / "attach"
        run([ROOT / "scripts/run_product_compiler.sh", XU, "build", "--xacp",
             example_path("attach/main.xu"), "-o", app])
        session_request_timeout_checks(app)
        for launcher in (None, TOOL):
            peer = Attached(app, launcher, timeout_ms="300", no_poll=True)
            try:
                peer.request(screen_hello(), 1)
                for i in (2, 4):
                    started = time.monotonic()
                    response = peer.request(screen_frame(i, "ui.tree"), i, "request_timeout")
                    elapsed = time.monotonic() - started
                    assert 0.25 <= elapsed < 2, elapsed
                    assert 'msg: "request exceeded 300 ms"' in response, response
                    assert "state: OPEN" in peer.request(screen_frame(i + 1, "proc.status"), i + 1)
                # EOF checks that no extra response was emitted for an expired id.
                peer.finish()
            finally:
                peer.stop()
        # Slow regression: invalid env must actually use the default deadline.
        peer = Attached(app, timeout_ms="abc", no_poll=True)
        try:
            peer.request(screen_hello(), 1)
            started = time.monotonic()
            response = peer.request(screen_frame(2, "ui.tree"), 2, "request_timeout")
            elapsed = time.monotonic() - started
            assert 4.5 <= elapsed < 7, elapsed
            assert 'msg: "request exceeded 5000 ms"' in response, response
            peer.request(screen_frame(3, "proc.status"), 3)
            peer.finish()
        finally:
            peer.stop()
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        server = Attached(app, port=port, timeout_ms="300", no_poll=True)
        try:
            wait_listener(server.child, port)
            # Expiry keeps this peer OPEN, and leaves no job for the next peer.
            for index in range(2):
                with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                    sock.sendall(screen_hello(nonce=f"request-timeout-{index}"))
                    checked(read_frame(sock.recv), 1)
                    for i, op, args in ((2, "ui.tree", "{}"),
                                        (4, "ui.screenshot", "\n  win: !i 1"),
                                        (6, "ui.act", "\n  win: !i 1\n  node: !i 2\n  act: click"),
                                        (8, "ui.input", "\n  win: !i 1\n  steps: []"),
                                        (10, "ui.record", "\n  win: !i 1\n  mode: events")):
                        started = time.monotonic()
                        sock.sendall(screen_frame(i, op, args))
                        checked(read_frame(sock.recv), i, "request_timeout")
                        assert 0.25 <= time.monotonic() - started < 2
                        sock.sendall(screen_frame(i + 1, "proc.status"))
                        checked(read_frame(sock.recv), i + 1)
            assert server.child.poll() is None
        finally:
            server.stop()
    print("XACP request timeout smoke: PASS")


timeout_checks()
run_screen_smoke(XU, TOOL)
print("XACP smoke: PASS")
