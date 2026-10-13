"""Executable replacement must preserve existing readers and failed installs."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts/install_product_executable.sh"


def install(source, target):
    return subprocess.run(["bash", str(INSTALL), str(source), str(target)], capture_output=True, text=True)


def test_replacement_preserves_an_existing_reader(tmp_path):
    target = tmp_path / "tool"
    source = tmp_path / "new tool"
    old = "#!/bin/sh\nprintf old"
    target.write_text(old)
    source.write_text("#!/bin/sh\nprintf new")
    with target.open() as reader:
        result = install(source, target)
        assert result.returncode == 0, result.stderr
        assert reader.read() == old
    assert subprocess.check_output([str(target)], text=True) == "new"


def test_identical_reinstall_gets_a_fresh_executable_identity(tmp_path):
    target = tmp_path / "tool"
    target.write_text("#!/bin/sh\nprintf same")
    target.chmod(0o755)
    before = target.stat().st_ino
    result = install(target, target)
    assert result.returncode == 0, result.stderr
    assert target.stat().st_ino != before
    assert subprocess.check_output([str(target)], text=True) == "same"


def test_failed_install_leaves_the_current_tool_available(tmp_path):
    target = tmp_path / "tool"
    target.write_text("#!/bin/sh\nprintf old")
    target.chmod(0o755)
    result = install(tmp_path / "missing", target)
    assert result.returncode != 0
    assert subprocess.check_output([str(target)], text=True) == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tool"]
