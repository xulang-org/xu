#!/usr/bin/env bash
# Bootstrap gate (M6b2/M6c): build the Xu-written compiler with the Rust
# bootstrap compiler and verify it end to end:
#   1. hello: gen1 emits a working macOS arm64 executable whose bytes are
#      identical to the Rust reference generator (M6b2-s1);
#   2. self-parse: gen1's front end parses every src/cmd/compile and src/xu
#      source file (its own sources, M6b2-s2);
#   3. stats consistency: for a sample of fixtures (generics, interfaces,
#      match, slices, Result/?, borrows, ...), gen1's token/node counts are
#      identical to `xu --dump-stats` (front-end equivalence);
#   4. negative cases: gen1 reports the same diagnostics as bootstrap;
#   5. safety negatives: bootstrap and gen1 reject memory-unsafe programs;
#   6. programs: bootstrap/gen1 observable results agree, including loud OOB
#      (`#net` / net_* / http_* stdlib tests are skipped — not compiler layer);
#   6b. fmt: xu --fmt and gen1 fmt are byte-identical on tests/fmt/*.in.xu;
#   6c. test runner (M32): --test/-run/-v/--cover outputs byte-identical;
#   6d. DWARF (M33): --debug line tables byte-identical + subprogram parity;
#   6e. warnings (M36): static-safety warnings byte-identical, exit unaffected;
#   7. fixed point: gen1 builds gen2, gen2 builds gen3, gen3 confirms gen4,
#      and gen3 == gen4; Gen2 is recorded as a deliberate warm-up output.
#      The confirmed Gen4 then builds sibling tools (xu-fmt, xu-desktop,
#      xu-doctor, xu-map, xu-doc).
#
# Stage 2 (bootstrap/FROZEN.md): this script is the primer *oracle*, not the
# product build. `make xu` uses a hosted seed and does not call primer.
# `--oracle=bootstrap` is the same gate with an explicit banner.
# Watermark emitter is injected by the primer compiler; hosted xu does not generate it.
set -euo pipefail

# Machine-readable boundary role: frozen-primer oracle evidence only.
BOUNDARY_LANE=oracle

source scripts/test_lib.sh
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"
export XU_STDLIB_ROOT="$ROOT/src"

ORACLE=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --oracle=bootstrap|--oracle)
            ORACLE=bootstrap
            ;;
        -h|--help)
            echo "usage: gen1_test.sh [--oracle=bootstrap]"
            echo "  Frozen primer oracle (hello bytes, safety, gen3==gen4 after warm-up)."
            echo "  Product build is make xu (hosted seed)."
            exit 0
            ;;
        *)
            echo "gen1_test: unknown arg $1 (want --oracle=bootstrap)" >&2
            exit 1
            ;;
    esac
    shift
done
if [ -n "$ORACLE" ]; then
    echo "=== oracle=$ORACLE (frozen primer; bootstrap/FROZEN.md) ==="
    echo "Product chain is make xu (hosted seed). Watermark inject is primer-only."
fi

# Child programs read TMPDIR via os.temp_dir(); a stale file path (e.g. from
# accidentally teeing a log to $TMPDIR) breaks exec/ui fixtures.
if [ -z "${TMPDIR:-}" ] || [ ! -d "${TMPDIR}" ]; then
    export TMPDIR="${TMPDIR:-/tmp}"
    if [ ! -d "$TMPDIR" ]; then
        export TMPDIR=/tmp
    fi
fi

# python3 scripts/check_ncall_registry.py || { echo "gen1_test: FAIL (ncall registry)"; exit 1; }
. ./scripts/lang_gate_skip.sh

cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu --bin xu --bin gen1_ref \
    || { echo "bootstrap build failed"; exit 1; }
XU="$BOOTSTRAP_ROOT/target/debug/xu"
# Keep the oracle input tied to this checkout's physical Gen0 artifact.  The
# resolver's strict mode rejects symlinked components and external aliases,
# while leaving the generated Gen1/Gen1-ref binaries unconstrained.
XU=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$XU" \
    "$ROOT/scripts/xu_host_seed.sh") || {
    echo "gen1_test: bootstrap compiler is not the canonical frozen primer" >&2
    exit 1
}
GEN1_REF="$BOOTSTRAP_ROOT/target/debug/gen1_ref"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fail() { echo "gen1_test: FAIL ($1)"; exit 1; }

# `src/xu/*` packages are loaded via import. Self-parse still lists those
# files so dump-stats covers them; build does not.
. ./scripts/gen1_sources.sh || fail "could not load scripts/gen1_sources.sh"

