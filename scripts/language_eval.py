#!/usr/bin/env python3
"""Global Xu language evaluation.

One entry point for every release-grade check we already have: cross-language
performance, Benchmarks Game, optimizer gates, stdlib/fixtures, safety (host,
cross-target, embedded, escape), portability, CLI, self-host, and product
optimized/unoptimized runtime and hosted compilation. Individual scripts stay independent so a speed
regression cannot hide a semantic or safety result. This driver runs them,
keeps native reports/logs, and writes one index.

Examples:
  make bench-language
  python3 scripts/language_eval.py
  python3 scripts/language_eval.py --quick
  python3 scripts/language_eval.py --suites=cross
  python3 scripts/language_eval.py --suites=performance,game,optimizer
  python3 scripts/language_eval.py --dry-run --list
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


from companion_repos import project_root

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_XU = ROOT / "bin" / "xu"


LANE = "product"


@dataclass(frozen=True)
class Suite:
    name: str
    face: str
    what: str


SUITES: tuple[Suite, ...] = (
    Suite(
        "performance",
        "横向能力套件",
        "Xu 与 Clang、rustc 的 O1/O2/O3 整程序 wall/CPU/RSS/体积/编译时间；另含 Go、Swift 参照。scripts/bench_crosslang.py",
    ),
    Suite(
        "game",
        "Benchmarks Game",
        "nbody / fannkuch / spectralnorm / mandelbrot / fasta / binarytrees；Xu 对 C/C++/Rust/Go，同算法小 N 金标。scripts/bench_game.py",
    ),
    Suite(
        "optimizer",
        "优化器正确性与回归",
        "Xu O0–O3、--no-regcache 与 MIR/RA 拆分；锁 stdout、超时、墙钟/CPU 和 O2/O3 对 O1 门禁。scripts/bench_opt_levels.py --check",
    ),
    Suite(
        "nbody_residency",
        "nbody 寄存器驻留与回归",
        "产品编译器的 FieldRMW/GPR/FP 驻留、能量金标及 O2/O3 对 O1 的配对 CPU 门禁。scripts/test_nbody_residency.sh",
    ),
    Suite(
        "opt_full",
        "优化器全量快照",
        "O0–O3 运行+资源+编译 + Xu --timings 摘要。scripts/bench_opt_full.sh",
    ),
    Suite(
        "runtime",
        "运行时 O0 与默认优化对拍",
        "xu-bench/tests/bench/*.xu 由产品 bin/xu 使用 O0 与默认优化各编各跑，stdout 必须一致。scripts/bench_runtime.sh",
    ),
    Suite(
        "compile",
        "自编译时间",
        "产品种子编 Gen1、Gen1 自编译；对照 bench_compile baseline。scripts/bench_compile.sh",
    ),
    Suite(
        "stdlib",
        "语义与标准库",
        "产品编译器跑 fixtures：正反例、I/O、并发、编码、压缩、密码、集合和网络。scripts/run_fixtures.sh",
    ),
    Suite(
        "programs",
        "程序行为对照",
        "tests/gen1/programs 在产品 xu 的 O0 与默认优化下 stdout/退出码一致。scripts/programs_cross_check.sh",
    ),
    Suite(
        "safety",
        "内存安全（本机）",
        "编译期拒绝、运行期 fail-loud、channel/xu 行为。scripts/safety_test.sh",
    ),
    Suite(
        "safety_cross",
        "内存安全（交叉目标）",
        "多目标安全夹具。scripts/safety_cross_target.sh",
    ),
    Suite(
        "safety_embedded",
        "内存安全（嵌入式）",
        "裸机/QEMU 安全探测。scripts/safety_embedded.sh",
    ),
    Suite(
        "safety_escape",
        "逃逸检查",
        "引用逃逸门禁。scripts/safety_escape_test.sh",
    ),
    Suite(
        "portability",
        "目标可移植性",
        "产品编译器在 macOS、Linux、Windows、LoongArch、RISC-V 的编译/执行矩阵。scripts/platform_test.sh",
    ),
    Suite(
        "cli_platform",
        "CLI 跨平台契约",
        "产品 CLI 旗标与环境变量烟测。scripts/cli_platform_test.sh",
    ),
    Suite(
        "gen1_platform",
        "平台目标矩阵",
        "产品编译器在各架构平台的矩阵验证。scripts/platform_test.sh",
    ),
    Suite(
        "selfhost",
        "自举与可复现",
        "纯自举 Seed→Gen1→Gen2→Gen3 固定点与可复现验证。scripts/build_hosted_chain.sh",
    ),
)
BY_NAME = {suite.name: suite for suite in SUITES}

# Named bundles so a later global run is one flag, not a remembered list.
ALIASES: dict[str, tuple[str, ...]] = {
    "all": tuple(s.name for s in SUITES),
    "cross": ("performance", "game"),
    "safety-all": ("safety", "safety_cross", "safety_embedded", "safety_escape"),
    "gates": (
        "optimizer",
        "nbody_residency",
        "stdlib",
        "programs",
        "safety",
        "safety_cross",
        "safety_escape",
        "portability",
        "cli_platform",
        "selfhost",
    ),
}


@dataclass
class Outcome:
    suite: Suite
    command: list[str]
    elapsed_s: float
    returncode: int
    log: Path
    detail: str


def parse_suites(raw: str | None) -> list[Suite]:
    if not raw:
        return list(SUITES)
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        raise SystemExit("--suites cannot be empty")
    names: list[str] = []
    seen: set[str] = set()
    for part in parts:
        group = ALIASES.get(part)
        expand = list(group) if group is not None else [part]
        for name in expand:
            if name not in BY_NAME:
                raise SystemExit(
                    f"unknown suite(s): {name}; "
                    f"known: {', '.join(BY_NAME)} "
                    f"(aliases: {', '.join(ALIASES)})"
                )
            if name not in seen:
                seen.add(name)
                names.append(name)
    return [BY_NAME[name] for name in names]


def command_for(
    suite: Suite,
    *,
    xu: Path,
    report_dir: Path,
    quick: bool,
    iters: int,
    benches: str | None,
    discard_first: bool,
) -> tuple[list[str], str]:
    if suite.name == "performance":
        report = report_dir / "crosslang.txt"
        cmd = [
            sys.executable,
            str(ROOT / "scripts/run_companion.py"),
            "bench",
            "scripts/bench_crosslang.py",
            "--xu",
            str(xu),
            "--out",
            str(report),
            "--iters",
            str(iters),
        ]
        if quick:
            cmd.append("--quick")
        if benches:
            cmd.extend(("--benches", benches))
        if discard_first:
            cmd.append("--discard-first")
        return cmd, f"cross-language report: {report}"

    if suite.name == "game":
        report = report_dir / "game.txt"
        md = report_dir / "game.md"
        cmd = [
            sys.executable,
            str(ROOT / "scripts/run_companion.py"),
            "bench",
            "scripts/bench_game.py",
            "--xu",
            str(xu),
            "--out",
            str(report),
            "--report",
            str(md),
            "--iters",
            str(max(3, iters) if not quick else 3),
        ]
        if quick:
            cmd.append("--quick")
        if benches:
            cmd.extend(("--benches", benches))
        if discard_first:
            cmd.append("--discard-first")
        return cmd, f"benchmarks game: {report}"

    if suite.name == "optimizer":
        report = report_dir / "optimizer.txt"
        cmd = [
            sys.executable,
            str(ROOT / "scripts/run_companion.py"),
            "bench",
            "scripts/bench_opt_levels.py",
            "--lane",
            "product",
            "--xu",
            str(xu),
            "--check",
            "--out",
            str(report),
            "--iters",
            str(iters),
        ]
        if quick:
            cmd.append("--quick")
        elif benches:
            cmd.extend(("--benches", benches))
        return cmd, f"optimizer report: {report}"

    if suite.name == "nbody_residency":
        report = report_dir / "nbody_residency.json"
        return [
            "./scripts/test_nbody_residency.sh",
            f"--xu={xu}",
            f"--out={report}",
        ], f"nbody residency report: {report}"

    if suite.name == "opt_full":
        return [sys.executable, str(ROOT / "scripts/run_companion.py"), "bench", "scripts/bench_opt_full.sh"], "optimizer full snapshot"

    if suite.name == "runtime":
        cmd = [sys.executable, str(ROOT / "scripts/run_companion.py"), "bench", "scripts/bench_runtime.sh"]
        if not quick:
            cmd.append("--check")
        return cmd, "product O0 vs default runtime"

    if suite.name == "compile":
        return [sys.executable, str(ROOT / "scripts/run_companion.py"), "bench", "scripts/bench_compile.sh"], "self-compile wall"

    if suite.name == "stdlib":
        cmd = [
            "./scripts/run_fixtures.sh",
            f"--xu={xu}",
            "--sub=build",
            "--label=product",
        ]
        if quick:
            cmd.append("--skip-net")
        return cmd, "product fixture corpus"

    if suite.name == "programs":
        return [
            "./scripts/programs_cross_check.sh",
            f"--xu={xu}",
        ], "programs product O0 vs default"

    if suite.name == "safety":
        cmd = ["./scripts/safety_test.sh", f"--xu={xu}"]
        return cmd, "safety gate"

    if suite.name == "safety_cross":
        return ["./scripts/safety_cross_target.sh"], "safety cross-target"

    if suite.name == "safety_embedded":
        return ["./scripts/safety_embedded.sh"], "safety embedded"

    if suite.name == "safety_escape":
        return [
            "./scripts/safety_escape_test.sh",
            f"--xu={xu}",
        ], "escape check"

    if suite.name == "portability":
        return ["./scripts/platform_test.sh", f"--xu={xu}", "--lane=product"], "product target matrix"

    if suite.name == "cli_platform":
        return ["./scripts/cli_platform_test.sh"], "CLI contract"

    if suite.name == "gen1_platform":
        return ["./scripts/platform_test.sh", f"--xu={xu}", "--lane=product"], "product target matrix"

    if suite.name == "selfhost":
        return ["./scripts/build_hosted_chain.sh", str(xu)], "hosted fixed point"

    raise AssertionError(f"unhandled suite {suite.name}")


def run_suite(suite: Suite, cmd: list[str], log: Path, dry_run: bool) -> Outcome:
    rendered = shlex.join(cmd)
    if dry_run:
        return Outcome(suite, cmd, 0.0, 0, log, "not run (--dry-run)")

    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    print(f"\n===== {suite.name}: {suite.face} =====", flush=True)
    print(f"$ {rendered}", flush=True)
    with log.open("w", encoding="utf-8") as fp:
        fp.write(f"$ {rendered}\n\n")
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            fp.write(line)
        code = proc.wait()
    elapsed = time.monotonic() - started
    detail = "PASS" if code == 0 else f"FAIL (exit {code})"
    print(f"===== {suite.name}: {detail}, {elapsed:.1f}s =====", flush=True)
    return Outcome(suite, cmd, elapsed, code, log, detail)


def write_index(
    out: Path,
    *,
    xu: Path,
    selected: list[Suite],
    outcomes: list[Outcome],
    quick: bool,
    dry_run: bool,
) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    by_suite = {item.suite.name: item for item in outcomes}
    lines = [
        "# Xu language evaluation",
        "",
        f"- Date: {time.strftime('%Y-%m-%d %H:%M %z')}",
        f"- Host: {os.uname().sysname} {os.uname().release} {os.uname().machine}",
        f"- Product compiler: `{xu}`",
        f"- Driver lane: `{LANE}` (self-host product evidence)",
        f"- Mode: {'quick' if quick else 'complete'}{' (dry run)' if dry_run else ''}",
        "",
        "| Dimension | Suite | Status | Time | Evidence |",
        "|---|---|---|---:|---|",
    ]
    for suite in selected:
        item = by_suite.get(suite.name)
        if item is None:
            status, elapsed, evidence = "NOT RUN", "—", "—"
        elif dry_run:
            status, elapsed, evidence = "DRY RUN", "—", f"`{shlex.join(item.command)}`"
        else:
            status = "PASS" if item.returncode == 0 else f"FAIL ({item.returncode})"
            elapsed = f"{item.elapsed_s:.1f}s"
            evidence = f"`{item.log.relative_to(out.parent)}`"
        lines.append(
            f"| {suite.face} | `{suite.name}` | {status} | {elapsed} | {evidence} |"
        )
    lines.extend(("", "## Scope", ""))
    for suite in selected:
        lines.append(f"- `{suite.name}` — {suite.what}")
    lines.extend(
        (
            "",
            "## Reading the result",
            "",
            "- A failure is scoped to its row: later rows still ran so the report distinguishes performance, correctness, safety, portability, and self-hosting failures.",
            "- `performance` is the language-capability cross suite (Xu/Clang/rustc O-levels; Go and Swift as reference lanes).",
            "- `game` is the Benchmarks Game subset (same algorithm, official small-N golden stdout).",
            "- `optimizer` is a release gate: an O2/O3 regression relative to O1 is a failing result, not a sampling warning.",
            "- The portability script labels an unavailable execution environment as `compile+file only`; that is a degraded observation, not proof of execution on that target.",
            "- Default with no `--suites` is the full global set (`all`). Use `--suites=cross` for only the two horizontal benches, `--suites=gates` for correctness gates without the long benches.",
            "",
        )
    )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--xu",
        default=str(PRODUCT_XU),
        help="product Xu compiler (default: bin/xu)",
    )
    ap.add_argument(
        "--out",
        default="docs/audit/language_eval.latest.md",
        help="Markdown index path (default: docs/audit/language_eval.latest.md)",
    )
    ap.add_argument(
        "--suites",
        help=(
            "comma-separated suites or aliases "
            f"(default all). suites: {', '.join(BY_NAME)}; "
            f"aliases: {', '.join(ALIASES)}"
        ),
    )
    ap.add_argument(
        "--quick",
        action="store_true",
        help="shrink long benches (crosslang/game/optimizer/fixtures); other selected suites stay complete",
    )
    ap.add_argument("--iters", type=int, default=7, help="timed runs per performance/optimizer/game cell")
    ap.add_argument(
        "--benches",
        help="shared comma-separated benchmark subset for performance, game, and optimizer",
    )
    ap.add_argument("--discard-first", action="store_true", help="drop first timed performance/game sample")
    ap.add_argument("--dry-run", action="store_true", help="write the plan without executing it")
    ap.add_argument("--fail-fast", action="store_true", help="stop after the first failing suite")
    ap.add_argument("--list", action="store_true", help="list suite dimensions and exit")
    args = ap.parse_args()
    if args.iters < 1:
        raise SystemExit("--iters must be >= 1")

    if args.list:
        print("aliases:")
        for alias, names in ALIASES.items():
            print(f"  {alias:<12} {','.join(names)}")
        print("suites:")
        for suite in SUITES:
            print(f"  {suite.name:<16} {suite.face}: {suite.what}")
        return 0

    raw_xu = Path(args.xu).expanduser()
    xu = raw_xu.resolve()
    if not args.dry_run:
        if not xu.is_file():
            raise SystemExit(f"missing product compiler {xu}; run `make xu` first")
        if not os.access(xu, os.X_OK):
            raise SystemExit(f"product compiler is not executable: {xu}")

    out = Path(args.out).expanduser()
    if not out.is_absolute():
        out = ROOT / out
    out = out.resolve()
    report_dir = out.parent / f"{out.stem}.artifacts"
    selected = parse_suites(args.suites)
    outcomes: list[Outcome] = []
    print(f"language_eval: lane={LANE} xu={xu}")
    print(f"language_eval: index={out}")
    print(f"language_eval: suites={', '.join(s.name for s in selected)}")
    for suite in selected:
        cmd, detail = command_for(
            suite,
            xu=xu,
            report_dir=report_dir,
            quick=args.quick,
            iters=args.iters,
            benches=args.benches,
            discard_first=args.discard_first,
        )
        log = report_dir / "logs" / f"{suite.name}.log"
        outcome = run_suite(suite, cmd, log, args.dry_run)
        outcome.detail = detail if outcome.returncode == 0 else outcome.detail
        outcomes.append(outcome)
        if outcome.returncode != 0 and args.fail_fast:
            break
    write_index(
        out,
        xu=xu,
        selected=selected,
        outcomes=outcomes,
        quick=args.quick,
        dry_run=args.dry_run,
    )
    failed = [item.suite.name for item in outcomes if item.returncode != 0]
    print(f"language_eval: index written to {out}")
    if failed:
        print(f"language_eval: FAIL ({', '.join(failed)})", file=sys.stderr)
        return 1
    print("language_eval: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
