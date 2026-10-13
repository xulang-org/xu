#!/usr/bin/env python3
"""Alloc/free multi-instance ledger battery.

Product emits a heap ledger into user binaries only when the **product
compiler process** has XU_GEN1_HEAP_LEDGER=1 at build time. This script
sets that env for every compile automatically.

  XUPATH=$PWD/src python3 scripts/memsafe_heap_ledger_test.py

Default product runtime stays ledger-free (crypto/sm9 cost). With the env
switch, short-lived ownership programs must show live_bytes=0 and
allocs==frees when they fully drop.
"""
from __future__ import annotations
import os, re, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
XU = os.environ.get("XU", "/tmp/xu_prod")
ENV = os.environ.copy()
ENV["XUPATH"] = str(ROOT / "src")
# Force ledger instrumentation into the compiled test binaries.
ENV["XU_GEN1_HEAP_LEDGER"] = "1"

# contract:
#   stdout must match
#   live_eq0: stderr live_bytes must be 0
#   allocs_eq_frees: allocs == frees
#   loud: non-zero exit (or compile reject)
#   any_exit: just run successfully (process-scoped may retain)

CASES = [
    # name, src, expect_stdout, live_eq0, af_balanced
    ("tmp_concat", '''
@main
fn main() int {
    a := "hello"
    b := "world"
    println(a + b)
    << 0
}
''', "helloworld\n", True, True),
    ("tmp_loop_drop", '''
@main
fn main() int {
    mut s := ""
    for i in 0 -< 12 {
        s = s + "0123456789abcdef"
    }
    println(s.len)
    s = "done"
    println(s)
    << 0
}
''', "192\ndone\n", True, True),
    ("tmp_arr_push_drop", '''
@main
fn main() int {
    mut a := []string{}
    for i in 0 -< 30 {
        a.push("x" + str(i) + "_pad")
    }
    println(a.len)
    println(a[29])
    << 0
}
''', "30\nx29_pad\n", True, True),
    ("tmp_arr_overwrite", '''
@main
fn main() int {
    mut a := []string{}
    a.push("aaaa_padpad")
    a.push("bbbb_padpad")
    a[0] = "cccc"
    println(a[0])
    << 0
}
''', "cccc\n", True, True),
    ("tmp_struct_field_churn", '''
@main
struct U { s string }
fn main() int {
    mut u := U{s: "init"}
    for i in 0 -< 20 {
        u.s = "v" + str(i) + "_padpad"
    }
    println(u.s)
    << 0
}
''', "v19_padpad\n", True, True),
    ("tmp_nested_struct", '''
@main
struct Leaf { s string }
struct Root { a Leaf t string }
fn main() int {
    r := Root{a: Leaf{s: "AA_pad"}, t: "top"}
    println(r.a.s + r.t)
    << 0
}
''', "AA_padtop\n", True, True),
    ("tmp_map_owning", '''
@main
fn main() int {
    mut m := map[string]string{}
    for i in 0 -< 15 {
        m["k" + str(i)] = "v" + str(i) + "_pad"
    }
    m["k0"] = "replaced"
    println(m["k0"])
    << 0
}
''', "replaced\n", False, False),  # map may retain buckets until process exit
    ("tmp_slice_copy", '''
@main
fn main() int {
    s := "0123456789"
    t := s[2 -< 6]
    println(t)
    << 0
}
''', "2345\n", True, True),
    ("tmp_fn_arg", '''
@main
fn take(s string) string { << s + "!" }
fn main() int {
    println(take("arg_pad"))
    << 0
}
''', "arg_pad!\n", True, True),
    ("tmp_closure", '''
@main
fn main() int {
    b := "cap"
    f := fn() string { << b + "!" }
    println(f())
    << 0
}
''', "cap!\n", False, False),
    ("tmp_live_end", '''
@main
fn main() int {
    mut a := []string{}
    for i in 0 -< 10 {
        a.push("keep" + str(i))
    }
    println(a.len)
    << 0
}
''', "10\n", False, False),  # array still live at exit
    ("loud_oob", '''
@main
fn main() int {
    a := [3]int{1,2,3}
    mut i := 3
    println(a[i])
    << 0
}
''', None, False, False),
    ("loud_div", '''
@main
fn main() int {
    mut z := 0
    println(1/z)
    << 0
}
''', None, False, False),
]

