"""Contract tests for the MIR borrow/drop side verifier (P1.1)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIR_BORROW = (ROOT / "src/xu/types/mir_20_borrow.xu").read_text(encoding="utf-8")
AST_BORROW = (ROOT / "src/xu/types/check_10_borrow.xu").read_text(encoding="utf-8")
LOWER = (ROOT / "src/xu/types/mir_02_addressing.xu").read_text(encoding="utf-8")


def test_mir_borrow_module_exports_analyze_and_check() -> None:
    assert "fn mir_borrow_analyze" in MIR_BORROW
    assert "fn mir_borrow_check_fn" in MIR_BORROW
    assert "struct MirBorrowReport" in MIR_BORROW


def test_mir_borrow_walks_cfg_and_tracks_drop() -> None:
    # Drop (kind 8) must kill a local; LoadLocal (2) after drop is a finding.
    assert "kind == 8" in MIR_BORROW
    assert "kind == 2" in MIR_BORROW
    assert "use_after_drop" in MIR_BORROW
    assert "addr_of_dropped" in MIR_BORROW
    # StoreLocal reinit after drop is not a use (loop-body mut x := …).
    assert "dropped[loc] = false" in MIR_BORROW or "reinit" in MIR_BORROW
    # Only owning locals participate in lifetime tracking.
    assert "locals_owning" in MIR_BORROW
    # CFG join: a drop on any reachable predecessor can poison a later use.
    assert "dropped_in" in MIR_BORROW
    assert "pred_dst" in MIR_BORROW or "pred_src" in MIR_BORROW
    # Cross-block pointer loans remain explicitly deferred.
    assert "loan_after_drop" in MIR_BORROW
    assert "loans" in MIR_BORROW


def test_mir_borrow_gate_env_hook() -> None:
    assert "XU_MIR_BORROW_GATE" in (ROOT / "src/cmd/compile/driver_build.xu").read_text(
        encoding="utf-8"
    )
    assert "mir_borrow_enforce" in MIR_BORROW or "mir_borrow_enforce" in (
        ROOT / "src/xu/types/mir_02_addressing.xu"
    ).read_text(encoding="utf-8")


def test_promote_does_not_bind_owning_sval_temporaries() -> None:
    # mfn_isval is `sval + ""` and may alias the instruction buffer; binding
    # it to a local double-frees under XU_HEAP_CHECK (promote ssa_f).
    PROMOTE = (ROOT / "src/xu/types/mir_17_opt_promote.xu").read_text(encoding="utf-8")
    assert "mir_promote_math_label_instr" in PROMOTE
    assert "mir_promote_sval_eq_lit" in PROMOTE
    # has_math_call must not bind mfn_isval to a string temporary.
    match = re.search(
        r"fn mir_promote_has_math_call_f\([^\n]*\)[^{]*\{(?P<body>.*?)^\}",
        PROMOTE,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    assert "mfn_isval(" not in match.group("body")


def test_ast_borrow_checker_remains_present() -> None:
    # Migration: AST checker stays until MIR is authoritative.
    assert "fn (c &mut Checker) borrow_check_fn" in AST_BORROW


def test_lower_fn_builds_mfn_for_side_verifier() -> None:
    assert "fn lower_fn" in LOWER
    # lower_fn returns MFn so a side verifier can walk it after lowering.
    match = re.search(
        r"^fn lower_fn\([^\n]*\)[^{]*\{(?P<body>.*?)^\}",
        LOWER,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    assert "<< f" in match.group("body")
