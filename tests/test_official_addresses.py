"""Product commands and package identities use the user's official addresses."""
from pathlib import Path
import json
import os
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from companion_repos import project_root

def test_actual_cli_reports_current_official_website():
    compiler = Path(os.environ.get("XU", ROOT / "bin/xu"))
    result = subprocess.run([str(compiler), "--version"], capture_output=True, text=True, check=True)
    assert "Docs: https://xulang.org" in result.stdout
    assert "xu-lang.dev" not in result.stdout

def test_install_commands_use_the_registered_github_organization():
    for name in ("install.sh", "install.ps1"):
        source = (ROOT / "scripts" / name).read_text()
        assert "https://github.com/xulang-org/xu/releases/download" in source
        assert "github.com/nouo/xu" not in source
    source = (ROOT / "scripts/pack_release_bundle.py").read_text()
    assert "curl -fsSL https://xulang.org/install.sh | bash" in source
    assert "irm https://xulang.org/install.ps1 | iex" in source

def test_editor_metadata_points_to_the_official_product():
    package = project_root("vscode") / "package.json"
    if not package.is_file():
        pytest.skip("optional VS Code extension checkout absent")
    metadata = json.loads(package.read_text())
    assert metadata["repository"]["url"] == "https://github.com/xulang-org/vscode"
    assert metadata["homepage"] == "https://xulang.org"
