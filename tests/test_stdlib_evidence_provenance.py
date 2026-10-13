"""A past PASS must stop applying after any of its inputs change."""
from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "stdlib_inventory", ROOT / "scripts/generate_stdlib_matrix.py"
)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


@pytest.fixture
def bound_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    (tmp_path / "compiler").write_bytes(b"compiler-v1")
    fixture = tmp_path / "tests/fixtures/text"
    fixture.mkdir(parents=True)
    (fixture / "expected.txt").write_text("ok\n")
    packages = [
        {"package": "text", "imports": ["utf8"], "source_sha256": "a" * 64,
         "fixtures": ["text"], "status": {"semantic": "not-measured",
                                              "platform": {"host": "not-measured"}}},
        {"package": "utf8", "imports": [], "source_sha256": "b" * 64,
         "fixtures": [], "status": {"semantic": "not-measured",
                                       "platform": {"host": "not-measured"}}},
    ]
    matrix = {"packages": packages, "evidence_states": ["native-run", "failed", "not-measured"]}
    by_name = {p["package"]: p for p in packages}
    evidence = {"compiler": "compiler",
                "compiler_sha256": inventory.file_sha256(tmp_path / "compiler"),
                "packages": {"text": {"semantic": "pass", "platform": {"host": "native-run"},
                                      "evidence_sha256": inventory.evidence_hash(packages[0], by_name)}}}
    return tmp_path, matrix, evidence


def test_unchanged_inputs_accept_verdict(bound_evidence):
    _, matrix, evidence = bound_evidence
    inventory.apply_evidence(matrix, evidence)
    assert matrix["packages"][0]["status"]["semantic"] == "pass"
    assert matrix["packages"][0]["status"]["platform"]["host"] == "native-run"
    assert matrix["evidence"]["rejected"] == {}


@pytest.mark.parametrize("change", ["source", "dependency", "runtime", "fixture", "resource", "shared_data", "compiler", "legacy"])
def test_changed_or_unbound_inputs_reject_verdict(bound_evidence, change):
    root, matrix, evidence = bound_evidence
    evidence = deepcopy(evidence)
    if change == "source":
        matrix["packages"][0]["source_sha256"] = "c" * 64
    elif change == "dependency":
        matrix["packages"][1]["source_sha256"] = "c" * 64
    elif change == "fixture":
        (root / "tests/fixtures/text/expected.txt").write_text("changed\n")
    elif change == "runtime":
        (root / "src/runtime").mkdir(parents=True)
        (root / "src/runtime/helper.xu").write_text("fn helper() int { << 1 }\n")
    elif change == "resource":
        (root / "tests/fixtures/text/input.bin").write_bytes(b"vector")
    elif change == "shared_data":
        (root / "tests/data").mkdir()
        (root / "tests/data/vector.bin").write_bytes(b"shared vector")
    elif change == "compiler":
        (root / "compiler").write_bytes(b"compiler-v2")
    else:
        evidence.pop("compiler_sha256")
        evidence["packages"]["text"].pop("evidence_sha256")
    inventory.apply_evidence(matrix, evidence)
    assert matrix["packages"][0]["status"]["semantic"] == "not-measured"
    assert matrix["packages"][0]["status"]["platform"]["host"] == "not-measured"
    assert "text" in matrix["evidence"]["rejected"]
