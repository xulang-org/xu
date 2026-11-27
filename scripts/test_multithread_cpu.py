#!/usr/bin/env python3
"""Verify hardware atomics, @sync/pool OS threads, and llm_engine --threads N parity & speedup."""
from __future__ import annotations

import os
import platform
import random
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XU = ROOT / "bin" / "xu"

sys.path.insert(0, str(ROOT / "scripts"))
from test_llm_engine import (  # noqa: E402
    CFG,
    bits_to_f32,
    f32,
    gen_weights,
    generate_weight_dict,
    pack_gguf_str,
    parse_bench,
    parse_verify,
    quantize_q4_0_matrix,
    quantize_q4_k_matrix,
    write_gguf_q4_0,
    write_safetensors,
)


def run(cmd: list[str], env: dict[str, str]) -> str:
    res = subprocess.run([str(x) for x in cmd], env=env, capture_output=True, text=True)
    if res.returncode != 0:
        raise AssertionError(
            f"Command failed ({res.returncode}): {' '.join(str(x) for x in cmd)}\n"
            f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
    return res.stdout


def build(exe: Path, src: Path, env: dict[str, str]) -> None:
    run([str(XU), "build", str(src), "-o", str(exe)], env)


def write_fast_tiled_gguf(path: Path, cfg: dict, fmt: str) -> None:
    dim = cfg["dim"]
    hidden = cfg["hidden_dim"]
    n_layers = cfg["n_layers"]
    n_heads = cfg["n_heads"]
    n_kv = cfg["n_kv_heads"]
    head_dim = dim // n_heads
    kv_dim = n_kv * head_dim
    vocab = cfg["vocab_size"]

    rng = random.Random(20261130)
    if fmt == "q4_k":
        tile_raw, _ = quantize_q4_k_matrix(gen_weights(rng, 4096, 0.04))
        gtype, blk_vals, blk_bytes, tile_blks = 12, 256, 144, 16
    elif fmt == "q4_0":
        tile_raw, _, _ = quantize_q4_0_matrix(gen_weights(rng, 4096, 0.04))
        gtype, blk_vals, blk_bytes, tile_blks = 2, 32, 18, 128
    else:
        raise ValueError(fmt)

    norm_raw = struct.pack(f"<{dim}f", *[f32(0.95 + 0.1 * rng.random()) for _ in range(dim)])
    vocab_pieces = [f"tok_{i}" for i in range(vocab)]
    kv_entries = [
        ("general.architecture", 8, pack_gguf_str("llama")),
        ("general.alignment", 4, struct.pack("<I", 32)),
        ("llama.embedding_length", 4, struct.pack("<I", dim)),
        ("llama.feed_forward_length", 4, struct.pack("<I", hidden)),
        ("llama.block_count", 4, struct.pack("<I", n_layers)),
        ("llama.attention.head_count", 4, struct.pack("<I", n_heads)),
        ("llama.attention.head_count_kv", 4, struct.pack("<I", n_kv)),
        ("llama.context_length", 4, struct.pack("<I", cfg["max_seq_len"])),
        ("llama.rope.freq_base", 6, struct.pack("<f", float(cfg["rope_theta"]))),
        ("llama.attention.layer_norm_rms_epsilon", 6, struct.pack("<f", 1e-5)),
        ("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 8, vocab) + b"".join(pack_gguf_str(p) for p in vocab_pieces)),
    ]

    tensor_specs = []

    def add_tiled(gname: str, cols: int, rows: int) -> None:
        n_blk = (rows * cols) // blk_vals
        rep = (n_blk + tile_blks - 1) // tile_blks
        raw = (tile_raw * rep)[: n_blk * blk_bytes]
        tensor_specs.append((gname, [cols, rows], gtype, raw))

    add_tiled("token_embd.weight", dim, vocab)
    for l in range(n_layers):
        gp = f"blk.{l}."
        tensor_specs.append((gp + "attn_norm.weight", [dim], 0, norm_raw))
        add_tiled(gp + "attn_q.weight", dim, dim)
        add_tiled(gp + "attn_k.weight", dim, kv_dim)
        add_tiled(gp + "attn_v.weight", dim, kv_dim)
        add_tiled(gp + "attn_output.weight", dim, dim)
        tensor_specs.append((gp + "ffn_norm.weight", [dim], 0, norm_raw))
        add_tiled(gp + "ffn_gate.weight", dim, hidden)
        add_tiled(gp + "ffn_up.weight", dim, hidden)
        add_tiled(gp + "ffn_down.weight", hidden, dim)
    tensor_specs.append(("output_norm.weight", [dim], 0, norm_raw))
    add_tiled("output.weight", dim, vocab)

    buf = bytearray(b"GGUF")
    buf.extend(struct.pack("<IQQ", 3, len(tensor_specs), len(kv_entries)))
    for k, vtype, vbytes in kv_entries:
        buf.extend(pack_gguf_str(k))
        buf.extend(struct.pack("<I", vtype))
        buf.extend(vbytes)

    payload = bytearray()
    for tname, dims, gt, raw in tensor_specs:
        tpad = (32 - (len(payload) % 32)) % 32
        payload.extend(b"\x00" * tpad)
        off = len(payload)
        payload.extend(raw)
        buf.extend(pack_gguf_str(tname))
        buf.extend(struct.pack("<I", len(dims)))
        for dv in dims:
            buf.extend(struct.pack("<Q", dv))
        buf.extend(struct.pack("<IQ", gt, off))

    pad = (32 - (len(buf) % 32)) % 32
    buf.extend(b"\x00" * pad)
    buf.extend(payload)
    path.write_bytes(buf)


def check_hardware_atomics(work: Path, env: dict[str, str]) -> None:
    src = work / "atomic_stress.xu"
    src.write_text('''@main
#ffi
#sync/pool as pool

fn stress_worker(ctx c_ptr, r0 int, r1 int) {
    unsafe {
        p_add := ffi.read_ptr(ctx, 0)
        p_cas := ffi.read_ptr(ctx, 8)
        iters := r1 - r0
        for _ in 0:iters {
            _ := atomic_add(p_add, 1)
            $ok := false
            while !ok {
                cur := atomic_load(p_cas)
                ok = atomic_cas(p_cas, cur, cur + 1)
            }
        }
    }
}

fn main() int {
    $local_v := 10
    _ := atomic_add($&local_v, 5)
    assert(atomic_load($&local_v) == 15)
    assert(atomic_cas($&local_v, 15, 99))
    assert(atomic_load($&local_v) == 99)

    $p := pool.new_thread_pool(4)
    unsafe {
        mem := ffi.calloc(32)
        ctx := p.scratch()
        ffi.write_ptr(ctx, 0, mem)
        ffi.write_ptr(ctx, 8, ffi.offset(mem, 8))
        p.parallel_for_raw(400000, 1, ctx, c_callback(stress_worker))
        sum_add := atomic_load(mem)
        sum_cas := atomic_load(ffi.offset(mem, 8))
        ffi.free(mem)
        p.close()
        println("NCPU:" + str(pool.cpu_count()))
        println("ADD:" + str(sum_add))
        println("CAS:" + str(sum_cas))
        if sum_add != 400000 || sum_cas != 400000 { << 2 }
    }
    << 0
}
''')
    exe = work / "atomic_stress"
    build(exe, src, env)
    if platform.system() == "Darwin" and platform.machine().lower() in ("arm64", "aarch64"):
        asm = run(["otool", "-tV", str(exe)], env)
        for sym, insns in [
            ("___xu_atomic_load_i64", ["ldar"]),
            ("___xu_atomic_store_i64", ["stlr"]),
            ("___xu_atomic_add_i64", ["ldaxr", "stlxr"]),
            ("___xu_atomic_cas_i64", ["ldaxr", "stlxr"]),
        ]:
            m = re.search(rf"^{re.escape(sym)}:[\s\S]*?(?=^___|\Z)", asm, re.M)
            assert m is not None, f"Missing atomic stub {sym}"
            for ins in insns:
                assert ins in m[0], f"Expected {ins} in {sym}:\n{m[0]}"

    out = run([str(exe)], env)
    vals = dict(line.split(":", 1) for line in out.strip().splitlines())
    assert int(vals["ADD"]) == 400000 and int(vals["CAS"]) == 400000, vals
    print(f"Hardware atomics + 4-thread OS pool stress (400k add + 400k cas, ncpu={vals['NCPU']}) PASS")


def check_llm_engine_parity_and_bench(work: Path, env: dict[str, str]) -> None:
    exe = work / "llm_engine_mt"
    build(exe, ROOT / "examples" / "llm_engine" / "main.xu", env)

    base_tensors = generate_weight_dict(CFG)
    st_path = work / "mt_f32.safetensors"
    write_safetensors(st_path, CFG, base_tensors)

    kcfg = dict(CFG, n_kv_heads=4, max_seq_len=128)
    k_tensors = generate_weight_dict(kcfg)

    parity_cases = [
        ("f32", st_path, []),
        ("q4_0", work / "mt_q4_0.gguf", []),
        ("q8_0", work / "mt_q8_0.gguf", []),
        ("q4_k", work / "mt_q4_k.gguf", ["--q8k-act"]),
        ("q5_k", work / "mt_q5_k.gguf", ["--q8k-act"]),
        ("q6_k", work / "mt_q6_k.gguf", ["--q8k-act"]),
    ]
    write_gguf_q4_0(work / "mt_q4_0.gguf", CFG, base_tensors, quant_mode=None)
    write_gguf_q4_0(work / "mt_q8_0.gguf", CFG, base_tensors, quant_mode="q8_0")
    for fmt in ("q4_k", "q5_k", "q6_k"):
        write_gguf_q4_0(work / f"mt_{fmt}.gguf", kcfg, k_tensors, quant_mode=fmt)

    for label, path, flags in parity_cases:
        out1 = run([str(exe), "verify", str(path), *flags, "--threads", "1"], env)
        out4 = run([str(exe), "verify", str(path), *flags, "--threads", "4"], env)
        seq1, cb1, meta1 = parse_verify(out1)
        seq4, cb4, meta4 = parse_verify(out4)
        assert seq1 == cb1 and seq4 == cb4, (label, meta1, meta4)
        assert seq1.keys() == seq4.keys(), (label, seq1.keys(), seq4.keys())
        max_diff = 0.0
        for r in seq1:
            t1 = [t for t, _ in seq1[r]]
            t4 = [t for t, _ in seq4[r]]
            assert t1 == t4, f"{label} req={r} token mismatch: {t1} vs {t4}"
            for (_, b1), (_, b4) in zip(seq1[r], seq4[r]):
                d = abs(bits_to_f32(b1) - bits_to_f32(b4))
                if d > max_diff:
                    max_diff = d
        if label in ("q4_k", "q5_k", "q6_k"):
            assert seq1 == seq4, f"{label} --threads 4 not bit-exact vs --threads 1 (max_diff={max_diff})"
        else:
            assert max_diff < 1e-5, f"{label} --threads 4 logit max_diff={max_diff}"
        print(f"llm_engine --threads 4 == --threads 1 parity ({label}, max_diff={max_diff:.2e}) PASS")

    bcfg = {
        "dim": 2048,
        "hidden_dim": 5632,
        "n_layers": 8,
        "n_heads": 16,
        "n_kv_heads": 8,
        "vocab_size": 2048,
        "max_seq_len": 128,
        "rope_theta": 10000,
    }
    for fmt, extra in [("q4_0", []), ("q4_k", ["--q8k-act"])]:
        gpath = work / f"bench_2048_{fmt}.gguf"
        write_fast_tiled_gguf(gpath, bcfg, fmt)
        b1 = parse_bench(run([str(exe), "bench", str(gpath), "16", "single", "32", *extra, "--threads", "1"], env))
        b4 = parse_bench(run([str(exe), "bench", str(gpath), "16", "single", "32", *extra, "--threads", "4"], env))
        p1 = b1["prefill_tokens"] * 1e9 / max(b1["prefill_ns"], 1)
        p4 = b4["prefill_tokens"] * 1e9 / max(b4["prefill_ns"], 1)
        d1 = b1["decode_steps"] * 1e9 / max(b1["decode_total_ns"], 1)
        d4 = b4["decode_steps"] * 1e9 / max(b4["decode_total_ns"], 1)
        assert b1["tokens"] == b4["tokens"], (fmt, b1["tokens"], b4["tokens"])
        p_sp = p4 / max(p1, 1e-9)
        d_sp = d4 / max(d1, 1e-9)
        print(
            f"[CPU Multi-Core dim=2048 L=8 {fmt}] Prefill P=32: 1T={p1:.1f} vs 4T={p4:.1f} tok/s ({p_sp:.2f}x) | "
            f"Decode 16: 1T={d1:.1f} vs 4T={d4:.1f} tok/s ({d_sp:.2f}x)"
        )
        min_dec = 1.8 if fmt == "q4_k" else 1.15
        assert p_sp > 1.8 and d_sp > min_dec, (fmt, p_sp, d_sp)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        env = dict(
            os.environ,
            XU_STDLIB_ROOT=str(ROOT / "src"),
            XU_CACHE=str(work / "cache"),
            XU_TENSOR_FUSION="1",
            XU_TENSOR_FAST_MATH="1",
            XU_KEEP_SYMBOLS="1",
        )
        check_hardware_atomics(work, env)
        check_llm_engine_parity_and_bench(work, env)


if __name__ == "__main__":
    main()
