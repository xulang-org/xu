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


def quantize_q5_k_matrix(vals):
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
            sc = rng / 31.0 if rng > 0.0 else 0.0
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

        qh_b = bytearray(32)
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
                q0 = min(31, max(0, int(round((sub_lo[l] + m1) / d1)))) if d1 > 0.0 else 0
                q1 = min(31, max(0, int(round((sub_hi[l] + m2) / d2)))) if d2 > 0.0 else 0
                qs_b[chunk * 32 + l] = (q0 & 15) | ((q1 & 15) << 4)
                if q0 & 16:
                    qh_b[l] |= 1 << (chunk * 2)
                if q1 & 16:
                    qh_b[l] |= 1 << (chunk * 2 + 1)
                ql_vals.append(f32(f32(d1 * q0) - m1))
                qh_vals.append(f32(f32(d2 * q1) - m2))
            dequant.extend(ql_vals)
            dequant.extend(qh_vals)
        raw.extend(qh_b)
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
                    kquant_mode=False, quant_mode=None, tok_model=None,
                    arch_name=None, extra_kv=None, post_norms=None, return_q8_all=False, moe=None):
    dim = cfg["dim"]
    hidden = cfg["hidden_dim"]
    n_layers = cfg["n_layers"]
    n_heads = cfg["n_heads"]
    n_kv = cfg["n_kv_heads"]
    head_dim = dim // n_heads
    kv_dim = n_kv * head_dim
    vocab = cfg["vocab_size"]

    arch = arch_name if arch_name is not None else ("qwen2" if qwen_mode else "llama")
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
    if extra_kv:
        kv_entries.extend(extra_kv)

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

    def add_q5k(gname, dims, vals):
        raw, dq = quantize_q5_k_matrix(vals)
        tensor_specs.append((gname, dims, 13, raw))
        dequant_data[gname] = dq

    def add_q8_dq(gname, dims, vals):
        raw, qs, sc = quantize_q8_0_matrix(vals)
        tensor_specs.append((gname, dims, 8, raw))
        q8_data[gname] = (qs, sc)
        dequant_data[gname] = [f32(qs[i] * sc[i // 32]) for i in range(len(vals))]

    def add_matrix(gname, st_key, dims, vals):
        if kquant_mode:
            if gname.endswith("attn_v.weight") or gname.endswith("ffn_down.weight"):
                add_q6k(gname, dims, vals)
            else:
                add_q4k(gname, dims, vals)
        elif quant_mode == "q5_0":
            add_q5(gname, dims, vals)
        elif quant_mode == "q5_k":
            add_q5k(gname, dims, vals)
        elif quant_mode == "q8_0":
            add_q8_dq(gname, dims, vals)
        elif quant_mode == "f32":
            add_f32(gname, dims, vals)
            dequant_data[gname] = [f32(v) for v in vals]
        elif encode_dense is not None:
            add_dense(gname, st_key, dims, vals)
        else:
            add_q4(gname, dims, vals)

    def add_f16_dequant(gname, dims, vals):
        raw = struct.pack(f"<{len(vals)}e", *[float(v) for v in vals])
        tensor_specs.append((gname, dims, 1, raw))
        dequant_data[gname] = [f32(struct.unpack("<e", struct.pack("<e", float(v)))[0]) for v in vals]

    if kquant_mode:
        add_q6k("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    elif quant_mode == "q5_0":
        add_q5("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
    elif quant_mode == "q5_k":
        add_q5k("token_embd.weight", [dim, vocab], tensors["embed_tokens.weight"][1])
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
        add_dense(gp + "attn_output.weight", p + "self_attn.o_proj.weight", [dim, dim], tensors[p + "self_attn.o_proj.weight"][1]) if False else add_matrix(gp + "attn_output.weight", p + "self_attn.o_proj.weight", [dim, dim], tensors[p + "self_attn.o_proj.weight"][1])
        if post_norms is not None:
            add_f32(gp + "post_attention_norm.weight", [dim], post_norms[l][0])
            add_f32(gp + "ffn_post_norm.weight", [dim], post_norms[l][1])
        add_dense(gp + "ffn_norm.weight", p + "post_attention_layernorm.weight", [dim], tensors[p + "post_attention_layernorm.weight"][1])
        if moe is not None and l < len(moe["layers"]):
            ml = moe["layers"][l]
            exp_cnt = moe["expert_count"]
            exp_h = moe["expert_hidden_dim"]
            if moe.get("router_f16"):
                add_f16_dequant(gp + "ffn_gate_inp.weight", [dim, exp_cnt], ml["gate_inp"])
            else:
                add_f32(gp + "ffn_gate_inp.weight", [dim, exp_cnt], ml["gate_inp"])
                dequant_data[gp + "ffn_gate_inp.weight"] = [f32(v) for v in ml["gate_inp"]]
            if ml.get("bias") is not None:
                add_f32(gp + "ffn_exp_probs_b.bias", [exp_cnt], ml["bias"])
            if moe.get("packed_3d"):
                for kind, key, dims3 in (
                    ("ffn_gate_exps.weight", "w1_exps", [dim, exp_h, exp_cnt]),
                    ("ffn_up_exps.weight", "w3_exps", [dim, exp_h, exp_cnt]),
                    ("ffn_down_exps.weight", "w2_exps", [exp_h, dim, exp_cnt]),
                ):
                    raw_all = bytearray()
                    base_k = kind.replace("_exps.weight", "")
                    for e_i, evals in enumerate(ml[key]):
                        ekey = f"{gp}{base_k}.{e_i}.weight"
                        if quant_mode == "f32":
                            raw_all.extend(struct.pack(f"<{len(evals)}f", *evals))
                            dequant_data[ekey] = [f32(v) for v in evals]
                        else:
                            eraw, eqs, esc = quantize_q4_0_matrix(evals)
                            raw_all.extend(eraw)
                            q4_data[ekey] = (eqs, esc)
                    tensor_specs.append((gp + kind, dims3, 0 if quant_mode == "f32" else 2, bytes(raw_all)))
            else:
                for e_i in range(exp_cnt):
                    add_matrix(f"{gp}ffn_gate.{e_i}.weight", "", [dim, exp_h], ml["w1_exps"][e_i])
                    add_matrix(f"{gp}ffn_up.{e_i}.weight", "", [dim, exp_h], ml["w3_exps"][e_i])
                    add_matrix(f"{gp}ffn_down.{e_i}.weight", "", [exp_h, dim], ml["w2_exps"][e_i])
            if moe.get("shared_hidden_dim", 0) > 0:
                sh_h = moe["shared_hidden_dim"]
                add_matrix(gp + "ffn_gate_shexp.weight", "", [dim, sh_h], ml["sh_w1"])
                add_matrix(gp + "ffn_up_shexp.weight", "", [dim, sh_h], ml["sh_w3"])
                add_matrix(gp + "ffn_down_shexp.weight", "", [sh_h, dim], ml["sh_w2"])
                if ml.get("sh_gate_inp") is not None:
                    if moe.get("router_f16"):
                        add_f16_dequant(gp + "ffn_gate_inp_shexp.weight", [dim, 1], ml["sh_gate_inp"])
                    else:
                        add_f32(gp + "ffn_gate_inp_shexp.weight", [dim, 1], ml["sh_gate_inp"])
                        dequant_data[gp + "ffn_gate_inp_shexp.weight"] = [f32(v) for v in ml["sh_gate_inp"]]
        else:
            add_matrix(gp + "ffn_gate.weight", p + "mlp.gate_proj.weight", [dim, hidden], tensors[p + "mlp.gate_proj.weight"][1])
            add_matrix(gp + "ffn_up.weight", p + "mlp.up_proj.weight", [dim, hidden], tensors[p + "mlp.up_proj.weight"][1])
            add_matrix(gp + "ffn_down.weight", p + "mlp.down_proj.weight", [hidden, dim], tensors[p + "mlp.down_proj.weight"][1])
    add_dense("output_norm.weight", "norm.weight", [dim], tensors["norm.weight"][1])
    if not tied_output:
        if kquant_mode:
            add_q6k("output.weight", [dim, vocab], tensors["lm_head.weight"][1])
        elif quant_mode == "q5_0":
            add_q5("output.weight", [dim, vocab], tensors["lm_head.weight"][1])
        elif quant_mode == "q5_k":
            add_q5k("output.weight", [dim, vocab], tensors["lm_head.weight"][1])
        elif quant_mode == "q8_0":
            add_q8_dq("output.weight", [dim, vocab], tensors["lm_head.weight"][1])
        elif quant_mode == "f32":
            add_f32("output.weight", [dim, vocab], tensors["lm_head.weight"][1])
            dequant_data["output.weight"] = [f32(v) for v in tensors["lm_head.weight"][1]]
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
    if return_q8_all:
        return dequant_data, q8_data
    if kquant_mode or quant_mode in ("q5_0", "q5_k", "q8_0", "f32"):
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


def py_rope(vec, n_heads, head_dim, pos, theta, rope_dim=None, rope_interleaved=False, yarn=None):
    out = list(vec)
    rdim = head_dim if rope_dim is None else rope_dim
    half = rdim // 2
    log_theta = math.log(float(theta))
    use_yarn = yarn is not None and yarn["scale"] > 1.0 and yarn["orig_ctx"] > 0
    if use_yarn:
        scale = float(yarn["scale"])
        orig_ctx = int(yarn["orig_ctx"])
        bfast = float(yarn.get("beta_fast", 32.0))
        bslow = float(yarn.get("beta_slow", 1.0))
        two_pi = 6.283185307179586
        low = max(0.0, (rdim * math.log(orig_ctx / (bfast * two_pi))) / (2.0 * log_theta))
        high = min(float(half - 1), (rdim * math.log(orig_ctx / (bslow * two_pi))) / (2.0 * log_theta))
        if high <= low:
            high = low + 0.001
        af = float(yarn.get("attn_factor", 0.0))
        mscale = af if af > 0.0 else (0.1 * math.log(scale) + 1.0)
    for j in range(half):
        if use_yarn:
            f_ext = math.exp(-log_theta * ((2 * j) / rdim))
            f_int = f_ext / scale
            ramp = min(1.0, max(0.0, (j - low) / (high - low)))
            gamma = 1.0 - ramp
            angle = pos * ((1.0 - gamma) * f_int + gamma * f_ext)
            c = f32(math.cos(angle) * mscale)
            s = f32(math.sin(angle) * mscale)
        else:
            angle = pos * math.exp(-log_theta * ((2 * j) / rdim))
            c = f32(math.cos(angle))
            s = f32(math.sin(angle))
        for h in range(n_heads):
            off = h * head_dim
            if rope_interleaved:
                v0 = out[off + 2 * j]
                v1 = out[off + 2 * j + 1]
                out[off + 2 * j] = f32(f32(v0 * c) - f32(v1 * s))
                out[off + 2 * j + 1] = f32(f32(v0 * s) + f32(v1 * c))
            else:
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
                   biases=None, qk_norms=None, dequant_data=None,
                   rope_dim=None, rope_interleaved=False, sliding_window=0,
                   attn_softcap=0.0, final_softcap=0.0, use_geglu=False,
                   embed_scale=1.0, post_norms=None, yarn=None, moe_cfg=None,
                   return_last_logits=False):
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
        if q8_data is not None and gguf_name in q8_data and use_q8_act:
            qs, sc = q8_data[gguf_name]
            xq, xs = q8
            return py_matvec_q8_0_q8_0(xq, xs, qs, sc, rows, cols)
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

    def cap_attn(raw):
        s = float(f32(raw * inv_sqrt_d))
        if attn_softcap > 0.0:
            return attn_softcap * math.tanh(s / attn_softcap)
        return s

    tokens = []
    logits_out = []
    cur = prompt[0]
    total_steps = len(prompt) + max_gen - 1
    esc = f32(embed_scale)
    q8_layers = (q4_data is not None) or (q8_data is not None and "blk.0.attn_q.weight" in q8_data)
    q8_head = q8_layers or (q8_data is not None and "output.weight" in q8_data)
    for step in range(total_steps):
        x = embed[cur * dim:(cur + 1) * dim]
        if embed_scale != 1.0:
            x = [f32(v * esc) for v in x]
        for l in range(n_layers):
            p = f"layers.{l}."
            gp = f"blk.{l}."
            xb = py_rmsnorm(x, zeros, tensors[p + "input_layernorm.weight"][1])
            q8_xb = py_quantize_q8_0(xb) if (q8_layers and use_q8_act) else None
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
            q = py_rope(q_raw, n_heads, head_dim, step, theta, rope_dim=rope_dim, rope_interleaved=rope_interleaved, yarn=yarn)
            k = py_rope(k_raw, n_kv, head_dim, step, theta, rope_dim=rope_dim, rope_interleaved=rope_interleaved, yarn=yarn)
            k_cache[l].append(k)
            v_cache[l].append(v)

            win_start = max(0, step + 1 - sliding_window) if sliding_window > 0 else 0
            # Online Softmax 1-pass attention matching forward_token
            xb_att = [0.0] * dim
            for h in range(n_heads):
                q_off = h * head_dim
                kv_off = (h // kv_mul) * head_dim
                k0 = k_cache[l][win_start]
                v0 = v_cache[l][win_start]
                acc0 = 0.0
                for d in range(head_dim):
                    acc0 = f32(acc0 + f32(q[q_off + d] * k0[kv_off + d]))
                m_val = cap_attn(acc0)
                l_val = 1.0
                for d in range(head_dim):
                    xb_att[q_off + d] = v0[kv_off + d]

                for t in range(win_start + 1, step + 1):
                    kt = k_cache[l][t]
                    vt = v_cache[l][t]
                    acc = 0.0
                    for d in range(head_dim):
                        acc = f32(acc + f32(q[q_off + d] * kt[kv_off + d]))
                    score = cap_attn(acc)
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

            q8_att = py_quantize_q8_0(xb_att) if (q8_layers and use_q8_act) else None
            xb2 = proj(xb_att, q8_att, p + "self_attn.o_proj.weight", gp + "attn_output.weight", dim, dim)
            if post_norms is not None:
                xb2 = py_rmsnorm(xb2, zeros, post_norms[l][0])
            x = [f32(a + b) for a, b in zip(x, xb2)]
            xb = py_rmsnorm(x, zeros, tensors[p + "post_attention_layernorm.weight"][1])
            if moe_cfg is not None:
                exp_cnt = moe_cfg["expert_count"]
                k_used = moe_cfg["expert_used_count"]
                exp_h = moe_cfg["expert_hidden_dim"]
                r_w = dequant_data[gp + "ffn_gate_inp.weight"]
                r_logits = py_matvec(xb, None, 0, 0) if False else py_matvec(xb, r_w, exp_cnt, dim)
                if moe_cfg.get("use_sigmoid"):
                    scores = [f32(1.0 / (1.0 + math.exp(-float(v)))) for v in r_logits]
                else:
                    rmax = max(float(v) for v in r_logits)
                    exps = [math.exp(float(v) - rmax) for v in r_logits]
                    esum = sum(exps)
                    scores = [f32(ev / esum) for ev in exps]
                bias = moe_cfg["layers"][l].get("bias")
                if bias is not None:
                    pick_scores = [f32(scores[ei] + bias[ei]) for ei in range(exp_cnt)]
                else:
                    pick_scores = list(scores)
                chosen = []
                used = [False] * exp_cnt
                for _ in range(k_used):
                    bi = max((ei for ei in range(exp_cnt) if not used[ei]), key=lambda idx: pick_scores[idx])
                    used[bi] = True
                    chosen.append((bi, scores[bi]))
                wscale = float(moe_cfg.get("weights_scale", 1.0))
                if wscale <= 0.0:
                    wscale = 1.0
                if moe_cfg.get("norm_topk"):
                    wsum = 0.0
                    for _, wv in chosen:
                        wsum += float(wv)
                    if wsum > 0.0:
                        inv_w = wscale / wsum
                        chosen = [(ei, f32(float(wv) * inv_w)) for ei, wv in chosen]
                elif wscale != 1.0:
                    chosen = [(ei, f32(float(wv) * wscale)) for ei, wv in chosen]
                xb2 = [f32(0.0)] * dim
                q8_ffn = py_quantize_q8_0(xb) if (q8_layers and use_q8_act) else None
                for ei, ew in chosen:
                    hb = proj(xb, q8_ffn, "", f"{gp}ffn_gate.{ei}.weight", exp_h, dim)
                    hb2 = proj(xb, q8_ffn, "", f"{gp}ffn_up.{ei}.weight", exp_h, dim)
                    act = [f32(f32(g / (1.0 + math.exp(-g))) * u) for g, u in zip(hb, hb2)]
                    q8_act = py_quantize_q8_0(act) if (q8_layers and use_q8_act) else None
                    e_out = proj(act, q8_act, "", f"{gp}ffn_down.{ei}.weight", dim, exp_h)
                    xb2 = [f32(xb2[i] + f32(ew * e_out[i])) for i in range(dim)]
                if moe_cfg.get("shared_hidden_dim", 0) > 0:
                    sh_h = moe_cfg["shared_hidden_dim"]
                    hb = proj(xb, q8_ffn, "", gp + "ffn_gate_shexp.weight", sh_h, dim)
                    hb2 = proj(xb, q8_ffn, "", gp + "ffn_up_shexp.weight", sh_h, dim)
                    act = [f32(f32(g / (1.0 + math.exp(-g))) * u) for g, u in zip(hb, hb2)]
                    q8_act = py_quantize_q8_0(act) if (q8_layers and use_q8_act) else None
                    e_out = proj(act, q8_act, "", gp + "ffn_down_shexp.weight", dim, sh_h)
                    sh_scale = f32(1.0)
                    sh_gw = dequant_data.get(gp + "ffn_gate_inp_shexp.weight")
                    if sh_gw is not None:
                        sg = py_matvec(xb, sh_gw, 1, dim)[0]
                        sh_scale = f32(1.0 / (1.0 + math.exp(-float(sg))))
                    xb2 = [f32(xb2[i] + f32(sh_scale * e_out[i])) for i in range(dim)]
            else:
                q8_ffn = py_quantize_q8_0(xb) if (q8_layers and use_q8_act) else None
                hb = proj(xb, q8_ffn, p + "mlp.gate_proj.weight", gp + "ffn_gate.weight", hidden, dim)
                hb2 = proj(xb, q8_ffn, p + "mlp.up_proj.weight", gp + "ffn_up.weight", hidden, dim)
                if use_geglu:
                    act = [f32(f32(0.5 * g * (1.0 + math.tanh(0.7978845608028654 * (g + 0.044715 * g * g * g)))) * u) for g, u in zip(hb, hb2)]
                else:
                    act = [f32(f32(g / (1.0 + math.exp(-g))) * u) for g, u in zip(hb, hb2)]
                q8_act = py_quantize_q8_0(act) if (q8_layers and use_q8_act) else None
                xb2 = proj(act, q8_act, p + "mlp.down_proj.weight", gp + "ffn_down.weight", dim, hidden)
            if post_norms is not None:
                xb2 = py_rmsnorm(xb2, zeros, post_norms[l][1])
            if l + 1 < n_layers:
                x = [f32(a + b) for a, b in zip(x, xb2)]

        xb = py_rmsnorm(x, xb2, final_norm)
        q8_out = py_quantize_q8_0(xb) if (q8_head and use_q8_act) else None
        logits = proj(xb, q8_out, "lm_head.weight", "output.weight", vocab, dim)
        if final_softcap > 0.0:
            logits = [f32(final_softcap * math.tanh(float(v) / final_softcap)) for v in logits]
        nxt = max(range(vocab), key=lambda i: logits[i])
        if step + 1 < len(prompt):
            cur = prompt[step + 1]
        else:
            if return_last_logits:
                return tokens + [nxt], logits_out + [logits[nxt]], list(logits)
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

    exe = exes[1][2] if len(exes) > 1 else exes[0][2]  # fusion-strict
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
        "gguf_stream_q4_0_p4k4_at": "__xu_tensor_pack_q4_0_p4k4_signed",
        "matvec_q4_0_p4k4_q8_0": f"__xu_tensor_gemv4_q4_0_p4k4_signed_f16_q8_0{suffix}_f32",
        "matmat_q4_0_p4k4_q8_0": f"__xu_tensor_gemm4x8_q4_0_p4k4_signed_f16_q8_0{suffix}_f32",
        "gguf_stream_q8_0_p4k4_at": "__xu_tensor_pack_q8_0_p4k4",
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
    q8_dq, q8_all = write_gguf_q4_0(q8_path, CFG, tensors, quant_mode="q8_0", return_q8_all=True)
    py_q8_f32 = [py_run_request(tensors, prompt, gen, dequant_data=q8_dq) for prompt, gen in REQUESTS]
    check_format(exes, q8_path, py_q8_f32, "Q8_0_layers_f32act", "q8_0", "f32", CFG["vocab_size"],
                 verify_cmd="verify-f32act", bench_cmd="bench-f32act")
    py_q8_simd = [
        py_run_request(tensors, prompt, gen, q8_data=q8_all, use_q8_act=True,
                       dequant_data={"token_embd.weight": q8_dq["token_embd.weight"]})
        for prompt, gen in REQUESTS
    ]
    check_format(exes, q8_path, py_q8_simd, "Q8_0_layers_p4k4_q8act", "q8_0", "q8_0", CFG["vocab_size"],
                 verify_cmd="verify", bench_cmd="bench")


def check_arch_extensions(exes, work, tensors):
    # 1. Partial RoPE (rope_dim=32 < head_dim=64) + Interleaved RoPE (--rope-type norm / metadata)
    rope_path = work / "mini_partial_interleaved_rope.gguf"
    q4_r, _ = write_gguf_q4_0(
        rope_path, CFG, tensors,
        extra_kv=[
            ("llama.rope.dimension_count", 4, struct.pack("<I", 32)),
            ("llama.rope.interleaved", 7, b"\x01"),
        ],
    )
    py_rope_ref = [
        py_run_request(tensors, prompt, gen, q4_data=q4_r, use_q8_act=True, rope_dim=32, rope_interleaved=True)
        for prompt, gen in REQUESTS
    ]
    check_format(exes, rope_path, py_rope_ref, "partial_interleaved_rope", "q4_0", "q8_0", CFG["vocab_size"])
    # Verify --rope-type norm matches metadata and --rope-type neox differs
    out_norm = run([exes[1][2], "verify", str(rope_path), "--rope-type", "norm"])
    out_neox = run([exes[1][2], "verify", str(rope_path), "--rope-type", "neox"])
    seq_norm, _, _ = parse_verify(out_norm)
    seq_neox, _, _ = parse_verify(out_neox)
    assert seq_norm[0][0] == (py_rope_ref[0][0][0], struct.unpack("<I", struct.pack("<f", py_rope_ref[0][1][0]))[0])
    assert seq_neox[0] != seq_norm[0], "Expected --rope-type neox to diverge from interleaved RoPE"

    # 2. Sliding window attention (window=2) + attention logit softcap (15.0)
    sw_path = work / "mini_sliding_softcap.gguf"
    q4_sw, _ = write_gguf_q4_0(
        sw_path, CFG, tensors,
        extra_kv=[
            ("llama.attention.sliding_window", 4, struct.pack("<I", 2)),
            ("llama.attn_logit_softcapping", 6, struct.pack("<f", 15.0)),
        ],
    )
    py_sw_ref = [
        py_run_request(tensors, prompt, gen, q4_data=q4_sw, use_q8_act=True, sliding_window=2, attn_softcap=15.0)
        for prompt, gen in REQUESTS
    ]
    check_format(exes, sw_path, py_sw_ref, "sliding_window+attn_softcap", "q4_0", "q8_0", CFG["vocab_size"])

    # 3. Gemma-2 style (arch=gemma2 -> sqrt(dim) embed_scale + GeGLU + post_attention_norm + ffn_post_norm + final_logit_softcap)
    rng = random.Random(20261127)
    dim = CFG["dim"]
    post_norms = [
        (
            [f32(0.8 + 0.3 * rng.random()) for _ in range(dim)],
            [f32(0.8 + 0.3 * rng.random()) for _ in range(dim)],
        )
        for _ in range(CFG["n_layers"])
    ]
    gemma_path = work / "mini_gemma2.gguf"
    q4_g, _ = write_gguf_q4_0(
        gemma_path, CFG, tensors,
        arch_name="gemma2",
        post_norms=post_norms,
        extra_kv=[
            ("gemma2.attn_logit_softcapping", 6, struct.pack("<f", 20.0)),
            ("gemma2.final_logit_softcapping", 6, struct.pack("<f", 30.0)),
        ],
    )
    py_g_ref = [
        py_run_request(
            tensors, prompt, gen, q4_data=q4_g, use_q8_act=True,
            attn_softcap=20.0, final_softcap=30.0, use_geglu=True,
            embed_scale=math.sqrt(dim), post_norms=post_norms,
        )
        for prompt, gen in REQUESTS
    ]
    check_format(exes, gemma_path, py_g_ref, "gemma2_geglu_postnorms", "q4_0", "q8_0", CFG["vocab_size"])


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

        # 7. Request created timestamp + unique ids + max_completion_tokens + logprobs/top_logprobs + response_format json_object
        c_lp1 = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": " hello world"}],
                "max_completion_tokens": 2,
                "temperature": 0.0,
                "logprobs": True,
                "top_logprobs": 4,
            }).encode(),
            headers=auth_headers,
            method="POST",
        )
        c_lp2 = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": " hello world"}],
                "max_tokens": 2,
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }).encode(),
            headers=auth_headers,
            method="POST",
        )
        with urllib.request.urlopen(c_lp1, timeout=5) as resp:
            d1 = json.loads(resp.read().decode())
        with urllib.request.urlopen(c_lp2, timeout=5) as resp:
            d2 = json.loads(resp.read().decode())
        assert d1["created"] > 1700000000 and d2["created"] >= d1["created"], (d1, d2)
        assert d1["id"] != d2["id"] and d1["id"].startswith("chatcmpl-"), (d1["id"], d2["id"])
        assert d1["usage"]["completion_tokens"] == 2, d1
        lp_content = d1["choices"][0]["logprobs"]["content"]
        assert len(lp_content) == 2, lp_content
        for entry in lp_content:
            assert entry["logprob"] <= 0.0, entry
            assert len(entry["top_logprobs"]) == 4, entry
            assert entry["top_logprobs"][0]["logprob"] >= entry["top_logprobs"][1]["logprob"], entry

        print("Enterprise serve verified (CORS, --api-key, --max-slots, batch embeddings, Llama-3 template, include_usage, created/id, logprobs/top_logprobs, response_format, SSE cancel, concurrent batched decode)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def check_serve_tools_and_json_mode(exe, work, cfg, base_tensors):
    import json
    import subprocess
    import time
    import urllib.request

    # Build a tiny deterministic Q4_0 GGUF whose lm_head strongly predicts '{"ok":1}' or '<tool_call>{"name":"add","arguments":{"a":2}}</tool_call>'
    vocab = cfg["vocab_size"]
    t_map = {k: (list(s), list(v)) for k, (s, v) in base_tensors.items()}
    dim = cfg["dim"]
    # Zero lm_head except chosen output tokens so argmax emits an exact sequence:
    # We'll zero all rows of lm_head + norm/post weights? Actually bias-only doesn't apply to lm_head;
    # simpler: set final norm weight large positive and lm_head row = +50 * constant sign of last hidden?
    # Wait: residual stream x preserves embed(tok) + attn/ffn; make all attn/ffn layer weights 0.0 -> x stays exact embed(last_tok)!
    zero_tensors = {k: (list(s), [f32(0.0)] * len(v)) for k, (s, v) in base_tensors.items()}
    zero_tensors["norm.weight"] = ([dim], [f32(1.0)] * dim)
    emb = [f32(0.0)] * (vocab * dim)
    head = [f32(0.0)] * (vocab * dim)
    # Every token embedding activates dim[0..31] = +1.0, and dim[32..63] selects per-state
    for tid in range(vocab):
        emb[tid * dim] = f32(1.0)
    # Token 10..15 encode a single complete tool call piece by piece, triggered linearly or in sequence:
    # Even simpler: one single piece token for JSON `{` + `}` (`tok 10 = "{}"`) won't match because prompt could trigger multiple tokens,
    # Wait: if token 8 has emb[8*dim + 1] = +1.0 (user prompt ends with `\n`), after step 0 generates tok 10, tok 10 feeds step 1!
    # So each emitted token uniquely selects the NEXT token via x = embed[cur]!
    # Prompt ends with token 7 ('\n'): step 0 -> token 10 (`<tool_call>`), token 10 -> token 11 (`{"name":"calc","arguments":{"x":1}}`), token 11 -> token 12 (`</tool_call>`), token 12 -> EOS (token 2)!
    # And for JSON mode test, prompt token 9 ("json") -> token 13 (`{`), token 13 -> token 14 (`"k":1}`), after `}` JSON mode stops immediately!
    chain = [(7, 10), (10, 11), (11, 12), (12, 2), (9, 13), (13, 14), (14, 15)]
    for col_idx, (src_tok, dst_tok) in enumerate(chain, start=1):
        emb[src_tok * dim + col_idx] = f32(1.0)
        for j in range(32):
            head[dst_tok * dim + (col_idx if j == 0 else j + 32)] = f32(2.0 if j == 0 else 0.0)
        head[dst_tok * dim + col_idx] = f32(5.0)
    head[13 * dim + 1] = f32(2.0)
    zero_tensors["embed_tokens.weight"] = ([vocab, dim], emb)
    zero_tensors["lm_head.weight"] = ([vocab, dim], head)

    vocab_pieces = [f"tok_{i}" for i in range(vocab)]
    vocab_pieces[0] = "<|endoftext|>"
    vocab_pieces[1] = "<|im_start|>"
    vocab_pieces[2] = "<|im_end|>"
    vocab_pieces[3] = "user"
    vocab_pieces[4] = "assistant"
    vocab_pieces[5] = "system"
    vocab_pieces[7] = "\n"
    vocab_pieces[9] = "json"
    vocab_pieces[10] = "<tool_call>"
    vocab_pieces[11] = "{\"name\":\"calc\",\"arguments\":{\"x\":1}}"
    vocab_pieces[12] = "</tool_call>"
    vocab_pieces[13] = "{"
    vocab_pieces[14] = "\"k\":1}"
    vocab_pieces[15] = "EXTRA_TRAILING_TEXT"

    tool_path = work / "mini_tools_json.gguf"
    write_gguf_q4_0(tool_path, cfg, zero_tensors, vocab_pieces=vocab_pieces)

    proc = subprocess.Popen(
        [str(exe), "serve", str(tool_path), "127.0.0.1:0"],
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

        # 1. tools -> tool_calls structured response
        req_tc = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": "json"}],
                "tools": [{
                    "type": "function",
                    "function": {"name": "calc", "description": "calc", "parameters": {"type": "object"}},
                }],
                "max_tokens": 6,
                "temperature": 0.0,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_tc, timeout=5) as resp:
            tc_data = json.loads(resp.read().decode())
        ch0 = tc_data["choices"][0]
        assert ch0["finish_reason"] == "tool_calls", tc_data
        tcs = ch0["message"]["tool_calls"]
        assert len(tcs) == 1 and tcs[0]["function"]["name"] == "calc", tc_data
        assert json.loads(tcs[0]["function"]["arguments"]) == {"x": 1}, tc_data

        # 2. response_format json_object constrains start to '{' and terminates on balanced '}' before token 15
        req_js = urllib.request.Request(
            base_url + "/v1/completions",
            data=json.dumps({
                "prompt": "ids:7",
                "response_format": {"type": "json_object"},
                "max_tokens": 6,
                "temperature": 0.0,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_js, timeout=5) as resp:
            js_data = json.loads(resp.read().decode())
        # Note: token 7 leads to <tool_call> without json_mode, while with json_mode step 0 masks <tool_call> and picks '{' (tok 13) -> '"k":1}' (tok 14) -> stop!
        txt = js_data["choices"][0]["text"]
        assert txt == "{\"k\":1}", (txt, js_data)
        assert json.loads(txt) == {"k": 1}, js_data
        assert js_data["choices"][0]["finish_reason"] == "stop", js_data

        # 3. response_format json_schema matches json_object constraint
        req_jschema = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": "json"}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "kv", "schema": {"type": "object"}},
                },
                "max_tokens": 6,
                "temperature": 0.0,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_jschema, timeout=5) as resp:
            jsc_data = json.loads(resp.read().decode())
        jsc_txt = jsc_data["choices"][0]["message"]["content"]
        assert json.loads(jsc_txt) == {"k": 1}, jsc_data

        # 4. Multi-turn chat formatting with assistant.content=null + tool_calls + role="tool"
        req_mt = urllib.request.Request(
            base_url + "/v1/chat/completions",
            data=json.dumps({
                "messages": [
                    {"role": "user", "content": "json"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_0",
                            "type": "function",
                            "function": {"name": "calc", "arguments": "{\"x\":1}"},
                        }],
                    },
                    {"role": "tool", "tool_call_id": "call_0", "content": "{\"y\":2}"},
                ],
                "max_tokens": 2,
                "temperature": 0.0,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_mt, timeout=5) as resp:
            mt_data = json.loads(resp.read().decode())
        assert "content" in mt_data["choices"][0]["message"], mt_data

        # 5. logit_bias steers greedy sampling directly to token 15 ("EXTRA_TRAILING_TEXT")
        req_lb = urllib.request.Request(
            base_url + "/v1/completions",
            data=json.dumps({
                "prompt": "ids:7",
                "logit_bias": {"15": 100.0},
                "max_tokens": 1,
                "temperature": 0.0,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_lb, timeout=5) as resp:
            lb_data = json.loads(resp.read().decode())
        assert lb_data["choices"][0]["text"] == "EXTRA_TRAILING_TEXT", lb_data
        print("Serve tools/multi-turn/json_object/json_schema/logit_bias verified")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


def check_moe_and_yarn_gguf(exes, work, tensors):
    rng = random.Random(20261130)
    dim = CFG["dim"]
    exp_cnt = 4
    exp_h = 64

    # Case A: 3D packed ffn_*_exps.weight (Q4_0) + F16 router (compact negative offset) + Softmax + YaRN RoPE
    layers_a = []
    for _ in range(CFG["n_layers"]):
        layers_a.append({
            "gate_inp": gen_weights(rng, exp_cnt * dim, 0.2),
            "w1_exps": [gen_weights(rng, exp_h * dim, 0.08) for _ in range(exp_cnt)],
            "w3_exps": [gen_weights(rng, exp_h * dim, 0.08) for _ in range(exp_cnt)],
            "w2_exps": [gen_weights(rng, dim * exp_h, 0.08) for _ in range(exp_cnt)],
        })
    moe_a = {
        "expert_count": exp_cnt,
        "expert_used_count": 2,
        "expert_hidden_dim": exp_h,
        "norm_topk": True,
        "packed_3d": True,
        "router_f16": True,
        "layers": layers_a,
    }
    yarn_cfg = {
        "scale": 2.0,
        "orig_ctx": 32,
        "beta_fast": 32.0,
        "beta_slow": 1.0,
        "attn_factor": 0.0,
    }
    moe_a_path = work / "mini_moe_packed3d_yarn.gguf"
    q4_a, _ = write_gguf_q4_0(
        moe_a_path, CFG, tensors,
        arch_name="qwen2moe",
        moe=moe_a,
        extra_kv=[
            ("qwen2moe.expert_count", 4, struct.pack("<I", exp_cnt)),
            ("qwen2moe.expert_used_count", 4, struct.pack("<I", 2)),
            ("qwen2moe.expert_feed_forward_length", 4, struct.pack("<I", exp_h)),
            ("qwen2moe.expert_gating_func", 4, struct.pack("<I", 1)),
            ("qwen2moe.expert_weights_norm", 7, b"\x01"),
            ("qwen2moe.rope.scaling.type", 8, pack_gguf_str("yarn")),
            ("qwen2moe.rope.scaling.factor", 6, struct.pack("<f", 2.0)),
            ("qwen2moe.rope.scaling.original_context_length", 4, struct.pack("<I", 32)),
        ],
    )
    # Also grab F16 router dequant map by checking write_gguf_q4_0; write_gguf_q4_0 returned q4_a only, so compute F16 router values identically
    dq_a = {}
    for l in range(CFG["n_layers"]):
        raw = layers_a[l]["gate_inp"]
        dq_a[f"blk.{l}.ffn_gate_inp.weight"] = [f32(struct.unpack("<e", struct.pack("<e", float(v)))[0]) for v in raw]
    py_a_ref = [
        py_run_request(tensors, prompt, gen, q4_data=q4_a, use_q8_act=True, dequant_data=dq_a, yarn=yarn_cfg, moe_cfg=moe_a)
        for prompt, gen in REQUESTS
    ]
    check_format(exes, moe_a_path, py_a_ref, "moe_3d_yarn_q4", "q4_0", "q8_0", CFG["vocab_size"])
    _, _, meta_a = parse_verify(run([exes[1][2], "verify", str(moe_a_path)]))
    assert meta_a.get("expert_count") == "4" and meta_a.get("rope_scaling") == "yarn", meta_a

    # Case B: Split experts (F32) + Sigmoid routing + routing bias + weights_scale + shared expert + F16 shared gate
    layers_b = []
    for _ in range(CFG["n_layers"]):
        layers_b.append({
            "gate_inp": gen_weights(rng, exp_cnt * dim, 0.2),
            "bias": [f32((e - 1.5) * 0.15) for e in range(exp_cnt)],
            "w1_exps": [gen_weights(rng, exp_h * dim, 0.08) for _ in range(exp_cnt)],
            "w3_exps": [gen_weights(rng, exp_h * dim, 0.08) for _ in range(exp_cnt)],
            "w2_exps": [gen_weights(rng, dim * exp_h, 0.08) for _ in range(exp_cnt)],
            "sh_w1": gen_weights(rng, exp_h * dim, 0.08),
            "sh_w3": gen_weights(rng, exp_h * dim, 0.08),
            "sh_w2": gen_weights(rng, dim * exp_h, 0.08),
            "sh_gate_inp": gen_weights(rng, dim, 0.15),
        })
    moe_b = {
        "expert_count": exp_cnt,
        "expert_used_count": 2,
        "expert_hidden_dim": exp_h,
        "shared_hidden_dim": exp_h,
        "use_sigmoid": True,
        "norm_topk": True,
        "weights_scale": 1.5,
        "packed_3d": False,
        "router_f16": True,
        "layers": layers_b,
    }
    moe_b_path = work / "mini_moe_split_sigmoid_shared.gguf"
    dq_b, _ = write_gguf_q4_0(
        moe_b_path, CFG, tensors,
        quant_mode="f32",
        arch_name="deepseek2",
        moe=moe_b,
        extra_kv=[
            ("deepseek2.expert_count", 4, struct.pack("<I", exp_cnt)),
            ("deepseek2.expert_used_count", 4, struct.pack("<I", 2)),
            ("deepseek2.expert_feed_forward_length", 4, struct.pack("<I", exp_h)),
            ("deepseek2.expert_shared_count", 4, struct.pack("<I", 1)),
            ("deepseek2.expert_shared_feed_forward_length", 4, struct.pack("<I", exp_h)),
            ("deepseek2.expert_gating_func", 4, struct.pack("<I", 2)),
            ("deepseek2.expert_weights_norm", 7, b"\x01"),
            ("deepseek2.expert_weights_scale", 6, struct.pack("<f", 1.5)),
        ],
    )
    py_b_ref = [
        py_run_request(tensors, prompt, gen, dequant_data=dq_b, moe_cfg=moe_b)
        for prompt, gen in REQUESTS
    ]
    check_format(exes, moe_b_path, py_b_ref, "moe_split_sigmoid_shared", "f32", "f32", CFG["vocab_size"])


def check_hf_sharded_dir(exes, work, cfg, tensors, py_ref):
    import json
    hf_dir = work / "hf_sharded_model"
    hf_dir.mkdir(parents=True, exist_ok=True)
    dim = cfg["dim"]
    vocab = cfg["vocab_size"]
    n_heads = cfg["n_heads"]
    n_kv = cfg["n_kv_heads"]
    hidden = cfg["hidden_dim"]
    n_layers = cfg["n_layers"]

    # Map GGUF/mini tensor names to HuggingFace model.* names split across 2 shards
    shard1 = {}
    shard2 = {}
    weight_map = {}

    def put_tensor(shard, shard_name, hf_name, shape, vals):
        shard[hf_name] = (shape, vals)
        weight_map[hf_name] = shard_name

    put_tensor(shard1, "model-00001-of-00002.safetensors", "model.embed_tokens.weight", [vocab, dim], tensors["embed_tokens.weight"][1])
    for l in range(n_layers):
        tgt = shard1 if l == 0 else shard2
        sname = "model-00001-of-00002.safetensors" if l == 0 else "model-00002-of-00002.safetensors"
        put_tensor(tgt, sname, f"model.layers.{l}.input_layernorm.weight", [dim], tensors[f"layers.{l}.input_layernorm.weight"][1])
        put_tensor(tgt, sname, f"model.layers.{l}.self_attn.q_proj.weight", [dim, dim], tensors[f"layers.{l}.self_attn.q_proj.weight"][1])
        put_tensor(tgt, sname, f"model.layers.{l}.self_attn.k_proj.weight", [n_kv * (dim // n_heads), dim], tensors[f"layers.{l}.self_attn.k_proj.weight"][1])
        put_tensor(tgt, sname, f"model.layers.{l}.self_attn.v_proj.weight", [n_kv * (dim // n_heads), dim], tensors[f"layers.{l}.self_attn.v_proj.weight"][1])
        put_tensor(tgt, sname, f"model.layers.{l}.self_attn.o_proj.weight", [dim, dim], tensors[f"layers.{l}.self_attn.o_proj.weight"][1])
        put_tensor(tgt, sname, f"model.layers.{l}.post_attention_layernorm.weight", [dim], tensors[f"layers.{l}.post_attention_layernorm.weight"][1])
        put_tensor(tgt, sname, f"model.layers.{l}.mlp.gate_proj.weight", [hidden, dim], tensors[f"layers.{l}.mlp.gate_proj.weight"][1])
        put_tensor(tgt, sname, f"model.layers.{l}.mlp.up_proj.weight", [hidden, dim], tensors[f"layers.{l}.mlp.up_proj.weight"][1])
        put_tensor(tgt, sname, f"model.layers.{l}.mlp.down_proj.weight", [dim, hidden], tensors[f"layers.{l}.mlp.down_proj.weight"][1])
    put_tensor(shard2, "model-00002-of-00002.safetensors", "model.norm.weight", [dim], tensors["norm.weight"][1])
    put_tensor(shard2, "model-00002-of-00002.safetensors", "lm_head.weight", [vocab, dim], tensors["lm_head.weight"][1])

    write_safetensors(hf_dir / "model-00001-of-00002.safetensors", {}, shard1)
    write_safetensors(hf_dir / "model-00002-of-00002.safetensors", {}, shard2)
    (hf_dir / "model.safetensors.index.json").write_text(json.dumps({
        "metadata": {"total_size": 0},
        "weight_map": weight_map,
    }))
    (hf_dir / "config.json").write_text(json.dumps({
        "model_type": "llama",
        "hidden_size": dim,
        "intermediate_size": hidden,
        "num_hidden_layers": n_layers,
        "num_attention_heads": n_heads,
        "num_key_value_heads": n_kv,
        "vocab_size": vocab,
        "max_position_embeddings": cfg["max_seq_len"],
        "rope_theta": cfg["rope_theta"],
        "rms_norm_eps": 1e-5,
        "tie_word_embeddings": False,
        "bos_token_id": 0,
        "eos_token_id": [2],
    }))
    tok_vocab = {f"tok_{i}": i for i in range(vocab)}
    tok_vocab["<|endoftext|>"] = 0
    tok_vocab["<|im_end|>"] = 2
    (hf_dir / "tokenizer.json").write_text(json.dumps({
        "model": {"type": "BPE", "vocab": tok_vocab, "merges": []},
        "added_tokens": [],
    }))
    (hf_dir / "tokenizer_config.json").write_text(json.dumps({
        "eos_token": "<|im_end|>",
        "chat_template": "{% for m in messages %}<|im_start|>{{ m.role }}\n{{ m.content }}<|im_end|>\n{% endfor %}",
    }))
    check_format(exes, hf_dir, py_ref, "hf_sharded_dir", "f32", "f32", vocab)


def check_mla_and_q8k_act(exes, work):
    rng = random.Random(20261201)
    # 1. DeepSeek-style MLA GGUF verification (baseline / fusion-strict / fusion-fast + CB)
    dim = 64
    hidden = 128
    n_heads = 4
    n_layers = 1
    q_rank = 16
    kv_rank = 16
    qk_nope = 8
    qk_rope = 8
    v_hd = 8
    head_dim = qk_nope + qk_rope
    vocab = 32
    max_seq = 16

    def pack_raw_gguf(path, kv_entries, tensor_specs):
        hdr = bytearray()
        hdr.extend(b"GGUF")
        hdr.extend(struct.pack("<IQQ", 3, len(tensor_specs), len(kv_entries)))
        for k, vtype, vbytes in kv_entries:
            hdr.extend(pack_gguf_str(k))
            hdr.extend(struct.pack("<I", vtype))
            hdr.extend(vbytes)
        cur = 0
        t_payload = bytearray()
        for name, dims, gtype, raw in tensor_specs:
            cur = (cur + 31) & ~31
            while len(t_payload) < cur:
                t_payload.append(0)
            hdr.extend(pack_gguf_str(name))
            hdr.extend(struct.pack("<I", len(dims)))
            for d in reversed(dims):
                hdr.extend(struct.pack("<Q", d))
            hdr.extend(struct.pack("<IQ", gtype, cur))
            t_payload.extend(raw)
            cur += len(raw)
        while len(hdr) % 32 != 0:
            hdr.append(0)
        path.write_bytes(bytes(hdr) + bytes(t_payload))

    def f32_spec(name, dims, scale=0.05):
        n = 1
        for d in dims:
            n *= d
        vals = gen_weights(rng, n, scale)
        return (name, dims, 0, struct.pack(f"<{n}f", *vals))

    mla_path = work / "mini_mla.gguf"
    mla_kv = [
        ("general.architecture", 8, pack_gguf_str("deepseek2")),
        ("general.alignment", 4, struct.pack("<I", 32)),
        ("deepseek2.embedding_length", 4, struct.pack("<I", dim)),
        ("deepseek2.feed_forward_length", 4, struct.pack("<I", hidden)),
        ("deepseek2.block_count", 4, struct.pack("<I", n_layers)),
        ("deepseek2.attention.head_count", 4, struct.pack("<I", n_heads)),
        ("deepseek2.attention.head_count_kv", 4, struct.pack("<I", n_heads)),
        ("deepseek2.attention.key_length", 4, struct.pack("<I", head_dim)),
        ("deepseek2.attention.value_length", 4, struct.pack("<I", v_hd)),
        ("deepseek2.attention.q_lora_rank", 4, struct.pack("<I", q_rank)),
        ("deepseek2.attention.kv_lora_rank", 4, struct.pack("<I", kv_rank)),
        ("deepseek2.attention.key_length_mla", 4, struct.pack("<I", qk_nope)),
        ("deepseek2.attention.value_length_mla", 4, struct.pack("<I", v_hd)),
        ("deepseek2.rope.dimension_count", 4, struct.pack("<I", qk_rope)),
        ("deepseek2.context_length", 4, struct.pack("<I", max_seq)),
        ("deepseek2.rope.freq_base", 6, struct.pack("<f", 10000.0)),
        ("deepseek2.attention.layer_norm_rms_epsilon", 6, struct.pack("<f", 1e-5)),
        ("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 8, vocab) + b"".join(pack_gguf_str(f"tok_{i}") for i in range(vocab))),
    ]
    mla_specs = [
        f32_spec("token_embd.weight", [vocab, dim], 0.2),
        f32_spec("blk.0.attn_norm.weight", [dim], 1.0),
        f32_spec("blk.0.attn_q_a.weight", [q_rank, dim]),
        f32_spec("blk.0.attn_q_a_norm.weight", [q_rank], 1.0),
        f32_spec("blk.0.attn_q_b.weight", [n_heads * head_dim, q_rank]),
        f32_spec("blk.0.attn_kv_a_mqa.weight", [kv_rank + qk_rope, dim]),
        f32_spec("blk.0.attn_kv_a_norm.weight", [kv_rank], 1.0),
        f32_spec("blk.0.attn_kv_b.weight", [n_heads * (qk_nope + v_hd), kv_rank]),
        f32_spec("blk.0.attn_output.weight", [dim, n_heads * v_hd]),
        f32_spec("blk.0.ffn_norm.weight", [dim], 1.0),
        f32_spec("blk.0.ffn_gate.weight", [hidden, dim]),
        f32_spec("blk.0.ffn_up.weight", [hidden, dim]),
        f32_spec("blk.0.ffn_down.weight", [dim, hidden]),
        f32_spec("output_norm.weight", [dim], 1.0),
        f32_spec("output.weight", [vocab, dim], 0.2),
    ]
    pack_raw_gguf(mla_path, mla_kv, mla_specs)
    ref_ids = None
    for name, _, exe, _ in exes:
        seq, cb, meta = parse_verify(run([exe, "verify", str(mla_path)]))
        assert seq and seq == cb, (name, seq, cb)
        free_num, free_den = map(int, meta["kv_free_after"].split("/"))
        assert free_num == free_den and free_den > 0, (name, meta)
        out = strip_volatile_gen(run([exe, "generate", str(mla_path), "ids:1,2,3", "4", "0", "4"]).splitlines())
        if ref_ids is None:
            ref_ids = out
        else:
            assert out == ref_ids, (name, out, ref_ids)
    print("DeepSeek MLA GGUF (seq/CB + baseline/fusion-strict/fusion-fast) verified")

    # 2. --q8k-act path for Q4_K model (cols=256 divisible by QK_K)
    kcfg = dict(CFG, dim=256, hidden_dim=256, n_layers=1, n_heads=4, n_kv_heads=4)
    ktensors = generate_weight_dict(kcfg)
    qk_path = work / "mini_q4_k_256.gguf"
    write_gguf_q4_0(qk_path, kcfg, ktensors, kquant_mode=True)
    out_std = strip_volatile_gen(run([exes[1][2], "generate", str(qk_path), "ids:1,2", "3", "0", "4"]).splitlines())
    out_q8k = strip_volatile_gen(run([exes[1][2], "generate", str(qk_path), "ids:1,2", "3", "0", "4", "--q8k-act"]).splitlines())
    assert any(l.startswith("generated_ids:") for l in out_q8k), out_q8k
    assert out_q8k == out_std, (out_q8k, out_std)
    seq_q8k, cb_q8k, meta_q8k = parse_verify(run([exes[1][2], "verify", str(qk_path), "--q8k-act"]))
    assert seq_q8k and seq_q8k == cb_q8k, (seq_q8k, cb_q8k, meta_q8k)
    print("--q8k-act integer K-quant activation dot verified")


def check_serve_v17_protocols(exe, work, cfg, base_tensors):
    import json
    import subprocess
    import time
    import urllib.error
    import urllib.request

    vocab = cfg["vocab_size"]
    dim = cfg["dim"]

    def make_chain_gguf(path, vocab_pieces, chain):
        zero_tensors = {k: (list(s), [f32(0.0)] * len(v)) for k, (s, v) in base_tensors.items()}
        zero_tensors["norm.weight"] = ([dim], [f32(1.0)] * dim)
        emb = [f32(0.0)] * (vocab * dim)
        head = [f32(0.0)] * (vocab * dim)
        for tid in range(vocab):
            emb[tid * dim] = f32(1.0)
        for col_idx, (src_tok, dst_tok) in enumerate(chain, start=1):
            emb[src_tok * dim + col_idx] = f32(1.0)
            head[dst_tok * dim + 0] = f32(2.0)
            head[dst_tok * dim + col_idx] = f32(5.0)
        zero_tensors["embed_tokens.weight"] = ([vocab, dim], emb)
        zero_tensors["lm_head.weight"] = ([vocab, dim], head)
        write_gguf_q4_0(path, cfg, zero_tensors, vocab_pieces=vocab_pieces)

    def start_srv(mpath, extra_args=()):
        proc = subprocess.Popen(
            [str(exe), "serve", str(mpath), "127.0.0.1:0", *extra_args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        base_url = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line and line.strip().startswith("serving:http://"):
                base_url = line.strip().split("serving:", 1)[1]
                break
        assert base_url, "server failed to start"
        return proc, base_url

    def stop_srv(proc):
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)

    # Server A: <think>plan</think>Hello + x-api-key + Anthropic /v1/messages (sync + SSE)
    pieces_a = [f"tok_{i}" for i in range(vocab)]
    pieces_a[0] = "<|endoftext|>"
    pieces_a[1] = "<|im_start|>"
    pieces_a[2] = "<|im_end|>"
    pieces_a[3] = "user"
    pieces_a[4] = "assistant"
    pieces_a[5] = "system"
    pieces_a[7] = "\n"
    pieces_a[9] = "hi"
    pieces_a[10] = "<think>"
    pieces_a[11] = "plan"
    pieces_a[12] = "</think>"
    pieces_a[13] = "Hello"
    think_path = work / "mini_think_serve.gguf"
    make_chain_gguf(think_path, pieces_a, [(7, 10), (10, 11), (11, 12), (12, 13), (13, 2)])

    proc_a, url_a = start_srv(think_path, ("--api-key", "secret17"))
    try:
        # 401 when key wrong / missing
        req_bad = urllib.request.Request(
            url_a + "/v1/messages",
            data=json.dumps({"model": "xu", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4}).encode(),
            headers={"Content-Type": "application/json", "x-api-key": "wrong"},
            method="POST",
        )
        got_401 = False
        try:
            urllib.request.urlopen(req_bad, timeout=5)
        except urllib.error.HTTPError as e:
            got_401 = (e.code == 401)
        assert got_401

        # OpenAI sync <think> -> reasoning_content + content
        req_oai = urllib.request.Request(
            url_a + "/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}], "max_tokens": 6, "temperature": 0.0}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret17"},
            method="POST",
        )
        with urllib.request.urlopen(req_oai, timeout=5) as resp:
            oai_d = json.loads(resp.read().decode())
        msg = oai_d["choices"][0]["message"]
        assert msg["reasoning_content"] == "plan" and msg["content"] == "Hello", oai_d

        # OpenAI SSE <think> -> delta.reasoning_content + delta.content
        req_oai_s = urllib.request.Request(
            url_a + "/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}], "max_tokens": 6, "temperature": 0.0, "stream": True}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret17"},
            method="POST",
        )
        with urllib.request.urlopen(req_oai_s, timeout=5) as resp:
            sse_lines = [l.decode() for l in resp.read().splitlines() if l.decode().startswith("data: ") and l.decode() != "data: [DONE]"]
        r_acc, c_acc = "", ""
        for sl in sse_lines:
            d = json.loads(sl[6:])["choices"][0]["delta"]
            r_acc += d.get("reasoning_content", "")
            c_acc += d.get("content", "")
        assert r_acc == "plan" and c_acc == "Hello", (r_acc, c_acc, sse_lines)

        # Anthropic /v1/messages sync with x-api-key
        req_ant = urllib.request.Request(
            url_a + "/v1/messages",
            data=json.dumps({
                "model": "xu-local",
                "system": "be brief",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                "max_tokens": 6,
                "temperature": 0.0,
            }).encode(),
            headers={"Content-Type": "application/json", "x-api-key": "secret17", "anthropic-version": "2023-06-01"},
            method="POST",
        )
        with urllib.request.urlopen(req_ant, timeout=5) as resp:
            ant_d = json.loads(resp.read().decode())
        assert ant_d["type"] == "message" and ant_d["stop_reason"] == "end_turn", ant_d
        assert ant_d["content"] == [
            {"type": "thinking", "thinking": "plan"},
            {"type": "text", "text": "Hello"},
        ], ant_d

        # Anthropic /v1/messages SSE
        req_ant_s = urllib.request.Request(
            url_a + "/v1/messages",
            data=json.dumps({
                "model": "xu-local",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 6,
                "temperature": 0.0,
                "stream": True,
            }).encode(),
            headers={"Content-Type": "application/json", "x-api-key": "secret17"},
            method="POST",
        )
        with urllib.request.urlopen(req_ant_s, timeout=5) as resp:
            ant_sse = resp.read().decode()
        assert "event: message_start" in ant_sse and "\"thinking_delta\"" in ant_sse and "\"text_delta\"" in ant_sse and "event: message_stop" in ant_sse, ant_sse
    finally:
        stop_srv(proc_a)

    # Server B: tool_calls SSE delta.tool_calls & Anthropic tool_use + tool_result
    pieces_b = list(pieces_a)
    pieces_b[13] = "<tool_call>"
    pieces_b[14] = "{\"name\":\"add\",\"arguments\":{\"a\":2,\"b\":3}}"
    pieces_b[15] = "</tool_call>"
    tool_b_path = work / "mini_tool_v17.gguf"
    make_chain_gguf(tool_b_path, pieces_b, [(7, 10), (10, 11), (11, 12), (12, 13), (13, 14), (14, 15), (15, 2)])
    proc_b, url_b = start_srv(tool_b_path)
    try:
        # OpenAI SSE delta.tool_calls
        req_tc_s = urllib.request.Request(
            url_b + "/v1/chat/completions",
            data=json.dumps({
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [{"type": "function", "function": {"name": "add", "description": "add", "parameters": {"type": "object"}}}],
                "max_tokens": 8,
                "temperature": 0.0,
                "stream": True,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_tc_s, timeout=5) as resp:
            tc_sse = [json.loads(l.decode()[6:]) for l in resp.read().splitlines() if l.decode().startswith("data: {")]
        got_tcs = [c["choices"][0]["delta"]["tool_calls"] for c in tc_sse if "tool_calls" in c["choices"][0]["delta"]]
        assert len(got_tcs) == 1 and got_tcs[0][0]["function"]["name"] == "add", tc_sse
        assert tc_sse[-1]["choices"][0]["finish_reason"] == "tool_calls", tc_sse

        # Anthropic sync tool_use + stop_reason="tool_use"
        req_ant_tc = urllib.request.Request(
            url_b + "/v1/messages",
            data=json.dumps({
                "model": "xu-local",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [{"name": "add", "description": "add", "input_schema": {"type": "object"}}],
                "max_tokens": 8,
                "temperature": 0.0,
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_ant_tc, timeout=5) as resp:
            ant_tc = json.loads(resp.read().decode())
        assert ant_tc["stop_reason"] == "tool_use", ant_tc
        assert any(b.get("type") == "tool_use" and b.get("name") == "add" and b.get("input") == {"a": 2, "b": 3} for b in ant_tc["content"]), ant_tc
    finally:
        stop_srv(proc_b)
    print("Serve v1.7.0 (<think> reasoning_content, SSE delta.tool_calls, Anthropic /v1/messages sync+SSE+x-api-key) verified")


def check_lora_and_speculative(exes, work, cfg, base_tensors):
    import json

    dim = cfg["dim"]
    hidden = cfg["hidden_dim"]
    vocab = cfg["vocab_size"]
    rank = 2
    alpha = 4.0
    scale = alpha / rank

    base_path = work / "lora_base.safetensors"
    write_safetensors(base_path, cfg, base_tensors)

    lrng = random.Random(20261126)
    def rand_mat(r, c, amp=0.15):
        return [f32(lrng.uniform(-amp, amp)) for _ in range(r * c)]

    specs = [
        ("base_model.model.model.layers.0.self_attn.q_proj", "layers.0.self_attn.q_proj.weight", dim, dim),
        ("base_model.model.model.layers.0.self_attn.o_proj", "layers.0.self_attn.o_proj.weight", dim, dim),
        ("base_model.model.model.layers.0.mlp.down_proj", "layers.0.mlp.down_proj.weight", dim, hidden),
        ("base_model.model.lm_head", "lm_head.weight", vocab, dim),
    ]

    lora_dir = work / "lora_adapter_dir"
    lora_dir.mkdir(exist_ok=True)
    (lora_dir / "adapter_config.json").write_text(json.dumps({"r": rank, "lora_alpha": alpha}))

    merged = {k: (list(s), list(v)) for k, (s, v) in base_tensors.items()}
    sf_tensors = {}
    for lora_prefix, base_key, out_d, in_d in specs:
        a = rand_mat(rank, in_d, 0.25)
        b = rand_mat(out_d, rank, 0.25)
        sf_tensors[f"{lora_prefix}.lora_A.weight"] = ([rank, in_d], a)
        sf_tensors[f"{lora_prefix}.lora_B.weight"] = ([out_d, rank], b)
        _, base_vals = merged[base_key]
        new_vals = list(base_vals)
        for i in range(out_d):
            for j in range(in_d):
                delta = sum(b[i * rank + r] * a[r * in_d + j] for r in range(rank))
                new_vals[i * in_d + j] = f32(new_vals[i * in_d + j] + scale * delta)
        merged[base_key] = ([out_d, in_d], new_vals)

    # Pack PEFT adapter_model.safetensors cleanly (F32)
    sf_hdr = {}
    sf_payload = bytearray()
    for tname, (shape, vals) in sf_tensors.items():
        raw = struct.pack(f"<{len(vals)}f", *vals)
        start = len(sf_payload)
        sf_payload.extend(raw)
        sf_hdr[tname] = {"dtype": "F32", "shape": shape, "data_offsets": [start, start + len(raw)]}
    hb = json.dumps(sf_hdr).encode("utf-8")
    (lora_dir / "adapter_model.safetensors").write_bytes(struct.pack("<Q", len(hb)) + hb + bytes(sf_payload))

    py_merged = [py_run_request(merged, prompt, gen) for prompt, gen in REQUESTS]
    for name, _, exe, _ in exes:
        seq, cb, meta = parse_verify(run([exe, "verify", str(base_path), "--lora", str(lora_dir)]))
        assert seq and seq == cb, (name, seq, cb)
        free_num, free_den = map(int, meta["kv_free_after"].split("/"))
        assert free_num == free_den and free_den > 0, (name, meta)
        for r, (want_toks, want_logits) in enumerate(py_merged):
            got_toks = [t for t, _ in seq[r]]
            assert got_toks == want_toks, (name, r, got_toks, want_toks)
            for t, (_, gbits) in enumerate(seq[r]):
                assert abs(bits_to_f32(gbits) - want_logits[t]) < 1e-4, (name, r, t, bits_to_f32(gbits), want_logits[t])
    print("--lora PEFT SafeTensors adapter (attn/mlp/lm_head, seq/CB, Python parity) verified")

    # 2. Pure-Xu train-lora -> generate --lora
    trained_sf = work / "trained_lm_head.safetensors"
    tr_out = run([
        exes[1][2], "train-lora", str(base_path), "ids:1,7,42,19", str(trained_sf),
        "--lora-rank", "4", "--lora-alpha", "16.0", "--steps", "35", "--lr", "0.2",
    ])
    losses = [float(l.split("loss:", 1)[1].split()[0]) for l in tr_out.splitlines() if l.startswith("step:")]
    assert len(losses) == 35 and losses[-1] < 0.05 and losses[-1] < losses[0] * 0.1, losses
    assert trained_sf.exists() and any(l == "kv_free_after:4/4" for l in tr_out.splitlines()), tr_out
    gen_tr = run([exes[1][2], "generate", str(base_path), "ids:1,7", "2", "0", "40", "--lora", str(trained_sf)])
    kv_tr = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in gen_tr.splitlines() if ":" in l}
    assert kv_tr["generated_ids"] == "42,19", kv_tr
    print(f"Pure-Xu train-lora verified (loss {losses[0]:.4f} -> {losses[-1]:.6f}, predicts 42,19)")

    # 3. Exact Lossless Speculative Decoding (--draft same & --draft perturbed)
    target_gen = [l for l in strip_volatile_gen(run([exes[1][2], "generate", str(base_path), "ids:1,7,42", "10", "0", "40"]).splitlines()) if not l.startswith("load_ms:")]
    target_kv = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in target_gen if ":" in l}

    same_spec = run([exes[1][2], "generate", str(base_path), "ids:1,7,42", "10", "0", "40", "--draft", str(base_path), "--draft-k", "4"]).splitlines()
    same_kv = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in same_spec if ":" in l}
    assert same_kv["generated_ids"] == target_kv["generated_ids"], (same_kv, target_kv)
    assert same_kv["generated_text"] == target_kv["generated_text"], (same_kv, target_kv)
    assert int(same_kv["spec_drafted"]) > 0 and same_kv["spec_accepted"] == same_kv["spec_drafted"], same_kv
    assert same_kv["kv_free_after"] == "4/4", same_kv

    # Perturbed draft model: flip sign on down_proj so draft proposes diverging tokens
    draft_tensors = {k: (list(s), list(v)) for k, (s, v) in base_tensors.items()}
    s_dp, v_dp = draft_tensors["layers.0.mlp.down_proj.weight"]
    draft_tensors["layers.0.mlp.down_proj.weight"] = (s_dp, [f32(-val * 1.5) for val in v_dp])
    draft_path = work / "draft_perturbed.safetensors"
    write_safetensors(draft_path, cfg, draft_tensors)

    pert_spec = run([exes[1][2], "generate", str(base_path), "ids:1,7,42", "10", "0", "40", "--draft", str(draft_path), "--draft-k", "4"]).splitlines()
    pert_kv = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in pert_spec if ":" in l}
    assert pert_kv["generated_ids"] == target_kv["generated_ids"], (pert_kv, target_kv)
    assert pert_kv["generated_text"] == target_kv["generated_text"], (pert_kv, target_kv)
    assert int(pert_kv["spec_accepted"]) < int(pert_kv["spec_drafted"]), pert_kv
    assert pert_kv["kv_free_after"] == "4/4", pert_kv

    stoch1 = [l for l in strip_volatile_gen(run([exes[1][2], "generate", str(base_path), "ids:1,7,42", "8", "800", "40", "--draft", str(draft_path), "--draft-k", "3", "--seed", "777"]).splitlines()) if not l.startswith("load_ms:")]
    stoch2 = [l for l in strip_volatile_gen(run([exes[1][2], "generate", str(base_path), "ids:1,7,42", "8", "800", "40", "--draft", str(draft_path), "--draft-k", "3", "--seed", "777"]).splitlines()) if not l.startswith("load_ms:")]
    assert stoch1 == stoch2, (stoch1, stoch2)
    stoch_kv = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in stoch1 if ":" in l}
    assert len(stoch_kv["generated_ids"].split(",")) == 8 and stoch_kv["kv_free_after"] == "4/4", stoch_kv
    print(f"Lossless speculative decoding verified (same={same_kv['spec_accepted']}/{same_kv['spec_drafted']}, perturbed={pert_kv['spec_accepted']}/{pert_kv['spec_drafted']})")


def check_q5_k_and_responses_api(exes, work, cfg, base_tensors):
    import json
    import subprocess
    import time
    import urllib.request

    # 1. GGUF Q5_K verify + --q8k-act
    q5k_path = work / "mini_q5_k.gguf"
    q5k_dq, _ = write_gguf_q4_0(q5k_path, cfg, base_tensors, quant_mode="q5_k")
    py_q5k = [py_run_request(base_tensors, prompt, gen, dequant_data=q5k_dq) for prompt, gen in REQUESTS]
    check_format(exes, q5k_path, py_q5k, "Q5_K", "q5_k", "f32", cfg["vocab_size"],
                 verify_cmd="verify-f32act", bench_cmd="bench-f32act")
    seq_q8k, cb_q8k, meta_q8k = parse_verify(run([exes[1][2], "verify", str(q5k_path), "--q8k-act"]))
    assert meta_q8k.get("format") == "q5_k" and seq_q8k and seq_q8k == cb_q8k, meta_q8k
    assert [t for t, _ in seq_q8k[0]] == py_q5k[0][0], (seq_q8k[0], py_q5k[0][0])

    # 2. train-lora with --max-grad-norm clipping
    clip_sf = work / "trained_clip.safetensors"
    tr_clip = run([
        exes[1][2], "train-lora", str(work / "lora_base.safetensors"), "ids:1,7,42,19", str(clip_sf),
        "--lora-rank", "4", "--lora-alpha", "16.0", "--steps", "20", "--lr", "0.25", "--max-grad-norm", "0.5",
    ])
    c_losses = [float(l.split("loss:", 1)[1].split()[0]) for l in tr_clip.splitlines() if l.startswith("step:")]
    assert len(c_losses) == 20 and c_losses[-1] < c_losses[0] * 0.5 and clip_sf.exists(), tr_clip

    # 3. POST /v1/responses sync, previous_response_id continuation, tools + function_call_output, and SSE
    vocab = cfg["vocab_size"]
    dim = cfg["dim"]
    pieces = [f"tok_{i}" for i in range(vocab)]
    pieces[0] = "<|endoftext|>"
    pieces[1] = "<|im_start|>"
    pieces[2] = "<|im_end|>"
    pieces[3] = "user"
    pieces[4] = "assistant"
    pieces[5] = "system"
    pieces[7] = "\n"
    pieces[9] = "hi"
    pieces[10] = "<tool_call>"
    pieces[11] = "{\"name\":\"add\",\"arguments\":{\"a\":2,\"b\":3}}"
    pieces[12] = "</tool_call>"
    pieces[13] = "Result"

    zero_tensors = {k: (list(s), [f32(0.0)] * len(v)) for k, (s, v) in base_tensors.items()}
    zero_tensors["norm.weight"] = ([dim], [f32(1.0)] * dim)
    emb = [f32(0.0)] * (vocab * dim)
    head = [f32(0.0)] * (vocab * dim)
    for tid in range(vocab):
        emb[tid * dim] = f32(1.0)
    for col_idx, (src_tok, dst_tok) in enumerate([(7, 10), (10, 11), (11, 12), (12, 2)], start=1):
        emb[src_tok * dim + col_idx] = f32(1.0)
        head[dst_tok * dim + 0] = f32(2.0)
        head[dst_tok * dim + col_idx] = f32(5.0)
    zero_tensors["embed_tokens.weight"] = ([vocab, dim], emb)
    zero_tensors["lm_head.weight"] = ([vocab, dim], head)
    resp_gguf = work / "mini_responses.gguf"
    write_gguf_q4_0(resp_gguf, cfg, zero_tensors, vocab_pieces=pieces)

    proc = subprocess.Popen(
        [str(exes[1][2]), "serve", str(resp_gguf), "127.0.0.1:0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        url = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line and line.strip().startswith("serving:http://"):
                url = line.strip().split("serving:", 1)[1]
                break
        assert url, "responses server failed to start"

        def post_json(path, payload):
            req = urllib.request.Request(
                url + path,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.read().decode()

        # Sync tool call response
        r1 = json.loads(post_json("/v1/responses", {
            "model": "xu-local",
            "instructions": "Use tools.",
            "input": "hi",
            "tools": [{"type": "function", "name": "add", "description": "add", "parameters": {"type": "object"}}],
            "max_output_tokens": 8,
            "temperature": 0.0,
        }))
        assert r1["id"].startswith("resp_") and r1["status"] == "completed", r1
        fcs = [it for it in r1["output"] if it.get("type") == "function_call"]
        assert len(fcs) == 1 and fcs[0]["name"] == "add" and json.loads(fcs[0]["arguments"]) == {"a": 2, "b": 3}, r1

        # previous_response_id continuation with function_call_output
        r2 = json.loads(post_json("/v1/responses", {
            "model": "xu-local",
            "previous_response_id": r1["id"],
            "input": [{"type": "function_call_output", "call_id": fcs[0]["call_id"], "output": "{\"sum\":5}"}],
            "max_output_tokens": 4,
            "temperature": 0.0,
        }))
        assert r2["id"] != r1["id"] and r2["status"] == "completed" and r2["usage"]["input_tokens"] > r1["usage"]["input_tokens"], (r1, r2)

        # Streaming SSE /v1/responses (text deltas + tool_call output_item.done + completed)
        sse_txt = post_json("/v1/responses", {
            "model": "xu-local",
            "input": "hi",
            "max_output_tokens": 8,
            "temperature": 0.0,
            "stream": True,
        })
        assert "event: response.output_text.delta" in sse_txt and "event: response.completed" in sse_txt, sse_txt

        sse_raw = post_json("/v1/responses", {
            "model": "xu-local",
            "input": "hi",
            "tools": [{"type": "function", "name": "add", "parameters": {"type": "object"}}],
            "max_output_tokens": 8,
            "temperature": 0.0,
            "stream": True,
        })
        assert "event: response.output_item.done" in sse_raw and "event: response.completed" in sse_raw, sse_raw
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    print("GGUF Q5_K (--q8k-act), train-lora --max-grad-norm, and POST /v1/responses (sync/previous_response_id/tools/SSE) verified")


def check_v10_perplexity_sft_dpo_ollama_metrics(exes, work, cfg, tensors):
    import json
    import subprocess
    import urllib.request

    exe = exes[1][2] if len(exes) > 1 else exes[0][2]
    st_path = work / "v10_base.safetensors"
    write_safetensors(st_path, cfg, tensors)

    # 1. Sliding-window perplexity vs independent Python reference
    ppl_seq = [1, 7, 42, 3, 19, 5, 11, 23, 9]
    win, stride = 6, 2
    ppl_out = run([
        exe, "perplexity", str(st_path), "ids:" + ",".join(map(str, ppl_seq)),
        "--ctx", str(win), "--stride", str(stride),
    ])
    pkv = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in ppl_out.splitlines() if ":" in l}
    assert pkv["tokens"] == str(len(ppl_seq) - 1), pkv
    fnum, fden = map(int, pkv["kv_free_after"].split("/"))
    assert fnum == fden and fden > 0, pkv

    def py_token_nll(logits, target):
        mx = max(logits)
        lse = mx + math.log(sum(math.exp(v - mx) for v in logits))
        return lse - logits[target]

    py_nll_sum = 0.0
    scored_until = 1
    begin = 0
    while True:
        end = min(begin + win, len(ppl_seq))
        sub = ppl_seq[begin:end]
        if len(sub) >= 2:
            for k in range(len(sub) - 1):
                gpos = begin + k + 1
                if gpos >= scored_until:
                    _, _, logits_k = py_run_request(tensors, sub[:k + 1], 1, return_last_logits=True)
                    py_nll_sum += py_token_nll(logits_k, ppl_seq[gpos])
        if end >= len(ppl_seq):
            break
        scored_until = end
        begin = end - (win - stride)
    py_ppl = math.exp(py_nll_sum / (len(ppl_seq) - 1))
    assert abs(float(pkv["perplexity"]) - py_ppl) < 1e-4, (pkv, py_ppl)

    # 2. Full JSONL SFT with loss masking, grad accumulation, warmup + cosine LR
    sft_jsonl = work / "sft_train.jsonl"
    sft_jsonl.write_text(
        json.dumps({"prompt_ids": [1, 7], "completion_ids": [42, 3, 19]}) + "\n" +
        json.dumps({"prompt": "ids:3,19", "completion": "ids:5,11"}) + "\n"
    )
    sft_lora = work / "sft_lora.safetensors"
    sft_out = run([
        exe, "train-lora", str(st_path), str(sft_lora),
        "--dataset", str(sft_jsonl),
        "--grad-accum", "2", "--warmup-steps", "2", "--lr-schedule", "cosine",
        "--lora-rank", "4", "--lora-alpha", "8.0", "--steps", "12", "--lr", "0.08", "--max-grad-norm", "1.0",
    ])
    losses = []
    lrs = []
    for line in sft_out.splitlines():
        if line.startswith("step:"):
            parts = {p.split(":", 1)[0]: p.split(":", 1)[1] for p in line.split()}
            losses.append(float(parts["loss"]))
            lrs.append(float(parts["lr"]))
    assert len(losses) == 12 and losses[-1] < losses[0], losses
    assert lrs[0] < lrs[1] and lrs[-1] < lrs[1], lrs
    assert sft_lora.is_file()
    ver_sft = run([exe, "verify", str(st_path), "--lora", str(sft_lora)])
    assert "kv_free_after:" in ver_sft

    # 3. Direct Preference Optimization (train-dpo)
    dpo_jsonl = work / "dpo_pairs.jsonl"
    dpo_jsonl.write_text(
        json.dumps({"prompt_ids": [1, 7], "chosen_ids": [42, 3], "rejected_ids": [19, 5]}) + "\n"
    )
    dpo_lora = work / "dpo_lora.safetensors"
    dpo_out = run([
        exe, "train-dpo", str(st_path), str(dpo_jsonl), str(dpo_lora),
        "--dpo-beta", "0.25", "--lora-rank", "4", "--lora-alpha", "8.0",
        "--steps", "12", "--lr", "0.08", "--max-grad-norm", "1.0",
    ])
    dpo_losses, dpo_margins = [], []
    for line in dpo_out.splitlines():
        if line.startswith("step:"):
            parts = {p.split(":", 1)[0]: p.split(":", 1)[1] for p in line.split()}
            dpo_losses.append(float(parts["dpo_loss"]))
            dpo_margins.append(float(parts["margin"]))
    assert len(dpo_losses) == 12 and dpo_losses[-1] < dpo_losses[0], dpo_losses
    assert dpo_margins[-1] > dpo_margins[0] and dpo_margins[-1] > 0.0, dpo_margins
    assert dpo_lora.is_file()

    # 4. Ollama (/api/tags, /api/generate, /api/chat) + Prometheus /metrics
    gguf_ollama = work / "ollama_v10.gguf"
    pieces = [f"tok_{i}" for i in range(cfg["vocab_size"])]
    pieces[0], pieces[1], pieces[2] = "<|endoftext|>", "<|im_start|>", "<|im_end|>"
    pieces[3], pieces[4], pieces[7], pieces[9] = "user", "assistant", "\n", "hello"
    write_gguf_q4_0(gguf_ollama, cfg, tensors, vocab_pieces=pieces)

    proc = subprocess.Popen(
        [str(exe), "serve", str(gguf_ollama), "127.0.0.1:0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        base_url = None
        for _ in range(100):
            ln = proc.stdout.readline()
            if ln and ln.strip().startswith("serving:http://"):
                base_url = ln.strip().split("serving:", 1)[1]
                break
        assert base_url is not None

        def req_http(path, payload=None):
            data = None if payload is None else json.dumps(payload).encode()
            headers = {"Content-Type": "application/json"} if data is not None else {}
            req = urllib.request.Request(base_url + path, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode()

        st, _, tags_raw = req_http("/api/tags")
        assert st == 200 and json.loads(tags_raw)["models"][0]["name"] == str(gguf_ollama)

        st, _, gen_sync = req_http("/api/generate", {"model": "local", "prompt": "hello", "stream": False, "options": {"num_predict": 3, "temperature": 0}})
        gs_obj = json.loads(gen_sync)
        assert st == 200 and gs_obj["done"] is True and gs_obj["eval_count"] >= 1, gs_obj

        st, ct, gen_nd = req_http("/api/generate", {"model": "local", "prompt": "hello", "options": {"num_predict": 3}})
        nd_lines = [json.loads(l) for l in gen_nd.splitlines() if l.strip()]
        assert st == 200 and "ndjson" in ct and len(nd_lines) >= 2 and nd_lines[-1]["done"] is True, (ct, nd_lines)

        st, _, chat_sync = req_http("/api/chat", {"model": "local", "messages": [{"role": "user", "content": "hello"}], "stream": False, "options": {"num_predict": 3}})
        cs_obj = json.loads(chat_sync)
        assert st == 200 and cs_obj["done"] is True and cs_obj["message"]["role"] == "assistant", cs_obj

        st, ct, metrics_raw = req_http("/metrics")
        assert st == 200 and "text/plain" in ct and "xu_llm_requests_total " in metrics_raw and "xu_llm_completion_tokens_total " in metrics_raw, (ct, metrics_raw)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    print("perplexity, JSONL SFT (--dataset/--grad-accum/--lr-schedule cosine), train-dpo, Ollama /api/*, and Prometheus /metrics verified")


def check_v11_inspect_merge_grpo_distill(exes, work, cfg, tensors):
    exe = exes[1][2] if len(exes) > 1 else exes[0][2]
    st_path = work / "v11_base.safetensors"
    write_safetensors(st_path, cfg, tensors)

    # 1. inspect diagnostics
    insp_out = run([exe, "inspect", str(st_path)])
    ikv = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in insp_out.splitlines() if ":" in l}
    assert ikv["dim"] == str(cfg["dim"]) and ikv["n_layers"] == str(cfg["n_layers"])
    assert ikv["vocab_size"] == str(cfg["vocab_size"])
    assert int(ikv["est_params"]) > 0
    kv32 = int(ikv["kv_bytes_per_tok_f32"])
    kv16 = int(ikv["kv_bytes_per_tok_f16"])
    kv8 = int(ikv["kv_bytes_per_tok_fp8"])
    assert kv32 == kv16 * 2 and kv32 == kv8 * 4 and kv32 > 0, ikv

    # 2. train-lora -> merge-lora parity
    lora_sf = work / "v11_lora.safetensors"
    run([exe, "train-lora", str(st_path), "ids:1,7,42,19", str(lora_sf), "--lora-rank", "4", "--lora-alpha", "16.0", "--steps", "20", "--lr", "0.2"])
    merged_sf = work / "v11_merged.safetensors"
    m_out = run([exe, "merge-lora", str(st_path), str(lora_sf), str(merged_sf)])
    assert "merged_tensors:1" in m_out and merged_sf.is_file(), m_out
    g_lora = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in run([exe, "generate", str(st_path), "ids:1,7", "3", "0", "40", "--lora", str(lora_sf)]).splitlines() if ":" in l}
    g_merged = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in run([exe, "generate", str(merged_sf), "ids:1,7", "3", "0", "40"]).splitlines() if ":" in l}
    assert g_lora["generated_ids"] == g_merged["generated_ids"], (g_lora, g_merged)

    # 3. train-grpo RL fine-tuning
    grpo_jsonl = work / "grpo_groups.jsonl"
    grpo_jsonl.write_text(json.dumps({
        "prompt_ids": [1, 7],
        "completions": [
            {"ids": [42, 3], "reward": 2.0},
            {"ids": [19, 5], "reward": 0.0},
            {"ids": [11, 23], "reward": 1.0},
        ],
    }) + "\n")
    grpo_lora = work / "v11_grpo.safetensors"
    grpo_out = run([
        exe, "train-grpo", str(st_path), str(grpo_jsonl), str(grpo_lora),
        "--clip-eps", "0.2", "--kl-beta", "0.04", "--lora-rank", "4", "--lora-alpha", "8.0",
        "--steps", "12", "--lr", "0.008", "--max-grad-norm", "1.0",
    ])
    g_losses, g_advs = [], []
    for ln in grpo_out.splitlines():
        if ln.startswith("step:"):
            parts = {p.split(":", 1)[0]: p.split(":", 1)[1] for p in ln.split()}
            g_losses.append(float(parts["grpo_loss"]))
            g_advs.append(float(parts["avg_adv_logp"]))
    assert len(g_losses) == 12 and g_losses[-1] < g_losses[0], g_losses
    assert g_advs[-1] > g_advs[0], g_advs
    assert "kv_free_after:4/4" in grpo_out and grpo_lora.is_file(), grpo_out

    # 4. train-distill knowledge distillation
    teacher_tensors = {k: (shape, list(vals)) for k, (shape, vals) in tensors.items()}
    lm_shape, lm_vals = tensors["lm_head.weight"]
    teacher_tensors["lm_head.weight"] = (lm_shape, [v * 6.0 for v in lm_vals])
    teacher_sf = work / "v11_teacher.safetensors"
    write_safetensors(teacher_sf, cfg, teacher_tensors)
    distill_lora = work / "v11_distill.safetensors"
    dist_out = run([
        exe, "train-distill", str(st_path), "ids:1,7,42,19", str(distill_lora),
        "--teacher", str(teacher_sf), "--distill-temp", "2.0", "--distill-alpha", "0.7",
        "--lora-rank", "4", "--lora-alpha", "8.0", "--steps", "12", "--lr", "0.02", "--max-grad-norm", "1.0",
    ])
    d_losses, d_kls = [], []
    for ln in dist_out.splitlines():
        if ln.startswith("step:"):
            parts = {p.split(":", 1)[0]: p.split(":", 1)[1] for p in ln.split()}
            d_losses.append(float(parts["distill_loss"]))
            d_kls.append(float(parts["kl"]))
    assert len(d_losses) == 12 and d_losses[-1] < d_losses[0] and d_kls[-1] < d_kls[0], (d_losses, d_kls)
    assert "kv_free_after:4/4" in dist_out and distill_lora.is_file(), dist_out
    print("inspect, merge-lora, train-grpo, and train-distill verified")


def check_v12_gbnf_ckpt_models(exes, work, cfg, tensors):
    import http.server
    import json
    import subprocess
    import threading
    import urllib.request

    exe = exes[1][2] if len(exes) > 1 else exes[0][2]

    # 1. Generic GBNF grammar constrained decoding (CLI + HTTP serve)
    gguf_gbnf = work / "gbnf_v12.gguf"
    pieces = [f"tok_{i}" for i in range(cfg["vocab_size"])]
    pieces[0] = "<|endoftext|>"
    pieces[2] = "<|im_end|>"
    write_gguf_q4_0(gguf_gbnf, cfg, tensors, vocab_pieces=pieces)

    gbnf_file = work / "choice.gbnf"
    gbnf_file.write_text('root ::= ("tok_1" | "tok_5") ("tok_3" | "tok_4")\n')

    cli_file_out = run([exe, "generate", str(gguf_gbnf), "ids:1,5", "4", "0", "40", "--grammar", str(gbnf_file)])
    gkv1 = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in cli_file_out.splitlines() if ":" in l}
    gids1 = [int(x) for x in gkv1["generated_ids"].split(",") if x]
    assert len(gids1) == 2 and gids1[0] in (1, 5) and gids1[1] in (3, 4), (gids1, gkv1)
    assert gkv1["generated_text"] in ("tok_1tok_3", "tok_1tok_4", "tok_5tok_3", "tok_5tok_4"), gkv1

    cli_inline_out = run([exe, "generate", str(gguf_gbnf), "ids:1,3", "4", "0", "40", "--grammar", 'root ::= ("tok_6" | "tok_7")'])
    gkv2 = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in cli_inline_out.splitlines() if ":" in l}
    gids2 = [int(x) for x in gkv2["generated_ids"].split(",") if x]
    assert len(gids2) == 1 and gids2[0] in (6, 7), (gids2, gkv2)
    assert gkv2["generated_text"] in ("tok_6", "tok_7"), gkv2

    proc = subprocess.Popen(
        [str(exe), "serve", str(gguf_gbnf), "127.0.0.1:0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        base_url = None
        for _ in range(100):
            ln = proc.stdout.readline()
            if ln and ln.strip().startswith("serving:http://"):
                base_url = ln.strip().split("serving:", 1)[1]
                break
        assert base_url is not None

        def post_srv(path, payload):
            req = urllib.request.Request(
                base_url + path,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode())

        st1, obj1 = post_srv("/v1/completions", {
            "model": "local",
            "prompt": "tok_1",
            "max_tokens": 4,
            "temperature": 0,
            "grammar": 'root ::= ("tok_1" | "tok_5") ("tok_3" | "tok_4")',
        })
        assert st1 == 200 and obj1["choices"][0]["text"] in ("tok_1tok_3", "tok_1tok_4", "tok_5tok_3", "tok_5tok_4"), obj1

        st2, obj2 = post_srv("/v1/chat/completions", {
            "model": "local",
            "messages": [{"role": "user", "content": "tok_1"}],
            "max_tokens": 4,
            "temperature": 0,
            "grammar": 'root ::= ("tok_8" | "tok_9")',
        })
        assert st2 == 200 and obj2["choices"][0]["message"]["content"] in ("tok_8", "tok_9"), obj2
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)

    # 2. SFT LoRA optimizer + weight checkpoint save & resume
    st_path = work / "v12_base.safetensors"
    write_safetensors(st_path, cfg, tensors)
    lora_full = work / "v12_full.safetensors"
    full_out = run([
        exe, "train-lora", str(st_path), "ids:1,7,42,19", str(lora_full),
        "--lora-rank", "4", "--lora-alpha", "16.0", "--steps", "10", "--lr", "0.1",
    ])
    full_losses = {}
    for ln in full_out.splitlines():
        if ln.startswith("step:"):
            kv = {p.split(":", 1)[0]: p.split(":", 1)[1] for p in ln.split()}
            full_losses[int(kv["step"])] = float(kv["loss"])
    assert len(full_losses) == 10, full_out

    ckpt_path = work / "v12_sft.ckpt.safetensors"
    lora_p1 = work / "v12_part1.safetensors"
    p1_out = run([
        exe, "train-lora", str(st_path), "ids:1,7,42,19", str(lora_p1),
        "--lora-rank", "4", "--lora-alpha", "16.0", "--steps", "5", "--lr", "0.1",
        "--save-ckpt", str(ckpt_path),
    ])
    assert f"saved_ckpt:{ckpt_path}" in p1_out and ckpt_path.is_file(), p1_out

    lora_resumed = work / "v12_resumed.safetensors"
    p2_out = run([
        exe, "train-lora", str(st_path), "ids:1,7,42,19", str(lora_resumed),
        "--lora-rank", "4", "--lora-alpha", "16.0", "--steps", "10", "--lr", "0.1",
        "--resume-ckpt", str(ckpt_path),
    ])
    assert "resumed_step:5" in p2_out, p2_out
    res_losses = {}
    for ln in p2_out.splitlines():
        if ln.startswith("step:"):
            kv = {p.split(":", 1)[0]: p.split(":", 1)[1] for p in ln.split()}
            res_losses[int(kv["step"])] = float(kv["loss"])
    assert list(sorted(res_losses.keys())) == [6, 7, 8, 9, 10], res_losses
    for s in range(6, 11):
        assert abs(res_losses[s] - full_losses[s]) < 1e-6, (s, res_losses[s], full_losses[s])
    assert lora_resumed.read_bytes() == lora_full.read_bytes(), "resumed LoRA SafeTensors mismatch"

    # 3. Local model cache manager (models pull / list / rm + path traversal check)
    demo_payload = b"GGUF_DEMO_PAYLOAD_V12"
    seen_paths = []

    class HfMockHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            seen_paths.append(self.path)
            if self.path == "/org/repo/resolve/main/demo.gguf":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(demo_payload)))
                self.end_headers()
                self.wfile.write(demo_payload)
            else:
                self.send_response(404)
                self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HfMockHandler)
    srv_thread = threading.Thread(target=srv.serve_forever, daemon=True)
    srv_thread.start()
    try:
        port = srv.server_address[1]
        models_dir = work / "models_cache"
        hf_env = dict(os.environ, XU_HF_BASE_URL=f"http://127.0.0.1:{port}")
        pull_out = subprocess.run(
            [str(exe), "models", "pull", "hf://org/repo/demo.gguf", "demo.gguf", "--models-dir", str(models_dir)],
            env=hf_env, check=True, capture_output=True, text=True,
        ).stdout
        assert "pulled:" in pull_out and f"bytes:{len(demo_payload)}" in pull_out, pull_out
        assert seen_paths == ["/org/repo/resolve/main/demo.gguf"], seen_paths
        assert (models_dir / "demo.gguf").read_bytes() == demo_payload

        list1 = run([exe, "models", "list", "--models-dir", str(models_dir)])
        assert "model:demo.gguf" in list1 and f"bytes:{len(demo_payload)}" in list1 and "count:1" in list1, list1

        bad_rm = subprocess.run(
            [str(exe), "models", "rm", "../escape", "--models-dir", str(models_dir)],
            check=False, capture_output=True, text=True,
        )
        assert bad_rm.returncode != 0, bad_rm

        rm_out = run([exe, "models", "rm", "demo.gguf", "--models-dir", str(models_dir)])
        assert "removed:demo.gguf" in rm_out and not (models_dir / "demo.gguf").exists(), rm_out

        list2 = run([exe, "models", "list", "--models-dir", str(models_dir)])
        assert "count:0" in list2, list2
    finally:
        srv.shutdown()
        srv.server_close()

    print("GBNF constrained decoding (CLI + HTTP), SFT --save-ckpt/--resume-ckpt, and models pull/list/rm verified")


def check_v13_mamba_rlvr_quantize(exes, work, cfg, tensors):
    rng = random.Random(20261126)

    def write_custom_gguf(path, extra_kv, tensor_specs, vocab_pieces):
        kv_entries = list(extra_kv)
        kv_entries.append((
            "tokenizer.ggml.tokens", 9,
            struct.pack("<IQ", 8, len(vocab_pieces)) + b"".join(pack_gguf_str(p) for p in vocab_pieces),
        ))
        kv_data = bytearray()
        for k, vtype, vbytes in kv_entries:
            kv_data.extend(pack_gguf_str(k))
            kv_data.extend(struct.pack("<I", vtype))
            kv_data.extend(vbytes)

        cur_off = 0
        t_infos = []
        payload = bytearray()
        for gname, dims, gtype, raw in tensor_specs:
            pad = (32 - (cur_off % 32)) % 32
            if pad:
                payload.extend(b"\x00" * pad)
                cur_off += pad
            t_infos.append((gname, dims, gtype, cur_off))
            payload.extend(raw)
            cur_off += len(raw)

        hdr = bytearray()
        hdr.extend(b"GGUF")
        hdr.extend(struct.pack("<IQQ", 3, len(t_infos), len(kv_entries)))
        hdr.extend(kv_data)
        for gname, dims, gtype, toff in t_infos:
            hdr.extend(pack_gguf_str(gname))
            hdr.extend(struct.pack("<I", len(dims)))
            for d in dims:
                hdr.extend(struct.pack("<Q", d))
            hdr.extend(struct.pack("<IQ", gtype, toff))
        hpad = (32 - (len(hdr) % 32)) % 32
        if hpad:
            hdr.extend(b"\x00" * hpad)
        path.write_bytes(bytes(hdr) + bytes(payload))

    def silu_f(v):
        if v >= 0.0:
            return v / (1.0 + math.exp(-v))
        ev = math.exp(v)
        return v * ev / (1.0 + ev)

    def softplus_f(u):
        if u > 20.0:
            return u
        if u < -20.0:
            return math.exp(u)
        return math.log(1.0 + math.exp(u))

    def matvec_f32_py(mat, x_vec, rows, cols):
        out = []
        for r in range(rows):
            row_b = r * cols
            acc = 0.0
            for c in range(cols):
                acc += float(mat[row_b + c]) * float(x_vec[c])
            out.append(f32(acc))
        return out

    def py_mamba_and_hybrid_eval(model_cfg, layer_defs, emb_w, final_norm_w, lm_w, prompt, max_gen):
        dim = model_cfg["dim"]
        n_layers = model_cfg["n_layers"]
        vocab = model_cfg["vocab_size"]
        d_inner = model_cfg["d_inner"]
        d_conv = model_cfg["d_conv"]
        d_state = model_cfg["d_state"]
        dt_rank = model_cfg["dt_rank"]
        n_heads = model_cfg.get("n_heads", 1)
        n_kv_heads = model_cfg.get("n_kv_heads", 1)
        head_dim = model_cfg.get("head_dim", dim)
        hidden = model_cfg.get("hidden_dim", d_inner)

        conv_states = [[f32(0.0)] * (d_inner * (d_conv - 1)) for _ in range(n_layers)]
        ssm_states = [[f32(0.0)] * (d_inner * d_state) for _ in range(n_layers)]
        k_cache = [[] for _ in range(n_layers)]
        v_cache = [[] for _ in range(n_layers)]

        def step(tok, pos):
            x = [emb_w[tok * dim + i] for i in range(dim)]
            zeros_dim = [f32(0.0)] * dim
            xb2 = [f32(0.0)] * dim
            for l in range(n_layers):
                ld = layer_defs[l]
                xb = py_rmsnorm(x, zeros_dim, ld["attn_norm"])
                if ld["kind"] == "mamba":
                    xz = matvec_f32_py(ld["ssm_in"], xb, 2 * d_inner, dim)
                    x_proj = xz[:d_inner]
                    z = xz[d_inner:]
                    cs = conv_states[l]
                    cw = ld["ssm_conv1d_w"]
                    cb = ld["ssm_conv1d_b"]
                    x_conv = [f32(0.0)] * d_inner
                    for d in range(d_inner):
                        acc = float(cb[d])
                        wbase = d * d_conv
                        sbase = d * (d_conv - 1)
                        for j in range(d_conv - 1):
                            acc += float(cs[sbase + j]) * float(cw[wbase + j])
                        acc += float(x_proj[d]) * float(cw[wbase + d_conv - 1])
                        for j in range(d_conv - 2):
                            cs[sbase + j] = cs[sbase + j + 1]
                        cs[sbase + d_conv - 2] = x_proj[d]
                        x_conv[d] = f32(silu_f(acc))
                    xdbl = matvec_f32_py(ld["ssm_x"], x_conv, dt_rank + 2 * d_state, d_inner)
                    dt_raw = xdbl[:dt_rank]
                    b_vec = xdbl[dt_rank:dt_rank + d_state]
                    c_vec = xdbl[dt_rank + d_state:]
                    dt_p = matvec_f32_py(ld["ssm_dt"], dt_raw, d_inner, dt_rank)
                    dtb = ld["ssm_dt_b"]
                    dt_vec = [f32(softplus_f(float(dt_p[d]) + float(dtb[d]))) for d in range(d_inner)]
                    ss = ssm_states[l]
                    sa = ld["ssm_a"]
                    sd = ld["ssm_d"]
                    y_ssm = [f32(0.0)] * d_inner
                    for d in range(d_inner):
                        xv = float(x_conv[d])
                        dtv = float(dt_vec[d])
                        sbase = d * d_state
                        y = 0.0
                        for s in range(d_state):
                            da = math.exp(dtv * float(sa[sbase + s]))
                            h_new = f32(da * float(ss[sbase + s]) + dtv * float(b_vec[s]) * xv)
                            ss[sbase + s] = h_new
                            y += float(h_new) * float(c_vec[s])
                        y += float(sd[d]) * xv
                        y_ssm[d] = f32(y * silu_f(float(z[d])))
                    xb2 = matvec_f32_py(ld["ssm_out"], y_ssm, dim, d_inner)
                else:
                    kv_dim = n_kv_heads * head_dim
                    kv_mul = n_heads // n_kv_heads
                    q = py_rope(matvec_f32_py(ld["wq"], xb, dim, dim), n_heads, head_dim, pos, 10000.0)
                    k = py_rope(matvec_f32_py(ld["wk"], xb, kv_dim, dim), n_kv_heads, head_dim, pos, 10000.0)
                    v = matvec_f32_py(ld["wv"], xb, kv_dim, dim)
                    k_cache[l].append(k)
                    v_cache[l].append(v)
                    attn_out = [f32(0.0)] * dim
                    scale = 1.0 / math.sqrt(head_dim)
                    for h in range(n_heads):
                        qh = q[h * head_dim:(h + 1) * head_dim]
                        kvh = (h // kv_mul) * head_dim
                        scores = []
                        for kp in range(pos + 1):
                            kh = k_cache[l][kp][kvh:kvh + head_dim]
                            scores.append(sum(qh[d] * kh[d] for d in range(head_dim)) * scale)
                        mx = max(scores)
                        exps = [math.exp(s - mx) for s in scores]
                        denom = sum(exps)
                        probs = [e / denom for e in exps]
                        for d in range(head_dim):
                            attn_out[h * head_dim + d] = f32(
                                sum(probs[kp] * v_cache[l][kp][kvh + d] for kp in range(pos + 1))
                            )
                    xb2 = matvec_f32_py(ld["wo"], attn_out, dim, dim)
                    x = [f32(x[i] + xb2[i]) for i in range(dim)]
                    xb_f = py_rmsnorm(x, zeros_dim, ld["ffn_norm"])
                    hb1 = matvec_f32_py(ld["w1"], xb_f, hidden, dim)
                    hb3 = matvec_f32_py(ld["w3"], xb_f, hidden, dim)
                    act = [f32(silu_f(hb1[i]) * hb3[i]) for i in range(hidden)]
                    xb2 = matvec_f32_py(ld["w2"], act, dim, hidden)
                if l + 1 < n_layers:
                    x = [f32(x[i] + xb2[i]) for i in range(dim)]

            xn = py_rmsnorm(x, xb2, final_norm_w)
            logits = matvec_f32_py(lm_w, xn, vocab, dim)
            best = max(range(vocab), key=lambda i: logits[i])
            return best, logits[best]

        pos = 0
        tok = 0
        for p in prompt:
            tok, best_logit = step(p, pos)
            pos += 1
        out_toks = [tok]
        out_logits = [best_logit]
        for _ in range(1, max_gen):
            tok, best_logit = step(tok, pos)
            pos += 1
            out_toks.append(tok)
            out_logits.append(best_logit)
        return out_toks, out_logits

    def build_mamba_or_hybrid_fixture(path, hybrid):
        m_dim, d_inner, d_conv, d_state, dt_rank, m_vocab = 16, 32, 4, 8, 4, 64
        m_layers = 2
        n_heads, n_kv_heads = (2, 1) if hybrid else (1, 1)
        head_dim = m_dim // n_heads
        hidden = 32
        emb_w = gen_weights(rng, m_vocab * m_dim, 0.25)
        final_w = [f32(0.9 + 0.2 * rng.random()) for _ in range(m_dim)]
        lm_w = gen_weights(rng, m_vocab * m_dim, 0.2)
        pieces = [f"t{i}" for i in range(m_vocab)]
        pieces[0], pieces[1], pieces[2] = "<unk>", "<s>", "</s>"

        tspecs = [("token_embd.weight", [m_dim, m_vocab], 0, struct.pack(f"<{len(emb_w)}f", *emb_w))]
        layer_defs = []
        for l in range(m_layers):
            gp = f"blk.{l}."
            an = [f32(0.9 + 0.2 * rng.random()) for _ in range(m_dim)]
            tspecs.append((gp + "attn_norm.weight", [m_dim], 0, struct.pack(f"<{len(an)}f", *an)))
            if not hybrid or l == 0:
                s_in = gen_weights(rng, 2 * d_inner * m_dim, 0.25)
                cw = gen_weights(rng, d_inner * d_conv, 0.2)
                cb = gen_weights(rng, d_inner, 0.05)
                sx = gen_weights(rng, (dt_rank + 2 * d_state) * d_inner, 0.25)
                sdt = gen_weights(rng, d_inner * dt_rank, 0.25)
                sdt_b = gen_weights(rng, d_inner, 0.1)
                sa = [f32(-math.exp(rng.uniform(-1.5, 0.2))) for _ in range(d_inner * d_state)]
                sd = gen_weights(rng, d_inner, 0.2)
                sout = gen_weights(rng, m_dim * d_inner, 0.25)
                tspecs.extend([
                    (gp + "ssm_in.weight", [m_dim, 2 * d_inner], 0, struct.pack(f"<{len(s_in)}f", *s_in)),
                    (gp + "ssm_conv1d.weight", [d_conv, d_inner], 0, struct.pack(f"<{len(cw)}f", *cw)),
                    (gp + "ssm_conv1d.bias", [d_inner], 0, struct.pack(f"<{len(cb)}f", *cb)),
                    (gp + "ssm_x.weight", [d_inner, dt_rank + 2 * d_state], 0, struct.pack(f"<{len(sx)}f", *sx)),
                    (gp + "ssm_dt.weight", [dt_rank, d_inner], 0, struct.pack(f"<{len(sdt)}f", *sdt)),
                    (gp + "ssm_dt.bias", [d_inner], 0, struct.pack(f"<{len(sdt_b)}f", *sdt_b)),
                    (gp + "ssm_a", [d_state, d_inner], 0, struct.pack(f"<{len(sa)}f", *sa)),
                    (gp + "ssm_d", [d_inner], 0, struct.pack(f"<{len(sd)}f", *sd)),
                    (gp + "ssm_out.weight", [d_inner, m_dim], 0, struct.pack(f"<{len(sout)}f", *sout)),
                ])
                layer_defs.append({
                    "kind": "mamba", "attn_norm": an, "ssm_in": s_in, "ssm_conv1d_w": cw, "ssm_conv1d_b": cb,
                    "ssm_x": sx, "ssm_dt": sdt, "ssm_dt_b": sdt_b, "ssm_a": sa, "ssm_d": sd, "ssm_out": sout,
                })
            else:
                kv_dim = n_kv_heads * head_dim
                wq = gen_weights(rng, m_dim * m_dim, 0.25)
                wk = gen_weights(rng, kv_dim * m_dim, 0.25)
                wv = gen_weights(rng, kv_dim * m_dim, 0.25)
                wo = gen_weights(rng, m_dim * m_dim, 0.25)
                fn_w = [f32(0.9 + 0.2 * rng.random()) for _ in range(m_dim)]
                w1 = gen_weights(rng, hidden * m_dim, 0.25)
                w3 = gen_weights(rng, hidden * m_dim, 0.25)
                w2 = gen_weights(rng, m_dim * hidden, 0.25)
                tspecs.extend([
                    (gp + "ffn_norm.weight", [m_dim], 0, struct.pack(f"<{len(fn_w)}f", *fn_w)),
                    (gp + "attn_q.weight", [m_dim, m_dim], 0, struct.pack(f"<{len(wq)}f", *wq)),
                    (gp + "attn_k.weight", [m_dim, kv_dim], 0, struct.pack(f"<{len(wk)}f", *wk)),
                    (gp + "attn_v.weight", [m_dim, kv_dim], 0, struct.pack(f"<{len(wv)}f", *wv)),
                    (gp + "attn_output.weight", [m_dim, m_dim], 0, struct.pack(f"<{len(wo)}f", *wo)),
                    (gp + "ffn_gate.weight", [m_dim, hidden], 0, struct.pack(f"<{len(w1)}f", *w1)),
                    (gp + "ffn_up.weight", [m_dim, hidden], 0, struct.pack(f"<{len(w3)}f", *w3)),
                    (gp + "ffn_down.weight", [hidden, m_dim], 0, struct.pack(f"<{len(w2)}f", *w2)),
                ])
                layer_defs.append({
                    "kind": "attn", "attn_norm": an, "ffn_norm": fn_w,
                    "wq": wq, "wk": wk, "wv": wv, "wo": wo, "w1": w1, "w3": w3, "w2": w2,
                })
        tspecs.append(("output_norm.weight", [m_dim], 0, struct.pack(f"<{len(final_w)}f", *final_w)))
        tspecs.append(("output.weight", [m_dim, m_vocab], 0, struct.pack(f"<{len(lm_w)}f", *lm_w)))

        arch = "jamba" if hybrid else "mamba"
        extra_kv = [
            ("general.architecture", 8, pack_gguf_str(arch)),
            (f"{arch}.embedding_length", 4, struct.pack("<I", m_dim)),
            (f"{arch}.block_count", 4, struct.pack("<I", m_layers)),
            (f"{arch}.context_length", 4, struct.pack("<I", 64)),
            (f"{arch}.attention.layer_norm_rms_epsilon", 6, struct.pack("<f", 1e-5)),
            (f"{arch}.ssm.conv_kernel", 4, struct.pack("<I", d_conv)),
            (f"{arch}.ssm.inner_size", 4, struct.pack("<I", d_inner)),
            (f"{arch}.ssm.state_size", 4, struct.pack("<I", d_state)),
            (f"{arch}.ssm.time_step_rank", 4, struct.pack("<I", dt_rank)),
        ]
        if hybrid:
            extra_kv.extend([
                (f"{arch}.feed_forward_length", 4, struct.pack("<I", hidden)),
                (f"{arch}.attention.head_count", 4, struct.pack("<I", n_heads)),
                (f"{arch}.attention.head_count_kv", 4, struct.pack("<I", n_kv_heads)),
                (f"{arch}.rope.freq_base", 6, struct.pack("<f", 10000.0)),
            ])
        write_custom_gguf(path, extra_kv, tspecs, pieces)
        m_cfg = {
            "dim": m_dim, "n_layers": m_layers, "vocab_size": m_vocab,
            "d_inner": d_inner, "d_conv": d_conv, "d_state": d_state, "dt_rank": dt_rank,
            "n_heads": n_heads, "n_kv_heads": n_kv_heads, "head_dim": head_dim, "hidden_dim": hidden,
        }
        return [py_mamba_and_hybrid_eval(m_cfg, layer_defs, emb_w, final_w, lm_w, p, g) for p, g in REQUESTS]

    # 1. Pure Mamba GGUF + Hybrid Attention+Mamba GGUF parity across all modes (seq & cb)
    mamba_gguf = work / "v13_mamba.gguf"
    hybrid_gguf = work / "v13_hybrid_mamba.gguf"
    py_mamba_ref = build_mamba_or_hybrid_fixture(mamba_gguf, False)
    py_hybrid_ref = build_mamba_or_hybrid_fixture(hybrid_gguf, True)

    exe = exes[1][2] if len(exes) > 1 else exes[0][2]
    insp_mamba = run([exe, "inspect", str(mamba_gguf)])
    assert "is_mamba:true" in insp_mamba and "ssm_inner_size:32" in insp_mamba and "ssm_state_size:8" in insp_mamba, insp_mamba

    for label, gpath, ref in (("pure-mamba", mamba_gguf, py_mamba_ref), ("hybrid-mamba-attn", hybrid_gguf, py_hybrid_ref)):
        for name, _fast, mode_exe, _kb in exes:
            vout = run([mode_exe, "verify", str(gpath)])
            assert "is_mamba:true" in vout and "kv_free_after:16/16" in vout, f"{label}/{name}: {vout}"
            seq_rows, cb_rows, _meta = parse_verify(vout)
            assert len(seq_rows) == len(REQUESTS) and cb_rows == seq_rows, f"{label}/{name} seq!=cb"
            for r, (py_toks, py_logits) in enumerate(ref):
                xu_pairs = seq_rows[r]
                xu_toks = [t for t, _b in xu_pairs]
                xu_bits = [b for _t, b in xu_pairs]
                assert xu_toks == py_toks, f"{label}/{name} req {r} tok mismatch: {xu_toks} vs {py_toks}"
                for b, p in zip(xu_bits, py_logits):
                    assert abs(bits_to_f32(b) - p) < 1e-4, f"{label}/{name} logit mismatch: {bits_to_f32(b)} vs {p}"

    # 2. Online RLVR (train-rlvr) verifiable-reward GRPO
    st_path = work / "v13_base.safetensors"
    write_safetensors(st_path, cfg, tensors)
    rlvr_jsonl = work / "v13_rlvr_tasks.jsonl"
    # Pick target token 5 so verifiable reward triggers cleanly when sampled
    rlvr_jsonl.write_text(
        '{"prompt_ids": [1, 7], "expected_ids": [5]}\n'
        '{"prompt_ids": [3, 19], "expected_ids": [5]}\n'
    )
    rlvr_lora = work / "v13_rlvr.safetensors"
    rlvr_out = run([
        exe, "train-rlvr", str(st_path), str(rlvr_jsonl), str(rlvr_lora),
        "--verifier", "contains", "--group-size", "4", "--gen-tokens", "4",
        "--temp", "1200", "--clip-eps", "0.2", "--kl-beta", "0.02",
        "--lora-rank", "4", "--lora-alpha", "16.0", "--steps", "8", "--lr", "0.05", "--max-grad-norm", "1.0",
    ])
    rlvr_steps = [ln for ln in rlvr_out.splitlines() if ln.startswith("step:")]
    assert len(rlvr_steps) == 8 and rlvr_lora.is_file() and "kv_free_after:4/4" in rlvr_out, rlvr_out
    assert all("avg_reward:" in s and "rlvr_loss:" in s for s in rlvr_steps), rlvr_steps
    rlvr_gen = run([exe, "generate", str(st_path), "ids:1,7", "3", "0", "40", "--lora", str(rlvr_lora)])
    assert "generated_ids:" in rlvr_gen, rlvr_gen

    # 3. Offline GGUF quantizer (quantize --type q4_0 & q8_0 + merge-lora -> quantize roundtrip)
    q4_gguf = work / "v13_quant_q4_0.gguf"
    q8_gguf = work / "v13_quant_q8_0.gguf"
    q4_out = run([exe, "quantize", str(st_path), str(q4_gguf), "--type", "q4_0"])
    assert "quant_type:q4_0" in q4_out and "quantized_tensors:" in q4_out and q4_gguf.is_file(), q4_out
    v_q4 = run([exe, "verify", str(q4_gguf)])
    assert "format:q4_0" in v_q4 and "kv_free_after:16/16" in v_q4, v_q4
    s4, c4, _ = parse_verify(v_q4)
    assert s4 == c4

    q8_out = run([exe, "quantize", str(st_path), str(q8_gguf), "--type", "q8_0"])
    assert "quant_type:q8_0" in q8_out and q8_gguf.is_file(), q8_out
    v_q8 = run([exe, "verify", str(q8_gguf)])
    assert "format:q8_0" in v_q8 and "kv_free_after:16/16" in v_q8, v_q8
    s8, c8, _ = parse_verify(v_q8)
    assert s8 == c8
    g_q8 = run([exe, "generate", str(q8_gguf), "ids:1,7,42", "4", "0", "40"])
    assert "generated_ids:" in g_q8 and "kv_free_after:4/4" in g_q8, g_q8

    merged_sf = work / "v13_merged.safetensors"
    run([exe, "merge-lora", str(st_path), str(rlvr_lora), str(merged_sf)])
    merged_q4 = work / "v13_merged_q4_0.gguf"
    mq4_out = run([exe, "quantize", str(merged_sf), str(merged_q4), "--type", "q4_0"])
    assert "quant_type:q4_0" in mq4_out and merged_q4.is_file(), mq4_out
    assert "format:q4_0" in run([exe, "verify", str(merged_q4)])

    print("Mamba SSM + Hybrid Attention+SSM GGUF, train-rlvr, and offline GGUF quantizer (q4_0/q8_0) verified")


def check_v14_vlm_and_q4k_quantize(exes, work: Path, cfg: dict, tensors: dict):
    import base64
    import json as pyjson
    import subprocess
    import urllib.request

    def vlm_post_json(url, payload):
        req = urllib.request.Request(
            url,
            data=pyjson.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, pyjson.loads(resp.read().decode("utf-8"))

    exe = exes[1][2] if len(exes) > 1 else exes[0][2]

    # 1. Native Multimodal VLM (--mmproj ViT+MLP, --image PPM/BMP/rgb:, and HTTP /v1/chat/completions image_url)
    st_path = work / "v14_llm.safetensors"
    write_safetensors(st_path, cfg, tensors)
    gguf_path = work / "v14_llm.gguf"
    pieces = [f"tok_{i}" for i in range(cfg["vocab_size"])]
    write_gguf_q4_0(gguf_path, cfg, tensors, vocab_pieces=pieces)

    img_sz = 8
    patch_sz = 4
    in_c = 3
    hid = 16
    nl = 1
    nh = 2
    head_dim = hid // nh
    ffn_d = 32
    proj_d = cfg["dim"]
    grid = img_sz // patch_sz
    n_patches = grid * grid
    rng = random.Random(20261127)

    v_tensors = {
        "v.patch_embd.weight": [f32(rng.uniform(-0.3, 0.3)) for _ in range(hid * in_c * patch_sz * patch_sz)],
        "v.patch_embd.bias": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.position_embd.weight": [f32(rng.uniform(-0.1, 0.1)) for _ in range(n_patches * hid)],
        "v.blk.0.ln1_w": [f32(rng.uniform(0.8, 1.2)) for _ in range(hid)],
        "v.blk.0.ln1_b": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.wq": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * hid)],
        "v.blk.0.bq": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.wk": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * hid)],
        "v.blk.0.bk": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.wv": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * hid)],
        "v.blk.0.bv": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.wo": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * hid)],
        "v.blk.0.bo": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.ln2_w": [f32(rng.uniform(0.8, 1.2)) for _ in range(hid)],
        "v.blk.0.ln2_b": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.w1": [f32(rng.uniform(-0.2, 0.2)) for _ in range(ffn_d * hid)],
        "v.blk.0.b1": [f32(rng.uniform(-0.05, 0.05)) for _ in range(ffn_d)],
        "v.blk.0.w2": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * ffn_d)],
        "v.blk.0.b2": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.post_ln_w": [f32(rng.uniform(0.8, 1.2)) for _ in range(hid)],
        "v.post_ln_b": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "mm.0.weight": [f32(rng.uniform(-0.2, 0.2)) for _ in range(proj_d * hid)],
        "mm.0.bias": [f32(rng.uniform(-0.05, 0.05)) for _ in range(proj_d)],
        "mm.2.weight": [f32(rng.uniform(-0.2, 0.2)) for _ in range(proj_d * proj_d)],
        "mm.2.bias": [f32(rng.uniform(-0.05, 0.05)) for _ in range(proj_d)],
    }

    mmproj_path = work / "v14_mmproj.safetensors"
    v_meta = {
        "vision.image_size": str(img_sz),
        "vision.patch_size": str(patch_sz),
        "vision.in_channels": str(in_c),
        "vision.hidden_size": str(hid),
        "vision.num_layers": str(nl),
        "vision.num_heads": str(nh),
        "vision.ffn_dim": str(ffn_d),
        "vision.proj_dim": str(proj_d),
        "vision.ln_eps": "1e-5",
    }
    v_header = {"__metadata__": v_meta}
    v_off = 0
    v_chunks = []
    for k, arr in v_tensors.items():
        raw = b"".join(struct.pack("<f", v) for v in arr)
        v_header[k] = {"dtype": "F32", "shape": [len(arr)], "data_offsets": [v_off, v_off + len(raw)]}
        v_chunks.append(raw)
        v_off += len(raw)
    vh_bytes = pyjson.dumps(v_header).encode("utf-8")
    mmproj_path.write_bytes(struct.pack("<Q", len(vh_bytes)) + vh_bytes + b"".join(v_chunks))

    def py_layernorm(vec, w, b, eps=1e-5):
        n = len(vec)
        mean = sum(float(x) for x in vec) / n
        var = sum((float(x) - mean) ** 2 for x in vec) / n
        inv = 1.0 / math.sqrt(var + eps)
        return [f32(((float(vec[i]) - mean) * inv) * float(w[i]) + float(b[i])) for i in range(n)]

    def py_linear_rows(rows_vecs, w, b, out_d, in_d):
        out = []
        for rv in rows_vecs:
            row = []
            for oi in range(out_d):
                acc = float(b[oi])
                wb = oi * in_d
                for ii in range(in_d):
                    acc += float(rv[ii]) * float(w[wb + ii])
                row.append(f32(acc))
            out.append(row)
        return out

    def py_gelu(v):
        k = 0.7978845608028654
        fv = float(v)
        return f32(0.5 * fv * (1.0 + math.tanh(k * (fv + 0.044715 * fv * fv * fv))))

    def py_encode_vision(img_chw):
        pw = v_tensors["v.patch_embd.weight"]
        pb = v_tensors["v.patch_embd.bias"]
        pos_emb = v_tensors["v.position_embd.weight"]
        hw = img_sz * img_sz
        p2 = patch_sz * patch_sz
        h = []
        for py_y in range(grid):
            for py_x in range(grid):
                tok = py_y * grid + py_x
                row = []
                for oc in range(hid):
                    acc = float(pb[oc])
                    for ic in range(in_c):
                        for dy in range(patch_sz):
                            for dx in range(patch_sz):
                                pix = img_chw[ic * hw + (py_y * patch_sz + dy) * img_sz + (py_x * patch_sz + dx)]
                                wv = pw[((oc * in_c + ic) * patch_sz + dy) * patch_sz + dx]
                                acc += float(pix) * float(wv)
                    row.append(f32(f32(acc) + pos_emb[tok * hid + oc]))
                h.append(row)
        n1 = [py_layernorm(r, v_tensors["v.blk.0.ln1_w"], v_tensors["v.blk.0.ln1_b"]) for r in h]
        qv = py_linear_rows(n1, v_tensors["v.blk.0.wq"], v_tensors["v.blk.0.bq"], hid, hid)
        kv = py_linear_rows(n1, v_tensors["v.blk.0.wk"], v_tensors["v.blk.0.bk"], hid, hid)
        vv = py_linear_rows(n1, v_tensors["v.blk.0.wv"], v_tensors["v.blk.0.bv"], hid, hid)
        attn = [[f32(0.0)] * hid for _ in range(n_patches)]
        sc = 1.0 / math.sqrt(head_dim)
        for qi in range(n_patches):
            for hd in range(nh):
                ho = hd * head_dim
                scs = [sum(float(qv[qi][ho + d]) * float(kv[ki][ho + d]) for d in range(head_dim)) * sc for ki in range(n_patches)]
                mx = max(scs)
                ex = [math.exp(s - mx) for s in scs]
                dn = sum(ex)
                for ki in range(n_patches):
                    wgt = ex[ki] / dn
                    for d in range(head_dim):
                        attn[qi][ho + d] = f32(float(attn[qi][ho + d]) + wgt * float(vv[ki][ho + d]))
        proj = py_linear_rows(attn, v_tensors["v.blk.0.wo"], v_tensors["v.blk.0.bo"], hid, hid)
        h = [[f32(h[i][j] + proj[i][j]) for j in range(hid)] for i in range(n_patches)]
        n2 = [py_layernorm(r, v_tensors["v.blk.0.ln2_w"], v_tensors["v.blk.0.ln2_b"]) for r in h]
        fc1 = py_linear_rows(n2, v_tensors["v.blk.0.w1"], v_tensors["v.blk.0.b1"], ffn_d, hid)
        fc1a = [[py_gelu(x) for x in r] for r in fc1]
        fc2 = py_linear_rows(fc1a, v_tensors["v.blk.0.w2"], v_tensors["v.blk.0.b2"], hid, ffn_d)
        h = [[f32(h[i][j] + fc2[i][j]) for j in range(hid)] for i in range(n_patches)]
        post = [py_layernorm(r, v_tensors["v.post_ln_w"], v_tensors["v.post_ln_b"]) for r in h]
        mm1 = py_linear_rows(post, v_tensors["mm.0.weight"], v_tensors["mm.0.bias"], proj_d, hid)
        mm1a = [[py_gelu(x) for x in r] for r in mm1]
        return py_linear_rows(mm1a, v_tensors["mm.2.weight"], v_tensors["mm.2.bias"], proj_d, proj_d)

    def py_eval_vlm(img_chw, prompt_toks, max_gen):
        dim = cfg["dim"]
        vis_vecs = py_encode_vision(img_chw)
        emb_w = tensors["embed_tokens.weight"][1]
        all_vecs = vis_vecs + [emb_w[tok * dim:(tok + 1) * dim] for tok in prompt_toks]
        n_layers = cfg["n_layers"]
        n_heads = cfg["n_heads"]
        n_kv_heads = cfg["n_kv_heads"]
        hdim = dim // n_heads
        kv_dim = n_kv_heads * hdim
        kv_mul = n_heads // n_kv_heads
        hidden_dim = cfg["hidden_dim"]
        vocab = cfg["vocab_size"]
        k_cache = [[] for _ in range(n_layers)]
        v_cache = [[] for _ in range(n_layers)]

        def mv(mat, vec, rows, cols):
            return [f32(sum(float(mat[r * cols + c]) * float(vec[c]) for c in range(cols))) for r in range(rows)]

        def fwd(vec, pos):
            x = list(vec)
            zeros = [f32(0.0)] * dim
            inv_sqrt_d = 1.0 / math.sqrt(hdim)
            for l in range(n_layers):
                p = f"layers.{l}."
                xb = py_rmsnorm(x, zeros, tensors[p + "input_layernorm.weight"][1])
                q = py_rope(mv(tensors[p + "self_attn.q_proj.weight"][1], xb, dim, dim), n_heads, hdim, pos, cfg["rope_theta"])
                k = py_rope(mv(tensors[p + "self_attn.k_proj.weight"][1], xb, kv_dim, dim), n_kv_heads, hdim, pos, cfg["rope_theta"])
                v = mv(tensors[p + "self_attn.v_proj.weight"][1], xb, kv_dim, dim)
                k_cache[l].append(k)
                v_cache[l].append(v)
                att = [f32(0.0)] * dim
                for h in range(n_heads):
                    qh = q[h * hdim:(h + 1) * hdim]
                    kvh = (h // kv_mul) * hdim
                    scs = [sum(float(qh[d]) * float(k_cache[l][kp][kvh + d]) for d in range(hdim)) * inv_sqrt_d for kp in range(pos + 1)]
                    mx = max(scs)
                    ex = [math.exp(s - mx) for s in scs]
                    dn = sum(ex)
                    for kp in range(pos + 1):
                        wgt = ex[kp] / dn
                        for d in range(hdim):
                            att[h * hdim + d] = f32(float(att[h * hdim + d]) + wgt * float(v_cache[l][kp][kvh + d]))
                xb2 = mv(tensors[p + "self_attn.o_proj.weight"][1], att, dim, dim)
                x = [f32(x[i] + xb2[i]) for i in range(dim)]
                xb = py_rmsnorm(x, zeros, tensors[p + "post_attention_layernorm.weight"][1])
                g = mv(tensors[p + "mlp.gate_proj.weight"][1], xb, hidden_dim, dim)
                u = mv(tensors[p + "mlp.up_proj.weight"][1], xb, hidden_dim, dim)
                act = [f32((float(g[i]) / (1.0 + math.exp(-float(g[i])))) * float(u[i])) for i in range(hidden_dim)]
                down = mv(tensors[p + "mlp.down_proj.weight"][1], act, dim, hidden_dim)
                x = [f32(x[i] + down[i]) for i in range(dim)]
            out_n = py_rmsnorm(x, zeros, tensors["norm.weight"][1])
            logits = mv(tensors["lm_head.weight"][1], out_n, vocab, dim)
            best = max(range(vocab), key=lambda i: float(logits[i]))
            return best, float(logits[best])

        pos = 0
        nxt, lg = 0, 0.0
        for vec in all_vecs:
            nxt, lg = fwd(vec, pos)
            pos += 1
        out_toks, out_lgs = [nxt], [lg]
        for _ in range(1, max_gen):
            emb = emb_w[nxt * dim:(nxt + 1) * dim]
            nxt, lg = fwd(emb, pos)
            pos += 1
            out_toks.append(nxt)
            out_lgs.append(lg)
        return out_toks, out_lgs

    img_rng = random.Random(7714)
    img_vals = [f32(img_rng.uniform(0.0, 1.0)) for _ in range(in_c * img_sz * img_sz)]
    rgb_spec = "rgb:" + str(img_sz) + "," + str(img_sz) + "," + ",".join(f"{float(v):.6f}" for v in img_vals)
    py_mm_toks, py_mm_lgs = py_eval_vlm(img_vals, REQUESTS[0][0], REQUESTS[0][1])

    insp_vlm = run([exe, "inspect", str(st_path), "--mmproj", str(mmproj_path)])
    assert "vision_encoder:true" in insp_vlm and "vision_tokens:4" in insp_vlm, insp_vlm

    for name, _fast, mode_exe, _kb in exes:
        v_mm = run([mode_exe, "verify", str(st_path), "--mmproj", str(mmproj_path), "--image", rgb_spec])
        assert "vision_tokens:4" in v_mm and "mm_kv_free_after:16/16" in v_mm, f"{name}: {v_mm}"
        mm_line = [ln for ln in v_mm.splitlines() if ln.startswith("mm_seq:")][0]
        _, _, pairs_s = mm_line.split(":", 2)
        pairs = [(int(tok), int(b)) for tok, b in (p.split("@") for p in pairs_s.split(","))]
        xu_toks = [t for t, _ in pairs]
        xu_bits = [b for _, b in pairs]
        assert xu_toks == py_mm_toks, f"{name} mm toks {xu_toks} != {py_mm_toks}"
        for b, p in zip(xu_bits, py_mm_lgs):
            assert abs(bits_to_f32(b) - p) < 1e-4, f"{name} mm logit diff {bits_to_f32(b)} vs {p}"

    ppm_a = work / "img_a.ppm"
    ppm_b = work / "img_b.ppm"
    raw_a = b"P6\n8 8\n255\n" + bytes([250, 10, 10] * (8 * 8))
    raw_b = b"P6\n8 8\n255\n" + bytes([10, 20, 250] * (8 * 8))
    ppm_a.write_bytes(raw_a)
    ppm_b.write_bytes(raw_b)
    ga = run([exe, "generate", str(st_path), "ids:1,7", "3", "0", "40", "--mmproj", str(mmproj_path), "--image", str(ppm_a)])
    gb = run([exe, "generate", str(st_path), "ids:1,7", "3", "0", "40", "--mmproj", str(mmproj_path), "--image", str(ppm_b)])
    assert "vision_tokens:4" in ga and "generated_ids:" in ga and "kv_free_after:4/4" in ga, ga
    assert "vision_tokens:4" in gb and "generated_ids:" in gb and "kv_free_after:4/4" in gb, gb

    b64_a = "data:image/x-portable-pixmap;base64," + base64.b64encode(raw_a).decode("ascii")
    b64_b = "data:image/x-portable-pixmap;base64," + base64.b64encode(raw_b).decode("ascii")
    srv = subprocess.Popen(
        [str(exe), "serve", str(gguf_path), "127.0.0.1:0", "--mmproj", str(mmproj_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = None
        for _ in range(100):
            line = srv.stdout.readline()
            if line.startswith("serving:"):
                base_url = line.strip()[len("serving:"):]
                break
        assert base_url, "VLM server did not start"
        req_a = {
            "model": "vlm-test",
            "max_tokens": 4,
            "temperature": 0,
            "logprobs": True,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "describe"}, {"type": "image_url", "image_url": {"url": b64_a}}]}],
        }
        req_b = {
            "model": "vlm-test",
            "max_tokens": 4,
            "temperature": 0,
            "logprobs": True,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "describe"}, {"type": "image_url", "image_url": {"url": b64_b}}]}],
        }
        st_a, body_a = vlm_post_json(base_url + "/v1/chat/completions", req_a)
        st_b, body_b = vlm_post_json(base_url + "/v1/chat/completions", req_b)
        assert st_a == 200 and st_b == 200, (st_a, body_a, st_b, body_b)
        assert body_a["usage"]["prompt_tokens"] >= 5 and body_b["usage"]["prompt_tokens"] >= 5, (body_a, body_b)
        assert body_a["choices"][0]["logprobs"] != body_b["choices"][0]["logprobs"] or body_a["choices"][0]["message"]["content"] != body_b["choices"][0]["message"]["content"]
    finally:
        srv.terminate()
        srv.wait(timeout=5)

    # 2. Offline GGUF Q4_K quantizer (quantize --type q4_k -> verify --q8k-act)
    q4k_cfg = {
        "dim": 256,
        "hidden_dim": 256,
        "n_layers": 1,
        "n_heads": 4,
        "n_kv_heads": 2,
        "vocab_size": 64,
        "max_seq_len": 32,
        "rope_theta": 10000,
    }
    q4k_tensors = generate_weight_dict(q4k_cfg)
    q4k_sf = work / "v14_q4k_base.safetensors"
    write_safetensors(q4k_sf, q4k_cfg, q4k_tensors)
    q4k_gguf = work / "v14_quant_q4_k.gguf"
    qk_out = run([exe, "quantize", str(q4k_sf), str(q4k_gguf), "--type", "q4_k"])
    assert "quant_type:q4_k" in qk_out and q4k_gguf.is_file(), qk_out

    v_f32 = run([exe, "verify", str(q4k_sf)])
    v_q4k = run([exe, "verify", str(q4k_gguf), "--q8k-act"])
    assert "format:q4_k" in v_q4k and "kv_free_after:8/8" in v_q4k, v_q4k
    s_f32, _, _ = parse_verify(v_f32)
    s_q4k, c_q4k, _ = parse_verify(v_q4k)
    assert s_q4k == c_q4k and len(s_q4k) == len(s_f32)
    all_diffs = [
        abs(bits_to_f32(b1) - bits_to_f32(b2))
        for r_idx in s_f32
        for (_, b1), (_, b2) in zip(s_f32[r_idx], s_q4k[r_idx])
    ]
    mean_diff = sum(all_diffs) / len(all_diffs)
    assert mean_diff < 0.5, f"q4_k quantized logit mean_diff too high: {mean_diff}"

    print("VLM (--mmproj + PPM/BMP/rgb:/image_url) and offline Q4_K GGUF quantizer (quantize --type q4_k) verified")


def check_v15_engine_hardening(exes, work: Path, cfg: dict, tensors: dict, compiler: Path, build_env: dict):
    import http.server
    import json as pyjson
    import subprocess
    import threading
    import urllib.request
    import zlib

    exe = exes[1][2] if len(exes) > 1 else exes[0][2]

    def make_png_rgb(w: int, h: int, rgb: tuple[int, int, int]) -> bytes:
        def png_chunk(ctype: bytes, payload: bytes) -> bytes:
            body = ctype + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        r, g, b = rgb
        row = b"\x00" + bytes([r, g, b] * w)
        raw = row * h
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", ihdr)
            + png_chunk(b"IDAT", zlib.compress(raw))
            + png_chunk(b"IEND", b"")
        )

    def post_json(url: str, payload: dict):
        req = urllib.request.Request(
            url,
            data=pyjson.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, pyjson.loads(resp.read().decode("utf-8"))

    # 1. Hardened VLM: PNG/JPEG + bilinear resize + image_mean/std + HTTP URL + inline <image> splicing
    img_sz = 8
    patch_sz = 4
    in_c = 3
    hid = 16
    nl = 1
    nh = 2
    head_dim = hid // nh
    ffn_d = 32
    proj_d = cfg["dim"]
    grid = img_sz // patch_sz
    n_patches = grid * grid
    rng = random.Random(20261128)
    mean_vals = [0.5, 0.25, 0.1]
    std_vals = [0.5, 0.5, 0.5]

    v_tensors = {
        "v.patch_embd.weight": [f32(rng.uniform(-0.3, 0.3)) for _ in range(hid * in_c * patch_sz * patch_sz)],
        "v.patch_embd.bias": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.position_embd.weight": [f32(rng.uniform(-0.1, 0.1)) for _ in range(n_patches * hid)],
        "v.blk.0.ln1_w": [f32(rng.uniform(0.8, 1.2)) for _ in range(hid)],
        "v.blk.0.ln1_b": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.wq": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * hid)],
        "v.blk.0.bq": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.wk": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * hid)],
        "v.blk.0.bk": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.wv": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * hid)],
        "v.blk.0.bv": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.wo": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * hid)],
        "v.blk.0.bo": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.ln2_w": [f32(rng.uniform(0.8, 1.2)) for _ in range(hid)],
        "v.blk.0.ln2_b": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.blk.0.w1": [f32(rng.uniform(-0.2, 0.2)) for _ in range(ffn_d * hid)],
        "v.blk.0.b1": [f32(rng.uniform(-0.05, 0.05)) for _ in range(ffn_d)],
        "v.blk.0.w2": [f32(rng.uniform(-0.2, 0.2)) for _ in range(hid * ffn_d)],
        "v.blk.0.b2": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "v.post_ln_w": [f32(rng.uniform(0.8, 1.2)) for _ in range(hid)],
        "v.post_ln_b": [f32(rng.uniform(-0.05, 0.05)) for _ in range(hid)],
        "mm.0.weight": [f32(rng.uniform(-0.2, 0.2)) for _ in range(proj_d * hid)],
        "mm.0.bias": [f32(rng.uniform(-0.05, 0.05)) for _ in range(proj_d)],
        "mm.2.weight": [f32(rng.uniform(-0.2, 0.2)) for _ in range(proj_d * proj_d)],
        "mm.2.bias": [f32(rng.uniform(-0.05, 0.05)) for _ in range(proj_d)],
    }
    mmproj_v15 = work / "v15_mmproj.safetensors"
    v_meta = {
        "vision.image_size": str(img_sz),
        "vision.patch_size": str(patch_sz),
        "vision.in_channels": str(in_c),
        "vision.hidden_size": str(hid),
        "vision.num_layers": str(nl),
        "vision.num_heads": str(nh),
        "vision.ffn_dim": str(ffn_d),
        "vision.proj_dim": str(proj_d),
        "vision.ln_eps": "1e-5",
        "vision.image_mean": ",".join(str(v) for v in mean_vals),
        "vision.image_std": ",".join(str(v) for v in std_vals),
    }
    v_hdr = {"__metadata__": v_meta}
    v_off = 0
    v_chunks = []
    for k, arr in v_tensors.items():
        raw = b"".join(struct.pack("<f", v) for v in arr)
        v_hdr[k] = {"dtype": "F32", "shape": [len(arr)], "data_offsets": [v_off, v_off + len(raw)]}
        v_chunks.append(raw)
        v_off += len(raw)
    vh_bytes = pyjson.dumps(v_hdr).encode("utf-8")
    mmproj_v15.write_bytes(struct.pack("<Q", len(vh_bytes)) + vh_bytes + b"".join(v_chunks))

    vlm_st = work / "v15_vlm.safetensors"
    write_safetensors(vlm_st, cfg, tensors)
    vlm_gguf = work / "v15_vlm.gguf"
    vlm_pieces = [f"tok_{i}" for i in range(cfg["vocab_size"])]
    write_gguf_q4_0(vlm_gguf, cfg, tensors, vocab_pieces=vlm_pieces)

    png_red = work / "v15_red.png"
    png_blue = work / "v15_blue.png"
    png_red.write_bytes(make_png_rgb(12, 12, (245, 15, 15)))
    png_blue.write_bytes(make_png_rgb(12, 12, (15, 25, 245)))

    # Generate a real baseline JPEG via stdlib #image/jpeg
    jpg_path = work / "v15_img.jpg"
    jpg_gen_src = work / "make_jpg.xu"
    jpg_gen_exe = work / "make_jpg"
    jpg_gen_src.write_text(
        "@main\n#os\n#image\n#image/color\n#image/jpeg\n"
        "fn main() int {\n"
        "    args := os.args()\n"
        "    $img := image.new_rgba(image.rect(0, 0, 10, 10))\n"
        "    for y in 0:10 {\n"
        "        for x in 0:10 {\n"
        "            img.set_rgba(x, y, color.rgba8(40 + x * 10, 180, 70 + y * 10, 255))\n"
        "        }\n"
        "    }\n"
        "    enc := jpeg.encode_rgba(&img) >>> (err) { << 1 }\n"
        "    _ := os.write(args[1] + \"\", enc) >>> (err) { << 2 }\n"
        "    << 0\n"
        "}\n"
    )
    jpg_env = dict(build_env, XU_TENSOR_FUSION="0", XU_TENSOR_FAST_MATH="0")
    jpg_env.pop("XU_DUMP_MIR", None)
    build(compiler, jpg_env, jpg_gen_src, jpg_gen_exe)
    run([jpg_gen_exe, str(jpg_path)])
    assert jpg_path.is_file() and jpg_path.read_bytes()[:2] == b"\xff\xd8"

    for img_p in (png_red, png_blue, jpg_path):
        g_img = run([exe, "generate", str(vlm_st), "tok_4", "2", "0", "40", "--mmproj", str(mmproj_v15), "--image", str(img_p)])
        assert "vision_tokens:4" in g_img and "kv_free_after:4/4" in g_img, g_img

    # Python reference for inline <image> placement + image_mean/std normalization
    def py_layernorm(vec, w, b, eps=1e-5):
        n = len(vec)
        mean = sum(float(v) for v in vec) / n
        var = sum((float(v) - mean) ** 2 for v in vec) / n
        inv = 1.0 / math.sqrt(var + eps)
        return [f32((float(vec[i]) - mean) * inv * float(w[i]) + float(b[i])) for i in range(n)]

    def py_linear_rows(rows, w, b, out_d, in_d):
        out = []
        for r in rows:
            row = []
            for oi in range(out_d):
                acc = float(b[oi])
                for ii in range(in_d):
                    acc += float(r[ii]) * float(w[oi * in_d + ii])
                row.append(f32(acc))
            out.append(row)
        return out

    def py_gelu(x):
        return f32(0.5 * float(x) * (1.0 + math.erf(float(x) / math.sqrt(2.0))))

    def py_encode_vision(img_chw):
        pw = v_tensors["v.patch_embd.weight"]
        pb = v_tensors["v.patch_embd.bias"]
        pos_emb = v_tensors["v.position_embd.weight"]
        hw = img_sz * img_sz
        h = []
        for py_y in range(grid):
            for py_x in range(grid):
                tok = py_y * grid + py_x
                row = []
                for oc in range(hid):
                    acc = float(pb[oc])
                    for ic in range(in_c):
                        for dy in range(patch_sz):
                            for dx in range(patch_sz):
                                pix = img_chw[ic * hw + (py_y * patch_sz + dy) * img_sz + (py_x * patch_sz + dx)]
                                wv = pw[((oc * in_c + ic) * patch_sz + dy) * patch_sz + dx]
                                acc += float(pix) * float(wv)
                    row.append(f32(f32(acc) + pos_emb[tok * hid + oc]))
                h.append(row)
        n1 = [py_layernorm(r, v_tensors["v.blk.0.ln1_w"], v_tensors["v.blk.0.ln1_b"]) for r in h]
        qv = py_linear_rows(n1, v_tensors["v.blk.0.wq"], v_tensors["v.blk.0.bq"], hid, hid)
        kv = py_linear_rows(n1, v_tensors["v.blk.0.wk"], v_tensors["v.blk.0.bk"], hid, hid)
        vv = py_linear_rows(n1, v_tensors["v.blk.0.wv"], v_tensors["v.blk.0.bv"], hid, hid)
        attn = [[f32(0.0)] * hid for _ in range(n_patches)]
        sc = 1.0 / math.sqrt(head_dim)
        for qi in range(n_patches):
            for hd in range(nh):
                ho = hd * head_dim
                scs = [sum(float(qv[qi][ho + d]) * float(kv[ki][ho + d]) for d in range(head_dim)) * sc for ki in range(n_patches)]
                mx = max(scs)
                ex = [math.exp(s - mx) for s in scs]
                dn = sum(ex)
                for ki in range(n_patches):
                    wgt = ex[ki] / dn
                    for d in range(head_dim):
                        attn[qi][ho + d] = f32(float(attn[qi][ho + d]) + wgt * float(vv[ki][ho + d]))
        proj = py_linear_rows(attn, v_tensors["v.blk.0.wo"], v_tensors["v.blk.0.bo"], hid, hid)
        h = [[f32(h[i][j] + proj[i][j]) for j in range(hid)] for i in range(n_patches)]
        n2 = [py_layernorm(r, v_tensors["v.blk.0.ln2_w"], v_tensors["v.blk.0.ln2_b"]) for r in h]
        fc1 = py_linear_rows(n2, v_tensors["v.blk.0.w1"], v_tensors["v.blk.0.b1"], ffn_d, hid)
        fc1a = [[py_gelu(x) for x in r] for r in fc1]
        fc2 = py_linear_rows(fc1a, v_tensors["v.blk.0.w2"], v_tensors["v.blk.0.b2"], hid, ffn_d)
        h = [[f32(h[i][j] + fc2[i][j]) for j in range(hid)] for i in range(n_patches)]
        post = [py_layernorm(r, v_tensors["v.post_ln_w"], v_tensors["v.post_ln_b"]) for r in h]
        mm1 = py_linear_rows(post, v_tensors["mm.0.weight"], v_tensors["mm.0.bias"], proj_d, hid)
        mm1a = [[py_gelu(x) for x in r] for r in mm1]
        return py_linear_rows(mm1a, v_tensors["mm.2.weight"], v_tensors["mm.2.bias"], proj_d, proj_d)

    def py_eval_vlm_segments(segments, max_gen):
        dim = cfg["dim"]
        emb_w = tensors["embed_tokens.weight"][1]
        all_vecs = []
        for kind, payload in segments:
            if kind == "img":
                all_vecs.extend(payload)
            else:
                all_vecs.extend(emb_w[tok * dim:(tok + 1) * dim] for tok in payload)
        n_layers = cfg["n_layers"]
        n_heads = cfg["n_heads"]
        n_kv_heads = cfg["n_kv_heads"]
        hdim = dim // n_heads
        kv_dim = n_kv_heads * hdim
        kv_mul = n_heads // n_kv_heads
        hidden_dim = cfg["hidden_dim"]
        vocab = cfg["vocab_size"]
        k_cache = [[] for _ in range(n_layers)]
        v_cache = [[] for _ in range(n_layers)]

        def mv(mat, vec, rows, cols):
            return [f32(sum(float(mat[r * cols + c]) * float(vec[c]) for c in range(cols))) for r in range(rows)]

        def fwd(vec, pos):
            x = list(vec)
            zeros = [f32(0.0)] * dim
            inv_sqrt_d = 1.0 / math.sqrt(hdim)
            for l in range(n_layers):
                p = f"layers.{l}."
                xb = py_rmsnorm(x, zeros, tensors[p + "input_layernorm.weight"][1])
                q = py_rope(mv(tensors[p + "self_attn.q_proj.weight"][1], xb, dim, dim), n_heads, hdim, pos, cfg["rope_theta"])
                k = py_rope(mv(tensors[p + "self_attn.k_proj.weight"][1], xb, kv_dim, dim), n_kv_heads, hdim, pos, cfg["rope_theta"])
                v = mv(tensors[p + "self_attn.v_proj.weight"][1], xb, kv_dim, dim)
                k_cache[l].append(k)
                v_cache[l].append(v)
                att = [f32(0.0)] * dim
                for h in range(n_heads):
                    qh = q[h * hdim:(h + 1) * hdim]
                    kvh = (h // kv_mul) * hdim
                    scs = [sum(float(qh[d]) * float(k_cache[l][kp][kvh + d]) for d in range(hdim)) * inv_sqrt_d for kp in range(pos + 1)]
                    mx = max(scs)
                    ex = [math.exp(s - mx) for s in scs]
                    dn = sum(ex)
                    for kp in range(pos + 1):
                        wgt = ex[kp] / dn
                        for d in range(hdim):
                            att[h * hdim + d] = f32(float(att[h * hdim + d]) + wgt * float(v_cache[l][kp][kvh + d]))
                xb2 = mv(tensors[p + "self_attn.o_proj.weight"][1], att, dim, dim)
                x = [f32(x[i] + xb2[i]) for i in range(dim)]
                xb = py_rmsnorm(x, zeros, tensors[p + "post_attention_layernorm.weight"][1])
                g = mv(tensors[p + "mlp.gate_proj.weight"][1], xb, hidden_dim, dim)
                u = mv(tensors[p + "mlp.up_proj.weight"][1], xb, hidden_dim, dim)
                act = [f32((float(g[i]) / (1.0 + math.exp(-float(g[i])))) * float(u[i])) for i in range(hidden_dim)]
                down = mv(tensors[p + "mlp.down_proj.weight"][1], act, dim, hidden_dim)
                x = [f32(x[i] + down[i]) for i in range(dim)]
            out_n = py_rmsnorm(x, zeros, tensors["norm.weight"][1])
            logits = mv(tensors["lm_head.weight"][1], out_n, vocab, dim)
            best = max(range(vocab), key=lambda i: float(logits[i]))
            return best

        pos = 0
        nxt = 0
        for vec in all_vecs:
            nxt = fwd(vec, pos)
            pos += 1
        out_toks = [nxt]
        for _ in range(1, max_gen):
            nxt = fwd(emb_w[nxt * dim:(nxt + 1) * dim], pos)
            pos += 1
            out_toks.append(nxt)
        return out_toks

    ppm_norm = work / "v15_norm.ppm"
    prng = random.Random(9015)
    raw_pix = bytes([prng.randrange(0, 256) for _ in range(3 * img_sz * img_sz)])
    ppm_norm.write_bytes(b"P6\n8 8\n255\n" + raw_pix)
    chw_norm = []
    hw8 = img_sz * img_sz
    for ch in range(3):
        for i in range(hw8):
            val = (raw_pix[i * 3 + ch] / 255.0 - mean_vals[ch]) / std_vals[ch]
            chw_norm.append(f32(val))
    vis_norm = py_encode_vision(chw_norm)

    # Note: write_gguf_q4_0 isn't needed for vlm_st; build an F32 SafeTensors with string vocab tokens?
    # generate only encodes raw vocab pieces for GGUF! So test inline <image> on a GGUF built from zero_tensors/real vocab or vlm_st? Wait: vlm_st doesn't load custom vocab pieces, vlm_gguf DOES! Wait: tensors inside vlm_gguf are q4_0 quantized, whereas if we write an F32 GGUF OR use vlm_gguf with inline vs prepended! Even simpler: write a tiny F32 GGUF? Or run Python py_eval_vlm_segments against q4_0 dequantized weights! We ALREADY have py_run_request / q4_data from write_gguf_q4_0!
    _, _ = None, None
    # Actually vlm_st uses encode_prompt? Let's check: tok_4 only works with GGUF vocab, whereas vlm_st uses default fallback! So let's test BOTH:
    # A) vlm_gguf generate with "tok_4<image>tok_7" vs "<image>tok_4tok_7" using Q4_0 dequantized tensors OR just check parity on F32 GGUF! Let's write a 20-line F32 GGUF helper for exact < 1e-4 Python parity!
    def write_f32_gguf(out_p: Path, pieces_list: list[str]):
        kv_entries = [
            ("general.architecture", 8, "llama"),
            ("llama.embedding_length", 4, cfg["dim"]),
            ("llama.feed_forward_length", 4, cfg["hidden_dim"]),
            ("llama.block_count", 4, cfg["n_layers"]),
            ("llama.attention.head_count", 4, cfg["n_heads"]),
            ("llama.attention.head_count_kv", 4, cfg["n_kv_heads"]),
            ("llama.context_length", 4, cfg["max_seq_len"]),
            ("llama.rope.freq_base", 6, float(cfg["rope_theta"])),
            ("llama.attention.layer_norm_rms_epsilon", 6, 1e-5),
            ("tokenizer.ggml.bos_token_id", 4, 1),
            ("tokenizer.ggml.eos_token_id", 4, 2),
        ]
        gname_map = {
            "embed_tokens.weight": "token_embd.weight",
            "norm.weight": "output_norm.weight",
            "lm_head.weight": "output.weight",
        }
        t_list = []
        cur_off = 0
        for sfk, (sh, vals) in tensors.items():
            gk = gname_map.get(sfk)
            if gk is None and sfk.startswith("layers."):
                parts = sfk.split(".")
                lp = f"blk.{parts[1]}."
                tail = ".".join(parts[2:])
                m_map = {
                    "input_layernorm.weight": "attn_norm.weight",
                    "post_attention_layernorm.weight": "ffn_norm.weight",
                    "self_attn.q_proj.weight": "attn_q.weight",
                    "self_attn.k_proj.weight": "attn_k.weight",
                    "self_attn.v_proj.weight": "attn_v.weight",
                    "self_attn.o_proj.weight": "attn_output.weight",
                    "mlp.gate_proj.weight": "ffn_gate.weight",
                    "mlp.up_proj.weight": "ffn_up.weight",
                    "mlp.down_proj.weight": "ffn_down.weight",
                }
                gk = lp + m_map[tail]
            cur_off += (32 - (cur_off % 32)) % 32
            raw_b = b"".join(struct.pack("<f", v) for v in vals)
            t_list.append((gk, list(reversed(sh)), 0, cur_off, raw_b))
            cur_off += len(raw_b)

        def pstr(s: str) -> bytes:
            b = s.encode("utf-8")
            return struct.pack("<Q", len(b)) + b

        buf = bytearray()
        buf.extend(b"GGUF")
        buf.extend(struct.pack("<IQQ", 3, len(t_list), len(kv_entries) + 1))
        for k, vt, val in kv_entries:
            buf.extend(pstr(k))
            buf.extend(struct.pack("<I", vt))
            if vt == 8:
                buf.extend(pstr(val))
            elif vt == 4:
                buf.extend(struct.pack("<I", val))
            elif vt == 6:
                buf.extend(struct.pack("<f", val))
        buf.extend(pstr("tokenizer.ggml.tokens"))
        buf.extend(struct.pack("<IIQ", 9, 8, len(pieces_list)))
        for pc in pieces_list:
            buf.extend(pstr(pc))
        for gk, dims, gt, toff, _ in t_list:
            buf.extend(pstr(gk))
            buf.extend(struct.pack("<I", len(dims)))
            for d in dims:
                buf.extend(struct.pack("<Q", d))
            buf.extend(struct.pack("<IQ", gt, toff))
        buf.extend(b"\x00" * ((32 - (len(buf) % 32)) % 32))
        data_start = len(buf)
        for _, _, _, toff, raw_b in t_list:
            while len(buf) - data_start < toff:
                buf.append(0)
            buf.extend(raw_b)
        out_p.write_bytes(bytes(buf))

    vlm_f32_gguf = work / "v15_vlm_f32.gguf"
    f32_pieces = [f"tok_{i}" for i in range(cfg["vocab_size"])]
    f32_pieces[0], f32_pieces[1], f32_pieces[2] = "<|endoftext|>", "<|im_start|>", "<|im_end|>"
    write_f32_gguf(vlm_f32_gguf, f32_pieces)

    g_inline = run([exe, "generate", str(vlm_f32_gguf), "tok_4<image>tok_7", "3", "0", "40", "--mmproj", str(mmproj_v15), "--image", str(ppm_norm)])
    ikv = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in g_inline.splitlines() if ":" in l}
    xu_inline_ids = [int(x) for x in ikv["generated_ids"].split(",") if x]
    py_inline_ids = py_eval_vlm_segments([("txt", [4]), ("img", vis_norm), ("txt", [7])], 3)
    assert xu_inline_ids == py_inline_ids, (xu_inline_ids, py_inline_ids, g_inline)

    class ImgHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/red.png":
                data = png_red.read_bytes()
            elif self.path == "/blue.png":
                data = png_blue.read_bytes()
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            return

    img_httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ImgHandler)
    img_port = img_httpd.server_address[1]
    threading.Thread(target=img_httpd.serve_forever, daemon=True).start()

    vlm_srv = subprocess.Popen(
        [str(exe), "serve", str(vlm_gguf), "127.0.0.1:0", "--mmproj", str(mmproj_v15)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        vlm_url = None
        for _ in range(100):
            ln = vlm_srv.stdout.readline()
            if ln.startswith("serving:"):
                vlm_url = ln.strip()[len("serving:"):]
                break
        assert vlm_url, "v15 VLM server did not start"
        st_r, body_r = post_json(vlm_url + "/v1/chat/completions", {
            "model": "v15-vlm", "max_tokens": 3, "temperature": 0, "logprobs": True,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "tok_4"},
                {"type": "image_url", "image_url": {"url": f"http://127.0.0.1:{img_port}/red.png"}},
            ]}],
        })
        st_b, body_b = post_json(vlm_url + "/v1/chat/completions", {
            "model": "v15-vlm", "max_tokens": 3, "temperature": 0, "logprobs": True,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "tok_4"},
                {"type": "image_url", "image_url": {"url": f"http://127.0.0.1:{img_port}/blue.png"}},
            ]}],
        })
        assert st_r == 200 and st_b == 200
        assert body_r["choices"][0]["logprobs"] != body_b["choices"][0]["logprobs"]

        st_m, body_m = post_json(vlm_url + "/v1/chat/completions", {
            "model": "v15-vlm", "max_tokens": 2, "temperature": 0,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"http://127.0.0.1:{img_port}/red.png"}},
                {"type": "text", "text": "tok_4"},
                {"type": "image_url", "image_url": {"url": f"http://127.0.0.1:{img_port}/blue.png"}},
            ]}],
        })
        assert st_m == 200 and body_m["usage"]["prompt_tokens"] >= 9, body_m
    finally:
        vlm_srv.terminate()
        vlm_srv.wait(timeout=5)
        img_httpd.shutdown()
        img_httpd.server_close()

    # 2. Indexed GBNF VocabIndex + JSON Schema -> GBNF (--json-schema CLI + HTTP response_format/text.format)
    s_vocab = cfg["vocab_size"]
    s_dim = cfg["dim"]
    s_tensors = {k: (list(sh), [f32(0.0)] * len(v)) for k, (sh, v) in tensors.items()}
    s_tensors["norm.weight"] = ([s_dim], [f32(1.0)] * s_dim)
    s_emb = [f32(0.0)] * (s_vocab * s_dim)
    s_head = [f32(0.0)] * (s_vocab * s_dim)
    for tid in range(s_vocab):
        s_emb[tid * s_dim] = f32(1.0)
    biases_q4 = {
        21: 49.0,  # INVALID_TEXT (distractor must be blocked by GBNF)
        2: 42.0,   # <|im_end|> (EOS blocked until object finishes)
        10: 35.0,  # {
        11: 35.0,  # }
        13: 28.0,  # ,
        12: 28.0,  # :
        14: 28.0,  # "
        15: 21.0,  # status
        18: 21.0,  # count
        16: 14.0,  # ok
        17: 7.0,   # err
        19: 14.0,  # 4
        20: 7.0,   # 2
    }
    for tid, bv in biases_q4.items():
        s_head[tid * s_dim] = f32(bv)
    s_tensors["embed_tokens.weight"] = ([s_vocab, s_dim], s_emb)
    s_tensors["lm_head.weight"] = ([s_vocab, s_dim], s_head)

    s_pieces = [f"tok_{i}" for i in range(s_vocab)]
    s_pieces[0], s_pieces[1], s_pieces[2] = "<|endoftext|>", "<|im_start|>", "<|im_end|>"
    s_pieces[3], s_pieces[4], s_pieces[5], s_pieces[6] = "user", "assistant", "system", "\n"
    s_pieces[10], s_pieces[11], s_pieces[12], s_pieces[13], s_pieces[14] = "{", "}", ":", ",", "\""
    s_pieces[15], s_pieces[16], s_pieces[17], s_pieces[18], s_pieces[19], s_pieces[20] = "status", "ok", "err", "count", "4", "2"
    s_pieces[21] = "INVALID_TEXT"

    schema_gguf = work / "v15_schema.gguf"
    write_gguf_q4_0(schema_gguf, cfg, s_tensors, vocab_pieces=s_pieces)

    target_schema = {
        "type": "object",
        "properties": {
            "status": {"enum": ["ok", "err"]},
            "count": {"type": "integer"},
        },
        "required": ["status", "count"],
    }
    schema_file = work / "v15_schema.json"
    schema_file.write_text(pyjson.dumps(target_schema))

    unconstrained = run([exe, "generate", str(schema_gguf), "ids:3", "3", "0", "40"])
    assert "INVALID_TEXT" in unconstrained, unconstrained

    constrained = run([exe, "generate", str(schema_gguf), "ids:3", "24", "0", "40", "--json-schema", str(schema_file)])
    ckv = {l.split(":", 1)[0]: l.split(":", 1)[1] for l in constrained.splitlines() if ":" in l}
    cli_obj = pyjson.loads(ckv["generated_text"])
    assert cli_obj["status"] == "ok" and isinstance(cli_obj["count"], int) and set(cli_obj.keys()) == {"status", "count"}, cli_obj

    sch_srv = subprocess.Popen(
        [str(exe), "serve", str(schema_gguf), "127.0.0.1:0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        sch_url = None
        for _ in range(100):
            ln = sch_srv.stdout.readline()
            if ln.startswith("serving:"):
                sch_url = ln.strip()[len("serving:"):]
                break
        assert sch_url
        st_c, body_c = post_json(sch_url + "/v1/chat/completions", {
            "model": "schema-test",
            "messages": [{"role": "user", "content": "user"}],
            "max_tokens": 24,
            "temperature": 0,
            "response_format": {"type": "json_schema", "json_schema": {"name": "res", "schema": target_schema}},
        })
        assert st_c == 200
        chat_obj = pyjson.loads(body_c["choices"][0]["message"]["content"])
        assert chat_obj["status"] in ("ok", "err") and isinstance(chat_obj["count"], int), (chat_obj, body_c)

        st_rs, body_rs = post_json(sch_url + "/v1/responses", {
            "model": "schema-test",
            "input": "user",
            "max_output_tokens": 24,
            "temperature": 0,
            "text": {"format": {"type": "json_schema", "schema": target_schema}},
        })
        assert st_rs == 200
        resp_obj = pyjson.loads(body_rs["output_text"])
        assert resp_obj["status"] in ("ok", "err") and isinstance(resp_obj["count"], int), (resp_obj, body_rs)
    finally:
        sch_srv.terminate()
        sch_srv.wait(timeout=5)

    # 3. Hardened Offline Quantizer: HF sharded F16/BF16 dir -> Q5_K/Q6_K/Q4_K_M/Q5_K_M + GGUF->GGUF
    qcfg = {
        "dim": 256, "hidden_dim": 256, "n_layers": 1, "n_heads": 4,
        "n_kv_heads": 2, "vocab_size": 64, "max_seq_len": 32, "rope_theta": 10000,
    }
    qtensors = generate_weight_dict(qcfg)
    qbase_st = work / "v15_q256_f32.safetensors"
    write_safetensors(qbase_st, qcfg, qtensors)
    v_f32 = run([exe, "verify", str(qbase_st)])
    s_f32, _, _ = parse_verify(v_f32)

    hf_dir = work / "v15_hf_dir"
    hf_dir.mkdir()
    (hf_dir / "config.json").write_text(pyjson.dumps({
        "model_type": "qwen2",
        "hidden_size": qcfg["dim"],
        "intermediate_size": qcfg["hidden_dim"],
        "num_hidden_layers": qcfg["n_layers"],
        "num_attention_heads": qcfg["n_heads"],
        "num_key_value_heads": qcfg["n_kv_heads"],
        "vocab_size": qcfg["vocab_size"],
        "max_position_embeddings": qcfg["max_seq_len"],
        "rope_theta": qcfg["rope_theta"],
        "rms_norm_eps": 1e-5,
        "bos_token_id": 1,
        "eos_token_id": 2,
    }))
    (hf_dir / "tokenizer_config.json").write_text(pyjson.dumps({"chat_template": "<|im_start|>"}))
    hf_vocab = {f"tok_{i}": i for i in range(qcfg["vocab_size"])}
    hf_vocab["<unk>"], hf_vocab["<s>"], hf_vocab["</s>"] = 0, 1, 2
    hf_vocab["hello_xu"], hf_vocab["world_xu"] = 10, 11
    (hf_dir / "tokenizer.json").write_text(pyjson.dumps({"model": {"vocab": hf_vocab, "merges": []}}))

    def pack_f16_vals(vals):
        return b"".join(struct.pack("<e", float(v)) for v in vals)

    def pack_bf16_vals(vals):
        out_b = bytearray()
        for v in vals:
            u32 = struct.unpack("<I", struct.pack("<f", float(v)))[0]
            out_b.extend(struct.pack("<H", (u32 >> 16) & 0xFFFF))
        return bytes(out_b)

    def write_typed_shard(path: Path, items):
        hdr = {}
        off = 0
        chunks = []
        for name, sh, vals, dtype_tag in items:
            raw_b = pack_f16_vals(vals) if dtype_tag == "F16" else pack_bf16_vals(vals)
            hdr[name] = {"dtype": dtype_tag, "shape": list(sh), "data_offsets": [off, off + len(raw_b)]}
            chunks.append(raw_b)
            off += len(raw_b)
        hb = pyjson.dumps(hdr).encode("utf-8")
        path.write_bytes(struct.pack("<Q", len(hb)) + hb + b"".join(chunks))

    sh1_items, sh2_items, wmap = [], [], {}
    for idx_t, (sfk, (sh, vals)) in enumerate(qtensors.items()):
        hf_name = sfk if sfk == "lm_head.weight" else ("model." + sfk)
        if idx_t % 2 == 0:
            sh1_items.append((hf_name, sh, vals, "F16"))
            wmap[hf_name] = "model-00001-of-00002.safetensors"
        else:
            sh2_items.append((hf_name, sh, vals, "BF16"))
            wmap[hf_name] = "model-00002-of-00002.safetensors"
    write_typed_shard(hf_dir / "model-00001-of-00002.safetensors", sh1_items)
    write_typed_shard(hf_dir / "model-00002-of-00002.safetensors", sh2_items)
    (hf_dir / "model.safetensors.index.json").write_text(pyjson.dumps({"weight_map": wmap}))

    q_modes = [
        ("q5_k", "format:q5_k", 0.35),
        ("q6_k", "format:q6_k", 0.25),
        ("q4_k_m", "format:q4_k", 0.45),
        ("q5_k_m", "format:q5_k", 0.35),
    ]
    q6k_gguf = None
    for qt, expected_fmt, max_diff in q_modes:
        out_gg = work / f"v15_hf_{qt}.gguf"
        q_out = run([exe, "quantize", str(hf_dir), str(out_gg), "--type", qt])
        assert "source_format:hf_dir" in q_out and f"quant_type:{qt}" in q_out and out_gg.is_file(), q_out
        if qt == "q6_k":
            q6k_gguf = out_gg
        vq = run([exe, "verify", str(out_gg), "--q8k-act"])
        assert expected_fmt in vq and "kv_free_after:8/8" in vq, (qt, vq)
        sq, cq, _ = parse_verify(vq)
        assert sq == cq and len(sq) == len(s_f32), qt
        diffs = [abs(bits_to_f32(b1) - bits_to_f32(b2)) for r in s_f32 for (_, b1), (_, b2) in zip(s_f32[r], sq[r])]
        mdiff = sum(diffs) / len(diffs)
        assert mdiff < max_diff, f"{qt} mean_diff {mdiff} >= {max_diff}"

    insp_hf = run([exe, "inspect", str(q6k_gguf)])
    assert "arch:qwen2" in insp_hf, insp_hf
    gen_vocab = run([exe, "generate", str(q6k_gguf), "hello_xuworld_xu", "2", "0", "40"])
    assert "prompt_ids:10,11" in gen_vocab, gen_vocab

    re_q5k = work / "v15_re_q5k.gguf"
    req_out = run([exe, "quantize", str(q6k_gguf), str(re_q5k), "--type", "q5_k"])
    assert "source_format:gguf" in req_out and "quant_type:q5_k" in req_out and re_q5k.is_file(), req_out
    insp_re = run([exe, "inspect", str(re_q5k)])
    assert "arch:qwen2" in insp_re, insp_re
    v_re = run([exe, "verify", str(re_q5k), "--q8k-act"])
    assert "format:q5_k" in v_re and "kv_free_after:8/8" in v_re, v_re
    sr, cr, _ = parse_verify(v_re)
    assert sr == cr
    rdiffs = [abs(bits_to_f32(b1) - bits_to_f32(b2)) for r in s_f32 for (_, b1), (_, b2) in zip(s_f32[r], sr[r])]
    assert (sum(rdiffs) / len(rdiffs)) < 0.40

    print("v1.15 engine hardening (PNG/JPEG+bilinear+mean/std+HTTP+<image> VLM, VocabIndex JSON-Schema GBNF, HF-dir/GGUF quantize q5_k/q6_k/q4_k_m/q5_k_m) verified")


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
        check_arch_extensions(exes, work, tensors)
        check_moe_and_yarn_gguf(exes, work, tensors)
        spm_path = check_extended_sampling_and_spm(exes[1][2], work, CFG, tensors)
        check_serve_http(exes[1][2], gguf_path)
        check_serve_chatml(exes[1][2], work, CFG, tensors)
        check_serve_enterprise_features(exes[1][2], spm_path)
        check_serve_tools_and_json_mode(exes[1][2], work, CFG, tensors)
        check_hf_sharded_dir(exes, work, CFG, tensors, py_f32_ref)
        check_mla_and_q8k_act(exes, work)
        check_serve_v17_protocols(exes[1][2], work, CFG, tensors)
        check_lora_and_speculative(exes, work, CFG, tensors)
        check_q5_k_and_responses_api(exes, work, CFG, tensors)
        check_v10_perplexity_sft_dpo_ollama_metrics(exes, work, CFG, tensors)
        check_v11_inspect_merge_grpo_distill(exes, work, CFG, tensors)
        check_v12_gbnf_ckpt_models(exes, work, CFG, tensors)
        check_v13_mamba_rlvr_quantize(exes, work, CFG, tensors)
        check_v14_vlm_and_q4k_quantize(exes, work, CFG, tensors)
        check_v15_engine_hardening(exes, work, CFG, tensors, compiler, env)
        print("LLM engine verification passed (Safetensors F32/HF-sharded, GGUF Q4_0/Q5_0/Q8_0/Q4_K_M/Q5_K/Q6_K/MLA/Mamba-SSM/Hybrid/VLM --mmproj PNG+JPEG+inline, --q8k-act, --lora, merge-lora, quantize HF+GGUF q4_0/q8_0/q4_k/q5_k/q6_k/q4_k_m/q5_k_m, train-lora SFT/DPO/GRPO/RLVR/distill, --save-ckpt/--resume-ckpt, VocabIndex --grammar/--json-schema GBNF, models pull/list/rm, perplexity, inspect, --draft, qk_norm, arch extensions, MoE + YaRN, ChatML/Llama-3, SPM, continuous batch HTTP serve + Ollama + Prometheus /metrics)")


if __name__ == "__main__":
    main()
