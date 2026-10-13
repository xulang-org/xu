#!/usr/bin/env bash
# Virtual-register self-host regression.  The bootstrap compiler is only the
# O0 primer; hosted hops are built at the product O1/RA1 tier.  The first
# hosted output (Gen2) is a warm-up, so the release fixed-point check is
# Gen3 == Gen4; this prevents a one-time primer-to-hosted lowering transition
# from being mistaken for nondeterminism or hidden by a weaker gate.
set -euo pipefail

# Machine-readable boundary role: fixed-point oracle/acceptance evidence.
BOUNDARY_LANE=oracle

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
BOOTSTRAP_ROOT=$("$repo_root/scripts/xu_host_seed.sh" --bootstrap-root)
export XU_ROOT="$repo_root"
cd "$repo_root"

. ./scripts/gen1_sources.sh
. ./scripts/test_lib.sh

tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/xu-vreg-selfhost.XXXXXX")
cleanup() {
    rc=$?
    if [ "$rc" -ne 0 ] && [ "${VREG_SELFHOST_KEEP_FAILURES:-0}" = 1 ]; then
        printf 'test_vreg_selfhost: preserved failure artifacts in %s\n' "$tmp_dir" >&2
    else
        rm -rf "$tmp_dir"
    fi
}
trap cleanup EXIT

pick_bin() {
    if [ -x "$1" ]; then
        printf '%s\n' "$1"
    elif [ -x "$1.exe" ]; then
        printf '%s\n' "$1.exe"
    else
        printf 'test_vreg_selfhost: missing executable %s\n' "$1" >&2
        exit 1
    fi
}

fail() {
    printf 'test_vreg_selfhost: %s\n' "$*" >&2
    exit 1
}

run_step() {
    label=$1
    seconds=$2
    shift 2
    if run_with_timeout "$seconds" "$@"; then
        return 0
    else
        rc=$?
    fi
    if [ "$rc" -eq 124 ]; then
        fail "$label timed out after ${seconds}s"
    fi
    fail "$label failed (exit $rc)"
}

disassemble() {
    if command -v otool >/dev/null 2>&1; then
        otool -tvV "$1"
    elif command -v llvm-objdump >/dev/null 2>&1; then
        llvm-objdump -d "$1"
    elif command -v objdump >/dev/null 2>&1; then
        objdump -d "$1"
    else
        fail 'need otool, llvm-objdump, or objdump for fixed-home structure checks'
    fi
}

# Print the total frame allocation for each emitted function prologue.  Arm64
# splits frames above 64KiB into `sub ..., #hi, lsl #12` plus a low `sub`, so
# this must sum consecutive terms rather than reading only the first immediate.
# Xu binaries are stripped; stable fixture function order is the test seam.
frame_sizes() {
    case "$(uname -m)" in
        arm64|aarch64|x86_64|amd64) ;;
        *) fail "unsupported host architecture for structure checks: $(uname -m)" ;;
    esac
    disassemble "$1" | python3 -c '
import re
import sys

arch = sys.argv[1]
arm = arch in ("arm64", "aarch64")
prologue = (
    re.compile(r"\bmov\s+x29,\s*sp\b") if arm else
    re.compile(r"\bmovq?\s+%?rsp,\s*%?rbp\b")
)
arm_sub = re.compile(
    r"\bsub\s+sp,\s*sp,\s*#0x([0-9a-f]+)(?:,\s*lsl\s*#([0-9]+))?",
    re.I,
)
x64_sub = re.compile(r"\bsubq?\s+\$0x([0-9a-f]+),\s*%rsp\b", re.I)
collecting = False
total = 0
for line in sys.stdin:
    if prologue.search(line):
        if collecting:
            print(total)
        collecting = True
        total = 0
        continue
    if not collecting:
        continue
    match = arm_sub.search(line) if arm else x64_sub.search(line)
    if match:
        value = int(match.group(1), 16)
        if arm and match.group(2):
            value <<= int(match.group(2))
        total += value
        continue
    print(total)
    collecting = False
