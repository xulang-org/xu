#!/usr/bin/env python3
"""Self-contained regression gate for Xu memory-safety and zero-GC lowering.

Covers compile-time borrow/move/unsafe/Send rejections and runtime bounds,
overflow, optimizer aliasing, drop-flag, and RC/COW invariants.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent


def default_xu_path() -> Path:
    exe = "xu.exe" if platform.system().lower().startswith("win") else "xu"
    return REPO_ROOT / "bin" / exe


@dataclass(frozen=True)
class NegCase:
    name: str
    code: str
    expect_substrings: tuple[str, ...]


@dataclass(frozen=True)
class PosCase:
    name: str
    code: str
    expect_stdout: Optional[str] = None
    expect_stdout_lines: tuple[str, ...] = ()
    expect_trap: bool = False
    expect_trap_substrings: tuple[str, ...] = ()
    test_no_opt: bool = False
    debug_free: bool = True


SYNTAX_NOISE = (
    "unexpected character",
    "unexpected token",
    "expected ",
    "undefined name",
    "unknown type",
    "unknown compile tag",
)


NEG_CASES: list[NegCase] = [
    NegCase(
        name="C1_closure_double_mut_capture",
        code="""@main
fn take_two(f fn() int, g fn() int) int {
    << f() + g()
}
fn main() {
    $x := 1
    r1 := $&x
    f := fn() int {
        *r1 += 1
        << *r1
    }
    g := fn() int {
        *r1 += 2
        << *r1
    }
    println(take_two(f, g))
}
""",
        expect_substrings=("borrow", "moved", "cannot"),
    ),
    NegCase(
        name="C1_if_local_ref_escape",
        code="""@main
fn bad(cond bool) int {
    $a := 10
    $r := &a
    if cond {
        $local := 20
        r = &local
    }
    << *r
}
fn main() { println(bad(true)) }
""",
        expect_substrings=("live long enough", "outlive", "reference"),
    ),
    NegCase(
        name="C1_move_while_borrowed",
        code="""@main
struct Own {
    v int
}
fn (o $&Own) drop() { println("drop") }
fn consume(o Own) {
    println(o.v)
}
fn main() {
    o := Own{v: 7}
    r := &o
    consume(o)
    println(r.v)
}
""",
        expect_substrings=("borrow", "cannot move"),
    ),
    NegCase(
        name="C1_ambiguous_ref_params",
        code="""@main
fn pick(a &int, b &int) &int {
    if *a > *b { << a }
    << b
}
fn main() {
    x := 1
    y := 2
    println(*pick(&x, &y))
}
""",
        expect_substrings=("lifetime", "reference"),
    ),
    NegCase(
        name="C1_local_ref_return",
        code="""@main
fn bad() &int {
    x := 42
    << &x
}
fn main() { println(*bad()) }
""",
        expect_substrings=("cannot return", "local", "reference"),
    ),
    NegCase(
        name="C1_closure_env_local_ref_return",
        code="""@main
fn main() {
    f := fn() &int {
        x := 99
        << &x
    }
    println(*f())
}
""",
        expect_substrings=("cannot return", "local", "reference"),
    ),
    NegCase(
        name="C2_unsafe_fn_value",
        code="""@main
unsafe fn danger() int {
    << 1
}
fn main() {
    f := danger
    println(f())
}
""",
        expect_substrings=("unsafe",),
    ),
    NegCase(
        name="C2_unsafe_method_value",
        code="""@main
struct Boxed {
    v int
}
unsafe fn (b &Boxed) danger() int {
    << b.v
}
fn main() {
    b := Boxed{v: 3}
    f := b.danger
    println(f())
}
""",
        expect_substrings=("unsafe",),
    ),
    NegCase(
        name="C2_xu_spawn_unsafe_fn",
        code="""@main
unsafe fn bg() {
    println("bg")
}
fn main() {
    xu bg()
}
""",
        expect_substrings=("unsafe",),
    ),
    NegCase(
        name="C2_generic_unsafe_call",
        code="""@main
unsafe fn g#T(x T) T {
    << x
}
fn main() {
    println(g(5))
}
""",
        expect_substrings=("unsafe",),
    ),
    NegCase(
        name="C2_unsafe_method_call",
        code="""@main
struct S { v int }
unsafe fn (s &S) read_v() int { << s.v }
fn main() {
    s := S{v: 1}
    println(s.read_v())
}
""",
        expect_substrings=("unsafe",),
    ),
    NegCase(
        name="C2_c_callback_unsafe_fn",
        code="""@main
unsafe fn cb(x int) int {
    << x + 1
}
fn main() {
    p := c_callback(cb)
    println(p)
}
""",
        expect_substrings=("unsafe", "c_callback"),
    ),
    NegCase(
        name="C3_or_fallback_shadow",
        code="""@main
#errors
fn fallible(fail bool) int {
    if fail { >> errors.new("boom") }
    << 10
}
fn main() {
    $x := 1
    x = fallible(true) or (e) {
        x := 99
        << x
    }
    println(x)
}
""",
        expect_substrings=("shadow", "or"),
    ),
    NegCase(
        name="C3_or_target_mismatch",
        code="""@main
