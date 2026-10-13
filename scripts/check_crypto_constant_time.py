#!/usr/bin/env python3
"""Enforce XU-CT-CONTRACT v1 and the stdlib/core crypto boundary."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from companion_repos import project_root

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "audit" / "CRYPTO_CONSTANT_TIME.md"

REQUIRED_CLASSES = {
    "src/crypto/subtle/mod.xu": "constant-time-contracted",
    "src/crypto/aes/mod.xu": "variable-time",
    "src/crypto/cipher/gcm.xu": "variable-time",
    "src/math/big/mod.xu": "variable-time",
    "src/crypto/rsa/mod.xu": "variable-time",
    "src/crypto/ecdsa/mod.xu": "variable-time",
    "src/crypto/ed25519/mod.xu": "variable-time",
    "src/crypto/sm2/mod.xu": "variable-time",
    "src/crypto/sm9/mod.xu": "variable-time",
    "src/crypto/tls/mod.xu": "variable-time",
}

CONTRACTED = {
    "constant_time_compare",
    "constant_time_byte_eq",
    "constant_time_eq",
    "constant_time_select",
}

DOC_MARKERS = {
    "XU-CT-CONTRACTED": {
        "crypto/subtle.constant_time_compare",
        "crypto/subtle.constant_time_byte_eq",
        "crypto/subtle.constant_time_eq",
        "crypto/subtle.constant_time_select",
    },
    "XU-CT-FIXED-SHAPE": {
        "crypto/cipher.gcm_tag_compare",
        "crypto/hmac.equal",
    },
    "XU-CT-VARIABLE": {
        "crypto/aes",
        "crypto/cipher.gcm",
        "math/big",
        "crypto/rsa",
        "crypto/ecdsa",
        "crypto/ecdsa.ecdh",
        "crypto/ed25519",
        "crypto/sm2",
        "crypto/sm9",
        "crypto/tls",
    },
}

# Instruction selection and inlining guards name private hardware hooks.
# Permit only their complete string literals in these exact dispatch files;
# imports, public crypto calls and algorithm implementations remain forbidden.
HW_INLINE_PREFIXES = {
    "_xu_crypto_aes_aes_hw_", "_xu_crypto_sha256_sha256_hw_",
    "_xu_crypto_sha1_sha1_hw_", "_xu_crypto_sm4_sm4_hw_",
    "_xu_crypto_sha512_sha512_hw_",
}
HW_DISPATCH_LABELS = {
    "_xu_crypto_aes_aes_hw_supported", "_xu_crypto_aes_aes_hw_block_enc",
    "_xu_crypto_aes_aes_hw_block_dec", "_xu_crypto_aes_aes_hw_drk",
    "_xu_crypto_sha256_sha256_hw_supported",
    "_xu_crypto_sha256_sha256_hw_compress_block", "_xu_crypto_sha1_sha1_hw_supported",
    "_xu_crypto_sha1_sha1_hw_compress_block", "_xu_crypto_sm4_sm4_hw_supported",
    "_xu_crypto_sm4_sm4_hw_crypt", "_xu_crypto_sha512_sha512_hw_supported",
    "_xu_crypto_sha512_sha512_hw_compress_block",
}
HW_REFERENCE_FILES = {
    "src/xu/types/mir_09_opt_inline.xu": HW_INLINE_PREFIXES,
    "src/xu/types/mir_10_opt_cfg.xu": HW_INLINE_PREFIXES,
    "src/cmd/compile/emit_instr_call_user_net.xu": HW_DISPATCH_LABELS,
}


def mask_hardware_references(relative: str, text: str) -> str:
    allowed = HW_REFERENCE_FILES.get(relative, set())
    return re.sub(r'"(?:[^"\\\n]|\\.)*"',
                  lambda match: '"hardware-reference"' if match.group(0)[1:-1] in allowed else match.group(0),
                  text)


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        fail(f"missing {relative}")
    return path.read_text()


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\bpub\s+fn\s+{re.escape(name)}\s*\(", source)
    if match is None:
        fail(f"crypto/subtle is missing {name}")
    start = source.find("{", match.end())
    if start < 0:
        fail(f"cannot find body for {name}")
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index]
    fail(f"unterminated body for {name}")
    return ""


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def check_doc() -> None:
    text = read("docs/audit/CRYPTO_CONSTANT_TIME.md")
    if "XU-CT-CONTRACT v1" not in text:
        fail("constant-time document has no v1 version")
    for key, expected in DOC_MARKERS.items():
        match = re.search(rf"<!--\s*{re.escape(key)}:\s*([^>]+?)\s*-->", text)
        if match is None:
            fail(f"constant-time document is missing {key}")
        actual = {item.strip() for item in match.group(1).split(",") if item.strip()}
        if actual != expected:
            fail(f"{key} differs: expected {sorted(expected)}, got {sorted(actual)}")


def check_classes() -> None:
    for relative, classification in REQUIRED_CLASSES.items():
        text = read(relative)
        marker = f"XU-CT-CLASS: {classification}"
        if marker not in text:
            fail(f"{relative} must contain '{marker}'")


def check_subtle() -> None:
    source = read("src/crypto/subtle/mod.xu")
    public_names = set(re.findall(r"\bpub\s+fn\s+(constant_time_[a-z_]+)\s*\(", source))
    if public_names != CONTRACTED:
        fail(f"contracted subtle set changed: expected {sorted(CONTRACTED)}, got {sorted(public_names)}")

    compare = function_body(source, "constant_time_compare")
    compare_c = compact(compare)
    if "ifx.len!=y.len{<<0}" not in compare_c:
        fail("constant_time_compare must keep the public length-mismatch check")
    if "foriin0:x.len" not in compare_c:
        fail("constant_time_compare must scan the complete equal-length input")
    if compare.count("if ") != 1:
        fail("constant_time_compare may branch only for public length mismatch")
    if "nz:=((v|(0-v))>>63)&1" not in compare_c or "<<1-nz" not in compare_c:
        fail("constant_time_compare result must use branchless nonzero reduction")

    for name, value in (("constant_time_byte_eq", "z"), ("constant_time_eq", "z")):
        body = function_body(source, name)
        body_c = compact(body)
        if re.search(r"\bif\b", body):
            fail(f"{name} must not branch on its operands")
        if f"nz:=(({value}|(0-{value}))>>63)&1" not in body_c or "<<1-nz" not in body_c:
            fail(f"{name} must use branchless nonzero reduction")

    select = function_body(source, "constant_time_select")
    select_c = compact(select)
    if re.search(r"\bif\b", select):
        fail("constant_time_select must not branch on its selector")
    if "mask:=0-(v&1)" not in select_c or "<<(mask&x)|((mask^(0-1))&y)" not in select_c:
        fail("constant_time_select must use mask selection")

    xor_body = function_body(source, "xor_bytes")
    if "ifx.len!=y.len" not in compact(xor_body):
        fail("xor_bytes must reject unequal public shapes instead of truncating")


def check_consumers() -> None:
    gcm = read("src/crypto/cipher/gcm.xu")
    eq16 = re.search(r"fn\s+gcm_eq16\b.*?\n}", gcm, flags=re.DOTALL)
    if eq16 is None or "subtle.constant_time_compare" not in eq16.group(0):
        fail("AES-GCM tag equality must use crypto/subtle")
    if "XU-CT-USE: fixed-shape-only" not in gcm:
        fail("AES-GCM must label its narrow crypto/subtle use")

    hmac = read("src/crypto/hmac/mod.xu")
    if "XU-CT-USE: fixed-shape-only" not in hmac:
        fail("crypto/hmac must label its narrow crypto/subtle use")

    consumer_files: set[Path] = set()
    for path in (ROOT / "src" / "crypto").rglob("*.xu"):
        if path == ROOT / "src" / "crypto" / "subtle" / "mod.xu":
            continue
        text = path.read_text()
        if "#crypto/subtle" in text or "subtle.constant_time" in text:
            consumer_files.add(path)
            if "XU-CT-USE: fixed-shape-only" not in text and "XU-CT-CLASS: variable-time" not in text:
                fail(
                    f"{path.relative_to(ROOT)} uses crypto/subtle without a "
                    "fixed-shape-only or variable-time marker"
                )
    if not consumer_files:
        fail("no crypto/subtle consumers were discovered")


def check_core_boundary() -> None:
    roots = [ROOT / "src" / "xu", ROOT / "src" / "cmd" / "compile"]
    # Tests/examples may legitimately mention crypto fixture names. The
    # boundary applies to bootstrap implementation code, not its test corpus.
    bootstrap_root = project_root("bootstrap", core_root=ROOT)
    roots.extend(sorted((bootstrap_root / "crates").glob("*/src")))
    def logical(path: Path) -> str:
        if path.is_relative_to(ROOT):
            return path.relative_to(ROOT).as_posix()
        return (Path("bootstrap") / path.relative_to(bootstrap_root)).as_posix()
    forbidden = re.compile(
        r"@crypto(?:/|\.)|#crypto(?:/|\.)|_xu_crypto_|"
        r"\bcrypto_(?:aes|rsa|ecdsa|ecdh|ed25519|tls|x509|sha[0-9_]*)\b|"
        r"\btls_(?:aes|rsa|ecdhe)[a-z0-9_]*\b|"
        r"\bfn\s+(?:aes|ghash|rsa|ecdsa|ecdh|tls13)\b",
        flags=re.IGNORECASE,
    )
    for root in roots:
        if not root.is_dir():
            fail(f"missing boundary root {logical(root)}")
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".xu", ".rs"}:
                continue
            relative = logical(path)
            text = mask_hardware_references(relative, path.read_text(errors="replace"))
            match = forbidden.search(text)
            if match:
                fail(
                    f"stdlib crypto implementation marker '{match.group(0)}' entered "
                    f"{logical(path)}"
                )


def main() -> int:
    check_doc()
    check_classes()
    check_subtle()
    check_consumers()
    check_core_boundary()
    print("ok: XU-CT-CONTRACT v1 and stdlib/core crypto boundary")
    return 0


if __name__ == "__main__":
    sys.exit(main())
