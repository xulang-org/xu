"""Stage 0 OptStats baseline: bind compiler SHA, opt/RA, stdout hash, and stats.

Observation only. Skips when the compiler predates --timings opt-stats.
Set OPT_BASELINE_WRITE=1 to refresh docs/audit/opt_baseline.latest.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", str(ROOT / "bin" / "xu")))
BASELINE = ROOT / "docs" / "audit" / "opt_baseline.latest.json"

# Roadmap core list that already has a locked stdout in compiler_workloads fixtures.
CORE = (
    ("loop_sum", ROOT / "tests" / "data" / "compiler_workloads" / "loop_sum.xu", "25574942656\n"),
    ("scan_dep", ROOT / "tests" / "data" / "compiler_workloads" / "scan_dep.xu", "2378880\n"),
    ("sroa_vec3", ROOT / "tests" / "data" / "compiler_workloads" / "sroa_vec3.xu", "537600000\n"),
    ("sort_lcg", ROOT / "tests" / "data" / "compiler_workloads" / "sort_lcg.xu", "8588477465\n"),
    ("math_bits", ROOT / "tests" / "data" / "compiler_workloads" / "math_bits.xu", "-8160978732932967136\n"),
)

OPTS = (
    ("O0", ["-O0"]),
    ("O1", ["-O1"]),
    ("O2", ["-O2"]),
    ("O3", ["-O3"]),
    ("nrc", ["--no-regcache"]),
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _parse_line(blob: str, prefix: str) -> str | None:
    for ln in blob.splitlines():
        if ln.startswith(prefix):
            return ln
    return None


def _compile_run(src: Path, flags: list[str], tmp: Path) -> dict:
    out = tmp / (src.stem + "_" + "_".join(flags).replace("=", "") + ".xin")
    cmd = [str(XU), "build", str(src), "-o", str(out), "--timings", *flags]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    err = r.stderr + r.stdout
    if r.returncode != 0:
        raise AssertionError(src.name + " " + " ".join(flags) + "\n" + err)
    opt = _parse_line(err, "opt-stats:")
    ra = _parse_line(err, "ra-stats:")
    if opt is None:
        import pytest

        pytest.skip("compiler predates OptStats; run make xu")
    got = subprocess.run([str(out)], capture_output=True, text=True, check=False)
    if got.returncode != 0:
        raise AssertionError(src.name + " run failed\n" + got.stderr)
    stdout = got.stdout
    return {
        "opt": flags[0] if flags else "O1",
        "flags": flags,
        "stdout": stdout,
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "opt_stats": opt,
        "ra_stats": ra or "",
    }


def test_core_o1_stdout_and_stats() -> None:
    if not XU.is_file():
        raise AssertionError("missing compiler " + str(XU))
    rows = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, src, expected in CORE:
            row = _compile_run(src, ["-O1"], tmp)
            assert row["stdout"] == expected, name + ": " + repr(row["stdout"])
            assert "clone=" in row["opt_stats"], row["opt_stats"]
            assert row["ra_stats"].startswith("ra-stats:"), row["ra_stats"]
            rows.append({"bench": name, **row})
    if os.environ.get("OPT_BASELINE_WRITE") == "1":
        _write_baseline(rows)


def test_matmul_tiny_opt_matrix() -> None:
    if not XU.is_file():
        raise AssertionError("missing compiler " + str(XU))
    src = ROOT / "tests" / "fixtures" / "matmul_tiny" / "main.xu"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        hashes = []
        for label, flags in OPTS:
            row = _compile_run(src, flags, tmp)
            assert row["stdout"] == "25216\n", label + ": " + repr(row["stdout"])
            hashes.append(row["stdout_sha256"])
        assert len(set(hashes)) == 1


def _write_baseline(o1_rows: list[dict]) -> None:
    payload = {
        "compiler_path": str(XU),
        "compiler_sha256": _sha256_file(XU),
        "target": platform.system().lower() + "-" + platform.machine().lower(),
        "rows": [
            {
                "bench": r["bench"],
                "opt": "O1",
                "flags": r["flags"],
                "stdout_sha256": r["stdout_sha256"],
                "opt_stats": r["opt_stats"],
                "ra_stats": r["ra_stats"],
            }
            for r in o1_rows
        ],
    }
    BASELINE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
