#!/usr/bin/env python3
"""FieldAssign / DropField heap-ledger multi-instance battery.

Compiles each case with XU_GEN1_HEAP_LEDGER=1 and requires:
  - stdout contract
  - unknown_frees=0, double_frees=0
  - live_bytes=0 and allocs==frees when `balanced` is set
"""
from __future__ import annotations
import os, re, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
XU = os.environ.get("XU", "/tmp/xu_prod")

# name, src, expect_stdout, balanced
CASES = [
("field_assign_two", """
@main
struct U { a string b string }
fn main() int {
    $u := U{a: "a0_" + "padpadpadpadpad", b: "b0_" + "padpadpadpadpad"}
    u.a = "a1_" + "padpadpadpadpad"
    u.b = "b1_" + "padpadpadpadpad"
    u.a = "a2_" + "padpadpad"
    println(u.a)
    println(u.b)
    << 0
}
""", "a2_padpadpad\nb1_padpadpadpadpad\n", True),

("field_assign_loop_one", """
@main
struct U { s string }
fn main() int {
    $u := U{s: "init_" + "padpadpadpad"}
    for i in 0 -< 20 {
        u.s = "v" + str(i) + "_" + "padpadpadpad"
    }
    println(u.s)
    << 0
}
""", "v19_padpadpadpad\n", True),

("field_assign_loop_both", """
@main
struct U { a string b string }
fn main() int {
    $u := U{a: "a0_" + "padpadpadpad", b: "b0_" + "padpadpadpad"}
    for i in 0 -< 12 {
        u.a = "a" + str(i) + "_" + "padpadpadpad"
        u.b = "b" + str(i) + "_" + "padpadpadpad"
    }
    println(u.a)
    println(u.b)
    << 0
}
""", "a11_padpadpadpad\nb11_padpadpadpad\n", True),

("nested_field_assign", """
@main
struct Leaf { s string }
struct Root { a Leaf b Leaf }
fn main() int {
    $r := Root{a: Leaf{s: "A0_" + "padpadpadpad"}, b: Leaf{s: "B0_" + "padpadpadpad"}}
    for i in 0 -< 8 {
        r.a.s = "A" + str(i) + "_" + "padpadpadpad"
        r.b.s = "B" + str(i) + "_" + "padpadpadpad"
    }
    println(r.a.s)
    println(r.b.s)
    << 0
}
""", "A7_padpadpadpad\nB7_padpadpadpad\n", True),

("array_elem_assign", """
@main
fn main() int {
    $a := []string{}
    for i in 0 -< 6 {
        a.push("s" + str(i) + "_" + "padpadpadpad")
    }
    for i in 0 -< 6 {
        a[i] = "r" + str(i) + "_" + "padpadpadpad"
    }
    println(a[0])
    println(a[5])
    << 0
}
""", "r0_padpadpadpad\nr5_padpadpadpad\n", True),

("array_struct_field_assign", """
@main
struct P { name string id int }
fn main() int {
    $ps := []P{}
    for i in 0 -< 8 {
        ps.push(P{name: "n" + str(i) + "_" + "padpadpadpad", id: i})
    }
    for i in 0 -< 8 {
        ps[i].name = "m" + str(i) + "_" + "padpadpadpad"
    }
    println(ps[0].name)
    println(ps[7].id)
    << 0
}
""", "m0_padpadpadpad\n7\n", True),

("map_value_assign", """
@main
fn main() int {
    $m := map[string]string{}
    for i in 0 -< 8 {
        m["k" + str(i)] = "v" + str(i) + "_" + "padpadpadpad"
    }
    for i in 0 -< 8 {
        m["k" + str(i)] = "w" + str(i) + "_" + "padpadpadpad"
    }
    println(m["k0"])
    << 0
}
""", "w0_padpadpadpad\n", False),  # map buckets may retain

("rebind_local_struct", """
@main
struct U { s string }
fn main() int {
    $u := U{s: "old_" + "padpadpadpad"}
    u = U{s: "new_" + "padpadpadpad"}
    println(u.s)
    << 0
}
""", "new_padpadpadpad\n", True),

("field_assign_fn_result", """
@main
struct U { s string }
fn make(i int) string {
    << "m" + str(i) + "_" + "padpadpadpad"
}
fn main() int {
    $u := U{s: make(0)}
    u.s = make(1)
    u.s = make(2)
    println(u.s)
    << 0
}
""", "m2_padpadpadpad\n", True),

("store_index_then_field", """
@main
struct Cell { s string }
fn main() int {
    $a := []Cell{}
    a.push(Cell{s: "c0_" + "padpadpadpad"})
    a.push(Cell{s: "c1_" + "padpadpadpad"})
    a[0] = Cell{s: "d0_" + "padpadpadpad"}
    a[0].s = "e0_" + "padpadpadpad"
    println(a[0].s)
    println(a[1].s)
    << 0
}
""", "e0_padpadpadpad\nc1_padpadpadpad\n", True),

("drop_intermediate_concat", """
@main
struct U { s string }
fn main() int {
    $u := U{s: ""}
    for i in 0 -< 10 {
        u.s = "x" + str(i) + "_" + "padpadpadpad"
        u.s = u.s + "_tailpadpad"
    }
    println(u.s)
    << 0
}
""", "x9_padpadpadpad_tailpadpad\n", True),

("no_drop_when_moved_out", """
@main
struct U { s string }
fn take(s string) {
    println(s)
}
fn main() int {
    $u := U{s: "mv_" + "padpadpadpad"}
    take(u.s)
    u.s = "after_" + "padpadpadpad"
    println(u.s)
    << 0
}
""", "mv_padpadpadpad\nafter_padpadpadpad\n", True),

("map_get_println_drop", """
@main
fn main() int {
    $m := map[string]string{}
    m["a"] = "aa_" + "padpadpadpad"
    m["b"] = "bb_" + "padpadpadpad"
    println(m["a"])
    println(m.has("b"))
    println(m.len())
    << 0
}
""", "aa_padpadpadpad\ntrue\n2\n", True),

("map_str_loop_get_drop", """
@main
fn main() int {
    $m := map[string]string{}
    for i in 0 -< 4 {
        m["k" + str(i)] = "v" + str(i) + "_" + "padpadpadpad"
    }
    println(m["k0"])
    println(m["k3"])
    << 0
}
""", "v0_padpadpadpad\nv3_padpadpadpad\n", True),
]