if collecting:
    print(total)
' "$(uname -m)"
}

max_first_frames() {
    bin=$1
    want=$2
    frames=$(frame_sizes "$bin" | sed -n "1,${want}p")
    seen=0
    max=0
    while IFS= read -r value; do
        [ -n "$value" ] || continue
        if [ "$value" -gt "$max" ]; then
            max=$value
        fi
        seen=$((seen + 1))
    done <<< "$frames"
    [ "$seen" -eq "$want" ] \
        || fail "could not read $want user-function frames from $bin (got $seen)"
    printf '%s\n' "$max"
}

frame_at() {
    bin=$1
    want=$2
    value=$(frame_sizes "$bin" | sed -n "$want"p)
    [ -n "$value" ] || fail "could not read user-function frame $want from $bin"
    printf '%s\n' "$value"
}

# Return the explicit local-stack allocation for the call-free 20M loop
# helper. `max_first_frames` intentionally includes the caller envelope, but
# this fixture's caller can have the same envelope in both RA modes; compare
# the helper itself so the gate measures the optimized hot loop rather than an
# unrelated channel/runtime frame.
chan_loop_frame_size() {
    disassemble "$1" | python3 -c '
import re
import sys

arch = sys.argv[1]
arm = arch in ("arm64", "aarch64")
prologue = (
    re.compile(r"\bmov\s+x29,\s*sp\b") if arm else
    re.compile(r"\bmovq?\s+%?rsp,\s*%?rbp\b")
)
call = re.compile(r"\bbl\b") if arm else re.compile(r"\bcallq?\b")
loop_const = re.compile(r"(?:0x1312d00\b|0x131\s*,\s*lsl\s*#16\b)", re.I)
branch = (
    re.compile(r"\bb(?:\.\w+)?\b", re.I) if arm else
    re.compile(r"\bj[a-z]*\b", re.I)
)
arm_sub = re.compile(
    r"\bsub\s+sp,\s*sp,\s*#0x([0-9a-f]+)(?:,\s*lsl\s*#([0-9]+))?",
    re.I,
)
x64_sub = re.compile(r"\bsubq?\s+\$0x([0-9a-f]+),\s*%rsp\b", re.I)
groups = []
cur = None
for line in sys.stdin:
    if prologue.search(line):
        if cur is not None:
            groups.append(cur)
        cur = []
    if cur is not None:
        cur.append(line)
if cur is not None:
    groups.append(cur)

matches = []
for lines in groups:
    if sum(bool(loop_const.search(line)) for line in lines) < 1:
        continue
    if any(call.search(line) for line in lines):
        continue
    if sum(bool(branch.search(line)) for line in lines) < 2:
        continue
    size = 0
    for line in lines:
        match = arm_sub.search(line) if arm else x64_sub.search(line)
        if match:
            value = int(match.group(1), 16)
            if arm and match.group(2):
                value <<= int(match.group(2))
            size += value
    matches.append(size)
if len(matches) != 1:
    raise SystemExit("expected one call-free 20M loop helper, found %d" % len(matches))
print(matches[0])
' "$(uname -m)"
}

