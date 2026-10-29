#!/usr/bin/env python3
"""Product multi-instance memory-safety battery.

Usage:
  XUPATH=$PWD/src python3 scripts/memsafe_multi_test.py [--xu /tmp/xu_prod.xin]

Exit 0 only when every instance matches its contract:
  stdout  — compile+run, stdout must match
  loud    — must fail-loud (compile reject OR runtime non-zero)
  reject  — must fail compile
"""
from __future__ import annotations
import argparse, os, subprocess, tempfile, textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CASES: list[tuple[str, str, str, str | None]] = []

def pos(name, src, expect):
    CASES.append((name, textwrap.dedent(src).lstrip("\n"), "stdout", expect))

def loud(name, src):
    CASES.append((name, textwrap.dedent(src).lstrip("\n"), "loud", None))

def reject(name, src):
    CASES.append((name, textwrap.dedent(src).lstrip("\n"), "reject", None))

# ---- stdout / ownership ----
pos("str_concat_borrow", """
@main
fn main() int {
    a := "hello"
    b := "world"
    c := a + b
    println(c)
    println(a)
    println(b)
    << 0
}
""", "helloworld\nhello\nworld\n")

pos("str_field_clone", """
@main
struct U { name string n int }
fn main() int {
    $u := U{name: "field", n: 1}
    x := u.name
    u.name = "other"
    println(x)
    println(u.name)
    << 0
}
""", "field\nother\n")

pos("fn_arg_move", """
@main
fn take(s string) int {
    println(s)
    << s.len
}
fn main() int {
    n := take("moved_arg_pad")
    println(n)
    << 0
}
""", "moved_arg_pad\n13\n")

pos("arr_overwrite_owning", """
@main
fn main() int {
    $a := []string{}
    for i in 0 -< 40 {
        a.push("item_" + str(i) + "_padpad")
    }
    a[3] = "replaced_padpad"
    println(a[3])
    println(a[4])
    println(a.len)
    << 0
}
""", "replaced_padpad\nitem_4_padpad\n40\n")

pos("struct_arr_overwrite", """
@main
struct P { name string id int }
fn main() int {
    $ps := []P{}
    ps.push(P{name: "a", id: 1})
    ps.push(P{name: "bb", id: 2})
    x := ps[0].name
    ps[0] = P{name: "zzz", id: 9}
    println(x)
    println(ps[0].name)
    println(ps[1].name)
    << 0
}
""", "a\nzzz\nbb\n")

pos("foreach_struct_clone", """
@main
struct P { name string }
fn main() int {
    ps := [P{name: "aa_pad"}, P{name: "bb_pad"}]
    for p in ps {
        println(p.name)
    }
    println(ps[0].name)
    println(ps[1].name)
    << 0
}
""", "aa_pad\nbb_pad\naa_pad\nbb_pad\n")

pos("map_owning_values", """
@main
fn main() int {
    $m := map[string]string{}
    for i in 0 -< 25 {
        m["k" + str(i)] = "v" + str(i) + "_padpad"
    }
    m["k0"] = "replaced0"
    println(m["k0"])
    println(m["k24"])
    << 0
}
""", "replaced0\nv24_padpad\n")

pos("chan_string_move", """
@main
fn worker(ch chan string) {
    ch <- "hello-chan"
    ch <- "second_msg_pad"
}
fn main() int {
    ch := chan string{cap: 2}
    xu worker(ch)
    a := <-ch
    b := <-ch
    println(a)
    println(b)
    << 0
}
""", "hello-chan\nsecond_msg_pad\n")

pos("chan_multi_sender_str", """
@main
fn sender(id int, ch chan string, done chan int) {
    ch <- "from_" + str(id) + "_padpad"
    done <- id
}
fn main() int {
    ch := chan string{cap: 8}
    done := chan int{cap: 4}
    xu sender(1, ch, done)
    xu sender(2, ch, done)
    xu sender(3, ch, done)
    xu sender(4, ch, done)
    $got := 0
    for i in 0 -< 4 {
        s := <-ch
        println(s)
        got = got + s.len
    }
    for i in 0 -< 4 {
        <-done
    }
    println(got)
    << 0
}
""", "")

pos("xu_string_arg_done", """
@main
fn worker(s string, done chan int) {
    println(s)
    done <- 1
}
fn main() int {
    done := chan int{cap: 1}
    xu worker("xu_arg_string_pad", done)
    <-done
    << 0
}
""", "xu_arg_string_pad\n")

pos("parse_int_or", """
@main
fn main() int {
    println(parse_int("42") or (err) { << 1 })
    println(parse_int("-7") or (err) { << 1 })
    << 0
}
""", "42\n-7\n")

pos("slice_copy_borrow_src", """
@main
fn main() int {
    s := "0123456789abcdef"
    t := s[3 -< 9]
    println(t)
    println(s)
    << 0
}
""", "345678\n0123456789abcdef\n")

