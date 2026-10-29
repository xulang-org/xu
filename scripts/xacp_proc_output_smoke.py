#!/usr/bin/env python3
"""proc.output spec §7: raw bytes, bounded snapshots and pagination.

Runs all eight groups over direct stdio and xu-xacp attach, without a UI
owner. Also probes attach TCP when loopback is available, exclusive stdio,
absent capture, concurrent writers, environment bounds and escape expansion.
All pipe reads have deadlines.
"""
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

from xacp_frame import fd_reader, read_frame
from xacp_screen_marshal_smoke import checked, frame, hello

ROOT = Path(__file__).resolve().parents[1]
MAX_FRAME = 1048576
TOKEN = "output-smoke-token"
PREFIXES = (b"stdout-print\n", b"stderr-print\n")

FIXTURE = r'''@main

#os
#xacp
#errors

fn write_all(fd int,data &string) int {
    mut offset := 0
    while offset < data.len {
        n := os.fd_write(fd,data[offset:data.len]) or >>
        if n <= 0 { >> errors.new("output made no progress") }
        offset += n
    }
    << 0
}

fn worker(done chan int) {
    for i in 0:1000 {
        _ := os.fd_write(2,"worker-line\n") or (err) { done <- 1
            << }
    }
    done <- 0
}

fn main() int {
    out := read_file(os.getenv("XACP_OUTPUT_STDOUT")) or (err) { << 90 }
    err := read_file(os.getenv("XACP_OUTPUT_STDERR")) or (err) { << 91 }
    println("stdout-print")
    write_all(1,&out) or (err) { << 92 }
    eprintln("stderr-print")
    write_all(2,&err) or (err) { << 93 }
    port := os.getenv("XACP_OUTPUT_TCP")
    if port.len > 0 {
        number := parse_int(port) or (err) { << 94 }
        control := xacp.attach_tcp(number) or (err) { << 95 }
        << <-control.done
    }
    control := xacp.attach_stdio()
    if os.getenv("XACP_OUTPUT_CONCURRENT") == "1" {
        done := chan int{cap: 2}
        xu worker(done)
        xu worker(done)
        _ := <-done
        _ := <-done
    }
    << <-control.done
}
'''


