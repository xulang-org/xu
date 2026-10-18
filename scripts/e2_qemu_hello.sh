#!/usr/bin/env bash
# E2: compile freestanding hello and run it on QEMU mps2-an386.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
export XU_ROOT="$ROOT"
BIN=$("$ROOT/scripts/xu_host_seed.sh")
echo "e2_qemu_hello: lane=product compiler=$BIN" >&2
SRC="${ROOT}/tests/embedded/hello.xu"
OUT="${TMPDIR:-/tmp}/xu_e2_hello.elf"
"$ROOT/scripts/run_product_compiler.sh" "$BIN" build "$SRC" --target thumbv7em-none -o "$OUT"
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
