#!/usr/bin/env bash
# Perturbation self-host gate (T0.1 in OVERALL_OPTIMIZATION_PLAN_2026-09.md).
#
# The hosted compiler has been miscompiled several times by *adding* a
# function or a counter to one of its own sources (struct intern breaks, the
# checker's integer while loops index out of bounds).  Such bugs depend on
# declaration count/order, so the Gen3 == Gen4 fixed point cannot see them:
# a deterministic miscompile is self-consistent.  This gate perturbs the
# compiler sources in ways that must not change live behaviour and checks
# the compiler that results.
#
# For each round (deterministic --random-seed):
#   1. scripts/selfhost_perturb.py copies src/ and appends unused fns/structs
#      (shifting intern pool, fn numbering and struct tags) and swaps two
#      adjacent top-level fn blocks in a few compiler files;
#   2. SEED compiles the perturbed tree           -> P1
#   3. P1 compiles the *unperturbed* tree          -> X ; X must be byte-equal
#      to REF (what the unperturbed compiler produces from the same tree);
#   4. P1 compiles + runs a struct/int-loop/OOB smoke subset of tests/fixtures;
#   5. --full-chain: P1 -> P2 -> P3 -> P4 on the perturbed tree, cmp P3 P4.
#
# Usage:
#   scripts/selfhost_perturb.sh                       # seed bin/xu, 3 rounds
#   scripts/selfhost_perturb.sh --rounds=5 --random-seed=100
#   scripts/selfhost_perturb.sh --seed=/tmp/xu-p50/xu.xin --full-chain
#   scripts/selfhost_perturb.sh --files=src/cmd/compile/emit_ra_fp.xu,src/cmd/compile/emit_vec.xu
#   scripts/selfhost_perturb.sh --self-test          # prove the harness compiles the perturbed tree
#
# The seed is a hosted compiler resolved by xu_host_seed.sh.
# Perturbed candidates are isolated from the installed bin/xu.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
export XU_ROOT="$ROOT"
cd "$ROOT"
LANE=product
source scripts/test_lib.sh
. ./scripts/gen1_sources.sh

SEED_INPUT=""
ROUNDS=3
RSEED=1
FILES=""
NFILES=3
FNS=4
STRUCTS=2
REORDER=1
FULL_CHAIN=0
KEEP=0
SELF_TEST=0
HOP_TIMEOUT=${XU_PERTURB_HOP_TIMEOUT:-1800}
SMOKE='^(hello_string|struct_fields|struct_methods|struct_tag_overflow|struct_init_move|closure_basic|crypto_aes|field_arr_while_off|while_countdown|bounds_while_len|generic_nested|iface_box_user|enum_owning_match|matmul_tiny|nbody_pair_rmw|copy_index_loop|map_lang_basic|chan_xu_basic|err_index_kernel_oob|err_bounds_while_n)$'
while [ "$#" -gt 0 ]; do
    case "$1" in
        --seed=*) SEED_INPUT="${1#*=}" ;;
        --rounds=*) ROUNDS="${1#*=}" ;;
        --random-seed=*) RSEED="${1#*=}" ;;
        --files=*) FILES="${1#*=}" ;;
        --nfiles=*) NFILES="${1#*=}" ;;
        --fns=*) FNS="${1#*=}" ;;
        --structs=*) STRUCTS="${1#*=}" ;;
        --no-reorder) REORDER=0 ;;
        --full-chain) FULL_CHAIN=1 ;;
        --keep) KEEP=1 ;;
        --self-test) SELF_TEST=1 ;;
        --smoke=*) SMOKE="${1#*=}" ;;
        --hop-timeout=*) HOP_TIMEOUT="${1#*=}" ;;
        -h|--help)
            sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "selfhost_perturb: unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

if ! SEED=$(XU_SEED="$SEED_INPUT" ./scripts/xu_host_seed.sh); then
    echo "selfhost_perturb: seed rejected by hosted product policy: ${SEED_INPUT:-<auto>}" >&2
    exit 1
