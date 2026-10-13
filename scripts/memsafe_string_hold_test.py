#!/usr/bin/env python3
"""String hold / fresh-expr ledger battery (XU_GEN1_HEAP_LEDGER=1)."""
from __future__ import annotations
import os, re, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path('/Users/nouo/github/xu')
os.chdir(ROOT)
XU = '/tmp/xu_prod.xin'
P = 'padpadpadpad'

CASES = [
("println_concat", f'''
@main
fn main() int {{
    println("aa_"+ "{P}")
    << 0
}}
''', "aa_"+P+"\n", True),

("println_str_int", '''
@main
fn main() int {
    println(str(42))
    << 0
}
''', "42\n", True),

("println_local_borrow", f'''
@main
fn main() int {{
    s := "loc_"+ "{P}"
    println(s)
    println(s)
    << 0
}}
''', "loc_"+P+"\nloc_"+P+"\n", True),

("user_fn_concat_arg", f'''
@main
fn take(s string) int {{
    println(s)
    << s.len
}}
fn main() int {{
    n := take("arg_"+ "{P}")
    println(n)
    << 0
}}
''', "arg_"+P+"\n"+str(len("arg_"+P))+"\n", True),

("user_fn_two_concat", f'''
@main
fn cat(a string, b string) string {{
    << a + b
}}
fn main() int {{
    println(cat("x_"+ "{P}", "y_"+ "{P}"))
    << 0
}}
''', "x_"+P+"y_"+P+"\n", True),

("array_push_concat", f'''
@main
fn main() int {{
    mut a := []string{{}}
    for i in 0 -< 5 {{
        a.push("p"+str(i)+"_"+ "{P}")
    }}
    println(a.len)
    println(a[4])
    << 0
}}
''', "5\np4_"+P+"\n", True),

("chan_send_concat", f'''
@main
fn worker(ch chan string) {{
    ch <- "ch_"+ "{P}"
}}
fn main() int {{
    ch := chan string{{cap: 1}}
    xu worker(ch)
    s := <-ch
    println(s)
    << 0
}}
''', "ch_"+P+"\n", False),

("return_concat", f'''
@main
fn make() string {{
    << "ret_"+ "{P}"
}}
fn main() int {{
    println(make())
    << 0
}}
''', "ret_"+P+"\n", True),

("result_ok_string", '''
@main
#errors
fn may(ok bool) string {
    if ok {
        << "ok_val"
    }
    >> errors.new("err_val")
    << ""
}
fn main() int {
    r := may(true) or (e) {
        println(e.msg())
        << 0
    }
    println(r)
    e := may(false) or (err) {
        println(err.msg())
        << 0
    }
    println(e)
    << 0
}
''', "ok_val\nerr_val\n", True),

("foreach_array_concat_store", f'''
@main
fn main() int {{
    mut a := []string{{}}
    a.push("a0_"+ "{P}")
    a.push("a1_"+ "{P}")
    mut n := 0
    for s in a {{
        n = n + s.len
    }}
    println(n)
    << 0}}
''', None, False),

("field_assign_fn_concat", f'''
@main
struct U {{ s string }}
fn mk(i int) string {{
    << "m"+str(i)+"_"+ "{P}"
}}
fn main() int {{
    mut u := U{{s: mk(0)}}
    u.s = mk(1)
    println(u.s)
    << 0
}}
''', "m1_"+P+"\n", True),

("nested_call_args", f'''
@main
fn inner(s string) string {{
    << s + "!"
}}
fn outer(s string) string {{
    << inner(s)
}}
fn main() int {{
    println(outer("n_"+ "{P}"))
    << 0
}}
''', "n_"+P+"!\n", True),

("map_both_concat", f'''
@main
fn main() int {{
    mut m := map[string]string{{}}
    for i in 0 -< 6 {{
        m["k"+str(i)] = "v"+str(i)+"_"+ "{P}"
    }}
    m["k3"] = "replaced_"+ "{P}"
    println(m["k3"])
    println(m.len())
    << 0
}}
''', "replaced_"+P+"\n6\n", True),

("string_rebind_loop", f'''
@main
fn main() int {{
    mut s := "s0_"+ "{P}"
    for i in 0 -< 8 {{
        s = "s"+str(i)+"_"+ "{P}"
    }}
    println(s)
    << 0
}}
''', "s7_"+P+"\n", True),

("eprintln_concat", f'''
@main
fn main() int {{
    eprintln("ee_"+ "{P}")
    << 0
}}
''', None, False),

("map_foreach_strings", f'''
@main
fn main() int {{
    mut m := map[string]string{{}}
    for i in 0 -< 3 {{
        m["k"+str(i)] = "v"+str(i)+"_"+ "{P}"
    }}
    mut n := 0
    for k, v in m {{
        n = n + k.len + v.len
    }}
    println(n > 0)
    << 0
}}
''', "true\n", True),

("map_foreach_intkey", f'''
@main
fn main() int {{
    mut m := map[int]string{{}}
    m[1] = "one_"+ "{P}"
    m[2] = "two_"+ "{P}"
    mut n := 0
    for k, v in m {{
        n = n + k + v.len
    }}
    println(n > 0)
    << 0
}}
''', "true\n", True),
]


def parse_stats(err: str) -> dict:
    out = {}
    for key in ("live_bytes", "allocs", "frees", "unknown_frees", "double_frees"):
        m = re.search(rf"{key}=(\d+)", err)
        if m:
            out[key] = int(m.group(1))
    return out


def run_case(name, src, expect, balanced):
    td = Path(tempfile.mkdtemp(prefix=f"xuSH_{name}_"))
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
    st = parse_stats(r.stderr.decode())
    if not st:
        return name, False, f"no-stats {r.stderr.decode()[:60]!r}"
    if st.get("unknown_frees", 0) != 0:
        return name, False, f"unknown_frees {st}"
    if st.get("double_frees", 0) != 0:
        return name, False, f"double_frees {st}"
    if balanced and st.get("live_bytes", -1) != 0:
        return name, False, f"live!=0 {st}"
    if balanced and st.get("allocs") != st.get("frees"):
        return name, False, f"A!=F {st}"
    return name, True, f"ok {st}"


def main():
    print(f"string-hold cases={len(CASES)}")
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(run_case, *c) for c in CASES]
        for f in as_completed(futs):
            results.append(f.result())
    results.sort()
    ok = sum(1 for r in results if r[1])
    bad = [r for r in results if not r[1]]
    for n, good, d in results:
        print(f"{'PASS' if good else 'FAIL':4} {n:28} {d[:110]}")
    print("====")
    print(f"string_hold pass={ok} fail={len(bad)} total={len(results)}")
    for n, _, d in bad:
        print(f"  {n}: {d[:140]}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
