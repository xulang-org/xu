#!/usr/bin/env python3
"""Drop / ownership multi-instance battery (default product, no heap ledger).

Contract: compile+run, stdout exact. Fail-closed cases must reject compile.
"""
from __future__ import annotations
import os, subprocess, tempfile, textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XU = os.environ.get("XU", "/tmp/xu_prod")

CASES = []

def pos(name, src, expect):
    CASES.append((name, textwrap.dedent(src).lstrip("\n"), "stdout", expect))

def reject(name, src):
    CASES.append((name, textwrap.dedent(src).lstrip("\n"), "reject", None))

def loud(name, src):
    CASES.append((name, textwrap.dedent(src).lstrip("\n"), "loud", None))

# --- drop / ownership positives ---
pos("struct_scope_drop", """
@main
struct U { s string n int }
fn main() int {
    $u := U{s: "init_padpad", n: 1}
    for i in 0 -< 15 {
        u.s = "v" + str(i) + "_padpadpad"
    }
    println(u.s)
    println(u.n)
    << 0
}
""", "v14_padpadpad\n1\n")

pos("nested_struct_drop", """
@main
struct Leaf { s string }
struct Mid { a Leaf b Leaf }
struct Root { m Mid t string }
fn main() int {
    $r := Root{m: Mid{a: Leaf{s: "A_padpad"}, b: Leaf{s: "B_padpad"}}, t: "top"}
    r.m.a.s = "AA_padpad"
    println(r.m.a.s)
    println(r.m.b.s)
    println(r.t)
    << 0
}
""", "AA_padpad\nB_padpad\ntop\n")

pos("throw_payload_drop", """
@main
#errors
fn may(ok bool) string {
    if ok {
        << "payload_padpad"
    }
    >> errors.new("err_padpad")
    << ""
}
fn main() int {
    a := may(true) or (e) {
        println(e.msg())
        << 1
    }
    println(a)
    b := may(false) or (e) {
        println(e.msg())
        << 0
    }
    println(b)
    << 0
}
""", "payload_padpad\nerr_padpad\n")

pos("throw_propagate_str", """
@main
#errors
fn inner() string {
    >> errors.new("boom_padpad")
    << ""
}
fn outer() string {
    << inner() or >>
}
fn main() int {
    r := outer() or (e) {
        println(e.msg())
        << 0
    }
    println(r)
    << 0
}
""", "boom_padpad\n")

pos("array_struct_scope", """
@main
struct P { name string id int }
fn main() int {
    $ps := []P{}
    for i in 0 -< 12 {
        ps.push(P{name: "p" + str(i) + "_padpad", id: i})
    }
    println(ps[11].name)
    println(ps[0].id)
    << 0
}
""", "p11_padpad\n0\n")

pos("rebind_struct_field_loop", """
@main
struct Box { a string b string }
fn main() int {
    $x := Box{a: "a0_padpad", b: "b0_padpad"}
    for i in 0 -< 8 {
        x.a = "a" + str(i) + "_padpad"
        x.b = "b" + str(i) + "_padpad"
    }
    println(x.a)
    println(x.b)
    << 0
}
""", "a7_padpad\nb7_padpad\n")

pos("fn_ret_struct", """
@main
struct S { s string n int }
fn make(i int) S {
    << S{s: "m" + str(i) + "_padpad", n: i}
}
fn main() int {
    a := make(3)
    b := make(9)
    println(a.s)
    println(b.n)
    << 0
}
""", "m3_padpad\n9\n")

pos("chan_struct_msg", """
@main
struct Msg { s string n int }
fn worker(ch chan Msg) {
    ch <- Msg{s: "m1_padpad", n: 1}
    ch <- Msg{s: "m2_padpad", n: 2}
}
fn main() int {
    ch := chan Msg{cap: 2}
    xu worker(ch)
    a := <-ch
    b := <-ch
    println(a.s)
    println(b.n)
    << 0
}
""", "m1_padpad\n2\n")

