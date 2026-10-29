#!/usr/bin/env python3
"""Bounded XACP/1 transport regression: pass an already-built example app.

Usage: python3 scripts/xacp_frame_fuzz.py /path/to/xacp-example
XACP_FUZZ_SEED overrides the reproducible default seed (20261028).
"""
import argparse
import json
import os
from pathlib import Path
import random
import re
import selectors
import subprocess
import time

from xacp_frame import MAGIC, encode, split

DEFAULT_SEED = 20261028
MAX_CASES = 120
CASE_TIMEOUT = 5
MAX_FRAME_BYTES = 1048576
OUTPUT_LIMIT = 65536
FRAME_ERRORS = {"frame_error", "frame_too_large", "truncated_frame"}
FATAL_ERRORS = FRAME_ERRORS | {"schema_error"}


def request(request_id, op, args="{}"):
    return encode(f"id: !i {request_id}\nop: {op}\nargs: {args}\n")


def hello(nonce="frame-fuzz"):
    return request(1, "xacp.hello", "\n  ver: !ver 1.0.0\n  nonce: " +
                   json.dumps(nonce, ensure_ascii=False))


def exchange(app, env, chunks, keep_open=False, delay=0):
    """Pump both output pipes while writing; one deadline covers all I/O and exit.

    Fatal cases keep stdin open, so waiting for EOF in the server is a failure.
    Nonblocking writes also put large bodies and a non-reading peer under the
    deadline. Output is capped independently of the number of input bytes.
    """
    deadline = time.monotonic() + CASE_TIMEOUT
    child = subprocess.Popen([str(app), "--xacp-stdio"], env=env, bufsize=0,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    output, errors = bytearray(), bytearray()
    pending = iter(chunk for chunk in chunks if chunk)
    data = memoryview(next(pending, b""))
    try:
        with selectors.DefaultSelector() as poller:
            for stream, events, target in (
                (child.stdout, selectors.EVENT_READ, output),
                (child.stderr, selectors.EVENT_READ, errors),
                (child.stdin, selectors.EVENT_WRITE, None),
            ):
                os.set_blocking(stream.fileno(), False)
                poller.register(stream, events, target)
            while poller.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"case exceeded {CASE_TIMEOUT}s")
                for key, _ in poller.select(remaining):
                    if key.fileobj is child.stdin:
                        if not data:
                            poller.unregister(child.stdin)
                            if not keep_open:
                                child.stdin.close()
                            continue
                        try:
                            count = os.write(child.stdin.fileno(), data[:4096])
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            poller.unregister(child.stdin)
                            continue  # A fatal header may close before its tail.
                        assert count > 0, "stdin write made no progress"
                        data = data[count:]
                        if not data:
                            data = memoryview(next(pending, b""))
                            if data and delay:
                                time.sleep(delay)
                    else:
                        try:
                            part = os.read(key.fd, 4096)
                        except BlockingIOError:
                            continue
                        if not part:
                            poller.unregister(key.fileobj)  # Require stdout EOF.
                        else:
                            key.data.extend(part)
                            assert len(output) + len(errors) <= OUTPUT_LIMIT, "output budget exceeded"
            child.wait(timeout=max(0, deadline - time.monotonic()))
        assert child.returncode in (0, 1), ("crash/unexpected exit", child.returncode)
        assert not errors, bytes(errors)
        bodies = split(bytes(output))
        # split checks completeness/UTF-8; re-encoding also rejects malformed
        # magic, signed/empty/zero lengths and other noncanonical output.
        assert b"".join(encode(body) for body in bodies) == output, bytes(output)
        return bodies, child.returncode
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=1)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


def outcomes(bodies):
    result = []
    for body in bodies:
        match = re.match(r"id: !i (-?\d+)\nok: !b (true|false)\n", body)
        assert match, body
        error = None
        if match[2] == "false":
            code = re.search(r"^  code: ([a-z_]+)$", body, re.MULTILINE)
            assert code and "\nerror:\n" in body and "\n  msg: " in body, body
            error = code[1]
        else:
            assert "\ndata:\n" in body and "  state: OPEN\n" in body, body
        result.append((int(match[1]), error))
    return result


