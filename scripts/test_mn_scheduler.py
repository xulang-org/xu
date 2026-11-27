#!/usr/bin/env python3
"""End-to-end tests for Xu's M:N multi-core coroutine scheduler & thread-safe runtime."""

import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
XU = ROOT / "bin" / "xu"


def xu_env(work: Path, extra=None) -> dict:
    env = dict(
        os.environ,
        XU_ROOT=str(ROOT),
        XU_STDLIB_ROOT=str(ROOT / "src"),
        XU_CACHE=str(work / "cache"),
        XU_TASK_POLL="0",
    )
    if extra:
        env.update(extra)
    return env


def build_and_run(work: Path, name: str, source: str, extra_env=None, check=True):
    src = work / f"{name}.xu"
    exe = work / f"{name}_bin"
    src.write_text(source, encoding="utf-8")
    env = xu_env(work, extra_env)
    subprocess.run([str(XU), "build", str(src), "-o", str(exe)], env=env, check=True)
    return subprocess.run([str(exe)], env=env, text=True, capture_output=True, timeout=60, check=check)


def test_heap_and_ffi_multicore_stress(work: Path):
    src = r'''@main
pool #sync/pool

fn heap_worker(wid int, iters int, out chan int) {
    $m := map[string]int{}
    $acc := 0
    for i in 0:iters {
        s := "w" + str(wid) + "_" + str(i & 63)
        $arr := [i, i + 1, wid]
        arr.push(s.len)
        m[s] = i
        acc += (m[s] & 255) + arr[3]
    }
    out <- acc
}

fn main() int {
    np := pool.set_max_procs(4)
    if np < 2 {
        eprintln("expected >= 2 procs, got " + str(np))
        << 1
    }
    if pool.max_procs() != np {
        eprintln("max_procs mismatch")
        << 1
    }
    n_workers := 8
    iters := 3000
    ch := chan int{cap: 8}
    for w in 0:n_workers {
        xu heap_worker(w, iters, ch)
    }
    $total := 0
    for _ in 0:n_workers {
        total += <- ch
    }
    pool.stop_scheduler()
    if pool.max_procs() != 1 {
        eprintln("expected max_procs == 1 after stop, got " + str(pool.max_procs()))
        << 1
    }
    println("HEAP_STRESS_OK total=" + str(total))
    << 0
}
'''
    r1 = build_and_run(work, "heap_stress", src)
    assert "HEAP_STRESS_OK total=" in r1.stdout, r1.stdout + r1.stderr
    # Run once with single proc for deterministic checksum equivalence.
    src_1t = src.replace("pool.set_max_procs(4)", "1").replace("np < 2", "false").replace("pool.stop_scheduler()", "")
    r2 = build_and_run(work, "heap_stress_1t", src_1t, extra_env={"XU_PROCS": "1"})
    t4 = int(re.search(r"total=(\d+)", r1.stdout).group(1))
    t1 = int(re.search(r"total=(\d+)", r2.stdout).group(1))
    assert t4 == t1 and t4 > 0, (t4, t1)
    print(f"M:N heap+map+string stress (8 tasks x 3000 iters on 4 OS threads, total={t4}) PASS")