def run(command):
    result = subprocess.run([str(x) for x in command], cwd=ROOT,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, (command, result.stdout, result.stderr)
    return result.stdout


def exact(fd, size):
    read = fd_reader(fd, 15)
    data = bytearray()
    while len(data) < size:
        chunk = read(size - len(data))
        assert chunk, ("unexpected output EOF", len(data), size)
        data.extend(chunk)
    return bytes(data)


def decode_string(text):
    """XUN quoted bytes: preserve UTF-8 literals; decode each escape to bytes."""
    assert text.startswith('"') and text.endswith('"'), text[:100]
    text = text[1:-1]
    out = bytearray()
    i = 0
    escapes = {'n': 10, 'r': 13, 't': 9, '"': 34, '\\': 92}
    while i < len(text):
        if text[i] != '\\':
            out.extend(text[i].encode('utf-8'))
            i += 1
            continue
        i += 1
        assert i < len(text), text
        if text[i] == 'x':
            out.append(int(text[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(escapes[text[i]])
            i += 1
    return bytes(out)


def page(response):
    values = dict(re.findall(r'^  (\w+): (.+)$', response, re.M))
    assert set(values) == {'stream', 'since', 'count', 'total', 'base', 'dropped',
                           'truncated', 'next_since', 'data'}, values
    result = {k: int(values[k].removeprefix('!i ')) for k in
              ('since', 'count', 'total', 'base', 'dropped', 'next_since')}
    result['data'] = decode_string(values['data'])
    result['stream'] = values['stream']
    assert values['truncated'] in ('!b true', '!b false'), values
    result['truncated'] = values['truncated'] == '!b true'
    assert result['count'] == len(result['data'])
    assert result['next_since'] == result['since'] + result['count']
    assert result['truncated'] == (result['next_since'] < result['total'])
    assert 0 <= result['base'] <= result['since'] <= result['next_since'] <= result['total']
    return result


class Peer:
    def __init__(self, app, launcher, directory, stdout=b'', stderr=b'', *,
                 capacity='', permissions=15, token=TOKEN, concurrent=False):
        out_file, err_file = directory / 'stdout.bin', directory / 'stderr.bin'
        out_file.write_bytes(stdout)
        err_file.write_bytes(stderr)
        self.expected = (PREFIXES[0] + stdout, PREFIXES[1] + stderr)
        env = dict(os.environ, XU_XACP_TOKEN=token, XU_XACP_ALLOW_RAW='',
                   XU_XACP_OUTPUT_BUFFER=capacity, XU_XACP_HELLO_TIMEOUT_MS='10000',
                   XU_XACP_IDLE_TIMEOUT_MS='60000', XU_XACP_REQUEST_TIMEOUT_MS='',
                   XU_XACP_NONCE_CACHE='', XU_XACP_NONCE_REPLAY='',
                   XACP_OUTPUT_STDOUT=str(out_file), XACP_OUTPUT_STDERR=str(err_file),
                   XACP_OUTPUT_CONCURRENT='1' if concurrent else '')
        self.socket = None
        self.tcp_port = None
        if launcher == 'tcp':
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0))
                self.tcp_port = reserve.getsockname()[1]
            env['XACP_OUTPUT_TCP'] = str(self.tcp_port)
        else:
            env['XACP_OUTPUT_TCP'] = ''
        command = [app] if launcher in (None, 'tcp') else [launcher, 'attach', app]
        self.child = subprocess.Popen([str(x) for x in command], cwd=ROOT, env=env,
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
        self.next_id = 1
        self.drain = None
        self.concurrent_bytes = None
        try:
            # Real stdout/stderr remain byte-for-byte intact. Drain before
            # starting framing; business main writes these before attaching.
            assert exact(self.child.stdout.fileno(), len(self.expected[0])) == self.expected[0]
            assert exact(self.child.stderr.fileno(), len(self.expected[1])) == self.expected[1]
            if self.tcp_port:
                deadline = time.monotonic() + 10
                while self.socket is None:
                    try:
                        self.socket = socket.create_connection(('127.0.0.1', self.tcp_port), timeout=2)
                    except ConnectionRefusedError:
                        assert self.child.poll() is None and time.monotonic() < deadline, 'TCP attach did not listen'
                        time.sleep(0.01)
                self.socket.settimeout(15)
            if concurrent:
                def drain():
                    self.concurrent_bytes = exact(self.child.stderr.fileno(), 24000)
                self.drain = threading.Thread(target=drain, daemon=True)
                self.drain.start()
            self.request(hello(token, permissions), 1)
            self.next_id = 2
        except BaseException:
            self.stop()
            raise

    def request(self, payload, request_id, error=None):
        if self.socket:
            self.socket.sendall(payload)
            body = read_frame(self.socket.recv)
        else:
            self.child.stdin.write(payload)
            self.child.stdin.flush()
            body = read_frame(fd_reader(self.child.stdout.fileno(), 15))
        assert len(body.encode()) <= MAX_FRAME, len(body.encode())
        return checked(body, request_id, error)

    def output(self, stream='stdout', since=0, maximum=None, error=None):
        args = f'\n  stream: {stream}\n  since: !i {since}'
        if maximum is not None:
            args += f'\n  max_bytes: !i {maximum}'
        result = self.request(frame(self.next_id, 'proc.output', args), self.next_id, error)
        if error not in ('schema_error', 'permission_denied'):
            self.next_id += 1
        return result if error else page(result)

    def status(self):
        self.request(frame(self.next_id, 'proc.status'), self.next_id)
        self.next_id += 1

    def finish(self):
        if self.drain:
            self.drain.join(timeout=15)
            assert not self.drain.is_alive()
            assert self.concurrent_bytes == b'worker-line\n' * 2000
        if self.socket:
            self.socket.shutdown(socket.SHUT_WR)
            assert self.socket.recv(1) == b''
            self.socket.close()
            self.socket = None
            assert self.child.poll() is None, 'peer EOF killed TCP listener'
            self.child.terminate()
            self.child.wait(timeout=5)
        else:
            self.child.stdin.close()
            assert self.child.wait(timeout=15) == 0
        assert self.child.stdout.read() == b'' and self.child.stderr.read() == b''

    def stop(self):
        if self.socket:
            self.socket.close()
            self.socket = None
        if self.child.poll() is None:
            self.child.kill()
            self.child.wait(timeout=5)
        for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
            if stream and not stream.closed:
                stream.close()


def collect(peer, stream, maximum, since=0):
    out = bytearray()
    for _ in range(100000):
        current = peer.output(stream, since, maximum)
        assert current['stream'] == stream
        out.extend(current['data'])
        since = current['next_since']
        if not current['truncated']:
            assert since == current['total']
            return bytes(out), current
        assert current['count'] > 0
    raise AssertionError('pagination failed to make progress')


def exercise(app, launcher, directory):
    # §7.1,2,4,7,8: isolate streams, paginate exact raw bytes, include binary,
    # UTF-8 split at byte boundaries, and ensure control frames never recur.
    binary = b'line\n"\\\x00\xff\r\t\x01\x7f' + '中文🙂'.encode() + bytes(range(256))
    peer = Peer(app, launcher, directory, b'known stdout\n' + binary, b'known stderr\n' + binary[::-1])
    try:
        for stream, expected in zip(('stdout', 'stderr'), peer.expected):
            initial = peer.output(stream)
            assert initial['data'] == expected and initial['since'] == initial['base'] == initial['dropped'] == 0
            assert initial['total'] == len(expected) and not initial['truncated']
            assert collect(peer, stream, 3)[0] == expected
            empty = peer.output(stream, len(expected))
            assert empty['data'] == b'' and empty['count'] == 0 and not empty['truncated']
            beyond = peer.output(stream, len(expected) + 1, error='adapter_error')
            assert 'msg: "since beyond end of stream"' in beyond
            peer.status()  # next id on the same connection succeeds
            again = peer.output(stream)
            assert again['data'] == expected and again['total'] == len(expected)
        # §7.6: bounds, required fields and types retain schema_error and id;
        # these argument errors in OPEN are recoverable without consuming id.
        for args in ('\n  stream: stdout\n  max_bytes: !i 0',
                     f'\n  stream: stdout\n  max_bytes: !i {MAX_FRAME + 1}',
                     '\n  stream: other', '\n  stream: stdout\n  since: !i -1',
                     '\n  stream: stdout\n  since: !b true',
                     '\n  stream: stdout\n  max_bytes: !s "1"', '{}'):
            peer.request(frame(peer.next_id, 'proc.output', args), peer.next_id, 'schema_error')
            peer.status()
        peer.finish()
    finally:
        peer.stop()

    # §7.3: both independent rings drop oldest, and absolute offsets survive
    # wraparound and a write larger than capacity. since<base never errors.
    peer = Peer(app, launcher, directory, bytes(range(256)) * 37,
                b'stderr-overflow-' * 650, capacity='4096')
    try:
        for stream, expected in zip(('stdout', 'stderr'), peer.expected):
            current = peer.output(stream, maximum=MAX_FRAME)
            base = len(expected) - 4096
            assert current['since'] == current['base'] == current['dropped'] == base > 0
            assert current['data'] == expected[-4096:] and current['total'] == len(expected)
            assert collect(peer, stream, 127)[0] == expected[-4096:]
            last = peer.output(stream, len(expected) - 1, 1)
            assert last['data'] == expected[-1:] and last['dropped'] == 0
        peer.finish()
    finally:
        peer.stop()

    # §7.5: denial preserves connection/id, both default INFO and explicit INFO.
    for token in ('', TOKEN):
        peer = Peer(app, launcher, directory, permissions=1, token=token)
        try:
            peer.output(error='permission_denied')
            peer.status()
            peer.finish()
        finally:
            peer.stop()

    # The client requests raw bytes, so even a valid max_bytes may expand past
    # the frame limit. Automatically shrink, signal truncation, and finish.
    peer = Peer(app, launcher, directory, b'\xff' * 300000,
                b'\x00' * 300000, capacity=str(MAX_FRAME))
    try:
        for stream, expected in zip(('stdout', 'stderr'), peer.expected):
            first = peer.output(stream, maximum=MAX_FRAME)
            assert 1 <= first['count'] < len(expected) and first['truncated']
            assert first['data'] == expected[:first['count']]
            rest, _ = collect(peer, stream, MAX_FRAME, first['next_since'])
            assert first['data'] + rest == expected
        peer.finish()
    finally:
        peer.stop()
    label = 'stdio' if launcher is None else ('attach TCP' if launcher == 'tcp' else 'attach')
    print(f'XACP proc.output smoke ({label}): PASS (8 spec groups + frame fitting)')


def extra_checks(app, plain, tool, directory):
    # Invalid capacities match the nonce-cache decimal parser, including
    # overflow. Default retains 64 KiB; maximum capacity is accepted as well.
    for capacity in ('', 'bad', '-1', '4095', '16777217', '9' * 40, ' 4096', '16777216'):
        peer = Peer(app, None, directory, b'A' * 70000, capacity=capacity)
        try:
            expected = peer.expected[0]
            current = peer.output(maximum=MAX_FRAME)
            retained = len(expected) if capacity == '16777216' else 65536
            assert current['base'] == len(expected) - retained
            assert current['data'] == expected[-retained:]
            peer.finish()
        finally:
            peer.stop()
    # Exclusive startup stdio never runs main and never captures control frames.
    env = dict(os.environ, XU_XACP_TOKEN=TOKEN, XU_XACP_OUTPUT_BUFFER='')
    args = '\n  stream: stdout'
    child = subprocess.run([str(app), '--xacp-stdio'],
                           input=hello(TOKEN) + frame(2, 'proc.output', args) + frame(3, 'proc.output', args),
                           capture_output=True, env=env, timeout=15)
    from xacp_frame import split
    assert child.returncode == 0 and child.stderr == b'', child
    responses = split(child.stdout)
    assert len(responses) == 3
    checked(responses[0], 1)
    for i, response in enumerate(responses[1:], 2):
        result = page(checked(response, i))
        assert result['data'] == b'' and result['total'] == 0
    # A host built without the startup capture seam keeps not_implemented.
    peer = Peer(plain, tool, directory)
    try:
        peer.output(error='not_implemented')
        peer.status()
        peer.finish()
    finally:
        peer.stop()
    # Multiple writer coroutines share a stream while control snapshots it;
    # no Screen registration/poll is involved and the stream remains exact.
    for launcher in (None, tool):
        peer = Peer(app, launcher, directory, concurrent=True)
        try:
            expected = peer.expected[1] + b'worker-line\n' * 2000
            previous_total = 0
            deadline = time.monotonic() + 15
            while True:
                current = peer.output('stderr', maximum=MAX_FRAME)
                assert previous_total <= current['total'] <= len(expected)
                previous_total = current['total']
                assert current['data'] == expected[:current['count']]
                if current['total'] == len(expected):
                    assert current['data'] == expected
                    break
                assert time.monotonic() < deadline, current
            peer.finish()
        finally:
            peer.stop()
    print('XACP proc.output capacity bounds, exclusive stdio, absent capture and concurrent writers: PASS')


def main():
    if os.name == 'nt' or sys.maxsize <= 2**32:
        print('XACP proc.output smoke: SKIP (64-bit POSIX fd capture and readiness required)')
        return
    xu = Path(os.environ.get('XU', ROOT / 'bin/xu')).resolve()
    tool = xu.with_name('xu-xacp' + xu.suffix)
    with tempfile.TemporaryDirectory(prefix='xu-xacp-output-') as tmp:
        directory = Path(tmp)
        source = directory / 'main.xu'
        source.write_text(FIXTURE)
        app, plain = directory / 'output', directory / 'plain'
        run([ROOT / 'scripts/run_product_compiler.sh', xu, 'build', '--xacp', source, '-o', app])
        run([ROOT / 'scripts/run_product_compiler.sh', xu, 'build', source, '-o', plain])
        for launcher in (None, tool):
            exercise(app, launcher, directory)
        extra_checks(app, plain, tool, directory)
        try:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
        except PermissionError as error:
            print(f'XACP proc.output attach TCP: SKIP (sandbox denies loopback socket/bind: {error})')
        else:
            exercise(app, 'tcp', directory)


if __name__ == '__main__':
    main()