def fragments(data, rng):
    parts, pos = [], 0
    while pos < len(data):
        end = pos + rng.randint(1, 37)
        parts.append(data[pos:end])
        pos = end
    return parts


def run_frame_fuzz(app, env=None):
    if os.name == "nt":
        print("XACP frame fuzz: SKIP (POSIX pipe readiness required)")
        return
    seed = int(os.environ.get("XACP_FUZZ_SEED", DEFAULT_SEED))
    rng = random.Random(seed)
    # The harness owns the deadline; ambient auth/session timers must not
    # turn a transport failure into an unrelated authentication/timeout error.
    env = dict(os.environ if env is None else env, XU_XACP_TOKEN="",
               XU_XACP_REQUEST_TIMEOUT_MS="5000", XU_XACP_HELLO_TIMEOUT_MS="600000",
               XU_XACP_IDLE_TIMEOUT_MS="0")
    count = 0

    def case(name, chunks, expected=None, keep_open=False, delay=0, same_as=None, message=None):
        nonlocal count
        count += 1
        assert count <= MAX_CASES, "fuzz case budget exceeded"
        try:
            bodies, status = exchange(app, env, chunks, keep_open, delay)
            actual = outcomes(bodies)
            if expected is not None:
                assert actual == expected, ("responses", actual, expected, bodies)
            else:
                assert len(actual) <= 2, actual
                for index, (request_id, error) in enumerate(actual):
                    if error is None:
                        assert request_id == 1 and index == 0, actual
                    else:
                        assert error in FATAL_ERRORS and index == len(actual) - 1, actual
                        assert request_id in ({0, 1} if error == "schema_error" else {0}), actual
                assert actual or not any(chunks), "nonempty input closed without a response"
            # serve_control deliberately exits 1 for an oversized frame.
            assert status == int(any(error == "frame_too_large" for _, error in actual)), status
            if message is not None:
                assert len(bodies) == 1 and message in bodies[0], bodies
            # Separate child processes have different pids; all other response
            # bytes, including nonce escaping and errors, must be identical.
            normalized = [re.sub(r"^  pid: !i \d+$", "  pid: !i <pid>", body, flags=re.MULTILINE)
                          for body in bodies]
            if same_as is not None:
                assert normalized == same_as, ("fragmented responses differ", normalized, same_as)
            return normalized
        except Exception as exc:
            raise AssertionError(f"XACP frame fuzz FAIL seed={seed} case={count}:{name}: {exc}") from exc

    opening = hello()
    status_request = request(2, "proc.status")
    case("boundary-eof", [b""], [])
    case("hello-boundary-eof", [opening], [(1, None)])
    bad_headers = [
        ("bad-magic", b"broken\n1\nx", "frame_error"),
        ("version", b"XACP/2\n1\nx", "frame_error"),
        ("lowercase", b"xacp/1\n1\nx", "frame_error"),
        ("crlf-magic", b"XACP/1\r\n1\nx", "frame_error"),
        ("magic-line-limit", b"x" * 17, "frame_error"),
        ("length-line-limit", MAGIC + b"1" * 17, "frame_error"),
        ("max-plus-one", MAGIC + b"1048577\n", "frame_too_large"),
        ("eight-digit-overflow", MAGIC + b"99999999\n", "frame_too_large"),
    ]
    for length in (b"", b"abc", b"+5", b"-5", b" 5", b"5 ", b"5\r",
                   b"\xff", b"\x00", "５".encode(), b"0", b"00000000", b"000000001"):
        bad_headers.append((f"length-{length!r}", MAGIC + length + b"\n", "frame_error"))
    for name, payload, error in bad_headers:
        # A queued valid frame must never run after the fatal response.
        case(name, [payload + opening], [(0, error)], keep_open=True,
             message="frame header line too long" if name.endswith("line-limit") else None)
    # At 16 bytes EOF still wins: overflow is checked before appending byte 17.
    for name, partial in (
        ("magic", b"XAC"), ("magic-newline", MAGIC[:-1]), ("magic-limit", b"x" * 16),
        ("missing-length", MAGIC), ("length", MAGIC + b"12"),
        ("length-limit", MAGIC + b"1" * 16),
        ("missing-body", MAGIC + b"5\n"), ("body", MAGIC + b"5\nabc"),
        ("last-body-byte", opening[:-1]),
    ):
        case(f"eof-{name}", [partial], [(0, "truncated_frame")])
    case("open-eof-body", [opening + status_request[:-1]], [(1, None), (0, "truncated_frame")])
    case("open-fatal-tail", [opening + b"XACP/2\n" + status_request],
         [(1, None), (0, "frame_error")], keep_open=True)
    body = split(opening)[0].encode()
    for width in (4, 8):
        length = str(len(body)).encode().rjust(width, b"0")
        case(f"leading-zero-{width}-digits", [MAGIC + length + b"\n" + body],
             [(1, None)])
    case("maximum-body", [encode(b" " * MAX_FRAME_BYTES) + opening],
         [(0, "schema_error")], keep_open=True)
    # Syntax failures (including NUL rejected by XUN, not the transport) are
    # frame_error/id 0 in control_request. Only parsed invalid schemas use an
    # id hint. This distinction is more precise than the design's shorthand.
    for name, body, request_id, error, message in (
        ("schema-id", b"id: !i 7\nop: unknown\nargs: {}\n", 7, "schema_error", "unknown operation"),
        ("schema-no-id", b"op: proc.status\nargs: {}\n", 0, "schema_error", ""),
        ("syntax", b"id: !i bad\n", 0, "frame_error", "XUN parse error"),
        ("literal-delimiters", b"id: !i 7\n\n===\n--- !xacp\n", 0, "frame_error", "XUN parse error"),
        ("legacy-body", b"--- !xacp\nid: !i 7\nop: proc.status\nargs: {}\n===\n",
         0, "frame_error", "XUN parse error"),
        ("nul-body", b"id: !i 7\nop: proc.status\nargs: {}\n#\x00\n",
         0, "frame_error", "NUL byte is not allowed"),
        # XUN checks NUL before parsing lines. Seeing this diagnostic proves
        # bytes beyond both literal legacy delimiters reached the body parser.
        ("delimiters-before-nul", b"id: !i 7\n\n===\n--- !xacp\n#\x00\n",
         0, "frame_error", "NUL byte is not allowed"),
        ("invalid-utf8-body", b"id: !i 7\n#\xff\n", 0, "frame_error", "invalid UTF-8"),
    ):
        case(name, [encode(body) + opening], [(request_id, error)], keep_open=True, message=message)
    escaped = hello('a\n===\n--- !xacp\nid: !i 9\n===\nx')
    case("escaped-delimiters", [escaped + status_request], [(1, None), (2, None)])
    whole = case("coalesced", [opening + status_request], [(1, None), (2, None)])
    case("bytewise", [bytes([byte]) for byte in opening + status_request],
         [(1, None), (2, None)], same_as=whole)
    for cut in (3, len(MAGIC) + 1, len(opening) - 1):
        case(f"complete-later-{cut}", [opening[:cut], opening[cut:] + status_request],
             [(1, None), (2, None)], delay=0.02, same_as=whole)

    for index in range(16):
        nonce = rng.choice(("plain", "会话", 'quote"\\', "a\n===\n--- !xacp")) + str(index)
        size = rng.randint(2, 8)
        payload = hello(nonce) + b"".join(request(i, "proc.status") for i in range(2, size + 1))
        expected = [(i, None) for i in range(1, size + 1)]
        whole = case(f"sequence-{index}-whole", [payload], expected)
        case(f"sequence-{index}-fragmented", fragments(payload, rng), expected, same_as=whole)

    header_end = opening.index(b"\n", len(MAGIC)) + 1
    for index in range(30):
        mode = ("flip", "insert", "truncate")[index % 3]
        pos = rng.randrange(header_end)
        if mode == "flip":
            payload = opening[:pos] + bytes([opening[pos] ^ (1 << rng.randrange(8))]) + opening[pos + 1:]
        elif mode == "insert":
            payload = opening[:pos] + bytes([rng.randrange(256)]) + opening[pos:]
        else:
            payload = opening[:pos]
        case(f"mutate-{index}-{mode}-{pos}", fragments(payload, rng))
    print(f"XACP frame fuzz: PASS ({count} cases, seed={seed})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path, help="example app built with --xacp")
    run_frame_fuzz(parser.parse_args().app.resolve())