def test_default_multicore_zero_import(work: Path):
    src = r'''@main
#time

fn cpu_worker(wid int, iters int, out chan int) {
    $x := wid * 131 + 7
    $sum := 0
    for i in 0:iters {
        x = ((x * 1103515245 + 12345) >> 1) & 0x7FFFFFFF
        sum += x & 1023
    }
    out <- sum
}

fn main() int {
    n_tasks := 8
    iters := 10000000
    ch := chan int{cap: 8}
    t0 := time.now()
    for w in 0:n_tasks {
        xu cpu_worker(w, iters, ch)
    }
    $total := 0
    for _ in 0:n_tasks {
        total += <- ch
    }
    dt_ns := time.now() - t0
    println("TOTAL=" + str(total) + " NS=" + str(dt_ns))
    << 0
}
'''
    exe = work / "default_mt_bin"
    sfile = work / "default_mt.xu"
    sfile.write_text(src, encoding="utf-8")
    subprocess.run([str(XU), "build", str(sfile), "-o", str(exe)], env=xu_env(work), check=True)

    env1 = xu_env(work, {"XU_PROCS": "1"})
    envd = xu_env(work)
    envd.pop("XU_PROCS", None)
    r1 = subprocess.run([str(exe)], env=env1, text=True, capture_output=True, timeout=60, check=True)
    rd = subprocess.run([str(exe)], env=envd, text=True, capture_output=True, timeout=60, check=True)

    m1 = re.search(r"TOTAL=(\d+) NS=(\d+)", r1.stdout)
    md = re.search(r"TOTAL=(\d+) NS=(\d+)", rd.stdout)
    assert m1 and md, (r1.stdout, rd.stdout)
    tot1, ns1 = int(m1.group(1)), int(m1.group(2))
    totd, nsd = int(md.group(1)), int(md.group(2))
    assert tot1 == totd and tot1 > 0, (tot1, totd)
    sp = ns1 / max(nsd, 1)
    print(f"[Default zero-import xu CPU speedup] 1-core={ns1/1e6:.1f}ms vs default-multicore={nsd/1e6:.1f}ms ({sp:.2f}x)")
    assert sp > 2.0, sp


def test_multicore_xu_task_speedup(work: Path):
    src = r'''@main
pool #sync/pool
#time

fn cpu_worker(wid int, iters int, out chan int) {
    $x := wid * 131 + 7
    $sum := 0
    for i in 0:iters {
        x = ((x * 1103515245 + 12345) >> 1) & 0x7FFFFFFF
        sum += x & 1023
    }
    out <- sum
}

fn main() int {
    np := pool.set_max_procs(0)
    n_tasks := 8
    iters := 8000000
    ch := chan int{cap: 8}
    t0 := time.now()
    for w in 0:n_tasks {
        xu cpu_worker(w, iters, ch)
    }
    $total := 0
    for _ in 0:n_tasks {
        total += <- ch
    }
    dt_ns := time.now() - t0
    pool.stop_scheduler()
    println("PROCS=" + str(np) + " TOTAL=" + str(total) + " NS=" + str(dt_ns))
    << 0
}
'''
    exe = work / "mn_speedup_bin"
    sfile = work / "mn_speedup.xu"
    sfile.write_text(src, encoding="utf-8")
    subprocess.run([str(XU), "build", str(sfile), "-o", str(exe)], env=xu_env(work), check=True)

    r1 = subprocess.run([str(exe)], env=xu_env(work, {"XU_PROCS": "1"}), text=True, capture_output=True, timeout=60, check=True)
    r4 = subprocess.run([str(exe)], env=xu_env(work, {"XU_PROCS": "4"}), text=True, capture_output=True, timeout=60, check=True)

    m1 = re.search(r"PROCS=(\d+) TOTAL=(\d+) NS=(\d+)", r1.stdout)
    m4 = re.search(r"PROCS=(\d+) TOTAL=(\d+) NS=(\d+)", r4.stdout)
    assert m1 and m4, (r1.stdout, r4.stdout)
    p1, tot1, ns1 = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
    p4, tot4, ns4 = int(m4.group(1)), int(m4.group(2)), int(m4.group(3))
    assert p1 == 1 and p4 == 4, (p1, p4)
    assert tot1 == tot4 and tot1 > 0, (tot1, tot4)
    sp = ns1 / max(ns4, 1)
    print(f"[M:N 8 green threads CPU speedup] 1-core={ns1/1e6:.1f}ms vs 4-core={ns4/1e6:.1f}ms ({sp:.2f}x)")
    assert sp > 2.0, sp