#errors
fn fallible() int {
    >> errors.new("boom")
    << 0
}
fn main() {
    x := fallible() or (e) {
        << "bad"
    }
    println(x)
}
""",
        expect_substrings=("mismatch", "cannot", "return", "void"),
    ),
    NegCase(
        name="H2_bound_method_move_owner",
        code="""@main
struct Own {
    v int
}
fn (o $&Own) drop() {}
fn (o &Own) get() int { << o.v }
fn take(o Own) { println(o.v) }
fn main() {
    o := Own{v: 5}
    f := o.get
    take(o)
    println(f())
}
""",
        expect_substrings=("borrow", "moved", "cannot"),
    ),
    NegCase(
        name="H3_struct_mut_ref_noncopy",
        code="""@main
struct Wrap {
    r $&int
}
fn use_w(w Wrap) { *w.r += 1 }
fn main() {
    $x := 1
    w := Wrap{r: $&x}
    use_w(w)
    use_w(w)
}
""",
        expect_substrings=("moved", "use of moved"),
    ),
    NegCase(
        name="H3_array_mut_ref_index_copy",
        code="""@main
fn main() {
    $x := 1
    arr := [1]$&int{ $&x }
    a := arr[0]
    b := arr[0]
    *a += 1
    *b += 1
}
""",
        expect_substrings=("cannot move", "cannot copy", "borrow", "$&"),
    ),
    NegCase(
        name="H4_for_in_string_slice_mutate",
        code="""@main
fn main() {
    $xs := ["a", "b"]
    for s in xs {
        xs.push("c")
        println(s)
    }
}
""",
        expect_substrings=("borrow", "cannot mutate", "immutable", "moved"),
    ),
    NegCase(
        name="H5_match_binding_ref_escape",
        code="""@main
enum E {
    A(int)
    B
}
fn main() {
    seed := 1
    $out := &seed
    e := E.A(7)
    match e {
        E.A(v) {
            out = &v
        }
        E.B {}
    }
    println(*out)
}
""",
        expect_substrings=("outlive", "control-flow arm", "reference"),
    ),
    NegCase(
        name="H5_select_recv_ref_escape",
        code="""@main
fn main() {
    ch := chan int{cap: 1}
    ch <- 7
    seed := 1
    $out := &seed
    select {
        v := <-ch {
            out = &v
        }
    }
    println(*out)
}
""",
        expect_substrings=("outlive", "control-flow arm", "reference"),
    ),
    NegCase(
        name="H6_lrefok_after_vec_push",
        code="""@main
fn bad() &int {
    $xs := []&int{}
    local := 12
    xs.push(&local)
    << xs[0]
}
fn main() { println(*bad()) }
""",
        expect_substrings=("local", "lifetime", "reference"),
    ),
    NegCase(
        name="H6_lrefok_after_vec_index_assign",
        code="""@main
fn bad(seed &int) &int {
    $xs := [seed]
    local := 12
    xs[0] = &local
    << xs[0]
}
fn main() {
    s := 1
    println(*bad(&s))
}
""",
        expect_substrings=("local", "lifetime", "reference"),
    ),
    NegCase(
        name="H6_lrefok_after_field_assign",
        code="""@main
struct Holder {
    r &int
}
fn bad(seed &int) &int {
    $h := Holder{r: seed}
    local := 12
    h.r = &local
    << h.r
}
fn main() {
    s := 1
    println(*bad(&s))
}
""",
        expect_substrings=("local", "lifetime", "reference"),
    ),
    NegCase(
        name="H7_nested_ref_field_write",
        code="""@main
struct Inner {
    p &int
}
struct Outer {
    r $&Inner
}
fn main() {
    $seed := 1
    $inn := Inner{p: &seed}
    outer := Outer{r: $&inn}
    if true {
        local := 9
        outer.r.p = &local
    }
    println(*inn.p)
}
""",
        expect_substrings=("cannot store a reference-bearing value through a reference",),
    ),
    NegCase(
        name="H8_transitive_borrow_alias",
        code="""@main
struct Hold {
    v int
}
fn bump(h $&Hold) { h.v += 1 }
fn main() {
    $h := Hold{v: 1}
    p := &h
    bump($&h)
    println(p.v)
}
""",
        expect_substrings=("borrow", "cannot"),
    ),
    NegCase(
        name="H9_self_alias_mut_method",
        code="""@main
struct Buf {
    xs []int
}
fn (b $&Buf) bad(p &int) {
    b.xs.push(*p + 1)
}
fn main() {
    $b := Buf{xs: [10]}
    b.bad(&b.xs[0])
    println(b.xs.len)
}
""",
        expect_substrings=("borrow", "cannot"),
    ),
    NegCase(
        name="H9_fnval_arg_move",
        code="""@main
struct Own { v int }
fn (o $&Own) drop() {}
fn take(o Own) { println(o.v) }
fn main() {
    o := Own{v: 3}
    f := take
    f(o)
    take(o)
}
""",
        expect_substrings=("moved", "use of moved"),
    ),
    NegCase(
        name="H9_throwing_arg_move",
        code="""@main
