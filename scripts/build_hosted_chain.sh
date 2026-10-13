#!/usr/bin/env bash
# Hosted self-host chain: seed → gen1 → gen2 (warm-up) → gen3.
# If gen2 == gen3, install gen3; otherwise build gen4 and require gen3 == gen4.
# No cargo to compile the compiler.
# After install: sibling tools, then cross product xu into
# bin/platform/<os>-<arch>/ (XU_SKIP_CROSS=1 to skip).
#
# Usage: scripts/build_hosted_chain.sh [--candidate-only] <seed-xu> [dest-xu]
#
# The seed is checked by xu_host_seed.sh even when this script is called
# directly (rather than through Makefile).  Thus passing the Rust primer by
# accident cannot turn an oracle build into a product build.  For an explicit
# oracle/recovery run, name the primer and set XU_ALLOW_ORACLE_SEED=1; the
# script prints a warning and the resulting artifact must not be release
# evidence.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
BOOTSTRAP_ROOT=$("$ROOT/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$ROOT"
python3 scripts/check_module_paths.py

CANDIDATE_ONLY=0
if [ "${1:-}" = --candidate-only ]; then
    CANDIDATE_ONLY=1
    shift
fi
if [ "$#" -lt 1 ]; then
    echo "usage: scripts/build_hosted_chain.sh [--candidate-only] <seed-xu> [dest-xu]" >&2
    exit 1
fi

SEED_INPUT=$1
DEST=${2:-bin/xu}
if [ "$CANDIDATE_ONLY" = 1 ] && [ "$#" -lt 2 ]; then
    echo "build_hosted_chain: --candidate-only requires an explicit artifact destination" >&2
    exit 1
fi
SEED_LANE=product
# Reuse the single seed policy implementation.  XU_SEED is scoped to this
# child invocation; the caller's environment remains untouched after exit.
if ! SEED=$(XU_SEED="$SEED_INPUT" ./scripts/xu_host_seed.sh); then
    echo "build_hosted_chain: seed rejected by hosted/oracle boundary: $SEED_INPUT" >&2
    exit 1
fi
case "$SEED" in
    "$BOOTSTRAP_ROOT"|"$BOOTSTRAP_ROOT"/*)
        SEED_LANE=oracle
        ;;
esac

# Recovery provenance follows hosted descendants as well as primer paths.
if [ -f "${SEED}.provenance" ] && [ "$(awk -F= '/^lane=/{print $2; exit}' "${SEED}.provenance")" = oracle ]; then
    SEED_LANE=oracle
fi

. ./scripts/gen1_sources.sh

tmp=$(mktemp -d "${TMPDIR:-/tmp}/xu-hosted-chain.XXXXXX")
KEEP_FAILURES=${HOSTED_CHAIN_KEEP_FAILURES:-0}
FAILED_STAGE=""
cleanup() {
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "build_hosted_chain: chain BLOCKED lane=$SEED_LANE stage=${FAILED_STAGE:-unknown} exit=$rc" >&2
        if [ "$KEEP_FAILURES" = 1 ]; then
            echo "build_hosted_chain: preserved failure artifacts in $tmp" >&2
        else
            rm -rf -- "$tmp"
        fi
    else
        rm -rf -- "$tmp"
    fi
    # EXIT traps must not turn a failing compiler hop into a successful chain.
    return "$rc"
}
trap cleanup EXIT

# A compiler process can load additional source roots through XUPATH and
# `require:` packages through XU_CACHE.  Those ambient values are outside the
# self-host contract and make Gen1/Gen2/Gen3/Gen4 non-reproducible (or let a local
# checkout inject shadow sources).  Build with a deterministic, empty search
# root and an isolated package cache instead.  XUOS/XUARCH are also cleared:
# the hosted chain must produce a runnable compiler for this host; cross
# targets are built explicitly by build_platform_xu.sh afterwards.
export LC_ALL=C
export XUPATH=""
native_path() {
    python3 -c 'from pathlib import Path; import sys; sys.stdout.write(Path(sys.argv[1]).resolve().as_posix())' "$1"
}
export XU_STDLIB_ROOT="$(native_path "$ROOT/src")"
export XU_CACHE="$tmp/xu-cache"
# Keep legacy hosted binaries that still fall back from XU_CACHE to HOME from
# seeing the developer's package tree.  This also makes `require:` failures
# deterministic instead of accidentally succeeding from ~/.xu/pkg.
export HOME="$tmp/home"
export USERPROFILE="$HOME"
mkdir -p "$XU_CACHE" "$HOME"
export XU_CACHE="$(native_path "$XU_CACHE")"
export HOME="$(native_path "$HOME")"
export USERPROFILE="$HOME"
unset XUOS XUARCH XU_BOOT_EXTRA XU_HEAP_STATS XU_SEED XU_ALLOW_ORACLE_SEED

# Keep the product chain on the compiler's versioned defaults.  The explicit
# acceptance profile is available for deterministic vreg/SSA gates and must
# be selected by the caller; every hosted hop uses exactly the same arguments
# so a fixed-point comparison cannot mix profiles.  Gen2 is a deliberate
# warm-up: the O0 primer can expose a one-time lowering/optimization
# transition.  Confirm Gen2→Gen3 first; a transition needs Gen3→Gen4 confirmation.
HOSTED_PROFILE=${HOSTED_PROFILE:-product}
case "$HOSTED_PROFILE" in
    product)
        HOSTED_ARGS=()
        ;;
    acceptance)
        HOSTED_ARGS=(-O1 --ra=1)
        ;;
    *)
        echo "build_hosted_chain: unknown HOSTED_PROFILE=$HOSTED_PROFILE (want product or acceptance)" >&2
        exit 1
        ;;
esac

# Keep release evidence machine-readable.  The chain removes its temporary
# binaries on success, so the sidecar written after installation below binds
# the installed candidate to the source closure, profile, target and stage
# hashes.
sha256_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
        return
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
        return
    fi
    echo "build_hosted_chain: no SHA-256 utility (need shasum or sha256sum)" >&2
    return 1
}

# Never install a product binary inside the frozen primer tree.  Resolve the
# destination's existing path (or its parent when it does not exist) without
# relying on lexical spelling, so `bootstrap/../bin` and symlinks are covered.
canonical_path() {
    if command -v realpath >/dev/null 2>&1; then
        # BSD realpath may require the final component to exist.  Try it
        # first, then fall through to Python for a not-yet-created DEST.
        if resolved=$(realpath "$1" 2>/dev/null); then
            printf '%s\n' "$resolved"
            return 0
        fi
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$1" <<'PY'
import os
import sys

print(os.path.realpath(sys.argv[1]))
PY
        return
    fi
    echo "build_hosted_chain: cannot canonicalize destination (need realpath or python3)" >&2
    return 1
}

dest_abs=$(canonical_path "$DEST") || exit 1
case "$dest_abs" in
    "$BOOTSTRAP_ROOT"|"$BOOTSTRAP_ROOT"/*)
        echo "build_hosted_chain: refusing to install product into frozen bootstrap tree: $DEST" >&2
        exit 1
        ;;
esac

if [ "$CANDIDATE_ONLY" = 1 ]; then
    case "$dest_abs" in
        "$ROOT/bin"|"$ROOT/bin"/*|"$ROOT/developer/bin"|"$ROOT/developer/bin"/*)
            echo "build_hosted_chain: candidate destination must be outside product directories" >&2
            exit 1 ;;
    esac
fi

is_product_destination() {
    case "$1" in
        "$ROOT/bin/xu"|"$ROOT/bin/xu."*|"$ROOT/bin/xu.exe"|\
        "$ROOT/developer/bin/xu."*|"$ROOT/developer/bin/xu."*.exe)
            return 0 ;;
        *)
            return 1 ;;
    esac
}
if [ "$SEED_LANE" = "oracle" ] && is_product_destination "$dest_abs"; then
    if [ "${XU_ALLOW_ORACLE_INSTALL:-0}" != 1 ]; then
        echo "build_hosted_chain: refusing to install oracle-derived artifact as product: $DEST" >&2
        echo "build_hosted_chain: use a temporary destination, or explicitly set XU_ALLOW_ORACLE_INSTALL=1 for recovery" >&2
        exit 1
    fi
    echo "build_hosted_chain: WARNING oracle-derived product destination explicitly enabled; non-release evidence" >&2
fi

pick_bin() {
    if [ -x "$1" ]; then
        echo "$1"
        return 0
    fi
    if [ -x "${1}.exe" ]; then
        echo "${1}.exe"
        return 0
    fi
    echo "build_hosted_chain: missing $1 after compile" >&2
    ls -la "$(dirname "$1")" >&2 || true
    exit 1
}

if [ "$SEED_LANE" = "oracle" ]; then
    echo "build_hosted_chain: lane=oracle/recovery (non-product evidence)" >&2
else
    echo "build_hosted_chain: lane=product (hosted seed)"
fi
echo "build_hosted_chain: seed=$SEED"
echo "build_hosted_chain: hosted_profile=$HOSTED_PROFILE"
cat >"$tmp/provenance.env" <<EOF
lane=$SEED_LANE
seed=$SEED
hosted_profile=$HOSTED_PROFILE
source_seed_count=$(printf '%s\n' $GEN1_SRCS | wc -w | tr -d ' ')
EOF

# Obtain the exact source-manifest hashes used by the strict boundary checker.
# A hosted chain without this information is still useful for diagnosis, but
# it must not be reported as release evidence.
BOUNDARY_JSON="$tmp/boundary.json"
SOURCE_MANIFEST_STATUS="UNAVAILABLE"
SOURCE_SEED_SHA256="unknown"
SOURCE_CLOSURE_SHA256="unknown"
SOURCE_SEED_FILES="unknown"
SOURCE_CLOSURE_FILES="unknown"
REPO_HEAD="unknown"
if command -v python3 >/dev/null 2>&1; then
    if python3 scripts/check_bootstrap_xu_boundary.py --strict-freeze --json >"$BOUNDARY_JSON"; then
        MANIFEST_INFO=$(python3 - "$BOUNDARY_JSON" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    report = json.load(fh)
source = report.get("source_manifest", {})
print("|".join([
    "PASS" if source.get("complete") else "INCOMPLETE",
    str(source.get("seed_sha256", "unknown")),
    str(source.get("closure_sha256", "unknown")),
    str(source.get("seed_files", "unknown")),
    str(source.get("closure_files", "unknown")),
    str(report.get("repo_head", "unknown")),
]))
PY
        )
        IFS='|' read -r SOURCE_MANIFEST_STATUS SOURCE_SEED_SHA256 \
            SOURCE_CLOSURE_SHA256 SOURCE_SEED_FILES SOURCE_CLOSURE_FILES \
            REPO_HEAD <<EOF
$MANIFEST_INFO
EOF
    fi
fi
if [ "$SOURCE_MANIFEST_STATUS" != "PASS" ]; then
    echo "build_hosted_chain: source manifest unavailable/incomplete; refusing release chain" >&2
    exit 1
fi

# shellcheck disable=SC2086
FAILED_STAGE="gen0_to_gen1"
# Older seeds need an isolated declaration bridge for the first hop only.
# Gen1/Gen2/Gen3 read real slash sources; source provenance remains bound to
# the repository, and the bridge never rewrites function bodies or imports.
SEED_SRCS=($GEN1_SRCS)
SEED_SYNTAX_BRIDGE=none
mkdir -p "$tmp/syntax-probe/seed_probe/slash"
printf '@seed_probe/slash\npub fn value() int { << 0 }\n' >"$tmp/syntax-probe/seed_probe/slash/mod.xu"
printf '@main\n#seed_probe/slash\nfn main() int { << slash.value() }\n' >"$tmp/syntax-probe/main.xu"
if ! "$SEED" check "$tmp/syntax-probe/main.xu" >"$tmp/syntax-probe.log" 2>&1; then
    SEED_SYNTAX_BRIDGE=slash-declarations-to-dots
    python3 scripts/stage_seed_syntax.py --source-root src --dest-root "$tmp/seed-input/src"
    export XU_STDLIB_ROOT="$(native_path "$tmp/seed-input/src")"
    for i in "${!SEED_SRCS[@]}"; do
        SEED_SRCS[$i]="$tmp/seed-input/${SEED_SRCS[$i]}"
    done
fi
if [ -f src/cmd/compile/xu.xun ] && grep -q '^version:' src/cmd/compile/xu.xun; then
    SEED_INPUT_DIR="$tmp/seed-input/compile"
    mkdir -p "$SEED_INPUT_DIR"
    python3 - "$SEED_INPUT_DIR" "${SEED_SRCS[@]}" <<'PY'
import shutil, sys
from pathlib import Path
dest = Path(sys.argv[1])
for source in sys.argv[2:]:
    shutil.copyfile(source, dest / Path(source).name)
manifest = Path("src/cmd/compile/xu.xun").read_text(encoding="utf-8")
(dest / "xu.xun").write_text(
    "".join(line for line in manifest.splitlines(keepends=True)
            if not line.startswith("version:")), encoding="utf-8")
PY
    for i in "${!SEED_SRCS[@]}"; do
        SEED_SRCS[$i]="$SEED_INPUT_DIR/$(basename "${SEED_SRCS[$i]}")"
    done
fi
"$SEED" build "${SEED_SRCS[@]}" -o "$tmp/gen1.xin"
export XU_STDLIB_ROOT="$(native_path "$ROOT/src")"
G1=$(pick_bin "$tmp/gen1.xin")
echo "build_hosted_chain: gen1=$G1"
# shellcheck disable=SC2086
FAILED_STAGE="gen1_to_gen2"
set +u
"$G1" build "${HOSTED_ARGS[@]}" $GEN1_SRCS -o "$tmp/gen2.xin"
set -u
G2=$(pick_bin "$tmp/gen2.xin")
echo "build_hosted_chain: gen2=$G2"
# shellcheck disable=SC2086
FAILED_STAGE="gen2_to_gen3"
set +u
"$G2" build "${HOSTED_ARGS[@]}" $GEN1_SRCS -o "$tmp/gen3.xin"
set -u
G3=$(pick_bin "$tmp/gen3.xin")
echo "build_hosted_chain: gen3=$G3"
FAILED_STAGE="fixed_point_cmp"
CONFIRMED="$G3"
CONFIRMED_GENERATION=3
FIXED_POINT_PAIR=gen2_gen3
GEN2_GEN3_CMP=PASS
GEN3_GEN4_CMP=SKIPPED
if cmp -s "$G2" "$G3"; then
    echo "build_hosted_chain: fixed point confirmed (Gen2 == Gen3); skipping Gen4"
else
    echo "build_hosted_chain: warmup transition recorded (Gen2 != Gen3; release check is Gen3 == Gen4)"
    GEN2_GEN3_CMP=DIFFERENT
    FAILED_STAGE="gen3_to_gen4"
    set +u
    "$G3" build "${HOSTED_ARGS[@]}" $GEN1_SRCS -o "$tmp/gen4.xin"
    set -u
    G4=$(pick_bin "$tmp/gen4.xin")
    echo "build_hosted_chain: gen4=$G4"
    FAILED_STAGE="fixed_point_cmp"
    cmp "$G3" "$G4"
    CONFIRMED="$G4"
    CONFIRMED_GENERATION=4
    FIXED_POINT_PAIR=gen3_gen4
    GEN3_GEN4_CMP=PASS
fi

# Capture the actual compared generations. Never claim a skipped Gen4 exists.
SEED_SHA256=$(sha256_file "$SEED")
GEN1_SHA256=$(sha256_file "$G1")
GEN2_SHA256=$(sha256_file "$G2")
GEN3_SHA256=$(sha256_file "$G3")
if GEN3_SIZE=$(stat -f '%z' "$G3" 2>/dev/null); then :; else GEN3_SIZE=$(stat -c '%s' "$G3"); fi
GEN4_SHA256=SKIPPED
GEN4_SIZE=SKIPPED
if [ "$CONFIRMED_GENERATION" = 4 ]; then
    GEN4_SHA256=$(sha256_file "$G4")
    if GEN4_SIZE=$(stat -f '%z' "$G4" 2>/dev/null); then :; else GEN4_SIZE=$(stat -c '%s' "$G4"); fi
fi
CONFIRMED_SHA256=$(sha256_file "$CONFIRMED")
CONFIRMED_SIZE=$GEN3_SIZE
HOSTED_ARGS_TEXT=""
if [ "${#HOSTED_ARGS[@]}" -gt 0 ]; then
    HOSTED_ARGS_TEXT=$(printf '%s ' "${HOSTED_ARGS[@]}")
    HOSTED_ARGS_TEXT=${HOSTED_ARGS_TEXT% }
fi
if [ -z "$HOSTED_ARGS_TEXT" ]; then HOSTED_ARGS_TEXT="<compiler-defaults>"; fi

FAILED_STAGE="source_identity"
python3 scripts/check_bootstrap_xu_boundary.py --strict-freeze --json >"$tmp/boundary.final.json"
python3 - "$BOUNDARY_JSON" "$tmp/boundary.final.json" <<'PY_CHECK'
import json, sys
before, after = [json.load(open(p))['source_manifest'] for p in sys.argv[1:]]
for key in ('seed_sha256', 'closure_sha256'):
    if before[key] != after[key]:
        raise SystemExit('build_hosted_chain: source changed during chain: ' + key)
PY_CHECK

if [ "$SEED_LANE" = "oracle" ] && [ "${XU_ALLOW_ORACLE_INSTALL:-0}" != 1 ] && [ "$CANDIDATE_ONLY" != 1 ]; then
    # An oracle/recovery chain may be useful for diagnosing a hosted hop, but
    # it must not leak a primer-derived compiler, sibling tool, or platform
    # copy into a product directory.  In particular, DEST may be a temporary
    # path while the historical helpers would still write bin/platform.
    FAILED_STAGE="oracle_artifact"
    mkdir -p "$(dirname "$DEST")"
    bash ./scripts/install_product_executable.sh "$CONFIRMED" "$DEST"
    echo "build_hosted_chain: oracle artifact kept at $DEST (Gen$CONFIRMED_GENERATION; not installed as product)" >&2
    FAILED_STAGE=""
    echo "build_hosted_chain: chain PASS lane=oracle/recovery (non-product evidence)"
    exit 0
fi

# Product/tool/platform installation is reachable only from the hosted
# product lane, or from an explicitly authorised recovery override above.
# Keep the existing order and backup semantics for compatibility; the
# destination guard plus the oracle branch ensure that no implicit primer run
# can write sibling tools or cross-target product copies.
FAILED_STAGE="artifact"
mkdir -p "$(dirname "$DEST")"
if [ -f "$DEST" ]; then
    cp "$DEST" "${DEST}.bak"
    echo "build_hosted_chain: backed up $DEST to ${DEST}.bak"
fi
# A live or signature-cached Mach-O must get a new inode even if its bytes
# happen to match. Truncating it in place can make macOS SIGKILL later starts.
bash ./scripts/install_product_executable.sh "$CONFIRMED" "$DEST"
if [ "$CANDIDATE_ONLY" = 1 ]; then
    echo "build_hosted_chain: candidate=$DEST (no product/tool/platform installation)"
else
    echo "build_hosted_chain: installed $DEST"
    FAILED_STAGE="product_tools"
    ./scripts/build_product_tools.sh "$DEST" "$(dirname "$DEST")"
    FAILED_STAGE="cross_targets"
    ./scripts/build_platform_xu.sh "$DEST" bin/platform
fi
# Write provenance only after every requested install step succeeds.  A failed
# tool/cross build therefore cannot leave a sidecar that looks valid.
FAILED_STAGE="provenance"
PROVENANCE_PATH="${DEST}.provenance"
cat >"$tmp/provenance.final" <<EOF
schema=2
status=PASS
lane=$SEED_LANE
hosted_profile=$HOSTED_PROFILE
hosted_args=$HOSTED_ARGS_TEXT
target_os=$(uname -s)
target_arch=$(uname -m)
repo_head=$REPO_HEAD
seed_path=$SEED
seed_sha256=$SEED_SHA256
seed_syntax_bridge=$SEED_SYNTAX_BRIDGE
source_seed_files=$SOURCE_SEED_FILES
source_seed_sha256=$SOURCE_SEED_SHA256
source_closure_files=$SOURCE_CLOSURE_FILES
source_closure_sha256=$SOURCE_CLOSURE_SHA256
gen1_sha256=$GEN1_SHA256
gen2_sha256=$GEN2_SHA256
gen3_sha256=$GEN3_SHA256
gen4_sha256=$GEN4_SHA256
gen3_size=$GEN3_SIZE
gen4_size=$GEN4_SIZE
gen2_gen3_cmp=$GEN2_GEN3_CMP
gen3_gen4_cmp=$GEN3_GEN4_CMP
fixed_point_cmp=PASS
fixed_point_pair=$FIXED_POINT_PAIR
confirmed_generation=$CONFIRMED_GENERATION
confirmed_sha256=$CONFIRMED_SHA256
confirmed_size=$CONFIRMED_SIZE
candidate_only=$CANDIDATE_ONLY
cross_targets=$([ "$CANDIDATE_ONLY" = 1 ] || [ "${XU_SKIP_CROSS:-0}" = 1 ] && echo SKIPPED || echo PASS)
EOF
mkdir -p "$(dirname "$PROVENANCE_PATH")"
mv -f "$tmp/provenance.final" "$PROVENANCE_PATH"
echo "build_hosted_chain: provenance=$PROVENANCE_PATH"
FAILED_STAGE=""
echo "build_hosted_chain: chain PASS lane=$SEED_LANE hosted_profile=$HOSTED_PROFILE"