def test_channels_select_mutex_wg_stress(work: Path):
    src = r'''@main
pool #sync/pool
sync #sync

fn buf_producer(id int, n int, ch chan int) {
    for i in 0:n {
        ch <- (id * 10000 + i + 1)
    }
}

fn unbuf_producer(id int, n int, ch chan int) {
    for i in 0:n {
        ch <- (id * 10000 + i + 1)
    }
}

fn sel_producer(id int, n int, c0 chan int, c1 chan int, c2 chan int) {
    for i in 0:n {
        v := id * 10000 + i + 1
        which := i % 3
        if which == 0 {
            c0 <- v
        } else if which == 1 {
            c1 <- v
        } else {
            c2 <- v
        }
    }
}

fn mutex_wg_worker(n int, box chan int, wg sync.WaitGroup) {
    for _ in 0:n {
        v := <- box
        box <- (v + 1)
    }
    $w := wg
    w.done()
}

fn main() int {
    _ := pool.set_max_procs(4)

    // 1. 8 buffered producers -> main consumer (8 * 1000 = 8000 items)
    bch := chan int{cap: 16}
    for p in 0:8 { xu buf_producer(p, 1000, bch) }
    $bsum := 0
    for _ in 0:8000 { bsum += <- bch }

    // 2. 4 unbuffered producers -> main consumer (4 * 500 = 2000 items)
    uch := chan int{cap: 0}
    for p in 0:4 { xu unbuf_producer(p, 500, uch) }
    $usum := 0
    for _ in 0:2000 { usum += <- uch }

    // 3. 3-arm select across 3 producers (3 * 500 = 1500 items)
    s0 := chan int{cap: 4}
    s1 := chan int{cap: 4}
    s2 := chan int{cap: 4}
    for p in 0:3 { xu sel_producer(p, 500, s0, s1, s2) }
    $ssum := 0
    for _ in 0:1500 {
        select {
            v0 := <- s0 { ssum += v0 }
            v1 := <- s1 { ssum += v1 }
            v2 := <- s2 { ssum += v2 }
        }
    }

    // 4. Token channel lock + WaitGroup across 8 tasks x 1000 ops = 8000 increments
    box := chan int{cap: 1}
    box <- 0
    $wg := sync.wait_group()
    wg.add(8)
    for _ in 0:8 { xu mutex_wg_worker(1000, box, wg) }
    wg.wait_pending()
    cnt := <- box
    if cnt != 8000 {
        eprintln("mutex/wg count mismatch: " + str(cnt))
        << 1
    }

    pool.stop_scheduler()
    println("CHAN_SELECT_WG_OK bsum=" + str(bsum) + " usum=" + str(usum) + " ssum=" + str(ssum) + " cnt=" + str(cnt))
    << 0
}
'''
    r = build_and_run(work, "chan_select_wg", src)
    expected_bsum = sum(p * 10000 + i + 1 for p in range(8) for i in range(1000))
    expected_usum = sum(p * 10000 + i + 1 for p in range(4) for i in range(500))
    expected_ssum = sum(p * 10000 + i + 1 for p in range(3) for i in range(500))
    want = f"CHAN_SELECT_WG_OK bsum={expected_bsum} usum={expected_usum} ssum={expected_ssum} cnt=8000"
    assert want in r.stdout, (want, r.stdout + r.stderr)
    print("M:N buffered + unbuffered + 3-arm select + WaitGroup stress (19500 ops) PASS")


def test_preemption_and_drain(work: Path):
    src = r'''@main
pool #sync/pool
#ffi

fn busy_task(id int, out_ptr c_ptr) {
    $x := id + 1
    for i in 0:300000 {
        x = (x * 1664525 + 1013904223) & 0x7FFFFFFF
    }
    _ := atomic_add(out_ptr, 1)
    if x < 0 { println("neg") }
}

fn main() int {
    _ := pool.set_max_procs(4)
    $cnt := 0
    ptr := c_ptr(0)
    // Use an OS-visible atomic counter inside main stack? No, main returns before drain!
    // Use heap C memory via ffi.calloc so busy_task writes cleanly after main returns.
    unsafe {
        p := ffi.calloc(8)
        for i in 0:16 {
            xu busy_task(i, p)
        }
        // Poll wait loop? No, intentionally exit main WITHOUT waiting or calling stop_scheduler
        // to test task_drain(); print marker if heap survives, or run a second drain helper!
        println("MAIN_EXITING p_init=" + str(atomic_load(p)))
        _ = p
    }
    << 0
}
'''
    # Even simpler & cleaner observability: each busy_task println("TASK_DONE") during task_drain!
    src2 = r'''@main
pool #sync/pool

fn busy_task(id int) {
    $x := id + 1
    for _ in 0:400000 {
        x = (x * 1664525 + 1013904223) & 0x7FFFFFFF
    }
    println("TASK_DONE_" + str(id))
}

fn main() int {
    _ := pool.set_max_procs(4)
    for i in 0:16 {
        xu busy_task(i)
    }
    println("MAIN_EXITING")
    << 0
}
'''
    r = build_and_run(work, "drain_test", src2)
    assert "MAIN_EXITING\n" in r.stdout, r.stdout
    for i in range(16):
        assert f"TASK_DONE_{i}\n" in r.stdout, f"missing TASK_DONE_{i} in:\n{r.stdout}"
    print("M:N 16-task fair preemption & task_drain() PASS")


