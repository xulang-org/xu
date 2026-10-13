#!/usr/bin/env python3
"""Hosted cancellation gate: G/stack and select registration must retire.

Channel headers remain process-owned in the current ABI. Subtract that
known per-context/timer retention explicitly; it cannot conceal even one
leaked G stack (128 KiB), state or subscription. The bounded waiter pool may
retain at most 32 * 64 bytes, independently of loop count.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"live_bytes", "peak_bytes", "allocs", "frees", "unknown_frees",
          "double_frees", "ledger_overflows"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xu", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--modes", default="-O0,-O3")
    args = parser.parse_args()
    compiler = args.xu.resolve()
    report = {"compiler": str(compiler), "compiler_sha256": digest(compiler),
              "harness_sha256": digest(__file__), "source_sha256": {
                  str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "src").rglob("*.xu"))},
              "results": []}
    bodies = {
        "parent-child": "mut c := context.with_cancel_parent(&parent.ctx)\nsleep_ns(1000000)\nc.cancel()\nc.cancel()",
        "timeout": "mut c := context.with_timeout(600000000000)\nc.cancel()\nc.cancel()",
        "deadline": "mut c := context.with_deadline(now_ns() + 600000000000)\nc.cancel()",
        "timer": "t := time.new_timer(600000000000)\nt.stop()\nt.stop()",
        "ticker": "t := time.new_ticker(600000000000)\nt.stop()\nt.stop()",
        "select-error": "if failed_select(first, second) != -1 { << 1 }",
    }
    with tempfile.TemporaryDirectory(prefix="xu-cancel-lifetime-") as tmp:
        work = Path(tmp)
        for mode in args.modes.split(","):
            for kind, body in bodies.items():
                baseline = None
                for count in (0, 100, 1000):
                    src = work / "probe.xu"
                    source = "@main\n#context\n#time\n#errors\n"
                    if kind == "select-error":
                        source += "fn fail(ch chan int) chan int {\n>> errors.new(\"operand failed\")\n<< ch\n}\n"
                        source += "fn failed_select(first chan int, second chan int) int {\n"
                        source += "select { x := <-first { << x } y := <-(fail(second) or (err) { _ := err\n<< -1 }) { << y } }\n<< 0\n}\n"
                    source += "fn main() int {\nmut parent := context.with_cancel()\n"
                    if kind == "select-error":
                        source += "first := chan int{cap: 1}\nsecond := chan int{cap: 1}\n"
                    source += f"for i in 0:{count} {{\n{body}\n}}\n"
                    source += "sleep_ns(200000000)\nprintln(\"done\")\n<< 0\n}\n"
                    src.write_text(source)
                    binary = work / "probe.xin"
                    build = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), str(compiler),
                                            "build", str(src), mode, "-o", str(binary)],
                                           env=dict(os.environ, XU_GEN1_HEAP_LEDGER="1"),
                                           cwd=ROOT, capture_output=True, text=True, timeout=120)
                    if build.returncode:
                        raise SystemExit(build.stdout + build.stderr)
                    run = subprocess.run([str(binary)], env=dict(os.environ, XU_HEAP_STATS="1"),
                                         capture_output=True, text=True, timeout=5)
                    stats = {}
                    for line in run.stderr.splitlines():
                        match = re.fullmatch(r"xu_heap_stats ([a-z_]+)=([0-9]+)", line)
                        if not match or match[1] in stats:
                            raise SystemExit(f"invalid ledger: {run.stderr}")
                        stats[match[1]] = int(match[2])
                    # Zero iterations spawn no G. Imported Unicode/time
                    # tables retain a fixed live set, measured independently
                    # for the same program before any cancellation workers.
                    if count == 0:
                        baseline = dict(stats)
                    retained_channels = 0 if kind == "select-error" else 480 * count
                    extra = stats.get("live_bytes", -1) - baseline["live_bytes"] - retained_channels
                    ok = stats.keys() == FIELDS and run.returncode == 0 and run.stdout == "done\n"
                    ok = ok and 0 <= extra <= 2048 and extra % 64 == 0
                    channel_allocs = 0 if kind == "select-error" else 2 * count
                    ok = ok and stats["allocs"] - stats["frees"] - baseline["allocs"] + baseline["frees"] == channel_allocs + extra // 64
                    ok = ok and not any(stats[k] for k in ("unknown_frees", "double_frees", "ledger_overflows"))
                    entry = dict(kind=kind, mode=mode, count=count, passed=ok,
                                 stats=stats, baseline=baseline, known_channel_bytes=retained_channels,
                                 bounded_pool_bytes=extra, source=source, source_sha256=digest(src))
                    report["results"].append(entry)
                    print(f"{'PASS' if ok else 'FAIL'} {kind} {mode} n={count} {stats}", flush=True)
                    if not ok:
                        args.out.parent.mkdir(parents=True, exist_ok=True)
                        args.out.write_text(json.dumps(report, indent=2) + "\n")
                        raise SystemExit("cancellation lifetime invariant failed")
    assert digest(compiler) == report["compiler_sha256"]
    report["status"] = "PASS"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
