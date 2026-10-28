"""XACP/1 length-prefixed framing helpers shared by the smoke tests."""
import os
import select
import time

MAGIC = b"XACP/1\n"


def encode(body):
    data = body.encode() if isinstance(body, str) else body
    return MAGIC + str(len(data)).encode() + b"\n" + data


def split(data):
    """Split a byte/str stream of complete XACP/1 frames into body strings."""
    if isinstance(data, str):
        data = data.encode()
    out, pos = [], 0
    while pos < len(data):
        assert data.startswith(MAGIC, pos), data[pos:pos + 64]
        pos += len(MAGIC)
        nl = data.index(b"\n", pos)
        n = int(data[pos:nl])
        pos = nl + 1
        body = data[pos:pos + n]
        assert len(body) == n, ("truncated response", data)
        out.append(body.decode())
        pos += n
    return out


def complete(data):
    """Return True if data holds at least one complete frame."""
    if not data.startswith(MAGIC):
        return False
    nl = data.find(b"\n", len(MAGIC))
    if nl < 0:
        return False
    return len(data) - nl - 1 >= int(data[len(MAGIC):nl])


def read_frame(read, timeout=5):
    """read(n) -> bytes. Reads exactly one frame and returns its body."""
    buf = b""
    while not buf.endswith(b"\n") or buf.count(b"\n") < 2:
        c = read(1)
        assert c, buf
        buf += c
    n = int(buf.split(b"\n")[1])
    body = b""
    while len(body) < n:
        c = read(n - len(body))
        assert c, body
        body += c
    return body.decode()


def fd_reader(fd, timeout=5):
    deadline = time.monotonic() + timeout

    def read(n):
        ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        assert ready, "control response stalled"
        return os.read(fd, n)
    return read