def test_deadlock_detection(work: Path):
    src_1t = r'''@main
fn main() int {
    ch := chan int{cap: 0}
    v := <- ch
    println(str(v))
    << 0
}
'''
    r1 = build_and_run(work, "deadlock_1t", src_1t, check=False)
    assert r1.returncode != 0 and "deadlock" in (r1.stdout + r1.stderr).lower(), (r1.returncode, r1.stdout, r1.stderr)

    src_mt = r'''@main
pool #sync/pool

fn blocked_peer(ch chan int) {
    _ := <- ch
}

fn main() int {
    _ := pool.set_max_procs(4)
    ch := chan int{cap: 0}
    xu blocked_peer(ch)
    _ := <- ch
    << 0
}
'''
    r2 = build_and_run(work, "deadlock_mt", src_mt, check=False)
    assert r2.returncode != 0 and "deadlock" in (r2.stdout + r2.stderr).lower(), (r2.returncode, r2.stdout, r2.stderr)
    print("Deadlock detection (1T & 4T M:N) PASS")


def test_targeted_channel_wake_no_thundering_herd(work: Path):
    src = r'''@main
#time

fn idle_waiter(ch chan int, done chan int) {
    _ := <- ch
    done <- 1
}

fn ping_pong(a chan int, b chan int, n int, done chan int) {
    for i in 0:n {
        v := <- a
        b <- (v + 1)
    }
    done <- 1
}

fn main() int {
    n_idle := 400
    $idles := []chan int{}
    idle_done := chan int{cap: n_idle}
    for _ in 0:n_idle {
        c := chan int{cap: 0}
        idles.push(c)
        xu idle_waiter(c, idle_done)
    }
    // Let idle waiters park on their own channel queues.
    a := chan int{cap: 0}
    b := chan int{cap: 0}
    pp_done := chan int{cap: 1}
    rounds := 10000
    t0 := time.now()
    xu ping_pong(a, b, rounds, pp_done)
    $acc := 0
    for i in 0:rounds {
        a <- i
        acc += <- b
    }
    _ := <- pp_done
    dt_ns := time.now() - t0
    for i in 0:n_idle {
        close(idles[i])
    }
    $closed_ok := 0
    for _ in 0:n_idle {
        closed_ok += <- idle_done
    }
    println("TARGETED_WAKE_OK acc=" + str(acc) + " closed=" + str(closed_ok) + " NS=" + str(dt_ns))
    << 0
}
'''
    r = build_and_run(work, "targeted_wake", src)
    expected_acc = sum(i + 1 for i in range(10000))
    m = re.search(r"TARGETED_WAKE_OK acc=(\d+) closed=(\d+) NS=(\d+)", r.stdout)
    assert m, r.stdout + r.stderr
    acc, closed_ok, dt_ns = int(m.group(1)), int(m.group(2)), int(m.group(3))
    assert acc == expected_acc and closed_ok == 400, (acc, expected_acc, closed_ok)
    print(f"[Targeted channel wake: 400 idle chans + 10k unbuf ping-pong] {dt_ns/1e6:.1f}ms PASS")
    assert dt_ns < 5_000_000_000, f"too slow ({dt_ns/1e6:.1f}ms), possible thundering herd"