#errors
struct Own { v int }
fn (o $&Own) drop() {}
fn maybe_take(o Own) int {
    if o.v < 0 { >> errors.new("neg") }
    << o.v
}
fn run() int {
    o := Own{v: 4}
    r := maybe_take(o) or (e) { << 0 }
    println(o.v + r)
    << r
}
fn main() { println(run()) }
""",
        expect_substrings=("moved", "use of moved"),
    ),
    NegCase(
        name="H9_iface_method_arg_move",
        code="""@main
struct Own { v int }
fn (o $&Own) drop() {}
struct@ Consumer {
    fn consume(Own)
}
struct Impl {}
fn (i Impl) consume(o Own) { println(o.v) }
fn run_it(c Consumer) {
    o := Own{v: 8}
    c.consume(o)
    println(o.v)
}
fn main() {
    run_it(Impl{})
}
""",
        expect_substrings=("moved", "use of moved"),
    ),
    NegCase(
        name="H10_continue_after_move_map",
        code="""@main
fn eat(m map[string]int) { println(m.len) }
fn main() {
    $m := map[string]int{}
    m["a"] = 1
    for i in 0:2 {
        if i == 0 {
            eat(m)
            continue
        }
        println(m.len)
    }
}
""",
        expect_substrings=("moved", "use of moved"),
    ),
    NegCase(
        name="H10_continue_after_move_enum",
        code="""@main
struct Own { v int }
fn (o $&Own) drop() {}
enum BoxE {
    Has(Own)
    Empty
}
fn eat(b BoxE) {}
fn main() {
    b := BoxE.Has(Own{v: 1})
    for i in 0:2 {
        if i == 0 {
            eat(b)
            continue
        }
        eat(b)
    }
}
""",
        expect_substrings=("moved", "use of moved"),
    ),
    NegCase(
        name="H10_continue_after_move_closure",
        code="""@main
struct Own { v int }
fn (o $&Own) drop() {}
fn eat_fn(f fn() int) { println(f()) }
fn main() {
    o := Own{v: 5}
    f := fn() int { << o.v }
    for i in 0:2 {
        if i == 0 {
            eat_fn(f)
            continue
        }
        eat_fn(f)
    }
}
""",
        expect_substrings=("moved", "use of moved"),
    ),
    NegCase(
        name="H10_continue_after_move_mutref",
        code="""@main
fn eat_r(r $&int) { *r += 1 }
fn main() {
    $x := 1
    r := $&x
    for i in 0:2 {
        if i == 0 {
            eat_r(r)
            continue
        }
        eat_r(r)
    }
}
""",
        expect_substrings=("moved", "use of moved"),
    ),
    NegCase(
        name="H11_or_fallback_does_not_revive_moved",
        code="""@main
#errors
struct Own { v int }
fn (o $&Own) drop() {}
fn take(o Own) { println(o.v) }
fn fallible() int {
    if false { >> errors.new("x") }
    << 1
}
fn run() int {
    o := Own{v: 9}
    take(o)
    _ := fallible() or (e) {
        println(0)
        << 0
    }
    take(o)
    << 1
}
fn main() { println(run()) }
""",
        expect_substrings=("moved", "use of moved"),
    ),
    NegCase(
        name="ValueRecv_move_in_body",
        code="""@main
struct Own { v int }
fn (o $&Own) drop() {}
fn consume(o Own) { println(o.v) }
fn (w Own) bad_m() {
    consume(w)
}
fn main() {
    w := Own{v: 1}
    w.bad_m()
}
""",
        expect_substrings=("cannot move", "borrow"),
    ),
    NegCase(
        name="Send_struct_with_temp",
        code="""@main
struct Wrap {
    t temp
}
fn worker(w Wrap) {
    println(w.t is int)
}
fn main() {
    let x: temp = 1
    w := Wrap{t: x}
    xu worker(w)
}
""",
        expect_substrings=("reference", "M17", "Send"),
    ),
    NegCase(
        name="PushByte_while_borrowed",
        code="""@main
fn main() {
    $s := "abc"
    r := &s
    s.push_byte(65)
    println(*r)
}
""",
        expect_substrings=("borrow", "cannot"),
    ),
    NegCase(
        name="CPtr_deref_outside_unsafe",
        code="""@main
fn bad(p c_ptr) int {
    << *p
}
fn main() {}
""",
        expect_substrings=("unsafe", "cannot dereference", "c_ptr"),
    ),
    NegCase(
        name="H1_fixed_array_resource_owner_rejected",
        code="""@main
struct Guard { id int }
fn (g $&Guard) drop() {}
fn main() {
    a := [2]Guard{Guard{id: 1}, Guard{id: 2}}
    println(a.len)
}
""",
        expect_substrings=("fixed arrays containing resource owners are not supported",),
    ),
    NegCase(
        name="Select_send_owning_non_string_rejected",
        code="""@main
