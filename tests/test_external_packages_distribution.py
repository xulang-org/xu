"""Install and bundle the core with optional external modules, without network."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pack_release_bundle as bundler


@pytest.mark.parametrize("layout", ["absent", "sibling", "bundled", "override", "root"])
def test_offline_core_installer_with_optional_packages(tmp_path, layout):
    core = tmp_path / "xu"
    (core / "scripts").mkdir(parents=True)
    (core / "bin").mkdir()
    (core / "src").mkdir()
    (core / "src/mod.xu").write_text("stdlib")
    (core / "VERSION").write_text("0.8.2\n")
    shutil.copy2(ROOT / "scripts/install.sh", core / "scripts/install.sh")
    (core / "bin/xu").write_text('#!/bin/sh\necho "Xu Compiler Toolchain v0.8.2 (self-hosted)"\n')
    (core / "bin/xu").chmod(0o755)
    selected = {"sibling": tmp_path / "packages", "bundled": core / "packages", "override": tmp_path / "custom packages", "root": tmp_path / "packages"}.get(layout)
    if selected:
        (selected / "driver").mkdir(parents=True)
        (selected / "driver/xu.xun").write_text("module: driver\nversion: !ver 1.0.0\n")
        (selected / "driver/mod.xu").write_text("external")
        if layout == "root":
            (selected / "xu.xun").write_text('module: "github.com/xulang-org/packages"\nversion: !ver 0.1.0\n')
            (selected / "driver/xu.xun").unlink()
        (selected / ".git").mkdir()
        (selected / ".git/private-config").write_text("local")
        (selected / "tests").mkdir()
    env = dict(os.environ)
    env.pop("XU_PACKAGES_ROOT", None)
    if layout == "override":
        env["XU_PACKAGES_ROOT"] = str(selected)
    prefix = tmp_path / "installed"
    result = subprocess.run(["bash", str(core / "scripts/install.sh"), "--prefix", str(prefix), "--no-modify-path", "-y"],
        env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Downloading" not in result.stdout
    assert (prefix / "src/mod.xu").read_text() == "stdlib"
    assert (prefix / "bin/xu").exists()
    assert (prefix / "packages/driver/mod.xu").exists() == (layout != "absent")
    assert not (prefix / "packages/.git").exists()
    assert not (prefix / "packages/tests").exists()
    assert (prefix / "packages/xu.xun").exists() == (layout == "root")


@pytest.mark.parametrize("available", [False, True])
def test_bundle_selects_external_modules_and_full_standard_library(tmp_path, monkeypatch, available):
    core = tmp_path / "xu"
    (core / "src/os").mkdir(parents=True)
    (core / "src/os/mod.xu").write_text("os stdlib")
    (core / "src/cmd").mkdir()
    compiler = tmp_path / "compiler"
    compiler.write_text("compiler")
    packages = tmp_path / "packages"
    if available:
        (packages / "driver/native").mkdir(parents=True)
        (packages / "driver/xu.xun").write_text("module: driver\n")
        (packages / "driver/native/lib.xulib").write_text("native release resource")
        (packages / "docs").mkdir()
        (packages / "docs/local.md").write_text("local")
        (packages / ".git").mkdir()
        (packages / "tests").mkdir()
    monkeypatch.setattr(bundler, "REPO_ROOT", core)
    monkeypatch.setattr(bundler, "get_host_target", lambda: "macos-arm64")
    monkeypatch.setattr(bundler, "SIBLING_TOOLS", [])
    monkeypatch.setattr(bundler, "project_root", lambda project: packages if project == "packages" else tmp_path / "missing examples")
    monkeypatch.delenv("XU_PACKAGES_ROOT", raising=False)
    stage = tmp_path / "stage"
    bundler.assemble_bundle_dir("macos-arm64", stage, compiler, tmp_path / "cache", "0.8.2")
    assert (stage / "src/os/mod.xu").read_text() == "os stdlib"
    assert (stage / "packages/driver/native/lib.xulib").exists() == available
    assert not (stage / "packages/.git").exists()
    assert not (stage / "packages/docs").exists()
    assert not (stage / "packages/tests").exists()


def test_environment_activation_keeps_external_modules_explicit(tmp_path):
    core = tmp_path / "xu"
    (core / "scripts").mkdir(parents=True)
    (core / "src").mkdir()
    shutil.copy2(ROOT / "scripts/env.sh", core / "scripts/env.sh")
    result = subprocess.run(["bash", "-c", 'source "$1" >/dev/null; printf "%s\\n" "$XU_ROOT" "$XUPATH"', "env-test", str(core / "scripts/env.sh")],
        capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [str(core), str(core / "src")]


def test_bundle_copies_single_root_manifest_and_internal_package(monkeypatch, tmp_path):
    from companion_repos import package_directories
    packages = tmp_path / "packages"
    (packages / "mysql").mkdir(parents=True)
    (packages / "mysql/mod.xu").write_text('@"github.com/xulang-org/packages/mysql"')
    (packages / "xu.xun").write_text('module: "github.com/xulang-org/packages"\nversion: !ver 0.1.0\n')
    (packages / "tests").mkdir()
    (packages / ".git").mkdir()
    assert package_directories(packages) == [packages / "mysql"]
