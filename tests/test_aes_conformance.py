#!/usr/bin/env python3
"""AES independent known-answer/differential oracle, six compiler configurations.

No network or Python package installation is needed. cryptography is preferred;
the openssl CLI provides the ECB/CBC/CTR fallback. GCM differential cases are
reported as unavailable when cryptography is absent (never silently counted).
FIPS 197 vectors: https://csrc.nist.gov/pubs/fips/197/final
"""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = (['-O0'], ['-O1'], ['-O2'], ['-O3'],
           ['-O1', '--no-regcache'], ['-O3', '--ra=0'])
FIPS = (
    ('000102030405060708090a0b0c0d0e0f', '69c4e0d86a7b0430d8cdb78070b4c55a'),
    ('000102030405060708090a0b0c0d0e0f1011121314151617', 'dda97ca4864cdfe06eaf70a0ec0d7191'),
    ('000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f', '8ea2b7ca516745bfeafc49904b496089'),
)
PT = bytes.fromhex('00112233445566778899aabbccddeeff')


class Oracle:
    def __init__(self):
        try:
            import cryptography
            from cryptography.hazmat.backends.openssl.backend import backend
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            self.Cipher, self.algorithms, self.modes, self.AESGCM = Cipher, algorithms, modes, AESGCM
            self.identity = dict(cryptography=cryptography.__version__, openssl=backend.openssl_version_text())
        except ImportError:
            if not shutil.which('openssl'):
                raise RuntimeError('AES oracle needs cryptography or the openssl CLI')
            self.Cipher = self.AESGCM = None
            self.identity = dict(openssl_cli=subprocess.check_output(['openssl', 'version'], text=True).strip(),
                                 gcm='unavailable: cryptography not installed')
        for key, ct in FIPS:
            assert self.crypt(bytes.fromhex(key), PT).hex() == ct
            assert self.crypt(bytes.fromhex(key), bytes.fromhex(ct), decrypt=True) == PT

    def crypt(self, key, data, mode='ecb', iv=None, decrypt=False):
        if self.Cipher:
            m = self.modes.ECB() if mode == 'ecb' else getattr(self.modes, mode.upper())(iv)
            cipher = self.Cipher(self.algorithms.AES(key), m)
            ctx = cipher.decryptor() if decrypt else cipher.encryptor()
            return ctx.update(data) + ctx.finalize()
        cmd = ['openssl', 'enc', f'-aes-{len(key) * 8}-{mode}', '-nopad', '-nosalt', '-K', key.hex()]
        if iv is not None:
            cmd += ['-iv', iv.hex()]
        if decrypt:
            cmd += ['-d']
        return subprocess.run(cmd, input=data, capture_output=True, check=True).stdout


