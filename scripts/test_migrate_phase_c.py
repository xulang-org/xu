"""Unit tests for scripts/migrate_phase_c.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.migrate_phase_c import lex, main, migrate_text, rejected_spellings


ROOT = Path(__file__).resolve().parents[1]


def test_mut_binding_to_dollar_name() -> None:
    src = "fn main() {\n  mut x := 1\n}\n"
    result = migrate_text(src)
    assert result.text == "fn main() {\n  $x := 1\n}\n"
    assert [hit.kind for hit in result.hits] == ["mut-bind"]
    assert result.hits[0].line == 2
    assert result.hits[0].old == "mut x :="
    assert result.hits[0].new == "$x :="
    assert result.candidates == []


def test_mut_binding_keeps_spacing_around_colon_assign() -> None:
    src = "fn main() {\nmut  x  := 1\n}\n"
    assert migrate_text(src).text == "fn main() {\n$x  := 1\n}\n"


def test_writable_borrow_and_mut_reborrow() -> None:
    src = "fn main() {\n  r := mut &x\n  g(mut &*r)\n  h(mut & xs[0])\n}\n"
    result = migrate_text(src)
    assert result.text == "fn main() {\n  r := $&x\n  g(&*r)\n  h($&xs[0])\n}\n"
    assert [hit.kind for hit in result.hits] == ["mut-borrow", "mut-reborrow", "mut-borrow"]


def test_mut_ref_type_with_and_without_lifetime() -> None:
    src = "fn old(p &mut a int, q &mut int) &mut int {\n  << q\n}\n"
    result = migrate_text(src)
    assert result.text == "fn old(p $&a int, q $&int) $&int {\n  << q\n}\n"
    assert [hit.kind for hit in result.hits] == ["mut-type", "mut-type", "mut-type"]


def test_spaced_mut_type_glues_dollar_amp() -> None:
    src = "fn old(p & mut int) {\n}\n"
    assert migrate_text(src).text == "fn old(p $&int) {\n}\n"


def test_nested_mut_ref_type() -> None:
    src = "fn f(p &mut &mut int) {\n}\n"
    assert migrate_text(src).text == "fn f(p $&$&int) {\n}\n"


def test_infix_amp_and_and_and_are_left_alone() -> None:
    src = "fn main() {\n  mut x := 1\n  y := x & 1\n  z := x && y\n}\n"
    result = migrate_text(src)
    assert result.text == "fn main() {\n  $x := 1\n  y := x & 1\n  z := x && y\n}\n"
    assert result.candidates == []


def test_already_new_syntax_is_unchanged() -> None:
    src = "fn f(p $&a int) {\n  $x := 1\n  r := $&x\n  g(&*r)\n}\n"
    result = migrate_text(src)
    assert result.text == src
    assert result.hits == []


def test_dollar_space_amp_is_already_new_syntax() -> None:
    src = "fn f(p $ & int) {\n}\n"
    assert migrate_text(src).text == src
    assert migrate_text(src).hits == []


def test_skips_strings_comments_and_compile_tags() -> None:
    src = (
        "@main\n"
        "$linux\n"
        "$$windows\n"
        "fn main() {\n"
        "  // mut x := 1 &mut T mut &a mut &*r\n"
        "  /* mut y := 2\n"
        "     &mut int\n"
        "  */\n"
        '  s := "mut z := 3 &mut int \\$name"\n'
        "  raw := `mut w := 4 &mut`\n"
        "  mut v := 5\n"
        "}\n"
    )
    result = migrate_text(src)
    assert "// mut x := 1 &mut T mut &a mut &*r\n" in result.text
    assert "/* mut y := 2\n     &mut int\n  */\n" in result.text
    assert '"mut z := 3 &mut int \\$name"' in result.text
    assert "`mut w := 4 &mut`" in result.text
    assert "$linux\n" in result.text
    assert "$$windows\n" in result.text
    assert "$v := 5\n" in result.text
    assert [hit.kind for hit in result.hits] == ["mut-bind"]


def test_comment_between_mut_and_name_is_preserved() -> None:
    src = "fn main() {\n  mut /*keep*/ x := 1\n}\n"
    assert migrate_text(src).text == "fn main() {\n  /*keep*/ $x := 1\n}\n"


def test_does_not_match_mut_binding_across_newline_or_split_colon() -> None:
    src = "fn main() {\n  mut\n  x := 1\n  mut y : = 2\n}\n"
    assert migrate_text(src).text == src
    assert migrate_text(src).hits == []


def test_rejected_spellings_are_not_produced() -> None:
    src = (
        "fn old(p &mut a int) &mut int {\n"
        "  mut x := 1\n"
        "  r := mut &x\n"
        "  g(mut &*r)\n"
        "  h(x & 1)\n"
        "  q := $&x\n"
        "}\n"
    )
    result = migrate_text(src)
    assert result.text == (
        "fn old(p $&a int) $&int {\n"
        "  $x := 1\n"
        "  r := $&x\n"
        "  g(&*r)\n"
        "  h(x & 1)\n"
        "  q := $&x\n"
        "}\n"
    )
    assert rejected_spellings(result.text) == []
    assert rejected_spellings("fn f(p & $T) {\n  z := *$&r\n  g($&*r)\n}\n") == [
        "&$",
        "*$&",
        "$&*",
    ]


def test_idempotent_on_mixed_sample() -> None:
    src = (
        "fn old(p &mut a int, q &mut int) {\n"
        "  mut x := 1\n"
        "  r := mut &x\n"
        "  g(mut &*r)\n"
        "  y := x & 1 && true\n"
        '  s := "mut x := &mut"\n'
        "}\n"
    )
    once = migrate_text(src)
    twice = migrate_text(once.text)
    assert twice.text == once.text
    assert twice.hits == []


def test_omit_read_borrow_rewrites_call_and_shared_let() -> None:
    src = "fn main() {\n  f(&x)\n  g(a, &y)\n  let s: &int = &z\n}\n"
    off = migrate_text(src)
    assert off.text == src
    assert off.hits == []
    on = migrate_text(src, omit_read_borrows=True)
    assert on.text == "fn main() {\n  f(x)\n  g(a, y)\n  let s: &int = z\n}\n"
    assert [hit.kind for hit in on.hits] == [
        "omit-read-borrow",
        "omit-read-borrow",
        "omit-read-borrow",
    ]


def test_omit_read_borrow_candidates_are_not_rewritten() -> None:
    src = (
        "fn main() {\n"
        "  f(&p.field)\n"
        "  f(&Item)\n"
        "  f((&x))\n"
        "  s := &x\n"
        "  t = &x\n"
        "  a & b\n"
        "}\n"
    )
    result = migrate_text(src, omit_read_borrows=True)
    assert result.text == src
    assert result.hits == []
    reasons = [item.reason for item in result.candidates]
    assert any("not a plain local or name" in reason for reason in reasons)
    assert any("may be a type" in reason for reason in reasons)
    assert any("not a call argument" in reason for reason in reasons)
    assert any("binding initializer" in reason for reason in reasons)
    assert not any("a & b" in item.text for item in result.candidates)


def test_omit_does_not_touch_types_or_fn_types() -> None:
    src = "fn f(p &int) &int {\n  let s: &int = x\n  g(fn(&int))\n}\n"
    result = migrate_text(src, omit_read_borrows=True)
    assert result.text == src
    assert result.hits == []
    assert result.candidates == []


def test_simplify_reborrow_rewrites_known_shared_only() -> None:
    src = (
        "fn read(p &int) {\n"
        "  f(&*p)\n"
        "}\n"
        "fn main() {\n"
        "  s := &x\n"
        "  f(&*s)\n"
        "}\n"
        "fn write(r $&int) {\n"
        "  f(&*r)\n"
        "}\n"
    )
    off = migrate_text(src)
    assert "&*p" in off.text and "&*s" in off.text and "&*r" in off.text
    on = migrate_text(src, simplify_reborrow=True)
    assert on.text == (
        "fn read(p &int) {\n"
        "  f(p)\n"
        "}\n"
        "fn main() {\n"
        "  s := &x\n"
        "  f(s)\n"
        "}\n"
        "fn write(r $&int) {\n"
        "  f(&*r)\n"
        "}\n"
    )
    assert [hit.kind for hit in on.hits] == ["simplify-reborrow", "simplify-reborrow"]
    assert len(on.candidates) == 1
    assert "writable" in on.candidates[0].reason


def test_simplify_reborrow_compound_and_unknown_are_candidates() -> None:
    src = "fn read(p &int) {\n  f(&*p.field)\n  f(&*other)\n}\n"
    result = migrate_text(src, simplify_reborrow=True)
    assert result.text == src
    assert result.hits == []
    assert len(result.candidates) == 2


def test_method_receiver_shared_reborrow() -> None:
    src = "fn (p &int) read() {\n  f(&*p)\n}\n"
    result = migrate_text(src, simplify_reborrow=True)
    assert result.text == "fn (p &int) read() {\n  f(p)\n}\n"


def test_mut_reborrow_of_writable_stays_shared_spelling() -> None:
    src = "fn g(r $&int) {\n  f(mut &*r)\n}\n"
    plain = migrate_text(src)
    assert plain.text == "fn g(r $&int) {\n  f(&*r)\n}\n"
    both = migrate_text(src, simplify_reborrow=True)
    assert both.text == plain.text
    assert any(hit.kind == "mut-reborrow" for hit in both.hits)
    assert both.candidates
    again = migrate_text(both.text, simplify_reborrow=True)
    assert again.text == both.text
    assert again.hits == []


def test_mut_reborrow_of_shared_simplifies_in_one_run() -> None:
    src = "fn main() {\n  s := &x\n  f(mut &*s)\n}\n"
    result = migrate_text(src, simplify_reborrow=True)
    assert result.text == "fn main() {\n  s := &x\n  f(s)\n}\n"
    assert migrate_text(result.text, simplify_reborrow=True).text == result.text


def test_optional_flags_are_idempotent_together() -> None:
    src = (
        "fn read(p &int) {\n"
        "  f(&x, &*p)\n"
        "  g(&p.field)\n"
        "  mut y := 1\n"
        "  h(mut &y)\n"
        "}\n"
    )
    once = migrate_text(src, omit_read_borrows=True, simplify_reborrow=True)
    twice = migrate_text(once.text, omit_read_borrows=True, simplify_reborrow=True)
    assert once.text == (
        "fn read(p &int) {\n"
        "  f(x, p)\n"
        "  g(&p.field)\n"
        "  $y := 1\n"
        "  h($&y)\n"
        "}\n"
    )
    assert twice.text == once.text
    assert twice.hits == []
    assert rejected_spellings(once.text) == []


def test_check_apply_and_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "sample.xu"
    target.write_text("fn main() {\n  mut x := 1\n  f(&x)\n}\n", encoding="utf-8")
    other = tmp_path / "note.py"
    other.write_text("mut x := 1\n", encoding="utf-8")

    assert main(["--check", str(target)]) == 1
    check_out = capsys.readouterr().out
    assert "mut-bind:" in check_out
    assert target.read_text(encoding="utf-8") == "fn main() {\n  mut x := 1\n  f(&x)\n}\n"

    assert main([str(target)]) == 0
    assert "mut-bind:" in capsys.readouterr().out
    assert target.read_text(encoding="utf-8") == "fn main() {\n  mut x := 1\n  f(&x)\n}\n"

    assert main(["--apply", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "fn main() {\n  $x := 1\n  f(&x)\n}\n"
    assert main(["--check", str(target)]) == 0
    assert main(["--apply", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "fn main() {\n  $x := 1\n  f(&x)\n}\n"
    assert other.read_text(encoding="utf-8") == "mut x := 1\n"

    assert main(["--check", "--omit-read-borrows", str(target)]) == 1
    assert main(["--apply", "--omit-read-borrows", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "fn main() {\n  $x := 1\n  f(x)\n}\n"
    assert main(["--check", "--omit-read-borrows", str(target)]) == 0


def test_check_candidates_do_not_fail(tmp_path: Path) -> None:
    target = tmp_path / "maybe.xu"
    target.write_text("fn main() {\n  f(&p.field)\n  s := &x\n}\n", encoding="utf-8")
    assert main(["--check", "--omit-read-borrows", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "fn main() {\n  f(&p.field)\n  s := &x\n}\n"


def test_directory_scan_skips_non_xu_and_hidden(tmp_path: Path) -> None:
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "a.xu").write_text("fn main() {\n  mut x := 1\n}\n", encoding="utf-8")
    nested = src / "sub"
    nested.mkdir()
    (nested / "b.xu").write_text("fn main() {\n  y := 1\n}\n", encoding="utf-8")
    (src / "skip.py").write_text("mut x := 1\n", encoding="utf-8")
    hidden = src / ".git"
    hidden.mkdir()
    (hidden / "c.xu").write_text("fn main() {\n  mut z := 1\n}\n", encoding="utf-8")

    assert main(["--apply", str(src)]) == 0
    assert (src / "a.xu").read_text(encoding="utf-8") == "fn main() {\n  $x := 1\n}\n"
    assert (nested / "b.xu").read_text(encoding="utf-8") == "fn main() {\n  y := 1\n}\n"
    assert (src / "skip.py").read_text(encoding="utf-8") == "mut x := 1\n"
    assert (hidden / "c.xu").read_text(encoding="utf-8") == "fn main() {\n  mut z := 1\n}\n"


def test_apply_and_check_together_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "a.xu"
    target.write_text("fn main() {\n  mut x := 1\n}\n", encoding="utf-8")
    assert main(["--apply", "--check", str(target)]) == 2
    assert "mut x :=" in target.read_text(encoding="utf-8")


def _opaque_pieces(src: str) -> list[str]:
    return [tok.text for tok in lex(src) if tok.kind in ("STRING", "COMMENT")]


def test_real_parser_sources_stay_idempotent_and_do_not_gain_rejected_spellings() -> None:
    for rel in ("src/xu/parser/expressions.xu", "src/xu/parser/statements.xu", "src/xu/parser/declarations.xu"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        once = migrate_text(src, omit_read_borrows=True, simplify_reborrow=True)
        twice = migrate_text(once.text, omit_read_borrows=True, simplify_reborrow=True)
        assert twice.text == once.text
        assert twice.hits == []
        assert rejected_spellings(once.text) == []
        assert _opaque_pieces(once.text) == _opaque_pieces(src)


def test_dry_run_does_not_touch_real_source() -> None:
    path = ROOT / "src" / "xu" / "parser" / "statements.xu"
    before = path.read_bytes()
    assert main([str(path)]) == 0
    assert path.read_bytes() == before