fi
SEED_LANE=hosted

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        sha256sum "$1" | awk '{print $1}'
    fi
}

pick_bin() {
    for cand in "$1" "${1}.xin" "${1}.exe"; do
        if [ -x "$cand" ]; then
            echo "$cand"
            return 0
        fi
    done
    return 1
}

HOP_EXT=""
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) HOP_EXT=".exe" ;;
esac
if [ "${OS-}" = "Windows_NT" ]; then HOP_EXT=".exe"; fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/xu-perturb.XXXXXX")
STATUS=FAIL
cleanup() {
    local rc=$?
    if [ "$rc" -ne 0 ] || [ "$KEEP" = 1 ]; then
        echo "selfhost_perturb: work tree kept at $WORK" >&2
    else
        rm -rf -- "$WORK"
    fi
    echo "selfhost_perturb: $STATUS lane=$LANE seed_lane=$SEED_LANE rounds=$ROUNDS"
    return "$rc"
}
trap cleanup EXIT

# Same hermetic environment as build_hosted_chain.sh: no ambient search
# roots or package caches may leak into a hop.
export LC_ALL=C
export XUPATH=""
export XU_CACHE="$WORK/cache"
export HOME="$WORK/home"
export USERPROFILE="$HOME"
mkdir -p "$XU_CACHE" "$HOME"
unset XUOS XUARCH XU_BOOT_EXTRA XU_HEAP_STATS XU_SEED

# hop <cwd> <compiler> <out> : compile the Gen1 source list found below <cwd>.
hop() {
    local cwd="$1" xu="$2" out="$3" rc
    set +e
    # shellcheck disable=SC2086
    (cd "$cwd" &&
        export XU_ROOT="$(python3 -c 'from pathlib import Path; print(Path.cwd().resolve().as_posix())')" &&
        export XU_STDLIB_ROOT="$XU_ROOT/src" &&
        run_with_timeout "$HOP_TIMEOUT" "$xu" build $GEN1_SRCS -o "$out") >"$out.log" 2>&1
    rc=$?
    set -e
    if [ "$rc" -eq 124 ]; then
        echo "selfhost_perturb: hop timed out after ${HOP_TIMEOUT}s: $xu (cwd=$cwd)" >&2
        return 124
    fi
    if [ "$rc" -ne 0 ]; then
        echo "selfhost_perturb: hop failed rc=$rc: $xu (cwd=$cwd)" >&2
        tail -40 "$out.log" | sed 's/^/  | /' >&2
        return "$rc"
    fi
    pick_bin "$out" >/dev/null || { echo "selfhost_perturb: missing artifact $out" >&2; return 1; }
    return 0
}

echo "selfhost_perturb: lane=$LANE seed_lane=$SEED_LANE"
echo "selfhost_perturb: seed=$SEED"
echo "selfhost_perturb: seed_sha256=$(sha256_file "$SEED")"
echo "selfhost_perturb: rounds=$ROUNDS random_seed=$RSEED files=${FILES:-<random $NFILES>} fns=$FNS structs=$STRUCTS reorder=$REORDER full_chain=$FULL_CHAIN"

