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
check('main', [], 'int', [], -16n);
console.log(`PASS f64 arithmetic/comparison/negation/casts/branches/literals (${calls} frame calls)`);
EOF

for mode in opt no-opt; do
    flags=()
    if [ "$mode" = no-opt ]; then flags=(--no-opt); fi
    for name in fold add mul calls f64; do
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
    node "$tmp/check_f64.js" "$tmp/f64.wasm"
done
echo "wasm32_smoke: PASS (10 builds, integer and f64 frame ABI)"
