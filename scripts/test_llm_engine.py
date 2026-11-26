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


def quantize_q4_k_matrix(vals):
    assert len(vals) % 256 == 0
    nb = len(vals) // 256
    raw = bytearray()
    dequant = []
    for b in range(nb):
        blk = vals[b * 256:(b + 1) * 256]
        sub_scales = []
        sub_mins = []
        q_subs = []
        for s in range(8):
            sub = blk[s * 32:(s + 1) * 32]
            lo = min(0.0, min(sub))
            hi = max(sub)
            rng = max(hi - lo, 0.0)
            sc = rng / 15.0 if rng > 0.0 else 0.0
            mn = -lo
            sub_scales.append(sc)
            sub_mins.append(mn)
            q_subs.append(sub)
        max_sc = max(sub_scales) if sub_scales else 0.0
        max_mn = max(sub_mins) if sub_mins else 0.0
        d = f32(max_sc / 63.0) if max_sc > 0.0 else 0.0
        dmin = f32(max_mn / 63.0) if max_mn > 0.0 else 0.0
        d16_b = struct.pack("<e", d)
        dmin16_b = struct.pack("<e", dmin)
        d16 = f32(struct.unpack("<e", d16_b)[0])
        dmin16 = f32(struct.unpack("<e", dmin16_b)[0])
        raw.extend(d16_b)
        raw.extend(dmin16_b)

        sc_q = [min(63, max(0, int(round(s / d16)))) if d16 > 0.0 else 0 for s in sub_scales]
        mn_q = [min(63, max(0, int(round(m / dmin16)))) if dmin16 > 0.0 else 0 for m in sub_mins]
        scales_b = bytearray(12)
        for j in range(4):
            scales_b[j] = sc_q[j] & 63
            scales_b[j + 4] = mn_q[j] & 63
        for j in range(4, 8):
            scales_b[j + 4] = (sc_q[j] & 15) | ((mn_q[j] & 15) << 4)
            scales_b[j - 4] |= ((sc_q[j] >> 4) & 3) << 6
            scales_b[j] |= ((mn_q[j] >> 4) & 3) << 6
        raw.extend(scales_b)

        qs_b = bytearray(128)
        for chunk in range(4):
            s_lo = chunk * 2
            s_hi = s_lo + 1
            d1 = f32(d16 * sc_q[s_lo])
            m1 = f32(dmin16 * mn_q[s_lo])
            d2 = f32(d16 * sc_q[s_hi])
            m2 = f32(dmin16 * mn_q[s_hi])
            sub_lo = q_subs[s_lo]
            sub_hi = q_subs[s_hi]
            ql_vals = []
            qh_vals = []
            for l in range(32):
                q0 = min(15, max(0, int(round((sub_lo[l] + m1) / d1)))) if d1 > 0.0 else 0
                q1 = min(15, max(0, int(round((sub_hi[l] + m2) / d2)))) if d2 > 0.0 else 0
                qs_b[chunk * 32 + l] = (q0 & 15) | ((q1 & 15) << 4)
                ql_vals.append(f32(f32(d1 * q0) - m1))
                qh_vals.append(f32(f32(d2 * q1) - m2))
            dequant.extend(ql_vals)
            dequant.extend(qh_vals)
        raw.extend(qs_b)
    return bytes(raw), dequant


def quantize_q6_k_matrix(vals):
    assert len(vals) % 256 == 0
    nb = len(vals) // 256
    raw = bytearray()
    dequant = []
    for b in range(nb):
        blk = vals[b * 256:(b + 1) * 256]
        amax_subs = []
        for s in range(16):
            sub = blk[s * 16:(s + 1) * 16]
            amax_subs.append(max(abs(v) for v in sub))
        max_sub = max(amax_subs)
        d = f32(max_sub / (31.0 * 127.0)) if max_sub > 0.0 else 0.0
        d16_b = struct.pack("<e", d)
        d16 = f32(struct.unpack("<e", d16_b)[0])
        sc_q = []
        for amax in amax_subs:
            qsc = min(127, max(1, int(round(amax / (31.0 * d16))))) if (d16 > 0.0 and amax > 0.0) else 0
            sc_q.append(qsc)
        ql = bytearray(128)
        qh = bytearray(64)
        dq_blk = [0.0] * 256
        for h in range(2):
            y_off = h * 128
            ql_off = h * 64
            qh_off = h * 32
            sc_off = h * 8
            for l in range(32):
                is_idx = l // 16
                quants = []
                for quad, off_s in enumerate((0, 32, 64, 96)):
                    idx = y_off + l + off_s
                    sc_val = d16 * sc_q[sc_off + is_idx + quad * 2]
                    q = min(31, max(-32, int(round(blk[idx] / sc_val)))) if sc_val != 0.0 else 0
                    quants.append(q + 32)
                    dq_blk[idx] = f32(f32(d16 * sc_q[sc_off + is_idx + quad * 2]) * q)
                q1, q2, q3, q4 = quants
                ql[ql_off + l] = (q1 & 15) | ((q3 & 15) << 4)
                ql[ql_off + l + 32] = (q2 & 15) | ((q4 & 15) << 4)
                qh[qh_off + l] = (
                    ((q1 >> 4) & 3)
                    | (((q2 >> 4) & 3) << 2)
                    | (((q3 >> 4) & 3) << 4)
                    | (((q4 >> 4) & 3) << 6)
                )
        raw.extend(ql)
        raw.extend(qh)
        raw.extend(struct.pack("<16b", *sc_q))
        raw.extend(d16_b)
        dequant.extend(dq_blk)
    return bytes(raw), dequant


