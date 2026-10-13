#!/usr/bin/env python3
"""Array / struct / chan foreach ledger battery."""
from __future__ import annotations
import os, re, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
XU = os.environ.get('XU', '/tmp/xu_prod.xin')
P = 'padpadpadpad'

CASES = [
("foreach_array_string", f'''
@main
fn main() int {{
    mut a := []string{{}}
    for i in 0:4 {{
        a.push("s"+str(i)+"_"+ "{P}")
    }}
    mut n := 0
    for s in a {{
        n = n + s.len
    }}
    println(n > 0)
    println(a.len)
    << 0
}}
''', "true\n4\n", True),

("foreach_array_struct", f'''
@main
struct P {{ name string id int }}
fn main() int {{
    mut ps := []P{{}}
    for i in 0:3 {{
        ps.push(P{{name: "p"+str(i)+"_"+ "{P}", id: i}})
    }}
    mut n := 0
    for p in ps {{
        n = n + p.name.len + p.id
    }}
    println(n > 0)
    println(ps.len)
    << 0
}}
''', "true\n3\n", True),

("foreach_fixed_array_int", '''
@main
fn main() int {
    a := [4]int{1,2,3,4}
    mut s := 0
    for x in a {
        s = s + x
    }
    println(s)
    << 0
}
''', "10\n", True),

("foreach_array_int_only", '''
@main
fn main() int {
    mut a := []int{}
    for i in 0:5 {
        a.push(i)
    }
    mut s := 0
    for x in a {
        s = s + x
    }
    println(s)
    << 0
}
''', "10\n", True),

("foreach_chan_int", '''
@main
fn sender(ch chan int) {
    ch <- 1
    ch <- 2
    ch <- 3
    close(ch)
}
fn main() int {
    ch := chan int{cap: 3}
    xu sender(ch)
    mut s := 0
    for x in ch {
        s = s + x
    }
    println(s)
    << 0
}
''', "6\n", False),

("foreach_nested_array_str", f'''
@main
fn main() int {{
    mut a := []string{{}}
    a.push("r0_"+ "{P}")
    a.push("r1_"+ "{P}")
    mut n := 0
    for s in a {{
        n = n + s.len
    }}
    println(n > 0)
    << 0
}}
''', "true\n", True),

("array_index_after_foreach", f'''
@main
fn main() int {{
    mut a := []string{{}}
    a.push("x_"+ "{P}")
    a.push("y_"+ "{P}")
    mut n := 0
    for s in a {{
        n = n + 1
    }}
    println(a[0])
    println(a[1])
    println(n)
    << 0
}}
''', "x_"+P+"\ny_"+P+"\n2\n", True),

("fixed_array_int_literal", '''
@main
fn main() int {
    a := [4]int{1, 2, 3, 4}
    println(a[0])
    println(a[3])
    << 0
}
''', "1\n4\n", True),

("fixed_array_str_literal", f'''
@main
fn main() int {{
    a := [2]string{{"aa_"+ "{P}", "bb_"+ "{P}"}}
    println(a[0])
    println(a[1])
    << 0
}}
''', "aa_"+P+"\nbb_"+P+"\n", True),
]


def parse(err):
    out = {}
    for k in ("live_bytes","allocs","frees","unknown_frees","double_frees"):
        m = re.search(rf"{k}=(\d+)", err)
        if m:
            out[k] = int(m.group(1))
    return out


def run_case(name, src, expect, balanced):
    td = Path(tempfile.mkdtemp(prefix=f"xuFE_{name}_"))
    (td/"main.xu").write_text(src.lstrip("\n"))
    out = td/"a.out"
    env = os.environ.copy()
    env["XUPATH"] = str(ROOT/"src")
    env["XU_GEN1_HEAP_LEDGER"] = "1"
    env["XU_HEAP_STATS"] = "1"
    try:
        p = subprocess.run([XU,"build",str(td/"main.xu"),"-o",str(out)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, timeout=25)
    except subprocess.TimeoutExpired:
        return name, False, "compile-timeout"
    if p.returncode != 0:
        return name, False, f"compile {(p.stderr.decode().splitlines() or [''])[0][:120]}"
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
    if expect is not None and got != expect:
        return name, False, f"stdout {got!r} want {expect!r}"
    st = parse(r.stderr.decode())
    if not st:
        return name, False, f"no-stats {r.stderr.decode()[:60]!r}"
    if st.get("unknown_frees",0) or st.get("double_frees",0):
        return name, False, f"bad-free {st}"
    if balanced and st.get("live_bytes",-1) != 0:
        return name, False, f"live!=0 {st}"
    if balanced and st.get("allocs") != st.get("frees"):
        return name, False, f"A!=F {st}"
    return name, True, f"ok {st}"


def main():
    print(f"foreach cases={len(CASES)} xu={XU}")
    res = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(run_case, *c) for c in CASES]
        for f in as_completed(futs):
            res.append(f.result())
    res.sort()
    ok = sum(1 for r in res if r[1])
    bad = [r for r in res if not r[1]]
    for n, good, d in res:
        print(f"{'PASS' if good else 'FAIL':4} {n:28} {d[:100]}")
    print("====")
    print(f"foreach_ledger pass={ok} fail={len(bad)} total={len(res)}")
    for n,_,d in bad:
        print(f"  {n}: {d[:140]}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
