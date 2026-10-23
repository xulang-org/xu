#!/usr/bin/env bash
# Differential test for backend loop patterns (src/cmd/compile/emit_pattern.xu).
#
# Usage:
#   scripts/pattern_diff.sh <xu> <dir-or-file>... [-- -O1 -O2 ...]
#
# Every program is built with all patterns on and with XU_PATTERNS_OFF=all
# (the generic per-instruction emitter), run, and must produce identical
# stdout and exit status. The per-pattern hit totals show which patterns the
# corpus actually exercised; a pattern with no hits has no differential
# coverage from this corpus.
set -u
cd "$(dirname "$0")/.."
if [ "$#" -lt 2 ]; then
    echo "usage: scripts/pattern_diff.sh <xu> <dir-or-file>... [-- -O1 -O2]" >&2
    exit 2
fi
xu=$1
shift
case "$xu" in /*) ;; *) xu="$PWD/$xu" ;; esac
inputs=()
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do inputs+=("$1"); shift; done
[ "$#" -gt 0 ] && shift
opts=("$@")
[ "${#opts[@]}" -eq 0 ] && opts=(-O1 -O2 -O3)

export XU_STDLIB_ROOT="$PWD/src" XUPATH=""
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
timeout_run() { perl -e 'alarm shift; exec @ARGV' "$@"; }

# A directory with main.xu is one program (fixture layout); a directory of
# fixture directories expands to each one; otherwise every *.xu is a program.
files=()
for p in "${inputs[@]}"; do
    if [ -f "$p/main.xu" ]; then
        files+=("$p/main.xu")
    elif [ -d "$p" ]; then
        for f in "$p"/*.xu; do [ -f "$f" ] && files+=("$f"); done
        for f in "$p"/*/main.xu; do [ -f "$f" ] && files+=("$f"); done
    else
        files+=("$p")
    fi
done

total=0
fails=0
skipped=0
: > "$work/hits"
for f in "${files[@]}"; do
    dir=$(cd "$(dirname "$f")" && pwd)
    src="$dir/$(basename "$f")"
    for o in "${opts[@]}"; do
        total=$((total + 1))
        on="$work/on.bin"
        off="$work/off.bin"
        rm -f "$on" "$off"
        if ! (cd "$dir" && XU_PATTERNS_OFF= "$xu" build "$o" --timings "$src" -o "$on") >"$work/on.log" 2>&1; then
            skipped=$((skipped + 1))
            continue
        fi
        grep '^pattern-hits:' "$work/on.log" | tr ' ' '\n' | grep '=' >> "$work/hits"
        if ! (cd "$dir" && XU_PATTERNS_OFF=all "$xu" build "$o" "$src" -o "$off") >"$work/off.log" 2>&1; then
            echo "FAIL build (patterns off): $f $o"
            fails=$((fails + 1))
            continue
        fi
        (cd "$dir" && timeout_run 60 "$on") >"$work/on.out" 2>/dev/null </dev/null
        echo "exit=$?" >>"$work/on.out"
        (cd "$dir" && timeout_run 60 "$off") >"$work/off.out" 2>/dev/null </dev/null
        echo "exit=$?" >>"$work/off.out"
        if ! cmp -s "$work/on.out" "$work/off.out"; then
            echo "FAIL output: $f $o"
            fails=$((fails + 1))
        fi
    done
done

echo "pattern hits across corpus:"
if [ -s "$work/hits" ]; then
    awk -F= '{n[$1] += $2} END {for (k in n) printf "  %-18s %d\n", k, n[k]}' "$work/hits" | sort
else
    echo "  (none)"
fi
echo "pattern_diff: builds=$total fail=$fails skipped(build failed with patterns on)=$skipped"
[ "$fails" -eq 0 ]