# The first five fixture functions are main, clobber_fp, across_call,
# two_across_call and dead_before_call. Require exact FP stack actions around
# their sole direct call: 1/2/0 saves before it and 1/2/0 reloads after it.
assert_f64_call_split_actions() {
    bin=$1
    disassemble "$bin" | python3 -c '
import re
import sys

arch = sys.argv[1]
arm = arch in ("arm64", "aarch64")
prologue = (
    re.compile(r"\bmov\s+x29,\s*sp\b") if arm else
    re.compile(r"\bmovq?\s+%?rsp,\s*%?rbp\b")
)
call = re.compile(r"\bbl\b") if arm else re.compile(r"\bcallq?\b")
groups = []
cur = None
for line in sys.stdin:
    if prologue.search(line):
        if cur is not None:
            groups.append(cur)
        cur = []
    if cur is not None:
        cur.append(line)
if cur is not None:
    groups.append(cur)
if len(groups) < 5:
    raise SystemExit("need five user functions, got %d" % len(groups))

def classify(line):
    if arm:
        if re.search(r"\b(?:stur|str)\s+d[0-9]+,\s*\[x29,", line):
            return "store"
        if re.search(r"\b(?:ldur|ldr)\s+d[0-9]+,\s*\[x29,", line):
            return "load"
        return None
    low = line.lower()
    if "movsd" not in low or "xmm" not in low or "rbp" not in low:
        return None
    xmm = low.find("xmm")
    rbp = low.find("rbp")
    # objdump/otool use AT&T syntax by default: source precedes destination.
    return "store" if xmm < rbp else "load"

for fn_index, want in ((2, 1), (3, 2), (4, 0)):
    lines = groups[fn_index]
    calls = [i for i, line in enumerate(lines) if call.search(line)]
    if len(calls) != 1:
        raise SystemExit("function %d: expected one direct call, got %d" % (fn_index, len(calls)))
    ci = calls[0]
    stores = sum(classify(line) == "store" for line in lines[:ci])
    loads = sum(classify(line) == "load" for line in lines[ci + 1:])
    if stores != want or loads != want:
        raise SystemExit(
            "function %d: expected %d/%d FP save/reload actions, got %d/%d"
            % (fn_index, want, want, stores, loads)
        )
' "$(uname -m)" || fail 'call-live f64 save/reload action structure mismatch'
}

# The channel fixture contains a deliberately long, side-effect-free loop in
# `spin`. The mixed caller must leave that helper out of line, and the
# unit-shaped void return must still receive fixed homes. Check the emitted
# loop body directly rather than relying only on a frame-size delta: a future
# change could shrink an unrelated caller frame while silently putting the
# hot loop back on frame-backed temporaries. The loop's 20,000,000 bound is
# encoded as 0x1312d00 (or as 0x2d00 + 0x131 << 16 on Arm64). Select the
# constant-bearing helper with no calls, then require no accesses through the
# frame pointer (`x29`/`rbp`) anywhere in that function.
assert_chan_loop_register_only() {
    disassemble "$1" | python3 -c '
import re
import sys

arch = sys.argv[1]
arm = arch in ("arm64", "aarch64")
prologue = (
    re.compile(r"\bmov\s+x29,\s*sp\b") if arm else
    re.compile(r"\bmovq?\s+%?rsp,\s*%?rbp\b")
)
call = re.compile(r"\bbl\b") if arm else re.compile(r"\bcallq?\b")
branch = (
    re.compile(r"\bb(?:\.\w+)?\b", re.I) if arm else
    re.compile(r"\bj[a-z]*\b", re.I)
)
bool_materialize = (
    re.compile(r"\bcset\b", re.I) if arm else
    re.compile(r"\bset[a-z]*\b", re.I)
)
# Arm64 materializes the bound with a low half and a movk high half; x86-64
# normally materializes the complete immediate in one instruction.
loop_const = re.compile(
    r"(?:0x1312d00\b|0x131\s*,\s*lsl\s*#16\b)", re.I
)
frame_mem = (
    re.compile(r"\[(?:x29|fp)\s*(?:,|\])", re.I) if arm else
    re.compile(r"(?:\(\s*%?(?:rbp|ebp)\b|\[\s*%?(?:rbp|ebp)\b)", re.I)
)
groups = []
cur = None
for line in sys.stdin:
    if prologue.search(line):
        if cur is not None:
            groups.append(cur)
        cur = []
    if cur is not None:
        cur.append(line)
if cur is not None:
    groups.append(cur)

candidates = []
for index, lines in enumerate(groups):
    constants = sum(bool(loop_const.search(line)) for line in lines)
    calls = sum(bool(call.search(line)) for line in lines)
    branches = sum(bool(branch.search(line)) for line in lines)
    # Requiring a bound materialization and loop branches keeps unrelated
    # runtime constants from being mistaken for the fixture loop.  The
    # lowering may materialize the bound once and reuse it, or repeat it.
    if constants >= 1 and calls == 0 and branches >= 2:
        candidates.append((index, lines, constants))

if len(candidates) != 1:
    raise SystemExit(
        "expected one call-free 20M loop helper, found %d (groups=%d)"
        % (len(candidates), len(groups))
    )
index, lines, constants = candidates[0]
frame_lines = [line.strip() for line in lines if frame_mem.search(line)]
if frame_lines:
    raise SystemExit(
        "loop helper group %d has %d frame-pointer accesses (first: %s)"
        % (index, len(frame_lines), frame_lines[0])
    )
materialized = [line.strip() for line in lines if bool_materialize.search(line)]
if materialized:
    raise SystemExit(
        "loop helper group %d still materializes a compare boolean (first: %s)"
        % (index, materialized[0])
    )
print(
    "chan loop structure: helper group %d, %d bound materializations, register-only/direct-branch body"
    % (index, constants),
    file=sys.stderr,
)
' "$(uname -m)" || fail 'chan_multi_sender_unbuffered loop is not register-only'
}

