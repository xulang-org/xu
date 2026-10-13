#!/usr/bin/env bash
# E2: compile freestanding hello and run it on QEMU mps2-an386.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
# BOUNDARY: this freestanding target probe intentionally exercises the frozen
# bootstrap oracle; its ELF/QEMU result is not hosted product evidence.
LANE="oracle"
echo "e2_qemu_hello: lane=oracle (bootstrap primer diagnostic; non-product evidence)" >&2
BIN="$BOOTSTRAP_ROOT/target/debug/xu"
if [ ! -x "$BIN" ] && [ ! -x "$BOOTSTRAP_ROOT/target/debug/xu.exe" ] && \
   [ ! -x "$BOOTSTRAP_ROOT/target/release/xu" ] && \
   [ ! -x "$BOOTSTRAP_ROOT/target/release/xu.exe" ]; then
  (cd "$BOOTSTRAP_ROOT" && cargo build -p xu)
fi
for candidate in \
  "$BOOTSTRAP_ROOT/target/debug/xu" \
  "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
  "$BOOTSTRAP_ROOT/target/release/xu" \
  "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
  if [ -x "$candidate" ]; then
    BIN="$candidate"
    break
  fi
done
if ! BIN=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$BIN" \
  "${ROOT}/scripts/xu_host_seed.sh"); then
  echo "e2_qemu_hello: compiler is not the canonical frozen primer" >&2
  exit 1
fi
SRC="${ROOT}/tests/embedded/hello.xu"
OUT="${TMPDIR:-/tmp}/xu_e2_hello.elf"
"$BIN" "$SRC" --target thumbv7em-none -o "$OUT"
echo "wrote $OUT"
if ! command -v qemu-system-arm >/dev/null 2>&1; then
  echo "qemu-system-arm not found; ELF only"
  exit 0
fi
# Cortex-M reset + UART0; process does not exit (WFI).
python3 - "$OUT" <<'PY'
import subprocess, sys
elf = sys.argv[1]
p = subprocess.Popen(
    ["qemu-system-arm", "-M", "mps2-an386", "-nographic", "-kernel", elf],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
try:
    out, _ = p.communicate(timeout=2)
except subprocess.TimeoutExpired:
    p.kill()
    out, _ = p.communicate()
text = out.decode("utf-8", "replace")
sys.stdout.write(text)
if "hello" not in text:
    sys.stderr.write("E2: QEMU UART missing hello\n")
    sys.exit(1)
print("E2 QEMU ok")
PY
