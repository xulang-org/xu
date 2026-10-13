#!/usr/bin/env python3
"""Functional + efficiency gate for the runtime-algo migration slices.

Compares an optional baseline compiler against the candidate
(cross-checked by run_fixtures / matrix separately). Here we only time
micro-benchmarks that stress the migrated names, so a quadratic copy or a
missed binding shows up as a wall-clock cliff.

Usage:
  python3 tests/test_runtime_algo_perf.py --new /tmp/xu-slice1/xu
  python3 tests/test_runtime_algo_perf.py --new /tmp/xu-slice1/xu --old bin/xu
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (name, source, iterations hint for the program itself)
BENCHES = {
    "starts_with_long": r"""
@main
fn mk(n int) string {
    mut b := []int{}
    for i in 0:n { b.push(120) }
    << string_from_bytes(b)
}
fn main() int {
    p := mk(2097152)
    mut n := 0
    for i in 0:20 {
        if starts_with("x", p) { n += 1 }
    }
    println(n)
    << 0
}
""",
    "parse_int_loop": r"""
@main
#errors
fn main() int {
    mut acc := 0
    for i in 0:200000 {
        acc += parse_int("12345") or (err) { << 0 }
    }
    println(acc)
    << 0
}
""",
    "itoa_loop": r"""
@main
fn main() int {
    mut n := 0
    for i in 0:100000 {
        s := str(i)
        n += s.len
    }
    println(n)
    << 0
}
""",
    "str_runes_long": r"""
@main
fn main() int {
    mut b := []int{}
    for i in 0:65536 { b.push(65) }
    s := string_from_bytes(b)
    r := s.runes()
    println(r.len)
    << 0
}
""",
    "is_digit_loop": r"""
@main
fn main() int {
    mut n := 0
    for i in 0:200000 {
        if is_digit(48) { n += 1 }
        if is_digit(65) { n += 1 }
        if is_space(32) { n += 1 }
        if is_alpha(97) { n += 1 }
    }
    println(n)
    << 0
}
""",
}


GOLDEN = {
    "starts_with_long": "0\n", "parse_int_loop": "2469000000\n",
    "itoa_loop": "488890\n", "str_runes_long": "65536\n",
    "is_digit_loop": "600000\n",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_run(binary: Path) -> float:
    t0 = time.perf_counter()
    p = subprocess.run([str(binary)], cwd=binary.parent, capture_output=True, timeout=60)
    elapsed = time.perf_counter() - t0
    if p.returncode != 0 or p.stderr or p.stdout != GOLDEN[binary.stem.split("-")[0]].encode():
        raise ValueError(f"{binary.name}: exit={p.returncode} stdout={p.stdout!r} stderr={p.stderr!r}")
    return elapsed


def summary(samples: list[float]) -> dict:
    return dict(median_s=statistics.median(samples), stdev_s=statistics.stdev(samples) if len(samples)>1 else 0,
                min_s=min(samples), max_s=max(samples), samples_s=samples)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    ap.add_argument("--old", default="", help="optional baseline; both use product wrapper")
    ap.add_argument("--only", default="")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--opt", type=int, choices=range(4), default=1)
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "xu-runtime-perf-report.json")
    args = ap.parse_args()
    if args.repeat < 2:
        ap.error("--repeat must be at least 2")
    compilers = {"new": Path(args.new).resolve()}
    if args.old:
        compilers["old"] = Path(args.old).resolve()
    names = [n for n in BENCHES if args.only in n]
    if not names:
        ap.error("--only matched no benchmarks")
    for compiler in compilers.values():
        if not compiler.is_file():
            ap.error(f"missing compiler: {compiler}")
    boundary = subprocess.run([sys.executable, "scripts/check_bootstrap_xu_boundary.py", "--strict-freeze", "--json"],
                              cwd=ROOT, capture_output=True, check=True)
    source_manifest = json.loads(boundary.stdout)["source_manifest"]
    sys.path.insert(0, str(ROOT))
    from scripts.verify_product_provenance import verify
    identity = {}
    for label, compiler in compilers.items():
        sidecar = Path(str(compiler) + ".provenance")
        provenance = sidecar.read_text() if sidecar.is_file() else None
        certified = False
        try:
            verify(compiler, source_manifest["closure_sha256"])
            certified = True
        except (ValueError, OSError):
            pass
        identity[label] = dict(path=str(compiler), sha256=sha(compiler),
                               provenance=provenance, verified_product=certified)
    report = dict(schema=2, lane="product-wrapper", target=platform.platform(), opt=args.opt,
                  source_manifest=source_manifest, compilers=identity, repeat=args.repeat,
                  warmup=1, method="alternating A/B, median and sample stdev; independent golden stdout/stderr/exit", benches={})
    failures = 0
    with tempfile.TemporaryDirectory(prefix="xu-runtime-perf-") as td:
        tmp = Path(td)
        for name in names:
            row = dict(source=BENCHES[name].lstrip("\n"), golden=dict(stdout=GOLDEN[name], stderr="", exit=0), builds={}, runs={})
            report["benches"][name] = row
            src = tmp / (name + ".xu")
            src.write_text(row["source"])
            row["source_sha256"] = sha(src)
            binaries = {}
            try:
                for label,compiler in compilers.items():
                    out = tmp / f"{name}-{label}"
                    command = [str(ROOT / "scripts/run_product_compiler.sh"), str(compiler), "build", str(src), f"-O{args.opt}", "-o", str(out)]
                    t0 = time.perf_counter()
                    cp = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=120)
                    row["builds"][label] = dict(seconds=time.perf_counter()-t0, command=command, exit=cp.returncode,
                                               stdout=cp.stdout.decode(errors="replace"), stderr=cp.stderr.decode(errors="replace"))
                    if cp.returncode or not out.is_file():
                        raise ValueError(f"{name}/{label}: compile failed")
                    row["builds"][label]["binary_sha256"] = sha(out)
                    binaries[label] = out
                    checked_run(out)
                samples = {label: [] for label in binaries}
                labels = list(binaries)
                for i in range(args.repeat):
                    for label in labels[::1 if i % 2 == 0 else -1]:
                        samples[label].append(checked_run(binaries[label]))
                row["runs"] = {label: summary(v) for label,v in samples.items()}
                if "old" in samples:
                    row["ratio"] = statistics.median(samples["new"]) / statistics.median(samples["old"])
                    if row["ratio"] > 1.5:
                        raise ValueError(f"{name}: runtime regression {row['ratio']:.2f}x")
                row["status"] = "PASS"
                print(name, row["runs"], flush=True)
            except (ValueError, subprocess.TimeoutExpired) as exc:
                row["status"] = "FAIL"
                row["error"] = str(exc)
                failures += 1
                print(str(exc), file=sys.stderr, flush=True)
    for label,c in compilers.items():
        if sha(c) != identity[label]["sha256"]:
            failures += 1
            report.setdefault("identity_errors", []).append(label + " compiler changed")
    final = subprocess.run([sys.executable, "scripts/check_bootstrap_xu_boundary.py", "--strict-freeze", "--json"],
                           cwd=ROOT, capture_output=True, check=True)
    if json.loads(final.stdout)["source_manifest"] != source_manifest:
        failures += 1
        report.setdefault("identity_errors", []).append("source changed during benchmark")
    report["failures"] = failures
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"runtime perf: failures={failures} report={args.out}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