# The branch-value fixture is the negative side of the fusion proof: its
# comparison feeds both a branch and a returned value.  Require a boolean
# materialization in one of the early user functions, so a future broadening
# of the one-use gate cannot silently clobber the returned value.
assert_branch_value_materialized() {
    disassemble "$1" | python3 -c '
import re
import sys

arch = sys.argv[1]
arm = arch in ("arm64", "aarch64")
prologue = (
    re.compile(r"\bmov\s+x29,\s*sp\b") if arm else
    re.compile(r"\bmovq?\s+%?rsp,\s*%?rbp\b")
)
call = re.compile(r"\bbl\b") if arm else re.compile(r"\bcallq?\b")
compare = re.compile(r"\bcmp\b", re.I)
branch = (
    re.compile(r"\bb(?:\.\w+)?\b", re.I) if arm else
    re.compile(r"\bj[a-z]*\b", re.I)
)
materialize = (
    re.compile(r"\bcset\b", re.I) if arm else
    re.compile(r"\bset[a-z]+\b", re.I)
)
groups = []
cur = None
for line in sys.stdin:
    if prologue.search(line):
        if cur is not None:
            groups.append(cur)
        cur = []
    if cur is not None:
        cur.append(line)
if cur is not None:
    groups.append(cur)

# The fixture classify function is emitted immediately after main.  Limit
# the search to early user groups to avoid matching a runtime helper cset.
for index, lines in enumerate(groups[:4]):
    if (
        any(compare.search(line) for line in lines)
        and any(branch.search(line) for line in lines)
        and any(materialize.search(line) for line in lines)
    ):
        if not any(call.search(line) for line in lines):
            print(
                "branch-value structure: function group %d retains compare boolean materialization"
                % index,
                file=sys.stderr,
            )
            break
else:
    raise SystemExit("branch-value compare lost its required boolean materialization")
' "$(uname -m)" || fail 'vreg_branch_value compare materialization structure mismatch'
}

# Keep only the four user functions in vreg_call_live.  Arm64 Gen1 emits a
# normal and a fail-closed epilogue per function; the following dispatch stubs
# and runtime helpers must not satisfy the callee-save assertions below.
arm64_call_live_user_text() {
    disassemble "$1" | awk '
        !done { print }
        !done && $NF == "ret" {
            returns++
            if (returns == 8) done = 1
        }
    '
}