struct Guard { id int }
fn (g $&Guard) drop() {}
fn mk_guard(id int) Guard { << Guard{id: id} }
fn main() {
    full := chan Guard{cap: 0}
    select {
        full <- mk_guard(1) {
            println("sent")
        }
    }
}
""",
        expect_substrings=("select send of owning non-string is not supported",),
    ),
    NegCase(
        name="IfCond_nonstring_move_propagates_across_arms",
        code="""@main
struct Guard { id int }
fn (g $&Guard) drop() {}
fn eat_guard(g Guard) bool { << g.id > 0 }
fn main() {
    g := Guard{id: 1}
    if eat_guard(g) { << }
    println(g.id)
}
""",
        expect_substrings=("moved", "use of moved"),
    ),
]


POS_CASES: list[PosCase] = [
    PosCase(
        name="C4_loop_signed_overflow_oob",
        code="""@main
fn main() {
    xs := [10, 20, 30]
    $i := 1
    $sum := 0
    for k in 0:3 {
        sum += xs[i]
        i += 9223372036854775807
        if k > 10 { <- }
    }
    println(sum)
}
""",
        expect_trap=True,
        expect_trap_substrings=("index out of bounds",),
        test_no_opt=True,
        debug_free=False,
    ),
    PosCase(
        name="C4_emit_vec_fast_lo_gt_hi",
        code="""@main
fn sum_range(lo int, hi int) int {
    $acc := 0
    for i in lo:hi {
        acc += i
    }
    << acc
}
fn main() {
    println(sum_range(10, 2))
}
""",
        expect_stdout="0\n",
        test_no_opt=True,
    ),
    PosCase(
        name="C5_make_string_huge_trap",
        code="""@main
fn get_n() int { << 9223372036854775807 }
fn main() {
    s := make_string(get_n())
    println(s.len)
}
""",
        expect_trap=True,
        expect_trap_substrings=("make_string", "invalid", "out of memory"),
        debug_free=False,
    ),
    PosCase(
        name="C5_chan_huge_cap_trap",
        code="""@main
fn get_cap() int { << 2305843009213693954 }
fn main() {
    ch := chan int{cap: get_cap()}
    ch <- 1
    println(<-ch)
}
""",
        expect_trap=True,
        expect_trap_substrings=("chan", "overflow", "out of memory", "invalid", "alloc"),
        debug_free=False,
    ),
    PosCase(
        name="C5_sys_random_fill_neg_and_zero",
        code="""@main
#errors
fn test_neg() int {
    b := sys_random_fill(-1) or (e) {
        println("neg_err")
        << 1
    }
    println(b.len)
    << 0
}
fn test_zero() string {
    z := sys_random_fill(0) or (e) {
        println("unexpected_zero_err")
        << ""
    }
    << z
}
fn main() {
    _ := test_neg()
    z := test_zero()
    println(z.len)
}
""",
        expect_stdout="neg_err\n0\n",
    ),
    PosCase(
        name="Opt_gvn_licm_ref_store_aliasing",
        code="""@main
fn mutate(p $&int, v int) {
    *p = v
}
fn run_loop() int {
    $x := 10
    $sum := 0
    for i in 0:5 {
        a := x
        mutate($&x, 20 + i)
        b := x
        sum += a + b
    }
    << sum
}
fn main() {
    println(run_loop())
}
""",
        expect_stdout="206\n",
        test_no_opt=True,
    ),
    PosCase(
        name="H1_fixed_array_owning_drop_and_clone",
        code="""@main
struct BoxStr {
    text string
}
fn test_box_arr() {
    a := [2]BoxStr{BoxStr{text: "one_padpad"}, BoxStr{text: "two_padpad"}}
    b := ~a
    println("len:" + str(a.len) + ":" + b[0].text + ":" + b[1].text)
}
fn test_str_arr() {
    $s := [2]string{"alpha_pad", "beta_pad"}
    t := ~s
    s[0] = "gamma_pad"
    println(t[0] + ":" + s[0])
}
fn main() {
    test_box_arr()
    test_str_arr()
}
""",
        expect_stdout_lines=(
            "len:2:one_padpad:two_padpad",
            "alpha_pad:gamma_pad",
        ),
    ),
    PosCase(
        name="H12_expr_stmt_discard_owning",
        code="""@main
struct@ Greet {
    fn hi() int
}
struct Impl { v int }
fn (i Impl) hi() int { << i.v }
fn mk_chan() chan int { << chan int{cap: 1} }
fn mk_map() map[string]int {
    $m := map[string]int{}
    m["k"] = 1
    << m
}
fn mk_iface() Greet { << Impl{v: 7} }
fn main() {
    for i in 0:50 {
        mk_chan()
        mk_map()
        mk_iface()
    }
    println("ok")
}
""",
        expect_stdout="ok\n",
    ),
    PosCase(
        name="H13_index_assign_alias_grow",
        code="""@main
struct Guard { id int }
fn (g $&Guard) drop() { println("drop:" + str(g.id)) }
fn grow(xs $&[]Guard) Guard {
    for i in 0:8 {
        xs.push(Guard{id: 100 + i})
    }
    << Guard{id: 99}
}
fn run() {
    $xs := [Guard{id: 1}]
    xs[0] = grow($&xs)
    println("len:" + str(xs.len))
    println("first:" + str(xs[0].id))
}
fn main() {
    run()
}
""",
        expect_stdout_lines=(
            "drop:1",
            "len:9",
            "first:99",
            "drop:99",
            "drop:107",
        ),
    ),
    PosCase(
        name="H14_string_cow_byte_write",
        code="""@main
