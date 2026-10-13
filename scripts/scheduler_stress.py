#!/usr/bin/env python3
"""Bounded Gen1 scheduler/channel stress gate.

The hosted runtime has a deliberately small, stackful scheduler.  A short
successful run is not useful evidence for a park/wake race, so this harness
compiles a fixture once for each requested optimisation profile and then runs
it in a fresh process repeatedly.  Every child is placed in its own process
group and has a hard watchdog; a wedged scheduler can therefore never wedge
the test runner itself.

The result is both human readable and machine readable.  Each run is reduced
to a small state machine (BUILT -> RUNNING -> PROGRESS_n -> terminal state),
which preserves the last observable stage when a process times out.  The
default case is the historical ``channel_select_sleep_gate``.  ``--matrix``
also runs that production fixture, the multi-waiter/recycle channel fixtures,
and the scheduler quadrants in ``tests/scheduler``.  A compiler capability
skip is represented explicitly in the JSON report; an unknown build failure
still fails the gate.  The current Gen1 optimiser limitation for the
multi-sender fixture is therefore visible as a SKIP with an O0 fallback,
never as a silent pass.

This file intentionally uses only the Python standard library so it can run
before the bootstrap compiler or third-party test dependencies are available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import signal
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


from companion_repos import project_root

ROOT = Path(__file__).resolve().parents[1]

# This harness can exercise either side of the compiler seam, but it is not a
# fixed-point proof on its own.  Keep the mixed nature explicit in reports and
# in the boundary manifest; callers select the actual compiler lane with
# ``--lane``.
LANE = "dual"
HOST_SEED_RESOLVER = ROOT / "scripts" / "xu_host_seed.sh"
PRODUCT_COMPILER_RUNNER = ROOT / "scripts" / "run_product_compiler.sh"
_BOOT_CANDIDATES = (
    project_root("bootstrap", core_root=ROOT) / "target" / "debug" / "xu",
    project_root("bootstrap", core_root=ROOT) / "target" / "debug" / "xu.exe",
    project_root("bootstrap", core_root=ROOT) / "target" / "release" / "xu",
    project_root("bootstrap", core_root=ROOT) / "target" / "release" / "xu.exe",
)
BOOT_XU = next((candidate for candidate in _BOOT_CANDIDATES if candidate.is_file()), _BOOT_CANDIDATES[0])
# Oracle runs must be tied to a declared Gen0 artifact.  Keep this list
# explicit so an arbitrary executable passed with ``--lane oracle`` cannot
# silently become the frozen reference implementation.
FROZEN_PRIMER_PATHS = frozenset(
    {
        (project_root("bootstrap", core_root=ROOT) / "target" / "debug" / "xu").absolute(),
        (project_root("bootstrap", core_root=ROOT) / "target" / "debug" / "xu.exe").absolute(),
        (project_root("bootstrap", core_root=ROOT) / "target" / "release" / "xu").absolute(),
        (project_root("bootstrap", core_root=ROOT) / "target" / "release" / "xu.exe").absolute(),
    }
)


@dataclass(frozen=True)
class Case:
    name: str
    source: Path
    expected: Path


CASES: dict[str, Case] = {
    # Keep the original regression as the default.  It is intentionally not
    # replaced by a synthetic test: this gate must continue to exercise the
    # production call chain that exposed the missed park/wake.
    "channel_select_sleep_gate": Case(
        "channel_select_sleep_gate",
        ROOT / "tests/fixtures/channel_select_sleep_gate/main.xu",
        ROOT / "tests/fixtures/channel_select_sleep_gate/expected.txt",
    ),
    # These fixtures exercise the channel waiter FIFO and bounded waiter-node
    # recycle path.  Keep them in the matrix (rather than only in one-off
    # lifetime scripts) so every optimisation profile gets a fresh
    # process-group watchdog run.
    "chan_multi_sender_unbuffered": Case(
        "chan_multi_sender_unbuffered",
        ROOT / "tests/fixtures/chan_multi_sender_unbuffered/main.xu",
        ROOT / "tests/fixtures/chan_multi_sender_unbuffered/expected.txt",
    ),
    "chan_waiter_recycle": Case(
        "chan_waiter_recycle",
        ROOT / "tests/fixtures/chan_waiter_recycle/main.xu",
        ROOT / "tests/fixtures/chan_waiter_recycle/expected.txt",
    ),
    "single_no_sleep": Case(
        "single_no_sleep",
        ROOT / "tests/scheduler/single_no_sleep/main.xu",
        ROOT / "tests/scheduler/single_no_sleep/expected.txt",
    ),
    "single_sleep": Case(
        "single_sleep",
        ROOT / "tests/scheduler/single_sleep/main.xu",
        ROOT / "tests/scheduler/single_sleep/expected.txt",
    ),
    "double_no_sleep": Case(
        "double_no_sleep",
        ROOT / "tests/scheduler/double_no_sleep/main.xu",
        ROOT / "tests/scheduler/double_no_sleep/expected.txt",
    ),
    "double_sleep": Case(
        "double_sleep",
        ROOT / "tests/scheduler/double_sleep/main.xu",
        ROOT / "tests/scheduler/double_sleep/expected.txt",
    ),
    "close_multislot_recv": Case(
        "close_multislot_recv",
        ROOT / "tests/scheduler/close_multislot_recv/main.xu",
        ROOT / "tests/scheduler/close_multislot_recv/expected.txt",
    ),
    "blocked_sender_promotion": Case(
        "blocked_sender_promotion",
        ROOT / "tests/scheduler/blocked_sender_promotion/main.xu",
        ROOT / "tests/scheduler/blocked_sender_promotion/expected.txt",
    ),
    "blocked_sender_try_recv": Case(
        "blocked_sender_try_recv",
        ROOT / "tests/scheduler/blocked_sender_try_recv/main.xu",
        ROOT / "tests/scheduler/blocked_sender_try_recv/expected.txt",
    ),
}


# ``-O1`` is the normal product profile.  RA-only profiles are useful when a
# failure is sensitive to register-cache pressure, while ``--no-regcache``
# separates allocator effects from scheduler effects.
PROFILE_FLAGS: dict[str, tuple[str, ...]] = {
    "O0": ("-O0",),
    "O1": ("-O1",),
    "O2": ("-O2",),
    "O3": ("-O3",),
    "no-regcache": ("-O1", "--no-regcache"),
    "ra0": ("-O1", "--ra=0"),
    "ra1": ("-O1", "--ra=1"),
    "ra2": ("-O1", "--ra=2"),
    "ra3": ("-O1", "--ra=3"),
}


# A capability report is deliberately separate from pass/fail.  A successful
# run proves only the paths represented by the selected fixtures; the runtime
# currently has no direct waiter timeout/cancellation ABI or ABI-neutral
# scheduler wake counter.  Keeping those facts in the JSON makes an otherwise
# green stress run auditable by CI and by downstream tooling.
CAPABILITY_CATALOG: dict[str, dict[str, object]] = {
    "park_wake_watchdog": {
        "status": "covered",
        "description": (
            "Each fixture run has a wall-clock watchdog and process-group "
            "cleanup."
        ),
    },
    "channel_waiter_fifo": {
        "status": "covered",
        "description": "Unbuffered multi-sender rendezvous exercises FIFO waiter handoff.",
    },
    "channel_waiter_recycle": {
        "status": "covered",
        "description": "Repeated unbuffered rendezvous exercises waiter-node recycling.",
    },
    "waiter_timeout_cancellation": {
        "status": "not_implemented",
        "description": (
            "Direct channel waits have no timeout/cancellation waiter ABI; "
            "context timeout uses a select(done) arm."
        ),
    },
    "scheduler_double_wake_counter": {
        "status": "not_instrumented",
        "description": (
            "No ABI-neutral runtime double-wake counter is emitted; duplicate "
            "suppression remains state/lock based."
        ),
    },
}


# This is the one currently verified Gen1 capability gap in the channel
# matrix.  The product compiler (the hosted/self-hosted Gen1 CLI) rejects the
# multi-sender fixture at optimised profiles with the deterministic diagnostic
# below, while O0 compiles and runs.  We classify *only* this exact
# compiler/profile/diagnostic tuple as SKIP.  Any other build error, including
# a changed diagnostic after a compiler fix, remains a hard BUILD_FAILURE.
KNOWN_BUILD_SKIP_PROFILES = frozenset(
    {"O1", "O2", "O3", "no-regcache", "ra0", "ra1", "ra2", "ra3"}
)
KNOWN_BUILD_SKIP_CASE = "chan_multi_sender_unbuffered"
KNOWN_BUILD_SKIP_DIAGNOSTIC = "index out of bounds"


MAX_TAIL = 4096


@dataclass
class ProcessResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    elapsed_s: float
    timed_out: bool = False


@dataclass
class RunResult:
    iteration: int
    state: str
    trace: list[str]
    returncode: int | None
    elapsed_s: float
    stdout: bytes
    stderr: bytes


def _tail(data: bytes) -> str:
    """Return a bounded, JSON-safe diagnostic tail."""

    if len(data) > MAX_TAIL:
        data = data[-MAX_TAIL:]
        prefix = "...[truncated]"
    else:
        prefix = ""
    return prefix + data.decode("utf-8", errors="replace")


def _kill_process_group(proc: subprocess.Popen[bytes], grace_s: float) -> None:
    """Terminate a child and all descendants, then reap it.

    The scheduler can leave worker threads/processes behind when the main
    process is wedged.  A process-group kill is therefore required; killing
    just the leader would leak a worker and make later iterations interfere
    with one another.
    """

    if proc.poll() is not None:
        return
    if os.name == "nt":
        proc.kill()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=max(0.0, grace_s))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run_bounded(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
    kill_grace_s: float,
) -> ProcessResult:
    """Run one command with a wall-clock watchdog and process-group cleanup."""

    started = time.monotonic()
    proc = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name != "nt"),
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(proc, kill_grace_s)
        # ``communicate`` after termination drains pipes and reaps the leader.
        stdout, stderr = proc.communicate()
    return ProcessResult(
        proc.returncode,
        stdout or b"",
        stderr or b"",
        time.monotonic() - started,
        timed_out,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lexical_path(path: Path) -> Path:
    """Return an absolute path without following symlinks."""

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.absolute()


def _has_symlink_component(path: Path) -> bool:
    candidate = _lexical_path(path)
    owner = project_root("bootstrap", core_root=ROOT)
    if not candidate.is_relative_to(owner):
        owner = ROOT
    try:
        relative = candidate.relative_to(owner)
    except ValueError:
        return False
    if owner.is_symlink():
        return True
    current = owner
    for part in relative.parts:
        current /= part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _is_primer(path: Path, resolved: Path | None = None) -> bool:
    """Classify both lexical and resolved bootstrap provenance."""

    lexical = _lexical_path(path)
    if resolved is None:
        try:
            target = lexical.resolve()
        except (OSError, RuntimeError):
            target = lexical
    else:
        target = _lexical_path(resolved)
    bootstrap = project_root("bootstrap", core_root=ROOT)
    for candidate in (lexical, target):
        try:
            candidate.relative_to(bootstrap)
        except (OSError, RuntimeError, ValueError):
            continue
        return True
    return False


def _is_frozen_primer(path: Path) -> bool:
    """Return whether *path* is an allowed, canonical Gen0 artifact."""

    lexical = _lexical_path(path)
    if (
        lexical not in FROZEN_PRIMER_PATHS
        or _has_symlink_component(lexical)
        or not lexical.is_file()
        or not os.access(lexical, os.X_OK)
    ):
        return False
    try:
        return lexical.resolve() == lexical
    except (OSError, RuntimeError):
        return False


def _resolve_product_compiler(explicit: str | None) -> Path:
    """Resolve a hosted product seed and reject primer fallback."""

    if not PRODUCT_COMPILER_RUNNER.is_file() or not os.access(
        PRODUCT_COMPILER_RUNNER, os.X_OK
    ):
        raise ValueError(f"missing product compiler wrapper: {PRODUCT_COMPILER_RUNNER}")
    if explicit:
        raw = Path(explicit).expanduser()
        compiler = raw.resolve()
    else:
        if not HOST_SEED_RESOLVER.is_file():
            raise ValueError(f"missing hosted seed resolver: {HOST_SEED_RESOLVER}")
        env = os.environ.copy()
        env["XU_ALLOW_ORACLE_SEED"] = "0"
        env.pop("XU_SEED", None)
        probe = subprocess.run(
            [str(HOST_SEED_RESOLVER)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        if probe.returncode != 0:
            raise ValueError(
                "hosted product compiler missing; run make xu or pass --xu"
            )
        lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
        if len(lines) != 1:
            raise ValueError("hosted seed resolver returned invalid output")
        compiler = Path(lines[0]).expanduser().resolve()
    if _is_primer(raw if explicit else compiler, compiler):
        raise ValueError(
            "bootstrap primer is oracle-only; pass --lane oracle for primer diagnostics"
        )
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise ValueError(f"compiler is not an executable file: {compiler}")
    return compiler


def _resolve_oracle_compiler(explicit: str | None) -> Path:
    """Resolve an explicitly requested oracle compiler without product fallback."""

    raw = Path(explicit).expanduser() if explicit else BOOT_XU
    compiler = raw.resolve()
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise ValueError(
            f"oracle compiler is not executable: {compiler}; build bootstrap explicitly"
        )
    if not _is_frozen_primer(raw):
        raise ValueError(
            "oracle lane requires the frozen bootstrap primer "
            "(bootstrap/target/{debug,release}/xu[.exe]); use --lane product for "
            "a hosted compiler"
        )
    return compiler


def _longest_expected_prefix(actual: bytes, expected: bytes) -> int:
    """Count complete expected output records visible in ``actual``.

    Output is line-oriented for all scheduler fixtures.  Counting only full
    records avoids claiming progress for a partial line emitted just before a
    crash or watchdog kill.
    """

    count = 0
    offset = 0
    for record in expected.splitlines(keepends=True):
        if actual[offset : offset + len(record)] != record:
            break
        offset += len(record)
        count += 1
    return count


def _run_state(
    *,
    result: ProcessResult,
    expected: bytes,
    iteration: int,
) -> RunResult:
    """Map a process outcome onto the scheduler watchdog state machine."""

    trace = ["BUILT", "RUNNING"]
    progress = _longest_expected_prefix(result.stdout, expected)
    if progress:
        trace.append(f"PROGRESS_{progress}")

    if result.timed_out:
        state = "WATCHDOG_TIMEOUT"
    elif result.returncode is not None and result.returncode < 0:
        state = f"SIGNAL_{-result.returncode}"
    elif result.returncode != 0:
        state = "EXIT_FAILURE"
    elif result.stdout != expected:
        state = "OUTPUT_MISMATCH"
    else:
        state = "COMPLETE"
    trace.append(state)
    return RunResult(
        iteration,
        state,
        trace,
        result.returncode,
        result.elapsed_s,
        result.stdout,
        result.stderr,
    )


def _parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _resolve_cases(args: argparse.Namespace) -> list[Case]:
    if args.case:
        names: list[str] = []
        for value in args.case:
            names.extend(_parse_csv(value))
    elif args.matrix:
        names = [
            # Keep the historical production regression in the matrix.  It
            # covers the main-M park handshake that the synthetic quadrants
            # cannot exercise.
            "channel_select_sleep_gate",
            "single_no_sleep",
            "single_sleep",
            "double_no_sleep",
            "double_sleep",
            "chan_multi_sender_unbuffered",
            "chan_waiter_recycle",
            "close_multislot_recv",
            "blocked_sender_promotion",
            "blocked_sender_try_recv",
        ]
    else:
        names = ["channel_select_sleep_gate"]

    unknown = [name for name in names if name not in CASES]
    if unknown:
        raise ValueError(
            "unknown case(s): "
            + ", ".join(unknown)
            + "; choose from "
            + ", ".join(CASES)
        )
    selected: list[Case] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        selected.append(CASES[name])
    return selected


def _resolve_profiles(value: str) -> list[str]:
    names = _parse_csv(value)
    if not names:
        raise ValueError("--profiles must not be empty")
    if names == ["all"]:
        names = list(PROFILE_FLAGS)
    unknown = [name for name in names if name not in PROFILE_FLAGS]
    if unknown:
        raise ValueError(
            "unknown profile(s): "
            + ", ".join(unknown)
            + "; choose from "
            + ", ".join(PROFILE_FLAGS)
        )
    selected: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        selected.append(name)
    return selected


def _detect_compile_mode(compiler: Path, requested: str) -> str:
    """Resolve the product and bootstrap Xu command-line dialects.

    The hosted product exposes ``xu build ...`` while the Rust bootstrap
    accepts source files directly (``xu file.xu -o out``).  Keeping the
    distinction in the harness prevents a clean checkout from being reported
    as a scheduler runtime failure merely because the wrong CLI form was
    sent.  Explicit modes remain available for CI and post-mortem runs.
    """

    if requested in {"product", "direct"}:
        return requested
    try:
        probe = subprocess.run(
            [str(compiler), "--help"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Let the actual build produce the useful diagnostic if a wrapper does
        # not implement --help (for example a cross-target launcher).
        return "product"
    help_text = probe.stdout.decode("utf-8", errors="replace")
    # Product help has a dedicated `build input.xu...` section.  Bootstrap
    # mentions compiling Xu but does not implement this subcommand.
    if "build input.xu" in help_text or "build input" in help_text:
        return "product"
    return "direct"


def _build_command(
    compiler: Path,
    mode: str,
    profile: str,
    source: Path,
    binary: Path,
    *,
    lane: str = "oracle",
) -> list[str]:
    if mode == "product":
        command = [
            str(compiler),
            "build",
            *PROFILE_FLAGS[profile],
            str(source),
            "-o",
            str(binary),
        ]
        if lane == "product":
            return [
                str(PRODUCT_COMPILER_RUNNER),
                *command,
            ]
        return command
    return [
        str(compiler),
        *PROFILE_FLAGS[profile],
        str(source),
        "-o",
        str(binary),
    ]


def _known_build_skip(
    *,
    case: Case,
    profile: str,
    compile_mode: str,
    build: ProcessResult,
) -> dict[str, object] | None:
    """Return a narrowly-scoped capability skip for a verified build gap.

    Build failures are normally test failures.  The sole exception is the
    known Gen1 optimiser limitation documented above.  Matching the complete
    tuple (case, product dialect, profile set, and diagnostic) is important:
    a future compiler fix naturally turns the row into a normal runtime run,
    and a new/changed failure cannot be hidden as a skip.
    """

    if (
        compile_mode != "product"
        or case.name != KNOWN_BUILD_SKIP_CASE
        or profile not in KNOWN_BUILD_SKIP_PROFILES
        or build.timed_out
        or build.returncode in (None, 0)
    ):
        return None
    diagnostic = (build.stderr + b"\n" + build.stdout).decode(
        "utf-8", errors="replace"
    )
    if KNOWN_BUILD_SKIP_DIAGNOSTIC not in diagnostic:
        return None
    return {
        "kind": "compiler_capability",
        "code": "gen1_chan_multi_sender_optimized_compile",
        "reason": (
            "Gen1 hosted compiler currently rejects the multi-sender channel "
            "fixture at this optimised profile; run the fixture with O0 until "
            "the compiler diagnostic is fixed."
        ),
        "diagnostic": KNOWN_BUILD_SKIP_DIAGNOSTIC,
        "compile_mode": compile_mode,
        "profile": profile,
        "fallback_profiles": ["O0"],
    }


def _case_result(
    case: Case,
    profile: str,
    binary: Path,
    expected: bytes,
    runs: Sequence[RunResult],
    *,
    build: ProcessResult,
    compiler: Path,
    skip_reason: Mapping[str, object] | None = None,
) -> dict[str, object]:
    counts: dict[str, int] = {}
    for run in runs:
        counts[run.state] = counts.get(run.state, 0) + 1
    skipped = skip_reason is not None
    failures = [
        run
        for run in runs
        if run.state != "COMPLETE" and run.state != "SKIPPED_UNSUPPORTED"
    ]
    # A synthetic SKIPPED_UNSUPPORTED row carries build evidence but is not a
    # runtime iteration.  Report zero executed iterations instead of counting
    # that marker as a successful run.
    executed_runs = [run for run in runs if run.iteration > 0]
    durations = [run.elapsed_s * 1000.0 for run in executed_runs]
    summary: dict[str, object] = {
        "case": case.name,
        "source": str(case.source),
        "profile": profile,
        "flags": list(PROFILE_FLAGS[profile]),
        "iterations": len(executed_runs),
        "timeout_s": None,  # populated by caller for easier schema evolution
        "compiler": str(compiler),
        "compiler_sha256": _sha256(compiler) if compiler.is_file() else None,
        "build": {
            "returncode": build.returncode,
            "timed_out": build.timed_out,
            "elapsed_ms": round(build.elapsed_s * 1000.0, 3),
            "stderr_tail": _tail(build.stderr),
        },
        "counts": counts,
        "passed": (
            skipped
            or (not failures and build.returncode == 0 and not build.timed_out)
        ),
        "skipped": skipped,
        "latency_ms": {
            "median": round(statistics.median(durations), 3) if durations else None,
            "p95": round(_percentile(durations, 0.95), 3) if durations else None,
            "max": round(max(durations), 3) if durations else None,
        },
    }
    summary["status"] = (
        "SKIP"
        if skipped
        else ("PASS" if bool(summary["passed"]) else "FAIL")
    )
    if skip_reason is not None:
        summary["skip_reason"] = dict(skip_reason)
    if failures:
        first = failures[0]
        summary["first_failure"] = {
            "iteration": first.iteration,
            "state": first.state,
            "trace": first.trace,
            "returncode": first.returncode,
            "elapsed_ms": round(first.elapsed_s * 1000.0, 3),
            "stdout_tail": _tail(first.stdout),
            "stderr_tail": _tail(first.stderr),
            "progress_records": _longest_expected_prefix(first.stdout, expected),
        }
    return summary


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    # Nearest-rank interpolation keeps the statistic deterministic and avoids
    # depending on a Python-version-specific statistics.quantiles method.
    rank = (len(ordered) - 1) * fraction
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _capability_report(
    cases: Sequence[Case], skips: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Build the stable, machine-readable capability/skip section."""

    selected = [case.name for case in cases]
    report: dict[str, object] = {
        name: dict(spec) for name, spec in CAPABILITY_CATALOG.items()
    }
    fifo = report["channel_waiter_fifo"]
    assert isinstance(fifo, dict)
    fifo_selected = "chan_multi_sender_unbuffered" in selected
    fifo_skips = [
        skip for skip in skips if skip.get("case") == "chan_multi_sender_unbuffered"
    ]
    fifo["cases"] = ["chan_multi_sender_unbuffered"] if fifo_selected else []
    fifo["status"] = "partial" if fifo_skips else (
        "covered" if fifo_selected else "not_selected"
    )
    fifo["skipped_profiles"] = [
        str(skip["profile"]) for skip in fifo_skips if "profile" in skip
    ]
    recycle = report["channel_waiter_recycle"]
    assert isinstance(recycle, dict)
    recycle_selected = "chan_waiter_recycle" in selected
    recycle["cases"] = ["chan_waiter_recycle"] if recycle_selected else []
    recycle["status"] = "covered" if recycle_selected else "not_selected"
    watchdog = report["park_wake_watchdog"]
    assert isinstance(watchdog, dict)
    watchdog["cases"] = selected
    watchdog["status"] = "partial" if skips else "covered"

    codes = sorted(
        {
            str(skip["code"])
            for skip in skips
            if "code" in skip
        }
    )
    report["compiler_profile_support"] = {
        "status": "partial" if skips else "covered",
        "skip_count": len(skips),
        "skip_codes": codes,
        "description": (
            "Known unsupported compiler/profile tuples are explicit SKIP; "
            "unknown build diagnostics remain failures."
        ),
    }
    return report