assert_fixed_home_structure() {
    local_ra0=$1
    local_ra1=$2
    call_ra0=$3
    call_ra1=$4
    large_ra0=$5
    large_ra1=$6
    receiver_ra0=$7
    receiver_ra1=$8
    unreachable_ra0=$9
    unreachable_ra1=${10}
    wide_ra0=${11}
    wide_ra1=${12}

    # local_cfg has two user functions.  Its promoted diamond/loop locals must
    # make the largest RA1 user frame strictly smaller than the RA0 reference.
    frame_ra0=$(max_first_frames "$local_ra0" 2)
    frame_ra1=$(max_first_frames "$local_ra1" 2)
    [ "$frame_ra1" -lt "$frame_ra0" ] \
        || fail "local_cfg RA1 frame did not shrink (RA0=${frame_ra0}B RA1=${frame_ra1}B)"

    # The large-frame pressure fixture crosses the old synthetic-slot boundary
    # and still has one spill.  Fixed homes must reduce that real frame too.
    large_frame_ra0=$(max_first_frames "$large_ra0" 2)
    large_frame_ra1=$(max_first_frames "$large_ra1" 2)
    [ "$large_frame_ra1" -lt "$large_frame_ra0" ] \
        || fail "large-frame RA1 frame did not shrink (RA0=${large_frame_ra0}B RA1=${large_frame_ra1}B)"

    # A frame-backed value receiver must not disable fixed homes for unrelated
    # scalar temps in the same function.
    receiver_frame_ra0=$(max_first_frames "$receiver_ra0" 2)
    receiver_frame_ra1=$(max_first_frames "$receiver_ra1" 2)
    [ "$receiver_frame_ra1" -lt "$receiver_frame_ra0" ] \
        || fail "receiver RA1 frame did not shrink (RA0=${receiver_frame_ra0}B RA1=${receiver_frame_ra1}B)"

    # Unsupported calls in an unreachable block are deliberately fail-closed:
    # enabling RA1 must produce the exact RA0 binary, not a partial plan.
    cmp -s "$unreachable_ra0" "$unreachable_ra1" \
        || fail 'unreachable-runtime RA1 did not fail closed to the RA0 binary'

    # The first function crosses 62 locals and the second crosses 62 blocks.
    # Promotion must span packed words rather than failing closed at the old
    # scalar-bitset boundary.
    wide_frame_ra0=$(max_first_frames "$wide_ra0" 3)
    wide_frame_ra1=$(max_first_frames "$wide_ra1" 3)
    [ "$wide_frame_ra1" -lt "$wide_frame_ra0" ] \
        || fail "wide promotion RA1 frame did not shrink (RA0=$wide_frame_ra0 B RA1=$wide_frame_ra1 B)"
    wide_blocks_ra1=$(frame_at "$wide_ra1" 2)
    [ "$wide_blocks_ra1" -le 16 ] \
        || fail "wide-block promotion retained local frame homes (RA1=$wide_blocks_ra1 B)"

    case "$(uname -m)" in
        arm64|aarch64)
            ra0_user="$tmp_dir/vreg_call_live.ra0.user.asm"
            ra1_user="$tmp_dir/vreg_call_live.ra1.user.asm"
            arm64_call_live_user_text "$call_ra0" >"$ra0_user"
            arm64_call_live_user_text "$call_ra1" >"$ra1_user"

            # This is deliberately stronger than checking that the binaries
            # differ: a call-live value must occupy x19, and the containing
            # functions must dynamically preserve the x19/x20 ABI pair.
            grep -Eq 'stp[[:space:]]+x19,[[:space:]]*x20' "$ra1_user" \
                || fail 'call_live RA1 did not save the x19/x20 fixed-home pair'
            grep -Eq 'ldp[[:space:]]+x19,[[:space:]]*x20' "$ra1_user" \
                || fail 'call_live RA1 did not restore the x19/x20 fixed-home pair'
            if ! grep -E 'x19' "$ra1_user" \
                | grep -Eqv '[sl]dp[[:space:]]+x19,[[:space:]]*x20'; then
                fail 'call_live RA1 saved x19 but never used it as a value home'
            fi
            if grep -Eq '[sl]dp[[:space:]]+x19,[[:space:]]*x20' "$ra0_user"; then
                fail 'call_live RA0 unexpectedly uses the RA1 x19/x20 save pair'
            fi
            ;;
        x86_64|amd64)
            # The current x64 ABI saves its fixed-home pool in every prologue,
            # so dynamic save/restore is not a discriminator.  Instead require
            # the RA1 local_cfg user code to reference the pool beyond the
            # mandatory push/pop sequence, while RA0 does not.
            ra0_asm="$tmp_dir/vreg_local_cfg.ra0.asm"
            ra1_asm="$tmp_dir/vreg_local_cfg.ra1.asm"
            disassemble "$local_ra0" >"$ra0_asm"
            disassemble "$local_ra1" >"$ra1_asm"
            ra0_body=$(grep -E '%(rbx|r12|r13|r14|r15)' "$ra0_asm" \
                | grep -Evc '[[:space:]](pushq|popq)[[:space:]]' || true)
            ra1_body=$(grep -E '%(rbx|r12|r13|r14|r15)' "$ra1_asm" \
                | grep -Evc '[[:space:]](pushq|popq)[[:space:]]' || true)
            [ "$ra1_body" -gt "$ra0_body" ] \
                || fail "local_cfg RA1 did not add x64 fixed-home body uses (RA0=$ra0_body RA1=$ra1_body)"
            ;;
    esac

    printf 'vreg selfhost structure: local_cfg %sB -> %sB; large-frame %sB -> %sB; receiver %sB -> %sB; wide %sB -> %sB; fixed homes/fail-closed observed\n' \
        "$frame_ra0" "$frame_ra1" \
        "$large_frame_ra0" "$large_frame_ra1" \
        "$receiver_frame_ra0" "$receiver_frame_ra1" \
        "$wide_frame_ra0" "$wide_frame_ra1"
}

