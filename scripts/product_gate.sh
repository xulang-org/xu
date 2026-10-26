#!/usr/bin/env bash
# Unified product gate — OPEN_ADVANCED_PROGRAMMER_IMPLEMENTATION_PLAN.md §4 P0.1.
#
# Read-only evidence aggregator.  Runs the product-lane gates in a fixed
# order, binds every result to the current git commit and source manifests,
# and writes a single report.  It never installs a release package and never
# promotes an oracle/primer binary as product evidence.
#
# Order (plan §4 P0.1):
#   1. boundary --strict-freeze
#   2. pytest -q
#   3. XU_SKIP_CROSS=1 make xu   (Gen2==Gen3, or Gen3==Gen4 after a transition),
#      heap/MIR borrow checks, iterable ownership ledger, call ABI index,
#      assembly symbol/fixup/ownership checks
#   4. fixture-matrix --quick
#   5. selfhost-perturb
#   6. determinism
#
# Usage:
#   scripts/product_gate.sh                     # full local product gate
#   scripts/product_gate.sh --quick             # skip perturb + determinism
#   scripts/product_gate.sh --skip-build        # reuse existing bin/xu
#   scripts/product_gate.sh --out=DIR           # report directory override
#
# Lane: product.  The seed is resolved by xu_host_seed.sh (bin/xu or
# developer/bin snapshot).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
export XU_ROOT="$ROOT"
cd "$ROOT"
export XU_STDLIB_ROOT="$("${PYTHON:-python3}" -c 'from pathlib import Path; print(Path("src").resolve().as_posix())')"
source scripts/macos_sdk_env.sh
source scripts/test_lib.sh

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        python3 - "$1" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())
PY
    fi
}

PYTHON="${PYTHON:-python3}"
QUICK=0
SKIP_BUILD=0
SKIP_FIXTURE_MATRIX=0
OUT=""
LABEL="product-gate"

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --quick) QUICK=1 ;;
        --skip-build) SKIP_BUILD=1 ;;
        --skip-fixture-matrix) SKIP_FIXTURE_MATRIX=1 ;;
        --out=*) OUT="${1#*=}" ;;
        --label=*) LABEL="${1#*=}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "product_gate: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

LANE=product

if [ -z "$OUT" ]; then
    OUT="docs/audit"
fi
mkdir -p "$OUT"
REPORT="$OUT/product_gate.latest.txt"
JSON="$OUT/product_gate.latest.json"
LOG_DIR="$OUT/product_gate-logs"
mkdir -p "$LOG_DIR"

step() { printf '\n== product_gate: %s ==\n' "$1"; }
run() {
    echo "+ $*"
    "$@"
}

# --- environment / identity -------------------------------------------------

