#!/usr/bin/env python3
"""
Migrate all non-UPPER_SNAKE_CASE const declarations and references in the Xu codebase.
"""

import os
import re
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
TESTS_DIR = os.path.join(REPO_ROOT, "tests")

UPPER_SNAKE = re.compile(r"^_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
CONST_DECL = re.compile(r"^(\s*(?:pub\s+)?const\s+)([a-zA-Z_][a-zA-Z0-9_]*)(\s*=.*)$")

def to_upper_snake(name: str) -> str:
    if name == "_":
        return "_"
    return name.upper()

def get_pkg_info(filepath: str, base_dir: str):
    rel = os.path.relpath(filepath, base_dir)
    pkg_rel = os.path.dirname(rel)
    pkg_short = os.path.basename(pkg_rel) if pkg_rel and pkg_rel != "." else "main"
    return pkg_rel, pkg_short

def scan_consts(extra_dirs=None):
    pkg_consts = defaultdict(dict)
    global_pub = {} # (pkg_short, old_name) -> (new_name, pkg_rel)

    dirs_to_scan = [SRC_DIR]
    if extra_dirs:
        dirs_to_scan.extend(extra_dirs)

    for scan_d in dirs_to_scan:
        for root, dirs, files in os.walk(scan_d):
            if any(part in root for part in [".git", "dist", "staging", "target"]):
                continue
            for f in files:
                if f.endswith(".xu"):
                    fpath = os.path.join(root, f)
                    pkg_rel, pkg_short = get_pkg_info(fpath, scan_d)
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fp:
                        for idx, line in enumerate(fp, 1):
                            code = line.split("//")[0]
                            m = CONST_DECL.match(code)
                            if m:
                                prefix, name, suffix = m.groups()
                                if not UPPER_SNAKE.match(name):
                                    is_pub = "pub const" in prefix
                                    new_name = to_upper_snake(name)
                                    pkg_consts[pkg_rel][name] = {
                                        "new_name": new_name,
                                        "is_pub": is_pub,
                                        "file": fpath,
                                        "line": idx,
                                        "pkg_short": pkg_short
                                    }
                                    if is_pub:
                                        global_pub[(pkg_short, name)] = (new_name, pkg_rel)
    return pkg_consts, global_pub

TOKEN_SPEC = [
    ("COMMENT", r"//[^\n]*"),
    ("STRING", r'"(?:\\.|[^"\\])*"|`[^`]*`'),
    ("CHAR", r"'(?:\\.|[^'\\])*'"),
    ("COLONEQ", r":="),
    ("COLON", r":"),
    ("DOT", r"\."),
    ("IDENT", r"[a-zA-Z_][a-zA-Z0-9_]*"),
    ("NUMBER", r"0x[0-9a-fA-F]+|\d+(?:\.\d+)?"),
    ("WS", r"[ \t]+"),
    ("NEWLINE", r"\n"),
    ("OTHER", r"[^\s\w]"),
]
TOKEN_RE = re.compile("|".join(f"(?P<{pair[0]}>{pair[1]})" for pair in TOKEN_SPEC))

def tokenize_line(line: str):
    tokens = []
    for m in TOKEN_RE.finditer(line):
        tokens.append((m.lastgroup, m.group()))
    return tokens

def process_file_content(filepath: str, content: str, pkg_rel: str, pkg_consts: dict, global_pub: dict):
    local_dict = pkg_consts.get(pkg_rel, {})
    lines = content.split("\n")
    new_lines = []
    modified = False

    is_math_big = (pkg_rel == "math/big")
    inside_struct = False

    for line_idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            new_lines.append(line)
            continue

        if (stripped.startswith("struct ") or stripped.startswith("pub struct ")) and "{" in stripped:
            if "}" in stripped:
                inside_struct = False
            else:
                inside_struct = True
        elif inside_struct and "}" in stripped:
            inside_struct = False

        tokens = tokenize_line(line)
        if not tokens:
            new_lines.append(line)
            continue

        line_out = []
        n_tok = len(tokens)

        # Check if line contains "fn" or "const"
        is_fn_decl = any(kind == "IDENT" and text == "fn" for kind, text in tokens)
        is_const_decl = any(kind == "IDENT" and text == "const" for kind, text in tokens)

        for i, (kind, text) in enumerate(tokens):
            if kind != "IDENT":
                line_out.append(text)
                continue

            # Look behind for non-ws token
            prev_tok = None
            prev2_tok = None
            j = i - 1
            while j >= 0 and tokens[j][0] == "WS":
                j -= 1
            if j >= 0:
                prev_tok = tokens[j]
                k = j - 1
                while k >= 0 and tokens[k][0] == "WS":
                    k -= 1
                if k >= 0:
                    prev2_tok = tokens[k]

            # Look ahead for non-ws token
            next_tok = None
            j = i + 1
            while j < n_tok and tokens[j][0] == "WS":
                j += 1
            if j < n_tok:
                next_tok = tokens[j]

            # Case 1: Dot-qualified reference: pkg.const_name
            if prev_tok and prev_tok[0] == "DOT" and prev2_tok and prev2_tok[0] == "IDENT":
                pkg_qual = prev2_tok[1]
                if (pkg_qual, text) in global_pub:
                    new_name = global_pub[(pkg_qual, text)][0]
                    line_out.append(new_name)
                    modified = True
                    continue

            # Case 2: Dot field access: obj.field (NOT a package qualification)
            if prev_tok and prev_tok[0] == "DOT":
                line_out.append(text)
                continue

            # Case 3: Local package const reference or declaration
            if text in local_dict:
                # Is it the const declaration itself: "const <name> =" or "pub const <name> ="?
                if is_const_decl and prev_tok and prev_tok[1] == "const":
                    new_name = local_dict[text]["new_name"]
                    line_out.append(new_name)
                    modified = True
                    continue

                # Check for fn declaration: fn foo( or fn (...) foo(
                if is_fn_decl and next_tok and next_tok[1] == "(":
                    line_out.append(text)
                    continue

                # Check for struct field initialization in literal: ident: value
                # In struct literals, field is preceded by '{' or ',' or start of line.
                # If preceded by an operator like '+', '-', '*', '/', it is a slice index [start:stop], NOT a field!
                if next_tok and next_tok[0] == "COLON":
                    if prev_tok is None or prev_tok[1] in ("{", ",", "\n") or (prev_tok[0] == "IDENT" and prev_tok[1] == "pub"):
                        line_out.append(text)
                        continue

                # If inside struct definition, do not replace field declarations
                if inside_struct:
                    # In struct definition: "pub field_name Type" or "field_name Type"
                    if prev_tok is None or prev_tok[1] in ("pub", "\n"):
                        line_out.append(text)
                        continue

                # If prev_tok was "let" or "mut" and NOT const, then it's a local variable!
                if prev_tok and prev_tok[1] in ("let", "mut"):
                    line_out.append(text)
                    continue

                # Special case: math/big 'base'
                if is_math_big and text == "base" and line_idx > 500:
                    line_out.append(text)
                    continue

                # Replace with new UPPER_SNAKE_CASE name
                new_name = local_dict[text]["new_name"]
                line_out.append(new_name)
                modified = True
                continue

            line_out.append(text)

        new_lines.append("".join(line_out))

    return "\n".join(new_lines), modified

def update_python_tests(dry_run=True):
    updates = [
        ("tests/test_high_availability_primitives.py", [
            ("sync.circuit_closed", "sync.CIRCUIT_CLOSED"),
            ("sync.circuit_open", "sync.CIRCUIT_OPEN"),
            ("sync.circuit_half_open", "sync.CIRCUIT_HALF_OPEN"),
        ]),
        ("tests/test_crypto_complete_fixes.py", [
            ("rsa.sha256", "rsa.SHA256"),
            ("tls.version_tls13", "tls.VERSION_TLS13"),
            ("tls.tls_aes_128_gcm_sha256", "tls.TLS_AES_128_GCM_SHA256"),
        ]),
        ("tests/test_ui_runtime_bridge.py", [
            ("ui.ev_none", "ui.EV_NONE"),
            ("ui.ev_click", "ui.EV_CLICK"),
        ]),
        ("tests/test_dwarf_location_ranges.py", [
            ('assert "pub const dw_op_addr = 3" in content', 'assert "pub const DW_OP_ADDR = 3" in content'),
            ('assert "pub const dw_op_fbreg = 145" in content', 'assert "pub const DW_OP_FBREG = 145" in content'),
            ('assert "pub const dw_op_reg0 = 80" in content', 'assert "pub const DW_OP_REG0 = 80" in content'),
            ('assert "pub const dw_op_regx = 144" in content', 'assert "pub const DW_OP_REGX = 144" in content'),
        ]),
        ("tests/test_generic_lir_isel.py", [
            ('assert "pub const lir_op_add = 2" in content', 'assert "pub const LIR_OP_ADD = 2" in content'),
            ('assert "pub const lir_op_sub = 3" in content', 'assert "pub const LIR_OP_SUB = 3" in content'),
            ('assert "pub const lir_op_mul = 4" in content', 'assert "pub const LIR_OP_MUL = 4" in content'),
            ('assert "pub const lir_op_load = 11" in content', 'assert "pub const LIR_OP_LOAD = 11" in content'),
            ('assert "pub const lir_op_store = 12" in content', 'assert "pub const LIR_OP_STORE = 12" in content'),
            ('assert "pub const lir_op_jmp = 13" in content', 'assert "pub const LIR_OP_JMP = 13" in content'),
            ('assert "pub const lir_op_ret = 16" in content', 'assert "pub const LIR_OP_RET = 16" in content'),
        ]),
        ("tests/test_generic_loop_vectorization.py", [
            ('assert "const vp_generic_vector =" in content', 'assert "const VP_GENERIC_VECTOR =" in content'),
        ]),
        ("tests/test_alu_forward_edges.py", [
            ("r'^const vreg_plan_temp_cap = \\d+$'", "r'^const VREG_PLAN_TEMP_CAP = \\d+$'"),
        ]),
        ("tests/test_regplan_general.py", [
            ("const u32_max = 4294967295", "const U32_MAX = 4294967295"),
            ("const poly = 79764919", "const POLY = 79764919"),
            ("x = x ^ poly", "x = x ^ POLY"),
            ("poly", "POLY"),
            ("u32_max", "U32_MAX"),
        ]),
    ]

    for rel_path, replacements in updates:
        abs_path = os.path.join(REPO_ROOT, rel_path)
        if not os.path.exists(abs_path):
            continue
        with open(abs_path, "r", encoding="utf-8") as fp:
            c = fp.read()
        orig = c
        for old, new in replacements:
            c = c.replace(old, new)
        if c != orig:
            print(f"Updated python test: {rel_path}")
            if not dry_run:
                with open(abs_path, "w", encoding="utf-8") as fp:
                    fp.write(c)

def run_migration(dry_run=True, extra_dirs=None):
    pkg_consts, global_pub = scan_consts(extra_dirs=extra_dirs)
    total_consts = sum(len(v) for v in pkg_consts.values())
    print(f"Loaded {total_consts} consts, {len(global_pub)} global pub consts.")

    total_files_modified = 0
    targets = []
    scan_all = [SRC_DIR, TESTS_DIR]
    if extra_dirs:
        scan_all.extend(extra_dirs)

    for d in scan_all:
        for root, dirs, files in os.walk(d):
            if any(part in root for part in [".git", "dist", "staging", "target"]):
                continue
            for f in files:
                if f.endswith(".xu"):
                    if "err_name_const" in root:
                        continue
                    targets.append(os.path.join(root, f))

    for fpath in targets:
        base = SRC_DIR
        for d in scan_all:
            if fpath.startswith(d):
                base = d
                break
        pkg_rel, _ = get_pkg_info(fpath, base)
        try:
            with open(fpath, "r", encoding="utf-8") as fp:
                content = fp.read()
        except Exception:
            continue

        new_content, mod = process_file_content(fpath, content, pkg_rel, pkg_consts, global_pub)
        if mod:
            total_files_modified += 1
            if not dry_run:
                with open(fpath, "w", encoding="utf-8") as fp:
                    fp.write(new_content)

    print(f"Migration completed. Modified {total_files_modified} files (dry_run={dry_run}).")
    update_python_tests(dry_run=dry_run)

if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    extras = []
    for i, a in enumerate(sys.argv):
        if a == "--extra-dir" and i + 1 < len(sys.argv):
            extras.append(sys.argv[i + 1])
    run_migration(dry_run=dry_run, extra_dirs=extras)