pos("map_string_churn", """
@main
fn main() int {
    $m := map[string]string{}
    for i in 0 -< 12 {
        m["k" + str(i)] = "v" + str(i) + "_padpad"
    }
    m["k5"] = "replaced_pad"
    println(m["k5"])
    println(m["k11"])
    << 0
}
""", "replaced_pad\nv11_padpad\n")

pos("closure_str_capture", """
@main
fn main() int {
    x := "cap_padpad"
    f := fn() string { << x + "!" }
    println(f())
    << 0
}
""", "cap_padpad!\n")

reject("closure_struct_move_then_use", """
@main
struct S { s string }
fn main() int {
    x := S{s: "cap_padpad"}
    f := fn() string { << x.s + "!" }
    println(f())
    println(x.s)
    << 0
}
""")

# --- rejects ---
reject("uaf_struct_scope", """
@main
struct U { s string }
fn take(u U) { println(u.s) }
fn main() int {
    u := U{s: "xx_padpad"}
    take(u)
    println(u.s)
    << 0
}
""")

reject("partial_move_struct_field_array", """
@main
struct H { xs []string }
fn take(xs []string) { println(xs.len) }
fn main() int {
    $h := H{xs: []string{}}
    h.xs.push("a")
    take(h.xs)
    println(h.xs.len)
    << 0
}
""")

reject("double_free_style_result", """
@main
fn main() int {
    r := Ok("owned_padpad")
    a := r or (e) { << 1 }
    b := r or (e) { << 1 }
    println(a)
    println(b)
    << 0
}
""")

# loud
loud("oob_after_drop_loop", """
@main
fn main() int {
    $a := []string{}
    a.push("x")
    a.push("y")
    a[0] = "z_padpad"
    $i := 5
    println(a[i])
    << 0
}
""")

def run_one(env, name, src, kind, expect):
    td = Path(tempfile.mkdtemp(prefix=f"xuDM_{name}_"))
    (td / "main.xu").write_text(src)
    out = td / "a.out"
    try:
        p = subprocess.run([XU, "build", str(td / "main.xu"), "-o", str(out)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, timeout=25)
    except subprocess.TimeoutExpired:
        return name, False, "compile-timeout"
    if kind == "reject":
        if p.returncode == 0:
            return name, False, "ACCEPTED"
        return name, True, (p.stderr.decode().splitlines() or ["err"])[0][:70]
    if p.returncode != 0:
        return name, False, f"compile {(p.stderr.decode().splitlines() or [''])[0][:100]}"
    binp = out if out.is_file() else Path(str(out) + ".exe")
    if not binp.is_file():
        return name, False, "no-bin"
    try:
        r = subprocess.run([str(binp)], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=10)
    except subprocess.TimeoutExpired:
        return name, False, "run-timeout"
    if kind == "loud":
        if r.returncode == 0:
            return name, False, f"not-loud {r.stdout[:40]!r}"
        return name, True, f"exit={r.returncode}"
    if r.returncode != 0:
        return name, False, f"run-rc={r.returncode} {r.stderr.decode()[:80]!r}"
    got = r.stdout.decode()
    if expect is not None and got != expect:
        return name, False, f"stdout {got!r} want {expect!r}"
    return name, True, "ok"

def main():
    os.chdir(ROOT)
    env = os.environ.copy()
    env.setdefault("XUPATH", str(ROOT / "src"))
    print(f"drop-multi cases={len(CASES)} xu={XU}")
    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(run_one, env, *c) for c in CASES]
        for f in as_completed(futs):
            results.append(f.result())
    results.sort()
    ok = sum(1 for r in results if r[1])
    bad = [r for r in results if not r[1]]
    for n, good, d in results:
        print(f"{'PASS' if good else 'FAIL':4} {n:28} {d[:90]}")
    print("====")
    print(f"drop_multi pass={ok} fail={len(bad)} total={len(results)}")
    for n, _, d in bad:
        print(f"  {n}: {d[:120]}")
    return 0 if not bad else 1

if __name__ == "__main__":
    raise SystemExit(main())