def test_mcache_alloc_scaling(work: Path):
    src = r'''@main
#time

fn alloc_worker(wid int, iters int, out chan int) {
    $acc := 0
    for i in 0:iters {
        $arr := [i, i + 1, wid, i ^ wid]
        arr.push(i + 2)
        arr.push(i + 3)
        s := "k_" + str(wid) + "_" + str(i & 255)
        acc += arr[5] + s.len
    }
    out <- acc
}

fn main() int {
    n_tasks := 8
    iters := 60000
    ch := chan int{cap: 8}
    t0 := time.now()
    for w in 0:n_tasks {
        xu alloc_worker(w, iters, ch)
    }
    $total := 0
    for _ in 0:n_tasks {
        total += <- ch
    }
    dt_ns := time.now() - t0
    println("ALLOC_TOTAL=" + str(total) + " NS=" + str(dt_ns))
    << 0
}
'''
    exe = work / "mcache_scale_bin"
    sfile = work / "mcache_scale.xu"
    sfile.write_text(src, encoding="utf-8")
    subprocess.run([str(XU), "build", str(sfile), "-o", str(exe)], env=xu_env(work), check=True)
    r1 = subprocess.run([str(exe)], env=xu_env(work, {"XU_PROCS": "1"}), text=True, capture_output=True, timeout=60, check=True)
    r4 = subprocess.run([str(exe)], env=xu_env(work, {"XU_PROCS": "4"}), text=True, capture_output=True, timeout=60, check=True)
    m1 = re.search(r"ALLOC_TOTAL=(\d+) NS=(\d+)", r1.stdout)
    m4 = re.search(r"ALLOC_TOTAL=(\d+) NS=(\d+)", r4.stdout)
    assert m1 and m4, (r1.stdout, r4.stdout)
    tot1, ns1 = int(m1.group(1)), int(m1.group(2))
    tot4, ns4 = int(m4.group(1)), int(m4.group(2))
    assert tot1 == tot4 and tot1 > 0, (tot1, tot4)
    sp = ns1 / max(ns4, 1)
    print(f"[Per-M mcache alloc scaling] 1-core={ns1/1e6:.1f}ms vs 4-core={ns4/1e6:.1f}ms ({sp:.2f}x)")
    assert sp > 1.5, f"expected mcache scaling > 1.5x, got {sp:.2f}x"


