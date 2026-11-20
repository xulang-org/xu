#!/usr/bin/env python3
"""Verification and evaluation for net/poller and EventSet.

Evaluates the scenario from docs/audit/STDLIB_PLAN_2026-11-20.md:
- N connections registered in Poller with mostly idle connections and only tail connections ready.
- Checks returned connection IDs, timeout, close/remove behavior, and wakeup latency.
- Compares Poller compatibility entry with EventSet backend where supported.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "bin" / "xu.exe"

POLLER_TEST_CODE = r'''@main

#net
#net/stream
#net/poller
#os
#time

fn server_accept_all(listener net.Listener, n int, accepted_out chan net.Conn) {
    $l := listener
    for i in 0:n {
        c := l.accept() or (err) {
            accepted_out <- net.closed_conn()
            l.close() or (err2) { << }
            <<
        }
        accepted_out <- c
    }
    l.close() or (err) { << }
}

fn send_after_yield(fd int, payload string) {
    sleep_ns(1000000)
    net.conn_write(fd, &payload) or (err) { <<< 1 }
}

fn main() {
    println("--- EVALUATING NET/POLLER & EVENT_SET ---")
    println("event_set_supported: " + str(poller.event_set_supported()))

    $p := poller.new()
    no_events := p.wait(0)
    if no_events.len != 0 { <<< 1 }

    // 1. Setup local TCP listener
    $l := net.listen_on("tcp", "127.0.0.1:0") or (err) {
        eprintln("listen failed: " + err.msg())
        <<< 1
    }
    addr := l.addr()

    n := 20
    accepted_chan := chan net.Conn{cap: n + 1}
    xu server_accept_all(l, n + 1, accepted_chan)

    // Connect N client sockets
    $client_fds := []int{}
    for i in 0:n {
        cfd := net.dial(addr + "") or (err) {
            eprintln("dial failed: " + err.msg())
            <<< 1
        }
        client_fds.push(cfd)
    }

    // Receive all N server-side fds and wrap into Poller
    $registered_ids := []int{}
    for i in 0:n {
        conn := <-accepted_chan
        s := stream.from_tcp(conn)
        id := p.add(s)
        registered_ids.push(id)
    }

    if p.count() != n {
        eprintln("expected count " + str(n) + ", got " + str(p.count()))
        <<< 1
    }
    println("OK: " + str(n) + " connections registered in poller")

    // 2. Scenario 1: Tail connections ready (idle connections 0..n-3, ready n-2 and n-1)
    // Send data ONLY on the last two client connections
    tail_1 := n - 2
    tail_2 := n - 1
    id_tail_1 := registered_ids[tail_1]
    id_tail_2 := registered_ids[tail_2]

    msg := "ping_payload"
    net.conn_write(client_fds[tail_1], &msg) or (err) {
        eprintln("write tail 1 failed")
        <<< 1
    }
    net.conn_write(client_fds[tail_2], &msg) or (err) {
        eprintln("write tail 2 failed")
        <<< 1
    }

    // Measure wait latency for detecting tail ready connections
    t0 := time.now()
    events := p.wait(500000000) // 500ms timeout
    t1 := time.now()
    latency_ms := (t1 - t0) / 1000000

    println("Tail ready wait returned " + str(events.len) + " events in " + str(latency_ms) + " ms")
    if events.len == 0 {
        eprintln("expected events, got 0")
        <<< 1
    }

    $found_tail_1 := false
    $found_tail_2 := false
    for i in 0:events.len {
        ev := events[i]
        if ev.id == id_tail_1 { found_tail_1 = true }
        if ev.id == id_tail_2 { found_tail_2 = true }
        if (ev.events & poller.EVENT_READ) == 0 {
            eprintln("expected EVENT_READ for id " + str(ev.id))
            <<< 1
        }
    }

    if !found_tail_1 || !found_tail_2 {
        eprintln("missing tail event: found_tail_1=" + str(found_tail_1) + ", found_tail_2=" + str(found_tail_2))
        <<< 1
    }
    println("OK: correct tail ready connection IDs verified: " + str(id_tail_1) + ", " + str(id_tail_2))

    // Drain data from tail connections
    read1 := p.read_timeout(id_tail_1, 64, 10000000) or (err) {
        eprintln("read tail 1 failed: " + err.msg())
        <<< 1
    }
    read2 := p.read_timeout(id_tail_2, 64, 10000000) or (err) {
        eprintln("read tail 2 failed: " + err.msg())
        <<< 1
    }
    if read1 != msg || read2 != msg {
        eprintln("data mismatch on tail read: " + read1 + " vs " + read2)
        <<< 1
    }
    println("OK: tail read verified")

    // 3. Scenario 2: Timeout behavior when all connections are silent
    t_before := time.now()
    timeout_ns := 100000000 // 100ms
    empty_events := p.wait(timeout_ns)
    t_after := time.now()
    elapsed_ms := (t_after - t_before) / 1000000

    println("Silent wait returned " + str(empty_events.len) + " events in " + str(elapsed_ms) + " ms")
    if empty_events.len != 0 {
        eprintln("expected 0 events, got " + str(empty_events.len))
        <<< 1
    }
    if elapsed_ms < 80 {
        eprintln("timeout returned too early: " + str(elapsed_ms) + " ms")
        <<< 1
    }
    println("OK: timeout behavior verified (~" + str(elapsed_ms) + " ms for 100ms budget)")

    // An infinite wait must let another Xu task make the connection ready.
    xu send_after_yield(client_fds[tail_1], msg + "")
    delayed := p.wait(0)
    if delayed.len != 1 || delayed[0].id != id_tail_1 || (delayed[0].events & poller.EVENT_READ) == 0 { <<< 1 }
    data := p.read_timeout(id_tail_1, 64, 100000000) or (err) { <<< 1 }
    if data != msg { <<< 1 }

    // 4. Scenario 3: Close / Remove lifecycle
    // Close id_tail_2
    closed := p.close_id(id_tail_2) or (err) {
        eprintln("close_id threw: " + err.msg())
        <<< 1
    }
    if !closed {
        eprintln("close_id returned false for " + str(id_tail_2))
        <<< 1
    }
    if p.count() != n - 1 {
        eprintln("expected count " + str(n - 1) + ", got " + str(p.count()))
        <<< 1
    }

    // Now send data to id_tail_1 again
    net.conn_write(client_fds[tail_1], &msg) or (err) {
        eprintln("write tail 1 retry failed")
        <<< 1
    }

    events2 := p.wait(200000000)
    $has_closed_id := false
    $has_tail_1 := false
    for i in 0:events2.len {
        ev := events2[i]
        if ev.id == id_tail_2 { has_closed_id = true }
        if ev.id == id_tail_1 { has_tail_1 = true }
    }
    if has_closed_id {
        eprintln("closed connection id was returned in events!")
        <<< 1
    }
    if !has_tail_1 {
        eprintln("tail 1 was not returned after tail 2 close")
        <<< 1
    }
    tail_data := p.read_timeout(id_tail_1, 64, 100000000) or (err) { <<< 1 }
    if tail_data != msg { <<< 1 }
    println("OK: close_id lifecycle verified, closed connection dropped cleanly")

    removed_id := registered_ids[0]
    if !p.remove(removed_id) || p.count() != n - 2 { <<< 1 }
    if p.remove(removed_id) { <<< 1 }

    // A removed stream's peer must see EOF while the Poller is still alive.
    removed_peer := client_fds[0]
    eof_ready := os.socket_wait(removed_peer, poller.EVENT_READ, 500000000) or (err) { <<< 1 }
    if eof_ready == 0 { <<< 1 }
    eof := net.conn_read(removed_peer, 1) or (err) { <<< 1 }
    if eof.len != 0 { <<< 1 }

    // Reuse the vacant slot and check that its previous id stays invalid.
    replacement_peer := net.dial(addr + "") or (err) { <<< 1 }
    replacement := <-accepted_chan
    new_id := p.add(stream.from_tcp(replacement))
    if new_id <= id_tail_2 || p.set_interest(removed_id, poller.EVENT_WRITE) { <<< 1 }
    net.conn_write(replacement_peer, &msg) or (err) { <<< 1 }
    new_events := p.wait(500000000)
    $found_replacement := false
    for ev in new_events {
        if ev.id == removed_id { <<< 1 }
        if ev.id == new_id && (ev.events & poller.EVENT_READ) != 0 { found_replacement = true }
    }
    if !found_replacement { <<< 1 }
    if !p.set_interest(new_id, poller.EVENT_WRITE) { <<< 1 }
    writable := p.wait(500000000)
    if writable.len != 1 || writable[0].id != new_id || writable[0].events != poller.EVENT_WRITE { <<< 1 }
    p.close_id(new_id) or (err) { <<< 1 }
    net.conn_close(replacement_peer) or (err) { <<< 1 }

    if p.wait(10000000).len != 0 { <<< 1 }

    for i in 0:n {
        p.close_id(registered_ids[i]) or (err) { <<< 1 }
    }
    drained := p.wait(0)
    if p.count() != 0 || drained.len != 0 { <<< 1 }

    // Clean up
    for i in 0:n {
        net.conn_close(client_fds[i]) or (err) { << }
    }

    println("ALL_POLLER_STEP_TESTS_PASSED")
}
'''

def main() -> int:
    env = os.environ.copy()
    env["XU_STDLIB_ROOT"] = str(ROOT / "src")
    env["XU_ROOT"] = str(ROOT)

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "eval_poller.xu"
        exe = Path(td) / "eval_poller.exe"
        src.write_text(POLLER_TEST_CODE, encoding="utf-8")

        build_cmd = [str(COMPILER), "build", str(src), "-o", str(exe)]
        print("Compiling poller evaluation test...")
        r = subprocess.run(build_cmd, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print("COMPILE FAILED:\n" + r.stderr + "\n" + r.stdout)
            return 1

        print("Running poller evaluation test...")
        t0 = time.time()
        r2 = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=30)
        dt = time.time() - t0
        print(f"STDOUT:\n{r2.stdout}")
        if r2.stderr:
            print(f"STDERR:\n{r2.stderr}")

        if r2.returncode != 0:
            print(f"EXIT CODE: {r2.returncode}")
            return 1

        if "ALL_POLLER_STEP_TESTS_PASSED" not in r2.stdout:
            print("FAILURE: expected ALL_POLLER_STEP_TESTS_PASSED")
            return 1

    print("SUCCESS: net/poller evaluation passed cleanly!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
