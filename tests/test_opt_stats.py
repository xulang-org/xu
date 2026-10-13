"""Stage 0 OptStats: `xu build --timings` prints MIR and RA observation lines."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XU = Path(os.environ.get("XU", str(ROOT / "bin" / "xu")))
SRC = ROOT / "tests" / "fixtures" / "matmul_tiny" / "main.xu"


def test_timings_prints_opt_stats() -> None:
    if not XU.is_file():
        raise AssertionError("missing compiler " + str(XU))
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "matmul.xin"
        r = subprocess.run(
            [str(XU), "build", str(SRC), "-o", str(out), "--timings"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        err = r.stderr + r.stdout
        if r.returncode != 0:
            raise AssertionError(err)
        if "opt-stats:" not in err:
            import pytest
            pytest.skip("compiler predates OptStats; run make xu")
        line = [ln for ln in err.splitlines() if ln.startswith("opt-stats:")][0]
        for key in (
            "nfn=",
            "nins=",
            "nins_out=",
            "clone=",
            "commit=",
            "commit_skip=",
            "summary_hit=",
            "summary_scan=",
            "facts_fill=",
            "inline_ok=",
            "inline_skip=",
        ):
            assert key in line, line
        assert "timings:" in err
        if "ra-stats:" not in err:
            import pytest
            pytest.skip("compiler predates RA OptStats; run make xu")
        ra = [ln for ln in err.splitlines() if ln.startswith("ra-stats:")][0]
        for key in (
            "fn=",
            "try=",
            "vreg=",
            "rc=",
            "frame=",
            "keep_rc=",
            "empty=",
            "spill=",
        ):
            assert key in ra, ra