# ---- self-test: the harness must be compiling the perturbed tree -----------
if [ "$SELF_TEST" = 1 ]; then
    selftest_args=(--src-root "$ROOT" --out-root "$WORK/selftest"
        --random-seed "$RSEED" --nfiles 1 --fns 1 --structs 1 --no-reorder --self-test
        --manifest "$WORK/selftest/manifest.json")
    [ -z "$FILES" ] || selftest_args+=(--files "$FILES")
    python3 scripts/selfhost_perturb.py "${selftest_args[@]}" >/dev/null
    if hop "$WORK/selftest" "$SEED" "$WORK/selftest/p1$HOP_EXT" 2>/dev/null; then
        echo "selfhost_perturb: SELF-TEST FAILED: an injected syntax error compiled; the harness is not compiling the perturbed tree" >&2
        exit 1
    fi
    # The diagnostic must point at the injected line of the *perturbed* copy.
    expect_loc=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print("%s:%d" % (m["self_test"]["file"], m["self_test"]["line"]))' "$WORK/selftest/manifest.json")
    if ! grep -qF "$expect_loc" "$WORK/selftest/p1$HOP_EXT.log"; then
        echo "selfhost_perturb: SELF-TEST FAILED: expected a diagnostic at $expect_loc, got:" >&2
        tail -20 "$WORK/selftest/p1$HOP_EXT.log" >&2
        exit 1
    fi
    echo "selfhost_perturb: self-test PASS (perturbed tree is what gets compiled)"
    STATUS=PASS
    exit 0
fi

# ---- reference: what the unperturbed compiler produces --------------------
echo "selfhost_perturb: reference hop (seed builds unperturbed src)"
hop "$ROOT" "$SEED" "$WORK/baseline$HOP_EXT"
BASE=$(pick_bin "$WORK/baseline$HOP_EXT")
if cmp -s "$BASE" "$SEED"; then
    echo "selfhost_perturb: seed is at fixed point (seed == seed(src)); REF = baseline"
    REF="$BASE"
else
    echo "selfhost_perturb: seed is not at fixed point; REF = baseline(src) (one more hop)"
    hop "$ROOT" "$BASE" "$WORK/ref$HOP_EXT"
    REF=$(pick_bin "$WORK/ref$HOP_EXT")
fi
echo "selfhost_perturb: ref_sha256=$(sha256_file "$REF")"

# Smoke verdicts of the *reference* compiler.  A fixture the unperturbed
# compiler already fails is a compiler bug in its own right (reported, and
# it belongs to verify-gen3), but it is not perturbation sensitivity; rounds
# are judged against this baseline so the gate measures one thing.
smoke_verdicts() {
    grep -E '^(PASS|FAIL|KNOWN-FAIL|FIXED) ' "$1" | awk '{print $2 "\t" $1}' | LC_ALL=C sort
}
set +e
./scripts/run_fixtures.sh --xu="$REF" --sub=build --label="perturb-ref" --only="$SMOKE" >"$WORK/smoke-ref.log" 2>&1
set -e
smoke_verdicts "$WORK/smoke-ref.log" >"$WORK/smoke-ref.tsv"
if ! grep -q . "$WORK/smoke-ref.tsv"; then
    echo "selfhost_perturb: reference smoke produced no verdicts:" >&2
    tail -20 "$WORK/smoke-ref.log" >&2
    exit 1
fi
baseline_fail=$(awk -F'\t' '$2 != "PASS" {print $1}' "$WORK/smoke-ref.tsv" | tr '\n' ' ')
grep -E '^fixtures\[' "$WORK/smoke-ref.log" | sed 's/^/selfhost_perturb: reference smoke /'
if [ -n "$baseline_fail" ]; then
    echo "selfhost_perturb: WARNING reference compiler already fails smoke fixtures (not perturbation sensitivity; see verify-gen3): $baseline_fail"
fi

