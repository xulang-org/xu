#!/usr/bin/env python3
"""Release identity consistency check (OPEN_ADVANCED_PROGRAMMER_IMPLEMENTATION_PLAN.md P0.3).

Binds VERSION, `xu --version`, packaging manifests, and provenance so a
candidate cannot ship with mismatched identity strings.  Read-only: never
writes binaries or packages.

Exit codes:
  0  identity consistent (or --warn-only with only warnings)
  1  inconsistency / missing required identity source
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

if __package__:
    from .module_versions import read_version as read_module_version, read_xu_version, Version
    from .companion_repos import project_root
else:
    from module_versions import read_version as read_module_version, read_xu_version, Version
    from companion_repos import project_root

try:
    if __package__:
        from .verify_product_provenance import fixed_point_identity
    else:
        try:
            from verify_product_provenance import fixed_point_identity
        except ImportError:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from verify_product_provenance import fixed_point_identity
except ImportError:
    def fixed_point_identity(xu, **kwargs):
        return True, None, "missing verify_product_provenance"

ROOT = Path(__file__).resolve().parents[1]


def read_version_file() -> str | None:
    path = ROOT / "VERSION"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def parse_semver(value: str):
    try:
        return Version.parse(value.strip().removeprefix("v"))
    except ValueError:
        return None


def xu_cli_version(xu: Path) -> str | None:
    if not xu.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(xu), "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    m = re.search(r"v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?=\s|$)", blob)
    if m:
        return m.group(1)
    m = re.search(r"(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?=\s|$)", blob)
    return m.group(1) if m else None


def vscode_extension_version() -> str | None:
    path = project_root("vscode", core_root=ROOT) / "package.json"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    m = re.search(r'"version"\s*:\s*"([^"]+)"', text)
    return m.group(1) if m else None


def provenance_version_fields(prov: Path) -> dict[str, str]:
    if not prov.is_file():
        return {}
    out: dict[str, str] = {}
    for line in prov.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--xu",
        default=str(ROOT / "bin" / "xu"),
        help="product compiler to query for --version (default: bin/xu)",
    )
    ap.add_argument(
        "--require-cli",
        action="store_true",
        help="fail when bin/xu is missing or does not report a version",
    )
    ap.add_argument(
        "--warn-only",
        action="store_true",
        help="print inconsistencies but always exit 0",
    )
    args = ap.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    version = read_version_file()
    if not version:
        errors.append("VERSION file missing or empty")
    else:
        notes.append(f"VERSION={version}")
        if parse_semver(version) is None:
            errors.append(f"VERSION is not semver: {version!r}")

    xu_path = Path(args.xu)
    compiler_manifest = ROOT / "src/cmd/compile/xu.xun"
    if not compiler_manifest.is_file():
        errors.append("compiler manifest src/cmd/compile/xu.xun is missing")
    else:
        try:
            text = compiler_manifest.read_text()
            module_version = read_module_version(text)
            language_version = read_xu_version(text)
            if module_version != parse_semver(version) or language_version != parse_semver(version):
                errors.append("compiler module version: and xu: must both match VERSION")
            else:
                notes.append(f"compiler.version={version}")
        except ValueError as error:
            errors.append(f"compiler manifest: {error}")
    cli = xu_cli_version(xu_path)
    if cli is None:
        msg = f"cannot read --version from {xu_path}"
        if args.require_cli or xu_path.exists():
            errors.append(msg)
        else:
            warnings.append(msg + " (skipped)")
    else:
        notes.append(f"xu --version={cli}")
        if version and parse_semver(version) and parse_semver(cli) != parse_semver(version):
            errors.append(
                f"xu --version ({cli}) does not match VERSION ({version})"
            )

    ext = vscode_extension_version()
    if ext is None:
        notes.append("VS Code companion absent (optional; set XU_VSCODE_ROOT to select it)")
    else:
        notes.append(f"vscode.package.version={ext}")
        # The extension may ship its own marketing version; only require semver.
        if parse_semver(ext) is None:
            warnings.append(f"vscode extension version is not semver: {ext!r}")

    prov = Path(str(xu_path) + ".provenance")
    fields = provenance_version_fields(prov)
    if fields:
        status = fields.get("status", "unknown")
        notes.append(f"provenance.status={status}")
        if status != "PASS":
            warnings.append(f"bin/xu.provenance status is {status}, not PASS")
        try:
            identity = fixed_point_identity(fields, hashlib.sha256(xu_path.read_bytes()).hexdigest())
        except (ValueError, OSError) as error:
            errors.append(str(error))
        else:
            notes.append(f"provenance {identity['fixed_point_pair']}==PASS; confirmed Gen{identity['confirmed_generation']}")
    else:
        warnings.append(f"no provenance sidecar at {prov}")

    print("release identity:")
    for n in notes:
        print(f"  note: {n}")
    for w in warnings:
        print(f"  warn: {w}")
    for e in errors:
        print(f"  ERROR: {e}")

    if errors and not args.warn_only:
        print(f"release identity: FAIL ({len(errors)} error(s))")
        return 1
    print("release identity: PASS" if not errors else "release identity: WARN (--warn-only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
