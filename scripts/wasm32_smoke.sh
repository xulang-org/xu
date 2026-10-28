#!/usr/bin/env bash
# Exercise integer/f64 lowering and the descending i64 frame ABI in Node.
set -euo pipefail
cd "$(dirname "$0")/.."
export XU_ROOT="$PWD"
export XU_STDLIB_ROOT="$PWD/src"
compiler=${XU:-"$PWD/bin/xu"}
command -v node >/dev/null
test -x "$compiler"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/xu-wasm32-smoke.XXXXXX")
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/fold.xu" <<'EOF'
@main
fn main() int { r := 6 * 7
    << r }
EOF
cat > "$tmp/add.xu" <<'EOF'
@main
fn add(a int, b int) int { << a + b }
fn main() int { << add(40, 2) }
EOF
cat > "$tmp/mul.xu" <<'EOF'
@main
pub fn mul(a int, b int) int { mut r := a * b
    << r }
fn main() int { << 0 }
EOF
cat > "$tmp/calls.xu" <<'EOF'
@main
pub fn recur(a int, b int) int {
    if a == 0 { << b }
    << recur(a - 1, b + 2)
}
fn main() int { << recur(20, 2) }
EOF

cat > "$tmp/f64.xu" <<'EOF'
@main
pub fn fp_add(a f64, b f64) f64 { << a + b }
pub fn fp_sub(a f64, b f64) f64 { << a - b }
pub fn fp_mul(a f64, b f64) f64 { << a * b }
pub fn fp_div(a f64, b f64) f64 { << a / b }
pub fn fp_eq(a f64, b f64) bool { << a == b }
pub fn fp_ne(a f64, b f64) bool { << a != b }
pub fn fp_lt(a f64, b f64) bool { << a < b }
pub fn fp_le(a f64, b f64) bool { << a <= b }
pub fn fp_gt(a f64, b f64) bool { << a > b }
pub fn fp_ge(a f64, b f64) bool { << a >= b }
pub fn fp_neg(a f64) f64 { << -a }
pub fn fp_from_int(a int) f64 { << f64(a) }
pub fn fp_to_int(a f64) int { << int(a) }
pub fn fp_branch(a f64, b f64) int {
    if a < b { << 1 }
    << 0
}
fn main() int {
    a := fp_add(1.5, 2.25)
    << int((-a * 8.0 - 2.0) / 2.0)
}
EOF

# Keep field/element values dynamic so optimization cannot fold the updates.
cat > "$tmp/f64_rmw.xu" <<'EOF'
@main
struct FloatBox { guard int
    f f64 }
pub fn fp_field_add(x f64, y f64) f64 {
    mut box := FloatBox{guard: 17, f: x}
    fp_field_update(mut &box, y)
    if box.guard != 18 { <<< 1 }
    << box.f
}
fn fp_field_update(box &mut FloatBox, y f64) {
    box.f += y
    box.guard += 1
}
pub fn fp_field_literal(x f64) f64 {
    mut box := FloatBox{guard: 17, f: x}
    fp_field_update_literal(mut &box)
    << box.f
}
fn fp_field_update_literal(box &mut FloatBox) {
    box.f += 1.5
    box.f *= 2.0
    box.f -= 0.5
}
pub fn fp_index_mul(a &mut []f64, i int, y f64) f64 {
    a[i] *= y
    << a[i]
}
pub fn fp_index_literal(a &mut []f64, i int) f64 {
    a[i] += 1.5
    a[i] *= 2.0
    a[i] -= 0.5
    << a[i]
}
pub fn fp_index_store(a &mut []f64, i int, y f64) f64 {
    a[i] = y
    << a[i]
}
pub fn fp_buffer_field(a &mut []FloatBox, i int, y f64) f64 {
    a[i].f += y
    << a[i].f
}
pub fn int_index_add(a &mut []int, i int, y int) int {
    a[i] += y
    << a[i]
}
fn main() int { << 0 }
EOF

