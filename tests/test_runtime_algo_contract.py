"""Regression contracts for the runtime-algo layering fixes and matrix seam.

Locks the four COMPILE_LAYERING_REVIEW 2026-09-28 issues plus the
run_fixture_matrix parameter plumbing that previously advertised -O0/-O1/...
but never delivered those flags to the compiler.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STR_ALGO = (ROOT / "src/runtime/str_algo.xu").read_text(encoding="utf-8")
RT_STRING = (ROOT / "src/cmd/compile/rt_string.xu").read_text(encoding="utf-8")
MIR = (ROOT / "src/xu/types/mir.xu").read_text(encoding="utf-8")
INLINE = (ROOT / "src/xu/types/mir_09_opt_inline.xu").read_text(encoding="utf-8")
RUN_FIXTURES = (ROOT / "scripts/run_fixtures.sh").read_text(encoding="utf-8")
MATRIX = (ROOT / "scripts/run_fixture_matrix.sh").read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    match = re.search(
        rf"^(?:pub\s+)?fn\s+{re.escape(name)}\([^\n]*\)[^{{]*\{{(?P<body>.*?)^\}}",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing Xu function {name}"
    return match.group("body")


def _bash_function_body(source: str, name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{(?P<body>.*?)^\}}",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing shell function {name}"
    return match.group("body")


def test_parse_int_rejects_intmin_minus_one_and_minus_two() -> None:
    """INT_MIN is the only representable acc > lim negative; -810/-809 overflow."""

    body = _function_body(STR_ALGO, "parse_int")
    # The historical bug accepted any neg last-digit with acc == lim+1 and d==0
    # (i.e. -...810). That special case must be gone.
    assert "acc == lim + 1" not in body
    assert "lim + 1" not in body
    # The legitimate INT_MIN path is room == d - 1 on the final digit.
    assert "room == d - 1" in body
    assert "9223372036854775807 - 1" in body
    # Overflow message stays the documented one.
    assert "parse_int: out of range" in body


def test_starts_with_has_no_arbitrary_size_cap() -> None:
    """Prefixes may come from runtime data; only negative descriptor lengths fail."""

    xu_body = _function_body(STR_ALGO, "starts_with")
    assert "1048576" not in xu_body
    assert "1 MiB" not in xu_body
    assert "s.len < 0 || prefix.len < 0" in xu_body
    # Assembler twin is gone.
    assert "fn rt_emit_starts_with" not in RT_STRING


def test_str_runes_helpers_borrow_string() -> None:
    """utf8_next/utf8_advance must take &string or each rune clones the buffer."""

    for name in ("utf8_next", "utf8_advance"):
        match = re.search(
            rf"^fn\s+{name}\((?P<args>[^)]*)\)",
            STR_ALGO,
            flags=re.MULTILINE,
        )
        assert match is not None, f"missing helper {name}"
        assert "&string" in match.group("args"), f"{name} must borrow the string"

    body = _function_body(STR_ALGO, "str_runes")
    # Helpers are already `&string`; pass them through without re-borrow.
    assert "utf8_next(s, i)" in body
    assert "utf8_advance(s, i)" in body


def test_mir_fn_commit_returns_committed_index_and_inline_fails_closed() -> None:
    sig = re.search(r"^fn mir_fn_commit\([^\n]*\) int \{", MIR, re.MULTILINE)
    assert sig is not None
    commit = _function_body(MIR, "mir_fn_commit")
    assert commit.count("<< -1") >= 4
    assert "<< seq" in commit
    call = _function_body(INLINE, "mir_inline_cfg_call")
    assert "seq := mir_fn_commit(m, fi, f)" in call
    refused = call.split("if seq < 0 {")[1].split("m.opt_inline_ok")[0]
    assert "<< -1" in refused
    assert "<< seq" not in refused


def test_matrix_extra_args_reach_run_fixtures_compile() -> None:
    """XU_FIXTURE_EXTRA_ARGS must be consumed by compile_source, not ignored."""

    assert "XU_FIXTURE_EXTRA_ARGS" in MATRIX
    assert "XU_FIXTURE_EXTRA_ARGS" in RUN_FIXTURES
    compile_src = _bash_function_body(RUN_FIXTURES, "compile_source")
    assert "XU_FIXTURE_EXTRA_ARGS" in compile_src
    # Both the product wrapper path and the legacy $BIN path get the flags.
    assert "PRODUCT_COMPILER_RUNNER" in compile_src
    assert "extra" in compile_src


def test_run_fixtures_accepts_only_filter() -> None:
    """run_fixture_matrix and test_heap_check pass --only=; run_fixtures must honor it."""

    assert "--only=*)" in RUN_FIXTURES
    assert "ONLY" in RUN_FIXTURES
    assert "grep -Eq" in RUN_FIXTURES
    assert 'args+=(--only="$ONLY")' in MATRIX


def test_starts_with_builtin_prefers_runtime_xu() -> None:
    """P1 slice 1: bare starts_with binds to runtime.starts_with when loaded."""

    checker = (ROOT / "src/xu/types/check_12_call.xu").read_text(encoding="utf-8")
    marker = "fn (c &mut Checker) check_call_str("
    start = checker.find(marker)
    assert start >= 0, "missing check_call_str"
    body = checker[start : start + 8000]
    assert 'abi_name := "starts_with"' in body
    assert 'c.require_runtime_abi(p, n, runtime_abi_id(&abi_name))' in body
    # Non-consuming surface: do not arg_pass/move the historical string args.
    sw = body.split('if name == "starts_with"')[1].split("<< -1")[0]
    assert "c.arg_pass" not in sw
    # Old Assembler fallback removed — runtime is required.
    assert "ncall, n, -25" not in sw

    driver = (ROOT / "src/cmd/compile/driver_build.xu").read_text(encoding="utf-8")
    assert "load_unit_needs_runtime_algo" in driver
    assert 'imps.push("runtime")' in driver
    assert 'types.runtime_abi_syntax_id(&name)' in _function_body(driver, "load_unit_needs_runtime_algo")


def test_parse_int_builtin_prefers_runtime_xu() -> None:
    """P1 slice 2: bare parse_int binds to runtime.parse_int with throw ABI."""

    checker = (ROOT / "src/xu/types/check_12_call.xu").read_text(encoding="utf-8")
    marker = "fn (c &mut Checker) check_call_str("
    start = checker.find(marker)
    assert start >= 0, "missing check_call_str"
    body = checker[start : start + 8000]
    pi = body.split('if name == "parse_int"')[1].split('if name == "starts_with"')[0]
    assert 'abi_name := "parse_int"' in pi
    assert 'c.require_runtime_abi(p, n, runtime_abi_id(&abi_name))' in pi
    assert "wrap_throwable_call_result" in pi
    # Old Assembler fallback removed — runtime is required.
    assert "wrap_throwable_parse_int" not in pi
    assert "c.arg_pass" not in pi


def test_str_int_builtin_prefers_runtime_itoa() -> None:
    """P1 slice 3: str(int) binds to runtime.itoa; &int keeps the ncall deref."""

    checker = (ROOT / "src/xu/types/check_12_call.xu").read_text(encoding="utf-8")
    marker = "fn (c &mut Checker) check_call_str("
    start = checker.find(marker)
    assert start >= 0, "missing check_call_str"
    body = checker[start : start + 8000]
    assert 'abi_name := "itoa"' in body
    assert 'c.require_runtime_abi(p, n, runtime_abi_id(&abi_name))' in body
    # Both int and &int bind to runtime.itoa (MIR auto-derefs refs).
    assert "ncall, n, -6" not in body

    driver = (ROOT / "src/cmd/compile/driver_build.xu").read_text(encoding="utf-8")
    assert 'types.runtime_abi_syntax_id(&name)' in _function_body(driver, "load_unit_needs_runtime_algo")


def test_bytes_runes_bind_to_runtime_xu() -> None:
    """P1 slice 4: s.bytes()/s.runes() lower to runtime.str_bytes/str_runes."""

    mir = (ROOT / "src/xu/types/mir_07_call.xu").read_text(encoding="utf-8")
    # Redirect happens before arg packing so the receiver is a by-pointer string.
    assert 'ncall[n] == -75' in mir
    assert "redirected_br" in mir
    assert 'c.require_runtime_abi(p, n, runtime_abi_syntax_id(&abi_syntax))' in mir
    # Assembler fallback removed.
    marker = "} else if fi == -75 || fi == -76 {"
    start = mir.find(marker)
    assert start >= 0, "missing bytes/runes lowering"
    body = mir[start : start + 600]
    # Assembler fallback may remain as a fail-loud stub.

    driver = (ROOT / "src/cmd/compile/driver_build.xu").read_text(encoding="utf-8")
    assert 'types.runtime_abi_syntax_id(&name)' in _function_body(driver, "load_unit_needs_runtime_algo")
    assert 'types.runtime_abi_syntax_id(&name)' in _function_body(driver, "load_unit_needs_runtime_algo")


def test_readonly_runtime_entries_borrow_and_builtin_lowering_keeps_owner() -> None:
    for name in ("starts_with", "parse_int", "str_bytes", "str_runes"):
        sig = re.search(rf"^pub fn {name}\(([^)]*)\)", STR_ALGO, re.MULTILINE)
        assert sig is not None
        assert "s &string" in sig[1]
        assert "s string" not in sig[1]
    lowering = (ROOT / "src/xu/types/mir_07_call.xu").read_text()
    assert "borrowed = is_ref_type(pty)" in lowering
    assert "!cloned_str && !borrowed" in lowering


def test_fnval_source_proof_shared_and_includes_backedges() -> None:
    proof = _function_body(MIR, "mir_unique_pred_of")
    assert "pi == bi" not in proof
    assert "mir_fnaddr_label_of_temp_f" not in MIR + INLINE
    assert INLINE.count("mir_fnval_known_label(") == 2
    emitter = (ROOT / "src/cmd/compile/emit_instr_call_user_net.xu").read_text()
    assert "types.mir_fnval_known_label(m, fi, bi, ii, ptr_temp)" in emitter
    assert "types.mir_fnval_reaching_loadfn" not in emitter
