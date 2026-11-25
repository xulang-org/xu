#!/usr/bin/env python3
"""Verify and benchmark the pure-Xu Transformer engine (F32, Q4_0xF32, Q4_0xQ8_0 SDOT, FlashDecoding, generate CLI)."""

import argparse
import json
import math
import os
import platform
from pathlib import Path
import random
import re
import struct
import tempfile

from test_tensor_dynamic import mir_functions
from test_tensor_fusion import build, run


CFG = {
    "dim": 256,
    "hidden_dim": 512,
    "n_layers": 4,
    "n_heads": 4,
    "n_kv_heads": 2,
    "vocab_size": 512,
    "max_seq_len": 64,
    "rope_theta": 10000,
}

REQUESTS = [
    ([1, 7, 42], 3),
    ([3, 19], 5),
    ([5, 11, 23, 37], 2),
    ([9], 3),
]


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def bits_to_f32(b):
    return struct.unpack("<f", struct.pack("<I", b))[0]


def gen_weights(rng, count, scale):
    return [f32((rng.random() * 2.0 - 1.0) * scale) for _ in range(count)]


def generate_weight_dict(cfg):
    rng = random.Random(20261124)
    dim = cfg["dim"]
    hidden = cfg["hidden_dim"]
    n_layers = cfg["n_layers"]
    head_dim = dim // cfg["n_heads"]
    kv_dim = cfg["n_kv_heads"] * head_dim
    vocab = cfg["vocab_size"]

    tensors = {}
    tensors["embed_tokens.weight"] = ([vocab, dim], gen_weights(rng, vocab * dim, 0.08))
    for l in range(n_layers):
        p = f"layers.{l}."
        tensors[p + "input_layernorm.weight"] = ([dim], [f32(0.9 + 0.2 * rng.random()) for _ in range(dim)])
        tensors[p + "self_attn.q_proj.weight"] = ([dim, dim], gen_weights(rng, dim * dim, 1.0 / math.sqrt(dim)))
        tensors[p + "self_attn.k_proj.weight"] = ([kv_dim, dim], gen_weights(rng, kv_dim * dim, 1.0 / math.sqrt(dim)))
        tensors[p + "self_attn.v_proj.weight"] = ([kv_dim, dim], gen_weights(rng, kv_dim * dim, 1.0 / math.sqrt(dim)))
        tensors[p + "self_attn.o_proj.weight"] = ([dim, dim], gen_weights(rng, dim * dim, 1.0 / math.sqrt(dim)))
        tensors[p + "post_attention_layernorm.weight"] = ([dim], [f32(0.9 + 0.2 * rng.random()) for _ in range(dim)])
        tensors[p + "mlp.gate_proj.weight"] = ([hidden, dim], gen_weights(rng, hidden * dim, 1.0 / math.sqrt(dim)))
        tensors[p + "mlp.up_proj.weight"] = ([hidden, dim], gen_weights(rng, hidden * dim, 1.0 / math.sqrt(dim)))
        tensors[p + "mlp.down_proj.weight"] = ([dim, hidden], gen_weights(rng, dim * hidden, 1.0 / math.sqrt(hidden)))
    tensors["norm.weight"] = ([dim], [f32(0.9 + 0.2 * rng.random()) for _ in range(dim)])
    tensors["lm_head.weight"] = ([vocab, dim], gen_weights(rng, vocab * dim, 1.0 / math.sqrt(dim)))
    return tensors


def write_safetensors(path, cfg, tensors):
    header = {"__metadata__": {k: str(v) for k, v in cfg.items()}}
    payload = bytearray()
    for name, (shape, vals) in tensors.items():
        start = len(payload)
        payload.extend(struct.pack(f"<{len(vals)}f", *vals))
        end = len(payload)
        header[name] = {"dtype": "F32", "shape": shape, "data_offsets": [start, end]}

    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    pad = (8 - (len(header_bytes) % 8)) % 8
    header_bytes += b" " * pad
    path.write_bytes(struct.pack("<Q", len(header_bytes)) + header_bytes + payload)


def quantize_q4_0_matrix(vals):
    assert len(vals) % 32 == 0
    nb = len(vals) // 32
    raw = bytearray()
    qs_out = bytearray()
    scales_out = []
    for b in range(nb):
        blk = vals[b * 32:(b + 1) * 32]
        amax = max(abs(v) for v in blk)
        d = f32(amax / 7.0) if amax > 0.0 else 0.0
        d16_bytes = struct.pack("<e", d)
        d16 = f32(struct.unpack("<e", d16_bytes)[0])
        scales_out.append(d16)
        raw.extend(d16_bytes)
        inv_d = (1.0 / d16) if d16 != 0.0 else 0.0
        q_nibbles = []
        for v in blk:
            q = int(round(v * inv_d)) + 8
            if q < 0:
                q = 0
            elif q > 15:
                q = 15
            q_nibbles.append(q)
        for j in range(16):
            byte_val = (q_nibbles[j] & 15) | ((q_nibbles[16 + j] & 15) << 4)
            qs_out.append(byte_val)
            raw.append(byte_val)
    return bytes(raw), bytes(qs_out), scales_out