build_timeout=${VREG_SELFHOST_BUILD_TIMEOUT:-300}
fixture_compile_timeout=${VREG_SELFHOST_FIXTURE_COMPILE_TIMEOUT:-60}
fixture_run_timeout=${VREG_SELFHOST_FIXTURE_RUN_TIMEOUT:-10}

run_step 'bootstrap build' "$build_timeout" \
    cargo build --manifest-path "$BOOTSTRAP_ROOT/Cargo.toml" -q -p xu --bin xu

bootstrap_xu="$BOOTSTRAP_ROOT/target/debug/xu"
for candidate in \
    "$BOOTSTRAP_ROOT/target/debug/xu" \
    "$BOOTSTRAP_ROOT/target/debug/xu.exe" \
    "$BOOTSTRAP_ROOT/target/release/xu" \
    "$BOOTSTRAP_ROOT/target/release/xu.exe"; do
    if [ -x "$candidate" ]; then
        bootstrap_xu="$candidate"
        break
    fi
done
bootstrap_xu=$(XU_ALLOW_ORACLE_SEED=1 XU_REQUIRE_FROZEN_PRIMER=1 XU_SEED="$bootstrap_xu" \
    "$repo_root/scripts/xu_host_seed.sh") || {
    fail 'bootstrap compiler is not the canonical frozen primer'
}

# The Rust bootstrap's O1 path is a separately tracked miscompile; keep this
# one primer at O0.  It does not count as a hosted release hop.
# shellcheck disable=SC2086
run_step 'bootstrap -> Gen1 O0 primer' "$build_timeout" \
    "$bootstrap_xu" $GEN1_SRCS -O0 -o "$tmp_dir/gen1"
gen1=$(pick_bin "$tmp_dir/gen1")

# Pin both MIR and RA explicitly.  Relying on the default/AUTO tier would let a
# whole-program shape change silently choose a different allocator tier.
hosted_args=(-O1 --ra=1)
# shellcheck disable=SC2086
run_step 'Gen1 -> Gen2 hosted O1/RA1' "$build_timeout" \
    "$gen1" build $GEN1_SRCS "${hosted_args[@]}" -o "$tmp_dir/gen2"
gen2=$(pick_bin "$tmp_dir/gen2")