cat > "$tmp/check.js" <<'EOF'
const assert = require('node:assert/strict');
const fs = require('node:fs');
const [file, name, expected, ...args] = process.argv.slice(2);
const moduleBytes = fs.readFileSync(file);
assert.ok(WebAssembly.validate(moduleBytes), `${file}: invalid WebAssembly`);
const instance = new WebAssembly.Instance(new WebAssembly.Module(moduleBytes), {});
const memory = new DataView(instance.exports.memory.buffer);
const A = 4096, R = 8192;
// Reuse the instance to exercise frame/stack restoration between calls.
for (let i = 0; i < 3; ++i) {
    args.forEach((v, j) => memory.setBigInt64(A - 8 * j, BigInt(v), true));
    memory.setBigInt64(R, -123456789n, true);
    instance.exports[name](A, R);
    assert.equal(memory.getBigInt64(R, true), BigInt(expected), `${file}: ${name}`);
}
console.log(`PASS ${name}(${args.join(', ')}) => ${expected}`);
EOF

cat > "$tmp/check_f64.js" <<'EOF'
const assert = require('node:assert/strict');
const fs = require('node:fs');
const bytes = fs.readFileSync(process.argv[2]);
const rmwBytes = fs.readFileSync(process.argv[3]);
assert.ok(WebAssembly.validate(bytes), 'invalid f64 WebAssembly');
const instance = new WebAssembly.Instance(new WebAssembly.Module(bytes), {});
const memory = new DataView(instance.exports.memory.buffer);
const A = 4096, R = 8192;
let calls = 0;
function check(name, inputTypes, outputType, args, expected) {
    // Typed DataView access checks the raw slot ABI without a numeric cast.
    for (let i = 0; i < 3; ++i) {
        args.forEach((v, j) => {
            if (inputTypes[j] === 'f64') memory.setFloat64(A - 8 * j, v, true);
            else memory.setBigInt64(A - 8 * j, v, true);
        });
        memory.setBigInt64(R, -123456789n, true);
        instance.exports[`${name}_frame`](A, R);
        const result = outputType === 'f64'
            ? memory.getFloat64(R, true) : memory.getBigInt64(R, true);
        // strict equality distinguishes +0/-0 and accepts NaN results.
        assert.equal(result, expected, `${name}(${args.join(', ')})`);
        ++calls;
    }
}
const pairs = [
    [5.5, 2.25], [-5.5, 2.25], [2.25, 5.5], [2.25, 2.25],
    [0, -0], [-0, 0], [1, 0], [-1, 0], [0, 0],
    [Infinity, 2], [-Infinity, Infinity], [Infinity, Infinity],
    [NaN, 2], [2, NaN], [NaN, NaN],
];
const arithmetic = {
    add: (a, b) => a + b, sub: (a, b) => a - b,
    mul: (a, b) => a * b, div: (a, b) => a / b,
};
const comparisons = {
    eq: (a, b) => a === b, ne: (a, b) => a !== b,
    lt: (a, b) => a < b, le: (a, b) => a <= b,
    gt: (a, b) => a > b, ge: (a, b) => a >= b,
};
for (const [op, fn] of Object.entries(arithmetic)) {
    for (const args of pairs) check(`fp_${op}`, ['f64', 'f64'], 'f64', args, fn(...args));
}
for (const [op, fn] of Object.entries(comparisons)) {
    for (const args of pairs) check(`fp_${op}`, ['f64', 'f64'], 'int', args, BigInt(fn(...args)));
}
for (const args of pairs) check('fp_branch', ['f64', 'f64'], 'int', args, BigInt(args[0] < args[1]));
for (const a of [5.5, -5.5, 0, -0, Infinity, -Infinity, NaN]) {
    check('fp_neg', ['f64'], 'f64', [a], -a);
}
const min = -(1n << 63n), max = (1n << 63n) - 1n;
for (const a of [0n, 42n, -42n, 4294967296n, 9007199254740993n, min, max]) {
    check('fp_from_int', ['int'], 'f64', [a], Number(a));
}
for (const a of [0, -0, 42.75, -42.75, 4294967296.5, -4294967296.5,
                 2 ** 63 - 1024, -(2 ** 63), 2 ** 63, -(2 ** 64), Infinity, -Infinity, NaN]) {
    const expected = Number.isNaN(a) ? 0n : a >= 2 ** 63 ? max
        : a <= -(2 ** 63) ? min : BigInt(Math.trunc(a));
    check('fp_to_int', ['f64'], 'int', [a], expected);
}
// The borrowed array argument points at a descending three-slot descriptor;
// its elements live in ascending memory. Sentinel neighbors catch bad offsets.
const rmw = new WebAssembly.Instance(new WebAssembly.Module(rmwBytes), {});
const rmwMemory = new DataView(rmw.exports.memory.buffer);
const DESC = 12288, DATA = 16384;
let rmwCalls = 0;
function checkRmw(name, args, expected, indexed = false, struct = false, integer = false) {
    for (let repeat = 0; repeat < 3; ++repeat) {
        const width = struct ? 16 : 8;
        rmwMemory.setBigInt64(DESC, BigInt(DATA), true);
        rmwMemory.setBigInt64(DESC - 8, 3n, true);
        rmwMemory.setBigInt64(DESC - 16, 3n, true);
        for (let i = 0; i < 3; ++i) {
            rmwMemory.setBigInt64(DATA + i * width, 17n, true);
            if (struct) rmwMemory.setFloat64(DATA + i * width + 8, 23.25, true);
        }
        const target = DATA + width + (struct ? 8 : 0);
        if (indexed) {
            if (integer) rmwMemory.setBigInt64(target, args[0], true);
            else rmwMemory.setFloat64(target, args[0], true);
            rmwMemory.setBigInt64(A, BigInt(DESC), true);
            rmwMemory.setBigInt64(A - 8, 1n, true);
            if (args.length > 1) {
                if (integer) rmwMemory.setBigInt64(A - 16, args[1], true);
                else rmwMemory.setFloat64(A - 16, args[1], true);
            }
        } else args.forEach((x, i) => rmwMemory.setFloat64(A - i * 8, x, true));
        rmwMemory.setBigInt64(R, -123456789n, true);
        rmw.exports[`${name}_frame`](A, R);
        const read = address => integer ? rmwMemory.getBigInt64(address, true)
            : rmwMemory.getFloat64(address, true);
        assert.equal(read(R), expected, name);
        if (indexed) {
            assert.equal(read(target), expected, `${name}: stored value`);
            assert.equal(rmwMemory.getBigInt64(DATA, true), 17n);
            assert.equal(rmwMemory.getBigInt64(DATA + 2 * width, true), 17n);
            if (struct) assert.equal(rmwMemory.getBigInt64(DATA + width, true), 17n);
        }
        ++rmwCalls;
    }
}
for (const [x, y] of pairs) {
    checkRmw('fp_field_add', [x, y], x + y);
    checkRmw('fp_index_mul', [x, y], x * y, true);
    checkRmw('fp_buffer_field', [x, y], x + y, true, true);
    checkRmw('fp_index_store', [x, y], y, true);
}
for (const x of [2.25, -5.5, 0, -0, Infinity, -Infinity, NaN]) {
    checkRmw('fp_field_literal', [x], (x + 1.5) * 2 - 0.5);
    checkRmw('fp_index_literal', [x], (x + 1.5) * 2 - 0.5, true);
}
checkRmw('int_index_add', [40n, 2n], 42n, true, false, true);
console.log(`PASS f64 field/index RMW and bit-preserving load/store (${rmwCalls} frame calls)`);
check('main', [], 'int', [], -16n);
console.log(`PASS f64 arithmetic/comparison/negation/casts/branches/literals (${calls} frame calls)`);
EOF