def quantize_q5_0_matrix(vals):
    raw = bytearray()
    dequant = []
    for b in range(len(vals) // 32):
        seg = vals[b * 32:(b + 1) * 32]
        amax = max(abs(v) for v in seg)
        d = f32(amax / 15.0) if amax > 0 else 0.0
        d16_b = struct.pack("<e", d)
        d16 = f32(struct.unpack("<e", d16_b)[0])
        raw.extend(d16_b)
        inv_d = 1.0 / d16 if d16 != 0 else 0.0
        qs = [min(31, max(0, int(round(v * inv_d)) + 16)) for v in seg]
        qh = 0
        for j in range(32):
            if qs[j] & 16:
                qh |= 1 << j
        raw.extend(struct.pack("<I", qh))
        for j in range(16):
            raw.append((qs[j] & 15) | ((qs[16 + j] & 15) << 4))
        dequant.extend(f32((q - 16) * d16) for q in qs)
    return bytes(raw), dequant


def write_gguf_q4_0(path, cfg, tensors, biases=None, qwen_mode=False, tied_output=False,
                    encode_dense=None, merges=None, vocab_pieces=None, qk_norms=None,
                    kquant_mode=False, quant_mode=None, tok_model=None):
    dim = cfg["dim"]
    hidden = cfg["hidden_dim"]
    n_layers = cfg["n_layers"]
    n_heads = cfg["n_heads"]
    n_kv = cfg["n_kv_heads"]
    head_dim = dim // n_heads
    kv_dim = n_kv * head_dim
    vocab = cfg["vocab_size"]

    arch = "qwen2" if qwen_mode else "llama"
    if vocab_pieces is None:
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
    if tok_model is not None:
        kv_entries.extend([
            ("tokenizer.ggml.model", 8, pack_gguf_str(tok_model)),
            ("tokenizer.ggml.eos_token_id", 4, struct.pack("<I", 2)),
        ])
    elif qwen_mode:
        kv_entries.extend([
            ("tokenizer.ggml.model", 8, pack_gguf_str("gpt2")),
            ("tokenizer.ggml.bos_token_id", 4, struct.pack("<I", 0)),
            ("tokenizer.ggml.eos_token_id", 4, struct.pack("<I", 2)),
        ])
    kv_entries.append((
        "tokenizer.ggml.tokens", 9,
        struct.pack("<IQ", 8, vocab) + b"".join(pack_gguf_str(p) for p in vocab_pieces),
    ))
    if merges:
        kv_entries.append((
            "tokenizer.ggml.merges", 9,
            struct.pack("<IQ", 8, len(merges)) + b"".join(pack_gguf_str(m) for m in merges),
        ))

    tensor_specs = []
    q4_data = {}
    q8_data = {}
    dequant_data = {}

    def add_f32(gname, dims, vals):
        raw = struct.pack(f"<{len(vals)}f", *vals)
        tensor_specs.append((gname, dims, 0, raw))

    def add_dense(gname, st_key, dims, vals):
        if encode_dense is not None:
            gtype, raw = encode_dense(st_key, dims, vals)
            tensor_specs.append((gname, dims, gtype, raw))
        else:
            add_f32(gname, dims, vals)

    def add_q4(gname, dims, vals):
        raw, qs, sc = quantize_q4_0_matrix(vals)
        tensor_specs.append((gname, dims, 2, raw))
        q4_data[gname] = (qs, sc)

    def add_q8(gname, dims, vals):
        raw, qs, sc = quantize_q8_0_matrix(vals)
        tensor_specs.append((gname, dims, 8, raw))
        q8_data[gname] = (qs, sc)

    def add_q4k(gname, dims, vals):
        raw, dq = quantize_q4_k_matrix(vals)
        tensor_specs.append((gname, dims, 12, raw))
        dequant_data[gname] = dq

    def add_q6k(gname, dims, vals):
        raw, dq = quantize_q6_k_matrix(vals)
        tensor_specs.append((gname, dims, 14, raw))
        dequant_data[gname] = dq

    def add_q5(gname, dims, vals):
        raw, dq = quantize_q5_0_matrix(vals)
        tensor_specs.append((gname, dims, 6, raw))
        dequant_data[gname] = dq

    def add_q8_dq(gname, dims, vals):
        raw, qs, sc = quantize_q8_0_matrix(vals)
        tensor_specs.append((gname, dims, 8, raw))
        dequant_data[gname] = [f32(qs[i] * sc[i // 32]) for i in range(len(vals))]

    def add_matrix(gname, st_key, dims, vals):
        if kquant_mode:
            if gname.endswith("attn_v.weight") or gname.endswith("ffn_down.weight"):
                add_q6k(gname, dims, vals)
            else:
                add_q4k(gname, dims, vals)
        elif quant_mode == "q5_0":
            add_q5(gname, dims, vals)
        elif quant_mode == "q8_0":
            add_q8_dq(gname, dims, vals)
        elif encode_dense is not None:
            add_dense(gname, st_key, dims, vals)
        else:
            add_q4(gname, dims, vals)

    if kquant_mode:
        add_q6k("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    elif quant_mode == "q5_0":
        add_q5("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    elif quant_mode == "q8_0":
        add_q8_dq("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    elif encode_dense is not None:
        add_dense("token_embd.weight", "embed_tokens.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    elif qwen_mode or tied_output:
        add_q4("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    else:
        add_f32("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    for l in range(n_layers):
        p = f"layers.{l}."
        gp = f"blk.{l}."
        add_dense(gp + "attn_norm.weight", p + "input_layernorm.weight", [dim], tensors[p + "input_layernorm.weight"][1])
        add_matrix(gp + "attn_q.weight", p + "self_attn.q_proj.weight", [dim, dim], tensors[p + "self_attn.q_proj.weight"][1])
        add_matrix(gp + "attn_k.weight", p + "self_attn.k_proj.weight", [dim, kv_dim], tensors[p + "self_attn.k_proj.weight"][1])
        add_matrix(gp + "attn_v.weight", p + "self_attn.v_proj.weight", [dim, kv_dim], tensors[p + "self_attn.v_proj.weight"][1])
        if biases is not None:
            add_f32(gp + "attn_q.bias", [dim], biases[l][0])
            add_f32(gp + "attn_k.bias", [kv_dim], biases[l][1])
            add_f32(gp + "attn_v.bias", [kv_dim], biases[l][2])
        if qk_norms is not None:
            add_f32(gp + "attn_q_norm.weight", [head_dim], qk_norms[l][0])
            add_f32(gp + "attn_k_norm.weight", [head_dim], qk_norms[l][1])
        add_matrix(gp + "attn_output.weight", p + "self_attn.o_proj.weight", [dim, dim], tensors[p + "self_attn.o_proj.weight"][1])
        add_dense(gp + "ffn_norm.weight", p + "post_attention_layernorm.weight", [dim], tensors[p + "post_attention_layernorm.weight"][1])
        add_matrix(gp + "ffn_gate.weight", p + "mlp.gate_proj.weight", [dim, hidden], tensors[p + "mlp.gate_proj.weight"][1])
        add_matrix(gp + "ffn_up.weight", p + "mlp.up_proj.weight", [dim, hidden], tensors[p + "mlp.up_proj.weight"][1])
        add_matrix(gp + "ffn_down.weight", p + "mlp.down_proj.weight", [hidden, dim], tensors[p + "mlp.down_proj.weight"][1])
    add_dense("output_norm.weight", "norm.weight", [dim], tensors["norm.weight"][1])
    if not tied_output:
        if kquant_mode:
            add_q6k("output.weight", [dim, vocab], tensors["lm_head.weight"][1])
        elif quant_mode == "q5_0":
            add_q5("output.weight", [dim, vocab], tensors["lm_head.weight"][1])
        elif quant_mode == "q8_0":
            add_q8_dq("output.weight", [dim, vocab], tensors["lm_head.weight"][1])
        elif encode_dense is not None:
            add_dense("output.weight", "lm_head.weight", [dim, vocab], tensors["lm_head.weight"][1])
        elif qwen_mode:
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
        tpad = (32 - (len(payload) % 32)) % 32
        payload.extend(b"\x00" * tpad)
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
    if kquant_mode or quant_mode in ("q5_0", "q8_0"):
        return dequant_data, None
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


def py_head_rmsnorm(vec, n_heads, head_dim, weight):
    out = list(vec)
    for h in range(n_heads):
        off = h * head_dim
        part = out[off:off + head_dim]
        normed = py_rmsnorm(part, [0.0] * head_dim, weight)
        for j in range(head_dim):
            out[off + j] = normed[j]
    return out


def py_run_request(tensors, prompt, max_gen, q4_data=None, use_q8_act=False, q8_data=None,
                   biases=None, qk_norms=None, dequant_data=None):
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
        if dequant_data is not None and gguf_name in dequant_data:
            return py_matvec(x, dequant_data[gguf_name], rows, cols)
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

    if dequant_data is not None and "token_embd.weight" in dequant_data:
        embed = dequant_data["token_embd.weight"]
    elif q4_data is not None and "token_embd.weight" in q4_data:
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
            if qk_norms is not None:
                q_raw = py_head_rmsnorm(q_raw, n_heads, head_dim, qk_norms[l][0])
                k_raw = py_head_rmsnorm(k_raw, n_kv, head_dim, qk_norms[l][1])
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
            tol = (2e-2 if want_fmt == "q4_0" else (1e-3 if want_fmt in ("q4_k", "q6_k") else 1e-4)) if fast == "1" else (1e-4 if want_fmt in ("q4_k", "q6_k") else 1e-5)
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


def check_large_dim_and_head128(exe, work):
    dim = 2176  # > 2048 RMS_CAP, head_dim = 128
    hidden = 32
    kv_dim = 128
    vocab = 64
    cfg = {
        "dim": dim,
        "hidden_dim": hidden,
        "n_layers": 1,
        "n_heads": 17,
        "n_kv_heads": 1,
        "vocab_size": vocab,
        "max_seq_len": 16,
        "rope_theta": 10000,
    }
    def fast_vals(n, scale):
        pat = [scale * ((i % 7) - 3) for i in range(64)]
        return (pat * ((n + 63) // 64))[:n]
    tensors = {
        "embed_tokens.weight": ([vocab, dim], fast_vals(vocab * dim, 0.02)),
        "layers.0.input_layernorm.weight": ([dim], [1.0] * dim),
        "layers.0.self_attn.q_proj.weight": ([dim, dim], fast_vals(dim * dim, 0.005)),
        "layers.0.self_attn.k_proj.weight": ([kv_dim, dim], fast_vals(kv_dim * dim, 0.005)),
        "layers.0.self_attn.v_proj.weight": ([kv_dim, dim], fast_vals(kv_dim * dim, 0.005)),
        "layers.0.self_attn.o_proj.weight": ([dim, dim], fast_vals(dim * dim, 0.005)),
        "layers.0.post_attention_layernorm.weight": ([dim], [1.0] * dim),
        "layers.0.mlp.gate_proj.weight": ([hidden, dim], fast_vals(hidden * dim, 0.01)),
        "layers.0.mlp.up_proj.weight": ([hidden, dim], fast_vals(hidden * dim, 0.01)),
        "layers.0.mlp.down_proj.weight": ([dim, hidden], fast_vals(dim * hidden, 0.01)),
        "norm.weight": ([dim], [1.0] * dim),
        "lm_head.weight": ([vocab, dim], fast_vals(vocab * dim, 0.02)),
    }
    large_path = work / "large_dim_hd128_f32.safetensors"
    write_safetensors(large_path, cfg, tensors)
    v_out = run([exe, "verify", str(large_path)])
    seq, cb, meta = parse_verify(v_out)
    assert seq and seq == cb, "large_dim head_dim=128 sequential vs continuous batching mismatch"
    free_num, free_den = map(int, meta["kv_free_after"].split("/"))
    assert free_num == free_den and free_den > 0, meta
    assert int(meta["kv_storage_bytes"]) > 0, meta
    for req in seq.values():
        assert all(math.isfinite(bits_to_f32(b)) for _, b in req)
    print("Large dim (>2048 RMS_CAP) & head_dim=128 Safetensors verification passed")


def check_bpe_and_sampling(exe, work, cfg, tensors, qwen_biases):
    vocab = cfg["vocab_size"]
    vocab_pieces = [f"tok_{i}" for i in range(vocab)]
    vocab_pieces[0] = "<|endoftext|>"
    vocab_pieces[2] = "<|im_end|>"
    vocab_pieces[3] = "bc"
    vocab_pieces[4] = "ab"
    vocab_pieces[5] = "a"
    vocab_pieces[6] = "b"
    vocab_pieces[7] = "c"
    bpe_path = work / "bpe_merges.gguf"
    write_gguf_q4_0(
        bpe_path, cfg, tensors, biases=qwen_biases, qwen_mode=True,
        merges=["b c"], vocab_pieces=vocab_pieces,
    )
    out = run([exe, "generate", str(bpe_path), "abc", "3", "0", "40", "--ignore-eos"]).splitlines()
    kv = {k: v for k, v in (l.split(":", 1) for l in out)}
    assert kv["prompt_ids"] == "5,3", f"Expected BPE merge 'b c' -> [5,3], got {kv}"

    s1 = run([exe, "generate", str(bpe_path), "abc", "4", "800", "16",
              "--top-p", "750", "--repeat-penalty", "1250", "--seed", "77", "--ignore-eos"]).splitlines()
    s2 = run([exe, "generate", str(bpe_path), "abc", "4", "800", "16",
              "--top-p", "750", "--repeat-penalty", "1250", "--seed", "77", "--ignore-eos"]).splitlines()
    assert strip_volatile_gen(s1) == strip_volatile_gen(s2), "Top-p + repeat-penalty sampling not deterministic with seed"
    print("BPE merges tokenization & top-p/repeat-penalty/seed sampling verified")


def check_serve_http(exe, gguf_path):
    import json
    import subprocess
    import time
    import urllib.request

    proc = subprocess.Popen(
        [str(exe), "serve", str(gguf_path), "127.0.0.1:0", "--kv-dtype", "f16"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.02)
                continue
            line = line.strip()
            if line.startswith("serving:http://"):
                base_url = line.split("serving:", 1)[1]
                break
        if not base_url:
            err_txt = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"serve did not announce listening URL (rc={proc.poll()}): {err_txt}")

        with urllib.request.urlopen(base_url + "/health", timeout=5) as resp:
            assert resp.status == 200
            assert json.loads(resp.read().decode())["status"] == "ok"

        with urllib.request.urlopen(base_url + "/v1/models", timeout=5) as resp:
            assert resp.status == 200
            m_data = json.loads(resp.read().decode())
            assert m_data["object"] == "list" and len(m_data["data"]) == 1

        req = urllib.request.Request(
            base_url + "/v1/completions",
            data=json.dumps({"prompt": "ids:1,7,42", "max_tokens": 3, "temperature": 0.0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            c_data = json.loads(resp.read().decode())
            assert c_data["object"] == "text_completion"
            assert c_data["usage"]["prompt_tokens"] == 3
            assert c_data["usage"]["completion_tokens"] == 3
            assert len(c_data["choices"]) == 1

        chat_req = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": "ids:1,7,42"}],
                "max_tokens": 2,
                "temperature": 0.0,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(chat_req, timeout=5) as resp:
            assert resp.status == 200
            ch_data = json.loads(resp.read().decode())
            assert ch_data["object"] == "chat.completion"
            assert ch_data["choices"][0]["message"]["role"] == "assistant"
            assert ch_data["usage"]["completion_tokens"] == 2
            full_chat_text = ch_data["choices"][0]["message"]["content"]

        # Test SSE streaming on /v1/chat/completions
        stream_req = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": "ids:1,7,42"}],
                "max_tokens": 2,
                "temperature": 0.0,
                "stream": True,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(stream_req, timeout=5) as resp:
            assert resp.status == 200
            ctype = resp.headers.get("Content-Type", "")
            assert "text/event-stream" in ctype, ctype
            sse_raw = resp.read().decode()
        events = [line[6:] for line in sse_raw.splitlines() if line.startswith("data: ")]
        assert events and events[-1] == "[DONE]", events
        streamed_text = ""
        for ev in events[:-1]:
            obj = json.loads(ev)
            assert obj["object"] == "chat.completion.chunk"
            delta = obj["choices"][0]["delta"]
            if "content" in delta:
                streamed_text += delta["content"]
        assert streamed_text == full_chat_text, (streamed_text, full_chat_text)

        # Test stop sequence truncation on /v1/completions
        stop_tok = c_data["choices"][0]["text"][:5]
        stop_req = urllib.request.Request(
            base_url + "/v1/completions",
            data=json.dumps({
                "prompt": "ids:1,7,42",
                "max_tokens": 3,
                "temperature": 0.0,
                "stop": [stop_tok],
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(stop_req, timeout=5) as resp:
            assert resp.status == 200
            s_data = json.loads(resp.read().decode())
            assert s_data["choices"][0]["text"] == "", s_data
            assert s_data["choices"][0]["finish_reason"] == "stop", s_data

        # Test /v1/embeddings
        emb_req = urllib.request.Request(
            base_url + "/v1/embeddings",
            data=json.dumps({"input": "ids:1,7,42"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(emb_req, timeout=5) as resp:
            assert resp.status == 200
            e_data = json.loads(resp.read().decode())
            assert e_data["object"] == "list"
            vec = e_data["data"][0]["embedding"]
            assert len(vec) == CFG["dim"], (len(vec), CFG["dim"])
            assert all(math.isfinite(x) for x in vec)
            l2 = math.sqrt(sum(x * x for x in vec))
            assert abs(l2 - 1.0) < 1e-3, l2
            assert e_data["usage"]["prompt_tokens"] == 3

        # Test concurrent continuous batching in HTTP serve (SSE stream + completion in flight together)
        import concurrent.futures

        def do_concurrent_stream():
            s_req = urllib.request.Request(
                base_url + "/v1/chat/completions",
                data=json.dumps({
                    "messages": [{"role": "user", "content": "ids:1,7,42"}],
                    "max_tokens": 3,
                    "temperature": 0.0,
                    "stream": True,
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(s_req, timeout=10) as resp:
                assert resp.status == 200
                return resp.read().decode()

        def do_concurrent_comp():
            c_req = urllib.request.Request(
                base_url + "/v1/completions",
                data=json.dumps({
                    "prompt": "ids:5,11,23",
                    "max_tokens": 3,
                    "temperature": 0.0,
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(c_req, timeout=10) as resp:
                assert resp.status == 200
                return json.loads(resp.read().decode())

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_st = pool.submit(do_concurrent_stream)
            f_cm = pool.submit(do_concurrent_comp)
            sse2 = f_st.result(timeout=10)
            cm2 = f_cm.result(timeout=10)
        evs2 = [line[6:] for line in sse2.splitlines() if line.startswith("data: ")]
        assert evs2 and evs2[-1] == "[DONE]", evs2
        txt2 = "".join(json.loads(ev)["choices"][0]["delta"].get("content", "") for ev in evs2[:-1])
        assert txt2 == c_data["choices"][0]["text"], (txt2, c_data)
        assert cm2["usage"]["prompt_tokens"] == 3 and cm2["usage"]["completion_tokens"] == 3

        # Test Prefix KV Cache reuse: same prompt prefix on subsequent requests
        pfx_a = urllib.request.Request(
            base_url + "/v1/completions",
            data=json.dumps({"prompt": "ids:1,7,42,3", "max_tokens": 3, "temperature": 0.0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(pfx_a, timeout=5) as resp:
            out_a = json.loads(resp.read().decode())["choices"][0]["text"]
        pfx_b = urllib.request.Request(
            base_url + "/v1/completions",
            data=json.dumps({"prompt": "ids:1,7,42,9", "max_tokens": 3, "temperature": 0.0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(pfx_b, timeout=5) as resp:
            out_b = json.loads(resp.read().decode())["choices"][0]["text"]
        # Verify cached output on ids:1,7,42,9 equals uncached generate CLI output!
        gen_ref = run([exe, "generate", str(gguf_path), "ids:1,7,42,9", "3", "0", "40"]).splitlines()
        gen_kv = {k: v for k, v in (l.split(":", 1) for l in gen_ref)}
        assert out_b == gen_kv["generated_text"], (out_b, gen_kv["generated_text"], out_a)

        with urllib.request.urlopen(base_url + "/health", timeout=5) as resp:
            h_data = json.loads(resp.read().decode())
            assert h_data["status"] == "ok"
            assert h_data["max_slots"] == 4, h_data
            assert h_data["prefix_cache_hits"] >= 1, h_data
            assert h_data["prefix_cache_tokens"] >= 3, h_data

        print(f"OpenAI-compatible HTTP serve mode verified (continuous batching, prefix cache hits={h_data['prefix_cache_hits']}, SSE stream, stop, embeddings @ {base_url})")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def check_serve_chatml(exe, work, cfg, tensors):
    import json
    import subprocess
    import time
    import urllib.request

    vocab = cfg["vocab_size"]
    vocab_pieces = [f"tok_{i}" for i in range(vocab)]
    vocab_pieces[0] = "<|endoftext|>"
    vocab_pieces[1] = "<|im_start|>"
    vocab_pieces[2] = "<|im_end|>"
    vocab_pieces[3] = "user"
    vocab_pieces[4] = "assistant"
    vocab_pieces[5] = "\u0120hi"
    vocab_pieces[6] = "\u010a"  # GPT-2 newline '\n' -> U+010A
    chat_path = work / "mini_chatml.gguf"
    write_gguf_q4_0(chat_path, cfg, tensors, qwen_mode=True, vocab_pieces=vocab_pieces)

    # Expected ChatML prompt tokens: [<|im_start|>, user, \n, tok..., <|im_end|>, \n, <|im_start|>, assistant, \n]
    proc = subprocess.Popen(
        [str(exe), "serve", str(chat_path), "127.0.0.1:0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        base_url = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line and line.strip().startswith("serving:http://"):
                base_url = line.strip().split("serving:", 1)[1]
                break
        assert base_url
        req = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": " hi"}],
                "max_tokens": 2,
                "temperature": 0.0,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            assert data["usage"]["prompt_tokens"] == 9, data
        print("ChatML template + special-token encoding verified in HTTP serve")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def check_q4_k_q6_k_gguf(exes, work, tensors):
    path = work / "mini_q4_k_m.gguf"
    dequant_data, _ = write_gguf_q4_k_m = write_gguf_q4_0(path, CFG, tensors, kquant_mode=True)
    py_ref = [
        py_run_request(tensors, prompt, gen, dequant_data=dequant_data)
        for prompt, gen in REQUESTS
    ]
    check_format(exes, path, py_ref, "Q4_K_M", "q4_k", "f32", CFG["vocab_size"])


def check_qk_norm_gguf(exes, work, tensors):
    rng = random.Random(20261126)
    head_dim = CFG["dim"] // CFG["n_heads"]
    qk_norms = [
        (
            [f32(0.75 + 0.5 * rng.random()) for _ in range(head_dim)],
            [f32(0.80 + 0.4 * rng.random()) for _ in range(head_dim)],
        )
        for _ in range(CFG["n_layers"])
    ]
    path = work / "mini_qknorm.gguf"
    q4_data, _ = write_gguf_q4_0(path, CFG, tensors, qk_norms=qk_norms)
    py_ref = [
        py_run_request(tensors, prompt, gen, q4_data=q4_data, use_q8_act=True, qk_norms=qk_norms)
        for prompt, gen in REQUESTS
    ]
    check_format(exes, path, py_ref, "qk_norm", "q4_0", "q8_0", CFG["vocab_size"])


def check_q5_0_and_q8_0_layer_gguf(exes, work, tensors):
    q5_path = work / "mini_q5_0.gguf"
    q5_dq, _ = write_gguf_q4_0(q5_path, CFG, tensors, quant_mode="q5_0")
    py_q5 = [py_run_request(tensors, prompt, gen, dequant_data=q5_dq) for prompt, gen in REQUESTS]
    check_format(exes, q5_path, py_q5, "Q5_0", "q5_0", "f32", CFG["vocab_size"])

    q8_path = work / "mini_q8_0_layers.gguf"
    q8_dq, _ = write_gguf_q4_0(q8_path, CFG, tensors, quant_mode="q8_0")
    py_q8 = [py_run_request(tensors, prompt, gen, dequant_data=q8_dq) for prompt, gen in REQUESTS]
    check_format(exes, q8_path, py_q8, "Q8_0_layers", "q8_0", "f32", CFG["vocab_size"],
                 verify_cmd="verify-f32act", bench_cmd="bench-f32act")


def check_extended_sampling_and_spm(exe, work, cfg, tensors):
    vocab = cfg["vocab_size"]
    vocab_pieces = [f"tok_{i}" for i in range(vocab)]
    vocab_pieces[0] = "<|endoftext|>"
    vocab_pieces[1] = "<|begin_of_text|>"
    vocab_pieces[2] = "<|eot_id|>"
    vocab_pieces[3] = "<|start_header_id|>"
    vocab_pieces[4] = "<|end_header_id|>"
    vocab_pieces[5] = "user"
    vocab_pieces[6] = "assistant"
    vocab_pieces[7] = "\n"
    vocab_pieces[8] = "\u2581hello"
    vocab_pieces[9] = "\u2581world"
    vocab_pieces[10] = "\u2581"
    vocab_pieces[11] = "<0x41>"

    spm_path = work / "mini_spm_llama3.gguf"
    write_gguf_q4_0(spm_path, cfg, tensors, vocab_pieces=vocab_pieces, tok_model="llama")

    # SentencePiece '▁' word boundaries + <0xHH> byte fallback
    out1 = run([exe, "generate", str(spm_path), "hello world", "3", "0", "40", "--ignore-eos"]).splitlines()
    kv1 = {k: v for k, v in (l.split(":", 1) for l in out1)}
    assert kv1["prompt_ids"] == "8,9", kv1

    out2 = run([exe, "generate", str(spm_path), "A", "2", "0", "40", "--ignore-eos"]).splitlines()
    kv2 = {k: v for k, v in (l.split(":", 1) for l in out2)}
    assert kv2["prompt_ids"] == "10,11", kv2

    # Extended sampling: min_p + presence_penalty + frequency_penalty + top_k > 64
    s1 = run([exe, "generate", str(spm_path), "hello world", "6", "900", "128",
              "--min-p", "150", "--presence-penalty", "500", "--frequency-penalty", "250",
              "--seed", "99", "--ignore-eos"]).splitlines()
    s2 = run([exe, "generate", str(spm_path), "hello world", "6", "900", "128",
              "--min-p", "150", "--presence-penalty", "500", "--frequency-penalty", "250",
              "--seed", "99", "--ignore-eos"]).splitlines()
    assert strip_volatile_gen(s1) == strip_volatile_gen(s2), "Extended sampling not deterministic"
    kvs = {k: v for k, v in (l.split(":", 1) for l in s1)}
    assert len(kvs["generated_ids"].split(",")) == 6, kvs
    print("SentencePiece ('▁'/<0xHH>) and extended sampling (min_p/presence/frequency/top_k>64) verified")
    return spm_path


def check_serve_enterprise_features(exe, spm_path):
    from concurrent.futures import ThreadPoolExecutor
    import json
    import socket
    import subprocess
    import time
    import urllib.error
    import urllib.request

    proc = subprocess.Popen(
        [str(exe), "serve", str(spm_path), "127.0.0.1:0", "--max-slots", "2", "--api-key", "test-key-42"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        base_url = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line and line.strip().startswith("serving:http://"):
                base_url = line.strip().split("serving:", 1)[1]
                break
        assert base_url

        # 1. CORS OPTIONS preflight (unauthenticated OK) + /health max_slots=2
        opt_req = urllib.request.Request(base_url + "/v1/chat/completions", method="OPTIONS")
        with urllib.request.urlopen(opt_req, timeout=5) as resp:
            assert resp.status == 204, resp.status
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"
            assert "Authorization" in resp.headers.get("Access-Control-Allow-Headers", "")

        with urllib.request.urlopen(base_url + "/health", timeout=5) as resp:
            hdata = json.loads(resp.read().decode())
            assert hdata["max_slots"] == 2, hdata

        # 2. --api-key Bearer authentication enforcement on /v1/*
        try:
            urllib.request.urlopen(base_url + "/v1/models", timeout=5)
            raise AssertionError("Expected HTTP 401 without Authorization header")
        except urllib.error.HTTPError as e:
            assert e.code == 401, e.code
        auth_headers = {"Content-Type": "application/json", "Authorization": "Bearer test-key-42"}
        with urllib.request.urlopen(urllib.request.Request(base_url + "/v1/models", headers=auth_headers), timeout=5) as resp:
            assert resp.status == 200
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"

        # 3. Batch /v1/embeddings
        emb_req = urllib.request.Request(
            base_url + "/v1/embeddings",
            data=json.dumps({"input": ["hello world", "A"]}).encode(),
            headers=auth_headers,
            method="POST",
        )
        with urllib.request.urlopen(emb_req, timeout=5) as resp:
            edata = json.loads(resp.read().decode())
            assert len(edata["data"]) == 2, edata
            assert edata["data"][0]["index"] == 0 and edata["data"][1]["index"] == 1
            assert edata["usage"]["prompt_tokens"] == 4, edata

        # 4. Llama-3 chat template + stream_options.include_usage
        chat_stream_req = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": " hello world"}],
                "max_tokens": 3,
                "temperature": 0.0,
                "stream": True,
                "stream_options": {"include_usage": True},
            }).encode(),
            headers=auth_headers,
            method="POST",
        )
        with urllib.request.urlopen(chat_stream_req, timeout=5) as resp:
            sse_raw = resp.read().decode()
        events = [line[6:] for line in sse_raw.splitlines() if line.startswith("data: ")]
        assert len(events) >= 3 and events[-1] == "[DONE]", events
        usage_chunk = json.loads(events[-2])
        assert usage_chunk["choices"] == [], usage_chunk
        assert usage_chunk["usage"]["prompt_tokens"] == 14, usage_chunk
        assert usage_chunk["usage"]["completion_tokens"] == 3, usage_chunk

        # 5. Client-disconnect SSE cancellation frees slot & KV blocks
        host_port = base_url.split("http://", 1)[1]
        host, port_str = host_port.split(":", 1)
        sock = socket.create_connection((host, int(port_str)), timeout=5)
        payload = json.dumps({"prompt": "ids:1,7,42", "max_tokens": 16, "temperature": 0.0, "stream": True}).encode()
        raw_http = (
            f"POST /v1/completions HTTP/1.1\r\nHost: {host_port}\r\n"
            f"Authorization: Bearer test-key-42\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
        ).encode() + payload
        sock.sendall(raw_http)
        first_chunk = sock.recv(512)
        assert b"text/event-stream" in first_chunk, first_chunk
        sock.close()
        time.sleep(0.25)
        with urllib.request.urlopen(base_url + "/health", timeout=5) as resp:
            h_after = json.loads(resp.read().decode())
            assert h_after["active_slots"] == 0, h_after
            assert h_after["kv_free_blocks"] == h_after["kv_total_blocks"], h_after

        # 6. Concurrent multi-slot batched decode in serve
        def do_cmpl(idx):
            req = urllib.request.Request(
                base_url + "/v1/completions",
                data=json.dumps({
                    "prompt": f"ids:{1 + idx},{5 + idx}",
                    "max_tokens": 4,
                    "temperature": 0.0,
                    "ignore_eos": True,
                }).encode(),
                headers=auth_headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())["choices"][0]["text"]

        with ThreadPoolExecutor(max_workers=3) as pool:
            batch_texts = list(pool.map(do_cmpl, [0, 1, 2]))
        seq_texts = [do_cmpl(i) for i in range(3)]
        assert batch_texts == seq_texts, (batch_texts, seq_texts)
        print("Enterprise serve verified (CORS, --api-key, --max-slots, batch embeddings, Llama-3 template, include_usage, SSE cancel, concurrent batched decode)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


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
        check_large_dim_and_head128(exes[1][2], work)
        check_bpe_and_sampling(exes[1][2], work, CFG, tensors, qwen_biases)
        check_q4_k_q6_k_gguf(exes, work, tensors)
        check_qk_norm_gguf(exes, work, tensors)
        check_q5_0_and_q8_0_layer_gguf(exes, work, tensors)
        spm_path = check_extended_sampling_and_spm(exes[1][2], work, CFG, tensors)
        check_serve_http(exes[1][2], gguf_path)
        check_serve_chatml(exes[1][2], work, CFG, tensors)
        check_serve_enterprise_features(exes[1][2], spm_path)
        print("LLM engine verification passed (Safetensors F32, GGUF Q4_0/Q5_0/Q8_0/Q4_K_M, qk_norm, ChatML/Llama-3, SPM, continuous batch HTTP serve + prefix cache)")


if __name__ == "__main__":
    main()