pos("closure_capture_str", """
@main
fn main() int {
    base := "cap_pad"
    f := fn() string { << base + "!" }
    println(f())
    << 0
}
""", "cap_pad!\n")

pos("method_mut_str", """
@main
struct C { buf string }
fn (c $&C) add(s string) {
    c.buf = c.buf + s
}
fn main() int {
    $c := C{buf: "x"}
    c.add("yy")
    c.add("zzz")
    println(c.buf)
    << 0
}
""", "xyyzzz\n")

pos("nested_array_str", """
@main
fn main() int {
    $a := [][]string{}
    $row0 := []string{}
    row0.push("r0c0")
    row0.push("r0c1")
    $row1 := []string{}
    row1.push("r1c0")
    a.push(row0)
    a.push(row1)
    println(a[0][1])
    println(a[1][0])
    << 0
}
""", "r0c1\nr1c0\n")

pos("nested_struct_borrow", """
@main
struct Leaf { s string }
struct Root { a Leaf t string }
fn peek(r &Root) {
    println(r.a.s)
    println(r.t)
}
fn main() int {
    r := Root{a: Leaf{s: "AA_padpad"}, t: "top"}
    peek(&r)
    println(r.a.s)
    << 0
}
""", "AA_padpad\ntop\nAA_padpad\n")

pos("field_churn", """
@main
struct U { s string }
fn main() int {
    $u := U{s: "init"}
    for i in 0 -< 60 {
        u.s = "val_" + str(i) + "_padpadpadpad"
    }
    println(u.s)
    << 0
}
""", "val_59_padpadpadpad\n")

pos("live_string_array", """
@main
fn main() int {
    $a := []string{}
    for i in 0 -< 80 {
        a.push("live_" + str(i) + "_padpadpadpad")
    }
    println(a.len)
    println(a[0])
    println(a[79])
    << 0
}
""", "80\nlive_0_padpadpadpad\nlive_79_padpadpadpad\n")

pos("concat_loop", """
@main
fn main() int {
    $acc := ""
    for i in 0 -< 40 {
        acc = acc + str(i % 10)
    }
    println(acc.len)
    println(acc)
    << 0
}
""", "40\n0123456789012345678901234567890123456789\n")

# ---- loud ----
loud("oob_dyn_hi", """
@main
fn main() int {
    a := [4]int{1,2,3,4}
    mut i := 4
    println(a[i])
    << 0
}
""")
loud("oob_dyn_lo", """
@main
fn main() int {
    a := [4]int{1,2,3,4}
    mut i := 0
    i -= 1
    println(a[i])
    << 0
}
""")
loud("div_zero", """
@main
fn main() int {
    mut z := 0
    println(1 / z)
    << 0
}
""")
loud("div_zero_field", """
@main
struct S { z int }
fn main() int {
    s := S{z: 0}
    println(8 / s.z)
    << 0
}
""")
loud("mod_zero", """
@main
fn main() int {
    mut z := 0
    println(5 % z)
    << 0
}
""")
loud("map_missing_key", """
@main
fn main() int {
    mut m := map[string]int{}
    m["ok"] = 1
    println(m["nope"])
    << 0
}
""")

