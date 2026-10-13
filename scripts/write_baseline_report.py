#!/usr/bin/env python3
"""Write a commit-bound baseline report (OPEN_ADVANCED stage 1).

Records the gates that are currently green so later work cannot quietly
redefine "pass".  Read-only with respect to the compiler; writes one report
under docs/audit/.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .verify_product_provenance import verify
else:
    from verify_product_provenance import verify

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 125, f"error: {exc}"
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def last_line(text: str, prefix: str) -> str:
    hits = [ln for ln in text.splitlines() if ln.startswith(prefix)]
    return hits[-1] if hits else ""


def main() -> int:
    commit, commit_out = run(["git", "rev-parse", "HEAD"])
    dirty, dirty_out = run(["git", "status", "--porcelain"])
    commit_sha = commit_out if commit == 0 else "unknown"
    is_dirty = "1" if (dirty == 0 and dirty_out) else "0"

    gates: dict[str, dict[str, object]] = {}

    rc, out = run([sys.executable, "scripts/check_bootstrap_xu_boundary.py", "--strict-freeze"])
    gates["boundary"] = {
        "rc": rc,
        "ok": rc == 0,
        "summary": last_line(out, "bootstrap/Xu boundary"),
        "seed_files": next(
            (ln.split(":", 1)[1].strip() for ln in out.splitlines() if "Gen1 seed files" in ln),
            "",
        ),
        "closure_files": next(
            (ln.split(":", 1)[1].strip() for ln in out.splitlines() if "complete source closure" in ln),
            "",
        ),
    }

    rc, out = run([sys.executable, "-m", "pytest", "-q"], timeout=300)
    gates["pytest"] = {
        "rc": rc,
        "ok": rc == 0,
        "summary": out.splitlines()[-1] if out else "",
    }

    rc, out = run([sys.executable, "scripts/check_release_identity.py"])
    gates["release_identity"] = {
        "rc": rc,
        "ok": rc == 0,
        "summary": last_line(out, "release identity:"),
    }

    prov = ROOT / "bin" / "xu.provenance"
    xu = ROOT / "bin" / "xu"
    provenance: dict[str, str] = {}
    if prov.is_file():
        for line in prov.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                provenance[k.strip()] = v.strip()
    provenance_error = ""
    try:
        provenance = verify(xu, provenance.get("source_closure_sha256", ""))
    except (ValueError, OSError) as error:
        provenance_error = str(error)
    gates["product_binary"] = {
        "ok": not provenance_error,
        "summary": provenance_error,
        "bin_xu_sha256": sha256_file(xu) if xu.is_file() else "",
        "provenance_gen3_gen4": provenance.get("gen3_gen4_cmp", ""),
        "provenance_gen4_sha256": provenance.get("gen4_sha256", ""),
        "confirmed_generation": provenance.get("confirmed_generation", ""),
        "confirmed_sha256": provenance.get("confirmed_sha256", ""),
        "fixed_point_pair": provenance.get("fixed_point_pair", ""),
        "cross_targets": provenance.get("cross_targets", ""),
    }

    # Lightweight fixture smoke (not the full product-gate; that is separate).
    rc, out = run(
        [
            "bash",
            "scripts/run_fixtures.sh",
            f"--xu={ROOT / 'bin' / 'xu'}",
            "--sub=build",
            "--label=baseline",
            "--only=^(alloc_stress|matmul_tiny|copy_index_loop|nbody_pair_rmw|chan_xu_basic)$",
        ],
        timeout=300,
    )
    gates["fixture_smoke"] = {
        "rc": rc,
        "ok": rc == 0,
        "summary": last_line(out, "fixtures["),
    }

    report = {
        "schema": 1,
        "kind": "baseline",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": commit_sha,
        "git_dirty": is_dirty,
        "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if (ROOT / "VERSION").is_file()
        else "",
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "release": platform.release(),
        },
        "gates": gates,
        "notes": [
            "Historical PROGRESS.md numbers older than this file are not current status.",
            "product-gate-quick 209/0 is recorded separately in PROGRESS.md when run.",
            "promote SSA pass remains disabled (CHECK double-free).",
            "header canary helpers exist but are not wired.",
            "Windows G-stack remains heap-backed.",
            "MIR borrow is shadow-only in lower_fn; AST checker remains authoritative.",
            "cross_targets=SKIPPED in provenance (no multi-platform product chain here).",
        ],
    }

    out_dir = ROOT / "docs" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "baseline.latest.json"
    txt_path = out_dir / "baseline.latest.txt"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        f"# Xu baseline ({report['generated_at']})",
        f"commit={commit_sha} dirty={is_dirty} version={report['version']}",
        "",
    ]
    for name, g in gates.items():
        status = "PASS" if g.get("ok") else "FAIL"
        summary = str(g.get("summary", ""))
        extra = ""
        if name == "product_binary":
            extra = (
                f" fixed_point={g.get('fixed_point_pair')} confirmed=Gen{g.get('confirmed_generation')}"
                f" cross={g.get('cross_targets')}"
                f" sha={str(g.get('bin_xu_sha256'))[:12]}"
            )
        if name == "boundary":
            extra = f" seed={g.get('seed_files')} closure={g.get('closure_files')}"
        lines.append(f"{status} {name}{extra} :: {summary}")
    lines.append("")
    lines.append("Notes:")
    for n in report["notes"]:
        lines.append(f"- {n}")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(txt_path.read_text(encoding="utf-8"))
    all_ok = all(bool(g.get("ok")) for g in gates.values())
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
