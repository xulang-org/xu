#!/usr/bin/env python3
"""Public native library/network/concurrency fixtures for platform_test.sh.

Every compiled artifact must execute and match stdout, stderr and exit status.
No Docker, Wine, emulation or ignored tests/ corpus is needed by this gate.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import platform
import socket
import ssl
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = tuple(f"{os_name}-{arch}" for os_name in ("linux", "macos", "windows") for arch in ("x64", "arm64"))


def native_target() -> str:
    system = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform.system())
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    return f"{system}-{arch}"


def compiler_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("XU")}
    env.update(XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / "src"), XUPATH="")
    return env


LIBRARY = r'''@main
#os
#path/filepath
#time
#crypto/sha256
#crypto/rand
#encoding/json
fn literal_values() []int {
    << [0, 1, 2, 3, 4, 5, 6, 7]
}
fn main() int {
    // Separate evaluations must own separate storage, including literals
    // whose constant elements can be initialized from a compiler data pool.
    $first := literal_values()
    $second := literal_values()
    first[0] = 99
    if second[0] != 0 { << 12 }
    second[7] = 88
    $third := literal_values()
    if third[0] != 0 || third[7] != 7 || first[7] != 7 { << 13 }
    third.push(8)
    if third.len != 9 || third[8] != 8 || second[7] != 88 { << 14 }
    os.write("roundtrip", "Xu\nbytes") or (err) { eprintln(err.msg())
        << 1 }
    body := os.read("roundtrip") or (err) { eprintln(err.msg())
        << 2 }
    if body != "Xu\nbytes" { << 3 }
    path := "a/../b/./c"
    clean := filepath.clean(&path)
    slash := filepath.to_slash(&clean)
    if slash != "b/c" { << 4 }
    if sha256.sum256("abc") != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" { << 5 }
    bytes := rand.read(32) or (err) { eprintln(err.msg())
        << 6 }
    if bytes.len != 32 { << 7 }
    text := "{\"value\":42}"
    doc := json.parse(&text)
    if !doc.ok() { << 8 }
    value := doc.as_int(doc.get(doc.root(), "value")) or (err) { << 10 }
    if value != 42 { << 11 }
    if time.now() <= 0 { << 9 }
    println("library passed")
    << 0
}
'''

OPTIMIZED_CODE = r'''@main
#crypto/aes
#crypto/sha256
#encoding/hex
#math/bits

struct Counter {
    value int
}

fn (c $&Counter) add(n int) {
    c.value += n
}

fn rejects_invalid_hex() bool {
    _ := hex.decode_string("0123456789ABCDEFg123456789abcdef") or (err) { << true }
    << false
}

fn gcd(a int, b int) int {
    if b == 0 { << a }
    << gcd(b, a % b)
}

fn main() int {
    $counter := Counter{value: 3}
    $sum := 5
    $i := 3
    while i < 35 {
        sum += i & 7
        i += 1
    }
    counter.add(sum)
    if i != 35 || counter.value != 120 { << 1 }

    // The later read uses the incremented i and cannot be folded as above.
    i = 0
    sum = 0
    while i < 9 {
        i += 1
        sum += i & 7
    }
    if sum != 29 { << 2 }
    if gcd(1071, 462) != 21 { << 16 }

    if bits.len(0) != 0 || bits.leading_zeros(0) != 64 || bits.trailing_zeros(0) != 64 { << 3 }
    if bits.ones_count(-1) != 64 || bits.reverse(1) != (1 << 63) { << 4 }
    if bits.rotate_left(1, -1) != (1 << 63) || bits.rotate_right(1, 64) != 1 { << 5 }

    // Exercise a SIMD block plus a scalar tail, mixed case and bad bytes.
    bytes := hex.decode_string("0123456789ABCDEF0123456789abcdefF0") or (err) { << 6 }
    if hex.encode_to_string(bytes + "") != "0123456789abcdef0123456789abcdeff0" { << 7 }
    if !rejects_invalid_hex() { << 8 }

    key := hex.decode_string("000102030405060708090a0b0c0d0e0f") or (err) { << 9 }
    plain := hex.decode_string("00112233445566778899aabbccddeeff") or (err) { << 10 }
    cipher := aes.new_cipher(&key) or (err) { << 11 }
    encrypted := cipher.encrypt(&plain) or (err) { << 12 }
    if hex.encode_to_string(encrypted + "") != "69c4e0d86a7b0430d8cdb78070b4c55a" { << 13 }
    recovered := cipher.decrypt(&encrypted) or (err) { << 14 }
    if recovered != plain { << 15 }
    if sha256.sum256("abc") != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" { << 17 }
    println("optimized code passed")
    << 0
}
'''


CONCURRENCY = r'''@main
fn worker(ch chan string, value int) {
    $values := map[string]int{}
    for i in 0:64 { values["key-" + str(i)] = value + i }
    sleep_ns(1000000)
    ch <- str(values["key-63"])
}
fn probe(capacity int) int {
    ch := chan string{cap: capacity}
    for i in 0:32 { xu worker(ch, i) }
    $total := 0
    for i in 0:32 {
        value := <-ch
        n := parse_int(value) or (err) { << -1 }
        total += n
    }
    << total
}
fn main() int {
    for round in 0:4 {
        if probe(0) != 2512 { << 2 }
        if probe(32) != 2512 { << 4 }
    }
    println("concurrency passed")
    << 0
}
'''

STREAM = r'''@main
#net
fn probe(network string, address string) int {
    $conn := net.dial_to(network, address) or >>
    data := "Xu stream probe"
    $sent := 0
    while sent < data.len {
        part := data[sent:data.len]
        n := conn.write(&part) or >>
        if n <= 0 || n > part.len { << 2 }
        sent += n
    }
    $reply := ""
    while reply.len < data.len {
        part := conn.read(data.len - reply.len) or >>
        if part.len == 0 { << 3 }
        reply = reply + part
    }
    conn.close() or >>
    if reply != data { << 4 }
    println("stream passed")
    << 0
}
fn main() int {
    a := args()
    << probe(a[1] + "", a[2] + "") or (err) { eprintln(err.msg())
        << 1 }
}
'''

UDP = r'''@main
#net
fn probe(address string, connected bool) int {
    remote := net.resolve_udp_addr("udp4", address) or >>
    local := net.UDPAddr{ip: net.ipv4(127, 0, 0, 1), port: 0, zone: ""}
    data := "Xu datagram"
    if connected {
        $c := net.dial_udp("udp4", local.clone(), remote.clone()) or >>
        if (c.write(&data) or >>) != data.len { << 2 }
        reply := c.read(128) or >>
        c.close() or >>
        if reply != data { << 3 }
    } else {
        $c := net.listen_udp("udp4", local.clone()) or >>
        if (c.write_to(&data, &remote) or >>) != data.len { << 4 }
        reply := c.read_from(128) or >>
        c.close() or >>
        if reply.data != data || reply.addr.port != remote.port { << 5 }
    }
    println("udp passed")
    << 0
}
fn main() int {
    a := args()
    << probe(a[1] + "", a[2] == "connected") or (err) { eprintln(err.msg())
        << 1 }
}
'''

INTERFACES = r'''@main
#net
fn probe() int {
    all := net.interfaces() or >>
    if all.len == 0 { << 2 }
    $addresses := 0
    for i in 0:all.len {
        item := all[i]
        if item.name.len == 0 || item.index <= 0 { << 3 }
        found := net.interface_by_name(item.name + "") or >>
        if found.index != item.index { << 4 }
        ips := item.addrs() or >>
        addresses += ips.len
    }
    if addresses == 0 { << 5 }
    println("interfaces passed")
    << 0
}
fn main() int {
    << probe() or (err) { eprintln(err.msg())
        << 1 }
}
'''

WINDOWS_UNIX = r'''@main
#net
fn main() int {
    _ := net.dial_to("unix", "unsupported.sock") or (err) {
        if err.msg() != "net: unix sockets are not available on this target" { eprintln(err.msg())
            << 2 }
        println("unsupported Unix socket rejected")
        << 0
    }
    << 1
}
'''

NET_CONTRACT = r'''@main
#net
fn invalid_network() bool {
    _ := net.dial_to("invalid", "127.0.0.1:1") or (err) { << true }
    << false
}
fn invalid_socket() bool {
    _ := net.conn_read(-1, 1) or (err) { << true }
    << false
}
fn probe() int {
    port := net.lookup_port("tcp", "http") or >>
    protocol := net.lookup_protocol("tcp") or >>
    if port != 80 { << 2 }
    if protocol != 6 { << 3 }
    if !invalid_network() || !invalid_socket() { << 4 }
    println("network contracts passed")
    << 0
}
fn main() int {
    << probe() or (err) { eprintln(err.msg())
        << 1 }
}
'''


def checked_run(command: list[str], *, cwd: Path, env: dict[str, str], expected: bytes) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=45)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{command}: runtime timeout; stdout={error.stdout!r}, stderr={error.stderr!r}") from error
    if result.returncode != 0 or result.stdout != expected or result.stderr:
        raise RuntimeError(f"{command}: exit={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--target", required=True, choices=TARGETS)
    args = parser.parse_args()
    if args.target != native_target():
        parser.error(f"native execution required: host={native_target()}, requested={args.target}")
    compiler = str(args.compiler.resolve())
    env = compiler_env()
    # Windows can retain mappings briefly after process exit.
    from test_windows_workers import WindowsTemporaryDirectory
    with WindowsTemporaryDirectory(prefix="xu-platform-") as temporary:
        work = Path(temporary)
        env.update(XU_CACHE=str(work / "cache"), HOME=str(work), USERPROFILE=str(work))

        def build(name: str, source: str, *flags: str) -> Path:
            path = work / f"{name}.xu"
            path.write_text(source, encoding="utf-8", newline="\n")
            binary = work / (name + (".exe" if os.name == "nt" else ""))
            subprocess.run([compiler, "build", *flags, str(path), "--target", args.target, "-o", str(binary)],
                           cwd=work, env=env, check=True, timeout=180)
            return binary

        def run(name: str, binary: Path, *arguments: str, expected: str) -> None:
            checked_run([str(binary), *arguments], cwd=work, env=env, expected=(expected + "\n").encode())
            print(f"PASS {name}/{args.target} (executed)", flush=True)

        run("library", build("library", LIBRARY), expected="library passed")
        run("optimized_code", build("optimized_code", OPTIMIZED_CODE), expected="optimized code passed")
        run("optimized_code/no-opt", build("unoptimized_code", OPTIMIZED_CODE, "--no-opt"),
            expected="optimized code passed")
        run("chan_parallel/channel_blocking_string", build("concurrency", CONCURRENCY), expected="concurrency passed")
        run("net_interfaces", build("interfaces", INTERFACES), expected="interfaces passed")
        run("net_platform_files/net_unsupported_contract", build("net_contract", NET_CONTRACT), expected="network contracts passed")
        from platform_crypto_cases import SOURCE as CRYPTO, write_fixtures
        write_fixtures(work)
        env["SSL_CERT_FILE"] = str(work / "root.pem")
        crypto = build("crypto", CRYPTO)
        run("crypto_ecdsa/crypto_x509_chain/crypto_x509_pool", crypto, "crypto", expected="ECDSA and X509 chain/pool passed")
        run("crypto_sha256_parallel/crypto_rsa_pss", crypto, "parallel", expected="Parallel SHA256 and RSA-PSS passed")
        run("crypto_tls_pipe", crypto, "pipe", expected="TLS pipe passed")
        stream = build("stream", STREAM)
        udp = build("udp", UDP)
        with ThreadPoolExecutor(max_workers=1) as peers:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
            context.set_ciphers("ECDHE-ECDSA-AES128-GCM-SHA256")
            context.set_ecdh_curve("prime256v1")
            context.load_cert_chain(work / "leaf-chain.pem", work / "leaf-key.pem")
            with socket.socket() as listener:
                listener.settimeout(15)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                future = peers.submit(tls_peer, listener, context)
                run("crypto_tls_ecdhe_interop", crypto, "interop", f"127.0.0.1:{listener.getsockname()[1]}", expected="TLS ECDHE interop passed")
                future.result(timeout=20)
            for family, network, host in ((socket.AF_INET, "tcp4", "127.0.0.1"), (socket.AF_INET6, "tcp6", "::1")):
                # Missing IPv6 is a hard failure, including on CI runners.
                with socket.socket(family) as listener:
                    listener.settimeout(15)
                    listener.bind((host, 0))
                    listener.listen(1)
                    port = listener.getsockname()[1]
                    address = f"[{host}]:{port}" if family == socket.AF_INET6 else f"{host}:{port}"
                    future = peers.submit(stream_peer, listener)
                    run("net_" + network + "_loopback", stream, network, address, expected="stream passed")
                    future.result(timeout=20)
            for mode in ("connected", "unconnected"):
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
                    peer.settimeout(15)
                    peer.bind(("127.0.0.1", 0))
                    future = peers.submit(udp_peer, peer)
                    run("net_udp_" + mode, udp, f"127.0.0.1:{peer.getsockname()[1]}", mode, expected="udp passed")
                    future.result(timeout=20)
            if os.name == "nt":
                print("::notice::SKIP net_unix_loopback: Xu Windows Unix-domain sockets are unsupported; executing rejection contract instead", flush=True)
                run("net_unsupported_contract", build("unix_rejected", WINDOWS_UNIX), expected="unsupported Unix socket rejected")
            else:
                # Keep below the macOS sockaddr_un path limit, independent of TMPDIR.
                with tempfile.TemporaryDirectory(prefix="xu-unix-", dir="/tmp") as unix_dir:
                    address = str(Path(unix_dir) / "s")
                    with socket.socket(socket.AF_UNIX) as listener:
                        listener.settimeout(15)
                        listener.bind(address)
                        listener.listen(1)
                        future = peers.submit(stream_peer, listener)
                        run("net_unix_loopback", stream, "unix", address, expected="stream passed")
                        future.result(timeout=20)
    return 0


def stream_peer(listener: socket.socket) -> None:
    with listener.accept()[0] as conn:
        conn.settimeout(15)
        data = b""
        while len(data) < len(b"Xu stream probe"):
            part = conn.recv(128)
            if not part:
                raise AssertionError("stream ended before request")
            data += part
        assert data == b"Xu stream probe", data
        conn.sendall(data)


def udp_peer(peer: socket.socket) -> None:
    data, address = peer.recvfrom(128)
    assert data == b"Xu datagram", data
    peer.sendto(data, address)


def tls_peer(listener: socket.socket, context: ssl.SSLContext) -> None:
    with listener.accept()[0] as raw:
        raw.settimeout(15)
        with context.wrap_socket(raw, server_side=True) as conn:
            data = conn.recv(128)
            assert data == b"Xu stream probe", data
            conn.sendall(data)


if __name__ == "__main__":
    raise SystemExit(main())