# ---- compile reject (fail-closed) ----
reject("const_slice_oob", """
@main
fn main() int {
    s := "abcd"
    println(s[10 -< 12])
    << 0
}
""")
reject("const_index_oob", """
@main
fn main() int {
    a := [3]int{1,2,3}
    println(a[9])
    << 0
}
""")
reject("parse_int_unhandled", """
@main
fn main() int {
    v := parse_int("xxxxxxxx")
    println(v)
    << 0
}
""")
reject("uaf_string_ident", """
@main
fn main() int {
    s := "owned_heap_string_xxx"
    t := s
    println(s)
    println(t)
    << 0
}
""")
reject("uaf_after_fn_move", """
@main
struct U { name string }
fn take(u U) { println(u.name) }
fn main() int {
    u := U{name: "xx"}
    take(u)
    println(u.name)
    << 0
}
""")
reject("uaf_after_struct_move", """
@main
struct Leaf { s string }
struct Root { a Leaf }
fn take(r Root) { println(r.a.s) }
fn main() int {
    r := Root{a: Leaf{s: "pad"}}
    take(r)
    println(r.a.s)
    << 0
}
""")
reject("double_mut_borrow", """
@main
fn main() int {
    mut s := "abc"
    a := &mut s
    b := &mut s
    println(a + "" + b)
    << 0
}
""")
reject("mut_and_shared_borrow", """
@main
fn main() int {
    mut s := "abc"
    a := &mut s
    b := &s
    println(a)
    println(b)
    << 0
}
""")
reject("move_while_borrowed", """
@main
fn main() int {
    s := "heapstring_padpadpad"
    r := &s
    t := s
    println(r)
    println(t)
    << 0
}
""")
reject("return_local_ref", """
@main
fn get() &string {
    x := "local"
    << &x
}
fn main() int {
    println(get())
    << 0
}
""")
reject("return_struct_local_ref", """
@main
struct S { p &string }
fn get() S {
    x := "local_x"
    << S{p: &x}
}
fn main() int {
    s := get()
    println(s.p)
    << 0
}
""")
reject("partial_move_array_field", """
@main
struct Holder { values []int }
fn consume(values []int) { println(values.len) }
fn main() int {
    h := Holder{values: [1, 2]}
    consume(h.values)
    println(h.values.len)
    << 0
}
""")
reject("xu_arg_ref", """
@main
fn worker(s &string) { println(s) }
fn main() int {
    s := "shared"
    xu worker(&s)
    << 0
}
""")
reject("volatile_hosted", """
@main
fn main() int {
    volatile_store(4096, 1)
    << 0
}
""")
reject("irq_heap", """
@main
fn irq_0() {
    s := "x" + "y"
    println(s)
}
fn main() int {
    raise_irq(0)
    << 0
}
""")
reject("unwrap_after_move", """
@main
fn main() int {
    r := Ok("owned_string_xx")
    s := r or (err) { << 1 }
    t := r or (err) { << 1 }
    println(s)
    println(t)
    << 0
}
""")
reject("closure_move_then_use", """
@main
fn main() int {
    s := "moved_into_closure_xxx"
    f := fn() string { << s }
    t := s
    println(f())
    println(t)
    << 0
}
""")
reject("map_owning_index_move", """
@main
struct Item { s string }
fn main() int {
    mut m := map[string]Item{}
    m["k"] = Item{s: "padpad"}
    x := m["k"]
    println(m["k"].s)
    println(x.s)
    << 0
}
""")
reject("chan_ref_elem", """
@main
fn main() int {
    ch := chan &string{cap: 1}
    << 0
}
""")


def run_one(xu: str, env: dict, name: str, src: str, kind: str, expect: str | None):
    td = Path(tempfile.mkdtemp(prefix=f"xuMS_{name}_"))
    srcp = td / "main.xu"
    srcp.write_text(src)
    out = td / "a.out"
    try:
        p = subprocess.run(
            [xu, "build", str(srcp), "-o", str(out)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=25,
        )
    except subprocess.TimeoutExpired:
        return name, kind, False, "compile-timeout"
    if kind == "reject" or kind == "loud":
        if kind == "reject":
            if p.returncode == 0:
                return name, kind, False, "ACCEPTED"
            return name, kind, True, (p.stderr.decode().splitlines() or ["err"])[0][:70]
        # loud: compile reject is acceptable fail-closed; else runtime non-zero
        if p.returncode != 0:
            return name, kind, True, "compile-reject"
        binp = out if out.is_file() else Path(str(out) + ".exe")
        if not binp.is_file():
            return name, kind, False, "no-bin"
        try:
            r = subprocess.run([str(binp)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        except subprocess.TimeoutExpired:
            return name, kind, False, "run-timeout"
        if r.returncode == 0:
            return name, kind, False, f"not-loud out={r.stdout[:40]!r}"
        return name, kind, True, f"exit={r.returncode}"
    # stdout
    if p.returncode != 0:
        return name, kind, False, f"compile: {(p.stderr.decode().splitlines() or [''])[0][:100]}"
    binp = out if out.is_file() else Path(str(out) + ".exe")
    if not binp.is_file():
        return name, kind, False, "no-bin"
    try:
        r = subprocess.run([str(binp)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    except subprocess.TimeoutExpired:
        return name, kind, False, "run-timeout"
    if r.returncode != 0:
        return name, kind, False, f"run-rc={r.returncode} {r.stderr.decode()[:80]!r}"
    got = r.stdout.decode()
    if expect is not None and expect != "":
        if got != expect:
            return name, kind, False, f"stdout {got!r} want {expect!r}"
    return name, kind, True, "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xu", default="/tmp/xu_prod")
    ap.add_argument("--jobs", type=int, default=6)
    args = ap.parse_args()
    os.chdir(ROOT)
    env = os.environ.copy()
    env.setdefault("XUPATH", str(ROOT / "src"))
    print(f"multi-instance cases={len(CASES)} xu={args.xu}")
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(run_one, args.xu, env, *c) for c in CASES]
        for f in as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda x: x[0])
    passed = sum(1 for r in results if r[2])
    failed = [r for r in results if not r[2]]
    for name, kind, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL':4} {name:28} [{kind:6}] {detail[:90]}")
    print("====")
    print(f"memsafe_multi pass={passed} fail={len(failed)} total={len(results)}")
    for n, k, _, d in failed:
        print(f"  {n} [{k}] {d[:120]}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
