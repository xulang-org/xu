"""Regression contract for hosted RA call admission.

The direct math/bits lowering is an emitter optimisation, but it is not a
proof that every function containing that call is safe for the legacy
whole-function register cache.  Treating the call label as a no-ABI boundary
made the product-generated Gen1 compiler fail on its next self-host hop.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GLUE = (ROOT / "src/cmd/compile/emit_rt_glue.xu").read_text(encoding="utf-8")
INLINE = (ROOT / "src/xu/types/mir_09_opt_inline.xu").read_text(encoding="utf-8")
PROMOTE = (ROOT / "src/xu/types/mir_17_opt_promote.xu").read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    match = re.search(
        rf"^fn {re.escape(name)}\([^\n]*\)[^{{]*\{{(?P<body>.*?)^\}}",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing Xu function {name}"
    return match.group("body")


def test_product_ra_does_not_treat_math_calls_as_abi_free() -> None:
    body = _function_body(GLUE, "product_rc_mir_safe")
    fat = _function_body(GLUE, "rc_fat_desc_ok")

    # The legacy RA path may admit a proven self-recursive call. Direct
    # math/bits lowering is not generally an interprocedural call-clobber
    # proof, while the hardware fsqrt emitter is an explicit no-call intrinsic
    # and is therefore the one permitted math exception.
    for label in (
        "_xu_math_bits_leading_zeros",
        "_xu_math_bits_trailing_zeros",
        "_xu_math_bits_reverse",
        "_xu_math_bits_reverse_bytes",
        "_xu_math_bits_ones_count",
        "_xu_math_bits_rotate_left",
        "_xu_math_bits_rotate_right",
        "_xu_math_bits_len",
    ):
        assert label not in body

    assert 'sval == "_xu_math_sqrt"' in body

    assert "ck == 1 && sval == f.label" in body
    # Named fn-value binop peeps are ABI-free; unknown indirect still charges
    # has_user_call (fail-closed to fat-pointer blr).
    assert "ck == 80" in body
    # Two-word fn-value locals/temps stay frame-backed but must not reject
    # the whole scalar loop. The check lives in rc_fat_desc_ok, which
    # product_rc_mir_safe uses for every local/temp slot.
    assert "is_fn_type(ty)" in fat
    assert "mir_fnval_call_is_binop_peep" in body


def test_scalar_self_loop_keeps_regcache_over_vreg() -> None:
    """Fixed-home must not steal SIMD/pin loops from RegCache."""

    emit_fn = (ROOT / "src/cmd/compile/emit_function.xu").read_text(encoding="utf-8")
    # Contract: SIMD/pin kernels prefer RegCache; try_vregs stays off until the
    # planner's OOB on hash/fnv is fixed (see COMPILE_LAYERING_FNVAL_P0).
    assert "fn_keeps_rc_over_vreg" in (ROOT / "src/cmd/compile/emit_vec.xu").read_text()
    assert "try_vregs = false" in emit_fn or "mut try_vregs := false" in emit_fn

    vec = (ROOT / "src/cmd/compile/emit_vec.xu").read_text(encoding="utf-8")
    assert "fn fn_has_iand_reduce_self_loop" in vec
    assert "fn fn_keeps_rc_over_vreg" in vec
    # SIMD reduce must not require rc_on (fixed-home clears it).
    block = _function_body(vec, "emit_vec_block")
    assert "a.arch != 0" in block
    assert "if !a.rc_on" not in block


def test_product_cfg_inliner_requires_bounded_verified_commit() -> None:
    """The current cloner verifies its remapping and bounds every caller."""
    body = _function_body(INLINE, "mir_inline_cfg_leaves")
    assert re.search(r"if m.opt_level < 1\s*\{\s*<<", body)
    once = _function_body(INLINE, "mir_inline_cfg_leaves_once")
    assert "mir_cfg_caller_ok_f" in once
    assert "mir_cfg_caller_loop_inline_safe" in once
    # Validate the actual commit path, rather than the old O2/O3 disable flag.
    guard = INLINE.index("if !mir_verify_inline_cfg_f(&f,")
    tail = INLINE[guard:]
    failure = tail.split("\n    }", 1)[0]
    assert "m.opt_inline_skip += 1" in failure
    assert "<< -1" in failure
    assert tail.index("mir_fn_commit") > len(failure)


def test_scalar_promotion_only_opens_for_intrinsic_call_shapes() -> None:
    """Generic calls must not reintroduce the measured loop regression."""

    label_body = _function_body(PROMOTE, "mir_promote_math_label_instr")
    for label in (
        "_xu_math_sqrt",
        "_xu_math_bits_leading_zeros",
        "_xu_math_bits_trailing_zeros",
        "_xu_math_bits_reverse",
        "_xu_math_bits_reverse_bytes",
        "_xu_math_bits_ones_count",
        "_xu_math_bits_rotate_left",
        "_xu_math_bits_rotate_right",
        "_xu_math_bits_len",
    ):
        assert f'mir_promote_sval_eq_lit(&ins[ii].sval, "{label}")' in label_body
    assert 's[0] ==' not in label_body

    call_body = _function_body(PROMOTE, "mir_promote_scalar_call_f")
    assert "ck == 1 && mir_promote_math_label" in call_body
    assert "ck == 2 || ck == 3 || ck == 4 || ck == 5 || ck == 22" in call_body
    assert "mir_promote_call_terminal_f" in call_body
    witness_body = _function_body(PROMOTE, "mir_promote_has_math_call_f")
    assert "mir_promote_math_label" in witness_body
    assert "DEBUG-vreg" not in PROMOTE


def test_regcache_admission_has_no_user_function_name_exceptions() -> None:
    body = _function_body(GLUE, "emit_program")
    for name in ("advance", "energy", "offset_momentum", "take"):
        assert f'"{name}"' not in body
    assert "ok_rc := product_rc_mir_safe(m, fi)" in body