# Prove the compiler under test is already at its hosted fixed point before
# spending time on the fixture matrix. This is also the stale-label ownership
# regression seam: both hops must succeed and be byte-identical.
# shellcheck disable=SC2086
run_step 'Gen2 -> Gen3 hosted O1/RA1' "$build_timeout" \
    "$gen2" build $GEN1_SRCS "${hosted_args[@]}" -o "$tmp_dir/gen3"
gen3=$(pick_bin "$tmp_dir/gen3")

run_step 'Gen3 -> Gen4 hosted O1/RA1' "$build_timeout" \
    "$gen3" build $GEN1_SRCS "${hosted_args[@]}" -o "$tmp_dir/gen4"
gen4=$(pick_bin "$tmp_dir/gen4")

if cmp -s "$gen2" "$gen3"; then
    printf '%s\n' 'vreg selfhost: warm-up already stable (Gen2 == Gen3)' >&2
else
    printf '%s\n' 'vreg selfhost: warm-up transition recorded (Gen2 != Gen3)' >&2
fi
cmp "$gen3" "$gen4" || fail 'Gen3 != Gen4 at hosted O1/RA1'

# Gen3 and Gen4 are byte-identical after the confirmation hop; use the
# explicitly named confirmation artifact for the fixture matrix so a future
# refactor cannot accidentally test the warm-up binary.
candidate=$gen4

# A test-only fault injection makes the requested RA1 fixture builds use RA0.
# The runtime oracle still passes, but the structural checks below must fail;
# this proves an allocator that fully degenerates cannot make the gate green.
fixture_ra1_args=(-O1 --ra=1)
if [ "${VREG_SELFHOST_FAULT_RA1_AS_RA0:-0}" = 1 ]; then
    fixture_ra1_args=(-O1 --ra=0)
fi

local_ra0=
local_ra1=
call_ra0=
call_ra1=
large_ra0=
large_ra1=
receiver_ra0=
receiver_ra1=
unreachable_ra0=
unreachable_ra1=
wide_ra0=
wide_ra1=
f64_call_ra0=
f64_call_ra1=
chan_multi_ra0=
chan_multi_ra1=
branch_value_ra1=
for fixture_name in \
    vreg_local_cfg \
    vreg_call_live \
    vreg_branch_value \
    vreg_spill_scalar \
    vreg_large_frame_spill \
    vreg_receiver_scalar \
    vreg_unreachable_runtime \
    vreg_wide_promotion \
    vreg_search_loop \
    vreg_fwd_exit \
    vreg_f64_temp \
    vreg_f64_local \
    vreg_f64_call_split \
    vreg_ssa_critical_edge \
    vreg_sroa_fields \
    chan_multi_sender_unbuffered