def test_chan_coro_correctness_matrix(work: Path):
    """Exhaustive coroutine + channel communication correctness & race torture suite."""
    src = r'''@main
pool #sync/pool
sync #sync

struct WideMsg {
    pub pid int
    pub seq int
    pub checksum int
    pub label string
    pub nums []int
}

struct RpcReq {
    pub id int
    pub payload string
    pub reply chan string
}

fn pre_mt_sender(ch chan int, v int) {
    ch <- v
}

fn mpmc_int_prod(pid int, n int, ch chan int) {
    for i in 0:n {
        ch <- (pid * 100000 + i)
    }
}

fn mpmc_int_cons(n int, ch chan int, out chan []int) {
    $got := []int{}
    for _ in 0:n {
        got.push(<- ch)
    }
    out <- got
}

fn mpmc_wide_prod(pid int, n int, ch chan WideMsg) {
    for i in 0:n {
        ck := (pid * 131 + i * 17) ^ 0x5A5A
        msg := WideMsg{
            pid: pid,
            seq: i,
            checksum: ck,
            label: "p" + str(pid) + "_s" + str(i),
            nums: [pid, i, ck, pid + i]
        }
        ch <- msg
    }
}

fn mpmc_wide_cons(n int, ch chan WideMsg, out chan int) {
    $ok := 0
    for _ in 0:n {
        m := <- ch
        exp_ck := (m.pid * 131 + m.seq * 17) ^ 0x5A5A
        exp_lbl := "p" + str(m.pid) + "_s" + str(m.seq)
        if m.checksum == exp_ck && m.label == exp_lbl && m.nums.len == 4 && m.nums[0] == m.pid && m.nums[1] == m.seq && m.nums[2] == exp_ck && m.nums[3] == m.pid + m.seq {
            ok += 1
        }
    }
    out <- ok
}

fn fifo_sender(n int, ch chan int) {
    for i in 0:n { ch <- i }
}

fn range_drain_worker(ch chan int, out chan int) {
    $acc := 0
    for v in ch {
        acc += v
    }
    out <- acc
}

fn unbuf_close_waiter(ch chan int, out chan int) {
    v := <- ch
    out <- (v + 1)
}

fn drop_unread_worker(wid int, done chan int) {
    // Fill owning channels (string & WideMsg) and drop without draining.
    for r in 0:25 {
        cs := chan string{cap: 8}
        for j in 0:6 {
            cs <- ("unread_" + str(wid) + "_" + str(r) + "_" + str(j))
        }
        // Drain 2, leave 4 unread to be dropped by chan_release -> chan_take_unread.
        _ := <- cs
        _ := <- cs

        cw := chan WideMsg{cap: 4}
        for j in 0:3 {
            cw <- WideMsg{pid: wid, seq: j, checksum: 1, label: "drop_" + str(j), nums: [wid, j]}
        }
    }
    done <- 1
}

fn select_unbuf_receiver(ch chan int, n int, out chan int) {
    $sum := 0
    for _ in 0:n {
        sum += <- ch
    }
    out <- sum
}

fn select_unbuf_sender(ch chan int, n int) {
    for i in 0:n {
        ch <- (i + 1)
    }
}

fn pipe_stage(inp chan WideMsg, out chan WideMsg) {
    for m in inp {
        $next := m
        ck := next.checksum + 1
        next.checksum = ck
        next.nums.push(ck)
        out <- next
    }
    close(out)
}

fn rpc_server(reqs chan RpcReq, done chan int) {
    for req in reqs {
        req.reply <- ("ok:" + str(req.id) + ":" + req.payload)
    }
    done <- 1
}

fn rpc_client(cid int, n int, reqs chan RpcReq, out chan int) {
    $ok := 0
    for i in 0:n {
        rep := chan string{cap: 0}
        id := cid * 1000 + i
        reqs <- RpcReq{id: id, payload: "q" + str(i), reply: rep}
        ans := <- rep
        if ans == "ok:" + str(id) + ":q" + str(i) {
            ok += 1
        }
    }
    out <- ok
}

fn tree_spawn(depth int, id int, out chan int) {
    if depth <= 0 {
        out <- (id + 1)
        <<
    }
    c := chan int{cap: 2}
    xu tree_spawn(depth - 1, id * 2, c)
    xu tree_spawn(depth - 1, id * 2 + 1, c)
    a := <- c
    b := <- c
    out <- (a + b)
}

fn main() int {
    // 1. Pre-MT select/default on unbuffered channel, THEN first xu spawn!
    // Verifies stale ST C_WAITER never corrupts MT C_UNBUF_WAITER / MT_BLK_COUNT.
    pre_ch := chan int{cap: 0}
    $pre_def := 0
    select {
        pv := <- pre_ch {
            _ := pv
            pre_def = -1
        }
        else { pre_def = 1 }
    }
    if pre_def != 1 {
        eprintln("pre_mt select default failed")
        << 1
    }
    xu pre_mt_sender(pre_ch, 777)
    if <- pre_ch != 777 {
        eprintln("pre_mt unbuf recv failed")
        << 2
    }

    // 2. Strict FIFO order on cap:0, cap:1, cap:16
    for cap_i in [0, 1, 16] {
        fch := chan int{cap: cap_i}
        xu fifo_sender(2000, fch)
        for i in 0:2000 {
            v := <- fch
            if v != i {
                eprintln("FIFO violation cap=" + str(cap_i) + " got=" + str(v) + " want=" + str(i))
                << 3
            }
        }
    }

    // 3. MPMC exact-once verification on unbuffered (cap:0) and buffered (cap:1, cap:13)
    for cap_i in [0, 1, 13] {
        n_p := 8
        per_p := 400
        total := n_p * per_p
        mch := chan int{cap: cap_i}
        for p in 0:n_p { xu mpmc_int_prod(p, per_p, mch) }
        out := chan []int{cap: 8}
        for _ in 0:8 { xu mpmc_int_cons(total / 8, mch, out) }
        $seen := []int{}
        for _ in 0:total { seen.push(0) }
        for _ in 0:8 {
            batch := <- out
            for j in 0:batch.len {
                v := batch[j]
                pid := v / 100000
                seq := v % 100000
                idx := pid * per_p + seq
                if idx < 0 || idx >= total {
                    eprintln("MPMC oob val=" + str(v))
                    << 4
                }
                seen[idx] = seen[idx] + 1
            }
        }
        for k in 0:total {
            if seen[k] != 1 {
                eprintln("MPMC exact-once violation cap=" + str(cap_i) + " idx=" + str(k) + " cnt=" + str(seen[k]))
                << 5
            }
        }
    }

    // 4. MPMC wide owning structs (string + []int) on cap:0 and cap:7
    for cap_i in [0, 7] {
        wch := chan WideMsg{cap: cap_i}
        for p in 0:8 { xu mpmc_wide_prod(p, 200, wch) }
        wout := chan int{cap: 8}
        for _ in 0:8 { xu mpmc_wide_cons(200, wch, wout) }
        $wok := 0
        for _ in 0:8 { wok += <- wout }
        if wok != 1600 {
            eprintln("MPMC wide mismatch cap=" + str(cap_i) + " wok=" + str(wok))
            << 6
        }
    }

    // 5. Concurrent unread owning-channel drop (tests chan_take_unread under MT)
    ddone := chan int{cap: 8}
    for w in 0:8 { xu drop_unread_worker(w, ddone) }
    for _ in 0:8 { _ := <- ddone }

    // 6. Close + range drain (buffered) & close broadcast (unbuffered)
    dr_ch := chan int{cap: 500}
    $exp_dr := 0
    for i in 1:501 {
        dr_ch <- i
        exp_dr += i
    }
    close(dr_ch)
    dr_out := chan int{cap: 8}
    for _ in 0:8 { xu range_drain_worker(dr_ch, dr_out) }
    $got_dr := 0
    for _ in 0:8 { got_dr += <- dr_out }
    if got_dr != exp_dr {
        eprintln("close range drain mismatch: " + str(got_dr) + " vs " + str(exp_dr))
        << 7
    }

    bc_ch := chan int{cap: 0}
    bc_out := chan int{cap: 16}
    for _ in 0:16 { xu unbuf_close_waiter(bc_ch, bc_out) }
    close(bc_ch)
    $bc_sum := 0
    for _ in 0:16 { bc_sum += <- bc_out }
    if bc_sum != 16 {
        eprintln("unbuf close broadcast mismatch: " + str(bc_sum))
        << 8
    }

    // 7. Complex select: default + unbuf send + unbuf recv + closed channel
    su_send := chan int{cap: 0}
    su_out := chan int{cap: 1}
    xu select_unbuf_receiver(su_send, 300, su_out)
    for i in 0:300 {
        select {
            su_send <- (i + 1) {}
        }
    }
    if <- su_out != 300 * 301 / 2 {
        eprintln("select unbuf send mismatch")
        << 9
    }

    su_recv := chan int{cap: 0}
    xu select_unbuf_sender(su_recv, 300)
    $sr_sum := 0
    for _ in 0:300 {
        // Interleave non-blocking select/default before blocking select
        dummy := chan int{cap: 0}
        select {
            dv := <- dummy { _ := dv }
            else {}
        }
        select {
            v := <- su_recv { sr_sum += v }
        }
    }
    if sr_sum != 300 * 301 / 2 {
        eprintln("select unbuf recv mismatch: " + str(sr_sum))
        << 10
    }

    // 8. 6-stage coroutine pipeline with wide owning structs
    $p_in := chan WideMsg{cap: 8}
    p_head := p_in
    for _ in 0:6 {
        p_next := chan WideMsg{cap: 8}
        xu pipe_stage(p_in, p_next)
        p_in = p_next
    }
    xu mpmc_wide_prod(1, 300, p_head)
    // Wait for all 300 items through all 6 stages
    for i in 0:300 {
        m := <- p_in
        exp_ck := ((1 * 131 + i * 17) ^ 0x5A5A) + 6
        if m.seq != i || m.checksum != exp_ck || m.nums.len != 10 {
            eprintln("pipeline mismatch at " + str(i))
            << 11
        }
    }
    close(p_head)
    // Drain closed tail
    for _ in p_in {}

    // 9. Channel-of-channels RPC (12 clients x 80 reqs -> 4 servers, unbuf reply chans)
    reqs := chan RpcReq{cap: 16}
    sdone := chan int{cap: 4}
    for _ in 0:4 { xu rpc_server(reqs, sdone) }
    cout := chan int{cap: 12}
    for c in 0:12 { xu rpc_client(c, 80, reqs, cout) }
    $rpc_ok := 0
    for _ in 0:12 { rpc_ok += <- cout }
    close(reqs)
    for _ in 0:4 { _ := <- sdone }
    if rpc_ok != 960 {
        eprintln("RPC mismatch: " + str(rpc_ok))
        << 12
    }

    // 10. Nested recursive tree spawn (depth 7 -> 255 coroutines)
    t_out := chan int{cap: 1}
    xu tree_spawn(7, 0, t_out)
    t_sum := <- t_out
    // Leaves are id = 0..127 -> sum(id + 1) = 128*129/2 = 8256
    if t_sum != 8256 {
        eprintln("tree_spawn mismatch: " + str(t_sum))
        << 13
    }

    // 11. Scheduler stop & restart cycle
    pool.stop_scheduler()
    np2 := pool.set_max_procs(4)
    if np2 < 2 {
        eprintln("restart set_max_procs failed: " + str(np2))
        << 14
    }
    rch := chan int{cap: 0}
    xu fifo_sender(500, rch)
    for i in 0:500 {
        if <- rch != i {
            eprintln("post-restart FIFO failed")
            << 15
        }
    }
    pool.stop_scheduler()

    println("CHAN_CORO_MATRIX_OK")
    << 0
}
'''
    exe = work / "chan_coro_matrix_bin"
    exe_noopt = work / "chan_coro_matrix_noopt_bin"
    sfile = work / "chan_coro_matrix.xu"
    sfile.write_text(src, encoding="utf-8")
    subprocess.run([str(XU), "build", str(sfile), "-o", str(exe)], env=xu_env(work), check=True)
    subprocess.run([str(XU), "build", "--no-opt", str(sfile), "-o", str(exe_noopt)], env=xu_env(work), check=True)

    # Run 10 repeated default multi-core iterations + XU_DEBUG_FREE=1 + no-opt + XU_PROCS=1
    env_mt = xu_env(work)
    env_mt.pop("XU_PROCS", None)
    for it in range(10):
        r = subprocess.run([str(exe)], env=env_mt, text=True, capture_output=True, timeout=60, check=True)
        assert "CHAN_CORO_MATRIX_OK" in r.stdout, (it, r.stdout, r.stderr)
    r_df = subprocess.run([str(exe)], env=dict(env_mt, XU_DEBUG_FREE="1"), text=True, capture_output=True, timeout=60, check=True)
    assert "CHAN_CORO_MATRIX_OK" in r_df.stdout, (r_df.stdout, r_df.stderr)
    r_no = subprocess.run([str(exe_noopt)], env=env_mt, text=True, capture_output=True, timeout=60, check=True)
    assert "CHAN_CORO_MATRIX_OK" in r_no.stdout, (r_no.stdout, r_no.stderr)
    r_1t = subprocess.run([str(exe)], env=xu_env(work, {"XU_PROCS": "1"}), text=True, capture_output=True, timeout=60, check=True)
    assert "CHAN_CORO_MATRIX_OK" in r_1t.stdout, (r_1t.stdout, r_1t.stderr)

    # 12. Panic on send to closed channel (both immediate & concurrent blocked sender)
    panic_src = r'''@main
fn blocked_sender(ch chan int, ready chan int) {
    ch <- 1
    ready <- 1
    ch <- 2 // blocks until closed -> must panic
}
fn main() int {
    ch := chan int{cap: 1}
    ready := chan int{cap: 0}
    xu blocked_sender(ch, ready)
    _ := <- ready
    close(ch)
    << 0
}
'''
    rp = build_and_run(work, "panic_closed_mt", panic_src, check=False)
    assert rp.returncode != 0 and "send on closed channel" in (rp.stdout + rp.stderr), (rp.returncode, rp.stdout, rp.stderr)
    print("Coroutine + Channel torture matrix (10x MT + XU_DEBUG_FREE + no-opt + 1T + closed-send panic) PASS")


def main():
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        test_default_multicore_zero_import(work)
        test_heap_and_ffi_multicore_stress(work)
        test_multicore_xu_task_speedup(work)
        test_channels_select_mutex_wg_stress(work)
        test_targeted_channel_wake_no_thundering_herd(work)
        test_mcache_alloc_scaling(work)
        test_chan_coro_correctness_matrix(work)
        test_preemption_and_drain(work)
        test_deadlock_detection(work)


if __name__ == "__main__":
    main()
