#!/usr/bin/env python3
"""Multi-error checker / borrow recovery and adversarial diagnostic safety tests.

Usage: python3 scripts/test_checker_multi_error.py --compiler bin/xu.exe
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ERROR_LINE_RE = re.compile(r"(?:^|\n)[^\n]*?:\d+:\d+:\s*error:\s+", re.MULTILINE)
CRASH_MARKERS = ("panic", "out of bounds", "index out of", "SIGSEGV", "Segmentation fault", "fatal error", "assertion failed")


def resolve_compiler(cli_val: str | None) -> Path:
    if cli_val:
        p = Path(cli_val)
    elif os.environ.get("XU"):
        p = Path(os.environ["XU"])
    else:
        default_name = "xu.exe" if sys.platform.startswith("win") else "xu"
        p = ROOT / "bin" / default_name
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    if not p.exists():
        raise SystemExit(f"missing xu compiler: {p}")
    return p


def run_xu(compiler: Path, args: list[str], cwd: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env["XU_ROOT"] = str(ROOT)
    env["XUPATH"] = str(ROOT / "src")
    env["XU_STDLIB_ROOT"] = str(ROOT / "src")
    res = subprocess.run(
        [str(compiler), *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    out = (res.stdout + "\n" + res.stderr).replace("\r\n", "\n")
    return res.returncode, out


def count_errors(out: str) -> int:
    return len(ERROR_LINE_RE.findall(out))


def assert_no_crash(name: str, out: str) -> None:
    low = out.lower()
    for m in CRASH_MARKERS:
        if m.lower() in low:
            raise AssertionError(f"[{name}] unexpected crash/panic marker {m!r} in output:\n{out}")


def test_5fn_type_errors(compiler: Path, td: Path) -> None:
    src = """@main
fn f1() int { << "bad" }
fn f2() bool { << 42 }
fn f3() { x := 1 + "a" }
fn f4() { y := unknown_sym_4 }
fn f5(a int) int { << true }
fn main() int { << 0 }
"""
    p = td / "five_type.xu"
    p.write_text(src, encoding="utf-8")

    rc_chk, out_chk = run_xu(compiler, ["check", str(p)], td)
    assert_no_crash("5fn_check", out_chk)
    assert rc_chk == 1, f"[5fn_check] expected rc=1, got {rc_chk}\n{out_chk}"
    n_chk = count_errors(out_chk)
    assert n_chk == 5, f"[5fn_check] expected 5 error diagnostics, got {n_chk}:\n{out_chk}"

    out_bin = td / ("five_type.exe" if sys.platform.startswith("win") else "five_type.out")
    rc_bld, out_bld = run_xu(compiler, ["build", str(p), "-o", str(out_bin)], td)
    assert_no_crash("5fn_build", out_bld)
    assert rc_bld == 1, f"[5fn_build] expected rc=1, got {rc_bld}\n{out_bld}"
    n_bld = count_errors(out_bld)
    assert n_bld == 5, f"[5fn_build] expected 5 error diagnostics, got {n_bld}:\n{out_bld}"
    assert not out_bin.exists(), f"[5fn_build] binary should not be produced on error"


def test_3fn_borrow_errors(compiler: Path, td: Path) -> None:
    src = """@main
fn sink(s string) int { << s.len }
fn take_mut(x $&int) int { << *x }
fn take_sh(x &int, y $&int) int { << *x + *y }

fn b1() int {
    s := "abc" + "def"
    _ := sink(s)
    << s.len
}

fn b2() int {
    $x := 10
    a := $&x
    b := $&x
    << *a + *b
}

fn b3() int {
    $x := 10
    a := &x
    << take_sh(a, $&x)
}

fn main() int { << 0 }
"""
    p = td / "three_borrow.xu"
    p.write_text(src, encoding="utf-8")
    rc, out = run_xu(compiler, ["check", str(p)], td)
    assert_no_crash("3fn_borrow", out)
    assert rc == 1, f"[3fn_borrow] expected rc=1, got {rc}\n{out}"
    n = count_errors(out)
    assert n == 3, f"[3fn_borrow] expected 3 borrow errors across b1/b2/b3, got {n}:\n{out}"


def test_mixed_type_and_borrow(compiler: Path, td: Path) -> None:
    src = """@main
fn sink(s string) int { << s.len }

fn t1() int { << "nope" }

fn b1() int {
    s := "hi" + "!"
    _ := sink(s)
    << s.len
}

fn t2() { x := 1 + "two" }

fn b2() int {
    $x := 1
    p := $&x
    q := $&x
    << *p + *q
}

fn main() int { << 0 }
"""
    p = td / "mixed_type_borrow.xu"
    p.write_text(src, encoding="utf-8")
    rc, out = run_xu(compiler, ["check", str(p)], td)
    assert_no_crash("mixed", out)
    assert rc == 1, f"[mixed] expected rc=1, got {rc}\n{out}"
    n = count_errors(out)
    assert n == 4, f"[mixed] expected 4 errors (t1, b1, t2, b2), got {n}:\n{out}"


def test_multi_decl_errors(compiler: Path, td: Path) -> None:
    src = """@main