def quantize_q8_0_matrix(vals):
    assert len(vals) % 32 == 0
    nb = len(vals) // 32
    raw = bytearray()
    qs_out = []
    scales_out = []
    for b in range(nb):
        blk = vals[b * 32:(b + 1) * 32]
        amax = max(abs(v) for v in blk)
        d = f32(amax / 127.0) if amax > 0.0 else 0.0
        d16_bytes = struct.pack("<e", d)
        d16 = f32(struct.unpack("<e", d16_bytes)[0])
        scales_out.append(d16)
        raw.extend(d16_bytes)
        inv_d = (1.0 / d16) if d16 != 0.0 else 0.0
        for v in blk:
            q = int(round(v * inv_d))
            if q > 127:
                q = 127
            elif q < -127:
                q = -127
            qs_out.append(q)
            raw.append(q & 0xFF)
    return bytes(raw), qs_out, scales_out


def pack_gguf_str(s):
    b = s.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def write_gguf_q4_0(path, cfg, tensors, biases=None, qwen_mode=False, tied_output=False):
    dim = cfg["dim"]
    hidden = cfg["hidden_dim"]
    n_layers = cfg["n_layers"]
    n_heads = cfg["n_heads"]
    n_kv = cfg["n_kv_heads"]
    head_dim = dim // n_heads
    kv_dim = n_kv * head_dim
    vocab = cfg["vocab_size"]

    arch = "qwen2" if qwen_mode else "llama"
    vocab_pieces = []
    if qwen_mode:
        special = {0: "<|endoftext|>", 1: "Hi", 2: "<|im_end|>", 5: "\u0120Paris", 7: "\u0120world"}
        for i in range(vocab):
            vocab_pieces.append(special.get(i, f"tok_{i}"))
    else:
        vocab_pieces = [f"tok_{i}" for i in range(vocab)]

    kv_entries = [
        ("general.architecture", 8, pack_gguf_str(arch)),
        ("general.alignment", 4, struct.pack("<I", 32)),
        (f"{arch}.embedding_length", 4, struct.pack("<I", dim)),
        (f"{arch}.feed_forward_length", 4, struct.pack("<I", hidden)),
        (f"{arch}.block_count", 4, struct.pack("<I", n_layers)),
        (f"{arch}.attention.head_count", 4, struct.pack("<I", n_heads)),
        (f"{arch}.attention.head_count_kv", 4, struct.pack("<I", n_kv)),
        (f"{arch}.context_length", 4, struct.pack("<I", cfg["max_seq_len"])),
        (f"{arch}.rope.freq_base", 6, struct.pack("<f", float(cfg["rope_theta"]))),
        (f"{arch}.attention.layer_norm_rms_epsilon", 6, struct.pack("<f", 1e-5)),
    ]
    if qwen_mode:
        kv_entries.extend([
            ("tokenizer.ggml.model", 8, pack_gguf_str("gpt2")),
            ("tokenizer.ggml.bos_token_id", 4, struct.pack("<I", 0)),
            ("tokenizer.ggml.eos_token_id", 4, struct.pack("<I", 2)),
        ])
    kv_entries.append((
        "tokenizer.ggml.tokens", 9,
        struct.pack("<IQ", 8, vocab) + b"".join(pack_gguf_str(p) for p in vocab_pieces),
    ))

    tensor_specs = []
    q4_data = {}
    q8_data = {}

    def add_f32(gname, dims, vals):
        raw = struct.pack(f"<{len(vals)}f", *vals)
        tensor_specs.append((gname, dims, 0, raw))

    def add_q4(gname, dims, vals):
        raw, qs, sc = quantize_q4_0_matrix(vals)
        tensor_specs.append((gname, dims, 2, raw))
        q4_data[gname] = (qs, sc)

    def add_q8(gname, dims, vals):
        raw, qs, sc = quantize_q8_0_matrix(vals)
        tensor_specs.append((gname, dims, 8, raw))
        q8_data[gname] = (qs, sc)

    if qwen_mode or tied_output:
        add_q4("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    else:
        add_f32("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    for l in range(n_layers):
        p = f"layers.{l}."
        gp = f"blk.{l}."
        add_f32(gp + "attn_norm.weight", [dim], tensors[p + "input_layernorm.weight"][1])
        add_q4(gp + "attn_q.weight", [dim, dim], tensors[p + "self_attn.q_proj.weight"][1])
        add_q4(gp + "attn_k.weight", [dim, kv_dim], tensors[p + "self_attn.k_proj.weight"][1])
        add_q4(gp + "attn_v.weight", [dim, kv_dim], tensors[p + "self_attn.v_proj.weight"][1])
        if biases is not None:
            add_f32(gp + "attn_q.bias", [dim], biases[l][0])
            add_f32(gp + "attn_k.bias", [kv_dim], biases[l][1])
            add_f32(gp + "attn_v.bias", [kv_dim], biases[l][2])
        add_q4(gp + "attn_output.weight", [dim, dim], tensors[p + "self_attn.o_proj.weight"][1])
        add_f32(gp + "ffn_norm.weight", [dim], tensors[p + "post_attention_layernorm.weight"][1])
        add_q4(gp + "ffn_gate.weight", [dim, hidden], tensors[p + "mlp.gate_proj.weight"][1])
        add_q4(gp + "ffn_up.weight", [dim, hidden], tensors[p + "mlp.up_proj.weight"][1])
        add_q4(gp + "ffn_down.weight", [hidden, dim], tensors[p + "mlp.down_proj.weight"][1])
    add_f32("output_norm.weight", [dim], tensors["norm.weight"][1])
    if not tied_output:
        if qwen_mode:
            add_q8("output.weight", [dim, vocab], tensors["lm_head.weight"][1])
        else:
            add_q4("output.weight", [dim, vocab], tensors["lm_head.weight"][1])

    buf = bytearray()
    buf.extend(b"GGUF")
    buf.extend(struct.pack("<IQQ", 3, len(tensor_specs), len(kv_entries)))
    for k, vtype, vbytes in kv_entries:
        buf.extend(pack_gguf_str(k))
        buf.extend(struct.pack("<I", vtype))
        buf.extend(vbytes)

    payload = bytearray()
    for tname, dims, gtype, raw in tensor_specs:
        off = len(payload)
        payload.extend(raw)
        buf.extend(pack_gguf_str(tname))
        buf.extend(struct.pack("<I", len(dims)))
        for dv in dims:
            buf.extend(struct.pack("<Q", dv))
        buf.extend(struct.pack("<IQ", gtype, off))

    pad = (32 - (len(buf) % 32)) % 32
    buf.extend(b"\x00" * pad)
    buf.extend(payload)
    path.write_bytes(buf)
    return q4_data, q8_data if qwen_mode else None


def py_rmsnorm(x, skip, weight):
    n = len(x)
    res = [f32(a + b) for a, b in zip(x, skip)]
    total = 0.0
    for v in res:
        total = f32(total + f32(v * v))
    inv = f32(1.0 / math.sqrt(total / n + 0.00001))
    return [f32(f32(v * inv) * w) for v, w in zip(res, weight)]


def py_matvec(x, w, rows, cols):
    out = []
    for r in range(rows):
        base = r * cols
        acc = 0.0
        for c in range(cols):
            acc = f32(acc + f32(w[base + c] * x[c]))
        out.append(acc)
    return out


def py_matvec_q4_0(x, qs, scales, rows, cols):
    nb = cols // 32
    out = []
    for r in range(rows):
        acc = 0.0
        for b in range(nb):
            bsum = 0.0
            qb = (r * nb + b) * 16
            xb = b * 32
            sc = scales[r * nb + b]
            for j in range(16):
                bv = qs[qb + j]
                q0 = (bv & 15) - 8
                q1 = (bv >> 4) - 8
                bsum = f32(bsum + f32(f32(q0 * x[xb + j]) + f32(q1 * x[xb + 16 + j])))
            acc = f32(acc + f32(bsum * sc))
        out.append(acc)
    return out


def py_quantize_q8_0(x):
    nb = len(x) // 32
    xq = []
    xs = []
    for b in range(nb):
        blk = x[b * 32:(b + 1) * 32]
        amax = max(abs(float(v)) for v in blk)
        scale = f32(amax / 127.0)
        xs.append(scale)
        inv = (1.0 / float(scale)) if float(scale) != 0.0 else 0.0
        for v in blk:
            vf = float(v) * inv
            q = int(vf + 0.5) if vf >= 0.0 else -int(0.5 - vf)
            if q > 127:
                q = 127
            elif q < -127:
                q = -127
            xq.append(q)
    return xq, xs


def py_matvec_q4_0_q8_0(xq, xs, qs, ws, rows, cols):
    nb = cols // 32
    out = []
    for r in range(rows):
        acc = 0.0
        for b in range(nb):
            isum = 0
            qb = (r * nb + b) * 16
            xb = b * 32
            for j in range(16):
                bv = qs[qb + j]
                q0 = (bv & 15) - 8
                q1 = (bv >> 4) - 8
                isum += q0 * xq[xb + j] + q1 * xq[xb + 16 + j]
            acc = f32(acc + f32(f32(isum) * f32(ws[r * nb + b] * xs[b])))
        out.append(acc)
    return out


def py_matvec_q8_0_q8_0(xq, xs, qs, ws, rows, cols):
    nb = cols // 32
    out = []
    for r in range(rows):
        acc = 0.0
        for b in range(nb):
            rb = r * nb + b
            qoff = rb * 32
            xoff = b * 32
            isum = 0
            for j in range(32):
                isum += qs[qoff + j] * xq[xoff + j]
            acc = f32(acc + f32(f32(isum) * f32(ws[rb] * xs[b])))
        out.append(acc)
    return out


def py_dequantize_q4_0(qs, scales):
    out = []
    for b, d in enumerate(scales):
        qoff = b * 16
        lo = [f32(((qs[qoff + j] & 15) - 8) * d) for j in range(16)]
        hi = [f32(((qs[qoff + j] >> 4) - 8) * d) for j in range(16)]
        out.extend(lo)
        out.extend(hi)
    return out


def py_rope(vec, n_heads, head_dim, pos, theta):
    out = list(vec)
    half = head_dim // 2
    log_theta = math.log(float(theta))
    for j in range(half):
        angle = pos * math.exp(-log_theta * ((2 * j) / head_dim))
        c = f32(math.cos(angle))
        s = f32(math.sin(angle))
        for h in range(n_heads):
            off = h * head_dim
            v0 = out[off + j]
            v1 = out[off + j + half]
            out[off + j] = f32(f32(v0 * c) - f32(v1 * s))
            out[off + j + half] = f32(f32(v0 * s) + f32(v1 * c))
    return out


def py_run_request(tensors, prompt, max_gen, q4_data=None, use_q8_act=False, q8_data=None, biases=None):
    dim = CFG["dim"]
    hidden = CFG["hidden_dim"]
    n_layers = CFG["n_layers"]
    n_heads = CFG["n_heads"]
    n_kv = CFG["n_kv_heads"]
    head_dim = dim // n_heads
    kv_dim = n_kv * head_dim
    kv_mul = n_heads // n_kv
    vocab = CFG["vocab_size"]
    theta = CFG["rope_theta"]
    inv_sqrt_d = f32(1.0 / math.sqrt(head_dim))

    def proj(x, q8, st_name, gguf_name, rows, cols):
        if q8_data is not None and gguf_name in q8_data:
            qs, sc = q8_data[gguf_name]
            assert use_q8_act
            xq, xs = q8
            return py_matvec_q8_0_q8_0(xq, xs, qs, sc, rows, cols)
        if q4_data is None:
            return py_matvec(x, tensors[st_name][1], rows, cols)
        qs, sc = q4_data[gguf_name]
        if use_q8_act:
            xq, xs = q8
            return py_matvec_q4_0_q8_0(xq, xs, qs, sc, rows, cols)
        return py_matvec_q4_0(x, qs, sc, rows, cols)

    if q4_data is not None and "token_embd.weight" in q4_data:
        qs, sc = q4_data["token_embd.weight"]
        embed = py_dequantize_q4_0(qs, sc)
    else:
        embed = tensors["embed_tokens.weight"][1]
    final_norm = tensors["norm.weight"][1]
    k_cache = [[] for _ in range(n_layers)]
    v_cache = [[] for _ in range(n_layers)]
    zeros = [0.0] * dim

    tokens = []
    logits_out = []
    cur = prompt[0]
    total_steps = len(prompt) + max_gen - 1
    for step in range(total_steps):
        x = embed[cur * dim:(cur + 1) * dim]
        for l in range(n_layers):
            p = f"layers.{l}."
            gp = f"blk.{l}."
            xb = py_rmsnorm(x, zeros, tensors[p + "input_layernorm.weight"][1])
            q8_xb = py_quantize_q8_0(xb) if (q4_data is not None and use_q8_act) else None
            q_raw = proj(xb, q8_xb, p + "self_attn.q_proj.weight", gp + "attn_q.weight", dim, dim)
            k_raw = proj(xb, q8_xb, p + "self_attn.k_proj.weight", gp + "attn_k.weight", kv_dim, dim)
            v = proj(xb, q8_xb, p + "self_attn.v_proj.weight", gp + "attn_v.weight", kv_dim, dim)
            if biases is not None:
                bq, bk, bv = biases[l]
                q_raw = [f32(a + b) for a, b in zip(q_raw, bq)]
                k_raw = [f32(a + b) for a, b in zip(k_raw, bk)]
                v = [f32(a + b) for a, b in zip(v, bv)]
            q = py_rope(q_raw, n_heads, head_dim, step, theta)
            k = py_rope(k_raw, n_kv, head_dim, step, theta)
            k_cache[l].append(k)
            v_cache[l].append(v)

            # Online Softmax 1-pass attention matching forward_token
            xb_att = [0.0] * dim
            for h in range(n_heads):
                q_off = h * head_dim
                kv_off = (h // kv_mul) * head_dim
                k0 = k_cache[l][0]
                v0 = v_cache[l][0]
                acc0 = 0.0
                for d in range(head_dim):
                    acc0 = f32(acc0 + f32(q[q_off + d] * k0[kv_off + d]))
                m_val = float(f32(acc0 * inv_sqrt_d))
                l_val = 1.0
                for d in range(head_dim):
                    xb_att[q_off + d] = v0[kv_off + d]

                for t in range(1, step + 1):
                    kt = k_cache[l][t]
                    vt = v_cache[l][t]
                    acc = 0.0
                    for d in range(head_dim):
                        acc = f32(acc + f32(q[q_off + d] * kt[kv_off + d]))
                    score = float(f32(acc * inv_sqrt_d))
                    if score > m_val:
                        alpha = f32(math.exp(m_val - score))
                        for d in range(head_dim):
                            xb_att[q_off + d] = f32(xb_att[q_off + d] * alpha)
                        l_val = l_val * float(alpha) + 1.0
                        m_val = score
                        for d in range(head_dim):
                            xb_att[q_off + d] = f32(xb_att[q_off + d] + f32(f32(1.0) * vt[kv_off + d]))
                    else:
                        w = f32(math.exp(score - m_val))
                        l_val = l_val + float(w)
                        for d in range(head_dim):
                            xb_att[q_off + d] = f32(xb_att[q_off + d] + f32(w * vt[kv_off + d]))

                inv_l = f32(1.0 / l_val)
                for d in range(head_dim):
                    xb_att[q_off + d] = f32(xb_att[q_off + d] * inv_l)

            q8_att = py_quantize_q8_0(xb_att) if (q4_data is not None and use_q8_act) else None
            xb2 = proj(xb_att, q8_att, p + "self_attn.o_proj.weight", gp + "attn_output.weight", dim, dim)
            x = [f32(a + b) for a, b in zip(x, xb2)]
            xb = py_rmsnorm(x, zeros, tensors[p + "post_attention_layernorm.weight"][1])
            q8_ffn = py_quantize_q8_0(xb) if (q4_data is not None and use_q8_act) else None
            hb = proj(xb, q8_ffn, p + "mlp.gate_proj.weight", gp + "ffn_gate.weight", hidden, dim)
            hb2 = proj(xb, q8_ffn, p + "mlp.up_proj.weight", gp + "ffn_up.weight", hidden, dim)
            act = [f32(f32(g / (1.0 + math.exp(-g))) * u) for g, u in zip(hb, hb2)]
            q8_act = py_quantize_q8_0(act) if (q4_data is not None and use_q8_act) else None
            xb2 = proj(act, q8_act, p + "mlp.down_proj.weight", gp + "ffn_down.weight", dim, hidden)
            if l + 1 < n_layers:
                x = [f32(a + b) for a, b in zip(x, xb2)]

        xb = py_rmsnorm(x, xb2, final_norm)
        q8_out = py_quantize_q8_0(xb) if (q4_data is not None and use_q8_act) else None
        logits = proj(xb, q8_out, "lm_head.weight", "output.weight", vocab, dim)
        nxt = max(range(vocab), key=lambda i: logits[i])
        if step + 1 < len(prompt):
            cur = prompt[step + 1]
        else:
            tokens.append(nxt)
            logits_out.append(logits[nxt])
            cur = nxt
    return tokens, logits_out


def parse_verify(output):
    seq, cb = {}, {}
    meta = {}
    for line in output.splitlines():
        kind, rest = line.split(":", 1)
        if kind in ("seq", "cb"):
            idx_s, pairs_s = rest.split(":", 1)
            pairs = [(int(tok), int(bits)) for tok, bits in (p.split("@") for p in pairs_s.split(","))]
            (seq if kind == "seq" else cb)[int(idx_s)] = pairs
        else:
            meta[kind] = rest
    return seq, cb, meta


def parse_bench(output):
    out = {}
    for line in output.splitlines():
        k, v = line.split(":", 1)
        out[k] = v if k == "tokens" else int(v)
    return out


def check_format(exes, model_path, py_ref, label, want_fmt, want_act, want_vocab, verify_cmd="verify", bench_cmd="bench"):
    baseline_seq = None
    baseline_checksum = None
    m_kb = model_path.stat().st_size / 1024.0
    print(f"--- {label} ({model_path.name}, {m_kb:.1f} KiB) ---")
    for name, fast, exe, size_kb in exes:
        v_out = run([exe, verify_cmd, str(model_path)])
        seq, cb, meta = parse_verify(v_out)
        assert meta.get("format") == want_fmt, (name, meta)
        assert meta.get("act_mode") == want_act, (name, meta)
        assert int(meta.get("vocab_size", -1)) == want_vocab, (name, meta)
        free_num, free_den = map(int, meta["kv_free_after"].split("/"))
        assert free_num == free_den and free_den > 0, (name, meta)
        assert int(meta["kv_allocs"]) >= 8, (name, meta)
        assert seq == cb, (name, label, "Continuous Batching mismatch vs sequential!")
        assert len(seq) == len(REQUESTS)

        if name == "baseline":
            baseline_seq = seq
        elif name == "fusion-strict":
            assert seq == baseline_seq, f"{label}: fusion-strict bit-exact mismatch vs baseline!"

        for r, (py_toks, py_logits) in enumerate(py_ref):
            xu_toks = [t for t, _ in seq[r]]
            xu_logits = [bits_to_f32(b) for _, b in seq[r]]
            assert xu_toks == py_toks, (label, name, r, xu_toks, py_toks)
            tol = (2e-2 if want_fmt == "q4_0" else 1e-4) if fast == "1" else 1e-5
            for a, b in zip(xu_logits, py_logits):
                assert abs(a - b) < tol, (label, name, r, a, b)

        b_stats = parse_bench(run([exe, bench_cmd, str(model_path), "32"]))
        if name == "baseline":
            baseline_checksum = b_stats["checksum"]
        elif name == "fusion-strict":
            assert b_stats["checksum"] == baseline_checksum

        dec_tok_s = b_stats["decode_steps"] * 1e9 / b_stats["decode_total_ns"]
        cb_tok_s = b_stats["cb_steps"] * 1e9 / b_stats["cb_total_ns"]
        print(
            f"[{label:9} {name:13}] bin={size_kb:6.1f} KiB | "
            f"TTFT={b_stats['ttft_ns']/1e3:7.1f} us | "
            f"decode P50={b_stats['decode_p50_ns']/1e3:7.1f} us "
            f"P99={b_stats['decode_p99_ns']/1e3:7.1f} us "
            f"({dec_tok_s:6.1f} tok/s) | "
            f"CB={cb_tok_s:6.1f} tok/s"
        )


def strip_volatile_gen(lines):
    return [l for l in lines if not l.startswith(("load_ms:", "prefill_ns:", "decode_total_ns:"))]


def check_generate_cli(exe, gguf_path, expected_toks):
    out_ids = run([exe, "generate", str(gguf_path), "ids:1,7,42", "3", "0", "40"]).splitlines()
    kv_ids = {k: v for k, v in (l.split(":", 1) for l in out_ids)}
    assert kv_ids["prompt_ids"] == "1,7,42", kv_ids
    gen_ids = [int(t) for t in kv_ids["generated_ids"].split(",")]
    assert gen_ids == expected_toks, (gen_ids, expected_toks)
    assert kv_ids["generated_text"] == "".join(f"tok_{t}" for t in expected_toks), kv_ids
    free_num, free_den = map(int, kv_ids["kv_free_after"].split("/"))
    assert free_num == free_den and free_den > 0, kv_ids

    out_txt = run([exe, "generate", str(gguf_path), "tok_1tok_7tok_42", "3", "0", "40"]).splitlines()
    assert strip_volatile_gen(out_txt) == strip_volatile_gen(out_ids), (out_txt, out_ids)

    out_samp1 = run([exe, "generate", str(gguf_path), "tok_1tok_7tok_42", "4", "800", "8"]).splitlines()
    out_samp2 = run([exe, "generate", str(gguf_path), "tok_1tok_7tok_42", "4", "800", "8"]).splitlines()
    assert strip_volatile_gen(out_samp1) == strip_volatile_gen(out_samp2), "Top-K sampling not deterministic!"
    print(f"generate CLI verified (greedy IDs={gen_ids}, vocab tokenize+decode, deterministic Top-K sampling)")


def check_batched_prefill_parity(exes, model_path, tensors, q4_data, label):
    vocab = CFG["vocab_size"]
    use_q8 = q4_data is not None
    for prompt_len in (15, 16, 17, 36):
        prompt = [(pi * 17 + 1) % vocab for pi in range(prompt_len)]
        py_toks, _ = py_run_request(tensors, prompt, 9, q4_data=q4_data, use_q8_act=use_q8)
        base_cs = None
        base_toks = None
        for name, _, exe, _ in exes:
            st = parse_bench(run([exe, "bench", str(model_path), "8", "single", str(prompt_len)]))
            assert st["prefill_tokens"] == prompt_len, st
            toks = [int(t) for t in st["tokens"].split(",")]
            assert len(toks) == 9, toks
            assert toks == py_toks, (label, prompt_len, name, toks, py_toks)
            if name == "baseline":
                base_cs = st["checksum"]
                base_toks = toks
            elif name == "fusion-strict":
                assert st["checksum"] == base_cs, (label, prompt_len, st["checksum"], base_cs)
                assert toks == base_toks, (label, prompt_len, toks, base_toks)
    print(f"Batched prefill GEMM parity passed for {label} (prompt_len=15, 16, 17 & 36 vs Python & baseline)")


def check_qwen2_gguf(exes, qwen_path, tensors, biases, q4_data, q8_data):
    py_qwen_ref = [
        py_run_request(tensors, prompt, gen, q4_data=q4_data, use_q8_act=True, q8_data=q8_data, biases=biases)
        for prompt, gen in REQUESTS
    ]
    check_format(exes, qwen_path, py_qwen_ref, "qwen2_gguf", "q4_0", "q8_0", CFG["vocab_size"])

    exe = exes[1][2]  # fusion-strict
    # Test GPT-2 unicode 'Ġ' space decoding & encoding ("Hi Paris world" -> [1, 5, 7])
    out = run([exe, "generate", str(qwen_path), "Hi Paris world", "4", "0", "40", "--ignore-eos"]).splitlines()
    kv = {k: v for k, v in (l.split(":", 1) for l in out)}
    assert kv["prompt_ids"] == "1,5,7", kv
    assert kv["kv_free_after"] == "4/4", kv

    # Verify EOS stopping when generated token matches eos_token_id=2 (or run with --ignore-eos)
    out_eos = run([exe, "generate", str(qwen_path), "Hi Paris", "4", "0", "40"]).splitlines()
    kv_eos = {k: v for k, v in (l.split(":", 1) for l in out_eos)}
    assert kv_eos["prompt_ids"] == "1,5", kv_eos
    assert kv_eos["kv_free_after"] == "4/4", kv_eos
    print("Qwen2.5-format GGUF verified (Q4_0 embed + Q8_0 output.weight SDOT + attn QKV biases + GPT-2 vocab)")


def check_tensor_calls(mir, fast):
    functions = mir_functions(mir)
    suffix = "_fast" if fast == "1" else ""
    calls = {
        "gguf_stream_q4_0_p4k4": "__xu_tensor_pack_q4_0_p4k4_signed",
        "matvec_q4_0_p4k4_q8_0": f"__xu_tensor_gemv4_q4_0_p4k4_signed_f16_q8_0{suffix}_f32",
        "matmat_q4_0_p4k4_q8_0": f"__xu_tensor_gemm4x8_q4_0_p4k4_signed_f16_q8_0{suffix}_f32",
        "gguf_stream_q8_0_p4k4": "__xu_tensor_pack_q8_0_p4k4",
        "matvec_q8_0_p4k4_q8_0": f"__xu_tensor_gemv4_q8_0_p4k4_f16_q8_0{suffix}_f32",
    }
    if platform.machine().lower() in ("arm64", "aarch64"):
        calls["matmat_q8_0_p4k4_q8_0"] = f"__xu_tensor_gemm4x8_q8_0_p4k4_f16_q8_0{suffix}_f32"
        calls["attention_scores_paged"] = f"__xu_tensor_attn_scores_paged{suffix}_f32"
        calls["softmax_scaled"] = f"__xu_tensor_softmax_scaled{suffix}_f32"
        calls["attn_vsum_paged"] = f"__xu_tensor_attn_vsum_paged{suffix}_f32"
    for caller, target in calls.items():
        assert f"call {target}(" in functions[caller], (caller, target)


def check_tied_q4(exes, work, tensors):
    path = work / "mini_tied_q4_0.gguf"
    q4_data, _ = write_gguf_q4_0(path, CFG, tensors, tied_output=True)
    assert "output.weight" not in q4_data
    # The GGUF omits the output tensor. The reference projects through the embedding rows.
    q4_data["output.weight"] = q4_data["token_embd.weight"]
    reference = [
        py_run_request(tensors, prompt, gen, q4_data=q4_data, use_q8_act=True)
        for prompt, gen in REQUESTS
    ]
    check_format(exes, path, reference, "tied Q4", "q4_0", "q8_0", CFG["vocab_size"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    source = root / "examples/llm_engine/main.xu"

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        st_path = work / "mini_qwen_f32.safetensors"
        gguf_path = work / "mini_qwen_q4_0.gguf"
        qwen_path = work / "mini_qwen2_5.gguf"

        tensors = generate_weight_dict(CFG)
        write_safetensors(st_path, CFG, tensors)
        q4_data, _ = write_gguf_q4_0(gguf_path, CFG, tensors)

        b_rng = random.Random(20261125)
        head_dim = CFG["dim"] // CFG["n_heads"]
        kv_dim = CFG["n_kv_heads"] * head_dim
        qwen_biases = [
            (
                gen_weights(b_rng, CFG["dim"], 0.05),
                gen_weights(b_rng, kv_dim, 0.05),
                gen_weights(b_rng, kv_dim, 0.05),
            )
            for _ in range(CFG["n_layers"])
        ]
        qwen_q4_data, qwen_q8_data = write_gguf_q4_0(qwen_path, CFG, tensors, biases=qwen_biases, qwen_mode=True)

        py_f32_ref = [py_run_request(tensors, prompt, gen) for prompt, gen in REQUESTS]
        py_q4_f32_ref = [py_run_request(tensors, prompt, gen, q4_data=q4_data, use_q8_act=False) for prompt, gen in REQUESTS]
        py_q4_q8_ref = [py_run_request(tensors, prompt, gen, q4_data=q4_data, use_q8_act=True) for prompt, gen in REQUESTS]

        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_MIR_BORROW_GATE="1", XU_KEEP_SYMBOLS="1")
        modes = (
            ("baseline", "0", "0"),
            ("fusion-strict", "1", "0"),
            ("fusion-fast", "1", "1"),
        )
        exes = []
        for name, fusion, fast in modes:
            exe = work / f"llm-{name}"
            check_calls = fusion == "1" and platform.machine().lower() in ("arm64", "aarch64", "x86_64", "amd64")
            build_env = dict(env, XU_TENSOR_FUSION=fusion, XU_TENSOR_FAST_MATH=fast, XU_TASK_POLL="0")
            if check_calls:
                build_env["XU_DUMP_MIR"] = "_xu_main_"
            mir = build(compiler, build_env, source, exe)
            if check_calls:
                check_tensor_calls(mir, fast)
            size_kb = exe.stat().st_size / 1024.0
            if platform.system() == "Darwin" and platform.machine() == "arm64" and fusion == "1":
                asm = run(["otool", "-tV", exe])
                if fast == "1":
                    for sym in ("___xu_tensor_quantize_q8_0_fast",
                                "___xu_tensor_gemv4_fast_f32",
                                "___xu_tensor_gemv4_q4_0_q8_0_fast_f32",
                                "___xu_tensor_gemv4_q8_0_q8_0_fast_f32",
                                "___xu_tensor_gemm4x4_fast_f32",
                                "___xu_tensor_gemm4x4_q4_0_q8_0_fast_f32",
                                "___xu_tensor_rope_f32",
                                "___xu_tensor_swiglu_fast_f32",
                                "___xu_tensor_argmax_f32",
                                "___xu_tensor_dot_fast_f32", "___xu_tensor_norm_f32",
                                "___xu_tensor_axpy_fma_f32",
                                "___xu_tensor_add_sqsum_fast_f32", "___xu_tensor_dot_q4_0_fast_f32"):
                        assert f"{sym}:" in asm, sym
                    m_gemv = re.search(r"^___xu_tensor_gemv4_fast_f32:[\s\S]*?(?=^___|\Z)", asm, re.M)[0]
                    assert "fmla.4s" in m_gemv and "faddp.4s" in m_gemv
                    m_sdot = re.search(r"^___xu_tensor_gemv4_q4_0_q8_0_fast_f32:[\s\S]*?(?=^___|\Z)", asm, re.M)[0]
                    assert "sdot.4s" in m_sdot and "addv.4s" in m_sdot and "scvtf" in m_sdot
                else:
                    for sym in ("___xu_tensor_quantize_q8_0",
                                "___xu_tensor_gemv4_f32",
                                "___xu_tensor_gemv4_q4_0_q8_0_f32",
                                "___xu_tensor_gemv4_q8_0_q8_0_f32",
                                "___xu_tensor_gemm4x4_f32",
                                "___xu_tensor_gemm4x4_q4_0_q8_0_f32",
                                "___xu_tensor_rope_f32",
                                "___xu_tensor_swiglu_f32",
                                "___xu_tensor_argmax_f32",
                                "___xu_tensor_dot_f32", "___xu_tensor_norm_f32",
                                "___xu_tensor_axpy_f32", "___xu_tensor_vadd_inplace_f32",
                                "___xu_tensor_dot_q4_0_f32"):
                        assert f"{sym}:" in asm, sym
            exes.append((name, fast, exe, size_kb))

        check_format(exes, st_path, py_f32_ref, "f32", "f32", "f32", 0)
        check_format(exes, gguf_path, py_q4_f32_ref, "q4_0xF32", "q4_0", "f32", CFG["vocab_size"],
                     verify_cmd="verify-f32act", bench_cmd="bench-f32act")
        check_format(exes, gguf_path, py_q4_q8_ref, "q4_0xQ8_0", "q4_0", "q8_0", CFG["vocab_size"],
                     verify_cmd="verify", bench_cmd="bench")
        check_tied_q4(exes, work, tensors)
        check_generate_cli(exes[1][2], gguf_path, py_q4_q8_ref[0][0])
        check_batched_prefill_parity(exes, st_path, tensors, None, "f32")
        check_batched_prefill_parity(exes, gguf_path, tensors, q4_data, "q4_0xQ8_0")
        check_qwen2_gguf(exes, qwen_path, tensors, qwen_biases, qwen_q4_data, qwen_q8_data)
        print("LLM engine verification passed (Safetensors F32, GGUF Q4_0xF32/Q8_0 SDOT, Qwen2.5 GGUF Q8_0+biases+GPT2, Batched Prefill 4x4, generate CLI)")


if __name__ == "__main__":
    main()
