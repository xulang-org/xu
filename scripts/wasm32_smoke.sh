#!/usr/bin/env bash
# Exercise optimized MIR lookup and the descending i64 frame ABI in Node.
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

for mode in opt no-opt; do
    flags=()
    if [ "$mode" = no-opt ]; then flags=(--no-opt); fi
    for name in fold add mul calls; do
        "$compiler" build "$tmp/$name.xu" --target wasm32 ${flags[@]+"${flags[@]}"} -o "$tmp/$name.wasm"
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
done
echo "wasm32_smoke: PASS (8 builds, 54 frame calls)"
