#!/usr/bin/env bash
# Hosted self-host chain: seed → gen1 → gen2 (warm-up) → gen3.
# If gen2 == gen3, install gen3; otherwise build gen4 and require gen3 == gen4.
# No cargo to compile the compiler.
# After install: sibling tools, then cross product xu into
# bin/platform/<os>-<arch>/ (XU_SKIP_CROSS=1 to skip).
#
# Usage: scripts/build_hosted_chain.sh [--candidate-only] <seed-xu> [dest-xu]
#
# The seed is resolved through the shared hosted product policy.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -P)
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
    echo "build_hosted_chain: seed rejected by hosted boundary: $SEED_INPUT" >&2
    exit 1
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
unset XUOS XUARCH XU_BOOT_EXTRA XU_HEAP_STATS XU_SEED

# Keep the product chain on the compiler's versioned defaults.  The explicit
# acceptance profile is available for deterministic vreg/SSA gates and must
# be selected by the caller; every hosted hop uses exactly the same arguments
# so a fixed-point comparison cannot mix profiles.  Gen2 is a deliberate
# warm-up: an older seed can expose a one-time lowering/optimization
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

# Canonicalize the destination before enforcing candidate isolation.
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

echo "build_hosted_chain: lane=product (hosted seed)"
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

FAILED_STAGE="seed_to_gen1"
# Every hop builds the original source and manifest with the same profile.
SEED_MANIFEST_BRIDGE=none
BRIDGE_SOCKET_SHA256=SKIPPED
BRIDGE_SEED_SHA256=SKIPPED
# shellcheck disable=SC2086
set +u
if "$SEED" build "${HOSTED_ARGS[@]}" $GEN1_SRCS -o "$tmp/gen1.xin" >"$tmp/seed-build.log" 2>&1; then
    seed_build_rc=0
else
    seed_build_rc=$?
fi
set -u
cat "$tmp/seed-build.log"
if [ "$seed_build_rc" -ne 0 ]; then
    # Older hosted SDKs cannot type-check the new, unused os wrapper. Build
    # an intermediate compiler without that wrapper, then restart Gen1 on
    # the complete original source. Never install or compare the bridge as
    # a product generation, and never recover unrelated compiler failures.
    if ! grep -Fq "undefined name 'sys_socket_poll'" "$tmp/seed-build.log"; then
        exit "$seed_build_rc"
    fi
    FAILED_STAGE="socket_poll_seed_bridge"
    echo "build_hosted_chain: bootstrapping socket_poll support for the older hosted seed"
    python3 - "$ROOT/src" "$tmp/seed-bridge-src" <<'PY_BRIDGE'
from pathlib import Path
import re
import shutil
import sys

source, destination = map(Path, sys.argv[1:])
shutil.copytree(source, destination)
socket = destination / 'os/socket.xu'
text, count = re.subn(
    r'^pub fn socket_poll\(fd int, events int\) int \{\n'
    r'    << sys_socket_poll\(fd, events\) or >>\n\}\n',
    '', socket.read_text(), flags=re.MULTILINE,
)
if count != 1:
    raise SystemExit('socket_poll seed bridge: expected the exact versioned wrapper')
socket.write_text(text)
PY_BRIDGE
    BRIDGE_SOCKET_SHA256=$(sha256_file "$tmp/seed-bridge-src/os/socket.xu")
    # shellcheck disable=SC2086
    set +u
    XU_STDLIB_ROOT="$(native_path "$tmp/seed-bridge-src")" \
        "$SEED" build "${HOSTED_ARGS[@]}" $GEN1_SRCS -o "$tmp/socket-poll-bootstrap.xin"
    set -u
    BRIDGE_SEED=$(pick_bin "$tmp/socket-poll-bootstrap.xin")
    BRIDGE_SEED_SHA256=$(sha256_file "$BRIDGE_SEED")
    SEED_MANIFEST_BRIDGE=socket_poll_wrapper_v1
    FAILED_STAGE="bridged_seed_to_gen1"
    # shellcheck disable=SC2086
    set +u
    "$BRIDGE_SEED" build "${HOSTED_ARGS[@]}" $GEN1_SRCS -o "$tmp/gen1.xin"
    set -u
fi
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


# Candidate builds write only their explicit destination. Product builds
# also install sibling tools and cross-target compiler copies.
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
seed_manifest_bridge=$SEED_MANIFEST_BRIDGE
bridge_socket_sha256=$BRIDGE_SOCKET_SHA256
bridge_seed_sha256=$BRIDGE_SEED_SHA256
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
