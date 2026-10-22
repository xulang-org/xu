#!/usr/bin/env python3
"""Fail-closed ARM32/RV32 differential gate; the host is the output reference.

Corpus programs print DONE immediately before returning from main. Bare-metal
QEMU parks after main returns, so its timeout is accepted only with that footer.
Known failures pin both the result kind and normalized evidence SHA256. Runner
failures are never eligible. --matrix emits a reproducible Markdown table;
--check-matrix compares a saved table with the current complete run.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "arm32_diff"
KNOWN = CORPUS / "known_diffs.txt"
TARGETS = ("linux-arm32", "thumbv7em-none", "riscv32imac-none")
KINDS = ("match", "rejected", "diff", "compile_fail", "run_fail")
DONE = "__ARM32_DIFF_DONE__"
EXPECT_RE = re.compile(r"^//\s*expect-32:\s*(match|reject)\s*(.*)$")


class GateError(RuntimeError):
    """Invalid inputs or infrastructure failure, never a known compiler diff."""


@dataclass(frozen=True)
class RunResult:
    stdout: str = ""
    error: str = ""


@dataclass(frozen=True)
class Result:
    name: str
    target: str
    kind: str
    evidence: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.evidence.encode("utf-8")).hexdigest()


def norm(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


def env_for() -> dict[str, str]:
    env = dict(os.environ)
    env["XU_ROOT"] = str(ROOT)
    env["XU_STDLIB_ROOT"] = str(ROOT / "src")
    env.pop("XU_WIDTH32", None)
    return env


def expectation(src: Path) -> tuple[str, str]:
    headers = [line.strip() for line in src.read_text(encoding="utf-8").splitlines()[:8]
               if "expect-32:" in line]
    if not headers:
        return "match", ""
    match = EXPECT_RE.fullmatch(headers[0])
    if len(headers) != 1 or not match:
        raise GateError(f"invalid expectation in {src}")
    mode, needle = match.group(1), match.group(2).strip()
    if (mode == "reject" and not needle) or (mode == "match" and needle):
        raise GateError(f"invalid expectation in {src}: {headers[0]}")
    return mode, needle


def build(compiler: Path, src: Path, out: Path, target: str | None) -> subprocess.CompletedProcess[str]:
    cmd = [str(compiler), "build", str(src), "-o", str(out)]
    if target:
        cmd[2:2] = ["--target", target]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env_for(), timeout=300)


def completed_output(output: str) -> RunResult:
    # A partial footer, repeated footer, or output after completion is a failure.
    lines = output.splitlines()
    if not lines or lines[-1] != DONE or lines.count(DONE) != 1:
        return RunResult(output, "missing or invalid completion footer")
    return RunResult(norm("\n".join(lines[:-1])))


def run_host(exe: Path) -> RunResult:
    try:
        result = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RunResult(error=f"host execution failed: {exc}")
    if result.returncode != 0:
        return RunResult(result.stdout, f"host exit {result.returncode}: {result.stderr}")
    return completed_output(result.stdout)


def qemu_tool(target: str) -> str:
    if target == "thumbv7em-none":
        return "qemu-system-arm"
    if target == "riscv32imac-none":
        return "qemu-system-riscv32"
    raise GateError(f"not a QEMU target: {target}")


def run_qemu(target: str, exe: Path, timeout: float) -> RunResult:
    command = [qemu_tool(target), "-M"]
    command += ["mps2-an386", "-nographic"] if target == "thumbv7em-none" else ["virt", "-nographic", "-bios", "none"]
    command += ["-kernel", str(exe)]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        return RunResult(error=f"QEMU launch failed: {exc}")
    timed_out = False
    try:
        output, errors = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        output, errors = process.communicate()
    stdout = output.decode("utf-8", "replace")
    stderr = errors.decode("utf-8", "replace")
    if stderr.strip() or (not timed_out and process.returncode != 0):
        return RunResult(stdout, f"QEMU exit {process.returncode}: {stderr}")
    completed = completed_output(stdout)
    if completed.error and timed_out:
        return RunResult(stdout, "QEMU timed out before completion")
    return completed


def run_docker_batch(exes: dict[str, Path], workdir: Path) -> dict[str, RunResult]:
    if not exes:
        return {}
    # Per-program files include its exit code; stdout cannot spoof framing.
    commands = ["#!/bin/sh\n"]
    for index, path in enumerate(exes.values()):
        prefix = f"/w/result-{index}"
        commands.append(f"{shlex.quote('/w/' + path.name)} > {prefix}.stdout 2> {prefix}.stderr\n")
        commands.append(f"printf '%s\\n' \"$?\" > {prefix}.status\n")
    (workdir / "run.sh").write_text("".join(commands), encoding="utf-8")
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--platform", "linux/arm/v7", "-v", f"{workdir}:/w",
             "busybox:latest", "sh", "/w/run.sh"],
            capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {name: RunResult(error=f"Docker execution failed: {exc}") for name in exes}
    if result.returncode != 0:
        return {name: RunResult(error=f"Docker exit {result.returncode}: {result.stderr}") for name in exes}
    outputs = {}
    for index, name in enumerate(exes):
        try:
            stdout = (workdir / f"result-{index}.stdout").read_text(encoding="utf-8")
            stderr = (workdir / f"result-{index}.stderr").read_text(encoding="utf-8")
            status = (workdir / f"result-{index}.status").read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            outputs[name] = RunResult(error=f"Docker missing/invalid result files: {exc}")
            continue
        if status != "0\n":
            outputs[name] = RunResult(stdout, f"target exit {status.strip()!r}: {stderr}")
        else:
            outputs[name] = completed_output(stdout)
    return outputs


def load_known(programs: set[str]) -> dict[tuple[str, str], tuple[str, str, str]]:
    known = {}
    if not KNOWN.is_file():
        return known
    for raw in KNOWN.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 4)
        if len(parts) != 5:
            raise GateError(f"known diff must pin name target kind sha256 reason: {raw!r}")
        name, target, kind, digest, reason = parts
        key = (name, target)
        if name not in programs or target not in TARGETS or key in known:
            raise GateError(f"unknown or duplicate known diff: {raw!r}")
        if kind not in ("match", "diff", "compile_fail") or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise GateError(f"invalid known diff kind/fingerprint: {raw!r}")
        known[key] = (kind, digest, reason)
    return known


def matrix_text(results: list[Result], tags: dict[tuple[str, str], str]) -> str:
    lines = ["<!-- Generated by scripts/arm32_diff_gate.py; do not edit. -->",
             "| Program | Target | Result | Status | Evidence SHA256 |",
             "| --- | --- | --- | --- | --- |"]
    for result in sorted(results, key=lambda item: (item.name, item.target)):
        lines.append(f"| {result.name} | {result.target} | {result.kind} | {tags[(result.name, result.target)]} | {result.digest} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xu", required=True, type=Path)
    parser.add_argument("--targets", default=",".join(TARGETS))
    parser.add_argument("--only", default="")
    parser.add_argument("--qemu-timeout", type=float, default=4.0)
    parser.add_argument("--matrix", type=Path, help="write the measured result table, including failures")
    parser.add_argument("--check-matrix", type=Path, help="fail if the measured table differs from this file")
    args = parser.parse_args(argv)
    targets = [target.strip() for target in args.targets.split(",")]
    if not targets or any(target not in TARGETS for target in targets) or len(set(targets)) != len(targets):
        parser.error("--targets must be a nonempty, unique comma-separated subset of " + ",".join(TARGETS))
    if not math.isfinite(args.qemu_timeout) or args.qemu_timeout <= 0:
        parser.error("--qemu-timeout must be finite and positive")
    try:
        return run_gate(args, targets)
    except (GateError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        print(f"FATAL {exc}", file=sys.stderr)
        return 2


def run_gate(args: argparse.Namespace, targets: list[str]) -> int:
    compiler = args.xu.resolve()
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise GateError(f"compiler is not executable: {compiler}")
    all_programs = sorted(CORPUS.glob("*.xu"))
    known = load_known({program.stem for program in all_programs})
    programs = [program for program in all_programs if not args.only or program.stem == args.only]
    if not programs:
        raise GateError("no ARM32 differential corpus files selected")
    expectations = {program.stem: expectation(program) for program in programs}
    selected = {(program.stem, target) for program in programs for target in targets}
    results: dict[tuple[str, str], Result] = {}

    def record(name: str, target: str, kind: str, evidence: str) -> None:
        key = (name, target)
        if key not in selected or key in results:
            raise GateError(f"unexpected or duplicate result: {name} {target}")
        results[key] = Result(name, target, kind, norm(evidence))

    with tempfile.TemporaryDirectory(prefix="arm32-diff-") as temp_dir:
        workdir = Path(temp_dir)
        references = {}
        for program in programs:
            output = workdir / f"{program.stem}.host"
            built = build(compiler, program, output, None)
            if built.returncode != 0:
                raise GateError(f"host build failed for {program.stem}:\n{built.stderr}")
            ran = run_host(output)
            if ran.error:
                raise GateError(f"host reference failed for {program.stem}: {ran.error}")
            references[program.stem] = ran.stdout

        docker_exes = {}
        qemu_jobs = []
        for program in programs:
            mode, needle = expectations[program.stem]
            for target in targets:
                output = workdir / f"{program.stem}.{target}"
                built = build(compiler, program, output, target)
                if built.returncode != 0:
                    diagnostics = norm(built.stderr + built.stdout).replace(str(workdir), "<workdir>").replace(str(ROOT), "<root>")
                    # Crashes and diagnostics on stdout are never expected rejection.
                    if built.returncode > 0 and mode == "reject" and needle in built.stderr:
                        record(program.stem, target, "rejected", needle)
                    else:
                        kind = "compile_fail" if built.returncode > 0 else "run_fail"
                        record(program.stem, target, kind, f"exit={built.returncode}\n{diagnostics}")
                    continue
                if not output.is_file():
                    record(program.stem, target, "run_fail", "compiler succeeded without an output binary")
                elif target == "linux-arm32":
                    docker_exes[program.stem] = output
                else:
                    qemu_jobs.append((program.stem, target, output))

        outputs = {}
        if docker_exes:
            batch = run_docker_batch(docker_exes, workdir) if shutil.which("docker") else {}
            if set(batch) - set(docker_exes):
                raise GateError("Docker returned unknown program results")
            for name in docker_exes:
                outputs[(name, "linux-arm32")] = batch.get(name, RunResult(error="Docker unavailable or missing program result"))
        if qemu_jobs:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                futures = {executor.submit(run_qemu, target, output, args.qemu_timeout): (name, target)
                           for name, target, output in qemu_jobs}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        outputs[futures[future]] = future.result()
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        outputs[futures[future]] = RunResult(error=f"QEMU execution failed: {exc}")
        for (name, target), output in outputs.items():
            if output.error:
                record(name, target, "run_fail", output.error)
            else:
                record(name, target, "match" if output.stdout == references[name] else "diff", output.stdout)

    if set(results) != selected:
        raise GateError(f"incomplete result matrix: expected {len(selected)}, got {len(results)}")
    seen_known = 0
    unexpected = 0
    tags = {}
    for key, result in sorted(results.items()):
        mode, _ = expectations[result.name]
        expected = result.kind == ("match" if mode == "match" else "rejected")
        entry = known.get(key)
        if expected:
            tag = "ok"
        elif result.kind != "run_fail" and entry is not None and (result.kind, result.digest) == entry[:2]:
            seen_known += 1
            tag = "known"
        else:
            unexpected += 1
            tag = "UNEXPECTED"
        tags[key] = tag
        print(f"RESULT {result.name} {result.target} {result.kind} {tag}")
        if not expected:
            print(f"--- {result.name} {result.target} {result.kind} sha256={result.digest}:\n{result.evidence}", file=sys.stderr)
    stale = len(set(known) & selected) - seen_known
    matrix = matrix_text(list(results.values()), tags)
    if args.matrix:
        args.matrix.write_text(matrix, encoding="utf-8")
    matrix_mismatch = bool(args.check_matrix and args.check_matrix.read_text(encoding="utf-8") != matrix)
    if matrix_mismatch:
        print(f"support matrix differs: {args.check_matrix}", file=sys.stderr)
    counts = {kind: sum(result.kind == kind for result in results.values()) for kind in KINDS}
    print("SUMMARY " + " ".join(f"{kind}={counts[kind]}" for kind in KINDS)
          + f" known={seen_known} stale_known={stale} unexpected={unexpected} total={len(results)} expected={len(selected)} matrix_mismatch={int(matrix_mismatch)}")
    return 0 if unexpected == 0 and stale == 0 and not matrix_mismatch else 1


if __name__ == "__main__":
    raise SystemExit(main())