PRELUDE = '''@main
#crypto/aes
#crypto/cipher
#encoding/hex

fn fail(msg string) int { println(msg)\n << -1 }
fn bad_key(key &string) bool {
    aes.new_cipher(key) or (err) { << err.msg() == "crypto/aes: invalid key size" }
    << false
}
fn bad_block(c &aes.Cipher, s &string, dec bool) bool {
    if dec { c.decrypt(s) or (err) { << err.msg() == "crypto/aes: invalid block size" } }
    else { c.encrypt(s) or (err) { << err.msg() == "crypto/aes: invalid block size" } }
    << false
}
fn boundaries() int {
    mut count := 0
    for n in 0:41 {
        if n != 16 && n != 24 && n != 32 {
            key := make_string(n)
            if !bad_key(&key) { << fail("bad key length") }
            count = count + 1
        }
    }
    for n in [63,64,65,255,256,4097] {
        key := make_string(n)
        if !bad_key(&key) { << fail("long key") }
        count = count + 1
    }
    for k in [16,24,32] {
        key := make_string(k)
        c := aes.new_cipher(&key) or (err) { << -1 }
        for n in 0:41 {
            if n != 16 {
                s := make_string(n)
                if !bad_block(&c,&s,false) || !bad_block(&c,&s,true) { << fail("bad block length") }
                count = count + 2
            }
        }
        for n in [63,64,65,255,256,4097] {
            s := make_string(n)
            if !bad_block(&c,&s,false) || !bad_block(&c,&s,true) { << fail("long block") }
            count = count + 2
        }
        s := make_string(16)
        ct := c.encrypt(&s) or (err) { << -1 }
        back := c.decrypt(&ct) or (err) { << -1 }
        if back != s { << fail("cipher damaged after rejected input") }
    }
    << count
}
fn group(kh string, ph string, eh string, ch string, dh string) int {
    key := hex.decode_string(kh + "") or (err) { << -1 }
    p := hex.decode_string(ph + "") or (err) { << -1 }
    e := hex.decode_string(eh + "") or (err) { << -1 }
    ct := hex.decode_string(ch + "") or (err) { << -1 }
    d := hex.decode_string(dh + "") or (err) { << -1 }
    c := aes.new_cipher(&key) or (err) { << -1 }
    if c.block_size() != 16 || c.nr != key.len / 4 + 6 || c.rk.len != 16 * (c.nr + 1) {
        << fail("cipher shape")
    }
    if c.sbox.len != 256 || c.inv.len != 256 { << fail("sbox length") }
    for i in 0:256 {
        if c.inv[c.sbox[i]] != i { << fail("sbox inverse") }
    }
    mut i := 0
    while i < p.len {
        block := p[i:i + 16]
        encrypted := c.encrypt(&block) or (err) { << -1 }
        if encrypted != e[i:i + 16] { << fail("independent encryption mismatch") }
        input := ct[i:i + 16]
        decrypted := c.decrypt(&input) or (err) { << -1 }
        if decrypted != d[i:i + 16] { << fail("independent decryption mismatch") }
        if block != p[i:i + 16] || input != ct[i:i + 16] { << fail("borrowed input changed") }
        if i == 0 {
            again := c.encrypt(&block) or (err) { << -1 }
            if again != encrypted { << fail("cipher reuse") }
        }
        i = i + 16
    }
    if hex.encode_to_string(key + "") != kh { << fail("borrowed key changed") }
    << p.len / 16
}
fn mode_case(kind string, kh string, ih string, ph string, eh string, ah string) int {
    key := hex.decode_string(kh) or (err) { << -1 }
    iv := hex.decode_string(ih) or (err) { << -1 }
    pt := hex.decode_string(ph) or (err) { << -1 }
    expected := hex.decode_string(eh) or (err) { << -1 }
    aad := hex.decode_string(ah) or (err) { << -1 }
    c := aes.new_cipher(&key) or (err) { << -1 }
    mut encrypted := ""
    mut back := ""
    if kind == "cbc" {
        encrypted = cipher.encrypt_cbc(&c,&iv,&pt) or (err) { << -1 }
        back = cipher.decrypt_cbc(&c,&iv,&expected) or (err) { << -1 }
    }
    if kind == "ctr" {
        encrypted = cipher.encrypt_ctr(&c,&iv,&pt) or (err) { << -1 }
        back = cipher.decrypt_ctr(&c,&iv,&expected) or (err) { << -1 }
    }
    if kind == "pkcs7" {
        encrypted = cipher.encrypt_cbc_pkcs7(&c,&iv,&pt) or (err) { << -1 }
        back = cipher.decrypt_cbc_pkcs7(&c,&iv,&expected) or (err) { << -1 }
    }
    if kind == "gcm" {
        encrypted = cipher.seal_gcm(&c,&iv,&pt,&aad) or (err) { << -1 }
        back = cipher.open_gcm(&c,&iv,&expected,&aad) or (err) { << -1 }
        mut corrupt := expected + ""
        corrupt[corrupt.len - 1] = corrupt[corrupt.len - 1] ^ 1
        if !reject_tag(&c,&iv,&corrupt,&aad) { << fail("accepted corrupt GCM tag") }
        wrongaad := aad + "x"
        if !reject_tag(&c,&iv,&expected,&wrongaad) { << fail("accepted wrong GCM AAD") }
    }
    if encrypted != expected || back != pt { << fail("mode oracle mismatch: " + kind) }
    << 1
}
fn reject_tag(c &aes.Cipher, iv &string, sealed &string, aad &string) bool {
    cipher.open_gcm(c,iv,sealed,aad) or (err) { << true }
    << false
}
'''


