#!/usr/bin/env bash
# Fixture runner: compile every tests/fixtures/<name>/main.xu, run it, and
# compare stdout (+ optional exit code) against expectations.
#
# Fixture layout:
#   main.xu          source
#   expected.txt    expected stdout (positive fixtures)
#   expected.exit   expected exit code (optional, default 0)
#   error.txt       expected compiler stderr (negative fixtures).
#                   Default: substring match (grep -F).
#                   If the fixture name is listed in
#                   docs/audit/SAFETY_DIAG_EXACT.txt (M177/M182), the first
#                   stderr line must equal error.txt exactly (trim).
#                   err_pkg_xun_mismatch keeps substring (absolute path).
#
# Usage:
#   scripts/run_fixtures.sh                       # Rust bootstrap (Gen0)
#   scripts/run_fixtures.sh --xu=/path/to/gen1 --sub=build \
#       --label=gen1 --known-fail=docs/audit/GEN1_FIXTURE_KNOWN_FAIL.txt
#   scripts/run_fixtures.sh --skip-net   # omit net_* / http_* (language gate)
#   scripts/run_fixtures.sh --only='^(parse_int|starts_with)'  # name regex
#
# XU_FIXTURE_EXTRA_ARGS (space-separated) is prepended to every compile
# invocation. run_fixture_matrix.sh sets it per mode (-O0/-O1/.../--no-regcache)
# so the optimization profile actually reaches the compiler.
#
# The same corpus must eventually pass on both ends. Until Gen1 catches up,
# --known-fail lists the fixtures it is allowed to fail; a listed fixture that
# starts passing is reported as FIXED and fails the run, so the list can only
# shrink.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
cd "$ROOT"
source scripts/test_lib.sh

XU=""
SUB=""
LABEL="bootstrap"
KNOWN_FAIL_LIST=""
SKIP_NET=0
ONLY=""
FIXTURE_TIMEOUT=${FIXTURE_TIMEOUT:-30}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) XU="${1#*=}" ;;
        --sub=*) SUB="${1#*=}" ;;
        --label=*) LABEL="${1#*=}" ;;
        --known-fail=*) KNOWN_FAIL_LIST="${1#*=}" ;;
        --only=*) ONLY="${1#*=}" ;;
        --skip-net) SKIP_NET=1 ;;
        *) echo "run_fixtures: unknown arg $1"; exit 1 ;;
    esac
    shift
done

# BOUNDARY: fixture execution is explicitly labelled by --label.  The
# historical default remains the bootstrap oracle; product callers pass a
# product label (gen1/gen2/gen3/product) and an explicit --xu path.  Oracle
# compilation is direct; product compilation is resolved canonically and
# routed through the hermetic product wrapper.
LANE="dual"
case "$LABEL" in
    oracle|bootstrap|primer|gen0) LANE="oracle" ;;
    product|gen1|gen2|gen3) LANE="product" ;;