def parse_stats(err: str) -> dict:
    out = {}
    for key in ("live_bytes", "peak_bytes", "allocs", "frees",
                "unknown_frees", "double_frees", "ledger_overflows"):
        m = re.search(rf"{key}=(\d+)", err)
        if m:
            out[key] = int(m.group(1))
    return out

def run_case(name, src, expect, live_eq0, af_balanced):
    td = Path(tempfile.mkdtemp(prefix=f"xuHF_{name}_"))
    (td / "main.xu").write_text(src.lstrip("\n"))
    out = td / "a.out"
    e = ENV.copy()
    e["XU_GEN1_HEAP_LEDGER"] = "1"
    try:
        p = subprocess.run([XU, "build", str(td / "main.xu"), "-o", str(out)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=e, timeout=25)
    except subprocess.TimeoutExpired:
        return name, False, "compile-timeout"
    if expect is None:
        # loud: compile reject OK
        if p.returncode != 0:
            return name, True, "compile-reject"
        binp = out if out.is_file() else Path(str(out) + ".exe")
        try:
            r = subprocess.run([str(binp)], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=8)
        except subprocess.TimeoutExpired:
            return name, False, "run-timeout"
        if r.returncode == 0:
            return name, False, f"not-loud {r.stdout[:40]!r}"
        return name, True, f"loud exit={r.returncode}"

    if p.returncode != 0:
        return name, False, f"compile {(p.stderr.decode().splitlines() or [''])[0][:90]}"
    binp = out if out.is_file() else Path(str(out) + ".exe")
    if not binp.is_file():
        return name, False, "no-bin"
    env = os.environ.copy()
    env["XU_HEAP_STATS"] = "1"
    try:
        r = subprocess.run([str(binp)], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=10, env=env)
    except subprocess.TimeoutExpired:
        return name, False, "run-timeout"
    if r.returncode != 0:
        return name, False, f"run rc={r.returncode} err={r.stderr.decode()[:80]!r}"
    got = r.stdout.decode()
    if got != expect:
        return name, False, f"stdout {got!r} want {expect!r}"
    st = parse_stats(r.stderr.decode())
    if not st:
        return name, False, f"no heap stats stderr={r.stderr.decode()[:80]!r}"
    notes = []
    if live_eq0 and st.get("live_bytes", -1) != 0:
        return name, False, f"live_bytes={st.get('live_bytes')} stats={st}"
    if af_balanced:
        if st.get("allocs") != st.get("frees"):
            return name, False, f"allocs!=frees {st}"
        if st.get("unknown_frees", 0) != 0 or st.get("double_frees", 0) != 0:
            return name, False, f"bad frees {st}"
    if st.get("ledger_overflows", 0) != 0:
        return name, False, f"ledger overflow {st}"
    if st.get("double_frees", 0) != 0:
        return name, False, f"double free {st}"
    if st.get("unknown_frees", 0) != 0:
        return name, False, f"unknown free {st}"
    return name, True, f"ok {st}"

def main():
    print(f"heap-ledger cases={len(CASES)} xu={XU}")
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(run_case, *c) for c in CASES]
        for f in as_completed(futs):
            results.append(f.result())
    results.sort()
    ok = sum(1 for r in results if r[1])
    bad = [r for r in results if not r[1]]
    for n, good, d in results:
        print(f"{'PASS' if good else 'FAIL':4} {n:24} {d[:100]}")
    print("====")
    print(f"heap_ledger_multi pass={ok} fail={len(bad)} total={len(results)}")
    return 0 if not bad else 1

if __name__ == "__main__":
    raise SystemExit(main())
