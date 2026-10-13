#!/usr/bin/env bash
# Coverage smoke for universal vreg plans (P4).
# Usage: scripts/coverage_smoke.sh [/path/to/xu]
# Exits 1 if any sample is below its SLO (warn-only message on stderr).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
XU="${1:-$ROOT/bin/xu}"
export XUPATH="" LC_ALL=C

if [[ ! -x "$XU" ]]; then
  echo "coverage_smoke: missing xu binary: $XU (try make xu / a /tmp candidate)" >&2
  exit 2
fi

# SLO: vreg/fn ratios from the universal-coverage plan.
# compiler uses the hosted Gen1 source list.
measure() {
  local label="$1"
  local slo_pct="$2"
  shift 2
  local out
  out="$("$XU" build "$@" --timings 2>&1 || true)"
  local line
  line="$(printf '%s\n' "$out" | rg '^ra-stats:' | tail -1 || true)"
  if [[ -z "$line" ]]; then
    echo "coverage_smoke: $label: no ra-stats (is --timings supported?)" >&2
    printf '%s\n' "$out" | rg -i 'error' | head -5 >&2 || true
    return 1
  fi
  local fn vreg
  fn="$(printf '%s\n' "$line" | sed -n 's/.* fn=\([0-9]*\).*/\1/p')"
  vreg="$(printf '%s\n' "$line" | sed -n 's/.* vreg=\([0-9]*\).*/\1/p')"
  if [[ -z "$fn" || -z "$vreg" || "$fn" -le 0 ]]; then
    echo "coverage_smoke: $label: bad stats: $line" >&2
    return 1
  fi
  local pct=$(( vreg * 100 / fn ))
  echo "$label: vreg=$vreg fn=$fn pct=$pct% slo=${slo_pct}%  ($line)"
  if [[ "$pct" -lt "$slo_pct" ]]; then
    echo "coverage_smoke: WARN $label below SLO ($pct% < ${slo_pct}%)" >&2
    return 1
  fi
  return 0
}

fail=0
# shellcheck disable=SC2086
. "$ROOT/scripts/gen1_sources.sh"
set -- $GEN1_SRCS
tmpc="$(mktemp /tmp/xu-cov-c.XXXXXX)"
measure "compiler" 70 "$@" -o "$tmpc" || fail=1
rm -f "$tmpc"

tmps="$(mktemp /tmp/xu-cov-s.XXXXXX)"
measure "strings_io" 90 "$ROOT/tests/data/compiler_workloads/strings_io.xu" -o "$tmps" || fail=1
rm -f "$tmps"

tmpr="$(mktemp /tmp/xu-cov-r.XXXXXX)"
measure "server" 85 "$ROOT/tests/data/compiler_workloads/http_server.xu" -o "$tmpr" || fail=1
rm -f "$tmpr"

if [[ "$fail" -ne 0 ]]; then
  echo "coverage_smoke: one or more samples below SLO" >&2
  exit 1
fi
echo "coverage_smoke: all samples meet SLO"
exit 0
