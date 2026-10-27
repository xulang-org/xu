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
#   scripts/run_fixtures.sh                       # hosted product compiler
#   scripts/run_fixtures.sh --xu=/path/to/gen1 --sub=build \
#       --label=gen1 --known-fail=docs/audit/GEN1_FIXTURE_KNOWN_FAIL.txt
#   scripts/run_fixtures.sh --skip-require  # cold Gen1; replay with --only-require after fixed point
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
export XU_ROOT="$ROOT"
# Only a fixture's xupath.txt may add package roots. An installed SDK in the
# caller's environment must not shadow this checkout or fail product isolation.
unset XUPATH
cd "$ROOT"
source scripts/test_lib.sh

XU=""
SUB="build"
LABEL="product"
KNOWN_FAIL_LIST=""
SKIP_NET=0
SKIP_REQUIRE=0
ONLY_REQUIRE=0
ONLY=""
TARGET=""
RUNNER=""
FIXTURE_TIMEOUT=${FIXTURE_TIMEOUT:-30}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) XU="${1#*=}" ;;
        --sub=*) SUB="${1#*=}" ;;
        --label=*) LABEL="${1#*=}" ;;
        --known-fail=*) KNOWN_FAIL_LIST="${1#*=}" ;;
        --only=*) ONLY="${1#*=}" ;;
        --target=*) TARGET="${1#*=}" ;;
        --runner=*) RUNNER="${1#*=}" ;;
        --skip-net) SKIP_NET=1 ;;
        --skip-require) SKIP_REQUIRE=1 ;;
        --only-require) ONLY_REQUIRE=1 ;;
        *) echo "run_fixtures: unknown arg $1"; exit 1 ;;
    esac
    shift
done

HOST_SEED_RESOLVER="$ROOT/scripts/xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER="$ROOT/scripts/run_product_compiler.sh"
XU=$(XU_SEED="$XU" "$HOST_SEED_RESOLVER")
BIN="$XU"
LANE=product
python3 scripts/check_ncall_registry.py
python3 scripts/check_crypto_constant_time.py
echo "run_fixtures: lane=product compiler=$BIN" >&2

compile_source() {
    # The matrix supplies a space-separated list of optimization flags.
    local extra=(${XU_FIXTURE_EXTRA_ARGS-})
    if [ -n "$TARGET" ]; then extra+=(--target "$TARGET"); fi
    XU_PRODUCT_XUPATH="${XUPATH-}" \
        "$PRODUCT_COMPILER_RUNNER" "$BIN" "$SUB" ${extra[@]+"${extra[@]}"} "$@"
}

runner_args=()
if [ -n "$RUNNER" ]; then runner_args+=("$RUNNER"); fi

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
        library_source=0
        for source in "$dir"/*.xu; do
            if [ -f "$source" ]; then library_source=1; break; fi
        done
        if [ "$library_source" = 1 ]; then
            echo "SKIP $name (no main.xu; library source)"
            skipped=$((skipped + 1))
        else
            record_fail "$name" "no main.xu or library source"
        fi
        continue
    fi
    requires=0
    if [ -f "$dir/xu.xun" ] && grep -q '^require:' "$dir/xu.xun"; then requires=1; fi
    if [ "$ONLY_REQUIRE" = 1 ] && [ "$requires" = 0 ]; then continue; fi
    if [ "$SKIP_REQUIRE" = 1 ] && [ "$requires" = 1 ]; then
        echo "SKIP $name (dependency features are checked after the hosted fixed point)"
        skipped=$((skipped + 1))
        continue
    fi
    external_packages=0
    if [ "$requires" = 1 ] && grep -q 'github.com/xulang-org/packages' "$dir/xu.xun"; then external_packages=1; fi

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
        (cd "$tmp" && run_with_timeout "$FIXTURE_TIMEOUT" ${runner_args[@]+"${runner_args[@]}"} ./a.out) >"$tmp/stdout" 2>/dev/null
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

    if [ "$external_packages" = 1 ]; then
        if ! python3 scripts/prepare_packages_fixture.py "$dir" "$tmp/external_fixture" 2>"$tmp/stderr"; then
            record_fail "$name" "external package fixture unavailable" "$(cat "$tmp/stderr")"
            rm -rf "$tmp"
            continue
        fi
        dir="$tmp/external_fixture"
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
        if [ "$LANE" = product ] || [ "$SUB" = build ]; then
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
    (cd "$tmp" && run_with_timeout "$FIXTURE_TIMEOUT" ${runner_args[@]+"${runner_args[@]}"} ./a.out $extra_args) >"$tmp/stdout" 2>"$tmp/stderr"
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