esac
if [ -n "$XU" ] && [ "$LABEL" = "bootstrap" ]; then
    case "$XU" in
        bootstrap/*|*/bootstrap/*) LANE="oracle" ;;
        *) LANE="product" ;;
    esac
fi
if [ "$LANE" = "product" ] && [ -z "$XU" ]; then
    echo "run_fixtures: lane=product requires an explicit --xu hosted compiler" >&2
    exit 1
fi

HOST_SEED_RESOLVER="$ROOT/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$ROOT/scripts/run_product_compiler.sh"

canonical_path() {
    if command -v realpath >/dev/null 2>&1; then
        realpath "$1"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$1" <<'PY'
import os
import sys
print(os.path.realpath(sys.argv[1]))
PY
        return
    fi
    echo "run_fixtures: cannot canonicalize compiler path (need realpath or python3)" >&2
    return 1
}

has_symlink_component() {
    local candidate=$1 root=$2 rel current part
    case "$candidate" in
        "$root"/*) rel=${candidate#"$root/"} ;;
        *) return 1 ;;
    esac
    [ -L "$root" ] && return 0
    current=$root
    local components=()
    IFS='/' read -r -a components <<< "$rel"
    for part in "${components[@]}"; do
        [ -n "$part" ] || continue
        current="$current/$part"
        [ -L "$current" ] && return 0
    done
    return 1
}

is_frozen_primer_path() {
    # Keep both the lexical candidate and canonical target.  Checking only
    # the resolved path would let an external symlink alias (or a symlinked
    # checkout component) masquerade as this repository's Gen0 artifact.
    local candidate=$1 resolved=${2:-$1} expected root lexical
    root=$(pwd -P)
    case "$candidate" in
        /*) lexical=$candidate ;;
        *) lexical="$root/$candidate" ;;
    esac
    for expected in \
        "$BOOTSTRAP_ROOT/target/debug/xu" \
        "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
        "$BOOTSTRAP_ROOT/target/release/xu" \
        "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
        [ "$lexical" = "$expected" ] || continue
        [ -f "$expected" ] || continue
        [ -x "$expected" ] || continue
        has_symlink_component "$expected" "$BOOTSTRAP_ROOT" && continue
        if [ "$resolved" = "$expected" ]; then
            return 0
        fi
    done
    return 1
}

python3 scripts/check_ncall_registry.py || { echo "ncall registry check failed"; exit 1; }
python3 scripts/check_crypto_constant_time.py || { echo "crypto constant-time contract check failed"; exit 1; }

if [ -z "$XU" ]; then
    cargo build --quiet --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -p xu || { echo "xu build failed"; exit 1; }
    XU=""
    for primer in \
        "$BOOTSTRAP_ROOT/target/debug/xu" \
        "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
        "$BOOTSTRAP_ROOT/target/release/xu" \
        "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
        if [ -x "$primer" ]; then
            XU="$primer"
            break
        fi
    done
    [ -n "$XU" ] || { echo "run_fixtures: bootstrap compiler missing after build" >&2; exit 1; }
elif [ "$LANE" = "product" ]; then
    # Do not let a product-labelled fixture run use a primer through a
    # symlink or a stale relative path.  The resolver also canonicalises the
    # hosted seed for reproducible diagnostics.
    if ! XU=$(XU_ALLOW_ORACLE_SEED=0 XU_SEED="$XU" "$HOST_SEED_RESOLVER"); then
        echo "run_fixtures: product lane requires a hosted compiler; bootstrap is oracle-only" >&2
        exit 1
    fi
fi
BIN="$XU"
if [ "$LANE" = "oracle" ]; then
    ORACLE_CANDIDATE="$BIN"
    BIN=$(canonical_path "$BIN") || exit 1
    is_frozen_primer_path "$ORACLE_CANDIDATE" "$BIN" || {
        echo "run_fixtures: oracle lane requires the frozen bootstrap primer (bootstrap/target/{debug,release}/xu[.exe])" >&2
        exit 1
    }
fi
case "$LANE" in
    oracle) echo "run_fixtures: lane=oracle (bootstrap primer; non-product evidence)" >&2 ;;
    product) echo "run_fixtures: lane=product (explicit compiler/label)" >&2 ;;
    *) echo "run_fixtures: lane=dual (custom compiler label; compare explicitly)" >&2 ;;
esac

compile_source() {
    # XU_FIXTURE_EXTRA_ARGS is the matrix/optimization seam: one space-separated
    # flag list prepended to every compile (e.g. "-O0", "--no-regcache").
    # Intentionally unquoted so multiple flags split; empty is a no-op.
    # shellcheck disable=SC2086
    local extra=(${XU_FIXTURE_EXTRA_ARGS-})
    if [ "$LANE" = "product" ]; then
        # Product Xu uses the hosted `build` subcommand.  Keep the legacy
        # direct path for oracle/dual diagnostics only.
        XU_PRODUCT_XUPATH="${XUPATH-}" \
            "$PRODUCT_COMPILER_RUNNER" "$BIN" build ${extra[@]+"${extra[@]}"} "$@"
    else
        "$BIN" $SUB ${extra[@]+"${extra[@]}"} "$@"
    fi
}

# M177: safety fixtures requiring exact first-line stderr.
SAFETY_EXACT_LIST="$ROOT/docs/audit/SAFETY_DIAG_EXACT.txt"
is_safety_exact() {
    local n="$1"
    [ -f "$SAFETY_EXACT_LIST" ] || return 1
    grep -qxF "$n" "$SAFETY_EXACT_LIST"
}

is_known_fail() {
    local n="$1"
    [ -n "$KNOWN_FAIL_LIST" ] || return 1
    [ -f "$KNOWN_FAIL_LIST" ] || return 1
    grep -v '^[[:space:]]*#' "$KNOWN_FAIL_LIST" | grep -qxF "$n"
}

. ./scripts/lang_gate_skip.sh

pass=0
fail=0
known=0
fixed=0
skipped=0

record_pass() {
    local n="$1"
    if is_known_fail "$n"; then
        echo "FIXED $n (listed in $KNOWN_FAIL_LIST but now passes — remove it)"
        fixed=$((fixed + 1))
    else
        echo "PASS $n"
        pass=$((pass + 1))
    fi
}

# record_fail <name> <reason> [detail]
record_fail() {
    local n="$1" reason="$2" detail="${3-}"
    if is_known_fail "$n"; then
        echo "KNOWN-FAIL $n ($reason)"
        known=$((known + 1))
    else
        echo "FAIL $n ($reason)"
        [ -n "$detail" ] && printf '%s\n' "$detail" | sed 's/^/  /'
        fail=$((fail + 1))
    fi
}

for dir in tests/fixtures/*/; do
    name=$(basename "$dir")
    dir="${dir%/}"
    if [ -n "$ONLY" ]; then
        # Unanchored ERE over the fixture name (same contract as matrix/heap-check).
        if ! printf '%s\n' "$name" | grep -Eq "$ONLY"; then
            continue
        fi
    fi
    if [ ! -f "$dir/main.xu" ] && [ ! -f "$dir/error.txt" ]; then
        echo "SKIP $name (no main.xu; library source)"
        skipped=$((skipped + 1))
        continue
    fi
    if [ "$SKIP_NET" = "1" ] && lang_gate_skip_fixture "$name"; then
        echo "SKIP $name (net package; not language-compiler gate)"
        skipped=$((skipped + 1))
        continue
    fi
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    http_pid=""
    save_cache="${XU_CACHE-}"

    if [ -f "$dir/error.txt" ]; then
        # Negative fixture: compilation must fail with the expected message.
        inputs="$dir/main.xu"
        for extra in "$dir"/*.xu; do
            [ -f "$extra" ] || continue
            [ "$extra" = "$dir/main.xu" ] && continue
            inputs="$inputs $extra"
        done
        for extra in "$dir"/*/*.xu; do
            [ -f "$extra" ] || continue
            inputs="$inputs $extra"
        done
        extra_target=""
        if [ -f "$dir/target.txt" ]; then
            extra_target="--target $(tr -d '[:space:]' < "$dir/target.txt")"
        fi
        if compile_source $inputs $extra_target -o "$tmp/a.out" 2>"$tmp/stderr"; then
            record_fail "$name" "expected compile error, compilation succeeded"
        elif is_safety_exact "$name"; then
            actual=$(head -1 "$tmp/stderr" | tr -d '\r' | sed 's/[[:space:]]*$//')
            expected=$(tr -d '\r' <"$dir/error.txt" | sed 's/[[:space:]]*$//' | head -1)
            if [ "$actual" != "$expected" ]; then
                record_fail "$name" "exact error mismatch, M177" \
                    "expected: $expected