fn main() {
    $s := "hello"
    s[0] = 72
    println("hello:" + s)
}
""",
        expect_stdout="hello:Hello\n",
    ),
    PosCase(
        name="Split_short_string_copy_survives_element_and_array_drop",
        code="""@main
#strings

fn copy_and_replace(src &string) string {
    $parts := strings.split(src, "|")
    $piece := parts[1]
    parts[1] = "replacement"
    piece[0] = 90
    << piece
}

fn copy_and_join(src &string) string {
    parts := strings.split(src, "|")
    piece := parts[1]
    joined := strings.join(parts, "|")
    if joined != *src { << "" }
    << piece
}

fn main() int {
    for n in 31:66 {
        body := strings.repeat(&"a", n)
        original := "|" + body + "|"
        replaced := copy_and_replace(&original)
        if replaced.len != n || replaced[0] != 90 || original[1] != 97 { << 1 }
        for i in 1:n {
            if replaced[i] != 97 { << 2 }
        }
        retained := copy_and_join(&original)
        if retained.len != n { << 3 }
        for i in 0:n {
            if retained[i] != 97 { << 4 }
        }
    }
    println("split copies survived")
    << 0
}
""",
        expect_stdout="split copies survived\n",
        test_no_opt=True,
        debug_free=True,
    ),
    PosCase(
        name="Runtime_debug_free_enable_after_cached_disabled",
        code="""@main
core #runtime/core

fn main() int {
    first := core.alloc(24)
    core.free(first)
    recycled := core.alloc(24)
    if recycled != first {
        core.free(recycled)
        << 1
    }

    core.debug_free_enable()
    core.free(recycled)
    next := core.alloc(24)
    if next == recycled {
        core.free(next)
        << 2
    }
    core.free(next)
    println("debug free prevented reuse")
    << 0
}
""",
        expect_stdout="debug free prevented reuse\n",
        test_no_opt=True,
        debug_free=False,
    ),
    PosCase(
        name="Runtime_free_rejects_duplicate_release",
        code="""@main
core #runtime/core

fn main() {
    block := core.alloc(24)
    core.free(block)
    core.free(block)
}
""",
        expect_trap=True,
        expect_trap_substrings=("double free?",),
        test_no_opt=True,
        debug_free=False,
    ),
    PosCase(
        name="Empty_concat_preserves_free_block_and_copy_ownership",
        code="""@main
core #runtime/core
#strings

fn concatenate(a &string, b &string) string {
    << *a + *b
}

fn main() int {
    empty := ""
    saved := core.alloc(16)
    core.free(saved)
    result := concatenate(&empty, &empty)
    reused := core.alloc(16)
    core.free(reused)
    if result.len != 0 { << 1 }
    if saved != reused { << 2 }

    sizes := [1, 15, 16, 31, 32, 63, 64, 20001]
    for i in 0:sizes.len {
        n := sizes[i]
        source := strings.repeat(&"a", n)
        $left := concatenate(&source, &empty)
        $right := concatenate(&empty, &source)
        if left != source || right != source { << 3 }
        left[0] = 98
        if source[0] != 97 || right[0] != 97 { << 4 }
        right[n - 1] = 99
        if source[n - 1] != 97 || left[0] != 98 { << 5 }
    }
    println("empty concat preserved ownership")
    << 0
}
""",
        expect_stdout="empty concat preserved ownership\n",
        test_no_opt=True,
        debug_free=False,
    ),
    PosCase(
        name="Bounded_string_append_preserves_buffer_on_rejection",
        code="""@main
core #runtime/core

fn main() int {
    $text := ""
    if core.string_append_bounded($&text, &"abc", 20, 3) { << 1 }
    if text != "" || core.string_buffer_size(&text) != 0 { << 2 }
    if !core.string_append_bounded($&text, &"abc", 20, 4) { << 3 }
    if text != "abc" || core.string_buffer_size(&text) != 4 { << 4 }
    if core.string_append_bounded($&text, &"def", 20, 6) { << 5 }
    if text != "abc" || core.string_buffer_size(&text) != 4 { << 6 }
    if !core.string_append_bounded($&text, &"def", 20, 7) { << 7 }
    if core.string_append_bounded($&text, &"g", 6, 14) { << 8 }
    if !core.string_append_bounded($&text, &"g", 20, 14) { << 9 }
    if !core.string_append_bounded($&text, &"h", 20, 0) { << 10 }
    if text != "abcdefgh" || core.string_buffer_size(&text) != 14 { << 11 }
    println("bounded append preserved ownership")
    << 0
}
""",
        expect_stdout="bounded append preserved ownership\n",
        test_no_opt=True,
    ),
    PosCase(
        name="Push_byte_releases_small_blocks_at_terminator_boundary",
        code="""@main
core #runtime/core

