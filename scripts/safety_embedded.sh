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
BOUNDARY_LANE=oracle
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"

GEN1=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --gen1=*) GEN1="${1#*=}" ;;
        *) echo "safety_embedded: unknown arg $1"; exit 1 ;;
    esac
    shift
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { echo "safety_embedded: FAIL ($1)"; exit 1; }

if [ -z "$GEN1" ]; then
    cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu --bin xu \
        || fail "bootstrap xu build failed"
    XU="$BOOTSTRAP_ROOT/target/debug/xu"
    XU=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$XU" \
        "$ROOT/scripts/xu_host_seed.sh") || fail "bootstrap compiler is not the canonical frozen primer"
    . ./scripts/gen1_sources.sh || fail "could not load scripts/gen1_sources.sh"
    # Primer -O0: bootstrap auto/O1 still miscompiles the full compiler.
    "$XU" -O0 $GEN1_SRCS -o "$tmp/gen1.xin" || fail "bootstrap could not compile Gen1"
    GEN1="$tmp/gen1.xin"
    echo "safety_embedded: lane=oracle (frozen bootstrap); generated Gen1 is parity-only, not product evidence" >&2
else
    # An explicit Gen1 is a comparison input only; do not let its embedded
    # results be read as hosted product evidence.
    echo "safety_embedded: lane=parity (explicit --gen1; not product evidence)" >&2
fi
chmod +x "$GEN1"

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
        if "$GEN1" build "$prog" --target "$target" -o "$tmp/${n}_${target}.elf" \
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
    if "$GEN1" build "$prog" --target thumbv7em-none -o "$tmp/${n}_thumb.elf" \
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
    "$GEN1" build tests/embedded/chan_xu_basic.xu --target thumbv7em-none -o "$tmp/chan_thumb.elf" \
        || fail "gen1 thumb chan_xu_basic build"
    run_qemu_arm "$tmp/chan_thumb.elf" "10" "chan_xu_basic"
    "$GEN1" build tests/embedded/irq_xu.xu --target thumbv7em-none -o "$tmp/irq_thumb.elf" \
        || fail "gen1 thumb irq_xu build"
    run_qemu_arm "$tmp/irq_thumb.elf" "7" "irq_xu"
else
    echo "SKIP thumb (no qemu-system-arm)"
    skip=$((skip + 2))
fi

if command -v qemu-system-riscv32 >/dev/null 2>&1; then
    "$GEN1" build tests/embedded/chan_xu_basic.xu --target riscv32imac-none -o "$tmp/chan_rv32.elf" \
        || fail "gen1 rv32 chan_xu_basic build"
    run_qemu_rv32 "$tmp/chan_rv32.elf" "10" "chan_xu_basic"
    "$GEN1" build tests/embedded/irq_xu.xu --target riscv32imac-none -o "$tmp/irq_rv32.elf" \
        || fail "gen1 rv32 irq_xu build"
    run_qemu_rv32 "$tmp/irq_rv32.elf" "7" "irq_xu"
else
    echo "SKIP rv32 chan_xu_basic + irq_xu (no qemu-system-riscv32)"
    skip=$((skip + 2))
fi

echo "safety_embedded: PASS=$pass SKIP=$skip FAIL=$fail_n (compile_checks=$compile_n)"
[ "$fail_n" -eq 0 ] || fail "$fail_n embedded lane(s) failed"
