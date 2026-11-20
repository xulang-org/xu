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

    test_src = """@main
#sync

fn worker(c sync.Cond, m sync.Mutex, ready chan int, wake_ch chan int) {
    $mu := m
    $cd := c
    mu.lock()
    ready <- 1
    cd.wait($&mu)
    mu.unlock()
    wake_ch <- 1
}

fn test_no_waiter_signal_not_buffered() {
    $mu := sync.mutex()
    $cd := sync.cond()

    // Signal and broadcast when nobody is waiting
    cd.signal()
    cd.broadcast()

    ready := chan int{cap: 1}
    wake_ch := chan int{cap: 1}

    xu worker(cd, mu, ready, wake_ch)

    // Wait until worker is holding lock and entering wait
    _ := <-ready

    // Let worker definitely reach wait
    $spin := 0
    while spin < 50000 { spin = spin + 1 }

    // Check that worker did NOT wake up from the earlier signal/broadcast
    $woke_early := false
    select {
        _ := <-wake_ch {
            woke_early = true
        }
        else {
            woke_early = false
        }
    }
    if woke_early {
        println("ERROR: worker woke up from early signal/broadcast!")
        <<< 1
    }
    println("OK: worker did not wake from pre-wait signal/broadcast")

    // Now send legitimate signal to wake it up
    cd.signal()
    w := <-wake_ch
    if w != 1 {
        println("ERROR: worker did not wake on signal")
        <<< 1
    }
    println("OK: worker woke on actual signal")
}

fn test_two_waiters_one_signal() {
    $mu := sync.mutex()
    $cd := sync.cond()

    ready := chan int{cap: 2}
    wake_ch := chan int{cap: 2}

    xu worker(cd, mu, ready, wake_ch)
    xu worker(cd, mu, ready, wake_ch)

    $tmp := 0
    tmp = <-ready
    tmp = <-ready

    $spin := 0
    while spin < 50000 { spin = spin + 1 }

    // Wake exactly one
    cd.signal()

    w1 := <-wake_ch
    if w1 != 1 {
        println("ERROR: first wake failed")
        <<< 1
    }

    $spin2 := 0
    while spin2 < 50000 { spin2 = spin2 + 1 }

    $second_woke := false
    select {
        _ := <-wake_ch {
            second_woke = true
        }
        else {
            second_woke = false
        }
    }
    if second_woke {
        println("ERROR: second worker woke on single signal!")
        <<< 1
    }
    println("OK: exactly one worker woke on signal")

    // Wake the second
    cd.signal()
    w2 := <-wake_ch
    if w2 != 1 {
        println("ERROR: second wake failed")
        <<< 1
    }
    println("OK: second worker woke on second signal")
}

fn test_broadcast_and_late_arrival() {
    $mu := sync.mutex()
    $cd := sync.cond()

    ready := chan int{cap: 3}
    wake_ch := chan int{cap: 3}

    xu worker(cd, mu, ready, wake_ch)
    xu worker(cd, mu, ready, wake_ch)
    xu worker(cd, mu, ready, wake_ch)

    $tmp := 0
    tmp = <-ready
    tmp = <-ready
    tmp = <-ready

    $spin := 0
    while spin < 50000 { spin = spin + 1 }

    // Broadcast should wake all 3
    cd.broadcast()

    tmp = <-wake_ch
    tmp = <-wake_ch
    tmp = <-wake_ch
    println("OK: all 3 waiters woke on broadcast")

    // Now test a late arrival (registers after broadcast)
    ready2 := chan int{cap: 1}
    wake_ch2 := chan int{cap: 1}
    xu worker(cd, mu, ready2, wake_ch2)
    tmp = <-ready2

    $spin2 := 0
    while spin2 < 50000 { spin2 = spin2 + 1 }

    $late_woke := false
    select {
        _ := <-wake_ch2 {
            late_woke = true
        }
        else {
            late_woke = false
        }
    }
    if late_woke {
        println("ERROR: late arrival woke from past broadcast!")
        <<< 1
    }
    println("OK: late arrival does not wake from past broadcast")

    cd.signal()
    tmp = <-wake_ch2
    println("OK: late arrival woke on subsequent signal")
}

fn test_4097_waiters() {
    $mu := sync.mutex()
    $cd := sync.cond()

    // 4097 waiters boundary test
    target := 4097
    ready := chan int{cap: 4097}
    wake_ch := chan int{cap: 4097}

    $i := 0
    while i < target {
        xu worker(cd, mu, ready, wake_ch)
        i = i + 1
    }

    $r := 0
    $tmp := 0
    while r < target {
        tmp = <-ready
        r = r + 1
    }

    $spin := 0
    while spin < 100000 { spin = spin + 1 }

    cd.broadcast()

    $w := 0
    while w < target {
        tmp = <-wake_ch
        w = w + 1
    }
    println("OK: all 4097 waiters woke successfully on broadcast")
}

fn main() {
    println("Running test_no_waiter_signal_not_buffered...")
    test_no_waiter_signal_not_buffered()

    println("Running test_two_waiters_one_signal...")
    test_two_waiters_one_signal()

    println("Running test_broadcast_and_late_arrival...")
    test_broadcast_and_late_arrival()

    println("Running test_4097_waiters...")
    test_4097_waiters()

    println("ALL_COND_STEP_TESTS_PASSED")
}
"""
    scratch_path = os.path.abspath("scratch_cond_test.xu")
    try:
        with open(scratch_path, "w", encoding="utf-8") as f:
            f.write(test_src)
        
        exe_path = os.path.abspath("scratch_cond_test.exe")
        env = os.environ.copy()
        env["XU_STDLIB_ROOT"] = os.path.abspath("src")
        env["XU_ROOT"] = os.path.abspath(".")
        
        bld = subprocess.run([xu_bin, "build", "-o", exe_path, scratch_path], capture_output=True, text=True, env=env)
        if bld.returncode != 0:
            print("BUILD FAILED:\n" + bld.stderr)
            return bld.returncode
            
        proc = subprocess.run([exe_path], capture_output=True, text=True)
        print("STDOUT:\n" + proc.stdout)
        print("STDERR:\n" + proc.stderr)
        
        if os.path.exists(exe_path):
            os.remove(exe_path)
            
        if proc.returncode != 0 or "ALL_COND_STEP_TESTS_PASSED" not in proc.stdout:
            return 1
            
        return 0
    finally:
        if os.path.exists(scratch_path):
            os.remove(scratch_path)

if __name__ == "__main__":
    sys.exit(main())