fn main() int {
    first := core.alloc(16)
    second := core.alloc(16)
    core.free(second)
    core.free(first)

    $text := ""
    for i in 0:16 { text.push_byte(256 + i) }
    // A 16-byte string needs room for its terminator. Both original
    // 16-byte blocks must be reusable while the completed text is live.
    reused_first := core.alloc(16)
    reused_second := core.alloc(16)
    core.free(reused_second)
    core.free(reused_first)
    if !((reused_first == first && reused_second == second) ||
         (reused_first == second && reused_second == first)) { << 1 }

    text.push_str("!")
    if text.len != 17 || text[16] != 33 { << 2 }
    prefix := text[0:16]
    text.push_str(prefix)
    if text.len != 33 || text[16] != 33 { << 3 }
    for i in 0:16 {
        if text[i] != i || text[17 + i] != i { << 4 }
    }
    println("push_byte preserved the payload and spare byte")
    << 0
}
""",
        expect_stdout="push_byte preserved the payload and spare byte\n",
        test_no_opt=True,
        debug_free=False,
    ),
    PosCase(
        name="Push_str_short_binary_suffix_preserves_both_buffers",
        code="""@main
#strings

fn main() int {
    sizes := [0, 1, 7, 8, 9, 10, 15, 16, 17, 63, 64]
    for size_index in 0:sizes.len {
        n := sizes[size_index]
        $source := make_string(n)
        for i in 0:n { source[i] = (i * 73) & 255 }
        for prefix in 0:18 {
            $text := strings.repeat(&"z", prefix)
            for _ in 0:5 { text.push_str(source) }
            if text.len != prefix + 5 * n { << 1 }
            for i in 0:prefix {
                if text[i] != 122 { << 2 }
            }
            for part in 0:5 {
                for i in 0:n {
                    expected := (i * 73) & 255
                    if text[prefix + part * n + i] != expected || source[i] != expected { << 3 }
                }
            }
            if n > 0 {
                text[prefix] = 255
                if source[0] != 0 || text[prefix + n] != 0 { << 4 }
            }
        }
    }
    println("short appends preserved both buffers")
    << 0
}
""",
        expect_stdout="short appends preserved both buffers\n",
        test_no_opt=True,
    ),
    PosCase(
        name="H15_map_delete_and_take_stress",
        code="""@main
struct Guard { id int }
fn (g $&Guard) drop() { println("drop:" + str(g.id)) }
fn run_stress() {
    $m := map[string]Guard{}
    $c := 0
    for i in 0:30 {
        k := "k_" + str(i)
        m[k] = Guard{id: i}
    }
    for i in 0:15 {
        k := "k_" + str(i)
        m.delete(k)
        c += 1
    }
    for i in 15:30 {
        k := "k_" + str(i)
        v := m.take(k)
        if v.id == i { c += 1 }
    }
    println("count:" + str(c))
}
fn main() {
    run_stress()
}
""",
        expect_stdout_lines=("count:30", "drop:0", "drop:29"),
    ),
    PosCase(
        name="H16_chan_closure_throw_rc",
        code="""@main
#errors
fn send_val(ch chan int, v int) int {
    ch <- v
    if v < 0 { >> errors.new("neg") }
    << v
}
fn run() int {
    ch := chan int{cap: 4}
    f := fn() {
        g := fn() {
            ch <- 11
        }
        g()
        ch <- 22
    }
    f()
    r := send_val(ch, 33) or (e) { << 0 }
    a := <-ch
    b := <-ch
    c := <-ch
    << a + b + c + r
}
fn main() {
    println(run())
}
""",
        expect_stdout="99\n",
    ),
    PosCase(
        name="H17_match_owning_enum_single_drop",
        code="""@main
struct Guard { id int }
fn (g $&Guard) drop() { println("drop:" + str(g.id)) }
enum Item {
    One(Guard)
    Two(Guard, int)
    Empty
}
fn main() {
    x := Item.One(Guard{id: 77})
    match x {
        Item.One(g) {
            println("matched:" + str(g.id))
        }
        Item.Two(g, n) {
            println(str(g.id + n))
        }
        Item.Empty {
            println("empty")
        }
    }
    y := Item.Two(Guard{id: 88}, 1)
    match y {
        Item.One(g) { println("one:" + str(g.id)) }
        else { println("fallback") }
    }
}
""",
        expect_stdout="matched:77\ndrop:77\nfallback\ndrop:88\n",
    ),
    PosCase(
        name="H18_map_put_new_guard_no_zero_drop",
        code="""@main
struct Guard { id int }
fn (g $&Guard) drop() { println("drop:" + str(g.id)) }
fn main() {
    $m := map[string]Guard{}
    m["a"] = Guard{id: 42}
    m["a"] = Guard{id: 43}
    println("done")
}
""",
        expect_stdout="drop:42\ndone\ndrop:43\n",
        test_no_opt=True,
    ),
    PosCase(
        name="LowerErr_iface_field_cast_and_or",
        code="""@main
