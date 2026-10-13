from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_stdlib_matrix.py"
MATRIX = ROOT / "docs" / "audit" / "stdlib_matrix.json"


def load_matrix() -> dict:
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def test_matrix_is_current_and_has_explicit_platform_states() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    matrix = load_matrix()
    assert matrix["schema"] == "xu.stdlib-matrix.v1"
    assert matrix["targets"] == [
        "macos-arm64",
        "macos-x64",
        "linux-arm64",
        "linux-x64",
        "windows-x64",
        "windows-arm64",
        "linux-loongarch64",
        "linux-riscv64",
    ]
    assert matrix["counts"]["packages"] >= 100
    assert all(
        set(package["status"]["platform"]) == set(matrix["targets"])
        for package in matrix["packages"]
    )


def test_matrix_keeps_extensions_separate_from_go_stdlib_scope() -> None:
    matrix = load_matrix()
    by_name = {package["package"]: package for package in matrix["packages"]}
    assert by_name["errors"]["scope"] == "stdlib"
    assert by_name["crypto/sm3"]["scope"] == "xu-extension"
    assert by_name["ui"]["scope"] == "xu-extension"


def test_matrix_records_source_and_fixture_provenance() -> None:
    matrix = load_matrix()
    by_name = {package["package"]: package for package in matrix["packages"]}
    for name in ("errors", "io", "net/http", "crypto/x509"):
        package = by_name[name]
        assert len(package["source_sha256"]) == 64
        assert package["source_files"] > 0
        assert package["public_symbol_count"] > 0
        assert isinstance(package["fixtures"], list)
    assert "archive_tar_err" in by_name["archive/tar"]["fixtures"]
    assert "http_scheme_err" in by_name["net/http"]["fixtures"]


def test_public_stream_constraints_have_names() -> None:
    package = next(p for p in load_matrix()["packages"] if p["package"] == "io")
    names = {p["name"] for p in package["public_symbols"] if p["kind"] == "struct"}
    assert {"StreamReader", "StreamWriter"} <= names
    assert "<anonymous>" not in names


def test_fixture_log_records_host_evidence(tmp_path) -> None:
    log = tmp_path / "fixtures.log"
    log.write_text(
        "PASS archive_tar\nPASS archive_tar_err\nPASS strings_bytes_b0\n"
        "FAIL os_file_rw\nFAIL os_b1c\nSKIP net_tcp_echo\n"
    )
    out = tmp_path / "evidence.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "stdlib_evidence_from_fixtures.py"),
            "--log",
            str(log),
            "--host",
            "macos-arm64",
            "--compiler",
            "bin/xu",
            "--output",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(out.read_text(encoding="utf-8"))
    assert evidence["schema"] == "xu.stdlib-evidence.v1"
    assert evidence["packages"]["archive/tar"]["semantic"] == "pass"
    assert evidence["packages"]["archive/tar"]["platform"]["macos-arm64"] == "native-run"
    assert evidence["packages"]["os"]["semantic"] == "fail"
    assert evidence["packages"]["os"]["platform"]["macos-arm64"] == "failed"
    assert evidence["packages"]["strings"]["semantic"] == "pass"
    assert evidence["packages"]["strings"]["platform"]["macos-arm64"] == "native-run"
