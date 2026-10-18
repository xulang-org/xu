#!/usr/bin/env bash
# Optimization-level / register-allocation differential matrix over the
# fixture corpus (T0.2 in OVERALL_OPTIMIZATION_PLAN_2026-09.md).
#
# The Gen3 == Gen4 fixed point cannot detect a deterministic miscompile and a
# single-mode fixture run only sees the default profile.  This harness runs
# scripts/run_fixtures.sh once per compiler mode (via XU_FIXTURE_EXTRA_ARGS)
# and then joins the per-fixture verdicts:
#
#   PASS      every mode matches the golden output
#   FAIL      every mode fails the same fixture (a corpus/compiler problem
#             independent of the mode)
#   DIVERGE   the verdict depends on the mode (an optimization/RA bug; the
#             historical `matmul -O2 prints 0` and `array_index_rw 0,99,0,99`
#             classes)
#
# Usage:
#   scripts/run_fixture_matrix.sh --xu=bin/xu                 # full corpus x 5 modes
#   scripts/run_fixture_matrix.sh --xu=bin/xu --quick         # RA/opt-sensitive subset
#   scripts/run_fixture_matrix.sh --xu=bin/xu --modes='-O0,-O1,-O3,--no-regcache,--ra=0'
#   scripts/run_fixture_matrix.sh --xu=bin/xu --only='^(matmul|nbody|copy_)' --skip-net
#   scripts/run_fixture_matrix.sh --xu=bin/xu --out=/tmp/matrix   # keep per-mode logs
#
# --xu selects the hosted compiler through xu_host_seed.sh. Each mode
# compares against fixture expectations; this is separate from the fixed point.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
export XU_ROOT="$ROOT"
cd "$ROOT"
LANE=product

XU_INPUT=""
MODES="-O0,-O1,-O2,-O3,--no-regcache"
ONLY=""
QUICK=0
SKIP_NET=0
OUT=""
LABEL="matrix"
QUICK_ONLY='^(emission_|matmul|nbody|copy_|vreg_|sroa_|lism_|mir_lism_|mir_fnval_|mir_cse_|mir_late_const_|mir_scalar_int_|scalar_int_|scalar_call_|scalar_inline_|mir_empty_tail_|mir_effect_|array_|bounds_|loop_|while_|for_|map_|iface_|interface_|generic_|enum_|struct_|chan_|select_|compound_|div_|sdiv_|math_|string_|str_|slice|index_|err_index|err_bounds|err_f64_|err_intfield_|image_|search|sort|heap|bits_|f64_|float|bool_|compare_logic$|short_circuit_|optimizer_name_|match_|closure|fn_val|fnval_|method_|recursion|fib)'
while [ "$#" -gt 0 ]; do
    case "$1" in
        --xu=*) XU_INPUT="${1#*=}" ;;
        --modes=*) MODES="${1#*=}" ;;
        --only=*) ONLY="${1#*=}" ;;
        --quick) QUICK=1 ;;
        --skip-net) SKIP_NET=1 ;;
        --out=*) OUT="${1#*=}" ;;
        --label=*) LABEL="${1#*=}" ;;
        -h|--help)
            sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "run_fixture_matrix: unknown arg $1" >&2; exit 1 ;;
    esac
    shift
done

if [ -z "$XU_INPUT" ]; then
    echo "run_fixture_matrix: --xu=<hosted compiler> is required (no primer/cargo fallback)" >&2
    exit 1
fi
if ! XU=$(XU_SEED="$XU_INPUT" ./scripts/xu_host_seed.sh); then
    echo "run_fixture_matrix: compiler rejected by hosted product policy: $XU_INPUT" >&2
    exit 1
fi
SEED_LANE=hosted
if [ "$QUICK" = 1 ] && [ -z "$ONLY" ]; then
    ONLY="$QUICK_ONLY"
fi

if [ -z "$OUT" ]; then
    OUT=$(mktemp -d "${TMPDIR:-/tmp}/xu-fixture-matrix.XXXXXX")
    CLEAN_OUT=1
else
    mkdir -p "$OUT"
    CLEAN_OUT=0