# Primer injects compiler extra in memory; tree sources have no hook.
GEN1_PARSE="$GEN1_SRCS $GEN1_AST $GEN1_SCANNER $GEN1_PARSER $GEN1_PRINTER $GEN1_FORMAT $GEN1_TYPES"

# ===== Build Gen1 with the bootstrap compiler (oracle only) =====
# Primer stays -O0: bootstrap auto/O1 still miscompiles the full compiler
# (ArrPush fast-path can treat a string payload as []int data; Gen1 then
# SIGSEGV on safety negatives such as any_mut). Product `make xu` does not
# use primer. Hosted hops re-inject from the payload compiled into the seed.
"$XU" -O0 $GEN1_SRCS -o "$tmp/gen1.xin" \
    || fail "bootstrap could not compile Gen1"

# `gen1 fmt` execs sibling xu-fmt (not hosted). The product install puts
# it next to bin/xu; the gate's gen1 lives in $tmp.
if [ -x bin/xu-fmt ]; then
    cp bin/xu-fmt "$tmp/xu-fmt"
    chmod +x "$tmp/xu-fmt"
fi

# Mark must answer on bootstrap and on Gen1 (via injected runtime).
mark=$("$XU" "@@") || fail "bootstrap @@ failed"
[ "$mark" = "xu830103" ] || fail "bootstrap @@ printed '$mark'"
mark=$("$tmp/gen1.xin" "@@") || fail "gen1 @@ failed"
[ "$mark" = "xu830103" ] || fail "gen1 @@ printed '$mark'"

# ===== 1. hello: emitter + byte comparison (M6b2-s1) =====
"$tmp/gen1.xin" hello "$tmp/hello_xu" \
    || fail "xu hello exited non-zero"
chmod +x "$tmp/hello_xu"
got=$("$tmp/hello_xu") || fail "hello_xu exited non-zero"
[ "$got" = "Hello from Xu!" ] || fail "hello_xu printed '$got'"
"$GEN1_REF" "$tmp/hello_ref" || fail "gen1_ref exited non-zero"
cmp -s "$tmp/hello_xu" "$tmp/hello_ref" \
    || { fail "hello_xu and hello_ref differ"; }

# ===== 2. self-parse: gen1 parses its own sources (M6b2-s2) =====
"$tmp/gen1.xin" parse $GEN1_PARSE > "$tmp/self_parse.out" \
    || fail "gen1 could not parse its own sources"
# ... and the numbers must match the bootstrap front end exactly.
"$XU" --dump-stats $GEN1_PARSE > "$tmp/self_parse.ref" \
    || fail "xu --dump-stats failed on compiler sources"
cmp -s "$tmp/self_parse.out" "$tmp/self_parse.ref" \
    || { diff "$tmp/self_parse.out" "$tmp/self_parse.ref"; fail "self-parse stats differ from bootstrap"; }

# ===== 3. stats consistency on fixture samples =====
SAMPLES="fib_recursive generic_identity generic_multi_use generic_struct generic_nested interface_dispatch match_int result_propagate slice_basic slice_bounds array_slice_copy struct_mut_receiver borrow_mut_param array_struct for_range bitwise_ops string_concat"
for f in $SAMPLES; do
    a=$("$XU" --dump-stats "tests/fixtures/$f/main.xu" 2>&1) \
        || fail "xu --dump-stats failed on $f"
    b=$("$tmp/gen1.xin" parse "tests/fixtures/$f/main.xu" 2>&1) \
        || fail "gen1 parse failed on $f"
    [ "$a" = "$b" ] || { echo "  bootstrap: $a"; echo "  gen1:      $b"; fail "stats differ on $f"; }
done

# ===== 4. negative cases: same error position as the bootstrap =====
for bad in tests/gen1/bad_*.xu; do
    # These commands are expected to fail.  Keep errexit/pipefail from
    # aborting the gate before we can compare their diagnostics.
    a=$("$XU" --dump-stats "$bad" 2>&1 >/dev/null | head -1 || true)
    [ -n "$a" ] || fail "bootstrap unexpectedly accepted $bad"
    b=$("$tmp/gen1.xin" parse "$bad" 2>&1 >/dev/null | head -1 || true)
    [ -n "$b" ] || fail "gen1 unexpectedly accepted $bad"
    # Both ends print `path:line:col: error: message` verbatim (M22/M177).
    [ "$a" = "$b" ] || { echo "  bootstrap: $a"; echo "  gen1:      $b"; fail "error message/position differs on $bad"; }
    case "$a" in
        *:*:*:*) ;;
        *) fail "parse error missing path:line:col on $bad: $a" ;;
    esac