#errors
struct Guard { id int }
fn (g $&Guard) drop() { println("drop:" + str(g.id)) }
struct@ AnyBox {}
struct Holder {
    e AnyBox
}
fn fail_after(g Guard) int {
    if g.id > 0 { >> errors.new("fail") }
    << g.id
}
fn test_cast() {
    h := Holder{e: Guard{id: 55}}
    g := h.e as Guard
    println("cast:" + str(g.id))
}
fn run_or() int {
    v := fail_after(Guard{id: 66}) or (e) {
        println("caught")
        << 7
    }
    << v
}
fn main() {
    test_cast()
    println("v:" + str(run_or()))
}
""",
        expect_stdout="cast:55\ndrop:55\ndrop:66\ncaught\nv:7\n",
    ),
    PosCase(
        name="Select_unselected_send_arm_drop",
        code="""@main
fn mk_msg(i int) string {
    << "unselected_send_payload_" + str(1000000 + i)
}
fn main() {
    ready := chan int{cap: 1}
    full := chan string{cap: 0}
    $sum := 0
    for i in 0:50 {
        ready <- i
        select {
            v := <-ready {
                sum += v
            }
            full <- mk_msg(i) {
                sum += 999999
            }
        }
    }
    println("sum:" + str(sum))
}
""",
        expect_stdout="sum:1225\n",
    ),
    PosCase(
        name="Loop_break_drop_flag_accuracy",
        code="""@main
struct Guard { id int }
fn (g $&Guard) drop() { println("drop:" + str(g.id)) }
fn take(g Guard) { println("take:" + str(g.id)) }
fn main() {
    for i in 0:3 {
        g := Guard{id: 10 + i}
        if i == 1 {
            take(g)
            <-
        }
        println("keep:" + str(g.id))
    }
}
""",
        expect_stdout="keep:10\ndrop:10\ntake:11\ndrop:11\n",
    ),
    PosCase(
        name="PrintInt_loop_stress",
        code="""@main
fn main() {
    $s := 0
    for i in 0:5000 {
        s += i
    }
    println(s)
}
""",
        expect_stdout="12497500\n",
    ),
    PosCase(
        name="Stdlib_slog_with_group_empty_no_double_free",
        code="""@main
#log/slog
fn main() {
    l := slog.new_logger()
    l2 := l.with_group("")
    l3 := l2.with_group("grp")
    l3.info("msg", "k", "v")
    println("slog_ok")
}
""",
        expect_stdout_lines=("slog_ok",),
    ),
    PosCase(
        name="TwoPhase_mut_recv_arg_eval",
        code="""@main
struct Buf {
    xs []int
}
fn (b $&Buf) append_n(n int) {
    b.xs.push(n)
}
fn (b &Buf) cur_len() int {
    << b.xs.len
}
fn main() {
    $b := Buf{xs: [5, 6]}
    b.append_n(b.cur_len())
    println(b.xs.len)
}
""",
        expect_stdout="3\n",
    ),
    PosCase(
        name="Chan_iface_in_struct_allowed",
        code="""@main
struct@ Worker {
    fn work() int
}
struct Job { id int }
fn (j Job) work() int { << j.id }
struct Slot {
    w Worker
}
fn main() {
    ch := chan Slot{cap: 1}
    ch <- Slot{w: Job{id: 123}}
    s := <-ch
    println(s.w.work())
}
""",
        expect_stdout="123\n",
    ),
    PosCase(
        name="IfCond_string_branch_return_clones_safely",
        code="""@main
fn starts(s string, prefix string) bool {
    << s.len >= prefix.len && s[0:prefix.len] == prefix
}
fn classify(raw string) string {
    if starts(raw, "https://") { << "https" }
    if starts(raw, "http://") { << "http" }
    << "other:" + raw
}
fn main() {
    long_url := "mysql://" + "127.0.0.1:3306/long_database_name_pad"
    println(classify(long_url))
}
""",
        expect_stdout="other:mysql://127.0.0.1:3306/long_database_name_pad\n",
    ),
    PosCase(
        name="Reader_read_rune_borrowed_utf8",
        code="""@main
#strings
fn main() {
    $r := strings.new_reader("A中🙂" + string_from_byte(255))
    for i in 0:4 {
        rune := r.read_rune() or (err) { <<< 1 }
        println(rune.ch)
        println(rune.size)
    }
    r.read_rune() or (err) {
        println(err.msg())
        <<
    }
    <<< 2
}
""",
        expect_stdout="65\n1\n20013\n3\n128578\n4\n65533\n1\nEOF\n",
        test_no_opt=True,
    ),
    PosCase(
        name="Ord_generic_self_method_works",
        code="""@main
