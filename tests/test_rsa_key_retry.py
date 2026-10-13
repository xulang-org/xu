"""Replay the real RSA retry body with deterministic prime candidates."""
from pathlib import Path
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]
REPLAY = """@main
#math/big
#errors
#crypto/rsa
fn rand_prime(bits int, draws &mut int) big.Int {
 *draws += 1
 mut text := "2147483659"
 if *draws > 2 {
  if (*draws & 1) != 0 { text = "3221225473" } else { text = "3221225479" }
 }
 mut z := big.new_int(0)
 z.set_string(text, 10) or >>
 << z
}
fn main() int {
 key := generate_key(64) or (err) {
  println(err.msg())
  << 1
 }
 n := &key.public.n
 println(n.bit_len())
 << 0
}
"""

@pytest.mark.parametrize("flags", [(), ("-O3",), ("--no-regcache",)])
def test_key_retry_replaces_both_primes(tmp_path, flags):
    # There is no injectable randomness seam in the public key generator.
    # Compile its exact shipped retry body; only the private prime provider
    # is replaced and given a local draw counter. Real big.Int/RSA types and
    # all remaining key arithmetic are exercised by the native compiler.
    text = (ROOT / "src/crypto/rsa/mod.xu").read_text()
    body = text[text.index("pub fn generate_key"):]
    body = body.replace("pub fn generate_key", "fn generate_key")
    body = body.replace("PrivateKey", "rsa.PrivateKey").replace("PublicKey", "rsa.PublicKey")
    body = body.replace("    if bits < 64", "    mut draws := 0\n    if bits < 64")
    body = body.replace("rand_prime(pbits)", "rand_prime(pbits, mut &draws)")
    body = body.replace("rand_prime(qbits)", "rand_prime(qbits, mut &draws)")
    source = tmp_path / "main.xu"
    source.write_text(REPLAY + body)
    binary = tmp_path / "replay"
    build = subprocess.run([str(ROOT / "scripts/run_product_compiler.sh"), str(ROOT / "bin/xu"),
                            "build", *flags, str(source), "-o", str(binary)],
                           cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert build.returncode == 0, build.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    assert (result.returncode, result.stdout, result.stderr) == (0, "64\n", "")