done

# ===== 5. semantic safety negatives + runtime loud probes =====
scripts/safety_test.sh --xu="$XU" --gen1="$tmp/gen1.xin" \
    || fail "safety_test failed"

# ===== 5b. multi-file error attribution (imported file) =====
set +e
"$XU" tests/gen1/attr/main.xu -o "$tmp/attr_boot.xin" >"$tmp/attr_bo" 2>"$tmp/attr_be"
attr_boot_rc=$?
"$tmp/gen1.xin" build tests/gen1/attr/main.xu -o "$tmp/attr_gen1.xin" >"$tmp/attr_go" 2>"$tmp/attr_ge"
attr_gen1_rc=$?
set -e
[ "$attr_boot_rc" != "0" ] || fail "bootstrap accepted broken multi-file program"
[ "$attr_gen1_rc" != "0" ] || fail "gen1 accepted broken multi-file program"
cmp -s "$tmp/attr_be" "$tmp/attr_ge" \
    || { diff "$tmp/attr_be" "$tmp/attr_ge"; fail "multi-file error attribution differs"; }

# ===== 5c. freestanding codegen smoke (QEMU, skipped when absent) =====
# Gen1's Thumb (mps2-an386) and RV32 (virt) backends must produce ELFs that
# print hello on the respective board — E7.
if command -v qemu-system-arm >/dev/null 2>&1; then
    "$tmp/gen1.xin" build tests/embedded/hello.xu --target thumbv7em-none -o "$tmp/e7_thumb.elf" \
        || fail "gen1 could not build thumbv7em-none hello"
    out=$(python3 - "$tmp/e7_thumb.elf" <<'PY'
import subprocess, sys
p = subprocess.Popen(["qemu-system-arm","-M","mps2-an386","-nographic","-kernel",sys.argv[1]],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try: out, _ = p.communicate(timeout=5)
except subprocess.TimeoutExpired: p.kill(); out, _ = p.communicate()
print(out.decode("utf-8", "replace"))
PY
)
    case "$out" in *hello*) ;; *) echo "$out"; fail "gen1 thumb hello missing in QEMU";; esac
fi
if command -v qemu-system-riscv32 >/dev/null 2>&1; then
    "$tmp/gen1.xin" build tests/embedded/hello.xu --target riscv32imac-none -o "$tmp/e7_rv32.elf" \
        || fail "gen1 could not build riscv32imac-none hello"
    out=$(python3 - "$tmp/e7_rv32.elf" <<'PY'
import subprocess, sys
p = subprocess.Popen(["qemu-system-riscv32","-M","virt","-nographic","-bios","none","-kernel",sys.argv[1]],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try: out, _ = p.communicate(timeout=5)
except subprocess.TimeoutExpired: p.kill(); out, _ = p.communicate()
print(out.decode("utf-8", "replace"))
PY
)
    case "$out" in *hello*) ;; *) echo "$out"; fail "gen1 riscv hello missing in QEMU";; esac
fi