def cases(oracle, small=False):
    rng = random.Random(20261008)
    groups = defaultdict(list)
    def add(key, pt):
        groups[key].append((pt, bytes(rng.randrange(256) for _ in range(16))))
    for kh, _ in FIPS:
        key = bytes.fromhex(kh)
        add(key, PT)
        for value in (0, 255):
            add(key, bytes([value]) * 16)
        if not small:
            for bit in range(len(key) * 8):
                walk = bytearray(len(key)); walk[bit // 8] = 1 << (bit % 8)
                add(bytes(walk), bytes(16))
            for bit in range(128):
                walk = bytearray(16); walk[bit // 8] = 1 << (bit % 8)
                add(bytes(len(key)), bytes(walk))
            for value in range(256):
                add(key, bytes([value]) * 16)
        for _ in range(1 if small else 8):
            random_key = bytes(rng.randrange(256) for _ in range(len(key)))
            for _ in range(4 if small else 64):
                add(random_key, bytes(rng.randrange(256) for _ in range(16)))
    rows = []
    for key, pairs in groups.items():
        p, ct = (b''.join(pair[i] for pair in pairs) for i in (0, 1))
        rows.append([key.hex(), p.hex(), oracle.crypt(key, p).hex(), ct.hex(), oracle.crypt(key, ct, decrypt=True).hex()])
    modes = []
    for n in (16, 24, 32):
        key = bytes(rng.randrange(256) for _ in range(n))
        for length in ((0, 17) if small else (0,1,15,16,17,31,32,33,255,256,1024)):
            pt = bytes(rng.randrange(256) for _ in range(length))
            iv = bytes(rng.randrange(256) for _ in range(16))
            for mode in ('cbc', 'ctr', 'pkcs7', 'gcm'):
                if mode == 'cbc' and length % 16:
                    continue
                aad = bytes(rng.randrange(256) for _ in range(length % 37))
                if mode == 'gcm':
                    if not oracle.AESGCM:
                        continue
                    nonce = iv[:12]
                    expected = oracle.AESGCM(key).encrypt(nonce, pt, aad)
                else:
                    nonce = iv
                    padded = pt + bytes([16 - length % 16]) * (16 - length % 16) if mode == 'pkcs7' else pt
                    expected = oracle.crypt(key, padded, 'cbc' if mode == 'pkcs7' else mode, iv)
                modes.append([mode, key.hex(), nonce.hex(), pt.hex(), expected.hex(), aad.hex()])
    return rows, modes


def source_for(groups, modes):
    calls = [('group', row, len(row[1]) // 32) for row in groups]
    calls += [('mode_case', row, 0) for row in modes]
    code = [PRELUDE]
    # Small functions avoid conflating crypto tests with giant caller frames.
    chunks = [calls[i:i + 24] for i in range(0, len(calls), 24)]
    for i, chunk in enumerate(chunks):
        code += [f'fn batch{i}() int {{', 'mut count := 0']
        for j, (fn, row, _) in enumerate(chunk):
            code += [f'v{j} := {fn}(' + ','.join(json.dumps(v) for v in row) + ')',
                     f'if v{j} < 0 {{ << -1 }}', f'count = count + v{j}']
        code += ['<< count', '}']
    block_count = sum(len(row[1]) // 32 for row in groups)
    expected = f'AES conformance PASS: blocks={block_count} errors=320 modes={len(modes)}\n'
    code += ['fn main() int {', 'errors := boundaries()', 'if errors != 320 { << 1 }', 'mut count := 0']
    for i in range(len(chunks)):
        code += [f'n{i} := batch{i}()', f'if n{i} < 0 {{ << 1 }}', f'count = count + n{i}']
    code += [f'if count != {block_count + len(modes)} {{ << 1 }}', f'println({json.dumps(expected.strip())})', '<< 0', '}']
    return '\n'.join(code) + '\n', expected


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xu', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--source-root', type=Path, default=ROOT)
    ap.add_argument('--write-fixture', action='store_true')
    args = ap.parse_args()
    compiler = args.xu.resolve()
    identity = hashlib.sha256(compiler.read_bytes()).hexdigest()
    oracle = Oracle()
    work = args.out.resolve().parent
    work.mkdir(parents=True, exist_ok=True)
    groups, modes = cases(oracle)
    source, golden = source_for(groups, modes)
    path = work / 'aes_oracle.xu'
    path.write_text(source)
    (work / 'aes_oracle.cases.json').write_text(json.dumps(dict(oracle=oracle.identity, groups=groups, modes=modes), indent=2) + '\n')
    if args.write_fixture:
        fixture = args.source_root / 'tests/fixtures/crypto_aes_conformance'
        fixture.mkdir(exist_ok=True)
        small_source, small_golden = source_for(*cases(oracle, small=True))
        (fixture / 'main.xu').write_text(small_source.replace('@main\n',
            '@main\n// Independent FIPS/OpenSSL oracle; generated by tests/test_aes_conformance.py.\n', 1))
        (fixture / 'expected.txt').write_text(small_golden)
    rows = []
    for flags in CONFIGS:
        tag = '_'.join(flag.lstrip('-').replace('=', '_') for flag in flags)
        binary = work / ('aes_oracle_' + tag)
        built = subprocess.run([str(args.source_root / 'scripts/run_product_compiler.sh'), str(compiler),
            'build', *flags, str(path), '-o', str(binary)], cwd=args.source_root, capture_output=True,
            text=True, timeout=180, env=dict(os.environ, XU_GEN1_HEAP_LEDGER='1'))
        row = dict(flags=flags, build_exit=built.returncode, build_stderr=built.stderr)
        if not built.returncode:
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=120,
                env=dict(os.environ, XU_HEAP_STATS='1'))
            ledger = {k: int(v) for k, v in re.findall(r'xu_heap_stats (\w+)=(\d+)', run.stderr)}
            extra = re.sub(r'xu_heap_stats \w+=\d+\n', '', run.stderr)
            row.update(run_exit=run.returncode, stdout=run.stdout, stderr=run.stderr, ledger=ledger,
                       binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
            good = (not run.returncode and run.stdout == golden and not extra and len(ledger) == 7
                    and ledger['live_bytes'] == 0 and ledger['allocs'] == ledger['frees']
                    and not any(ledger[k] for k in ('unknown_frees', 'double_frees', 'ledger_overflows')))
        else:
            good = False
        row['status'] = 'PASS' if good else 'FAIL'
        rows.append(row)
        print(flags, row['status'], row.get('stdout', built.stderr[-500:]).strip(), row.get('ledger'), flush=True)
    drift = hashlib.sha256(compiler.read_bytes()).hexdigest() != identity
    args.out.write_text(json.dumps(dict(compiler_sha256=identity, compiler_drift=drift, oracle=oracle.identity,
        blocks_per_config=sum(len(row[1]) // 32 for row in groups), independent_decrypt=True,
        errors_per_config=320, modes_per_config=len(modes), gcm_differential=bool(oracle.AESGCM),
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        golden_sha256=hashlib.sha256(golden.encode()).hexdigest(), rows=rows), indent=2) + '\n')
    return drift or any(row['status'] != 'PASS' for row in rows)


if __name__ == '__main__':
    raise SystemExit(main())