actual:   $actual"
            else
                record_pass "$name"
            fi
        elif ! grep -qF "$(cat "$dir/error.txt")" "$tmp/stderr"; then
            record_fail "$name" "error mismatch" \
                "expected substring: $(cat "$dir/error.txt")
actual stderr:      $(cat "$tmp/stderr")"
        else
            record_pass "$name"
        fi
        rm -rf "$tmp"
        continue
    fi

    if [ -f "$dir/warning.txt" ]; then
        # M36 warning fixture: compilation must SUCCEED with the expected
        # warning substring on stderr; the binary must then run and match
        # expected.txt with exit 0 (warnings never affect the exit code).
        inputs="$dir/main.xu"
        for extra in "$dir"/*.xu; do
            [ -f "$extra" ] || continue
            [ "$extra" = "$dir/main.xu" ] && continue
            inputs="$inputs $extra"
        done
        for extra in "$dir"/*/*.xu; do
            [ -f "$extra" ] || continue
            inputs="$inputs $extra"
        done
        if ! compile_source $inputs -o "$tmp/a.out" 2>"$tmp/stderr"; then
            record_fail "$name" "warning fixture failed to compile" "$(cat "$tmp/stderr")"
            rm -rf "$tmp"
            continue
        fi
        if ! grep -qF "$(cat "$dir/warning.txt")" "$tmp/stderr"; then
            record_fail "$name" "warning mismatch" \
                "expected substring: $(cat "$dir/warning.txt")
