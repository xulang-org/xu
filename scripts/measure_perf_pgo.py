#!/usr/bin/env python3
"""Train Xu edge PGO on Linux x86-64 and compare it on a held-out workload.

Example: python3 scripts/measure_perf_pgo.py --compiler ./bin/xu kernel.xu
    --train-arg train.bin --eval-arg holdout.bin --out /tmp/xu-pgo-run
Use a deterministic, repeatable program. Each argument may be repeated.
Results, the original perf.data and the two binaries are retained under --out.
"""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys

from import_perf_pgo import import_stacks
from resolve_pgo_edges import read_layout
from generate_pgo_profile import write_pgo_file


def run_measurement(args):
    if platform.system() != "Linux" or platform.machine() != "x86_64" or not shutil.which("perf"):
        raise ValueError("recording requires Linux x86-64 with perf and user-mode LBR")
    if args.pairs < 2:
        raise ValueError("--pairs must be at least two")
    if args.train_arg == args.eval_arg:
        raise ValueError("supply distinct training and held-out evaluation arguments")
    dest = args.out.resolve()
    dest.mkdir(parents=True, exist_ok=False)
    baseline = dest / "baseline"
    optimized = dest / "optimized"
    compiler = [str(args.compiler.resolve()), "build", str(args.source.resolve()), "--target", "linux-x64"]
    env = os.environ.copy()
    env.pop("XU_PGO_FILE", None)
    env.pop("XU_PGO_MAP", None)
    env["LC_ALL"] = "C"
    subprocess.run([*compiler, "-o", baseline], env={**env, "XU_PGO_MAP": "1"}, check=True)
    image = baseline.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    layout = read_layout(image, baseline.with_suffix(".xumap"), digest)
    (dest / "sampled.sha256").write_text(f"{digest}  {baseline}\n")
    data = dest / "perf.data"
    subprocess.run(["perf", "record", "-e", "cycles:u", "-j", "any,u", "-o", data,
                    "--", baseline, *args.train_arg], env=env, check=True)
    if hashlib.sha256(baseline.read_bytes()).hexdigest() != digest:
        raise ValueError("sampled executable changed during recording")
    stacks = dest / "stacks.txt"
    with stacks.open("w") as out:
        subprocess.run(["perf", "script", "--show-kernel-path", "-i", data, "-F", "brstack,dso"],
                       stdout=out, env=env, check=True)
    with stacks.open() as stream:
        profiles, stats = import_stacks(stream, str(baseline), image, layout)
    if not profiles:
        raise ValueError("no attributable edges; inspect stacks.txt and the training workload")
    profile = dest / "train.xupgo"
    write_pgo_file(profile, profiles)
    result = subprocess.run([*compiler, "--pgo", profile, "-o", optimized], env=env,
                            capture_output=True, text=True, check=True)
    if "ignoring mismatched edge profile" in result.stderr:
        raise ValueError(result.stderr.strip())
    binaries = (baseline, optimized)
    expected = None
    cycles = {path: [] for path in binaries}
    for pair in range(args.pairs):
        for binary in binaries if pair % 2 == 0 else reversed(binaries):
            report = dest / f"{binary.name}-{pair}.csv"
            cmd = ["perf", "stat", "-x", ";", "-o", report]
            for event in ["cycles:u", *args.event]:
                cmd.extend(["-e", event])
            proc = subprocess.run([*cmd, "--", binary, *args.eval_arg], env=env,
                                  capture_output=True, check=True)
            if expected is None:
                expected = proc.stdout
            if proc.stdout != expected:
                raise ValueError(f"held-out output differs for {binary.name} in pair {pair}")
            rows = [line.split(";") for line in report.read_text().splitlines()]
            values = [row[0].strip() for row in rows if len(row) >= 3 and row[2].strip() == "cycles:u"]
            if len(values) != 1 or not values[0].isdigit() or int(values[0]) == 0:
                raise ValueError(f"missing valid user cycles in {report}")
            cycles[binary].append(int(values[0]))
    ratios = [after / before for before, after in zip(cycles[baseline], cycles[optimized])]
    print(f"{stats['intervals']} sampled intervals, {len(profiles)} functions")
    print(f"Median paired change in user cycles: {(statistics.median(ratios) - 1) * 100:+.2f}%")
    print(f"Raw counters and profiles: {dest}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new results directory")
    parser.add_argument("--train-arg", action="append", default=[])
    parser.add_argument("--eval-arg", action="append", default=[])
    parser.add_argument("--event", action="append", default=[], help="additional perf stat event")
    parser.add_argument("--pairs", type=int, default=7)
    try:
        run_measurement(parser.parse_args())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
