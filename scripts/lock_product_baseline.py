#!/usr/bin/env python3
"""Freeze the current product binary + provenance into docs/audit/baseline.lock.json.

All subsequent benchmarks must bind to this snapshot (binary SHA, confirmed generation,
source seed/closure SHA, commit, dirty flag, timestamp).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .verify_product_provenance import verify
else:
    from verify_product_provenance import verify

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    prov_path = ROOT / "bin" / "xu.provenance"
    bin_path = ROOT / "bin" / "xu"
    if not bin_path.is_file() or not prov_path.is_file():
        print("baseline.lock: missing bin/xu or provenance", flush=True)
        return 1
    prov: dict[str, str] = {}
    for line in prov_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            prov[k.strip()] = v.strip()
    try:
        prov = verify(bin_path, prov.get("source_closure_sha256", ""))
    except (ValueError, OSError) as error:
        print(f"baseline.lock: {error}", flush=True)
        return 1
    bin_sha = sha256_file(bin_path)
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    )
    lock = {
        "schema": 2,
        "kind": "product-baseline-lock",
        "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if (ROOT / "VERSION").is_file()
        else "",
        "git_commit": prov.get("repo_head", ""),
        "git_dirty": "1" if dirty.stdout.strip() else "0",
        "bin_xu_sha256": bin_sha,
        "gen3_sha256": prov.get("gen3_sha256", ""),
        "gen4_sha256": prov.get("gen4_sha256", ""),
        "confirmed_generation": prov["confirmed_generation"],
        "confirmed_sha256": prov["confirmed_sha256"],
        "fixed_point_pair": prov["fixed_point_pair"],
        "source_seed_sha256": prov.get("source_seed_sha256", ""),
        "source_closure_sha256": prov.get("source_closure_sha256", ""),
        "source_seed_files": prov.get("source_seed_files", ""),
        "source_closure_files": prov.get("source_closure_files", ""),
        "target_os": prov.get("target_os", ""),
        "target_arch": prov.get("target_arch", ""),
        "hosted_args": prov.get("hosted_args", ""),
        "cross_targets": prov.get("cross_targets", ""),
        "notes": [
            "Benchmarks and RA stats must cite bin_xu_sha256 from this lock.",
            "Re-run scripts/lock_product_baseline.py after any product rebuild.",
        ],
    }
    out = ROOT / "docs" / "audit" / "baseline.lock.json"
    out.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(lock, indent=2, ensure_ascii=False))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
