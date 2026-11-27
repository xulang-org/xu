#!/usr/bin/env python3
"""Verification for crypto/cipher CFB/OFB modes and encoding/json parse_max."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER = ROOT / "bin" / "xu.exe"

TEST_CODE = r'''@main

#crypto/aes
#crypto/cipher
#encoding/hex
#encoding/json

fn test_cipher_cfb() {
    key := hex.decode_string("2b7e151628aed2a6abf7158809cf4f3c") >>> (err) { <<< 1 }
    iv := hex.decode_string("000102030405060708090a0b0c0d0e0f") >>> (err) { <<< 2 }
    c := aes.new_cipher(&key) >>> (err) { <<< 3 }

    // Test multi-block and partial block (27 bytes)
    pt := "The quick brown fox jumps over" // 30 bytes
    ct := cipher.encrypt_cfb(&c, &iv, &pt) >>> (err) {
        eprintln("encrypt_cfb failed: " + err.msg())
        <<< 4
    }
    if ct.len != pt.len {
        eprintln("cfb ciphertext length mismatch: " + str(ct.len) + " vs " + str(pt.len))
        <<< 5
    }
    decrypted := cipher.decrypt_cfb(&c, &iv, &ct) >>> (err) {
        eprintln("decrypt_cfb failed: " + err.msg())
        <<< 6
    }
    if decrypted != pt {
        eprintln("cfb roundtrip failed: " + decrypted)
        <<< 7
    }

    // Invalid IV
    short_iv := "short"
    cipher.encrypt_cfb(&c, &short_iv, &pt) >>> (err) {
        // Expected error
        println("OK: cfb invalid IV rejected")
        <<
    }
    eprintln("expected invalid IV error")
    <<< 8
}

fn test_cipher_ofb() {
    key := hex.decode_string("2b7e151628aed2a6abf7158809cf4f3c") >>> (err) { <<< 10 }
    iv := hex.decode_string("000102030405060708090a0b0c0d0e0f") >>> (err) { <<< 11 }
    c := aes.new_cipher(&key) >>> (err) { <<< 12 }

    pt := "Stream ciphers like OFB work on arbitrary byte lengths!"
    ct := cipher.encrypt_ofb(&c, &iv, &pt) >>> (err) {
        eprintln("encrypt_ofb failed: " + err.msg())
        <<< 13
    }
    if ct.len != pt.len {
        eprintln("ofb ciphertext length mismatch: " + str(ct.len) + " vs " + str(pt.len))
        <<< 14
    }
    decrypted := cipher.decrypt_ofb(&c, &iv, &ct) >>> (err) {
        eprintln("decrypt_ofb failed: " + err.msg())
        <<< 15
    }
    if decrypted != pt {
        eprintln("ofb roundtrip failed: " + decrypted)
        <<< 16
    }

    // Invalid IV
    bad_iv := "0123456789"
    cipher.encrypt_ofb(&c, &bad_iv, &pt) >>> (err) {
        println("OK: ofb invalid IV rejected")
        <<
    }
    eprintln("expected invalid IV error")
    <<< 17
}

fn test_json_parse_max() {
    valid_json := "{\"key\": \"value\", \"num\": 123}"
    doc := json.parse_max(&valid_json, 100)
    if !doc.ok() {
        eprintln("parse_max under limit failed: " + doc.error())
        <<< 20
    }
    r := doc.root()
    k := doc.get(r, "key") >>> (err) {
        eprintln("get key failed: " + err.msg())
        <<< 24
    }
    val := doc.as_string(k) >>> (err) {
        eprintln("as_string failed: " + err.msg())
        <<< 25
    }
    if val != "value" {
        eprintln("expected value, got " + val)
        <<< 21
    }

    // Now test exceeding max_bytes limit
    doc2 := json.parse_max(&valid_json, 10)
    if doc2.ok() {
        eprintln("expected error for exceeding max_bytes")
        <<< 22
    }
    if doc2.error() != "json: document exceeds maximum byte limit" {
        eprintln("unexpected error message: " + doc2.error())
        <<< 23
    }
    println("OK: json parse_max limit correctly enforced")
}

fn main() {
    test_cipher_cfb()
    test_cipher_ofb()
    test_json_parse_max()
    println("ALL_CIPHER_JSON_TESTS_PASSED")
}
'''

def main() -> int:
    env = os.environ.copy()
    env["XU_STDLIB_ROOT"] = str(ROOT / "src")
    env["XU_ROOT"] = str(ROOT)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        src = Path(td) / "test_cipher.xu"
        exe = Path(td) / "test_cipher.exe"
        src.write_text(TEST_CODE, encoding="utf-8")

        build_cmd = [str(COMPILER), "build", str(src), "-o", str(exe)]
        r = subprocess.run(build_cmd, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print("COMPILE FAILED:\n" + r.stderr + "\n" + r.stdout)
            return 1

        r2 = subprocess.run([str(exe)], env=env, capture_output=True, text=True, timeout=10)
        print(r2.stdout)
        if r2.stderr:
            print(r2.stderr, file=sys.stderr)

        if r2.returncode != 0:
            print(f"FAILED with exit code {r2.returncode}")
            return 1

        if "ALL_CIPHER_JSON_TESTS_PASSED" not in r2.stdout:
            print("FAILED: missing completion banner")
            return 1

    print("SUCCESS: crypto/cipher and json tests passed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