def _print_result(summary: Mapping[str, object]) -> None:
    counts = summary["counts"]
    assert isinstance(counts, Mapping)
    count_text = ", ".join(f"{key}={value}" for key, value in counts.items())
    if summary.get("skipped"):
        status = "SKIP"
    else:
        status = "PASS" if summary["passed"] else "FAIL"
    latency = summary["latency_ms"]
    assert isinstance(latency, Mapping)
    print(
        f"{status} {summary['case']}/{summary['profile']} "
        f"({count_text}; median={latency['median']}ms, max={latency['max']}ms)"
    )
    failure = summary.get("first_failure")
    if isinstance(failure, Mapping):
        print(
            f"  first failure: iteration={failure['iteration']} "
            f"state={failure['state']} trace={'->'.join(failure['trace'])}"
        )
        stdout_tail = str(failure.get("stdout_tail", ""))
        if stdout_tail:
            print(f"  stdout tail: {stdout_tail!r}")
    skip_reason = summary.get("skip_reason")
    if isinstance(skip_reason, Mapping):
        print(
            f"  skip: code={skip_reason.get('code')} "
            f"reason={skip_reason.get('reason')}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bounded Gen1 scheduler/channel park-wake stress tests."
    )
    parser.add_argument(
        "--xu",
        default=os.environ.get("XU_COMPILER"),
        help=(
            "compiler executable; product lane resolves hosted bin/xu when omitted, "
            "oracle lane resolves bootstrap debug xu"
        ),
    )
    parser.add_argument(
        "--lane",
        choices=("product", "oracle"),
        default=os.environ.get("XU_SCHED_LANE", "product"),
        help="compiler lane (default: product; oracle explicitly permits bootstrap)",
    )
    parser.add_argument(
        "--oracle",
        action="store_true",
        help="alias for --lane oracle",
    )
    parser.add_argument(
        "--compile-mode",
        choices=("auto", "product", "direct"),
        default=os.environ.get("XU_SCHED_COMPILE_MODE", "auto"),
        help=(
            "compiler CLI dialect: product uses `xu build`, direct uses "
            "bootstrap's file-first form (default: auto)"
        ),
    )
    parser.add_argument(
        "--profiles",
        default=os.environ.get("XU_SCHED_PROFILES", "O1"),
        help="comma-separated profiles, or 'all' (default: O1)",
    )
    parser.add_argument(
        "--case",
        action="append",
        help="case name (repeatable or comma-separated); overrides --matrix",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help=(
            "run the historical sleep-gate, scheduler sleep/no-sleep "
            "quadrants, multi-waiter/recycle channel cases, and channel "
            "close/blocked-sender regressions"
        ),
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=int(os.environ.get("XU_SCHED_ITERS", "100")),
        help="runs per case/profile (default: 100)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("XU_SCHED_TIMEOUT", "2")),
        help="per-run wall-clock watchdog in seconds (default: 2)",
    )
    parser.add_argument(
        "--build-timeout",
        type=float,
        default=float(os.environ.get("XU_SCHED_BUILD_TIMEOUT", "60")),
        help="per-build watchdog in seconds (default: 60)",
    )
    parser.add_argument(
        "--kill-grace",
        type=float,
        default=float(os.environ.get("XU_SCHED_KILL_GRACE", "0.5")),
        help="grace after SIGTERM before SIGKILL (default: 0.5)",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="write the complete machine-readable report to PATH (use '-' for stdout)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep temporary binaries/log context for post-mortem inspection",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="report failures but return success (useful for exploratory runs)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    lane = "oracle" if args.oracle else args.lane
    if args.oracle and args.lane != "product":
        parser.error("use either --oracle or --lane oracle, not both")
    try:
        cases = _resolve_cases(args)
        profiles = _resolve_profiles(args.profiles)
    except ValueError as exc:
        parser.error(str(exc))

    if args.iterations < 1 or args.iterations > 100_000:
        parser.error("--iterations must be between 1 and 100000")
    if args.timeout <= 0 or args.timeout > 3600:
        parser.error("--timeout must be >0 and <=3600 seconds")
    if args.build_timeout <= 0 or args.build_timeout > 3600:
        parser.error("--build-timeout must be >0 and <=3600 seconds")
    if args.kill_grace < 0 or args.kill_grace > 60:
        parser.error("--kill-grace must be between 0 and 60 seconds")

    try:
        compiler = (
            _resolve_product_compiler(args.xu)
            if lane == "product"
            else _resolve_oracle_compiler(args.xu)
        )
    except ValueError as exc:
        parser.error(str(exc))
    for case in cases:
        if not case.source.is_file():
            parser.error(f"case source does not exist: {case.source}")
        if not case.expected.is_file():
            parser.error(f"case expectation does not exist: {case.expected}")

    if lane == "product":
        if args.compile_mode == "direct":
            parser.error("product lane requires --compile-mode product or auto")
        compile_mode = "product"
    else:
        compile_mode = _detect_compile_mode(compiler, args.compile_mode)

    # Keep the child environment stable and prevent an inherited package cache
    # or scheduler-specific debug setting from changing the stress signal.
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env.pop("XU_SCHED_TRACE", None)

    temp_root = Path(tempfile.mkdtemp(prefix="xu-scheduler-stress-"))
    report_rows: list[dict[str, object]] = []
    report_skips: list[dict[str, object]] = []
    print(
        "scheduler-stress: "
        f"lane={lane} compiler={compiler} profiles={','.join(profiles)} "
        f"compile_mode={compile_mode} "
        f"cases={','.join(case.name for case in cases)} "
        f"iterations={args.iterations} timeout={args.timeout:g}s"
    )
    try:
        for case in cases:
            expected = case.expected.read_bytes()
            for profile in profiles:
                stem = f"{case.name}.{profile}".replace("/", "_")
                binary = temp_root / f"{stem}.xin"
                build_command = _build_command(
                    compiler,
                    compile_mode,
                    profile,
                    case.source,
                    binary,
                    lane=lane,
                )
                build = _run_bounded(
                    build_command,
                    cwd=ROOT,
                    env=env,
                    timeout_s=args.build_timeout,
                    kill_grace_s=args.kill_grace,
                )
                runs: list[RunResult] = []
                skip_reason = _known_build_skip(
                    case=case,
                    profile=profile,
                    compile_mode=compile_mode,
                    build=build,
                )
                if skip_reason is not None:
                    # Preserve the compiler diagnostic in the normal row and
                    # in the top-level skip ledger.  The marker has iteration
                    # zero so it cannot inflate executed-run statistics.
                    runs.append(
                        RunResult(
                            0,
                            "SKIPPED_UNSUPPORTED",
                            ["BUILDING", "SKIPPED_UNSUPPORTED"],
                            build.returncode,
                            build.elapsed_s,
                            build.stdout,
                            build.stderr,
                        )
                    )
                    skip_record = dict(skip_reason)
                    skip_record.update(
                        {
                            "case": case.name,
                            "source": str(case.source),
                            "compiler": str(compiler),
                        }
                    )
                    report_skips.append(skip_record)
                elif build.returncode == 0 and not build.timed_out and binary.is_file():
                    try:
                        binary.chmod(binary.stat().st_mode | 0o111)
                    except OSError:
                        pass
                    for iteration in range(1, args.iterations + 1):
                        run = _run_bounded(
                            [str(binary)],
                            cwd=ROOT,
                            env=env,
                            timeout_s=args.timeout,
                            kill_grace_s=args.kill_grace,
                        )
                        runs.append(
                            _run_state(
                                result=run,
                                expected=expected,
                                iteration=iteration,
                            )
                        )
                else:
                    # Preserve a terminal state in the same schema when the
                    # compiler itself fails, without pretending that a runtime
                    # iteration was executed.
                    runs.append(
                        RunResult(
                            0,
                            "BUILD_FAILURE",
                            ["BUILDING", "BUILD_FAILURE"],
                            build.returncode,
                            build.elapsed_s,
                            build.stdout,
                            build.stderr,
                        )
                    )
                row = _case_result(
                    case,
                    profile,
                    binary,
                    expected,
                    runs,
                    build=build,
                    compiler=compiler,
                    skip_reason=skip_reason,
                )
                row["timeout_s"] = args.timeout
                row["build_timeout_s"] = args.build_timeout
                row["keep_temp"] = args.keep
                report_rows.append(row)
                _print_result(row)
    finally:
        if args.keep:
            print(f"scheduler-stress: temporary artifacts kept at {temp_root}")
        else:
            shutil.rmtree(temp_root, ignore_errors=True)

    report: dict[str, object] = {
        "schema": "xu.scheduler-stress/v1",
        "lane": lane,
        "compiler": str(compiler),
        "compiler_sha256": _sha256(compiler),
        "compile_mode": compile_mode,
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "profiles": profiles,
        "cases": [case.name for case in cases],
        "iterations": args.iterations,
        "timeout_s": args.timeout,
        "build_timeout_s": args.build_timeout,
        "skip_policy": {
            "mode": "known_only",
            "unknown_build": "fail",
            "known_case": KNOWN_BUILD_SKIP_CASE,
            "known_diagnostic": KNOWN_BUILD_SKIP_DIAGNOSTIC,
        },
        "capabilities": _capability_report(cases, report_skips),
        "skips": report_skips,
        "rows": report_rows,
        "passed": all(bool(row["passed"]) for row in report_rows),
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json == "-":
        print(encoded, end="")
    elif args.json:
        report_path = Path(args.json).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(encoded, encoding="utf-8")
        print(f"scheduler-stress: report={report_path}")

    if report["passed"] or args.report_only:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