const C1 = "a"
const C1 = "b"

struct S1 { a NoSuchTypeA }
struct S1 { x int }

enum E1 { A(NoSuchTypeB) }
enum E1 { B }

fn dup_fn() int { << 1 }
fn dup_fn() int { << 2 }

fn main() int { << 0 }
"""
    p = td / "multi_decl.xu"
    p.write_text(src, encoding="utf-8")
    rc, out = run_xu(compiler, ["check", str(p)], td)
    assert_no_crash("multi_decl", out)
    assert rc == 1, f"[multi_decl] expected rc=1, got {rc}\n{out}"
    n = count_errors(out)
    assert n >= 4, f"[multi_decl] expected >= 4 decl errors, got {n}:\n{out}"


def test_zero_intra_fn_cascade(compiler: Path, td: Path) -> None:
    src = """@main
fn no_cascade() int {
    a := missing_var + 1
    b := a + missing_var
    c := b * 2
    println(missing_var)
    println(c)
    << a + c
}
fn main() int { << 0 }
"""
    p = td / "no_cascade.xu"
    p.write_text(src, encoding="utf-8")
    rc, out = run_xu(compiler, ["check", str(p)], td)
    assert_no_crash("no_cascade", out)
    assert rc == 1, f"[no_cascade] expected rc=1, got {rc}\n{out}"
    n = count_errors(out)
    assert n == 1, f"[no_cascade] expected exactly 1 error (no cascade), got {n}:\n{out}"

    src2 = """@main
struct Pt { x int }
enum Color { Red, Blue }

