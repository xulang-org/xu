#!/usr/bin/env python3
"""Migrate Xu Phase C borrow and mutability spellings.

In-repo source rewrite. This is not a ``xu fix`` subcommand and it does not
deprecate the old spellings (the compiler keeps accepting both until a later
release). Run it on the files you want to change.

Default mappings, always applied:

  mut name := expr     ->  $name := expr
  mut &place           ->  $&place
  &mut Type            ->  $&Type
  &mut life Type       ->  $&life Type
  mut &*place          ->  &*place

Optional cleanups are off unless the flag is passed. They rewrite only when
the token context is unambiguous. Anything else is printed as a candidate and
left unchanged.

  --omit-read-borrows   ``&name`` -> ``name`` for a plain read borrow that is
                        a call argument, or the initializer of ``let name: &T``.
  --simplify-reborrow   ``&*name`` -> ``name`` when ``name`` is a known shared
                        borrow (``&T``, not ``$&T`` / ``&mut T`` / ``mut &``).

The rewriter never emits ``&$T``, ``$T``, ``$&*r``, ``*$&r``, or ``&$name :=``.
Strings, comments, ``$linux``-style compile tags, ``$$``, ``\\$``, and infix
``&`` / ``&&`` are not migration sites. A comment sitting between the tokens
of a mapping is kept. A newline splits a mapping, so it is not rewritten.

Idempotent: a second run with the same flags produces no further rewrites.
``--check`` exits 0 when that run would rewrite nothing. Candidates do not
fail ``--check``. Optional flags count toward ``--check`` only when passed.

Usage:
  python3 scripts/migrate_phase_c.py [PATH ...]
  python3 scripts/migrate_phase_c.py --apply [PATH ...]
  python3 scripts/migrate_phase_c.py --check [PATH ...]
  python3 scripts/migrate_phase_c.py --omit-read-borrows --simplify-reborrow PATH

PATH defaults to the current directory. Directories are walked for ``*.xu``
files. Hidden directories and build outputs are skipped. ``--apply`` and
``--check`` cannot be combined.

Out of scope here: editing the compiler, emitting deprecation warnings,
migrating the tree, and committing the Phase C design note.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "dist",
    "staging",
    "target",
    "bin",
    "build",
    "tmp",
    "temp",
    "vendor",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}

BUILTIN_TYPES = {
    "int",
    "bool",
    "string",
    "f64",
    "i32",
    "u32",
    "u8",
    "byte",
    "any",
    "chan",
    "map",
    "fn",
    "temp",
}

# ``fn (`` introduces a type or parameter list, not a value call.
CALL_EXCLUDED_CALLEES = {
    "fn",
    "if",
    "for",
    "while",
    "match",
    "xu",
    "select",
}

# A newline alone does not prove a borrow is the whole expression.
EXPR_CONTINUATIONS = {
    ".", "[", "(", "#", "+", "-", "*", "/", "%", "&", "|", "^",
    "&&", "||", "==", "!=", "<", ">", "<=", ">=", "<<", ">>",
}

_PLAIN_NAME = re.compile(r"^[a-z_][A-Za-z0-9_]*$")
_OPS = (
    "<->",
    "<<<",
    "...",
    ":=",
    "&&",
    "||",
    "==",
    "!=",
    "<=",
    ">=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "<<",
    ">>",
    "->",
    "<-",
    "..",
)


@dataclass
class Tok:
    kind: str
    text: str
    line: int
    col: int
    start: int

    @property
    def end(self) -> int:
        return self.start + len(self.text)


@dataclass
class Hit:
    line: int
    col: int
    kind: str
    old: str
    new: str


@dataclass
class Candidate:
    line: int
    col: int
    kind: str
    text: str
    reason: str


@dataclass
class MigrationResult:
    text: str
    hits: list[Hit] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)


@dataclass
class _Binding:
    name: str
    kind: str
    visible_from: int
    visible_to: int


@dataclass
class _Options:
    omit_read_borrows: bool = False
    simplify_reborrow: bool = False


def lex(src: str) -> list[Tok]:
    """Lex ``src`` the way the Xu scanner splits code, strings, and comments.

    Whitespace and comments stay as tokens so a rewrite can put the file back
    together without shifting unrelated bytes.
    """
    tokens: list[Tok] = []
    i = 0
    n = len(src)
    line = 1
    col = 1

    def bump() -> None:
        nonlocal i, line, col
        if src[i] == "\n":
            line += 1
            col = 1
        else:
            col += 1
        i += 1

    while i < n:
        start = i
        line0 = line
        col0 = col
        ch = src[i]

        if ch in " \t\r":
            while i < n and src[i] in " \t\r":
                bump()
            tokens.append(Tok("WS", src[start:i], line0, col0, start))
            continue
        if ch == "\n":
            bump()
            tokens.append(Tok("NL", src[start:i], line0, col0, start))
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            bump()
            bump()
            while i < n and src[i] != "\n":
                bump()
            tokens.append(Tok("COMMENT", src[start:i], line0, col0, start))
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            bump()
            bump()
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                bump()
            if i + 1 < n:
                bump()
                bump()
            elif i < n:
                bump()
            tokens.append(Tok("COMMENT", src[start:i], line0, col0, start))
            continue
        if ch == '"':
            bump()
            while i < n and src[i] != "\n":
                if src[i] == "\\":
                    bump()
                    if i < n and src[i] != "\n":
                        bump()
                    continue
                if src[i] == '"':
                    bump()
                    break
                bump()
            tokens.append(Tok("STRING", src[start:i], line0, col0, start))
            continue
        if ch == "`":
            bump()
            while i < n and src[i] != "`":
                bump()
            if i < n and src[i] == "`":
                bump()
            tokens.append(Tok("STRING", src[start:i], line0, col0, start))
            continue
        if ch == "\\" and i + 1 < n and src[i + 1] == "$":
            bump()
            bump()
            tokens.append(Tok("OP", src[start:i], line0, col0, start))
            continue
        if ch.isalpha() or ch == "_":
            bump()
            while i < n and (src[i].isalnum() or src[i] == "_"):
                bump()
            text = src[start:i]
            kind = "MUT" if text == "mut" else "IDENT"
            tokens.append(Tok(kind, text, line0, col0, start))
            continue
        if ch.isdigit():
            if src.startswith(("0x", "0X", "0b", "0B"), i):
                bump()
                bump()
                while i < n and (src[i].isalnum() or src[i] == "_"):
                    bump()
            else:
                while i < n and (src[i].isdigit() or src[i] == "_"):
                    bump()
                if i < n and src[i] == "." and not src.startswith("..", i):
                    bump()
                    while i < n and (src[i].isdigit() or src[i] == "_"):
                        bump()
            tokens.append(Tok("NUM", src[start:i], line0, col0, start))
            continue

        matched = ""
        for op in _OPS:
            if src.startswith(op, i):
                matched = op
                break
        if matched:
            for _ in matched:
                bump()
            kind = "COLONEQ" if matched == ":=" else "OP"
            tokens.append(Tok(kind, matched, line0, col0, start))
            continue
        bump()
        if ch == "$":
            kind = "DOLLAR"
        elif ch == "&":
            kind = "AMP"
        elif ch == "*":
            kind = "STAR"
        else:
            kind = "OP"
        tokens.append(Tok(kind, src[start:i], line0, col0, start))
    return tokens


def rejected_spellings(src: str) -> list[str]:
    """Return rejected Phase C token sequences outside strings and comments.

    ``$&$&`` is two writable ref types and is not reported. ``&$`` is reported
    only when ``&`` is not already the second half of ``$&``.
    """
    significant = [tok for tok in lex(src) if tok.kind not in ("WS", "NL", "COMMENT", "STRING")]
    found: list[str] = []
    for i, tok in enumerate(significant):
        nxt = significant[i + 1] if i + 1 < len(significant) else None
        nxt2 = significant[i + 2] if i + 2 < len(significant) else None
        nxt3 = significant[i + 3] if i + 3 < len(significant) else None
        prev = significant[i - 1] if i > 0 else None
        if tok.kind == "AMP" and nxt is not None and nxt.kind == "DOLLAR" and (prev is None or prev.kind != "DOLLAR"):
            found.append("&$")
        if tok.kind == "DOLLAR" and nxt is not None and nxt.kind == "AMP" and nxt2 is not None and nxt2.kind == "STAR":
            found.append("$&*")
        if tok.kind == "STAR" and nxt is not None and nxt.kind == "DOLLAR" and nxt2 is not None and nxt2.kind == "AMP":
            found.append("*$&")
        if (
            tok.kind == "AMP"
            and (prev is None or prev.kind != "DOLLAR")
            and nxt is not None
            and nxt.kind == "DOLLAR"
            and nxt2 is not None
            and nxt2.kind == "IDENT"
            and nxt3 is not None
            and nxt3.kind == "COLONEQ"
        ):
            found.append("&$:=")
    return found


def migrate_text(
    src: str,
    *,
    omit_read_borrows: bool = False,
    simplify_reborrow: bool = False,
) -> MigrationResult:
    """Rewrite Phase C spellings in one source buffer."""
    tokens = lex(src)
    options = _Options(omit_read_borrows=omit_read_borrows, simplify_reborrow=simplify_reborrow)
    bindings = _collect_bindings(tokens)
    text, hits, candidates = _rewrite(src, tokens, options, bindings)
    return MigrationResult(text, hits, candidates)


def _rewrite(
    src: str,
    tokens: list[Tok],
    options: _Options,
    bindings: dict[str, list[_Binding]],
) -> tuple[str, list[Hit], list[Candidate]]:
    out: list[str] = []
    hits: list[Hit] = []
    candidates: list[Candidate] = []
    n = len(tokens)
    i = 0
    while i < n:
        tok = tokens[i]
        if tok.kind == "MUT":
            nxt = _match_mut(src, tokens, i, options, bindings, out, hits, candidates)
            if nxt is not None:
                i = nxt
                continue
        elif tok.kind == "AMP":
            nxt = _match_amp(src, tokens, i, options, bindings, out, hits, candidates)
            if nxt is not None:
                i = nxt
                continue
        out.append(tok.text)
        i += 1
    return "".join(out), hits, candidates


def _match_mut(
    src: str,
    tokens: list[Tok],
    i: int,
    options: _Options,
    bindings: dict[str, list[_Binding]],
    out: list[str],
    hits: list[Hit],
    candidates: list[Candidate],
) -> int | None:
    prev = _prev_same_line(tokens, i)
    if prev is not None and tokens[prev].end == tokens[i].start and tokens[prev].text in ("$", "\\$"):
        return None
    amp = _match_kind(tokens, i, "AMP")
    if amp is not None:
        star = _match_kind(tokens, amp[0], "STAR")
        if star is not None:
            return _rewrite_mut_reborrow(src, tokens, i, amp, star, options, bindings, out, hits, candidates)
        if _match_kind(tokens, amp[0], "MUT") is None:
            reason = _writable_prefix_reason(tokens, i, _next_code(tokens, amp[0]))
            if reason is not None:
                return _keep_mapping_candidate(src, tokens, i, amp[0], "mut-borrow", reason, out, candidates)
            return _rewrite_mut_borrow(src, tokens, i, amp, out, hits)
        return None
    name = _match_kind(tokens, i, "IDENT")
    if name is None:
        return None
    coloneq = _match_kind(tokens, name[0], "COLONEQ")
    if coloneq is None:
        return None
    prev = _prev_cross(tokens, i)
    if prev is not None and tokens[prev].kind in ("AMP", "STAR", "DOLLAR"):
        return _keep_mapping_candidate(src, tokens, i, coloneq[0], "mut-bind", "ambiguous marker prefix", out, candidates)
    _emit_comments(out, name[1])
    out.append("$")
    out.append(tokens[name[0]].text)
    name_end = tokens[name[0]].end
    colon_end = tokens[coloneq[0]].end
    out.append(src[name_end:colon_end])
    old = _compact(src[tokens[i].start:colon_end])
    new = "$" + tokens[name[0]].text + " :="
    hits.append(Hit(tokens[i].line, tokens[i].col, "mut-bind", old, new))
    return coloneq[0] + 1


def _rewrite_mut_borrow(
    src: str,
    tokens: list[Tok],
    mut_i: int,
    amp: tuple[int, list[str]],
    out: list[str],
    hits: list[Hit],
) -> int:
    amp_i, comments = amp
    _emit_comments(out, comments)
    out.append("$&")
    j = amp_i + 1
    n = len(tokens)
    while j < n and tokens[j].kind == "WS":
        j += 1
    if j < n and tokens[j].kind == "AMP" and _match_kind(tokens, j, "MUT") is None:
        out.append(" ")  # Keep two borrow markers from lexing as &&.
    old = _compact(src[tokens[mut_i].start:tokens[amp_i].end])
    hits.append(Hit(tokens[mut_i].line, tokens[mut_i].col, "mut-borrow", old, "$&"))
    return j


def _rewrite_mut_reborrow(
    src: str,
    tokens: list[Tok],
    mut_i: int,
    amp: tuple[int, list[str]],
    star: tuple[int, list[str]],
    options: _Options,
    bindings: dict[str, list[_Binding]],
    out: list[str],
    hits: list[Hit],
    candidates: list[Candidate],
) -> int:
    amp_i, comments_before_amp = amp
    star_i, comments_before_star = star
    place = _match_kind(tokens, star_i, "IDENT")
    simplify_to: int | None = None
    if options.simplify_reborrow and place is not None and _name_shape_reason(tokens, place[0]) is None:
        if _lookup(bindings, tokens[place[0]].text, place[0]) == "shared":
            simplify_to = place[0]
    if simplify_to is not None and place is not None:
        _emit_comments(out, comments_before_amp + comments_before_star + place[1])
        out.append(tokens[simplify_to].text)
        old = _compact(src[tokens[mut_i].start:tokens[simplify_to].end])
        hits.append(Hit(tokens[mut_i].line, tokens[mut_i].col, "simplify-reborrow", old, tokens[simplify_to].text))
        return simplify_to + 1

    _emit_comments(out, comments_before_amp)
    out.append(src[tokens[amp_i].start:tokens[star_i].end])
    old = _compact(src[tokens[mut_i].start:tokens[star_i].end])
    hits.append(Hit(tokens[mut_i].line, tokens[mut_i].col, "mut-reborrow", old, "&*"))
    if options.simplify_reborrow:
        _note_reborrow_candidate(tokens, amp_i, star_i, bindings, candidates)
    return star_i + 1


def _match_amp(
    src: str,
    tokens: list[Tok],
    i: int,
    options: _Options,
    bindings: dict[str, list[_Binding]],
    out: list[str],
    hits: list[Hit],
    candidates: list[Candidate],
) -> int | None:
    prev = _prev_same_line(tokens, i)
    if prev is not None and tokens[prev].kind == "DOLLAR":
        return None
    mut = _match_kind(tokens, i, "MUT")
    if mut is not None:
        target = _next_code(tokens, mut[0])
        reason = _writable_prefix_reason(tokens, i, target)
        if target is not None and _match_kind(tokens, target, "COLONEQ") is not None:
            reason = "borrow marker before a binding declaration"
        if reason is not None:
            return _keep_mapping_candidate(src, tokens, i, mut[0], "mut-type", reason, out, candidates)
        return _rewrite_mut_type(src, tokens, i, mut, out, hits)
    star = _match_kind(tokens, i, "STAR")
    if star is not None:
        if not options.simplify_reborrow:
            return None
        if _is_infix_amp(tokens, i):
            return None
        return _rewrite_or_note_reborrow(src, tokens, i, star, bindings, out, hits, candidates)
    if not options.omit_read_borrows:
        return None
    if _is_infix_amp(tokens, i) or _amp_is_type_context(tokens, i):
        return None
    return _rewrite_or_note_read_borrow(src, tokens, i, out, hits, candidates)


def _writable_prefix_reason(tokens: list[Tok], start: int, target: int | None) -> str | None:
    prev = _prev_cross(tokens, start)
    if prev is not None and tokens[prev].kind in ("AMP", "STAR", "DOLLAR"):
        return "rewriting would create a rejected marker sequence"
    if target is None:
        return "operand is missing or crosses a newline"
    if tokens[target].kind == "STAR":
        return "rewriting would create $&*"
    return None


def _keep_mapping_candidate(
    src: str, tokens: list[Tok], start: int, end: int, kind: str,
    reason: str, out: list[str], candidates: list[Candidate],
) -> int:
    text = src[tokens[start].start:tokens[end].end]
    out.append(text)
    _add_candidate(tokens, start, kind, _compact(text), reason, candidates)
    return end + 1


def _rewrite_mut_type(
    src: str,
    tokens: list[Tok],
    amp_i: int,
    mut: tuple[int, list[str]],
    out: list[str],
    hits: list[Hit],
) -> int:
    mut_i, comments = mut
    _emit_comments(out, comments)
    out.append("$&")
    j = mut_i + 1
    n = len(tokens)
    while j < n and tokens[j].kind == "WS":
        j += 1
    if j < n and tokens[j].kind == "AMP" and _match_kind(tokens, j, "MUT") is None:
        out.append(" ")
    old = _compact(src[tokens[amp_i].start:tokens[mut_i].end])
    hits.append(Hit(tokens[amp_i].line, tokens[amp_i].col, "mut-type", old, "$&"))
    return j


def _rewrite_or_note_reborrow(
    src: str,
    tokens: list[Tok],
    amp_i: int,
    star: tuple[int, list[str]],
    bindings: dict[str, list[_Binding]],
    out: list[str],
    hits: list[Hit],
    candidates: list[Candidate],
) -> int | None:
    star_i, star_comments = star
    place = _match_kind(tokens, star_i, "IDENT")
    if place is None or _name_shape_reason(tokens, place[0]) is not None or _lookup(bindings, tokens[place[0]].text, place[0]) != "shared":
        _note_reborrow_candidate(tokens, amp_i, star_i, bindings, candidates)
        return None
    _emit_comments(out, star_comments + place[1])
    out.append(tokens[place[0]].text)
    old = _compact(src[tokens[amp_i].start:tokens[place[0]].end])
    hits.append(Hit(tokens[amp_i].line, tokens[amp_i].col, "simplify-reborrow", old, tokens[place[0]].text))
    return place[0] + 1


def _note_reborrow_candidate(
    tokens: list[Tok],
    amp_i: int,
    star_i: int,
    bindings: dict[str, list[_Binding]],
    candidates: list[Candidate],
) -> None:
    place = _match_kind(tokens, star_i, "IDENT")
    if place is None:
        reason = "not a plain local or name"
        text = "&*"
    else:
        shape = _name_shape_reason(tokens, place[0])
        if shape is not None:
            reason = shape
        else:
            kind = _lookup(bindings, tokens[place[0]].text, place[0])
            if kind == "writable":
                reason = "referent is a writable borrow"
            else:
                reason = "referent is not a known shared borrow"
        text = "&*" + tokens[place[0]].text
    tok = tokens[amp_i]
    candidates.append(Candidate(tok.line, tok.col, "simplify-reborrow", text, reason))


def _rewrite_or_note_read_borrow(
    src: str,
    tokens: list[Tok],
    amp_i: int,
    out: list[str],
    hits: list[Hit],
    candidates: list[Candidate],
) -> int | None:
    name = _match_kind(tokens, amp_i, "IDENT")
    if name is None:
        opener = _match_kind(tokens, amp_i, "OP")
        if opener is not None and tokens[opener[0]].text == "(":
            _add_candidate(tokens, amp_i, "omit-read-borrow", "&(...)", "not a plain local or name", candidates)
        return None
    name_i, comments = name
    shape = _name_shape_reason(tokens, name_i)
    preview = "&" + tokens[name_i].text
    if shape is not None:
        _add_candidate(tokens, amp_i, "omit-read-borrow", preview, shape, candidates)
        return None
    if not _is_safe_read_borrow(tokens, amp_i):
        _add_candidate(tokens, amp_i, "omit-read-borrow", preview, _unsafe_read_reason(tokens, amp_i), candidates)
        return None
    post = _next_code(tokens, name_i)
    prev = _prev_cross(tokens, amp_i)
    is_initializer = prev is not None and tokens[prev].text == "="
    end_markers = (";", "}") if is_initializer else (",", ")")
    following = _next_cross(tokens, name_i)
    if not is_initializer or following is not None and tokens[following].text in EXPR_CONTINUATIONS:
        post = following
    if post is not None and tokens[post].text not in end_markers:
        _add_candidate(tokens, amp_i, "omit-read-borrow", preview, "borrow is part of a larger expression", candidates)
        return None
    _emit_comments(out, comments)
    out.append(tokens[name_i].text)
    old = _compact(src[tokens[amp_i].start:tokens[name_i].end])
    hits.append(Hit(tokens[amp_i].line, tokens[amp_i].col, "omit-read-borrow", old, tokens[name_i].text))
    return name_i + 1


def _add_candidate(
    tokens: list[Tok],
    i: int,
    kind: str,
    text: str,
    reason: str,
    candidates: list[Candidate],
) -> None:
    tok = tokens[i]
    candidates.append(Candidate(tok.line, tok.col, kind, text, reason))


def _is_safe_read_borrow(tokens: list[Tok], amp_i: int) -> bool:
    prev = _prev_cross(tokens, amp_i)
    if prev is None:
        return False
    text = tokens[prev].text
    if text == "(":
        return _paren_is_call(tokens, prev)
    if text == ",":
        opener = _matching_open(tokens, prev)
        return opener is not None and tokens[opener].text == "(" and _paren_is_call(tokens, opener)
    if text == "=":
        return _equals_is_shared_let(tokens, prev)
    return False


def _unsafe_read_reason(tokens: list[Tok], amp_i: int) -> str:
    prev = _prev_cross(tokens, amp_i)
    if prev is not None and tokens[prev].kind == "COLONEQ":
        return "binding initializer; omitting & would copy or move"
    if prev is not None and tokens[prev].text == "=":
        return "assignment is not a known shared let initializer"
    return "not a call argument or shared let initializer"


def _paren_is_call(tokens: list[Tok], open_i: int) -> bool:
    before = _prev_cross(tokens, open_i)
    if before is None or tokens[before].kind != "IDENT":
        return False
    return tokens[before].text not in CALL_EXCLUDED_CALLEES


def _amp_is_type_context(tokens: list[Tok], amp_i: int) -> bool:
    prev = _prev_cross(tokens, amp_i)
    if prev is None:
        return False
    if tokens[prev].text == ":" and _colon_is_let_type(tokens, prev):
        return True
    if tokens[prev].text == "(" and _introduced_by_fn(tokens, prev):
        return True
    if tokens[prev].text == ",":
        opener = _matching_open(tokens, prev)
        if opener is not None and tokens[opener].text == "(" and _introduced_by_fn(tokens, opener):
            return True
    return False


def _introduced_by_fn(tokens: list[Tok], open_i: int) -> bool:
    before = _prev_cross(tokens, open_i)
    return before is not None and tokens[before].kind == "IDENT" and tokens[before].text == "fn"


def _colon_is_let_type(tokens: list[Tok], colon_i: int) -> bool:
    j = colon_i - 1
    while j >= 0:
        tok = tokens[j]
        if tok.kind in ("WS", "COMMENT"):
            j -= 1
            continue
        if tok.kind == "NL":
            return False
        if tok.kind == "IDENT":
            if tok.text == "let":
                return True
            if tok.text in ("fn", "struct", "enum", "if", "for", "while", "match"):
                return False
            j -= 1
            continue
        if tok.kind == "DOLLAR":
            j -= 1
            continue
        return False
    return False


def _equals_is_shared_let(tokens: list[Tok], eq_i: int) -> bool:
    j = eq_i - 1
    colon: int | None = None
    while j >= 0:
        tok = tokens[j]
        if tok.kind in ("WS", "COMMENT"):
            j -= 1
            continue
        if tok.kind == "NL" or tok.kind == "COLONEQ" or tok.text in ("{", "}", ";"):
            return False
        if tok.text == ":":
            colon = j
            break
        j -= 1
    if colon is None or not _colon_is_let_type(tokens, colon):
        return False
    head = _next_code(tokens, colon)
    if head is None:
        return False
    return _ref_kind_at(tokens, head) == "shared"


def _is_infix_amp(tokens: list[Tok], amp_i: int) -> bool:
    prev = _prev_cross(tokens, amp_i)
    if prev is None:
        return False
    return _is_operand_end(tokens[prev])


def _is_operand_end(tok: Tok) -> bool:
    if tok.kind in ("IDENT", "NUM", "STRING", "MUT"):
        return True
    return tok.kind == "OP" and tok.text in (")", "]", "}")


def _name_shape_reason(tokens: list[Tok], name_i: int) -> str | None:
    tok = tokens[name_i]
    if tok.kind != "IDENT":
        return "not a plain local or name"
    if tok.text in BUILTIN_TYPES:
        return "builtin type name, not a local"
    if _PLAIN_NAME.fullmatch(tok.text) is None:
        return "name may be a type"
    post = _next_code(tokens, name_i)
    if post is None:
        return None
    if tokens[post].kind == "IDENT":
        return "possible lifetime type"
    if tokens[post].text in (".", "[", "(", "#"):
        return "not a plain local or name"
    return None


def _match_kind(tokens: list[Tok], i: int, kind: str) -> tuple[int, list[str]] | None:
    """Find ``kind`` after ``i``, skipping spaces. Newlines break the match.

    Comments in between are returned so the caller can keep them. ``i`` itself
    is not required to have ``kind``.
    """
    j = i + 1
    n = len(tokens)
    comments: list[str] = []
    while j < n and tokens[j].kind in ("WS", "COMMENT"):
        if "\n" in tokens[j].text:
            return None
        if tokens[j].kind == "COMMENT":
            comments.append(tokens[j].text)
        j += 1
    if j >= n or tokens[j].kind == "NL" or tokens[j].kind != kind:
        return None
    return j, comments


def _next_code(tokens: list[Tok], i: int) -> int | None:
    j = i + 1
    n = len(tokens)
    while j < n and tokens[j].kind in ("WS", "COMMENT"):
        if "\n" in tokens[j].text:
            return None
        j += 1
    if j >= n or tokens[j].kind == "NL":
        return None
    return j


def _prev_same_line(tokens: list[Tok], i: int) -> int | None:
    j = i - 1
    while j >= 0 and tokens[j].kind in ("WS", "COMMENT"):
        if "\n" in tokens[j].text:
            return None
        j -= 1
    if j < 0 or tokens[j].kind == "NL":
        return None
    return j


def _prev_cross(tokens: list[Tok], i: int) -> int | None:
    j = i - 1
    while j >= 0 and tokens[j].kind in ("WS", "COMMENT", "NL"):
        j -= 1
    if j < 0:
        return None
    return j


def _next_cross(tokens: list[Tok], i: int) -> int | None:
    j = i + 1
    n = len(tokens)
    while j < n and tokens[j].kind in ("WS", "COMMENT", "NL"):
        j += 1
    if j >= n:
        return None
    return j


def _emit_comments(out: list[str], comments: list[str]) -> None:
    if not comments:
        return
    text = " ".join(comments)
    out.append(text)
    if not text.endswith((" ", "\t", "\n")):
        out.append(" ")


def _compact(text: str) -> str:
    return " ".join(text.split())


def _lookup(bindings: dict[str, list[_Binding]], name: str, use_i: int) -> str | None:
    best: _Binding | None = None
    for binding in bindings.get(name, ()):
        if binding.visible_from < use_i < binding.visible_to and (best is None or binding.visible_from >= best.visible_from):
            best = binding
    if best is None:
        return None
    return best.kind


def _collect_bindings(tokens: list[Tok]) -> dict[str, list[_Binding]]:
    end_of_open, active_inside = _brace_maps(tokens)
    found: list[_Binding] = []
    n = len(tokens)

    def scope_end(idx: int) -> int:
        opener = active_inside[idx]
        if opener < 0:
            return n
        return end_of_open.get(opener, n)

    def next_nl(idx: int) -> int:
        j = idx + 1
        while j < n and tokens[j].kind != "NL":
            j += 1
        return j

    def add(name: str, kind: str, visible_from: int, visible_to: int) -> None:
        if not name or name in BUILTIN_TYPES or name in ("let", "fn", "mut"):
            return
        found.append(_Binding(name, kind, visible_from, visible_to))

    for i, tok in enumerate(tokens):
        if tok.kind == "COLONEQ":
            name_i = _prev_code_any(tokens, i)
            if name_i is None or tokens[name_i].kind != "IDENT":
                continue
            init = _next_code(tokens, i)
            # Until the declaration ends, do not fall back to an outer name.
            add(tokens[name_i].text, "unknown", name_i, next_nl(i))
            add(tokens[name_i].text, _classify_init(tokens, init), next_nl(i), scope_end(name_i))
            continue
        if tok.kind == "IDENT" and tok.text == "let":
            name_i = _next_code(tokens, i)
            if name_i is not None and tokens[name_i].kind == "DOLLAR":
                name_i = _next_code(tokens, name_i)
            if name_i is None or tokens[name_i].kind != "IDENT":
                continue
            colon = _next_code(tokens, name_i)
            if colon is None or tokens[colon].text != ":":
                continue
            head = _next_code(tokens, colon)
            kind = _ref_kind_at(tokens, head) if head is not None else "unknown"
            add(tokens[name_i].text, "unknown", name_i, next_nl(i))
            add(tokens[name_i].text, kind, next_nl(i), scope_end(name_i))
            continue
        if tok.kind == "IDENT" and tok.text == "for":
            name_i = _next_cross(tokens, i)
            names: list[str] = []
            while name_i is not None and tokens[name_i].kind == "IDENT":
                names.append(tokens[name_i].text)
                after = _next_cross(tokens, name_i)
                if after is not None and tokens[after].text == ",":
                    name_i = _next_cross(tokens, after)
                    continue
                if after is not None and tokens[after].text == "in":
                    # No type proof for loop variables. Keep this barrier to
                    # the enclosing scope end rather than guess the loop body.
                    for name in names:
                        add(name, "unknown", i, scope_end(i))
                break
            continue
        if tok.kind == "IDENT" and tok.text == "fn":
            _record_fn_params(tokens, i, end_of_open, add)

    by_name: dict[str, list[_Binding]] = {}
    for binding in found:
        by_name.setdefault(binding.name, []).append(binding)
    return by_name


def _prev_code_any(tokens: list[Tok], i: int) -> int | None:
    j = i - 1
    while j >= 0 and tokens[j].kind in ("WS", "COMMENT"):
        j -= 1
    if j < 0 or tokens[j].kind == "NL":
        return None
    return j


def _classify_init(tokens: list[Tok], init: int | None) -> str:
    if init is None:
        return "unknown"
    tok = tokens[init]
    if tok.kind == "MUT":
        nxt = _next_code(tokens, init)
        if nxt is not None and tokens[nxt].kind == "AMP":
            return "writable"
        return "unknown"
    if tok.kind == "DOLLAR":
        nxt = _next_code(tokens, init)
        if nxt is not None and tokens[nxt].kind == "AMP":
            return "writable"
        return "unknown"
    if tok.kind == "AMP":
        nxt = _next_code(tokens, init)
        if nxt is not None and _name_shape_reason(tokens, nxt) is None:
            end = _next_code(tokens, nxt)
            following = _next_cross(tokens, nxt)
            continues = following is not None and tokens[following].text in EXPR_CONTINUATIONS
            if not continues and (end is None or tokens[end].text in (";", "}")):
                return "shared"
        return "unknown"
    return "unknown"


def _ref_kind_at(tokens: list[Tok], idx: int) -> str:
    tok = tokens[idx]
    if tok.kind == "DOLLAR":
        nxt = _next_code(tokens, idx)
        if nxt is not None and tokens[nxt].kind == "AMP":
            return "writable"
        return "unknown"
    if tok.kind == "AMP":
        nxt = _next_code(tokens, idx)
        if nxt is not None and tokens[nxt].kind == "MUT":
            return "writable"
        return "shared"
    return "unknown"


def _record_fn_params(tokens: list[Tok], fn_i: int, end_of_open: dict[int, int], add) -> None:
    nxt = _next_cross(tokens, fn_i)
    if nxt is None:
        return
    params: list[tuple[str, str]]
    close: int | None
    if tokens[nxt].text == "(":
        first, first_close = _parse_param_list(tokens, nxt)
        after = _next_cross(tokens, first_close) if first_close is not None else None
        if after is not None and tokens[after].kind == "IDENT" and _looks_like_method_name(tokens, after):
            name_after = _next_cross(tokens, after)
            if name_after is not None and tokens[name_after].text == "#":
                name_after = _skip_until_paren(tokens, name_after)
            if name_after is None or tokens[name_after].text != "(":
                params = first
                close = first_close
            else:
                rest, rest_close = _parse_param_list(tokens, name_after)
                params = first + rest
                close = rest_close
        else:
            params = first
            close = first_close
    elif tokens[nxt].kind == "IDENT":
        cursor = _next_cross(tokens, nxt)
        if cursor is not None and tokens[cursor].text == "#":
            cursor = _skip_until_paren(tokens, cursor)
        if cursor is None or tokens[cursor].text != "(":
            return
        params, close = _parse_param_list(tokens, cursor)
    else:
        return
    if close is None:
        return
    body = _find_body_brace(tokens, close)
    if body is None:
        return
    visible_to = end_of_open.get(body, len(tokens))
    for name, kind in params:
        add(name, kind, body, visible_to)


def _looks_like_method_name(tokens: list[Tok], name_i: int) -> bool:
    if tokens[name_i].text in BUILTIN_TYPES:
        return False
    nxt = _next_cross(tokens, name_i)
    if nxt is not None and tokens[nxt].text == "#":
        nxt = _skip_until_paren(tokens, nxt)
    return nxt is not None and tokens[nxt].text == "("


def _skip_until_paren(tokens: list[Tok], hash_i: int) -> int | None:
    j = hash_i + 1
    n = len(tokens)
    while j < n:
        if tokens[j].text == "(" and tokens[j].kind == "OP":
            return j
        j += 1
    return None


def _find_body_brace(tokens: list[Tok], close_i: int) -> int | None:
    nxt = _next_cross(tokens, close_i)
    if nxt is None:
        return None
    if tokens[nxt].text == "{":
        return nxt
    after = _skip_type_from(tokens, nxt)
    if after is not None and tokens[after].text == "{":
        return after
    return None


def _parse_param_list(tokens: list[Tok], open_i: int) -> tuple[list[tuple[str, str]], int | None]:
    params: list[tuple[str, str]] = []
    j = _next_cross(tokens, open_i)
    guard = 0
    while j is not None and guard < len(tokens) + 1:
        guard += 1
        if tokens[j].text == ")":
            return params, j
        if tokens[j].kind != "IDENT":
            end = _skip_type_from(tokens, j)
            if end is None or end <= j:
                return params, j
            if tokens[end].text == ",":
                j = _next_cross(tokens, end)
                continue
            if tokens[end].text == ")":
                return params, end
            return params, end
        name = tokens[j].text
        k = _next_cross(tokens, j)
        if k is not None and tokens[k].text in ("#", "@"):
            k2 = _next_cross(tokens, k)
            if k2 is not None and tokens[k2].text in (",", ")"):
                params.append((name, "unknown"))
                if tokens[k2].text == ")":
                    return params, k2
                j = _next_cross(tokens, k2)
                continue
            k = k2
        if k is not None and tokens[k].text == "<->":
            k = _next_cross(tokens, k)
        if k is None:
            return params, None
        if tokens[k].text in (",", ")"):
            params.append((name, "unknown"))
            if tokens[k].text == ")":
                return params, k
            j = _next_cross(tokens, k)
            continue
        kind = _ref_kind_at(tokens, k) if tokens[k].kind in ("AMP", "DOLLAR") else "unknown"
        end = _skip_type_from(tokens, k)
        params.append((name, kind))
        if end is None:
            return params, None
        if tokens[end].text == ")":
            return params, end
        if tokens[end].text == ",":
            j = _next_cross(tokens, end)
            continue
        j = end
    return params, j


def _skip_type_from(tokens: list[Tok], i: int) -> int | None:
    """Return the token that ends a type starting at ``i`` (``{``, ``,``, ``)``, ``}``)."""
    if tokens[i].text == "{":
        return i
    depth_paren = 0
    depth_brack = 0
    depth_brace = 0
    j = i
    n = len(tokens)
    while j < n:
        tok = tokens[j]
        if tok.kind in ("WS", "COMMENT", "NL"):
            j += 1
            continue
        text = tok.text
        if text == "(":
            depth_paren += 1
            j += 1
            continue
        if text == "[":
            depth_brack += 1
            j += 1
            continue
        if text == "{":
            if depth_paren == depth_brack == depth_brace == 0:
                return j
            depth_brace += 1
            j += 1
            continue
        if text == ")":
            if depth_paren == depth_brack == depth_brace == 0:
                return j
            depth_paren = max(0, depth_paren - 1)
            j += 1
            continue
        if text == "]":
            depth_brack = max(0, depth_brack - 1)
            j += 1
            continue
        if text == "}":
            if depth_paren == depth_brack == depth_brace == 0:
                return j
            depth_brace = max(0, depth_brace - 1)
            j += 1
            continue
        if text == "," and depth_paren == depth_brack == depth_brace == 0:
            return j
        j += 1
    return None


def _matching_open(tokens: list[Tok], close_like: int) -> int | None:
    depth_paren = 0
    depth_brack = 0
    depth_brace = 0
    j = close_like
    while j >= 0:
        tok = tokens[j]
        text = tok.text
        if text == ")":
            depth_paren += 1
        elif text == "(":
            if depth_paren == depth_brack == depth_brace == 0:
                return j
            depth_paren = max(0, depth_paren - 1)
        elif text == "]":
            depth_brack += 1
        elif text == "[":
            if depth_paren == depth_brack == depth_brace == 0:
                return j
            depth_brack = max(0, depth_brack - 1)
        elif text == "}":
            depth_brace += 1
        elif text == "{":
            if depth_paren == depth_brack == depth_brace == 0:
                return j
            depth_brace = max(0, depth_brace - 1)
        j -= 1
    return None


def _brace_maps(tokens: list[Tok]) -> tuple[dict[int, int], list[int]]:
    end_of_open: dict[int, int] = {}
    active_inside = [-1] * len(tokens)
    stack: list[int] = []
    for i, tok in enumerate(tokens):
        if tok.kind == "OP" and tok.text == "}" and stack:
            end_of_open[stack.pop()] = i
        active_inside[i] = stack[-1] if stack else -1
        if tok.kind == "OP" and tok.text == "{":
            stack.append(i)
    return end_of_open, active_inside


def _iter_xu_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.suffix == ".xu":
                files.append(path)
            continue
        if not path.is_dir():
            continue
        for root, dirs, names in os.walk(path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for name in names:
                if name.endswith(".xu"):
                    files.append(Path(root) / name)
    unique = sorted({item.resolve() for item in files})
    return unique


def _format_hit(path: Path | None, hit: Hit) -> str:
    where = f"{hit.line}:{hit.col}" if path is None else f"{path}:{hit.line}:{hit.col}"
    return f"{where}: {hit.kind}: {hit.old} -> {hit.new}"


def _format_candidate(path: Path | None, item: Candidate) -> str:
    where = f"{item.line}:{item.col}" if path is None else f"{path}:{item.line}:{item.col}"
    return f"{where}: candidate {item.kind}: {item.text} ({item.reason})"


def _read_text(path: Path) -> str:
    # newline="" keeps CR LF pairs intact. Path.read_text did not grow a
    # newline argument until 3.13, and this repo still runs on older Pythons.
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate Xu Phase C mut and borrow spellings.")
    parser.add_argument("paths", nargs="*", type=Path, help="Files or directories to scan (default: .)")
    parser.add_argument("--apply", action="store_true", help="Write rewrites back to .xu files")
    parser.add_argument("--check", action="store_true", help="Exit 0 when no selected spelling remains")
    parser.add_argument("--omit-read-borrows", action="store_true", help="Drop safe plain &name read borrows")
    parser.add_argument("--simplify-reborrow", action="store_true", help="Simplify safe shared &*name reborrows to name")
    args = parser.parse_args(argv)
    if args.apply and args.check:
        print("error: --apply and --check are mutually exclusive", file=sys.stderr)
        return 2
    raw_paths = list(args.paths) or [Path(".")]
    missing = [str(path) for path in raw_paths if not path.exists()]
    if missing:
        print("error: not found: " + ", ".join(missing), file=sys.stderr)
        return 2
    files = _iter_xu_files(raw_paths)
    hit_count = 0
    candidate_count = 0
    changed_files = 0
    for path in files:
        original = _read_text(path)
        result = migrate_text(
            original,
            omit_read_borrows=args.omit_read_borrows,
            simplify_reborrow=args.simplify_reborrow,
        )
        for hit in result.hits:
            print(_format_hit(path, hit))
        for item in result.candidates:
            print(_format_candidate(path, item))
        hit_count += len(result.hits)
        candidate_count += len(result.candidates)
        if result.text != original:
            changed_files += 1
            if args.apply:
                _write_text(path, result.text)
    if args.check:
        print(f"check: {hit_count} remaining rewrite(s), {candidate_count} candidate(s)")
        return 1 if hit_count else 0
    if args.apply:
        print(f"applied: {hit_count} rewrite(s), {candidate_count} candidate(s) in {changed_files} file(s)")
        return 0
    print(f"dry-run: {hit_count} rewrite(s), {candidate_count} candidate(s) in {changed_files} file(s); no files written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