fi
STATUS=FAIL
cleanup() {
    local rc=$?
    if [ "$CLEAN_OUT" = 1 ] && [ "$rc" -eq 0 ]; then
        rm -rf -- "$OUT"
    else
        echo "run_fixture_matrix: per-mode logs in $OUT" >&2
    fi
    echo "run_fixture_matrix: $STATUS lane=$LANE seed_lane=$SEED_LANE"
    return "$rc"
}
trap cleanup EXIT

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        sha256sum "$1" | awk '{print $1}'
    fi
}

echo "run_fixture_matrix: lane=$LANE seed_lane=$SEED_LANE"
echo "run_fixture_matrix: xu=$XU sha256=$(sha256_file "$XU")"
echo "run_fixture_matrix: modes=$MODES only=${ONLY:-<all>} skip_net=$SKIP_NET"

IFS=',' read -r -a MODE_LIST <<< "$MODES"
mode_files=()
for mode in "${MODE_LIST[@]}"; do
    [ -n "$mode" ] || continue
    tag=$(printf '%s' "$mode" | tr -c 'A-Za-z0-9' '_')
    log="$OUT/mode$tag.log"
    args=(--xu="$XU" --sub=build --label="$LABEL")
    [ -n "$ONLY" ] && args+=(--only="$ONLY")
    [ "$SKIP_NET" = 1 ] && args+=(--skip-net)
    echo "run_fixture_matrix: mode [$mode] ..."
    set +e
    # Hosted compilers use build; the frozen oracle uses its file-first CLI.
    # The extra compiler flags are the only thing changing between modes.
    XU_FIXTURE_EXTRA_ARGS="$mode" ./scripts/run_fixtures.sh "${args[@]}" >"$log" 2>&1
    rc=$?
    set -e
    summary=$(grep -E '^fixtures\[' "$log" | tail -1 || true)
    echo "run_fixture_matrix: mode [$mode] rc=$rc ${summary:-<no summary; see $log>}"
    if [ -z "$summary" ]; then
        tail -20 "$log" >&2
        exit 1
    fi
    # Compiler options can contain '=' (for example --ra=0); keep the
    # mode/path delimiter distinct from option syntax and path names.
    mode_files+=("$mode"$'\t'"$log")
done

# Join per-mode verdicts.  PASS/FAIL/KNOWN-FAIL/FIXED lines come from
# run_fixtures; SKIP lines are ignored (same on every mode).
set +e
python3 - "$OUT/matrix.tsv" "${mode_files[@]}" <<'PY'
import re
import sys

out_path = sys.argv[1]
modes = []
verdicts = {}
line_re = re.compile(r"^(PASS|FAIL|KNOWN-FAIL|FIXED) (\S+)(?: \((.*)\))?$")
for spec in sys.argv[2:]:
    mode, _, path = spec.partition("\t")
    modes.append(mode)
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = line_re.match(line.rstrip("\n"))
            if not m:
                continue
            status, name, reason = m.group(1), m.group(2), m.group(3) or ""
            verdicts.setdefault(name, {})[mode] = (status, reason)

n_pass = n_fail = n_div = 0
rows = []
for name in sorted(verdicts):
    per = verdicts[name]
    statuses = {per.get(m, ("MISSING", ""))[0] for m in modes}
    if statuses == {"PASS"}:
        kind = "PASS"
        n_pass += 1
    elif "PASS" in statuses or "MISSING" in statuses:
        kind = "DIVERGE"
        n_div += 1
    else:
        kind = "FAIL"
        n_fail += 1
    cells = []
    for m in modes:
        status, reason = per.get(m, ("MISSING", ""))
        cells.append(status if not reason else f"{status}[{reason}]")
    rows.append((kind, name, cells))

with open(out_path, "w", encoding="utf-8") as fh:
    fh.write("kind\tfixture\t" + "\t".join(modes) + "\n")
    for kind, name, cells in rows:
        fh.write(f"{kind}\t{name}\t" + "\t".join(cells) + "\n")

for kind, name, cells in rows:
    if kind != "PASS":
        print(f"{kind} {name}")
        for m, c in zip(modes, cells):
            print(f"    {m:16s} {c}")
print(f"matrix: modes={len(modes)} fixtures={len(rows)} pass={n_pass} fail={n_fail} diverge={n_div}")
sys.exit(0 if (n_fail == 0 and n_div == 0) else 1)
PY
rc=$?
set -e
echo "run_fixture_matrix: table=$OUT/matrix.tsv"
if [ "$rc" -eq 0 ]; then
    STATUS=PASS
fi
exit "$rc"