# ---- rounds ----------------------------------------------------------------
failed=0
passed=0
for r in $(seq 1 "$ROUNDS"); do
    rs=$((RSEED + r - 1))
    rd="$WORK/r$r"
    mkdir -p "$rd"
    py_args=(--src-root "$ROOT" --out-root "$rd" --random-seed "$rs" --nfiles "$NFILES" --fns "$FNS" --structs "$STRUCTS" --manifest "$rd/manifest.json")
    [ -n "$FILES" ] && py_args+=(--files "$FILES")
    [ "$REORDER" = 0 ] && py_args+=(--no-reorder)
    python3 scripts/selfhost_perturb.py "${py_args[@]}" >/dev/null
    files_line=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(" ".join(f["file"]+("(swap)" if f["swaps"] else "") for f in m["files"]))' "$rd/manifest.json")
    echo "selfhost_perturb: round $r random_seed=$rs files: $files_line"
    reorder_flag=""
    if [ "$REORDER" = 0 ]; then reorder_flag=" --no-reorder"; fi
    repro="python3 scripts/selfhost_perturb.py --src-root . --out-root /tmp/xu-perturb-repro --random-seed $rs --nfiles $NFILES --fns $FNS --structs $STRUCTS${FILES:+ --files $FILES}$reorder_flag"

    # 2. seed compiles the perturbed tree.
    if ! hop "$rd" "$SEED" "$rd/p1$HOP_EXT"; then
        echo "FAIL round $r: seed cannot compile the perturbed tree (repro: $repro)"
        failed=$((failed + 1))
        continue
    fi
    P1=$(pick_bin "$rd/p1$HOP_EXT")

    # 3. perturbed compiler compiles the unperturbed tree; must equal REF.
    if ! hop "$ROOT" "$P1" "$rd/x$HOP_EXT"; then
        echo "FAIL round $r: perturbed compiler cannot compile src/ (repro: $repro)"
        failed=$((failed + 1))
        continue
    fi
    X=$(pick_bin "$rd/x$HOP_EXT")
    if ! cmp -s "$X" "$REF"; then
        echo "FAIL round $r: perturbed compiler output diverges from reference ($(sha256_file "$X") != $(sha256_file "$REF")) (repro: $repro)"
        failed=$((failed + 1))
        continue
    fi

    # 4. smoke fixtures compiled + run by the perturbed compiler; the verdict
    #    of every fixture must match the reference compiler's verdict.
    set +e
    ./scripts/run_fixtures.sh --xu="$P1" --sub=build --label="perturb-r$r" --only="$SMOKE" >"$rd/smoke.log" 2>&1
    set -e
    smoke_verdicts "$rd/smoke.log" >"$rd/smoke.tsv"
    if ! cmp -s "$rd/smoke.tsv" "$WORK/smoke-ref.tsv"; then
        echo "FAIL round $r: smoke verdicts differ from the reference compiler (repro: $repro)"
        diff "$WORK/smoke-ref.tsv" "$rd/smoke.tsv" | sed 's/^/  | /' || true
        grep -E '^FAIL ' -A3 "$rd/smoke.log" | sed 's/^/  | /' | head -40
        failed=$((failed + 1))
        continue
    fi
    grep -E '^fixtures\[' "$rd/smoke.log" | sed "s/^/selfhost_perturb: round $r /"

    # 5. optional fixed point on the perturbed tree itself.
    if [ "$FULL_CHAIN" = 1 ]; then
        ok=1
        hop "$rd" "$P1" "$rd/p2$HOP_EXT" || ok=0
        [ "$ok" = 1 ] && { hop "$rd" "$(pick_bin "$rd/p2$HOP_EXT")" "$rd/p3$HOP_EXT" || ok=0; }
        [ "$ok" = 1 ] && { hop "$rd" "$(pick_bin "$rd/p3$HOP_EXT")" "$rd/p4$HOP_EXT" || ok=0; }
        if [ "$ok" = 1 ] && ! cmp -s "$(pick_bin "$rd/p3$HOP_EXT")" "$(pick_bin "$rd/p4$HOP_EXT")"; then
            echo "FAIL round $r: perturbed tree has no fixed point (P3 != P4) (repro: $repro)"
            ok=0
        fi
        if [ "$ok" = 0 ]; then
            failed=$((failed + 1))
            continue
        fi
        echo "selfhost_perturb: round $r full chain P3 == P4"
    fi
    echo "PASS round $r"
    passed=$((passed + 1))
done

echo "selfhost_perturb: summary passed=$passed failed=$failed rounds=$ROUNDS"
if [ "$failed" -eq 0 ]; then
    STATUS=PASS
    exit 0
fi
exit 1