def parse_stats(err: str) -> dict:
    out = {}
    for key in ("live_bytes", "peak_bytes", "allocs", "frees",
                "unknown_frees", "double_frees", "ledger_overflows"):
        m = re.search(rf"{key}=(\d+)", err)
        if m:
            out[key] = int(m.group(1))
    return out


def run_case(name, src, expect, balanced):
    td = Path(tempfile.mkdtemp(prefix=f"xuFA_{name}_"))
    (td / "main.xu").write_text(src.lstrip("\n"))
    out = td / "a.out"
    env = os.environ.copy()
    env["XUPATH"] = str(ROOT / "src")
    env["XU_GEN1_HEAP_LEDGER"] = "1"
    env["XU_HEAP_STATS"] = "1"
    try:
        p = subprocess.run([XU, "build", str(td / "main.xu"), "-o", str(out)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, timeout=25)
    except subprocess.TimeoutExpired:
        return name, False, "compile-timeout"
    if p.returncode != 0:
        return name, False, f"compile {(p.stderr.decode().splitlines() or [''])[0][:100]}"
    binp = out if out.is_file() else Path(str(out) + ".exe")
    if not binp.is_file():
        return name, False, "no-bin"
    try:
        r = subprocess.run([str(binp)], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=10, env=env)
    except subprocess.TimeoutExpired:
        return name, False, "run-timeout"
    if r.returncode != 0:
        return name, False, f"run rc={r.returncode} {r.stderr.decode()[:80]!r}"
    got = r.stdout.decode()
    if got != expect:
        return name, False, f"stdout {got!r} want {expect!r}"
    st = parse_stats(r.stderr.decode())
    if not st:
        return name, False, f"no-stats {r.stderr.decode()[:80]!r}"
    if st.get("unknown_frees", 0) != 0:
        return name, False, f"unknown_frees {st}"
    if st.get("double_frees", 0) != 0:
        return name, False, f"double_frees {st}"
    if st.get("ledger_overflows", 0) != 0:
        return name, False, f"overflow {st}"
    if balanced:
        if st.get("live_bytes", -1) != 0:
            return name, False, f"live_bytes!=0 {st}"
        if st.get("allocs") != st.get("frees"):
            return name, False, f"allocs!=frees {st}"
    return name, True, f"ok {st}"


def main():
    print(f"field-assign ledger cases={len(CASES)} xu={XU}")
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(run_case, *c) for c in CASES]
        for f in as_completed(futs):
            results.append(f.result())
    results.sort()
    ok = sum(1 for r in results if r[1])
    bad = [r for r in results if not r[1]]
    for n, good, d in results:
        print(f"{'PASS' if good else 'FAIL':4} {n:28} {d[:100]}")
    print("====")
    print(f"field_assign_ledger pass={ok} fail={len(bad)} total={len(results)}")
    for n, _, d in bad:
        print(f"  {n}: {d[:140]}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