fn init_err() Pt { << Pt { bogus: 1 } }
fn match_err(c Color) int {
    match c {
        Color.Missing { << 1 }
    }
    << 0
}
fn main() int { << 0 }
"""
    p2 = td / "no_cascade_struct_enum.xu"
    p2.write_text(src2, encoding="utf-8")
    rc2, out2 = run_xu(compiler, ["check", str(p2)], td)
    assert_no_crash("no_cascade_struct_enum", out2)
    assert rc2 == 1, f"[no_cascade_struct_enum] expected rc=1, got {rc2}\n{out2}"
    n2 = count_errors(out2)
    assert n2 == 2, f"[no_cascade_struct_enum] expected 2 errors (1 per fn), got {n2}:\n{out2}"


def test_error_cap_25(compiler: Path, td: Path) -> None:
    lines_25 = ["@main"] + [f'fn bad_{i}() int {{ << "err" }}' for i in range(25)] + ["fn main() int { << 0 }"]
    p25 = td / "cap_25.xu"
    p25.write_text("\n".join(lines_25) + "\n", encoding="utf-8")
    rc25, out25 = run_xu(compiler, ["check", str(p25)], td)
    assert_no_crash("cap_25", out25)
    assert rc25 == 1, f"[cap_25] expected rc=1, got {rc25}\n{out25}"
    assert count_errors(out25) == 25, f"[cap_25] expected 25 errors, got {count_errors(out25)}:\n{out25}"
    assert "too many errors (stopping after 25)" not in out25, f"[cap_25] cap msg should NOT appear at 25:\n{out25}"

    lines_35 = ["@main"] + [f'fn bad_{i}() int {{ << "err" }}' for i in range(35)] + ["fn main() int { << 0 }"]
    p35 = td / "cap_35.xu"
    p35.write_text("\n".join(lines_35) + "\n", encoding="utf-8")
    rc35, out35 = run_xu(compiler, ["check", str(p35)], td)
    assert_no_crash("cap_35", out35)
    assert rc35 == 1, f"[cap_35] expected rc=1, got {rc35}\n{out35}"
    assert count_errors(out35) == 25, f"[cap_35] expected 25 errors before cap, got {count_errors(out35)}:\n{out35}"
    assert "too many errors (stopping after 25)" in out35, f"[cap_35] expected cap message:\n{out35}"


ADVERSARIAL_CASES: list[tuple[str, str]] = [
    ("println_0", "fn main() int { println()\n << 0 }"),
    ("env_get_0", "fn main() int { _ := env_get()\n << 0 }"),
    ("os_exec_0", "fn main() int { _ := os_exec()\n << 0 }"),
    ("atomic_load_0", "fn main() int { _ := atomic_load()\n << 0 }"),
    ("atomic_cas_0", "fn main() int { _ := atomic_cas()\n << 0 }"),
    ("sys_bind4_0", "fn main() int { _ := sys_bind4()\n << 0 }"),
    ("sys_socket_read_0", "fn main() int { _ := sys_socket_read()\n << 0 }"),
    ("volatile_write_0", "fn main() int { volatile_write()\n << 0 }"),
    ("read_file_0", "fn main() int { _ := read_file()\n << 0 }"),
    ("write_file_0", "fn main() int { _ := write_file()\n << 0 }"),
    ("assert_0", "fn main() int { assert()\n << 0 }"),
    ("close_0", "fn main() int { close()\n << 0 }"),
    ("starts_with_0", "fn main() int { _ := starts_with()\n << 0 }"),
    ("make_ints_0", "fn main() int { _ := make_ints()\n << 0 }"),
    ("string_from_bytes_0", "fn main() int { _ := string_from_bytes()\n << 0 }"),
    ("arr_push_0", "fn main() int { $a := [1]\n a.push()\n << 0 }"),
    ("arr_push4_0", "fn main() int { $a := [1]\n a.push4()\n << 0 }"),
    ("str_push_str_0", 'fn main() int { $s := "hi"\n s.push_str()\n << 0 }'),
    ("map_get_or_0", 'fn main() int { m := map[string]int{}\n _ := m.get_or()\n << 0 }'),
    ("deref_int", "fn main() int { _ := *123\n << 0 }"),
    ("borrow_mut_lit", "fn main() int { _ := $&123\n << 0 }"),
    ("index_int", "fn main() int { _ := 123[0]\n << 0 }"),
    ("field_int", "fn main() int { _ := 123.foo\n << 0 }"),
    ("empty_array_lit", "fn main() int { _ := []\n << 0 }"),
    ("recv_int", "fn main() int { _ := <-123\n << 0 }"),
    ("send_int", "fn main() int { 1 <- 2\n << 0 }"),
    ("select_send_bad", "fn main() int { select { 1 <- 2 {} }\n << 0 }"),
    ("select_recv_bad", "fn main() int { select { v := <- 1 { _ := v } }\n << 0 }"),
    ("for_in_int", "fn main() int { for x in 1 {}\n << 0 }"),
    ("for_kv_arr", "fn main() int { for k, v in [1] {}\n << 0 }"),
    ("xu_missing", "fn main() int { xu missing()\n << 0 }"),
    ("exit_bad", 'fn main() int { <<< "bad"\n << 0 }'),
    ("throw_outside", "fn main() int { >> 1\n << 0 }"),
    ("throw_triple_outside", "fn main() int { >>> 1\n << 0 }"),
    ("bad_str_match", 'fn main() int {\n    match "a" {\n        1 {}\n    }\n    << 0\n}'),
    ("bad_enum_match_dup_else", "enum E { A, B }\nfn main() int {\n    e := E.A\n    match e {\n        else {}\n        else {}\n    }\n    << 0\n}"),
    ("bad_struct_init", "struct S { x int }\nfn main() int { _ := S { bogus: 1 }\n << 0 }"),
    ("bad_cast_str", "fn main() int { _ := 1 as string\n << 0 }"),
    ("bad_is_int", "fn main() int { _ := 1 is int\n << 0 }"),
    ("bad_closure_ret", "fn main() int {\n    f := fn(x int) int { _ := x }\n    _ := f(1)\n    << 0\n}"),
    ("bad_map_cap", 'fn main() int { _ := map[int]string{ cap: "bad" }\n << 0 }'),
    ("bad_map_assign", 'fn main() int { $m := map[int]string{}\n m["k"] = 1\n << 0 }'),
    ("bad_assign_deref", "fn main() int { *1 = 2\n << 0 }"),
    ("bad_extra_args", "fn f(x int) int { << x }\nfn main() int { _ := f(1, 2, 3)\n << 0 }"),
]


def test_adversarial_cases(compiler: Path, td: Path) -> None:
    adv_dir = td / "adv"
    adv_dir.mkdir(exist_ok=True)
    for name, body in ADVERSARIAL_CASES:
        p = adv_dir / f"{name}.xu"
        p.write_text(f"@main\n{body}\n", encoding="utf-8")
        rc, out = run_xu(compiler, ["check", str(p)], adv_dir)
        assert_no_crash(f"adv:{name}", out)
        assert rc == 1, f"[adv:{name}] expected rc=1, got {rc}\n{out}"
        n = count_errors(out)
        assert n >= 1, f"[adv:{name}] expected >= 1 formatted error diagnostic, got {n}:\n{out}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compiler", "--xu", dest="compiler", default=None)
    args = ap.parse_args()
    compiler = resolve_compiler(args.compiler)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw_td:
        td = Path(raw_td)
        test_5fn_type_errors(compiler, td)
        print("OK: 5fn_type_errors (check + build)")
        test_3fn_borrow_errors(compiler, td)
        print("OK: 3fn_borrow_errors")
        test_mixed_type_and_borrow(compiler, td)
        print("OK: mixed_type_and_borrow")
        test_multi_decl_errors(compiler, td)
        print("OK: multi_decl_errors")
        test_zero_intra_fn_cascade(compiler, td)
        print("OK: zero_intra_fn_cascade")
        test_error_cap_25(compiler, td)
        print("OK: error_cap_25")
        test_adversarial_cases(compiler, td)
        print(f"OK: adversarial_cases ({len(ADVERSARIAL_CASES)} cases)")

    print("checker multi-error recovery: ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