actual stderr:      $(cat "$tmp/stderr")"
            rm -rf "$tmp"
            continue
        fi
        chmod +x "$tmp/a.out" 2>/dev/null
        set +e
        (cd "$tmp" && run_with_timeout "$FIXTURE_TIMEOUT" ./a.out) >"$tmp/stdout" 2>/dev/null
        code=$?
        set -e
        if [ "$code" -eq 124 ]; then
            record_fail "$name" "timeout after ${FIXTURE_TIMEOUT}s"
        elif [ "$code" -ne 0 ] || ! diff -q "$dir/expected.txt" "$tmp/stdout" >/dev/null; then
            record_fail "$name" "run exit=$code or stdout mismatch" \
                "$(diff "$dir/expected.txt" "$tmp/stdout")"
        else
            record_pass "$name"
        fi
        rm -rf "$tmp"
        continue
    fi

    # M183: local HTTP server for require: http:// locators.
    if [ "$name" = "require_http" ]; then
        cp -r "$dir" "$tmp/require_http_fixture"
        dir="$tmp/require_http_fixture"
        start_http_server "$dir/www" "$tmp/http.port" || {
            record_fail "$name" "http.server did not start"
            if [ -n "${save_cache}" ]; then export XU_CACHE="$save_cache"; else unset XU_CACHE; fi
            rm -rf "$tmp"
            continue
        }
        HTTP_PORT=$(cut -d: -f1 < "$tmp/http.port")
        http_pid=$(cut -d: -f2 < "$tmp/http.port")
        sed -i.bak "s/19883/$HTTP_PORT/g" "$dir/xu.xun"
        if [ "$LANE" = product ]; then
            python3 scripts/prepare_require_http_fixture.py "$dir"
        fi
        export XU_CACHE="$tmp/xu_cache"
    fi

    inputs="$dir/main.xu"
    for extra in "$dir"/*.xu; do
        [ -f "$extra" ] || continue
        [ "$extra" = "$dir/main.xu" ] && continue
        inputs="$inputs $extra"
    done
    for extra in "$dir"/*/*.xu; do
        [ -f "$extra" ] || continue
        case "$extra" in
            */www/*) continue ;;
        esac
        inputs="$inputs $extra"
    done
    # M18: optional XUPATH for package search (paths relative to fixture dir).
    save_xupath="${XUPATH-}"
    if [ -f "$dir/xupath.txt" ]; then
        qp=""
        while IFS= read -r line || [ -n "$line" ]; do
            [ -z "$line" ] && continue
            case "$line" in
                /*) abs="$line" ;;
                *) abs="$dir/$line" ;;
            esac
            if [ -z "$qp" ]; then qp="$abs"; else qp="$qp:$abs"; fi
        done < "$dir/xupath.txt"
        export XUPATH="$qp"
    fi
    if ! compile_source $inputs -o "$tmp/a.out" 2>"$tmp/stderr"; then
        record_fail "$name" "compilation failed" "$(cat "$tmp/stderr")"
        if [ -f "$dir/xupath.txt" ]; then
            if [ -n "${save_xupath}" ]; then export XUPATH="$save_xupath"; else unset XUPATH; fi
        fi
        if [ -n "$http_pid" ]; then
            kill "$http_pid" 2>/dev/null || true
            wait "$http_pid" 2>/dev/null || true
        fi
        if [ "$name" = "require_http" ]; then
            if [ -n "${save_cache}" ]; then export XU_CACHE="$save_cache"; else unset XU_CACHE; fi
        fi
        rm -rf "$tmp"
        continue
    fi
    if [ -f "$dir/xupath.txt" ]; then
        if [ -n "${save_xupath}" ]; then export XUPATH="$save_xupath"; else unset XUPATH; fi
    fi
    chmod +x "$tmp/a.out" 2>/dev/null

    extra_args=""
    if [ -f "$dir/args.txt" ]; then
        extra_args=$(cat "$dir/args.txt")
    fi
    # SIGSEGV is 139; with set -e the script would abort mid-corpus.
    set +e
    (cd "$tmp" && run_with_timeout "$FIXTURE_TIMEOUT" ./a.out $extra_args) >"$tmp/stdout" 2>"$tmp/stderr"
    code=$?
    set -e

    expected_exit=0
    if [ -f "$dir/expected.exit" ]; then
        expected_exit=$(tr -d '[:space:]' <"$dir/expected.exit")
    fi

    expected_stderr=""
    if [ -f "$dir/expected.stderr" ]; then
        expected_stderr="$dir/expected.stderr"
    fi
    result_kind=$(fixture_runtime_result_kind \
        "$code" "$expected_exit" "$dir/expected.txt" "$tmp/stdout" \
        "$expected_stderr" "$tmp/stderr")
    case "$result_kind" in
        timeout)
            record_fail "$name" "timeout after ${FIXTURE_TIMEOUT}s"
            ;;
        exit)
            record_fail "$name" "exit code: got $code, want $expected_exit"
            ;;
        stdout)
            record_fail "$name" "stdout mismatch" "$(diff "$dir/expected.txt" "$tmp/stdout")"
            ;;
        stderr)
            record_fail "$name" "stderr mismatch" "$(diff "$dir/expected.stderr" "$tmp/stderr")"
            ;;
        pass)
            record_pass "$name"
            ;;
        *)
            echo "run_fixtures: internal result kind '$result_kind'" >&2
            exit 1
            ;;
    esac
    if [ -n "$http_pid" ]; then
        kill "$http_pid" 2>/dev/null || true
        wait "$http_pid" 2>/dev/null || true
    fi
    if [ "$name" = "require_http" ]; then
        if [ -n "${save_cache}" ]; then export XU_CACHE="$save_cache"; else unset XU_CACHE; fi
    fi
    rm -rf "$tmp"
done

echo
summary="fixtures[$LABEL] lane=$LANE: PASS=$pass FAIL=$fail"
[ -n "$KNOWN_FAIL_LIST" ] && summary="$summary KNOWN-FAIL=$known FIXED=$fixed"
[ "$skipped" -gt 0 ] && summary="$summary SKIP=$skipped"
echo "$summary"
if [ "$fixed" -gt 0 ]; then
    echo "run_fixtures: $fixed fixture(s) listed in $KNOWN_FAIL_LIST now pass — remove them from the list"
fi
[ "$fail" -eq 0 ] && [ "$fixed" -eq 0 ]
