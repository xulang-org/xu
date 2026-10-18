"""Resolve optional Xu companion repositories without changing core builds."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = {"examples": "examples", "bench": "bench", "site": "xulang-org", "packages": "packages", "vscode": "vscode"}
LEGACY_NAMES = {"examples": "xu-examples", "bench": "xu-bench", "site": "xu-site", "packages": "xu-packages", "vscode": "xu-vscode"}

def project_root(project: str, *, core_root: Path | None = None) -> Path:
    root = ROOT if core_root is None else core_root
    name = PROJECTS[project]
    value = os.environ.get(f"XU_{project.upper()}_ROOT")
    if value:
        return Path(value).expanduser().resolve()
    current = root.parent / name
    legacy = root.parent / LEGACY_NAMES[project]
    if current.is_dir():
        return current
    if project == "site" and (root.parent / "xulanguage").is_dir():
        return root.parent / "xulanguage"
    if project == "vscode":
        if (root.parent / "vscode-xu").is_dir():
            return root.parent / "vscode-xu"
        if not legacy.is_dir() and (root / "editors/vscode").is_dir():
            return root / "editors/vscode"
    return legacy if legacy.is_dir() else current


def vscode_package_files(checkout: Path) -> list[Path]:
    """Select the current VSIX and public metadata, excluding checkout state."""
    import json

    if not checkout.is_dir():
        if os.environ.get("XU_VSCODE_ROOT"):
            raise FileNotFoundError(f"XU_VSCODE_ROOT does not exist: {checkout}")
        return []
    metadata = json.loads((checkout / "package.json").read_text())
    filename = f"{metadata['name']}-{metadata['version']}.vsix"
    if Path(filename).name != filename or "\\" in filename:
        raise ValueError("VS Code package name/version must form a plain filename")
    return [checkout / name for name in (filename, "package.json", "language-configuration.json", "README.md")
            if (checkout / name).is_file()]


def package_directories(checkout: Path) -> list[Path]:
    """Collect package sources for a root module or legacy multi-module layout."""
    if not checkout.is_dir():
        return []
    root_module = (checkout / "xu.xun").is_file()
    return sorted(path for path in checkout.iterdir() if path.is_dir() and
                  ((path / "xu.xun").is_file() or (root_module and any(path.glob("*.xu")))))