# ===== 6. build: gen1 compiles real programs (M6b2-s3) =====
# For every tests/gen1/programs/*.xu: compile with BOTH the bootstrap and
# gen1, run both, and compare stdout + exit code. Bootstrap and Gen1 use
# independent lowering, so their general program bytes are not a contract.
for prog in tests/gen1/programs/*.xu; do
    n=$(basename "$prog" .xu)
    if lang_gate_skip_program "$prog"; then
        echo "gen1_test: SKIP $n (stdlib/net package; not language-compiler gate)"
        continue
    fi
    "$XU" "$prog" -o "$tmp/${n}_boot.xin" || fail "bootstrap could not compile $prog"
    "$tmp/gen1.xin" build "$prog" -o "$tmp/${n}_gen1.xin" || fail "gen1 could not build $prog"
    chmod +x "$tmp/${n}_boot.xin" "$tmp/${n}_gen1.xin"
    run_args=()
    [ "$n" = "p14_args" ] && run_args=("probe")
    [ "$n" = "p15_fileio" ] && run_args=("$tmp/${n}.out")
    set +e
    if [ "${#run_args[@]}" -eq 0 ]; then
        # macOS still ships Bash 3.2; under `set -u`, expanding an empty
        # array as "${run_args[@]}" raises "unbound variable".
        "$tmp/${n}_boot.xin" > "$tmp/${n}_ob" 2> "$tmp/${n}_eb"; eb=$?
        "$tmp/${n}_gen1.xin" > "$tmp/${n}_og" 2> "$tmp/${n}_eg"; eg=$?
    else
        "$tmp/${n}_boot.xin" "${run_args[@]}" > "$tmp/${n}_ob" 2> "$tmp/${n}_eb"; eb=$?
        "$tmp/${n}_gen1.xin" "${run_args[@]}" > "$tmp/${n}_og" 2> "$tmp/${n}_eg"; eg=$?
    fi
    set -e
    cmp -s "$tmp/${n}_ob" "$tmp/${n}_og" || fail "output differs on $n"
    [ "$eb" = "$eg" ] || fail "exit code differs on $n ($eb vs $eg)"
    case "$n" in
        p17_negative_index|p18_slice_negative|p19_slice_reverse|p20_div_overflow_intmin|p21_div_zero_loud|p22_div_overflow_intmin_mod|p_array_slice_oob)
            [ "$eg" = "1" ] || fail "$n did not fail loudly"
            [ -s "$tmp/${n}_eg" ] || fail "$n produced no runtime diagnostic"
            ;;
        p30_chan_send_closed|p31_chan_close_parked_sender)
            [ "$eg" = "1" ] || fail "$n did not fail loudly"
            ;;
    esac
done

# ===== 6a. fixture corpus through Gen1 (double-ended coverage) =====
# tests/fixtures/* is the richest corpus in the tree; it long ran only on the
# Rust bootstrap, so Gen1-only defects (wrong multi-arg results, missing
# rejections) slipped past the self-host fixed-point gate — even Gen3 == Gen4
# (after the deliberate Gen2 warm-up) does not catch them because Gen1's bugs
# are deterministic. Divergences still being worked through are
# listed in docs/audit/GEN1_FIXTURE_KNOWN_FAIL.txt; that list can only shrink.
scripts/run_fixtures.sh --xu="$tmp/gen1.xin" --sub=build --label=gen1 \
    --known-fail=docs/audit/GEN1_FIXTURE_KNOWN_FAIL.txt --skip-net --skip-require > "$tmp/gen1_fixtures.log" 2>&1 \
    || { grep -E '^(FAIL|FIXED) ' -A3 "$tmp/gen1_fixtures.log" | head -40; fail "gen1 fixture corpus"; }
gen1_fx_line=$(grep '^fixtures\[gen1\]' "$tmp/gen1_fixtures.log" || echo "fixtures[gen1]: ?")
echo "gen1_test: $gen1_fx_line"

# ===== 6b. fmt: bootstrap ≡ gen1, golden + idempotent (M20) =====
fmt_n=0
for sample in tests/fmt/*.in.xu; do
    n=$(basename "$sample" .in.xu)
    "$XU" --fmt "$sample" > "$tmp/fmt_${n}_boot" || fail "xu --fmt $sample"
    "$tmp/gen1.xin" fmt "$sample" > "$tmp/fmt_${n}_gen1" || fail "gen1 fmt $sample"
    cmp -s "$tmp/fmt_${n}_boot" "$tmp/fmt_${n}_gen1" \
        || { diff -u "$tmp/fmt_${n}_boot" "$tmp/fmt_${n}_gen1" | head -20; fail "fmt boot/gen1 differ on $n"; }
    if [ -f "tests/fmt/${n}.expected.xu" ]; then
        cmp -s "$tmp/fmt_${n}_boot" "tests/fmt/${n}.expected.xu" \
            || { diff -u "tests/fmt/${n}.expected.xu" "$tmp/fmt_${n}_boot" | head -20; fail "fmt golden mismatch $n"; }
    fi
    "$XU" --fmt "$tmp/fmt_${n}_boot" > "$tmp/fmt_${n}_boot2" || fail "xu --fmt idempotent $n"
    cmp -s "$tmp/fmt_${n}_boot" "$tmp/fmt_${n}_boot2" || fail "fmt not idempotent $n"
    fmt_n=$((fmt_n + 1))
done
[ "$fmt_n" -gt 0 ] || fail "no tests/fmt/*.in.xu samples"

# ===== 6c. test runner parity (M32) =====
# tests/lang/*.xu compiled with --test by BOTH compilers: stdout, stderr and
# exit code must match byte-for-byte; -run filtering and --cover dumps too.
for sample in tests/lang/test.partial.xu tests/lang/test.skip.xu tests/lang/test.borrow_string.xu tests/lang/test.skipnow.xu tests/lang/test.errorf.xu; do
    n=$(basename "$sample" .xu)
    run_pat=""
    [ "$n" = "test.skip" ] && run_pat="-run test_kept"
    set +e
    "$XU" "$sample" --test > "$tmp/t_${n}_boot.out" 2> "$tmp/t_${n}_boot.err"
    boot_rc=$?
    set -e
    "$tmp/gen1.xin" test "$sample" -o "$tmp/t_${n}_gen1.xin" \
        || fail "gen1 test $n (build)"
    chmod +x "$tmp/t_${n}_gen1.xin"
    set +e
    "$tmp/t_${n}_gen1.xin" > "$tmp/t_${n}_gen1.out" 2> "$tmp/t_${n}_gen1.err"
    gen1_rc=$?
    set -e
    [ "$boot_rc" = "$gen1_rc" ] || fail "test $n exit code boot=$boot_rc gen1=$gen1_rc"
    cmp -s "$tmp/t_${n}_boot.out" "$tmp/t_${n}_gen1.out" \
        || { diff -u "$tmp/t_${n}_boot.out" "$tmp/t_${n}_gen1.out" | head -20; fail "test $n stdout differs"; }
    cmp -s "$tmp/t_${n}_boot.err" "$tmp/t_${n}_gen1.err" \
        || { diff -u "$tmp/t_${n}_boot.err" "$tmp/t_${n}_gen1.err" | head -20; fail "test $n stderr differs"; }
    # -run filter parity
    set +e
    "$XU" "$sample" --test $run_pat > "$tmp/t_${n}_run_boot.out" 2> "$tmp/t_${n}_run_boot.err"
    boot_rc=$?
    set -e
    "$tmp/gen1.xin" test "$sample" $run_pat -o "$tmp/t_${n}_run_gen1.xin" \
        || fail "gen1 test -run $n (build)"
    chmod +x "$tmp/t_${n}_run_gen1.xin"
    set +e
    "$tmp/t_${n}_run_gen1.xin" > "$tmp/t_${n}_run_gen1.out" 2> "$tmp/t_${n}_run_gen1.err"
    gen1_rc=$?
    set -e
    [ "$boot_rc" = "$gen1_rc" ] || fail "test -run $n exit code boot=$boot_rc gen1=$gen1_rc"
    cmp -s "$tmp/t_${n}_run_boot.out" "$tmp/t_${n}_run_gen1.out" \
        || { diff -u "$tmp/t_${n}_run_boot.out" "$tmp/t_${n}_run_gen1.out" | head -20; fail "test -run $n stdout differs"; }
    # -v parity (stdout only; ns values are runtime-dependent, so compare the
    # shape: both must contain ' ok ' and the same summary line).
    "$XU" "$sample" --test -v $run_pat > "$tmp/t_${n}_v_boot.out" 2>/dev/null || true
    "$tmp/gen1.xin" test "$sample" -v $run_pat -o "$tmp/t_${n}_v_gen1.xin" \
        || fail "gen1 test -v $n (build)"
    chmod +x "$tmp/t_${n}_v_gen1.xin"
    "$tmp/t_${n}_v_gen1.xin" > "$tmp/t_${n}_v_gen1.out" 2>/dev/null || true
    tail -n 1 "$tmp/t_${n}_v_boot.out" > "$tmp/t_${n}_v_boot.sum"
    tail -n 1 "$tmp/t_${n}_v_gen1.out" > "$tmp/t_${n}_v_gen1.sum"
    cmp -s "$tmp/t_${n}_v_boot.sum" "$tmp/t_${n}_v_gen1.sum" \
        || fail "test -v $n summary differs"
    grep -q ' ok [0-9]*ns$' "$tmp/t_${n}_v_boot.out" || fail "test -v $n boot missing timing"
    grep -q ' ok [0-9]*ns$' "$tmp/t_${n}_v_gen1.out" || fail "test -v $n gen1 missing timing"
    # --cover parity (normal build, both dumps byte-identical; a normal
    # build needs a user main, so only main-bearing files take this lane)
    if [ "$n" = "test.partial" ]; then
        "$XU" "$sample" --cover -o "$tmp/t_${n}_cov_boot.xin" || fail "xu --cover $n"
        chmod +x "$tmp/t_${n}_cov_boot.xin"
        "$tmp/t_${n}_cov_boot.xin" > "$tmp/t_${n}_cov_boot.out" || fail "cov boot run $n"
        "$tmp/gen1.xin" build "$sample" --cover -o "$tmp/t_${n}_cov_gen1.xin" \
            || fail "gen1 build --cover $n"
        chmod +x "$tmp/t_${n}_cov_gen1.xin"
        "$tmp/t_${n}_cov_gen1.xin" > "$tmp/t_${n}_cov_gen1.out" || fail "cov gen1 run $n"
        cmp -s "$tmp/t_${n}_cov_boot.out" "$tmp/t_${n}_cov_gen1.out" \
            || { diff -u "$tmp/t_${n}_cov_boot.out" "$tmp/t_${n}_cov_gen1.out" | head -20; fail "--cover $n dumps differ"; }
    fi
done

# ===== 6d. DWARF parity (M33) =====
# `--debug` outputs: bootstrap ≡ gen1 for .debug_line (byte-normalized via
# llvm-dwarfdump text), abbrev and strings; .debug_info high_pc may differ by
# the pre-existing 132B helper-area codegen delta, so it is compared
# structurally (subprogram count). Default (no --debug) binaries must differ
# from their --debug counterparts (the flag actually does something).
#
# Gen1 currently forces `rc_on = false` in emit_program (Assembler rc_* field
# stores OOB on the Gen1 host). Compare both sides under --no-regcache so
# line addresses stay aligned until asm_set_i re-enables regcache.
LLVM_DWARFDUMP=$(command -v llvm-dwarfdump || command -v dwarfdump || true)
if [ -n "$LLVM_DWARFDUMP" ]; then
    for target in macos-arm64 linux-arm64; do
        "$XU" tests/fixtures/hello_string/main.xu --target "$target" --debug --no-regcache -o "$tmp/dbg_boot.xin" \
            || fail "xu --debug $target"
        "$tmp/gen1.xin" build tests/fixtures/hello_string/main.xu --target "$target" --debug --no-regcache -o "$tmp/dbg_gen1.xin" \
            || fail "gen1 build --debug $target"
        # `tail -n +2` drops dwarfdump's own header line, which embeds the
        # (different) input file names; the DWARF payload itself is compared.
        "$LLVM_DWARFDUMP" --debug-line "$tmp/dbg_boot.xin" | tail -n +2 > "$tmp/dbg_boot.line" \
            || fail "llvm-dwarfdump --debug-line $target boot"
        "$LLVM_DWARFDUMP" --debug-line "$tmp/dbg_gen1.xin" | tail -n +2 > "$tmp/dbg_gen1.line" \
            || fail "llvm-dwarfdump --debug-line $target gen1"
        cmp -s "$tmp/dbg_boot.line" "$tmp/dbg_gen1.line" \
            || { diff -u "$tmp/dbg_boot.line" "$tmp/dbg_gen1.line" | head -20; fail "--debug-line $target boot/gen1 differ"; }
        grep -q "main.xu" "$tmp/dbg_boot.line" || fail "--debug-line $target missing source file"
        "$LLVM_DWARFDUMP" --debug-info "$tmp/dbg_boot.xin" | grep -c "DW_TAG_subprogram" > "$tmp/dbg_boot.nsub"
        "$LLVM_DWARFDUMP" --debug-info "$tmp/dbg_gen1.xin" | grep -c "DW_TAG_subprogram" > "$tmp/dbg_gen1.nsub"
        cmp -s "$tmp/dbg_boot.nsub" "$tmp/dbg_gen1.nsub" \
            || fail "--debug-info $target subprogram count boot/gen1 differ"
        "$XU" tests/fixtures/hello_string/main.xu --target "$target" --no-regcache -o "$tmp/plain_boot.xin"
        cmp -s "$tmp/plain_boot.xin" "$tmp/dbg_boot.xin" && fail "--debug $target did not change bytes"
    done
else
    echo "gen1_test: llvm-dwarfdump not found; skipping 6d DWARF parity"
fi

# ===== 6e. warning parity (M36) =====
# Static-safety warnings (recursion / possible division by zero) must be
# byte-identical between the two compilers, and must not affect the exit
# code (both binaries run and print the same stdout).
"$XU" tests/fixtures/warn_recursive/main.xu -o "$tmp/wr_boot.xin" 2> "$tmp/wr_boot.err" \
    || fail "xu warn_recursive"
"$tmp/gen1.xin" build tests/fixtures/warn_recursive/main.xu -o "$tmp/wr_gen1.xin" 2> "$tmp/wr_gen1.err" \
    || fail "gen1 warn_recursive"
chmod +x "$tmp/wr_boot.xin" "$tmp/wr_gen1.xin"
cmp -s "$tmp/wr_boot.err" "$tmp/wr_gen1.err" \
    || { diff -u "$tmp/wr_boot.err" "$tmp/wr_gen1.err" | head -20; fail "warning stderr boot/gen1 differ"; }
grep -q "warning: recursive call cycle" "$tmp/wr_boot.err" || fail "warn_recursive missing warning"
"$tmp/wr_boot.xin" > "$tmp/wr_boot.out"; boot_rc=$?
"$tmp/wr_gen1.xin" > "$tmp/wr_gen1.out"; gen1_rc=$?
[ "$boot_rc" = "$gen1_rc" ] && [ "$boot_rc" = 0 ] || fail "warn_recursive exit codes differ"
cmp -s "$tmp/wr_boot.out" "$tmp/wr_gen1.out" || fail "warn_recursive stdout differs"
"$XU" tests/fixtures/warn_div_zero_var/main.xu -o "$tmp/wz_boot.xin" 2> "$tmp/wz_boot.err" \
    || fail "xu warn_div_zero_var"
"$tmp/gen1.xin" build tests/fixtures/warn_div_zero_var/main.xu -o "$tmp/wz_gen1.xin" 2> "$tmp/wz_gen1.err" \
    || fail "gen1 warn_div_zero_var"
chmod +x "$tmp/wz_boot.xin" "$tmp/wz_gen1.xin"
cmp -s "$tmp/wz_boot.err" "$tmp/wz_gen1.err" \
    || { diff -u "$tmp/wz_boot.err" "$tmp/wz_gen1.err" | head -20; fail "warn_div_zero_var stderr boot/gen1 differ"; }

# ===== 7. self-hosting fixed point (M6c) =====
echo "gen1_test: building Gen2, Gen3 and Gen4 fixed point (this is the slow stage)"
gen2_t0=$(date +%s)
"$tmp/gen1.xin" build --timings $GEN1_SRCS -o "$tmp/gen2.xin" 2>"$tmp/gen2.timings" \
    || fail "gen1 could not build gen2"
gen2_wall=$(( $(date +%s) - gen2_t0 ))
grep '^timings:' "$tmp/gen2.timings" | tail -1 > "$tmp/gen2.line" 2>/dev/null || true
echo "gen1_test: Gen2 build wall=${gen2_wall}s $(cat "$tmp/gen2.line" 2>/dev/null || true)"
perf_failed=0
if [ "${XU_BOUNDARY_CI:-0}" = 1 ]; then
  echo "gen1_test: compile timing recorded; pinned-host performance baseline remains local"
elif [[ -f docs/audit/bench_compile.baseline.txt ]]; then
  if ! python3 scripts/compile_baseline_identity.py docs/audit/bench_compile.baseline.txt; then
    perf_failed=1
  else
    base=$(grep '^gen1_wall=' docs/audit/bench_compile.baseline.txt | cut -d= -f2 || echo 0)
    gen2_total=$(grep -o 'total=[0-9]*ms' "$tmp/gen2.line" 2>/dev/null | cut -d= -f2 | tr -d 'ms' || echo 0)
    base_total=$(grep '^gen1_timings=' docs/audit/bench_compile.baseline.txt | grep -o 'total=[0-9]*ms' | cut -d= -f2 | tr -d 'ms' || echo 0)
    if [ "$gen2_total" -gt 0 ] && [ "$base_total" -gt 0 ]; then
      if awk -v b="$base_total" -v n="$gen2_total" 'BEGIN{ if (n>b*1.05) exit 1; else exit 0 }'; then
        echo "gen1_test: perf OK (gen2 total=${gen2_total}ms vs baseline ${base_total}ms; wall=${gen2_wall}s ref ${base}s)"
      else
        echo "gen1_test: PERF REGRESSION gen2 total ${gen2_total}ms > baseline ${base_total}ms + 5%"
        perf_failed=1
      fi
    elif awk -v b="$base" -v n="$gen2_wall" 'BEGIN{ if (b>0 && n>b*1.05) exit 1; else exit 0 }'; then
      echo "gen1_test: perf OK (gen2 ${gen2_wall}s vs baseline ${base}s)"
    else
      echo "gen1_test: PERF REGRESSION gen2 wall ${gen2_wall}s > baseline ${base}s + 5%"
      perf_failed=1
    fi
  fi
else
  echo "gen1_test: missing compile baseline; explicit calibration required"
  perf_failed=1
fi
chmod +x "$tmp/gen2.xin"
"$tmp/gen2.xin" build $GEN1_SRCS -o "$tmp/gen3.xin" \
    || fail "gen2 could not build gen3"
chmod +x "$tmp/gen3.xin"
"$tmp/gen3.xin" build $GEN1_SRCS -o "$tmp/gen4.xin" \
    || fail "gen3 could not build gen4"
chmod +x "$tmp/gen4.xin"
if cmp -s "$tmp/gen2.xin" "$tmp/gen3.xin"; then
  echo "gen1_test: warm-up already stable (Gen2 == Gen3)"
else
  echo "gen1_test: warm-up transition recorded (Gen2 != Gen3)"
fi
cmp -s "$tmp/gen3.xin" "$tmp/gen4.xin" \
    || { cmp -l "$tmp/gen3.xin" "$tmp/gen4.xin" | head -20; fail "fixed point not reached (gen3 != gen4)"; }
# Naming: Rust output is bootstrap; the self-hosted chain is gen1 (built by
# bootstrap), gen2 (by gen1), gen3 (by gen2), gen4 (by gen3); the confirmed
# fixed-point gen4 is the product, named xu.
cp "$tmp/gen4.xin" "$tmp/xu"
chmod +x "$tmp/xu"
"$tmp/xu" parse src/cmd/compile/main.xu > "$tmp/gen3_parse.out" \
    || fail "xu (gen4) sanity parse failed"
scripts/build_product_tools.sh "$tmp/xu" "$tmp" \
    || fail "gen4 could not build xu-fmt/xu-desktop/xu-doctor/xu-map/xu-doc"

# ===== 8. Confirmed hosted require: http:// download (M183) =====
python3 -m http.server 19883 --bind 127.0.0.1 --directory tests/fixtures/require_http/www >/dev/null 2>&1 &
http_pid=$!
ready=0
i=0
while [ "$i" -lt 40 ]; do
    if curl -fsS "http://127.0.0.1:19883/rempkg.xu" >/dev/null 2>&1; then
        ready=1
        break
    fi
    i=$((i + 1))
    sleep 0.05
done
[ "$ready" = "1" ] || { kill "$http_pid" 2>/dev/null || true; fail "M183 http.server did not start"; }
export XU_CACHE="$tmp/xu_cache_m183"
"$XU" tests/fixtures/require_http/main.xu -o "$tmp/req_http_boot.xin" \
    || { kill "$http_pid" 2>/dev/null || true; fail "bootstrap require_http"; }
cp -R tests/fixtures/require_http "$tmp/require_http_product"
python3 scripts/prepare_require_http_fixture.py "$tmp/require_http_product"
"$tmp/gen4.xin" build "$tmp/require_http_product/main.xu" -o "$tmp/req_http_gen1.xin" \
    || { kill "$http_pid" 2>/dev/null || true; fail "gen4 require_http"; }
chmod +x "$tmp/req_http_boot.xin" "$tmp/req_http_gen1.xin"
"$tmp/req_http_boot.xin" > "$tmp/req_http_ob"
"$tmp/req_http_gen1.xin" > "$tmp/req_http_og"
kill "$http_pid" 2>/dev/null || true
wait "$http_pid" 2>/dev/null || true
unset XU_CACHE
cmp -s "$tmp/req_http_ob" "$tmp/req_http_og" || fail "require_http stdout boot/gen1 differ"
[ "$(cat "$tmp/req_http_ob")" = "42" ] || fail "require_http stdout want 42"

# New dependency acquisition belongs to Xu. Cold Gen1 uses the frozen
# primer's older file ABI; replay every require fixture with confirmed Gen4.
scripts/run_fixtures.sh --xu="$tmp/gen4.xin" --sub=build --label=oracle-gen4 \
    --only-require > "$tmp/gen4_dependencies.log" 2>&1 \
    || { cat "$tmp/gen4_dependencies.log"; fail "confirmed hosted dependency fixtures"; }
echo "gen1_test: $(grep '^fixtures\[' "$tmp/gen4_dependencies.log")"

# A performance failure must not suppress the independent fixed-point and
# sibling-tool checks. Keep the same baseline/threshold and final failure.
if [ "$perf_failed" = 1 ]; then
    echo "gen1_test: fixed point and sibling tools PASS; performance gate FAIL"
    fail "performance regression on Gen2 self-compile"
fi

echo "gen1_test: PASS (hello byte-identical; self-parse + 16 fixture stats match; parser negatives match; $(ls tests/gen1/safety/*.xu | wc -l | tr -d ' ') safety negatives rejected; $(ls tests/gen1/programs/*.xu | wc -l | tr -d ' ') programs behavior-match; $gen1_fx_line; $fmt_n fmt samples boot≡gen1; test runner + -run/-v/--cover boot≡gen1 (M32); DWARF --debug line tables boot≡gen1 (M33); warnings boot≡gen1 (M36); gen3 == gen4 fixed point after Gen2 warm-up, gen4 installed name xu + sibling tools)"
