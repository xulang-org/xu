#!/usr/bin/env bash
# Freestanding memory-safety gate (E3/S8):
#
#   §1 compile-only: embedded negatives rejected; hosted-only ISR/MMIO mirrors compile
#   §2 QEMU runtime: chan_xu_basic (10), irq_xu (7) on Thumb + RV32 chan
#
# Skips QEMU lanes cleanly when qemu-system-arm / qemu-system-riscv32 are absent.
#
# Usage:
#   scripts/safety_embedded.sh
#   scripts/safety_embedded.sh --gen1=/path/to/gen1
set -euo pipefail
# Machine-readable boundary role: embedded safety oracle evidence.
BOUNDARY_LANE=product
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
export XU_ROOT="$ROOT"
cd "$ROOT"

GEN1=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*|--gen1=*) GEN1="${1#*=}" ;;
        *) echo "safety_embedded: unknown arg $1"; exit 1 ;;
    esac
    shift
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { echo "safety_embedded: FAIL ($1)"; exit 1; }

HOST_SEED_RESOLVER="$ROOT/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$ROOT/scripts/run_product_compiler.sh"
GEN1=$(XU_SEED="$GEN1" "$HOST_SEED_RESOLVER")
compile_product() {
    "$PRODUCT_COMPILER_RUNNER" "$GEN1" build "$@"
}
echo "safety_embedded: lane=product compiler=$GEN1" >&2

# Compiler permissions are validated by the resolver.


pass=0
skip=0
fail_n=0
compile_n=0

# §1a — must be rejected at compile time on freestanding targets.
EMBED_NEG="volatile_mmio_outside irq_heap_call"
for n in $EMBED_NEG; do
    prog="tests/gen1/safety/embedded/${n}.xu"
    [ -f "$prog" ] || fail "missing embedded negative $prog"
    for target in thumbv7em-none riscv32imac-none; do
        if compile_product "$prog" --target "$target" -o "$tmp/${n}_${target}.elf" \
            >"$tmp/${n}_${target}.out" 2>"$tmp/${n}_${target}.err"; then
            echo "FAIL $n/$target (expected compile error)"
            fail_n=$((fail_n + 1))
        else
            echo "PASS $n/$target (compile rejected)"
            pass=$((pass + 1))
            compile_n=$((compile_n + 1))
        fi
    done
done

# §1b — hosted safety negatives must compile on Thumb (inverse profile).
EMBED_HOSTED_MIRROR="volatile_hosted raise_irq_hosted"
for n in $EMBED_HOSTED_MIRROR; do
    prog="tests/gen1/safety/${n}.xu"
    [ -f "$prog" ] || fail "missing hosted mirror $prog"
    if compile_product "$prog" --target thumbv7em-none -o "$tmp/${n}_thumb.elf" \
        >"$tmp/${n}_thumb.out" 2>"$tmp/${n}_thumb.err"; then
        echo "PASS $n/thumb (hosted-only API allowed on embedded)"
        pass=$((pass + 1))
        compile_n=$((compile_n + 1))
    else
        echo "FAIL $n/thumb (expected compile success on embedded)"
        sed 's/^/  /' "$tmp/${n}_thumb.err"
        fail_n=$((fail_n + 1))
    fi
done

run_qemu_arm() {
    local elf=$1 want=$2 name=$3
    out=$(python3 - "$elf" <<'PY'
import subprocess, sys
p = subprocess.Popen(["qemu-system-arm","-M","mps2-an386","-nographic","-kernel",sys.argv[1]],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try: out, _ = p.communicate(timeout=8)
except subprocess.TimeoutExpired: p.kill(); out, _ = p.communicate()
print(out.decode("utf-8", "replace"))
PY
)
    case "$out" in *"$want"*) echo "PASS $name (thumb/$want)"; pass=$((pass + 1)) ;;
        *) echo "FAIL $name (thumb missing '$want')"; echo "$out"; fail_n=$((fail_n + 1)) ;;
    esac
}

run_qemu_rv32() {
    local elf=$1 want=$2 name=$3
    out=$(python3 - "$elf" <<'PY'
import subprocess, sys
p = subprocess.Popen(["qemu-system-riscv32","-M","virt","-nographic","-bios","none","-kernel",sys.argv[1]],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try: out, _ = p.communicate(timeout=8)
except subprocess.TimeoutExpired: p.kill(); out, _ = p.communicate()
print(out.decode("utf-8", "replace"))
PY
)
    case "$out" in *"$want"*) echo "PASS $name (rv32/$want)"; pass=$((pass + 1)) ;;
        *) echo "FAIL $name (rv32 missing '$want')"; echo "$out"; fail_n=$((fail_n + 1)) ;;
    esac
}

if command -v qemu-system-arm >/dev/null 2>&1; then
    compile_product tests/embedded/chan_xu_basic.xu --target thumbv7em-none -o "$tmp/chan_thumb.elf" \
        || fail "gen1 thumb chan_xu_basic build"
    run_qemu_arm "$tmp/chan_thumb.elf" "10" "chan_xu_basic"
    compile_product tests/embedded/irq_xu.xu --target thumbv7em-none -o "$tmp/irq_thumb.elf" \
        || fail "gen1 thumb irq_xu build"
    run_qemu_arm "$tmp/irq_thumb.elf" "7" "irq_xu"
else
    echo "SKIP thumb (no qemu-system-arm)"
    skip=$((skip + 2))
fi

if command -v qemu-system-riscv32 >/dev/null 2>&1; then
    compile_product tests/embedded/chan_xu_basic.xu --target riscv32imac-none -o "$tmp/chan_rv32.elf" \
        || fail "gen1 rv32 chan_xu_basic build"
    run_qemu_rv32 "$tmp/chan_rv32.elf" "10" "chan_xu_basic"
    compile_product tests/embedded/irq_xu.xu --target riscv32imac-none -o "$tmp/irq_rv32.elf" \
        || fail "gen1 rv32 irq_xu build"
    run_qemu_rv32 "$tmp/irq_rv32.elf" "7" "irq_xu"
else
    echo "SKIP rv32 chan_xu_basic + irq_xu (no qemu-system-riscv32)"
    skip=$((skip + 2))
fi

echo "safety_embedded: PASS=$pass SKIP=$skip FAIL=$fail_n (compile_checks=$compile_n)"
[ "$fail_n" -eq 0 ] || fail "$fail_n embedded lane(s) failed"