#cmp
fn min2(a# Ord, b# Ord) Ord {
    if a.less(b) { << a }
    << b
}
fn main() {
    println(str(min2(9, 3)) + ":" + min2("banana_padpadpad", "apple_padpadpad"))
}
""",
        expect_stdout="3:apple_padpadpad\n",
    ),
]


def make_env(xu_path: Path, debug_free: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env["XU_ROOT"] = str(REPO_ROOT)
    env["XU_STDLIB_ROOT"] = str(REPO_ROOT / "src")
    env["XUPATH"] = str(REPO_ROOT / "src")
    if debug_free:
        env["XU_DEBUG_FREE"] = "1"
    else:
        env.pop("XU_DEBUG_FREE", None)
    return env


def run_neg(xu: Path, tmpdir: Path, idx: int, case: NegCase) -> Optional[str]:
    src = tmpdir / f"neg_{idx:03d}.xu"
    src.write_text(case.code, encoding="utf-8")
    proc = subprocess.run(
        [str(xu), "check", str(src)],
        capture_output=True,
        text=True,
        env=make_env(xu),
        timeout=60,
    )
    raw_out = (proc.stdout + "\n" + proc.stderr).strip()
    out = raw_out.replace(str(src), "<src>")
    if proc.returncode == 0:
        return f"expected compile error, but succeeded:\n{out}"
    low = out.lower()
    for noise in SYNTAX_NOISE:
        if noise in low:
            return f"unexpected syntax/front-end error ({noise}):\n{out}"
    if case.expect_substrings and not any(s.lower() in low for s in case.expect_substrings):
        return (
            f"missing expected diagnostic {case.expect_substrings!r};\n"
            f"actual output:\n{out}"
        )
    return None


def run_pos_mode(xu: Path, tmpdir: Path, idx: int, case: PosCase, no_opt: bool) -> Optional[str]:
    tag = "noopt" if no_opt else "opt"
    exe_suffix = ".exe" if platform.system().lower().startswith("win") else ""
    src = tmpdir / f"pos_{idx:03d}_{tag}.xu"
    exe = tmpdir / f"pos_{idx:03d}_{tag}{exe_suffix}"
    src.write_text(case.code, encoding="utf-8")

    cmd = [str(xu), "build", "-o", str(exe)]
    if no_opt:
        cmd.append("--no-opt")
    cmd.append(str(src))

    comp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=make_env(xu),
        timeout=120,
    )
    if comp.returncode != 0:
        return f"[{tag}] build failed ({comp.returncode}):\n{comp.stdout}\n{comp.stderr}"

    run = subprocess.run(
        [str(exe)],
        capture_output=True,
        text=True,
        env=make_env(xu, debug_free=case.debug_free),
        timeout=60,
    )
    out = run.stdout
    err = run.stderr
    combined = (out + "\n" + err).lower()

    if case.expect_trap:
        if run.returncode == 0:
            return f"[{tag}] expected runtime trap, but exited 0; stdout={out!r} stderr={err!r}"
        if run.returncode in (-11, -10, 139, 138):
            return f"[{tag}] raw memory crash rc={run.returncode}; stdout={out!r} stderr={err!r}"
        if case.expect_trap_substrings and not any(
            s.lower() in combined for s in case.expect_trap_substrings
        ):
            return (
                f"[{tag}] trap rc={run.returncode} missing expected message "
                f"{case.expect_trap_substrings!r}; out={out!r} err={err!r}"
            )
        return None

    if run.returncode != 0:
        return f"[{tag}] runtime failed rc={run.returncode}:\nstdout:\n{out}\nstderr:\n{err}"

    if case.expect_stdout is not None and out != case.expect_stdout:
        return f"[{tag}] stdout mismatch:\nwant: {case.expect_stdout!r}\ngot:  {out!r}"
    for line in case.expect_stdout_lines:
        if line not in out:
            return f"[{tag}] stdout missing {line!r};\ngot:\n{out}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Xu memory-safety & zero-GC regression gate")
    parser.add_argument("--xu", type=Path, default=default_xu_path(), help="Path to xu compiler")
    parser.add_argument("--filter", default="", help="Only run tests whose name contains substring")
    args = parser.parse_args()

    xu = args.xu.resolve()
    if not xu.is_file():
        print(f"ERROR: xu binary not found: {xu}", file=sys.stderr)
        return 2

    failures: list[str] = []
    ran = 0

    tmpdir = Path(tempfile.mkdtemp(prefix="xu_memsafe_"))
    try:
        for idx, nc in enumerate(NEG_CASES):
            if args.filter and args.filter not in nc.name:
                continue
            ran += 1
            err = run_neg(xu, tmpdir, idx, nc)
            if err:
                failures.append(f"FAIL [NEG] {nc.name}: {err}")
                print(f"FAIL [NEG] {nc.name}")
            else:
                print(f"PASS [NEG] {nc.name}")

        for idx, pc in enumerate(POS_CASES):
            if args.filter and args.filter not in pc.name:
                continue
            modes = (False, True) if pc.test_no_opt else (False,)
            for no_opt in modes:
                ran += 1
                tag = "no-opt" if no_opt else "opt"
                err = run_pos_mode(xu, tmpdir, idx, pc, no_opt=no_opt)
                if err:
                    failures.append(f"FAIL [POS/{tag}] {pc.name}: {err}")
                    print(f"FAIL [POS/{tag}] {pc.name}")
                else:
                    print(f"PASS [POS/{tag}] {pc.name}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\nSummary: {ran - len(failures)}/{ran} checks passed")
    if failures:
        print("\nDetails:")
        for f in failures:
            print("---")
            print(f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
