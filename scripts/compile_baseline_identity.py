#!/usr/bin/env python3
"""Reject a self-compile baseline from a different host or workload scale."""
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
from pathlib import Path

from companion_repos import project_root

ROOT = Path(__file__).resolve().parents[1]


def read_baseline(path):
    return dict(line.split("=", 1) for line in Path(path).read_text().splitlines()
                if line and not line.startswith("#") and "=" in line)


def identity():
    checked = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_bootstrap_xu_boundary.py"), "--json"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    source = json.loads(checked.stdout)["source_manifest"]
    if not source["complete"]:
        raise ValueError("incomplete compiler source closure")
    domains = json.loads((project_root("bootstrap", core_root=ROOT) / "BOUNDARY.json").read_text())["source_manifest"]["seed_domains"]
    return dict(
        host=f"{platform.system()}-{platform.machine()}",
        source_seed_files=str(source["seed_files"]),
        source_closure_files=str(source["closure_files"]),
        source_seed_bytes=str(sum(p.stat().st_size for d in domains for p in (ROOT / d).glob("*.xu"))),
        source_seed_sha256=source["seed_sha256"],
        source_closure_sha256=source["closure_sha256"],
        reference_primer_sha256=hashlib.sha256((project_root("bootstrap", core_root=ROOT) / "target/debug/xu").read_bytes()).hexdigest(),
        primer_opt="O0",
    )


def validate(baseline, current):
    errors = []
    for field in ("host", "source_seed_files", "source_closure_files", "primer_opt"):
        if not baseline.get(field) or baseline[field] != current[field]:
            errors.append(f"{field}: baseline={baseline.get(field, 'missing')} current={current[field]}")
    try:
        old, new = int(baseline["source_seed_bytes"]), int(current["source_seed_bytes"])
        if old <= 0 or abs(new - old) > old * 0.05:
            errors.append(f"source bytes changed by more than 5%: {old} -> {new}")
    except (KeyError, ValueError):
        errors.append("missing/invalid source_seed_bytes")
    for field in ("source_seed_sha256", "source_closure_sha256", "reference_primer_sha256"):
        if not baseline.get(field):
            errors.append(f"missing {field}")
    try:
        wall = float(baseline["gen1_wall"])
        total = re.search(r"\btotal=([0-9]+)ms\b", baseline["gen1_timings"])
        if not math.isfinite(wall) or wall <= 0 or total is None or int(total[1]) <= 0:
            errors.append("invalid/nonpositive reference timings")
    except (KeyError, ValueError):
        errors.append("missing/invalid reference timings")
    return errors


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: compile_baseline_identity.py BASELINE")
    baseline = read_baseline(sys.argv[1])
    current = identity()
    errors = validate(baseline, current)
    if errors:
        print("compile baseline: STALE/INCOMPARABLE; explicit calibration required", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("compile baseline: host, Primer profile and workload scale match")
    if baseline["reference_primer_sha256"] != current["reference_primer_sha256"]:
        # Rust debug paths/toolchain builds change this SHA even when the
        # canonical Primer source/profile is unchanged. Record the identity
        # change; it must still satisfy the same measured timing budget.
        print("compile baseline: Primer artifact changed; frozen O0 profile and original timing gate apply")
    if any(baseline[field] != current[field] for field in ("source_seed_sha256", "source_closure_sha256")):
        print("compile baseline: source contents changed within recorded workload scale; original 5% timing gate applies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
