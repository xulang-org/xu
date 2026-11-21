#!/usr/bin/env python3
"""Public native library/network/concurrency fixtures for platform_test.sh.

Every compiled artifact must execute and match stdout, stderr and exit status.
No Docker, Wine, emulation or ignored tests/ corpus is needed by this gate.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import errno
import os
from pathlib import Path
import platform
import select
import socket
import ssl
import subprocess
import tempfile
from threading import Timer
import time

ROOT = Path(__file__).resolve().parents[1]
TARGETS = tuple(f"{os_name}-{arch}" for os_name in ("linux", "macos", "windows") for arch in ("x64", "arm64"))


def native_target() -> str:
    system = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform.system())
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    return f"{system}-{arch}"


def compiler_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("XU")}
    env.update(XU_ROOT=str(ROOT), XU_STDLIB_ROOT=str(ROOT / "src"), XUPATH="")
    return env


LIBRARY = r'''@main
#os
#path/filepath
#time
#crypto/sha256
#crypto/rand
#encoding/json
fn literal_values() []int {
    << [0, 1, 2, 3, 4, 5, 6, 7]
}
fn file_read_boundary(size int) bool {
    $want := make_string(size)
    if size > 0 {
        want[0] = 255
        want[size - 1] = 129
    }
    written := os.write("file-read-boundary", want + "") or (err) { << false }
    if written != size { << false }
    $body := os.read("file-read-boundary") or (err) { << false }
    if body != want { << false }
    body.push_byte(128)
    << body.len == size + 1 && body[size] == 128 && body[0:size] == want
}
fn main() int {
    // Separate evaluations must own separate storage, including literals
    // whose constant elements can be initialized from a compiler data pool.
    $first := literal_values()
    $second := literal_values()
    first[0] = 99
    if second[0] != 0 { << 12 }
    second[7] = 88
    $third := literal_values()
    if third[0] != 0 || third[7] != 7 || first[7] != 7 { << 13 }
    third.push(8)
    if third.len != 9 || third[8] != 8 || second[7] != 88 { << 14 }
    os.write("roundtrip", "Xu\nbytes") or (err) { eprintln(err.msg())
        << 1 }
    body := os.read("roundtrip") or (err) { eprintln(err.msg())
        << 2 }
    if body != "Xu\nbytes" { << 3 }
    for size in [0, 65534, 65535, 65536, 524288] {
        if !file_read_boundary(size) { << 15 }
    }
    path := "a/../b/./c"
    clean := filepath.clean(&path)
    slash := filepath.to_slash(&clean)
    if slash != "b/c" { << 4 }
    if sha256.sum256("abc") != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" { << 5 }
    bytes := rand.read(32) or (err) { eprintln(err.msg())
        << 6 }
    if bytes.len != 32 { << 7 }
    text := "{\"value\":42}"
    doc := json.parse(&text)
    if !doc.ok() { << 8 }
    value := doc.as_int(doc.get(doc.root(), "value")) or (err) { << 10 }
    if value != 42 { << 11 }
    if time.now() <= 0 { << 9 }
    println("library passed")
    << 0
}
'''

OPTIMIZED_CODE = r'''@main
#crypto/aes
#crypto/md5
#crypto/sha256
#encoding/base64
#encoding/hex
#math
#math/bits
#strings

struct Counter {
    value int
}

fn (c $&Counter) add(n int) {
    c.value += n
}

fn (c &Counter) get() int {
    << c.value
}

fn bump_one(x int) int {
    << x + 1
}

fn bump_ten(x int) int {
    << x + 10
}

fn check_match_lut_cases() bool {
    // Masked dense 8-way match with else arm.
    $masked := 0
    for i in 0:64 {
        k := i & 7
        match k {
            0 { masked += 1 }
            1 { masked += 3 }
            2 { masked += 5 }
            3 { masked += 7 }
            4 { masked += 11 }
            5 { masked += 13 }
            6 { masked += 17 }
            else { masked += 19 }
        }
    }
    if masked != 608 { << false }

    // Unmasked match with negative lo, out-of-range inputs, duplicate arm, and empty arm.
    $unmasked := 0
    $inputs := [-10, -3, -2, -1, 0, 1, 2, 3, 10]
    for idx in 0:inputs.len {
        v := inputs[idx]
        match v {
            -3 { unmasked += 10 }
            -2 { unmasked += 20 }
            -1 { }
            0 { unmasked += 40 }
            1 { unmasked += 50 }
            1 { unmasked += 999 }
            2 { unmasked += 60 }
            3 { unmasked += 70 }
            else { unmasked += 3 }
        }
        // Keep selector live after match.
        if v != inputs[idx] { << false }
    }
    if unmasked != 256 { << false }

    // Selector local updated inside match arms.
    $self_sum := 0
    for j in 0:8 {
        $x := j
        match x {
            0 { x += 2 }
            1 { x += 4 }
            2 { x += 6 }
            3 { x += 8 }
            4 { x += 10 }
            5 { x += 12 }
            6 { x += 14 }
            else { x += 16 }
        }
        self_sum += x
    }
    << self_sum == 100
}

fn check_fnval_cases(flag bool) bool {
    // Non-capturing function value (eligible for zero-env drop elim + SROA + devirt).
    f := bump_one
    $sum := 0
    for i in 0:32 {
        sum += f(i & 7)
    }
    if sum != 144 { << false }

    // Reassigned non-capturing function value (must keep dynamic dispatch).
    $g := bump_one
    if flag { g = bump_ten }
    $want_g := 6
    if flag { want_g = 15 }
    if g(5) != want_g { << false }

    // Capturing closure (negative case: must preserve env and drop glue).
    base := 100
    h := fn(x int) int { << base + x }
    if h(7) != 107 { << false }

    // Mixed non-capturing and capturing reassignment (negative case: must preserve drop).
    $m := bump_one
    if flag {
        m = fn(x int) int { << base + x * 2 }
    }
    $want_m := 7
    if flag { want_m = 112 }
    if m(6) != want_m { << false }

    // Bound method value (negative case: non-zero borrowed receiver env).
    c := Counter{value: 42}
    bm := c.get
    << bm() == 42
}

fn rejects_invalid_hex() bool {
    _ := hex.decode_string("0123456789ABCDEFg123456789abcdef") or (err) { << true }
    << false
}

fn rejects_invalid_base64(src string) bool {
    _ := base64.decode_string(~src) or (err) { << err.msg() == "encoding/base64: invalid padding" }
    << false
}

fn check_recycled_strings() bool {
    lengths := [1, 15, 16, 31, 32, 47, 48, 63, 64, 16383, 16384, 20000, 32751, 32752]
    seed := "az"
    for index in 0:lengths.len {
        n := lengths[index]
        for _ in 0:3 {
            $buffer := make_string(n)
            for i in 0:n {
                if buffer[i] != 0 { << false }
                buffer[i] = 255
            }
        }
        repeated := strings.repeat(&seed, (n + 1) / 2)
        if repeated.len != ((n + 1) / 2) * 2 { << false }
        for i in 0:repeated.len {
            if repeated[i] != seed[i & 1] { << false }
        }
    }
    << true
}

fn check_short_string_copies() bool {
    seed := "za"
    src := strings.repeat(&seed, 18)
    if find_byte(&src, 122, 1) != 2 || find_byte(&src, 98, 1) != -1 { << false }
    for n in 1:34 {
        piece := src[1:n + 1]
        if piece.len != n || count_byte(&piece, 97) != (n + 1) / 2 { << false }
        for i in 0:n {
            if piece[i] != src[i + 1] { << false }
        }
    }
    $binary := make_string(67)
    for i in 0:binary.len { binary[i] = (i + 255) & 255 }
    for n in 31:66 {
        piece := binary[1:n + 1]
        if piece.len != n { << false }
        joined := strings.join(["start", piece, "end"], "|")
        if joined.len != n + 10 || !strings.has_prefix(&joined, "start|") || !strings.has_suffix(&joined, "|end") {
            << false
        }
        for i in 0:n {
            if joined[i + 6] != i { << false }
        }
    }
    << true
}

fn gcd(a int, b int) int {
    if b == 0 { << a }
    << gcd(b, a % b)
}

fn div2_if_even(x int) int {
    if x % 2 == 0 { << x / 2 }
    << x * 3 + 1
}

fn div4_if_mod4(x int) int {
    if x % 4 == 0 { << x / 4 }
    << x * 5 - 3
}

fn div8_if_neg_mod8(x int) int {
    if x % -8 != 0 { << x * 9 + 1 }
    << x / 8
}

fn div2_modified_after_guard(x0 int) int {
    $x := x0
    if x % 2 == 0 {
        x = x - 1
        << x / 2
    }
    << x
}

fn mod_value_used(x int) int {
    r := x % 4
    if r == 0 { << 100 }
    << r
}

fn div4_under_mod2_guard(x int) int {
    if x % 2 == 0 { << x / 4 }
    << 0
}

fn verify_divc_pow2_and_mul() bool {
    min_i64 := -9223372036854775807 - 1
    if div2_if_even(-6) != -3 || div2_if_even(-5) != -14 || div2_if_even(min_i64) != (-4611686018427387904) { << false }
    if div4_if_mod4(-12) != -3 || div4_if_mod4(-10) != -53 || div4_if_mod4(min_i64) != (-2305843009213693952) { << false }
    if div8_if_neg_mod8(-16) != -2 || div8_if_neg_mod8(-10) != -89 || div8_if_neg_mod8(min_i64) != (-1152921504606846976) { << false }
    // Negative cases: modified local after guard, modulo value used directly, narrower guard
    if div2_modified_after_guard(-4) != -2 || div2_modified_after_guard(0) != 0 { << false }
    if mod_value_used(-3) != -3 || mod_value_used(-4) != 100 || mod_value_used(3) != 3 { << false }
    if div4_under_mod2_guard(-2) != 0 || div4_under_mod2_guard(-6) != -1 { << false }
    // Collatz-style loop exercising cmp + hoisted store + select and mul by 2^k+1
    $acc := 0
    $x := 27
    while x != 1 {
        if x % 2 == 0 {
            acc += 1
            x = x / 2
        } else {
            acc += 1
            x = x * 3 + 1
        }
    }
    if acc != 111 { << false }
    // Negative odd/even mul by 3, 5, 9, 17
    v := -7
    if v * 3 != -21 || 3 * v != -21 || v * 5 != -35 || v * 9 != -63 || v * 17 != -119 { << false }
    << true
}

struct@ ZstVal {
    fn tag() int
}

struct ZstEmpty {}
struct ZstNonEmpty {
    n int
}
struct ZstEmptyErr {}

fn (e ZstEmpty) tag() int { << 42 }
fn (n ZstNonEmpty) tag() int { << n.n }
fn (e ZstEmptyErr) msg() string { << "zst-empty-err" }

fn zst_pass(v ZstVal) int { << v.tag() }

fn zst_may_fail(flag bool) int {
    if flag { >> ZstEmptyErr{} }
    << 99
}

fn zst_catch(flag bool) string {
    v := zst_may_fail(flag) or (err) { << err.msg() }
    << str(v)
}

fn check_zst_static_box() bool {
    let e: ZstVal = ZstEmpty{}
    if e.tag() != 42 || zst_pass(e) != 42 { << false }
    $arr := []ZstVal{}
    for _ in 0:16 {
        arr.push(ZstEmpty{})
        arr.push(ZstNonEmpty{n: 10})
    }
    $sum := 0
    for i in 0:arr.len {
        sum += arr[i].tag()
    }
    if sum != 832 { << false }
    if zst_catch(true) != "zst-empty-err" || zst_catch(false) != "99" { << false }
    let a1: any = ZstEmpty{}
    _ := a1 as ZstEmpty
    let a2: any = ZstNonEmpty{n: 55}
    u := a2 as ZstNonEmpty
    if u.n != 55 { << false }
    let ne: ZstVal = ZstNonEmpty{n: 13}
    << ne.tag() + zst_pass(ne) == 26
}

fn check_loop_carry_cases() bool {
    $a := []int{}
    $i := 0
    while i < 64 {
        a.push((i * 17 + 5) & 255)
        i += 1
    }
    $pass := 0
    while pass < 3 {
        $k := 1
        while k < a.len {
            a[k] = (a[k - 1] * 3 + a[k]) % 1000000007
            k += 1
        }
        pass += 1
    }
    if a[0] != 5 || a[63] != 564084038 { << false }
    // Zero-trip bound and offset-2 index guard must keep prefix untouched.
    $z := [11, 22, 33, 44]
    $zi := 2
    while zi < 2 {
        z[zi] = (z[zi - 1] * 5 + z[zi]) % 1000000007
        zi += 1
    }
    if z[0] != 11 || z[1] != 22 || z[2] != 33 || z[3] != 44 { << false }
    $j := 2
    while j < z.len {
        z[j] = (z[j - 1] * 5 + z[j]) % 1000000007
        j += 1
    }
    if z[0] != 11 || z[1] != 22 || z[2] != 143 || z[3] != 759 { << false }
    << true
}

fn check_map_int_cases() bool {
    $m := map[int]int{}
    edge_keys := [0, -1, -9223372036854775807 - 1, 9223372036854775807]
    for i in 0:edge_keys.len {
        m[edge_keys[i]] = 1000 + i
    }
    for i in 0:256 {
        m[i * 3 + 1] = i * 7 + 2
    }
    if m.len() != 260 { << false }
    for i in 0:160 {
        m.delete(i * 3 + 1)
    }
    if m.len() != 100 { << false }
    // Reuse tombstones and grow across threshold while overwriting existing entries.
    for i in 0:200 {
        key := 10000 + i
        m[key] = i + 50
        m[key] = m[key] + 10
    }
    if m.len() != 300 { << false }
    if m.has(1) || !m.has(160 * 3 + 1) || m[160 * 3 + 1] != 160 * 7 + 2 { << false }
    if m[10199] != 259 { << false }
    for i in 0:edge_keys.len {
        if m[edge_keys[i]] != 1000 + i { << false }
    }
    $seen := 0
    for key, value in m {
        if !m.has(key) || m[key] != value { << false }
        seen += 1
    }
    if seen != m.len() { << false }
    $sm := map[string]int{}
    for i in 0:64 {
        k := "k-" + str(i)
        sm[k] = i
        sm[k] = sm[k] + 100
    }
    for i in 0:40 {
        sm.delete("k-" + str(i))
    }
    for i in 0:64 {
        sm["n-" + str(i)] = i * 2
    }
    << sm.len() == 88 && !sm.has("k-0") && sm["k-63"] == 163 && sm["n-63"] == 126
}

fn implicit_borrow_values() bool {
    first := 23
    counter := Counter{value: 42}
    let $ref: &int = first
    if *ref != 23 { << false }
    ref = counter.value
    if *ref != 42 { << false }
    values := [4, 5]
    ref = values[1]
    if *ref != 5 { << false }
    ref = values.len
    << *ref == 2
}

struct Vec3 {
    x f64
    y f64
    z f64
}

struct Pair32 {
    a f32
    b f32
    c f64
}

fn callee_fp_pressure(a f64, b f64, c f64, d f64) f64 {
    $v0 := a + 1.0
    $v1 := b + 2.0
    $v2 := c + 3.0
    $v3 := d + 4.0
    $v4 := v0 * 1.25 + v1
    $v5 := v1 * 1.5 - v2
    $v6 := v2 * 0.75 + v3
    $v7 := v3 * 2.5 - v0
    $v8 := v4 + v5
    $v9 := v6 + v7
    $v10 := v8 * v9 - v4 * v6
    << v10 + v0 + v1 + v2 + v3 + v5 + v7 + v8 + v9
}

fn stack_params_f64(a0 f64, a1 f64, a2 f64, a3 f64, a4 f64, a5 f64, a6 f64, a7 f64, a8 f64, a9 f64, a10 f64, a11 f64) f64 {
    << a0 * 1.0 + a1 * 2.0 + a2 * 3.0 + a3 * 4.0 +
       a4 * 5.0 + a5 * 6.0 + a6 * 7.0 + a7 * 8.0 +
       a8 * 9.0 + a9 * 10.0 + a10 * 11.0 + a11 * 12.0
}

fn fp_cmp_bits(a f64, b f64) int {
    $m := 0
    if a == b { m = m | 1 }
    if a != b { m = m | 2 }
    if a < b  { m = m | 4 }
    if a <= b { m = m | 8 }
    if a > b  { m = m | 16 }
    if a >= b { m = m | 32 }
    << m
}

fn select_f64(cond bool, a f64, b f64) f64 {
    $r := b
    if cond { r = a }
    << r
}

fn verify_fp_regalloc() bool {
    x := 3.5
    y := -2.25
    if int((x * x + y * y + (x + x) - (y - y) + (x / x)) * 100.0) != 2531 { << false }
    if int(math.sqrt(152.25) * 1000.0) != 12338 { << false }
    if int(-x * 10.0) != -35 { << false }
    zero := 0.0
    neg_zero := -0.0
    pos_inf := 1.0 / zero
    neg_inf := -1.0 / zero
    nan := zero / zero
    if int(1.9) != 1 || int(-1.9) != -1 || int(neg_zero) != 0 { << false }
    if int(1e20) != 9223372036854775807 || int(-1e20) != (-9223372036854775807 - 1) { << false }
    if int(pos_inf) != 9223372036854775807 || int(neg_inf) != (-9223372036854775807 - 1) || int(nan) != 0 { << false }
    if fp_cmp_bits(1.0, 2.0) != 14 || fp_cmp_bits(2.0, 2.0) != 41 || fp_cmp_bits(3.0, 2.0) != 50 { << false }
    if fp_cmp_bits(zero, neg_zero) != 41 || fp_cmp_bits(nan, 1.0) != 2 || fp_cmp_bits(1.0, nan) != 2 || fp_cmp_bits(nan, nan) != 2 { << false }
    $a0 := 1.25
    $a1 := 2.5
    $a2 := 3.75
    $a3 := 4.5
    $a4 := 5.25
    $a5 := 6.5
    $a6 := 7.75
    $a7 := 8.5
    $a8 := 9.25
    $a9 := 10.5
    $call_sum := 0.0
    for k in 0:10 {
        call_sum += callee_fp_pressure(a0 + f64(k), a1, a2, a3)
        if hex.encode_to_string("0123456789abcdef0123456789abcdef").len != 64 { << false }
        a0 += 0.5
        a1 += 0.25
        a2 += 0.5
        a3 += 0.25
        a4 += 0.5
        a5 += 0.25
        a6 += 0.5
        a7 += 0.25
        a8 += 0.5
        a9 += 0.25
    }
    if int(call_sum + a0 + a1 + a2 + a3 + a4 + a5 + a6 + a7 + a8 + a9) != 3266 { << false }
    if int(stack_params_f64(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0)) != 650 { << false }
    if int(select_f64(true, 42.5, -7.5) * 2.0) != 85 || int(select_f64(false, 42.5, -7.5) * 2.0) != -15 { << false }
    $vs := []Vec3{}
    for i in 0:32 {
        vs.push(Vec3{x: f64(i), y: f64(i) * 0.5, z: f64(i) * 1.5})
    }
    $vsum := 0.0
    for i in 0:32 {
        vs[i].x = vs[i].x + 1.0
        vs[i].y = vs[i].y * 2.0
        vs[i].z = vs[i].z - 0.5
        vsum += vs[i].x * vs[i].x + vs[i].y * vs[i].y + vs[i].z * vs[i].z
    }
    if int(vsum * 4.0) != 178224 { << false }
    $ps := []Pair32{}
    for i in 0:8 {
        ps.push(Pair32{a: f32(i) + f32(0.25), b: f32(i) * f32(1.5), c: f64(i) * 2.25})
    }
    $psum := 0.0
    for i in 0:8 {
        psum += f64(ps[i].a) + f64(ps[i].b) + ps[i].c
    }
    << int(psum * 4.0) == 540
}

fn main() int {
    $counter := Counter{value: 3}
    $sum := 5
    $i := 3
    while i < 35 {
        sum += i & 7
        i += 1
    }
    if !verify_fp_regalloc() { << 40 }
    counter.add(sum)
    if i != 35 || counter.value != 120 { << 1 }

    // The later read uses the incremented i and cannot be folded as above.
    i = 0
    sum = 0
    while i < 9 {
        i += 1
        sum += i & 7
    }
    if sum != 29 { << 2 }
    if gcd(1071, 462) != 21 { << 16 }
    if !verify_divc_pow2_and_mul() { << 41 }
    if !implicit_borrow_values() { << 20 }

    if bits.len(0) != 0 || bits.leading_zeros(0) != 64 || bits.trailing_zeros(0) != 64 { << 3 }
    if bits.ones_count(-1) != 64 || bits.reverse(1) != (1 << 63) { << 4 }
    if bits.rotate_left(1, -1) != (1 << 63) || bits.rotate_right(1, 64) != 1 { << 5 }

    // Exercise a SIMD block plus a scalar tail, mixed case and bad bytes.
    bytes := hex.decode_string("0123456789ABCDEF0123456789abcdefF0") or (err) { << 6 }
    if hex.encode_to_string(bytes + "") != "0123456789abcdef0123456789abcdeff0" { << 7 }
    if !rejects_invalid_hex() { << 8 }

    key := hex.decode_string("000102030405060708090a0b0c0d0e0f") or (err) { << 9 }
    plain := hex.decode_string("00112233445566778899aabbccddeeff") or (err) { << 10 }
    cipher := aes.new_cipher(&key) or (err) { << 11 }
    encrypted := cipher.encrypt(&plain) or (err) { << 12 }
    if hex.encode_to_string(encrypted + "") != "69c4e0d86a7b0430d8cdb78070b4c55a" { << 13 }
    recovered := cipher.decrypt(&encrypted) or (err) { << 14 }
    if recovered != plain { << 15 }
    if sha256.sum256("abc") != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" { << 17 }
    if md5.sum("") != "d41d8cd98f00b204e9800998ecf8427e" { << 21 }
    if md5.sum("abc") != "900150983cd24fb0d6963f7d28e17f72" { << 22 }
    if md5.sum("0123456789abcdef0123456789abcdef") != "8516ac99dc60603295de7bdb6a153530" { << 23 }
    unaligned := "x0123456789abcdef0123456789abcdefy"
    if md5.sum(unaligned[1:33]) != "8516ac99dc60603295de7bdb6a153530" { << 24 }
    $md := md5.new()
    md.write(&"The quick brown ")
    md.write(&"fox jumps over the lazy dog")
    if md.sum() != "9e107d9d372bb6826bd81d3542a419d6" { << 25 }
    if md.sum() != "9e107d9d372bb6826bd81d3542a419d6" { << 26 }
    md.reset()
    md.write(&"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    if md.sum() != "3b0c8ac703f828b04c6c197006d17218" { << 27 }
    source := "abcd"
    view := source[1:3]
    $once := strings.repeat(&view, 1)
    once[0] = 120
    if view != "bc" || once != "xc" || strings.repeat(&view, 5) != "bcbcbcbcbc" { << 18 }
    empty := ""
    if strings.repeat(&empty, 5) != "" || strings.repeat(&view, -1) != "" { << 19 }
    if !check_match_lut_cases() { << 38 }
    if !check_fnval_cases(true) || !check_fnval_cases(false) { << 39 }
    $binary := make_string(33)
    for i in 0:33 { binary[i] = 128 + (i & 1) }
    if count_byte(&binary, 128) != 17 || count_byte(&binary, 129) != 16 || count_byte(&binary, 0) != 0 { << 28 }
    parts := split_byte(&binary, 128)
    if parts.len != 18 || parts[0] != "" || parts[1] != string_from_byte(129) || parts[17] != "" { << 29 }
    if strings.join(parts, string_from_byte(128)) != binary { << 30 }
    prefix := "/+7d"
    block := strings.repeat(&prefix, 33)
    original := base64.decode_string(block + "/g==") or (err) { << 31 }
    if original.len != 100 || original[0] != 255 || original[99] != 254 { << 32 }
    if base64.encode_to_string(original + "") != block + "/g==" { << 33 }
    if !rejects_invalid_base64(block + "AA=A") { << 34 }
    for i in 0:8 {
        $large := make_string(20000 + i)
        if large[0] != 0 || large[large.len - 1] != 0 { << 35 }
        large[0] = 255
        large[large.len - 1] = 255
    }
    if !check_recycled_strings() { << 36 }
    if !check_short_string_copies() { << 37 }
    if !check_zst_static_box() { << 40 }
    if !check_loop_carry_cases() { << 41 }
    if !check_map_int_cases() { << 42 }
    println("optimized code passed")
    << 0
}
'''


CONCURRENCY = r'''@main
fn worker(ch chan string, value int) {
    $values := map[string]int{}
    for i in 0:64 { values["key-" + str(i)] = value + i }
    sleep_ns(1000000)
    ch <- str(values["key-63"])
}
fn probe(capacity int) int {
    ch := chan string{cap: capacity}
    for i in 0:32 { xu worker(ch, i) }
    $total := 0
    for i in 0:32 {
        value := <-ch
        n := parse_int(value) or (err) { << -1 }
        total += n
    }
    << total
}
fn fp_worker(ch chan int, out chan int, seed f64) {
    $f0 := seed + 1.5
    $f1 := seed + 2.5
    $f2 := seed + 3.5
    $f3 := seed + 4.5
    $f4 := seed + 5.5
    $f5 := seed + 6.5
    $f6 := seed + 7.5
    $f7 := seed + 8.5
    $f8 := seed + 9.5
    $f9 := seed + 10.5
    for _ in 0:8 {
        dv := f64(<-ch)
        f0 += dv * 0.25
        f1 += dv * 0.5
        f2 += dv * 0.75
        f3 += dv * 1.0
        f4 += dv * 1.25
        f5 += dv * 1.5
        f6 += dv * 1.75
        f7 += dv * 2.0
        f8 += dv * 2.25
        f9 += dv * 2.5
        out <- int(f0 + f1 + f2 + f3 + f4 + f5 + f6 + f7 + f8 + f9)
    }
}
fn main() int {
    for round in 0:4 {
        if probe(0) != 2512 { << 2 }
        if probe(32) != 2512 { << 4 }
    }
    ch1 := chan int{cap: 0}
    out1 := chan int{cap: 0}
    ch2 := chan int{cap: 0}
    out2 := chan int{cap: 0}
    xu fp_worker(ch1, out1, 1.0)
    xu fp_worker(ch2, out2, 100.0)
    $tsum := 0
    for i in 0:8 {
        ch1 <- (i + 1)
        ch2 <- (i + 10)
        tsum += <-out1
        tsum += <-out2
    }
    if tsum != 16789 { << 5 }
    println("concurrency passed")
    << 0
}
'''

STREAM = r'''@main
#net
fn probe(network string, address string) int {
    $conn := net.dial_to(network, address) or >>
    data := "Xu stream probe"
    $sent := 0
    while sent < data.len {
        part := data[sent:data.len]
        n := conn.write(&part) or >>
        if n <= 0 || n > part.len { << 2 }
        sent += n
    }
    $reply := ""
    while reply.len < data.len {
        part := conn.read(data.len - reply.len) or >>
        if part.len == 0 { << 3 }
        reply = reply + part
    }
    conn.close() or >>
    if reply != data { << 4 }
    println("stream passed")
    << 0
}
fn main() int {
    a := args()
    << probe(a[1] + "", a[2] + "") or (err) { eprintln(err.msg())
        << 1 }
}
'''

UDP = r'''@main
#net
fn probe(address string, connected bool) int {
    remote := net.resolve_udp_addr("udp4", address) or >>
    local := net.UDPAddr{ip: net.ipv4(127, 0, 0, 1), port: 0, zone: ""}
    data := "Xu datagram"
    if connected {
        $c := net.dial_udp("udp4", local.clone(), remote.clone()) or >>
        if (c.write(&data) or >>) != data.len { << 2 }
        reply := c.read(128) or >>
        c.close() or >>
        if reply != data { << 3 }
    } else {
        $c := net.listen_udp("udp4", local.clone()) or >>
        if (c.write_to(&data, &remote) or >>) != data.len { << 4 }
        reply := c.read_from(128) or >>
        c.close() or >>
        if reply.data != data || reply.addr.port != remote.port { << 5 }
    }
    println("udp passed")
    << 0
}
fn main() int {
    a := args()
    << probe(a[1] + "", a[2] == "connected") or (err) { eprintln(err.msg())
        << 1 }
}
'''

INTERFACES = r'''@main
#net
fn probe() int {
    all := net.interfaces() or >>
    if all.len == 0 { << 2 }
    $addresses := 0
    for i in 0:all.len {
        item := all[i]
        if item.name.len == 0 || item.index <= 0 { << 3 }
        found := net.interface_by_name(item.name + "") or >>
        if found.index != item.index { << 4 }
        ips := item.addrs() or >>
        addresses += ips.len
    }
    if addresses == 0 { << 5 }
    println("interfaces passed")
    << 0
}
fn main() int {
    << probe() or (err) { eprintln(err.msg())
        << 1 }
}
'''

WINDOWS_UNIX = r'''@main
#net
fn main() int {
    _ := net.dial_to("unix", "unsupported.sock") or (err) {
        if err.msg() != "net: unix sockets are not available on this target" { eprintln(err.msg())
            << 2 }
        println("unsupported Unix socket rejected")
        << 0
    }
    << 1
}
'''

NET_CONTRACT = r'''@main
#net
fn invalid_network() bool {
    _ := net.dial_to("invalid", "127.0.0.1:1") or (err) { << true }
    << false
}
fn invalid_socket() bool {
    _ := net.conn_read(-1, 1) or (err) { << true }
    << false
}
fn probe() int {
    port := net.lookup_port("tcp", "http") or >>
    protocol := net.lookup_protocol("tcp") or >>
    if port != 80 { << 2 }
    if protocol != 6 { << 3 }
    if !invalid_network() || !invalid_socket() { << 4 }
    println("network contracts passed")
    << 0
}
fn main() int {
    << probe() or (err) { eprintln(err.msg())
        << 1 }
}
'''

HTTP_EVENT_SET = r'''@main
#net
#net/http
fn serve_task(lfd int, srv_done chan int) {
    _ := http.serve_listener(lfd, fn(c http.Context) {
        c.text(200, "pong:" + c.path()) or (err) { << }
    })
    srv_done <- 1
}
fn client_worker(base_url string, base_seq int, out chan int) {
    $c := http.new_client()
    c.set_timeout(5000000000)
    $ok := 0
    for i in 0:8 {
        path := "/r/" + str(base_seq + i)
        resp := c.get(base_url + path) or (err) {
            out <- -1
            <<
        }
        if resp.status_code() != 200 || resp.body() != "pong:" + path {
            out <- -2
            <<
        }
        ok += 1
    }
    out <- ok
}
fn try_listen(addr string) int {
    << net.listen(addr) or (err) { << -1 }
}
fn main() int {
    $port := 23401
    $lfd := -1
    $tries := 0
    while lfd < 0 && tries < 64 {
        addr := "127.0.0.1:" + str(port)
        lfd = try_listen(addr + "")
        if lfd < 0 {
            port += 1
            tries += 1
        }
    }
    if lfd < 0 {
        eprintln("no loopback port")
        << 1
    }
    srv_done := chan int{cap: 1}
    xu serve_task(lfd, srv_done)
    base_url := "http://127.0.0.1:" + str(port)
    out := chan int{cap: 8}
    for w in 0:8 {
        xu client_worker(base_url + "", w * 8, out)
    }
    $total := 0
    for _ in 0:8 {
        v := <-out
        if v < 0 { << 2 }
        total += v
    }
    net.conn_close(lfd) or (err) { << 3 }
    if <-srv_done != 1 { << 4 }
    if total != 64 { << 5 }
    println("http event set passed")
    << 0
}
'''


HTTP_PENDING_UPLOAD = r'''@main
#net
#net/http
#os
fn upload(c http.Context) {
    body := c.body()
    for i in 0:body.len {
        if body[i] != 120 {
            c.text(400, "bad body") or (err) { << }
            <<
        }
    }
    c.text(200, str(body.len)) or (err) { << }
}
fn main() int {
    args := os.args()
    $options := http.server_options()
    options.max_connections = 8
    options.max_buffer_bytes = 32768
    options.read_timeout_ns = 3000000000
    options.sync_handlers = args[1] == "sync"
    lfd := net.listen("127.0.0.1:0") or (err) { << 1 }
    println(net.socket_local_addr(lfd))
    http.serve_listener_with_options(lfd, upload, options) or (err) { << 2 }
    << 0
}
'''


def check_http_pending(binary: Path, work: Path, env: dict[str, str], sync: bool) -> None:
    def request(size: int, connection: str = "close") -> bytes:
        return (f"POST /upload HTTP/1.1\r\nHost: localhost\r\n"
                f"Content-Length: {size}\r\nConnection: {connection}\r\n\r\n").encode()

    def response(stream, size: int) -> None:
        status = stream.readline()
        if not status.startswith(b"HTTP/1.1 200 "):
            raise AssertionError(f"Unexpected HTTP status {status!r}")
        headers = {}
        for line in iter(stream.readline, b"\r\n"):
            name, separator, value = line.partition(b":")
            if not separator:
                raise AssertionError(f"Malformed HTTP header {line!r}")
            headers[name.lower()] = value.strip()
        content = stream.read(int(headers[b"content-length"]))
        if content != str(size).encode():
            raise AssertionError(f"Unexpected response body {content!r}")

    mode = "sync" if sync else "async"
    with subprocess.Popen([str(binary), mode], cwd=work, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        try:
            startup = Timer(15, child.kill)
            startup.start()
            try:
                address = child.stdout.readline().strip()
            finally:
                startup.cancel()
            port = int(address.rsplit(b":", 1)[1])

            def dial():
                return socket.create_connection(("127.0.0.1", port), timeout=12)

            def send_upload(size: int) -> None:
                with dial() as sock, sock.makefile("rb") as stream:
                    head = request(size)
                    sock.sendall(head[:-3])
                    sock.sendall(head[-3:] + b"x" * (size // 2))
                    sock.sendall(b"x" * (size - size // 2))
                    response(stream, size)

            def expect_close(sock) -> None:
                try:
                    if sock.recv(1):
                        raise AssertionError("Incomplete request received a response")
                except (ConnectionAbortedError, ConnectionResetError):
                    pass

            if not sync:
                send_upload(12288)
                with dial() as sock, sock.makefile("rb") as stream:
                    sock.sendall(b"POST /upload HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
                                 b"Transfer-Encoding: chunked\r\n\r\n5\r\nxx")
                    sock.sendall(b"xxx\r\n3\r\nxxx\r\n0\r\n\r\n")
                    response(stream, 8)
                # The payload fits the logical limit. Growing a pending buffer
                # to hold it would exceed the limit while the old one is live.
                with dial() as sock:
                    try:
                        sock.sendall(request(24576) + b"x" * 24576)
                        if sock.recv(1):
                            raise AssertionError("Request exceeded the pending-buffer growth budget")
                    except ConnectionResetError:
                        pass
                with dial() as sock:
                    started = time.monotonic()
                    sock.sendall(request(12000) + b"x" * 8192)
                    expect_close(sock)
                    if time.monotonic() - started < 1.0:
                        raise AssertionError("Incomplete request closed before its intake timeout")
                for _ in range(3):
                    with dial() as sock:
                        sock.sendall(request(12000) + b"x" * 8192)
                        sock.shutdown(socket.SHUT_WR)
                        expect_close(sock)

                # Each partial upload fits alone. Keeping all six unfinished
                # forces the listener to enforce its shared 32 KiB budget.
                with ExitStack() as pending:
                    started = time.monotonic()
                    peers = [pending.enter_context(dial()) for _ in range(6)]
                    partial = request(7001) + b"x" * 7000
                    for peer in peers:
                        try:
                            peer.sendall(partial)
                        except (ConnectionAbortedError, ConnectionResetError):
                            pass
                    remaining = max(0.0, started + 2.0 - time.monotonic())
                    readable, _, _ = select.select(peers, [], [], remaining)
                    if not readable or time.monotonic() >= started + 3.0:
                        raise AssertionError("Shared pending-buffer budget did not reject a peer before its timeout")
                    for peer in peers:
                        if peer not in readable:
                            try:
                                peer.shutdown(socket.SHUT_WR)
                            except (ConnectionAbortedError, ConnectionResetError):
                                pass
                            except OSError as error:
                                if error.errno not in (errno.ENOTCONN, getattr(errno, "WSAENOTCONN", errno.ENOTCONN)):
                                    raise
                        expect_close(peer)
                send_upload(12288)

            if os.name != "nt":
                with dial() as sock, sock.makefile("rb") as stream:
                    sock.sendall(request(3, "keep-alive") + b"xxx" + request(4) + b"xxxx")
                    response(stream, 3)
                    response(stream, 4)
                send_upload(12288)
        finally:
            if child.poll() is None:
                child.terminate()
            _, stderr = child.communicate(timeout=10)
            if stderr:
                raise AssertionError(f"HTTP pending fixture wrote to stderr {stderr!r}")
    print(f"PASS net_http_pending_budget/{mode}/{native_target()} (executed)", flush=True)


def checked_run(command: list[str], *, cwd: Path, env: dict[str, str], expected: bytes) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=45)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{command}: runtime timeout; stdout={error.stdout!r}, stderr={error.stderr!r}") from error
    if result.returncode != 0 or result.stdout != expected or result.stderr:
        raise RuntimeError(f"{command}: exit={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}")


HTTP_CLIENT_BUFFER = r'''@main
#net/http
#os
#strconv
#strings

fn valid_body(data &string, size int) bool {
    if data.len != size { << false }
    for i in 0:data.len {
        if (data[i] & 255) != i % 251 { << false }
    }
    << true
}

fn get_error(client $&http.Client, url string) string {
    _ := client.get(url) or (err) { << err.msg() }
    << ""
}

fn main() int {
    args := os.args()
    base := args[1] + ""
    $client := http.new_client()
    client.set_timeout(30000000000)
    client.insecure_skip_verify = true
    client.max_response_bytes = strconv.atoi(&args[2]) or (err) { << 6 }
    first := client.get(base + "/fixed") or (err) { << 7 }
    if first.status_code != 200 || !valid_body(&first.body, 16384) || !client.has_idle_connection() { << 1 }
    client.max_response_bytes = 9223372036854775807
    chunked := client.get(base + "/chunked") or (err) { << 8 }
    if chunked.status_code != 200 || !valid_body(&chunked.body, 12288) { << 2 }
    client.max_response_bytes = strconv.atoi(&args[3]) or (err) { << 9 }
    limit_failure := get_error($&client, base + "/over-limit")
    if !strings.contains(&limit_failure, "message too large") || client.has_idle_connection() { << 3 }
    client.max_response_bytes = 0
    short_failure := get_error($&client, base + "/truncated")
    if short_failure.len == 0 || client.has_idle_connection() { << 4 }
    fresh := client.get(base + "/fresh") or (err) { << 10 }
    if fresh.status_code != 200 || !valid_body(&fresh.body, 8192) || !valid_body(&first.body, 16384) { << 5 }
    client.close_idle_connections()
    println("HTTP client buffer passed")
    << 0
}
'''


def check_http_client_buffer(binary: Path, work: Path, env: dict[str, str],
                             context: ssl.SSLContext | None = None) -> None:
    def payload(size: int) -> bytes:
        return (bytes(range(251)) * ((size + 250) // 251))[:size]

    def fixed(size: int, connection: str = "close") -> bytes:
        return (f"HTTP/1.1 200 OK\r\nContent-Length: {size}\r\nConnection: {connection}\r\n\r\n".encode()
                + payload(size))

    first = fixed(16384, "keep-alive")
    over_limit = fixed(16384)
    chunks = payload(12288)
    chunked = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
               + b"".join(b"1000\r\n" + chunks[i:i + 4096] + b"\r\n" for i in range(0, len(chunks), 4096))
               + b"0\r\n\r\n")
    fresh = fixed(8192) if context else b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + payload(8192)
    sessions = (
        (("/fixed", first), ("/chunked", chunked)),
        (("/over-limit", over_limit),),
        (("/truncated", fixed(16384)[:-8192]),),
        (("/fresh", fresh),),
    )

    def peer(listener: socket.socket) -> None:
        for exchanges in sessions:
            with ExitStack() as sockets:
                raw = sockets.enter_context(listener.accept()[0])
                raw.settimeout(20)
                conn = sockets.enter_context(context.wrap_socket(raw, server_side=True)) if context else raw
                stream = sockets.enter_context(conn.makefile("rb"))
                for path, response in exchanges:
                    request = stream.readline()
                    if not request.startswith(f"GET {path} ".encode()):
                        raise AssertionError(f"Expected GET {path}, received {request!r}")
                    for line in iter(stream.readline, b"\r\n"):
                        if not line:
                            raise AssertionError("Incomplete HTTP request")
                    conn.sendall(response)

    scheme = "https" if context else "http"
    with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as peers:
        listener.settimeout(20)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        address = f"{scheme}://127.0.0.1:{listener.getsockname()[1]}"
        future = peers.submit(peer, listener)
        checked_run([str(binary), address, str(len(first)), str(len(over_limit) - 1)],
                    cwd=work, env=env, expected=b"HTTP client buffer passed\n")
        future.result(timeout=20)
    print(f"PASS net_http_client_buffer/{scheme}/{native_target()} (executed)", flush=True)


WINDOWS_MEMORY = r'''@main
#net
#net/poller
#net/stream
fn checkpoint(label string) {
    println(label)
    os_fd_read(0, 1) or (err) { <<< 1 }
}
fn empty_lengths(s string) int {
    joined := s + s
    bytes := s.bytes()
    runes := s.runes()
    src := [1, 2, 3]
    empty := src[1:1]
    << joined.len + bytes.len + runes.len + empty.len
}
fn worker(start chan int, done chan int) {
    _ := <-start
    done <- 1
}
fn wave(inspect bool) int {
    start := chan int{cap: 0}
    done := chan int{cap: 32}
    for i in 0:32 { xu worker(start, done) }
    if inspect { checkpoint("active") }
    close(start)
    $sum := 0
    for i in 0:32 { sum += <-done }
    << sum
}
fn churn(p $&poller.Poller, n int) {
    for i in 0:n {
        id := p.add(stream.from_tcp(net.closed_conn()))
        if !p.remove(id) { <<< 5 }
    }
}
fn main() {
    checkpoint("start")
    empty := ""
    $sum := 0
    for i in 0:200000 { sum += empty_lengths(empty) }
    if sum != 0 { <<< 2 }
    checkpoint("empty")
    if wave(true) != 32 { <<< 3 }
    checkpoint("idle")
    if wave(false) != 32 { <<< 4 }
    checkpoint("idle again")
    $p := poller.new()
    churn($&p, 1024)
    checkpoint("poller warm")
    churn($&p, 65536)
    checkpoint("poller churn")
    if p.count() != 0 { <<< 6 }
}
'''


def check_windows_memory(binary: Path, work: Path, env: dict[str, str]) -> None:
    import ctypes
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("page_faults", wintypes.DWORD),
            ("working_set_and_pool", ctypes.c_size_t * 8),
            ("private_usage", ctypes.c_size_t),
        ]

    class MemoryRegion(ctypes.Structure):
        _fields_ = [
            ("base", ctypes.c_void_p),
            ("allocation", ctypes.c_void_p),
            ("allocation_protect", wintypes.DWORD),
            ("partition_id", wintypes.WORD),
            ("size", ctypes.c_size_t),
            ("state", wintypes.DWORD),
            ("protect", wintypes.DWORD),
            ("type", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_memory = kernel32.K32GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    query = kernel32.VirtualQueryEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MemoryRegion), ctypes.c_size_t]
    query.restype = ctypes.c_size_t

    def guarded_stacks(handle: int) -> set[int]:
        stack_size = 1024**2
        guard_size = 16 * 1024
        mem_reserve, mem_commit, page_readwrite = 0x2000, 0x1000, 4
        stacks = set()
        guard = None
        address = 0
        region = MemoryRegion()
        while query(handle, address, ctypes.byref(region), ctypes.sizeof(region)):
            base = region.base or 0
            # A Xu stack is a reserved guard followed by writable pages in
            # the same allocation.
            if guard is not None and guard == region.allocation and base == guard + guard_size:
                if region.state == mem_commit and region.protect == page_readwrite and region.size == stack_size - guard_size:
                    stacks.add(guard)
            guard = None
            if region.state == mem_reserve and region.size == guard_size and base == region.allocation:
                guard = base
            address = base + region.size
        return stacks

    with subprocess.Popen(
        [str(binary)], cwd=work, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) as child:
        # Each marker holds the process at a known point until we sample it.
        timer = Timer(20, child.kill)
        timer.start()
        try:
            usage: dict[bytes, int] = {}
            stacks: dict[bytes, set[int]] = {}
            handle = int(child._handle)
            for marker in (
                b"start\n", b"empty\n", b"active\n", b"idle\n", b"idle again\n",
                b"poller warm\n", b"poller churn\n",
            ):
                line = child.stdout.readline()
                if line != marker:
                    raise AssertionError(f"expected {marker!r}, got {line!r}")
                counters = MemoryCounters()
                counters.size = ctypes.sizeof(counters)
                if not get_memory(handle, ctypes.byref(counters), counters.size):
                    raise ctypes.WinError(ctypes.get_last_error())
                usage[marker] = counters.private_usage
                stacks[marker] = guarded_stacks(handle)
                child.stdin.write(b"x")
                child.stdin.flush()
            out, err = child.communicate(timeout=10)
            if child.returncode != 0 or out or err:
                raise AssertionError(f"memory workload exited {child.returncode}: {out!r} {err!r}")
        finally:
            timer.cancel()
            if child.poll() is None:
                child.kill()

    start_bytes, empty_bytes, idle_bytes = usage[b"start\n"], usage[b"empty\n"], usage[b"idle\n"]
    if empty_bytes - start_bytes > 12 * 1024**2 or idle_bytes - empty_bytes > 16 * 1024**2:
        raise AssertionError(
            f"excess private commit growth: start={start_bytes}, empty={empty_bytes}, idle={idle_bytes}"
        )
    baseline = stacks[b"start\n"]
    active = stacks[b"active\n"] - baseline
    idle = stacks[b"idle\n"] - baseline
    idle_again = stacks[b"idle again\n"] - baseline
    if len(active) != 32 or len(idle) != 8 or not idle <= active or len(idle_again) != 8:
        raise AssertionError(
            f"unexpected guarded stack counts: active={len(active)}, idle={len(idle)}, idle again={len(idle_again)}"
        )
    poller_growth = usage[b"poller churn\n"] - usage[b"poller warm\n"]
    if poller_growth > 4 * 1024**2:
        raise AssertionError(f"Poller grew by {poller_growth} private bytes after warm-up")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--target", required=True, choices=TARGETS)
    args = parser.parse_args()
    if args.target != native_target():
        parser.error(f"native execution required: host={native_target()}, requested={args.target}")
    compiler = str(args.compiler.resolve())
    env = compiler_env()
    # Windows can retain mappings briefly after process exit.
    from test_windows_workers import WindowsTemporaryDirectory
    with WindowsTemporaryDirectory(prefix="xu-platform-") as temporary:
        work = Path(temporary)
        env.update(XU_CACHE=str(work / "cache"), HOME=str(work), USERPROFILE=str(work))

        def build(name: str, source: str, *flags: str) -> Path:
            path = work / f"{name}.xu"
            path.write_text(source, encoding="utf-8", newline="\n")
            binary = work / (name + (".exe" if os.name == "nt" else ""))
            subprocess.run([compiler, "build", *flags, str(path), "--target", args.target, "-o", str(binary)],
                           cwd=work, env=env, check=True, timeout=180)
            return binary

        def run(name: str, binary: Path, *arguments: str, expected: str) -> None:
            checked_run([str(binary), *arguments], cwd=work, env=env, expected=(expected + "\n").encode())
            print(f"PASS {name}/{args.target} (executed)", flush=True)

        run("library", build("library", LIBRARY), expected="library passed")
        run("optimized_code", build("optimized_code", OPTIMIZED_CODE), expected="optimized code passed")
        run("optimized_code/no-opt", build("unoptimized_code", OPTIMIZED_CODE, "--no-opt"),
            expected="optimized code passed")
        run("chan_parallel/channel_blocking_string", build("concurrency", CONCURRENCY), expected="concurrency passed")
        if os.name == "nt":
            check_windows_memory(build("memory", WINDOWS_MEMORY), work, env)
            print(f"PASS empty_allocations/guarded_task_stack_cache/poller_churn/{args.target} (executed)", flush=True)
        run("net_http_event_set", build("http_event_set", HTTP_EVENT_SET), expected="http event set passed")
        upload = build("http_pending_upload", HTTP_PENDING_UPLOAD)
        check_http_pending(upload, work, env, sync=False)
        if os.name != "nt":
            check_http_pending(upload, work, env, sync=True)
        client = build("http_client_buffer", HTTP_CLIENT_BUFFER)
        check_http_client_buffer(client, work, env)
        run("net_interfaces", build("interfaces", INTERFACES), expected="interfaces passed")
        run("net_platform_files/net_unsupported_contract", build("net_contract", NET_CONTRACT), expected="network contracts passed")
        from platform_crypto_cases import SOURCE as CRYPTO, write_fixtures
        write_fixtures(work)
        env["SSL_CERT_FILE"] = str(work / "root.pem")
        crypto = build("crypto", CRYPTO)
        run("crypto_ecdsa/crypto_x509_chain/crypto_x509_pool", crypto, "crypto", expected="ECDSA and X509 chain/pool passed")
        run("crypto_sha256_parallel/crypto_rsa_pss", crypto, "parallel", expected="Parallel SHA256 and RSA-PSS passed")
        run("crypto_tls_pipe", crypto, "pipe", expected="TLS pipe passed")
        stream = build("stream", STREAM)
        udp = build("udp", UDP)
        with ThreadPoolExecutor(max_workers=1) as peers:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
            context.set_ciphers("ECDHE-ECDSA-AES128-GCM-SHA256")
            context.set_ecdh_curve("prime256v1")
            context.load_cert_chain(work / "leaf-chain.pem", work / "leaf-key.pem")
            with socket.socket() as listener:
                listener.settimeout(15)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                future = peers.submit(tls_peer, listener, context)
                run("crypto_tls_ecdhe_interop", crypto, "interop", f"127.0.0.1:{listener.getsockname()[1]}", expected="TLS ECDHE interop passed")
                future.result(timeout=20)
            check_http_client_buffer(client, work, env, context)
            for family, network, host in ((socket.AF_INET, "tcp4", "127.0.0.1"), (socket.AF_INET6, "tcp6", "::1")):
                # Missing IPv6 is a hard failure, including on CI runners.
                with socket.socket(family) as listener:
                    listener.settimeout(15)
                    listener.bind((host, 0))
                    listener.listen(1)
                    port = listener.getsockname()[1]
                    address = f"[{host}]:{port}" if family == socket.AF_INET6 else f"{host}:{port}"
                    future = peers.submit(stream_peer, listener)
                    run("net_" + network + "_loopback", stream, network, address, expected="stream passed")
                    future.result(timeout=20)
            for mode in ("connected", "unconnected"):
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
                    peer.settimeout(15)
                    peer.bind(("127.0.0.1", 0))
                    future = peers.submit(udp_peer, peer)
                    run("net_udp_" + mode, udp, f"127.0.0.1:{peer.getsockname()[1]}", mode, expected="udp passed")
                    future.result(timeout=20)
            if os.name == "nt":
                print("::notice::SKIP net_unix_loopback: Xu Windows Unix-domain sockets are unsupported; executing rejection contract instead", flush=True)
                run("net_unsupported_contract", build("unix_rejected", WINDOWS_UNIX), expected="unsupported Unix socket rejected")
            else:
                # Keep below the macOS sockaddr_un path limit, independent of TMPDIR.
                with tempfile.TemporaryDirectory(prefix="xu-unix-", dir="/tmp") as unix_dir:
                    address = str(Path(unix_dir) / "s")
                    with socket.socket(socket.AF_UNIX) as listener:
                        listener.settimeout(15)
                        listener.bind(address)
                        listener.listen(1)
                        future = peers.submit(stream_peer, listener)
                        run("net_unix_loopback", stream, "unix", address, expected="stream passed")
                        future.result(timeout=20)
    return 0


def stream_peer(listener: socket.socket) -> None:
    with listener.accept()[0] as conn:
        conn.settimeout(15)
        data = b""
        while len(data) < len(b"Xu stream probe"):
            part = conn.recv(128)
            if not part:
                raise AssertionError("stream ended before request")
            data += part
        assert data == b"Xu stream probe", data
        conn.sendall(data)


def udp_peer(peer: socket.socket) -> None:
    data, address = peer.recvfrom(128)
    assert data == b"Xu datagram", data
    peer.sendto(data, address)


def tls_peer(listener: socket.socket, context: ssl.SSLContext) -> None:
    with listener.accept()[0] as raw:
        raw.settimeout(15)
        with context.wrap_socket(raw, server_side=True) as conn:
            data = conn.recv(128)
            assert data == b"Xu stream probe", data
            conn.sendall(data)


if __name__ == "__main__":
    raise SystemExit(main())
