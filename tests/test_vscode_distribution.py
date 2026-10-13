"""Keep the independent VS Code checkout optional in core distributions."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pack_release_bundle as bundler
from companion_repos import project_root, vscode_package_files


def extension(checkout):
    checkout.mkdir(parents=True)
    (checkout / "package.json").write_text(json.dumps(
        dict(name="xu-language", version="0.2.7"), indent=2))
    (checkout / "language-configuration.json").write_text("{}")
    (checkout / "README.md").write_text("extension docs")
    (checkout / "xu-language-0.2.7.vsix").write_bytes(b"current VSIX")
    (checkout / "xu-language-0.2.6.vsix").write_bytes(b"stale VSIX")
    for directory in (".git", "node_modules", ".vscode", "docs"):
        (checkout / directory).mkdir()
        (checkout / directory / "private").write_text("checkout-only data")


def test_sibling_checkout_precedes_legacy_and_nested_sources(tmp_path, monkeypatch):
    core = tmp_path / "xu"
    extension(core / "editors/vscode")
    extension(tmp_path / "xu-vscode")
    extension(tmp_path / "vscode")
    monkeypatch.delenv("XU_VSCODE_ROOT", raising=False)
    assert project_root("vscode", core_root=core) == tmp_path / "vscode"
    selected = tmp_path / "custom vscode"
    monkeypatch.setenv("XU_VSCODE_ROOT", str(selected))
    assert project_root("vscode", core_root=core) == selected
    with pytest.raises(FileNotFoundError, match="XU_VSCODE_ROOT"):
        vscode_package_files(selected)


@pytest.mark.parametrize("layout", ["absent", "sibling", "legacy", "bundled", "override"])
def test_offline_installer_selects_current_vsix_without_checkout_state(tmp_path, layout):
    core = tmp_path / "xu"
    (core / "scripts").mkdir(parents=True)
    (core / "bin").mkdir()
    (core / "src").mkdir()
    (core / "src/mod.xu").write_text("stdlib")
    (core / "VERSION").write_text("0.8.2\n")
    compiler = core / "bin/xu"
    compiler.write_text('#!/bin/sh\necho "Xu Compiler Toolchain v0.8.2 (self-hosted)"\n')
    compiler.chmod(0o755)
    installer = core / "scripts/install.sh"
    shutil.copy2(ROOT / "scripts/install.sh", installer)
    selected = {
        "sibling": tmp_path / "vscode",
        "legacy": tmp_path / "xu-vscode",
        "bundled": core / "editors/vscode",
        "override": tmp_path / "custom vscode",
    }.get(layout)
    if selected:
        extension(selected)
    # Capture auto-installation without touching the user's actual VS Code.
    commands = tmp_path / "commands"
    commands.mkdir()
    calls = tmp_path / "code-calls"
    code = commands / "code"
    code.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CODE_CALLS"\n')
    code.chmod(0o755)
    env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"],
               CODE_CALLS=str(calls), XU_PACKAGES_ROOT=str(tmp_path / "packages"))
    (tmp_path / "packages").mkdir()
    env.pop("XU_VSCODE_ROOT", None)
    if layout == "override":
        # The explicit checkout must win over an embedded source.
        extension(core / "editors/vscode")
        (core / "editors/vscode/xu-language-0.2.7.vsix").write_bytes(b"wrong source")
        env["XU_VSCODE_ROOT"] = str(selected)
    prefix = tmp_path / "installed"
    # An absent companion must not re-install leftover extension artifacts.
    stale = prefix / "editors/vscode/xu-language-0.2.6.vsix"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old installed VSIX")
    result = subprocess.run(
        ["bash", str(installer), "--prefix", str(prefix), "--no-modify-path", "-y"],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (prefix / "src/mod.xu").read_text() == "stdlib"
    installed = prefix / "editors/vscode"
    for directory in (".git", "node_modules", ".vscode", "docs"):
        assert not (installed / directory).exists()
    if selected:
        assert (installed / "xu-language-0.2.7.vsix").read_bytes() == b"current VSIX"
        assert calls.read_text().splitlines() == ["--install-extension", str(installed / "xu-language-0.2.7.vsix"), "--force"]
    else:
        assert not (installed / "xu-language-0.2.7.vsix").exists()
        assert not calls.exists()


@pytest.mark.parametrize("available", [False, True])
def test_bundle_uses_independent_current_extension_without_repository_state(tmp_path, monkeypatch, available):
    core = tmp_path / "xu"
    (core / "src/os").mkdir(parents=True)
    (core / "src/os/mod.xu").write_text("stdlib")
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"compiler")
    vscode = tmp_path / "vscode"
    if available:
        extension(vscode)
    monkeypatch.delenv("XU_VSCODE_ROOT", raising=False)
    monkeypatch.setattr(bundler, "REPO_ROOT", core)
    monkeypatch.setattr(bundler, "get_host_target", lambda: "macos-arm64")
    monkeypatch.setattr(bundler, "SIBLING_TOOLS", [])
    monkeypatch.setattr(bundler, "project_root", lambda project: vscode if project == "vscode" else tmp_path / "absent")
    stage = tmp_path / "stage"
    bundler.assemble_bundle_dir("macos-arm64", stage, compiler, tmp_path / "cache", "0.8.2")
    dest = stage / "editors/vscode"
    if available:
        assert sorted(path.name for path in dest.iterdir()) == [
            "README.md", "language-configuration.json", "package.json", "xu-language-0.2.7.vsix"]
        assert (dest / "xu-language-0.2.7.vsix").read_bytes() == b"current VSIX"
    else:
        assert not dest.exists()


def test_release_identity_reads_independent_extension_and_allows_absence(tmp_path, monkeypatch):
    from scripts import check_release_identity
    core = tmp_path / "xu"
    core.mkdir()
    monkeypatch.setattr(check_release_identity, "ROOT", core)
    monkeypatch.delenv("XU_VSCODE_ROOT", raising=False)
    assert check_release_identity.vscode_extension_version() is None
    extension(tmp_path / "vscode")
    assert check_release_identity.vscode_extension_version() == "0.2.7"
