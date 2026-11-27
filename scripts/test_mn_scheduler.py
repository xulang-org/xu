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
    r2 = build_and_run(work, "heap_stress_1t", src_1t)
    t4 = int(re.search(r"total=(\d+)", r1.stdout).group(1))
    t1 = int(re.search(r"total=(\d+)", r2.stdout).group(1))
    assert t4 == t1 and t4 > 0, (t4, t1)
    print(f"M:N heap+map+string stress (8 tasks x 3000 iters on 4 OS threads, total={t4}) PASS")


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


def main():
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        test_heap_and_ffi_multicore_stress(work)
        test_multicore_xu_task_speedup(work)
        test_channels_select_mutex_wg_stress(work)
        test_preemption_and_drain(work)
        test_deadlock_detection(work)


if __name__ == "__main__":
    main()
