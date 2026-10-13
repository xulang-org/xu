"""Core gates must remain runnable with optional companion repositories absent."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from companion_repos import project_root


def test_explicit_companion_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("XU_BENCH_ROOT", str(tmp_path))
    assert project_root("bench") == tmp_path


def test_missing_companion_reports_configuration_seam(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_companion.py"), "bench", "scripts/bench_crosslang.py"],
        env=dict(os.environ, XU_BENCH_ROOT=str(tmp_path)),
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "XU_BENCH_ROOT" in result.stderr


def test_companion_receives_core_root_and_its_own_cwd(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text("import os\nprint(os.getcwd())\nprint(os.environ['XU_ROOT'])\n")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_companion.py"), "bench", "probe.py"],
        env=dict(os.environ, XU_BENCH_ROOT=str(tmp_path)),
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.splitlines() == [str(tmp_path), str(ROOT)]


def test_core_build_has_no_companion_prerequisite(tmp_path):
    result = subprocess.run(
        ["make", "-n", "xu"], cwd=ROOT,
        env=dict(os.environ, XU_BENCH_ROOT=str(tmp_path), XU_SITE_ROOT=str(tmp_path),
                 XU_EXAMPLES_ROOT=str(tmp_path)),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_current_layout_precedes_legacy_names(monkeypatch, tmp_path):
    import companion_repos
    monkeypatch.setattr(companion_repos, "ROOT", tmp_path / "xu")
    for project, name in companion_repos.PROJECTS.items():
        monkeypatch.delenv(f"XU_{project.upper()}_ROOT", raising=False)
        legacy = tmp_path / companion_repos.LEGACY_NAMES[project]
        legacy.mkdir()
        assert project_root(project) == legacy
        current = tmp_path / name
        current.mkdir()
        assert project_root(project) == current


def test_packages_explicit_override_wins_even_when_missing(monkeypatch, tmp_path):
    import companion_repos
    monkeypatch.setattr(companion_repos, "ROOT", tmp_path / "xu")
    (tmp_path / "packages").mkdir()
    selected = tmp_path / "custom packages"
    monkeypatch.setenv("XU_PACKAGES_ROOT", str(selected))
    assert project_root("packages") == selected


def test_bootstrap_sibling_precedes_nested_archive(monkeypatch, tmp_path):
    import companion_repos
    core = tmp_path / "xu"
    (core / "bootstrap").mkdir(parents=True)
    monkeypatch.delenv("XU_BOOTSTRAP_ROOT", raising=False)
    assert project_root("bootstrap", core_root=core) == core / "bootstrap"
    sibling = tmp_path / "bootstrap"
    sibling.mkdir()
    assert project_root("bootstrap", core_root=core) == sibling


def test_bootstrap_override_preserves_symlink_provenance(monkeypatch, tmp_path):
    real = tmp_path / "bootstrap"
    real.mkdir()
    alias = tmp_path / "primer alias"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("XU_BOOTSTRAP_ROOT", str(alias))
    assert project_root("bootstrap") == alias


def test_missing_packages_entrypoint_reports_override(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_companion.py"), "packages", "tests/test_packages_regressions.py"],
        env=dict(os.environ, XU_PACKAGES_ROOT=str(tmp_path)), capture_output=True, text=True)
    assert result.returncode != 0
    assert "XU_PACKAGES_ROOT" in result.stderr