do
    fixture_dir="$repo_root/tests/fixtures/$fixture_name"
    expected=$(sed '/^[[:space:]]*$/d' "$fixture_dir/expected.txt")
    out_ra0="$tmp_dir/${fixture_name}.ra0"
    out_ra1="$tmp_dir/${fixture_name}.ra1"
    run_step "$fixture_name RA0 compile" "$fixture_compile_timeout" \
        "$candidate" build "$fixture_dir/main.xu" -O1 --ra=0 -o "$out_ra0"
    run_step "$fixture_name RA1 compile" "$fixture_compile_timeout" \
        "$candidate" build "$fixture_dir/main.xu" "${fixture_ra1_args[@]}" -o "$out_ra1"
    exe_ra0=$(pick_bin "$out_ra0")
    exe_ra1=$(pick_bin "$out_ra1")
    if actual_ra0=$(run_with_timeout "$fixture_run_timeout" "$exe_ra0"); then
        :
    else
        rc=$?
        [ "$rc" -eq 124 ] \
            && fail "$fixture_name RA0 run timed out after ${fixture_run_timeout}s"
        fail "$fixture_name RA0 run failed (exit $rc)"
    fi
    if actual_ra1=$(run_with_timeout "$fixture_run_timeout" "$exe_ra1"); then
        :
    else
        rc=$?
        [ "$rc" -eq 124 ] \
            && fail "$fixture_name RA1 run timed out after ${fixture_run_timeout}s"
        fail "$fixture_name RA1 run failed (exit $rc)"
    fi
    if [ "$actual_ra0" != "$expected" ]; then
        printf '%s RA0 output mismatch:\n%s\n' "$fixture_name" "$actual_ra0" >&2
        exit 1
    fi
    if [ "$actual_ra1" != "$expected" ]; then
        printf '%s RA1 output mismatch:\n%s\n' "$fixture_name" "$actual_ra1" >&2
        exit 1
    fi
    if [ "$actual_ra0" != "$actual_ra1" ]; then
        fail "$fixture_name RA0/RA1 output mismatch"
    fi

    if [ "$fixture_name" = vreg_unreachable_runtime ]; then
        cmp -s "$exe_ra0" "$exe_ra1" \
            || fail "$fixture_name RA1 must fail closed to a byte-identical RA0 binary"
    elif cmp -s "$exe_ra0" "$exe_ra1"; then
        fail "$fixture_name RA1 unexpectedly degenerated to the RA0 binary"
    fi

    case "$fixture_name" in
        vreg_local_cfg) local_ra0=$exe_ra0; local_ra1=$exe_ra1 ;;
        vreg_call_live) call_ra0=$exe_ra0; call_ra1=$exe_ra1 ;;
        vreg_large_frame_spill) large_ra0=$exe_ra0; large_ra1=$exe_ra1 ;;
        vreg_receiver_scalar) receiver_ra0=$exe_ra0; receiver_ra1=$exe_ra1 ;;
        vreg_unreachable_runtime) unreachable_ra0=$exe_ra0; unreachable_ra1=$exe_ra1 ;;
        vreg_wide_promotion) wide_ra0=$exe_ra0; wide_ra1=$exe_ra1 ;;
        vreg_branch_value) branch_value_ra1=$exe_ra1 ;;
        vreg_f64_call_split) f64_call_ra0=$exe_ra0; f64_call_ra1=$exe_ra1 ;;
        chan_multi_sender_unbuffered) chan_multi_ra0=$exe_ra0; chan_multi_ra1=$exe_ra1 ;;
    esac
done

assert_fixed_home_structure \
    "$local_ra0" "$local_ra1" \
    "$call_ra0" "$call_ra1" \
    "$large_ra0" "$large_ra1" \
    "$receiver_ra0" "$receiver_ra1" \
    "$unreachable_ra0" "$unreachable_ra1" \
    "$wide_ra0" "$wide_ra1"
assert_f64_call_split_actions "$f64_call_ra1"
assert_branch_value_materialized "$branch_value_ra1"

# The channel caller deliberately remains mixed, so the counted void `spin`
# helper must stay out-of-line. Its unit-shaped MIR carries ret==0 with one
# ABI slot; RA1 should therefore color the helper's scalar temps and shrink
# that helper's own stack allocation. Comparing the first three user
# envelopes is too coarse because `main` can dominate the max in both modes.
chan_frame_ra0=$(chan_loop_frame_size "$chan_multi_ra0")
chan_frame_ra1=$(chan_loop_frame_size "$chan_multi_ra1")
[ "$chan_frame_ra1" -lt "$chan_frame_ra0" ] \
    || fail "chan_multi_sender_unbuffered loop RA1 frame did not shrink (RA0=${chan_frame_ra0}B RA1=${chan_frame_ra1}B)"
assert_chan_loop_register_only "$chan_multi_ra1"

printf '%s\n' 'vreg selfhost: Gen3 == Gen4 at O1/RA1 (Gen2 warm-up recorded); sixteen RA0/RA1 fixtures pass; exact single/double/dead-at-call f64 save/reload actions, SROA field pieces, unit-shaped void-loop homes, and fixed-home/fail-closed structure checks pass'