git_commit="unknown"
git_dirty="unknown"
if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    git_commit=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)
    if [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
        git_dirty=1
    else
        git_dirty=0
    fi
fi

host_os=$(uname -s)
host_arch=$(uname -m)
kernel=$(uname -r)
version_file="unknown"
[ -f VERSION ] && version_file=$(tr -d ' \n\r\t' < VERSION)

started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
started_ts=$(date +%s)

declare -a STEP_NAMES=()
declare -a STEP_STATUS=()
declare -a STEP_RC=()
declare -a STEP_SUMMARY=()
declare -a STEP_SECONDS=()
FAILED=0
FIRST_FAIL=""

record_step() {
    local name=$1 status=$2 rc=$3 summary=$4 seconds=$5
    STEP_NAMES+=("$name")
    STEP_STATUS+=("$status")
    STEP_RC+=("$rc")
    STEP_SUMMARY+=("$summary")
    STEP_SECONDS+=("$seconds")
    if [ "$status" != "PASS" ] && [ "$status" != "SKIP" ]; then
        FAILED=1
        if [ -z "$FIRST_FAIL" ]; then
            FIRST_FAIL="$name"
        fi
    fi
}

# --- source manifests (from boundary --json) --------------------------------

SOURCE_SEED_SHA256="unknown"
SOURCE_CLOSURE_SHA256="unknown"
SOURCE_SEED_FILES="unknown"
SOURCE_CLOSURE_FILES="unknown"
BOUNDARY_JSON="$LOG_DIR/boundary.json"

extract_manifest() {
    $PYTHON - "$BOUNDARY_JSON" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        report = json.load(fh)
except Exception:
    print("unknown|unknown|unknown|unknown")
    raise SystemExit(0)
source = report.get("source_manifest", {})
print("|".join([
    str(source.get("seed_sha256", "unknown")),
    str(source.get("closure_sha256", "unknown")),
    str(source.get("seed_files", "unknown")),
    str(source.get("closure_files", "unknown")),
]))
PY
}

# --- step 1: boundary -------------------------------------------------------

step "boundary --strict-freeze"
t0=$(date +%s)
set +e
$PYTHON scripts/check_bootstrap_xu_boundary.py --strict-freeze \
    >"$LOG_DIR/boundary.log" 2>&1
b_rc=$?
set -e
t1=$(date +%s)
if [ -f "$BOUNDARY_JSON" ] || $PYTHON scripts/check_bootstrap_xu_boundary.py --strict-freeze --json >"$BOUNDARY_JSON" 2>>"$LOG_DIR/boundary.log"; then
    IFS='|' read -r SOURCE_SEED_SHA256 SOURCE_CLOSURE_SHA256 \
        SOURCE_SEED_FILES SOURCE_CLOSURE_FILES <<EOF
$(extract_manifest)
EOF
fi
if [ "$b_rc" -eq 0 ]; then
    record_step "boundary" PASS 0 "strict-freeze ok seed=$SOURCE_SEED_SHA256 closure=$SOURCE_CLOSURE_SHA256" "$((t1 - t0))"
    echo "boundary: PASS"
else
    record_step "boundary" FAIL "$b_rc" "strict-freeze failed (see $LOG_DIR/boundary.log)" "$((t1 - t0))"
    echo "boundary: FAIL rc=$b_rc" >&2
    tail -n 40 "$LOG_DIR/boundary.log" >&2 || true
fi

# --- step 2: pytest ---------------------------------------------------------

step "pytest -q"
t0=$(date +%s)
set +e
$PYTHON -m pytest -q >"$LOG_DIR/pytest.log" 2>&1
p_rc=$?
set -e
t1=$(date +%s)
pytest_summary=$(grep -E '^[0-9]+ (passed|failed)|failed,|passed,' "$LOG_DIR/pytest.log" | tail -n 1 || true)
[ -n "$pytest_summary" ] || pytest_summary=$(tail -n 1 "$LOG_DIR/pytest.log" || true)
if [ "$p_rc" -eq 0 ]; then
    record_step "pytest" PASS 0 "$pytest_summary" "$((t1 - t0))"
    echo "pytest: PASS $pytest_summary"
else
    record_step "pytest" FAIL "$p_rc" "$pytest_summary" "$((t1 - t0))"
    echo "pytest: FAIL rc=$p_rc" >&2
    tail -n 40 "$LOG_DIR/pytest.log" >&2 || true
fi

# --- step 2b: release identity ----------------------------------------------

step "release identity"
t0=$(date +%s)
set +e
$PYTHON scripts/check_release_identity.py >"$LOG_DIR/release-identity.log" 2>&1
id_rc=$?
set -e
t1=$(date +%s)
id_summary=$(grep -E '^release identity:' "$LOG_DIR/release-identity.log" | tail -n 1 || true)
if [ "$id_rc" -eq 0 ]; then
    record_step "release-identity" PASS 0 "${id_summary:-ok}" "$((t1 - t0))"
    echo "release-identity: PASS ${id_summary:-}"
else
    record_step "release-identity" FAIL "$id_rc" "${id_summary:-failed}" "$((t1 - t0))"
    echo "release-identity: FAIL rc=$id_rc" >&2
    cat "$LOG_DIR/release-identity.log" >&2 || true
fi

# --- step 3: hosted chain (make xu) -----------------------------------------

GEN1_SHA256="unknown"
GEN2_SHA256="unknown"
GEN3_SHA256="unknown"
GEN4_SHA256="unknown"
GEN3_GEN4_CMP="unknown"
CONFIRMED_GENERATION="unknown"
CONFIRMED_SHA256="unknown"
FIXED_POINT_PAIR="unknown"
BIN_SHA256="unknown"
SEED_PATH="unknown"
SEED_SHA256="unknown"
PROVENANCE_STATUS="UNAVAILABLE"

read_provenance() {
    local prov=$1
    [ -f "$prov" ] || return 0
    PROVENANCE_STATUS=$(awk -F= '/^status=/{print $2; exit}' "$prov" 2>/dev/null || echo unknown)
    SEED_PATH=$(awk -F= '/^seed_path=/{print $2; exit}' "$prov" 2>/dev/null || echo unknown)
    SEED_SHA256=$(awk -F= '/^seed_sha256=/{print $2; exit}' "$prov" 2>/dev/null || echo unknown)
    GEN1_SHA256=$(awk -F= '/^gen1_sha256=/{print $2; exit}' "$prov" 2>/dev/null || echo unknown)
    GEN2_SHA256=$(awk -F= '/^gen2_sha256=/{print $2; exit}' "$prov" 2>/dev/null || echo unknown)
    GEN3_SHA256=$(awk -F= '/^gen3_sha256=/{print $2; exit}' "$prov" 2>/dev/null || echo unknown)
    GEN4_SHA256=$(awk -F= '/^gen4_sha256=/{print $2; exit}' "$prov" 2>/dev/null || echo unknown)
    GEN3_GEN4_CMP=$(awk -F= '/^gen3_gen4_cmp=/{print $2; exit}' "$prov" 2>/dev/null || echo unknown)
    CONFIRMED_GENERATION=$(awk -F= '/^confirmed_generation=/{print $2; exit}' "$prov")
    CONFIRMED_SHA256=$(awk -F= '/^confirmed_sha256=/{print $2; exit}' "$prov")
    FIXED_POINT_PAIR=$(awk -F= '/^fixed_point_pair=/{print $2; exit}' "$prov")
    # Legacy sidecars always confirmed Gen3/Gen4.
    CONFIRMED_GENERATION=${CONFIRMED_GENERATION:-4}
    CONFIRMED_SHA256=${CONFIRMED_SHA256:-$GEN4_SHA256}
    FIXED_POINT_PAIR=${FIXED_POINT_PAIR:-gen3_gen4}
}

step "product chain (XU_SKIP_CROSS=1 make xu)"
t0=$(date +%s)
if [ "$SKIP_BUILD" = 1 ]; then
    if [ -x bin/xu ]; then
        BIN_SHA256=$(sha256_file bin/xu)
        read_provenance bin/xu.provenance
        if python3 scripts/verify_product_provenance.py bin/xu --source-closure-sha256 "$SOURCE_CLOSURE_SHA256" --lane "$LANE" >"$LOG_DIR/provenance.log" 2>&1; then
            record_step "product-chain" SKIP 0 "verified reuse bin/xu sha=$BIN_SHA256" 0
            echo "product-chain: SKIP (verified existing artifact)"
        else
            record_step "product-chain" FAIL 1 "reuse provenance invalid (see provenance.log)" 0
            echo "product-chain: FAIL existing artifact identity" >&2
        fi
    else
        record_step "product-chain" FAIL 1 "--skip-build but bin/xu missing" 0
        echo "product-chain: FAIL --skip-build without bin/xu" >&2
    fi
else
    set +e
    XU_SKIP_CROSS=1 make xu \
        >"$LOG_DIR/make-xu.log" 2>&1
    m_rc=$?
    set -e
    t1=$(date +%s)
    if [ "$m_rc" -eq 0 ] && [ -x bin/xu ]; then
        BIN_SHA256=$(sha256_file bin/xu)
        read_provenance bin/xu.provenance
        chain_summary="chain PASS lane=$LANE bin_sha=$BIN_SHA256 fixed_point=$FIXED_POINT_PAIR confirmed=Gen$CONFIRMED_GENERATION"
        if ! python3 scripts/verify_product_provenance.py bin/xu --source-closure-sha256 "$SOURCE_CLOSURE_SHA256" --lane "$LANE" >"$LOG_DIR/provenance.log" 2>&1; then
            record_step "product-chain" FAIL 1 "provenance missing/stale or fixed point unverified: $chain_summary" "$((t1 - t0))"
            echo "product-chain: FAIL provenance does not identify live product" >&2
        else
            record_step "product-chain" PASS 0 "$chain_summary" "$((t1 - t0))"
            echo "product-chain: PASS $chain_summary"
        fi
        grep -E 'build_hosted_chain:|chain PASS' "$LOG_DIR/make-xu.log" | tail -n 20 || true
    else
        record_step "product-chain" FAIL "$m_rc" "make xu failed (see $LOG_DIR/make-xu.log)" "$((t1 - t0))"
        echo "product-chain: FAIL rc=$m_rc" >&2
        tail -n 40 "$LOG_DIR/make-xu.log" >&2 || true
    fi
fi

# Remaining steps need a usable hosted compiler.
HAVE_XU=0
if [ -x bin/xu ]; then
    HAVE_XU=1
    BIN_SHA256=$(sha256_file bin/xu)
fi

# --- step 3b: heap-check ----------------------------------------------------

step "heap-check"
t0=$(date +%s)
if [ "$HAVE_XU" != 1 ]; then
    record_step "heap-check" FAIL 1 "no bin/xu" 0
    echo "heap-check: FAIL no bin/xu" >&2
else
    set +e
    XU="$ROOT/bin/xu" ./scripts/test_heap_check.sh \
        >"$LOG_DIR/heap-check.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    hc_summary=$(grep -E '^test_heap_check:|^fixtures\[' "$LOG_DIR/heap-check.log" | tail -n 2 | tr '\n' ';')
    if [ "$x_rc" -eq 0 ]; then
        record_step "heap-check" PASS 0 "${hc_summary:-ok}" "$((t1 - t0))"
        echo "heap-check: PASS"
    else
        record_step "heap-check" FAIL "$x_rc" "${hc_summary:-failed}" "$((t1 - t0))"
        echo "heap-check: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/heap-check.log" >&2 || true
    fi
fi

# --- step 3c: MIR borrow gate ------------------------------------------------

step "mir-borrow-gate"
t0=$(date +%s)
if [ "$HAVE_XU" != 1 ]; then
    record_step "mir-borrow-gate" FAIL 1 "no bin/xu" 0
    echo "mir-borrow-gate: FAIL no bin/xu" >&2
else
    set +e
    XU="$ROOT/bin/xu" ./scripts/test_mir_borrow_gate.sh \
        >"$LOG_DIR/mir-borrow-gate.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    mb_summary=$(grep -E '^test_mir_borrow_gate:' "$LOG_DIR/mir-borrow-gate.log" | tail -n 1)
    if [ "$x_rc" -eq 0 ]; then
        record_step "mir-borrow-gate" PASS 0 "${mb_summary:-ok}" "$((t1 - t0))"
        echo "mir-borrow-gate: PASS"
    else
        record_step "mir-borrow-gate" FAIL "$x_rc" "${mb_summary:-failed}" "$((t1 - t0))"
        echo "mir-borrow-gate: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/mir-borrow-gate.log" >&2 || true
    fi
fi

# --- step 3d: temporary iterable ownership ----------------------------------

step "foreach-owner-ledger"
t0=$(date +%s)
if [ "$HAVE_XU" != 1 ]; then
    record_step "foreach-owner-ledger" FAIL 1 "no bin/xu" 0
    echo "foreach-owner-ledger: FAIL no bin/xu" >&2
else
    set +e
    $PYTHON tests/test_foreach_owner.py --xu "$ROOT/bin/xu" \
        --out "$LOG_DIR/foreach-owner.json" >"$LOG_DIR/foreach-owner.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    fo_summary=$(grep -E '^foreach owner:' "$LOG_DIR/foreach-owner.log" | tail -n 1 || true)
    if [ "$x_rc" -eq 0 ]; then
        record_step "foreach-owner-ledger" PASS 0 "${fo_summary:-ok}" "$((t1 - t0))"
        echo "foreach-owner-ledger: PASS ${fo_summary:-}"
    else
        record_step "foreach-owner-ledger" FAIL "$x_rc" "${fo_summary:-failed}" "$((t1 - t0))"
        echo "foreach-owner-ledger: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/foreach-owner.log" >&2 || true
    fi
fi

# --- step 3e: indexed call ABI admission ------------------------------------

step "call-index-ledger"
t0=$(date +%s)
if [ "$HAVE_XU" != 1 ]; then
    record_step "call-index-ledger" FAIL 1 "no bin/xu" 0
    echo "call-index-ledger: FAIL no bin/xu" >&2
else
    set +e
    $PYTHON tests/test_call_index.py --xu "$ROOT/bin/xu" \
        --out "$LOG_DIR/call-index.json" >"$LOG_DIR/call-index.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    ci_summary=$(grep -E '^PASS:' "$LOG_DIR/call-index.log" | tail -n 1 || true)
    if [ "$x_rc" -eq 0 ]; then
        record_step "call-index-ledger" PASS 0 "${ci_summary:-ok}" "$((t1 - t0))"
        echo "call-index-ledger: PASS ${ci_summary:-}"
    else
        record_step "call-index-ledger" FAIL "$x_rc" "${ci_summary:-failed}" "$((t1 - t0))"
        echo "call-index-ledger: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/call-index.log" >&2 || true
    fi
fi

# --- step 3f: assembly symbols and fixups -----------------------------------

step "assembler-symbols-ledger"
t0=$(date +%s)
if [ "$HAVE_XU" != 1 ]; then
    record_step "assembler-symbols-ledger" FAIL 1 "no bin/xu" 0
    echo "assembler-symbols-ledger: FAIL no bin/xu" >&2
else
    set +e
    $PYTHON tests/test_assembler_symbols.py --xu "$ROOT/bin/xu" \
        --out "$LOG_DIR/assembler-symbols.json" >"$LOG_DIR/assembler-symbols.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    as_summary=$(grep -E '^PASS:' "$LOG_DIR/assembler-symbols.log" | tail -n 1 || true)
    if [ "$x_rc" -eq 0 ]; then
        record_step "assembler-symbols-ledger" PASS 0 "${as_summary:-ok}" "$((t1 - t0))"
        echo "assembler-symbols-ledger: PASS ${as_summary:-}"
    else
        record_step "assembler-symbols-ledger" FAIL "$x_rc" "${as_summary:-failed}" "$((t1 - t0))"
        echo "assembler-symbols-ledger: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/assembler-symbols.log" >&2 || true
    fi
fi

# --- step 3g: strmap-ledger -------------------------------------------------

step "strmap-ledger"
t0=$(date +%s)
if [ "$HAVE_XU" != 1 ]; then
    record_step "strmap-ledger" FAIL 1 "no bin/xu" 0
    echo "strmap-ledger: FAIL no bin/xu" >&2
else
    set +e
    $PYTHON tests/test_strmap.py --xu "$ROOT/bin/xu" --expect-zero-lookup-allocs \
        --out "$LOG_DIR/strmap-ledger.json" >"$LOG_DIR/strmap-ledger.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    summary=$(grep -E '^PASS:' "$LOG_DIR/strmap-ledger.log" | tail -n 1 || true)
    if [ "$x_rc" -eq 0 ]; then
        record_step "strmap-ledger" PASS 0 "${summary:-ok}" "$((t1 - t0))"
        echo "strmap-ledger: PASS ${summary:-}"
    else
        record_step "strmap-ledger" FAIL "$x_rc" "${summary:-failed}" "$((t1 - t0))"
        echo "strmap-ledger: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/strmap-ledger.log" >&2 || true
    fi
fi

# --- step 3h: throw-index-ledger -------------------------------------------------

step "throw-index-ledger"
t0=$(date +%s)
if [ "$HAVE_XU" != 1 ]; then
    record_step "throw-index-ledger" FAIL 1 "no bin/xu" 0
    echo "throw-index-ledger: FAIL no bin/xu" >&2
else
    set +e
    $PYTHON tests/test_throw_index.py --xu "$ROOT/bin/xu" \
        --out "$LOG_DIR/throw-index-ledger.json" >"$LOG_DIR/throw-index-ledger.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    summary=$(grep -E '^PASS:' "$LOG_DIR/throw-index-ledger.log" | tail -n 1 || true)
    if [ "$x_rc" -eq 0 ]; then
        record_step "throw-index-ledger" PASS 0 "${summary:-ok}" "$((t1 - t0))"
        echo "throw-index-ledger: PASS ${summary:-}"
    else
        record_step "throw-index-ledger" FAIL "$x_rc" "${summary:-failed}" "$((t1 - t0))"
        echo "throw-index-ledger: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/throw-index-ledger.log" >&2 || true
    fi
fi

# --- step 4: fixture matrix -------------------------------------------------

MATRIX_SUMMARY="skipped"
step "fixture-matrix --quick"
t0=$(date +%s)
if [ "$SKIP_FIXTURE_MATRIX" = 1 ]; then
    record_step "fixture-matrix" SKIP 0 "disabled by --skip-fixture-matrix" 0
    echo "fixture-matrix: SKIP"
elif [ "$HAVE_XU" != 1 ]; then
    record_step "fixture-matrix" FAIL 1 "no bin/xu" 0
    echo "fixture-matrix: FAIL no bin/xu" >&2
else
    set +e
    ./scripts/run_fixture_matrix.sh --xu="$ROOT/bin/xu" --quick \
        --out="$LOG_DIR/matrix" >"$LOG_DIR/fixture-matrix.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    MATRIX_SUMMARY=$(grep -E '^matrix:' "$LOG_DIR/fixture-matrix.log" | tail -n 1 || true)
    [ -n "$MATRIX_SUMMARY" ] || MATRIX_SUMMARY=$(grep -E '^run_fixture_matrix:' "$LOG_DIR/fixture-matrix.log" | tail -n 1 || true)
    if [ "$x_rc" -eq 0 ]; then
        record_step "fixture-matrix" PASS 0 "${MATRIX_SUMMARY:-ok}" "$((t1 - t0))"
        echo "fixture-matrix: PASS ${MATRIX_SUMMARY:-}"
    else
        record_step "fixture-matrix" FAIL "$x_rc" "${MATRIX_SUMMARY:-failed}" "$((t1 - t0))"
        echo "fixture-matrix: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/fixture-matrix.log" >&2 || true
    fi
fi

# --- step 5: selfhost-perturb -----------------------------------------------

PERTURB_SUMMARY="skipped"
step "selfhost-perturb"
t0=$(date +%s)
if [ "$QUICK" = 1 ]; then
    record_step "selfhost-perturb" SKIP 0 "skipped by --quick" 0
    echo "selfhost-perturb: SKIP (--quick)"
elif [ "$HAVE_XU" != 1 ]; then
    record_step "selfhost-perturb" FAIL 1 "no bin/xu" 0
    echo "selfhost-perturb: FAIL no bin/xu" >&2
else
    set +e
    ./scripts/selfhost_perturb.sh --seed="$ROOT/bin/xu" \
        >"$LOG_DIR/selfhost-perturb.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    PERTURB_SUMMARY=$(grep -E '^selfhost_perturb: summary' "$LOG_DIR/selfhost-perturb.log" | tail -n 1 || true)
    [ -n "$PERTURB_SUMMARY" ] || PERTURB_SUMMARY=$(grep -E '^selfhost_perturb: (PASS|FAIL)' "$LOG_DIR/selfhost-perturb.log" | tail -n 1 || true)
    if [ "$x_rc" -eq 0 ]; then
        record_step "selfhost-perturb" PASS 0 "${PERTURB_SUMMARY:-ok}" "$((t1 - t0))"
        echo "selfhost-perturb: PASS ${PERTURB_SUMMARY:-}"
    else
        record_step "selfhost-perturb" FAIL "$x_rc" "${PERTURB_SUMMARY:-failed}" "$((t1 - t0))"
        echo "selfhost-perturb: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/selfhost-perturb.log" >&2 || true
    fi
fi

# --- step 6: determinism ----------------------------------------------------

DETERMINISM_SUMMARY="skipped"
step "determinism"
t0=$(date +%s)
if [ "$QUICK" = 1 ]; then
    record_step "determinism" SKIP 0 "skipped by --quick" 0
    echo "determinism: SKIP (--quick)"
elif [ "$HAVE_XU" != 1 ]; then
    record_step "determinism" FAIL 1 "no bin/xu" 0
    echo "determinism: FAIL no bin/xu" >&2
else
    set +e
    ./scripts/build_determinism.sh --xu="$ROOT/bin/xu" \
        --unit=tests/fixtures/matmul_tiny/main.xu \
        >"$LOG_DIR/determinism.log" 2>&1
    x_rc=$?
    set -e
    t1=$(date +%s)
    DETERMINISM_SUMMARY=$(grep -E '^build_determinism:' "$LOG_DIR/determinism.log" | tail -n 1 || true)
    if [ "$x_rc" -eq 0 ]; then
        record_step "determinism" PASS 0 "${DETERMINISM_SUMMARY:-ok}" "$((t1 - t0))"
        echo "determinism: PASS ${DETERMINISM_SUMMARY:-}"
    else
        record_step "determinism" FAIL "$x_rc" "${DETERMINISM_SUMMARY:-failed}" "$((t1 - t0))"
        echo "determinism: FAIL rc=$x_rc" >&2
        tail -n 40 "$LOG_DIR/determinism.log" >&2 || true
    fi
fi

# --- report -----------------------------------------------------------------

finished_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
finished_ts=$(date +%s)
total_seconds=$((finished_ts - started_ts))
overall=PASS
[ "$FAILED" -eq 0 ] || overall=FAIL

{
    echo "schema=1"
    echo "label=$LABEL"
    echo "status=$overall"
    echo "lane=$LANE"
    echo "started_at=$started_at"
    echo "finished_at=$finished_at"
    echo "total_seconds=$total_seconds"
    echo "git_commit=$git_commit"
    echo "git_dirty=$git_dirty"
    echo "version=$version_file"
    echo "host_os=$host_os"
    echo "host_arch=$host_arch"
    echo "kernel=$kernel"
    echo "source_seed_files=$SOURCE_SEED_FILES"
    echo "source_seed_sha256=$SOURCE_SEED_SHA256"
    echo "source_closure_files=$SOURCE_CLOSURE_FILES"
    echo "source_closure_sha256=$SOURCE_CLOSURE_SHA256"
    echo "seed_path=$SEED_PATH"
    echo "seed_sha256=$SEED_SHA256"
    echo "bin_xu_sha256=$BIN_SHA256"
    echo "provenance_status=$PROVENANCE_STATUS"
    echo "gen1_sha256=$GEN1_SHA256"
    echo "gen2_sha256=$GEN2_SHA256"
    echo "gen3_sha256=$GEN3_SHA256"
    echo "gen4_sha256=$GEN4_SHA256"
    echo "gen3_gen4_cmp=$GEN3_GEN4_CMP"
    echo "confirmed_generation=$CONFIRMED_GENERATION"
    echo "confirmed_sha256=$CONFIRMED_SHA256"
    echo "fixed_point_pair=$FIXED_POINT_PAIR"
    echo "hosted_profile=$( [ "$QUICK" = 1 ] && echo quick || echo full )"
    echo "hosted_args=XU_SKIP_CROSS=1"
    echo "ra_level=compiler-default"
    echo "opt_level=compiler-default"
    echo "fixture_matrix=${MATRIX_SUMMARY}"
    echo "selfhost_perturb=${PERTURB_SUMMARY}"
    echo "determinism=${DETERMINISM_SUMMARY}"
    echo "first_fail=${FIRST_FAIL:-none}"
    echo "steps=${#STEP_NAMES[@]}"
    echo
    echo "# steps"
    step_i=0
    while [ "$step_i" -lt "${#STEP_NAMES[@]}" ]; do
        echo "step.${STEP_NAMES[$step_i]}=${STEP_STATUS[$step_i]} rc=${STEP_RC[$step_i]} seconds=${STEP_SECONDS[$step_i]} :: ${STEP_SUMMARY[$step_i]}"
        step_i=$((step_i + 1))
    done
    echo
    echo "# environment"
    echo "uname=$(uname -a)"
    echo "pwd=$ROOT"
    echo "python=$($PYTHON --version 2>&1 | head -n 1)"
} >"$REPORT"

# Machine-readable companion for CI / doctor tooling.
$PYTHON - "$JSON" "$REPORT" <<'PY'
import json, sys
from pathlib import Path

json_path, report_path = Path(sys.argv[1]), Path(sys.argv[2])
data: dict[str, object] = {}
steps: list[dict[str, object]] = []
for line in report_path.read_text(encoding="utf-8").splitlines():
    if line.startswith("step."):
        # step.name=STATUS rc=N seconds=S :: summary
        try:
            key, rest = line.split("=", 1)
            name = key[len("step."):]
            meta, summary = rest.split(" :: ", 1)
            parts = meta.split()
            status = parts[0]
            rc = int(parts[1].split("=", 1)[1])
            seconds = int(parts[2].split("=", 1)[1])
            steps.append({
                "name": name,
                "status": status,
                "rc": rc,
                "seconds": seconds,
                "summary": summary,
            })
        except Exception:
            continue
    elif "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        data[k] = v
data["steps"] = steps
json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

echo
echo "product_gate: $overall lane=$LANE report=$REPORT json=$JSON logs=$LOG_DIR"
if [ "$overall" != "PASS" ]; then
    echo "product_gate: first fail = $FIRST_FAIL" >&2
    exit 1
fi