for mode in opt no-opt; do
    flags=()
    if [ "$mode" = no-opt ]; then flags=(--no-opt); fi
    for name in fold add mul calls f64 f64_rmw; do
        "$compiler" build "$tmp/$name.xu" --target wasm32 "${flags[@]}" -o "$tmp/$name.wasm"
    done
    echo "wasm32_smoke: $mode"
    node "$tmp/check.js" "$tmp/fold.wasm" main_frame 42
    node "$tmp/check.js" "$tmp/add.wasm" main_frame 42
    node "$tmp/check.js" "$tmp/mul.wasm" main_frame 0
    node "$tmp/check.js" "$tmp/mul.wasm" mul_frame 42 6 7
    node "$tmp/check.js" "$tmp/mul.wasm" mul_frame -42 -6 7
    node "$tmp/check.js" "$tmp/mul.wasm" mul_frame 4294967296 2147483648 2
    node "$tmp/check.js" "$tmp/calls.wasm" main_frame 42
    node "$tmp/check.js" "$tmp/calls.wasm" recur_frame 16 3 10
    node "$tmp/check.js" "$tmp/calls.wasm" recur_frame -9 0 -9
    node "$tmp/check_f64.js" "$tmp/f64.wasm" "$tmp/f64_rmw.wasm"
done
echo "wasm32_smoke: PASS (12 builds, integer and f64 frame ABI/RMW)"
