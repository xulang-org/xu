#!/usr/bin/env python3
"""Benchmark Xu (baseline / strict / fast-math) vs Apple Clang C++ (-O3 / -O3 -ffast-math)
across Small (dim=256) and Edge-LLM (Qwen2.5-0.5B geometry, dim=896) F32 & Q4_0 models."""

import argparse
import json
import math
import os
from pathlib import Path
import random
import struct
import subprocess
import tempfile

from test_llm_engine import write_gguf_q4_0, write_safetensors, generate_weight_dict, CFG as SMALL_CFG
from test_tensor_fusion import build, run


EDGE_CFG = {
    "dim": 896,
    "hidden_dim": 4864,
    "n_layers": 4,
    "n_heads": 14,
    "n_kv_heads": 2,
    "vocab_size": 2048,
    "max_seq_len": 128,
    "rope_theta": 10000,
}


CPP_SOURCE = r"""
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static constexpr int KV_BLOCK_SIZE = 16;
static constexpr int MAX_BATCH_SLOTS = 4;
static constexpr uint32_t GGML_TYPE_F32 = 0;
static constexpr uint32_t GGML_TYPE_Q4_0 = 2;

struct ModelConfig {
    int dim = 0;
    int hidden_dim = 0;
    int n_layers = 0;
    int n_heads = 0;
    int n_kv_heads = 0;
    int head_dim = 0;
    int kv_dim = 0;
    int vocab_size = 0;
    int max_seq_len = 0;
    double rope_theta = 10000.0;
    double rms_eps = 1e-5;
};

struct Model {
    ModelConfig cfg;
    bool is_q4 = false;
    bool lm_head_q4 = false;
    std::vector<float> weights;
    std::vector<uint8_t> q4_qs;
    std::vector<float> q4_scales;
    size_t embed_off = 0;
    size_t lm_head_off = 0;
    std::vector<size_t> wq_off, wk_off, wv_off, wo_off, w1_off, w2_off, w3_off;
    std::vector<std::vector<float>> attn_norms, ffn_norms;
    std::vector<float> final_norm, zeros, rope_cos, rope_sin;
};

struct PagedKvCache {
    int max_slots;
    int num_blocks;
    int blocks_per_seq;
    int block_size;
    int n_layers;
    int layer_stride;
    int block_stride;
    int kv_dim;
    std::vector<float> k_blocks;
    std::vector<float> v_blocks;
    std::vector<int> free_stack;
    int free_top;
    std::vector<int> block_tables;

    PagedKvCache(const ModelConfig& cfg, int slots, int nblocks)
        : max_slots(slots), num_blocks(nblocks),
          blocks_per_seq((cfg.max_seq_len + KV_BLOCK_SIZE - 1) / KV_BLOCK_SIZE),
          block_size(KV_BLOCK_SIZE), n_layers(cfg.n_layers),
          layer_stride(KV_BLOCK_SIZE * cfg.kv_dim),
          block_stride(cfg.n_layers * KV_BLOCK_SIZE * cfg.kv_dim),
          kv_dim(cfg.kv_dim),
          k_blocks(size_t(nblocks) * block_stride, 0.0f),
          v_blocks(size_t(nblocks) * block_stride, 0.0f),
          free_stack(nblocks), free_top(nblocks),
          block_tables(slots * blocks_per_seq, -1) {
        for (int b = 0; b < nblocks; ++b) free_stack[b] = nblocks - 1 - b;
    }

    int ensure_block(int slot, int pos) {
        int logical = pos / block_size;
        int idx = slot * blocks_per_seq + logical;
        if (block_tables[idx] >= 0) return block_tables[idx];
        if (free_top <= 0) throw std::runtime_error("paged kv exhausted");
        int pb = free_stack[--free_top];
        block_tables[idx] = pb;
        return pb;
    }

    void free_slot(int slot) {
        int base = slot * blocks_per_seq;
        for (int lb = 0; lb < blocks_per_seq; ++lb) {
            int pb = block_tables[base + lb];
            if (pb >= 0) {
                block_tables[base + lb] = -1;
                free_stack[free_top++] = pb;
            }
        }
    }
};

static uint16_t read_u16(const uint8_t* p) {
    uint16_t v;
    std::memcpy(&v, p, 2);
    return v;
}
static uint32_t read_u32(const uint8_t* p) {
    uint32_t v;
    std::memcpy(&v, p, 4);
    return v;
}
static uint64_t read_u64(const uint8_t* p) {
    uint64_t v;
    std::memcpy(&v, p, 8);
    return v;
}
static float read_f32(const uint8_t* p) {
    float v;
    std::memcpy(&v, p, 4);
    return v;
}

static float f16_to_f32(uint16_t h) {
    uint32_t s = uint32_t(h & 0x8000u) << 16;
    uint32_t e = (h >> 10) & 0x1Fu;
    uint32_t m = h & 0x3FFu;
    uint32_t bits = 0;
    if (e == 0) {
        if (m == 0) bits = s;
        else {
            uint32_t eb = 113;
            while ((m & 0x400u) == 0) { m <<= 1; --eb; }
            m &= 0x3FFu;
            bits = s | (eb << 23) | (m << 13);
        }
    } else if (e == 31) {
        bits = s | 0x7F800000u | (m << 13);
    } else {
        bits = s | ((e + 112u) << 23) | (m << 13);
    }
    float out;
    std::memcpy(&out, &bits, 4);
    return out;
}

static void build_rope(Model& m) {
    int half = m.cfg.head_dim / 2;
    double log_theta = std::log(m.cfg.rope_theta);
    m.rope_cos.reserve(m.cfg.max_seq_len * half);
    m.rope_sin.reserve(m.cfg.max_seq_len * half);
    for (int pos = 0; pos < m.cfg.max_seq_len; ++pos) {
        for (int j = 0; j < half; ++j) {
            double freq = std::exp(-log_theta * (double(2 * j) / double(m.cfg.head_dim)));
            double ang = double(pos) * freq;
            m.rope_cos.push_back(float(std::cos(ang)));
            m.rope_sin.push_back(float(std::sin(ang)));
        }
    }
}

static int parse_meta_int(const std::string& hdr, size_t meta_pos, const std::string& key) {
    size_t k = hdr.find("\"" + key + "\"", meta_pos);
    if (k == std::string::npos) throw std::runtime_error("missing meta key: " + key);
    size_t c = hdr.find(':', k);
    size_t q1 = hdr.find('"', c + 1);
    size_t q2 = hdr.find('"', q1 + 1);
    return std::stoi(hdr.substr(q1 + 1, q2 - q1 - 1));
}

static std::pair<size_t, size_t> parse_st_offsets(const std::string& hdr, const std::string& name) {
    size_t k = hdr.find("\"" + name + "\"");
    if (k == std::string::npos) throw std::runtime_error("missing tensor: " + name);
    size_t doff = hdr.find("\"data_offsets\"", k);
    size_t lb = hdr.find('[', doff);
    size_t comma = hdr.find(',', lb);
    size_t rb = hdr.find(']', comma);
    size_t s = std::stoull(hdr.substr(lb + 1, comma - lb - 1));
    size_t e = std::stoull(hdr.substr(comma + 1, rb - comma - 1));
    return {s, e};
}

static Model load_safetensors(const std::vector<uint8_t>& data) {
    uint64_t hlen = read_u64(data.data());
    std::string hdr(reinterpret_cast<const char*>(data.data() + 8), hlen);
    size_t meta_pos = hdr.find("\"__metadata__\"");

    Model m;
    m.cfg.dim = parse_meta_int(hdr, meta_pos, "dim");
    m.cfg.hidden_dim = parse_meta_int(hdr, meta_pos, "hidden_dim");
    m.cfg.n_layers = parse_meta_int(hdr, meta_pos, "n_layers");
    m.cfg.n_heads = parse_meta_int(hdr, meta_pos, "n_heads");
    m.cfg.n_kv_heads = parse_meta_int(hdr, meta_pos, "n_kv_heads");
    m.cfg.vocab_size = parse_meta_int(hdr, meta_pos, "vocab_size");
    m.cfg.max_seq_len = parse_meta_int(hdr, meta_pos, "max_seq_len");
    m.cfg.rope_theta = double(parse_meta_int(hdr, meta_pos, "rope_theta"));
    m.cfg.head_dim = m.cfg.dim / m.cfg.n_heads;
    m.cfg.kv_dim = m.cfg.n_kv_heads * m.cfg.head_dim;

    size_t base = 8 + size_t(hlen);
    auto append_t = [&](const std::string& name, size_t exp) -> size_t {
        auto [s, e] = parse_st_offsets(hdr, name);
        size_t cnt = (e - s) / 4;
        if (cnt != exp) throw std::runtime_error("shape mismatch: " + name);
        size_t off = m.weights.size();
        m.weights.resize(off + cnt);
        std::memcpy(m.weights.data() + off, data.data() + base + s, cnt * 4);
        return off;
    };
    auto load_vec = [&](const std::string& name, size_t exp) -> std::vector<float> {
        auto [s, e] = parse_st_offsets(hdr, name);
        size_t cnt = (e - s) / 4;
        if (cnt != exp) throw std::runtime_error("shape mismatch: " + name);
        std::vector<float> out(cnt);
        std::memcpy(out.data(), data.data() + base + s, cnt * 4);
        return out;
    };

    m.embed_off = append_t("embed_tokens.weight", size_t(m.cfg.vocab_size) * m.cfg.dim);
    for (int l = 0; l < m.cfg.n_layers; ++l) {
        std::string p = "layers." + std::to_string(l) + ".";
        m.attn_norms.push_back(load_vec(p + "input_layernorm.weight", m.cfg.dim));
        m.wq_off.push_back(append_t(p + "self_attn.q_proj.weight", size_t(m.cfg.dim) * m.cfg.dim));
        m.wk_off.push_back(append_t(p + "self_attn.k_proj.weight", size_t(m.cfg.kv_dim) * m.cfg.dim));
        m.wv_off.push_back(append_t(p + "self_attn.v_proj.weight", size_t(m.cfg.kv_dim) * m.cfg.dim));
        m.wo_off.push_back(append_t(p + "self_attn.o_proj.weight", size_t(m.cfg.dim) * m.cfg.dim));
        m.ffn_norms.push_back(load_vec(p + "post_attention_layernorm.weight", m.cfg.dim));
        m.w1_off.push_back(append_t(p + "mlp.gate_proj.weight", size_t(m.cfg.hidden_dim) * m.cfg.dim));
        m.w3_off.push_back(append_t(p + "mlp.up_proj.weight", size_t(m.cfg.hidden_dim) * m.cfg.dim));
        m.w2_off.push_back(append_t(p + "mlp.down_proj.weight", size_t(m.cfg.dim) * m.cfg.hidden_dim));
    }
    m.final_norm = load_vec("norm.weight", m.cfg.dim);
    m.lm_head_off = append_t("lm_head.weight", size_t(m.cfg.vocab_size) * m.cfg.dim);
    m.zeros.assign(m.cfg.dim, 0.0f);
    build_rope(m);
    return m;
}

static Model load_gguf(const std::vector<uint8_t>& data) {
    const uint8_t* p = data.data();
    size_t pos = 24;
    uint64_t tc = read_u64(p + 8);
    uint64_t kvc = read_u64(p + 16);

    auto rstr = [&]() -> std::string {
        uint64_t l = read_u64(p + pos);
        pos += 8;
        std::string s(reinterpret_cast<const char*>(p + pos), l);
        pos += l;
        return s;
    };
    auto rint = [&](uint32_t vt) -> int64_t {
        int64_t v = 0;
        if (vt == 0) { v = p[pos]; pos += 1; }
        else if (vt == 1) { v = int8_t(p[pos]); pos += 1; }
        else if (vt == 2) { v = read_u16(p + pos); pos += 2; }
        else if (vt == 3) { v = int16_t(read_u16(p + pos)); pos += 2; }
        else if (vt == 4) { v = read_u32(p + pos); pos += 4; }
        else if (vt == 5) { v = int32_t(read_u32(p + pos)); pos += 4; }
        else if (vt == 10 || vt == 11) { v = int64_t(read_u64(p + pos)); pos += 8; }
        return v;
    };
    auto skip_val = [&](auto& self, uint32_t vt) -> void {
        if (vt == 0 || vt == 1 || vt == 7) pos += 1;
        else if (vt == 2 || vt == 3) pos += 2;
        else if (vt == 4 || vt == 5 || vt == 6) pos += 4;
        else if (vt == 10 || vt == 11 || vt == 12) pos += 8;
        else if (vt == 8) { (void)rstr(); }
        else if (vt == 9) {
            uint32_t et = read_u32(p + pos);
            uint64_t cnt = read_u64(p + pos + 4);
            pos += 12;
            for (uint64_t i = 0; i < cnt; ++i) self(self, et);
        }
    };
    auto ends_with = [](const std::string& s, const std::string& suf) {
        return s.size() >= suf.size() && s.compare(s.size() - suf.size(), suf.size(), suf) == 0;
    };

    Model m;
    size_t alignment = 32;
    for (uint64_t i = 0; i < kvc; ++i) {
        std::string key = rstr();
        uint32_t vt = read_u32(p + pos); pos += 4;
        if (ends_with(key, ".embedding_length")) m.cfg.dim = int(rint(vt));
        else if (ends_with(key, ".feed_forward_length")) m.cfg.hidden_dim = int(rint(vt));
        else if (ends_with(key, ".block_count")) m.cfg.n_layers = int(rint(vt));
        else if (ends_with(key, ".attention.head_count")) m.cfg.n_heads = int(rint(vt));
        else if (ends_with(key, ".attention.head_count_kv")) m.cfg.n_kv_heads = int(rint(vt));
        else if (ends_with(key, ".context_length")) m.cfg.max_seq_len = int(rint(vt));
        else if (ends_with(key, ".rope.freq_base") && vt == 6) { m.cfg.rope_theta = read_f32(p + pos); pos += 4; }
        else if (ends_with(key, ".attention.layer_norm_rms_epsilon") && vt == 6) { m.cfg.rms_eps = read_f32(p + pos); pos += 4; }
        else if (key == "general.alignment") alignment = size_t(rint(vt));
        else if (key == "tokenizer.ggml.tokens" && vt == 9) {
            pos += 4;
            uint64_t cnt = read_u64(p + pos); pos += 8;
            m.cfg.vocab_size = int(cnt);
            for (uint64_t t = 0; t < cnt; ++t) (void)rstr();
        } else {
            skip_val(skip_val, vt);
        }
    }

    struct TInfo { std::string name; uint32_t gtype; size_t nelems; size_t offset; };
    std::vector<TInfo> tensors(tc);
    for (uint64_t i = 0; i < tc; ++i) {
        tensors[i].name = rstr();
        uint32_t nd = read_u32(p + pos); pos += 4;
        size_t ne = 1;
        size_t last = 0;
        for (uint32_t d = 0; d < nd; ++d) {
            last = size_t(read_u64(p + pos)); pos += 8;
            ne *= last;
        }
        tensors[i].gtype = read_u32(p + pos);
        tensors[i].offset = size_t(read_u64(p + pos + 4));
        pos += 12;
        tensors[i].nelems = ne;
        if (tensors[i].name == "token_embd.weight") m.cfg.vocab_size = int(last);
    }
    size_t dbase = pos + ((alignment - (pos % alignment)) % alignment);
    m.cfg.head_dim = m.cfg.dim / m.cfg.n_heads;
    m.cfg.kv_dim = m.cfg.n_kv_heads * m.cfg.head_dim;

    auto find_t = [&](const std::string& nm) -> const TInfo* {
        for (const auto& t : tensors) if (t.name == nm) return &t;
        return nullptr;
    };
    auto load_f32_vec = [&](const TInfo* t) -> std::vector<float> {
        std::vector<float> out(t->nelems);
        std::memcpy(out.data(), p + dbase + t->offset, t->nelems * 4);
        return out;
    };
    auto append_f32 = [&](const TInfo* t) -> size_t {
        size_t off = m.weights.size();
        m.weights.resize(off + t->nelems);
        std::memcpy(m.weights.data() + off, p + dbase + t->offset, t->nelems * 4);
        return off;
    };
    auto append_q4 = [&](const TInfo* t) -> size_t {
        size_t blk_off = m.q4_scales.size();
        size_t nb = t->nelems / 32;
        m.q4_scales.reserve(blk_off + nb);
        m.q4_qs.reserve(m.q4_qs.size() + nb * 16);
        const uint8_t* bp = p + dbase + t->offset;
        for (size_t b = 0; b < nb; ++b) {
            m.q4_scales.push_back(f16_to_f32(read_u16(bp)));
            m.q4_qs.insert(m.q4_qs.end(), bp + 2, bp + 18);
            bp += 18;
        }
        return blk_off;
    };

    m.embed_off = append_f32(find_t("token_embd.weight"));
    const TInfo* q0 = find_t("blk.0.attn_q.weight");
    m.is_q4 = (q0->gtype == GGML_TYPE_Q4_0);
    for (int l = 0; l < m.cfg.n_layers; ++l) {
        std::string gp = "blk." + std::to_string(l) + ".";
        m.attn_norms.push_back(load_f32_vec(find_t(gp + "attn_norm.weight")));
        m.ffn_norms.push_back(load_f32_vec(find_t(gp + "ffn_norm.weight")));
        auto load_mat = [&](const std::string& nm) {
            const TInfo* ti = find_t(nm);
            return m.is_q4 ? append_q4(ti) : append_f32(ti);
        };
        m.wq_off.push_back(load_mat(gp + "attn_q.weight"));
        m.wk_off.push_back(load_mat(gp + "attn_k.weight"));
        m.wv_off.push_back(load_mat(gp + "attn_v.weight"));
        m.wo_off.push_back(load_mat(gp + "attn_output.weight"));
        m.w1_off.push_back(load_mat(gp + "ffn_gate.weight"));
        m.w3_off.push_back(load_mat(gp + "ffn_up.weight"));
        m.w2_off.push_back(load_mat(gp + "ffn_down.weight"));
    }
    m.final_norm = load_f32_vec(find_t("output_norm.weight"));
    const TInfo* out_w = find_t("output.weight");
    if (out_w) {
        if (out_w->gtype == GGML_TYPE_Q4_0) {
            m.lm_head_q4 = true;
            m.lm_head_off = append_q4(out_w);
        } else {
            m.lm_head_off = append_f32(out_w);
        }
    } else {
        m.lm_head_off = m.embed_off;
    }
    m.zeros.assign(m.cfg.dim, 0.0f);
    build_rope(m);
    return m;
}

static Model load_model(const std::string& path) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    if (!f) throw std::runtime_error("cannot open " + path);
    size_t sz = size_t(f.tellg());
    f.seekg(0);
    std::vector<uint8_t> buf(sz);
    f.read(reinterpret_cast<char*>(buf.data()), sz);
    if (sz >= 4 && buf[0] == 'G' && buf[1] == 'G' && buf[2] == 'U' && buf[3] == 'F')
        return load_gguf(buf);
    return load_safetensors(buf);
}

static void rmsnorm_add(int n, const float* x, const float* skip, const float* w, float* out, double eps) {
    float sum = 0.0f;
    float tmp[2048];
    for (int i = 0; i < n; ++i) tmp[i] = x[i] + skip[i];
    for (int i = 0; i < n; ++i) sum += tmp[i] * tmp[i];
    float inv = float(1.0 / std::sqrt(double(sum) / double(n) + eps));
    for (int i = 0; i < n; ++i) out[i] = (tmp[i] * inv) * w[i];
}

static void matvec(float* out, const float* x, const float* w, size_t off, int rows, int cols) {
    for (int r = 0; r < rows; ++r) {
        const float* row = w + off + size_t(r) * cols;
        float acc = 0.0f;
        for (int c = 0; c < cols; ++c) acc += row[c] * x[c];
        out[r] = acc;
    }
}

static void quantize_q8_0(const float* x, int8_t* xq, float* x_scales, int n) {
    int nb = n / 32;
    for (int b = 0; b < nb; ++b) {
        size_t base = size_t(b) * 32;
        double amax = 0.0;
        for (int i = 0; i < 32; ++i) {
            double v = double(x[base + i]);
            if (v < 0.0) v = -v;
            if (v > amax) amax = v;
        }
        float scale = float(amax / 127.0);
        x_scales[b] = scale;
        double inv = (double(scale) != 0.0) ? (1.0 / double(scale)) : 0.0;
        for (int i = 0; i < 32; ++i) {
            double vf = double(x[base + i]) * inv;
            int q = (vf >= 0.0) ? int(vf + 0.5) : -int(0.5 - vf);
            if (q > 127) q = 127;
            if (q < -127) q = -127;
            xq[base + i] = int8_t(q);
        }
    }
}

static void matvec_q4_0(float* out, const float* x, const uint8_t* qs, const float* scales, size_t blk_off, int rows, int cols) {
    int nb = cols / 32;
    for (int r = 0; r < rows; ++r) {
        size_t s_off = blk_off + size_t(r) * nb;
        size_t q_off = s_off * 16;
        float acc = 0.0f;
        for (int b = 0; b < nb; ++b) {
            float bsum = 0.0f;
            const uint8_t* qp = qs + q_off + size_t(b) * 16;
            const float* xp = x + size_t(b) * 32;
            for (int j = 0; j < 16; ++j) {
                int bv = qp[j];
                int q0 = (bv & 15) - 8;
                int q1 = (bv >> 4) - 8;
                bsum += float(q0) * xp[j] + float(q1) * xp[16 + j];
            }
            acc += bsum * scales[s_off + b];
        }
        out[r] = acc;
    }
}

static void matvec_q4_0_q8_0(float* out, const uint8_t* qs, const float* w_scales,
                             const int8_t* xq, const float* x_scales, size_t blk_off, int rows, int cols) {
    int nb = cols / 32;
    for (int r = 0; r < rows; ++r) {
        size_t s_off = blk_off + size_t(r) * nb;
        size_t q_off = s_off * 16;
        float acc = 0.0f;
        for (int b = 0; b < nb; ++b) {
            int isum = 0;
            const uint8_t* qp = qs + q_off + size_t(b) * 16;
            const int8_t* xp = xq + size_t(b) * 32;
            for (int j = 0; j < 16; ++j) {
                int bv = int(qp[j]);
                int q0 = (bv & 15) - 8;
                int q1 = (bv >> 4) - 8;
                isum += q0 * int(xp[j]) + q1 * int(xp[16 + j]);
            }
            acc += float(isum) * (w_scales[s_off + b] * x_scales[b]);
        }
        out[r] = acc;
    }
}

static int forward_token(const Model& m, PagedKvCache& kv,
                         std::vector<float>& x, std::vector<float>& xb, std::vector<float>& xb2,
                         std::vector<float>& q, std::vector<float>& k, std::vector<float>& v,
                         std::vector<float>& hb, std::vector<float>& hb2,
                         std::vector<float>& logits,
                         std::vector<int8_t>& xq, std::vector<float>& xs,
                         int slot, int token, int pos, bool use_q8_act) {
    const auto& cfg = m.cfg;
    int dim = cfg.dim;
    int hidden = cfg.hidden_dim;
    int head_dim = cfg.head_dim;
    int kv_dim = cfg.kv_dim;
    int n_heads = cfg.n_heads;
    int kv_mul = n_heads / cfg.n_kv_heads;
    int half = head_dim / 2;
    int rope_off = pos * half;
    bool use_q4 = m.is_q4;
    int pb = kv.ensure_block(slot, pos);
    int in_blk = pos % kv.block_size;
    size_t pb_base = size_t(pb) * kv.block_stride + size_t(in_blk) * kv.kv_dim;
    int bt_slot_off = slot * kv.blocks_per_seq;

    std::memcpy(x.data(), m.weights.data() + m.embed_off + size_t(token) * dim, size_t(dim) * 4);
    float inv_sqrt_d = float(1.0 / std::sqrt(double(head_dim)));

    auto proj = [&](bool q4_flag, float* out, const float* in, size_t off, int rows, int cols) {
        if (q4_flag) {
            if (use_q8_act) matvec_q4_0_q8_0(out, m.q4_qs.data(), m.q4_scales.data(), xq.data(), xs.data(), off, rows, cols);
            else matvec_q4_0(out, in, m.q4_qs.data(), m.q4_scales.data(), off, rows, cols);
        } else {
            matvec(out, in, m.weights.data(), off, rows, cols);
        }
    };
    auto apply_rope = [&](float* vec, int nh) {
        for (int h = 0; h < nh; ++h) {
            float* vh = vec + h * head_dim;
            for (int j = 0; j < half; ++j) {
                float c = m.rope_cos[rope_off + j];
                float s = m.rope_sin[rope_off + j];
                float v0 = vh[j];
                float v1 = vh[j + half];
                vh[j] = float(v0 * c - v1 * s);
                vh[j + half] = float(v0 * s + v1 * c);
            }
        }
    };

    for (int l = 0; l < cfg.n_layers; ++l) {
        rmsnorm_add(dim, x.data(), m.zeros.data(), m.attn_norms[l].data(), xb.data(), cfg.rms_eps);
        if (use_q4 && use_q8_act) quantize_q8_0(xb.data(), xq.data(), xs.data(), dim);
        proj(use_q4, q.data(), xb.data(), m.wq_off[l], dim, dim);
        proj(use_q4, k.data(), xb.data(), m.wk_off[l], kv_dim, dim);
        proj(use_q4, v.data(), xb.data(), m.wv_off[l], kv_dim, dim);
        apply_rope(q.data(), n_heads);
        apply_rope(k.data(), cfg.n_kv_heads);

        size_t kv_woff = pb_base + size_t(l) * kv.layer_stride;
        std::memcpy(kv.k_blocks.data() + kv_woff, k.data(), size_t(kv_dim) * 4);
        std::memcpy(kv.v_blocks.data() + kv_woff, v.data(), size_t(kv_dim) * 4);

        size_t layer_off = size_t(l) * kv.layer_stride;
        int t0_pb = kv.block_tables[bt_slot_off];
        for (int h = 0; h < n_heads; ++h) {
            int q_off = h * head_dim;
            int kv_head_off = (h / kv_mul) * head_dim;
            size_t k0_off = size_t(t0_pb) * kv.block_stride + layer_off + size_t(kv_head_off);
            const float* kp0 = kv.k_blocks.data() + k0_off;
            const float* vp0 = kv.v_blocks.data() + k0_off;
            float sc0 = 0.0f;
            for (int d = 0; d < head_dim; ++d) sc0 += q[q_off + d] * kp0[d];
            double m_val = double(sc0 * inv_sqrt_d);
            double l_val = 1.0;
            for (int d = 0; d < head_dim; ++d) xb[q_off + d] = vp0[d];
            for (int t = 1; t <= pos; ++t) {
                int t_pb = kv.block_tables[bt_slot_off + (t / kv.block_size)];
                int t_in = t % kv.block_size;
                size_t kv_t_off = size_t(t_pb) * kv.block_stride + layer_off + size_t(t_in) * kv.kv_dim + size_t(kv_head_off);
                const float* kp = kv.k_blocks.data() + kv_t_off;
                const float* vp = kv.v_blocks.data() + kv_t_off;
                float sc = 0.0f;
                for (int d = 0; d < head_dim; ++d) sc += q[q_off + d] * kp[d];
                double score = double(sc * inv_sqrt_d);
                if (score > m_val) {
                    float alpha = float(std::exp(m_val - score));
                    for (int d = 0; d < head_dim; ++d) xb[q_off + d] = xb[q_off + d] * alpha;
                    l_val = l_val * double(alpha) + 1.0;
                    m_val = score;
                    for (int d = 0; d < head_dim; ++d) xb[q_off + d] += vp[d];
                } else {
                    float w = float(std::exp(score - m_val));
                    l_val = l_val + double(w);
                    for (int d = 0; d < head_dim; ++d) xb[q_off + d] += w * vp[d];
                }
            }
            float inv_l = float(1.0 / l_val);
            for (int d = 0; d < head_dim; ++d) xb[q_off + d] = xb[q_off + d] * inv_l;
        }
        if (use_q4 && use_q8_act) quantize_q8_0(xb.data(), xq.data(), xs.data(), dim);
        proj(use_q4, xb2.data(), xb.data(), m.wo_off[l], dim, dim);
        for (int i = 0; i < dim; ++i) x[i] += xb2[i];
        rmsnorm_add(dim, x.data(), m.zeros.data(), m.ffn_norms[l].data(), xb.data(), cfg.rms_eps);
        if (use_q4 && use_q8_act) quantize_q8_0(xb.data(), xq.data(), xs.data(), dim);
        proj(use_q4, hb.data(), xb.data(), m.w1_off[l], hidden, dim);
        proj(use_q4, hb2.data(), xb.data(), m.w3_off[l], hidden, dim);
        for (int i = 0; i < hidden; ++i) {
            float g = hb[i];
            float silu = float(double(g) / (1.0 + std::exp(double(-g))));
            hb[i] = silu * hb2[i];
        }
        if (use_q4 && use_q8_act) quantize_q8_0(hb.data(), xq.data(), xs.data(), hidden);
        proj(use_q4, xb2.data(), hb.data(), m.w2_off[l], dim, hidden);
        if (l + 1 < cfg.n_layers) {
            for (int i = 0; i < dim; ++i) x[i] += xb2[i];
        }
    }
    rmsnorm_add(dim, x.data(), xb2.data(), m.final_norm.data(), xb.data(), cfg.rms_eps);
    if (m.lm_head_q4 && use_q8_act) quantize_q8_0(xb.data(), xq.data(), xs.data(), dim);
    proj(m.lm_head_q4, logits.data(), xb.data(), m.lm_head_off, cfg.vocab_size, dim);
    int best = 0;
    for (int i = 1; i < cfg.vocab_size; ++i) if (logits[i] > logits[best]) best = i;
    return best;
}

int main(int argc, char** argv) {
    if (argc < 3) return 1;
    Model m = load_model(argv[1]);
    int steps = std::stoi(argv[2]);
    bool use_q8_act = (argc < 4 || std::string(argv[3]) != "f32act");
    int prompt_len = (argc >= 5) ? std::stoi(argv[4]) : 1;
    int bps = (m.cfg.max_seq_len + KV_BLOCK_SIZE - 1) / KV_BLOCK_SIZE;
    PagedKvCache kv(m.cfg, MAX_BATCH_SLOTS, MAX_BATCH_SLOTS * bps);

    std::vector<float> x(m.cfg.dim), xb(m.cfg.dim), xb2(m.cfg.dim), q(m.cfg.dim);
    std::vector<float> k(m.cfg.kv_dim), v(m.cfg.kv_dim);
    std::vector<float> hb(m.cfg.hidden_dim), hb2(m.cfg.hidden_dim), logits(m.cfg.vocab_size);
    int max_act = std::max(m.cfg.dim, m.cfg.hidden_dim);
    std::vector<int8_t> xq(max_act);
    std::vector<float> xs((max_act + 31) / 32);

    std::vector<int> bench_prompt;
    if (prompt_len > 1) {
        bench_prompt.reserve(prompt_len);
        for (int pi = 0; pi < prompt_len; ++pi) {
            bench_prompt.push_back((pi * 17 + 1) % m.cfg.vocab_size);
        }
        for (int pi = 0; pi < prompt_len; ++pi) {
            forward_token(m, kv, x, xb, xb2, q, k, v, hb, hb2, logits, xq, xs, 0, bench_prompt[pi], pi, use_q8_act);
        }
        kv.free_slot(0);
    } else {
        // Warmup matching Xu run_single_request(&prompts[0], 4)
        const int warmup_prompt[3] = {1, 7, 42};
        int cur = warmup_prompt[0];
        for (int s = 0; s < 6; ++s) {
            int nxt = forward_token(m, kv, x, xb, xb2, q, k, v, hb, hb2, logits, xq, xs, 0, cur, s, use_q8_act);
            cur = (s + 1 < 3) ? warmup_prompt[s + 1] : nxt;
        }
        kv.free_slot(0);
    }

    using clk = std::chrono::steady_clock;
    auto t_start = clk::now();
    int first_tok = 0;
    if (prompt_len > 1) {
        for (int pi = 0; pi < prompt_len; ++pi) {
            first_tok = forward_token(m, kv, x, xb, xb2, q, k, v, hb, hb2, logits, xq, xs, 0, bench_prompt[pi], pi, use_q8_act);
        }
    } else {
        first_tok = forward_token(m, kv, x, xb, xb2, q, k, v, hb, hb2, logits, xq, xs, 0, 1, 0, use_q8_act);
    }
    int64_t ttft_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(clk::now() - t_start).count();

    std::vector<int64_t> decode_ns;
    decode_ns.reserve(steps);
    int tok = first_tok;
    int64_t checksum = first_tok;
    int pos = (prompt_len > 1) ? prompt_len : 1;
    auto total_start = clk::now();
    for (int step = 1; step <= steps; ++step) {
        if (pos >= m.cfg.max_seq_len) {
            kv.free_slot(0);
            pos = 0;
        }
        auto t0 = clk::now();
        tok = forward_token(m, kv, x, xb, xb2, q, k, v, hb, hb2, logits, xq, xs, 0, tok, pos, use_q8_act);
        decode_ns.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(clk::now() - t0).count());
        pos += 1;
        checksum += tok;
    }
    int64_t total_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(clk::now() - total_start).count();
    kv.free_slot(0);

    std::sort(decode_ns.begin(), decode_ns.end());
    int64_t p50 = decode_ns[decode_ns.size() / 2];
    int64_t p99 = decode_ns[(decode_ns.size() * 99) / 100];
    int pref_toks = (prompt_len > 1) ? prompt_len : 1;
    std::cout << "prefill_tokens:" << pref_toks << "\n"
              << "prefill_ns:" << ttft_ns << "\n"
              << "checksum:" << checksum << "\n"
              << "ttft_ns:" << ttft_ns << "\n"
              << "decode_p50_ns:" << p50 << "\n"
              << "decode_p99_ns:" << p99 << "\n"
              << "decode_total_ns:" << total_ns << "\n"
              << "decode_steps:" << steps << "\n";
    return 0;
}
"""


def write_fast_edge_models(st_path, gguf_path, cfg):
    """Build deterministic edge-LLM F32 Safetensors (~253 MB) and Q4_0 GGUF (~38 MB) in <0.5s using row-tile replication."""
    rng = random.Random(2026112402)
    dim = cfg["dim"]
    hidden = cfg["hidden_dim"]
    n_layers = cfg["n_layers"]
    n_heads = cfg["n_heads"]
    n_kv = cfg["n_kv_heads"]
    head_dim = dim // n_heads
    kv_dim = n_kv * head_dim
    vocab = cfg["vocab_size"]

    def make_f32_bank(cols, n_rows=32, scale=0.02):
        vals = [struct.unpack("<f", struct.pack("<f", (rng.random() * 2.0 - 1.0) * scale))[0]
                for _ in range(n_rows * cols)]
        return struct.pack(f"<{len(vals)}f", *vals)

    def write_tiled_f32(f, bank, row_bytes, rows):
        bank_rows = len(bank) // row_bytes
        full = rows // bank_rows
        rem = rows % bank_rows
        if full:
            f.write(bank * full)
        if rem:
            f.write(bank[:rem * row_bytes])

    # Prebuild F32 row banks (32 distinct rows per width -> ~1 MB total RAM, zero-copy replication)
    bank_dim = make_f32_bank(dim, 32, 0.02)
    bank_hidden = make_f32_bank(hidden, 32, 0.015)
    norm_bytes = struct.pack(f"<{dim}f", *[0.95 + 0.1 * rng.random() for _ in range(dim)])

    specs = [
        ("embed_tokens.weight", [vocab, dim], bank_dim, dim * 4, vocab),
    ]
    for l in range(n_layers):
        p = f"layers.{l}."
        specs.extend([
            (p + "input_layernorm.weight", [dim], norm_bytes, dim * 4, 1),
            (p + "self_attn.q_proj.weight", [dim, dim], bank_dim, dim * 4, dim),
            (p + "self_attn.k_proj.weight", [kv_dim, dim], bank_dim, dim * 4, kv_dim),
            (p + "self_attn.v_proj.weight", [kv_dim, dim], bank_dim, dim * 4, kv_dim),
            (p + "self_attn.o_proj.weight", [dim, dim], bank_dim, dim * 4, dim),
            (p + "post_attention_layernorm.weight", [dim], norm_bytes, dim * 4, 1),
            (p + "mlp.gate_proj.weight", [hidden, dim], bank_dim, dim * 4, hidden),
            (p + "mlp.up_proj.weight", [hidden, dim], bank_dim, dim * 4, hidden),
            (p + "mlp.down_proj.weight", [dim, hidden], bank_hidden, hidden * 4, dim),
        ])
    specs.append(("norm.weight", [dim], norm_bytes, dim * 4, 1))
    specs.append(("lm_head.weight", [vocab, dim], bank_dim, dim * 4, vocab))

    header = {"__metadata__": {k: str(v) for k, v in cfg.items()}}
    off = 0
    for nm, shape, _, rb, nr in specs:
        sz = rb * nr
        header[nm] = {"dtype": "F32", "shape": shape, "data_offsets": [off, off + sz]}
        off += sz
    hbytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    hbytes += b" " * ((8 - (len(hbytes) % 8)) % 8)
    with open(st_path, "wb") as f:
        f.write(struct.pack("<Q", len(hbytes)))
        f.write(hbytes)
        for _, _, bank, rb, nr in specs:
            write_tiled_f32(f, bank, rb, nr)

    # Prebuild Q4_0 row banks for fast GGUF v3 emission
    def make_q4_bank(cols, n_rows=32):
        assert cols % 32 == 0
        nb = cols // 32
        row_raw = bytearray()
        for r in range(n_rows):
            for b in range(nb):
                d16 = struct.pack("<e", 0.003 + 0.001 * ((r + b) % 5))
                row_raw.extend(d16)
                row_raw.extend(bytes(((r * 17 + b * 31 + j * 13 + 0x57) & 255) for j in range(16)))
        return bytes(row_raw)

    q4_bank_dim = make_q4_bank(dim, 32)
    q4_bank_hidden = make_q4_bank(hidden, 32)
    q4_rb_dim = (dim // 32) * 18
    q4_rb_hidden = (hidden // 32) * 18

    def pack_str(s):
        b = s.encode("utf-8")
        return struct.pack("<Q", len(b)) + b

    kv_entries = [
        ("general.architecture", 8, pack_str("qwen2")),
        ("general.alignment", 4, struct.pack("<I", 32)),
        ("qwen2.embedding_length", 4, struct.pack("<I", dim)),
        ("qwen2.feed_forward_length", 4, struct.pack("<I", hidden)),
        ("qwen2.block_count", 4, struct.pack("<I", n_layers)),
        ("qwen2.attention.head_count", 4, struct.pack("<I", n_heads)),
        ("qwen2.attention.head_count_kv", 4, struct.pack("<I", n_kv)),
        ("qwen2.context_length", 4, struct.pack("<I", cfg["max_seq_len"])),
        ("qwen2.rope.freq_base", 6, struct.pack("<f", float(cfg["rope_theta"]))),
        ("qwen2.attention.layer_norm_rms_epsilon", 6, struct.pack("<f", 1e-5)),
        ("tokenizer.ggml.tokens", 9,
         struct.pack("<IQ", 8, vocab) + b"".join(pack_str(f"t{i}") for i in range(vocab))),
    ]

    gguf_specs = [("token_embd.weight", [dim, vocab], 0, bank_dim, dim * 4, vocab)]
    for l in range(n_layers):
        gp = f"blk.{l}."
        gguf_specs.extend([
            (gp + "attn_norm.weight", [dim], 0, norm_bytes, dim * 4, 1),
            (gp + "attn_q.weight", [dim, dim], 2, q4_bank_dim, q4_rb_dim, dim),
            (gp + "attn_k.weight", [dim, kv_dim], 2, q4_bank_dim, q4_rb_dim, kv_dim),
            (gp + "attn_v.weight", [dim, kv_dim], 2, q4_bank_dim, q4_rb_dim, kv_dim),
            (gp + "attn_output.weight", [dim, dim], 2, q4_bank_dim, q4_rb_dim, dim),
            (gp + "ffn_norm.weight", [dim], 0, norm_bytes, dim * 4, 1),
            (gp + "ffn_gate.weight", [dim, hidden], 2, q4_bank_dim, q4_rb_dim, hidden),
            (gp + "ffn_up.weight", [dim, hidden], 2, q4_bank_dim, q4_rb_dim, hidden),
            (gp + "ffn_down.weight", [hidden, dim], 2, q4_bank_hidden, q4_rb_hidden, dim),
        ])
    gguf_specs.append(("output_norm.weight", [dim], 0, norm_bytes, dim * 4, 1))
    gguf_specs.append(("output.weight", [dim, vocab], 2, q4_bank_dim, q4_rb_dim, vocab))

    hdr_buf = bytearray()
    hdr_buf.extend(b"GGUF")
    hdr_buf.extend(struct.pack("<IQQ", 3, len(gguf_specs), len(kv_entries)))
    for k, vt, vb in kv_entries:
        hdr_buf.extend(pack_str(k))
        hdr_buf.extend(struct.pack("<I", vt))
        hdr_buf.extend(vb)
    toff = 0
    for nm, dims, gt, _, rb, nr in gguf_specs:
        hdr_buf.extend(pack_str(nm))
        hdr_buf.extend(struct.pack("<I", len(dims)))
        for dv in dims:
            hdr_buf.extend(struct.pack("<Q", dv))
        hdr_buf.extend(struct.pack("<IQ", gt, toff))
        toff += rb * nr
    hdr_buf.extend(b"\x00" * ((32 - (len(hdr_buf) % 32)) % 32))
    with open(gguf_path, "wb") as f:
        f.write(hdr_buf)
        for _, _, _, bank, rb, nr in gguf_specs:
            write_tiled_f32(f, bank, rb, nr)


def parse_kv(output):
    out = {}
    for line in output.splitlines():
        k, v = line.split(":", 1)
        out[k] = v if k == "tokens" else int(v)
    return out


def bench_case(label, model_path, steps, runners, require_exact_with_cpp=True):
    m_mib = model_path.stat().st_size / (1024.0 * 1024.0)
    print(f"\n=== {label} ({model_path.name}, {m_mib:.2f} MiB, {steps} decode steps) ===")
    strict_cs = None
    cpp_o3_cs = None
    results = {}
    for name, exe, pre_args, post_args in runners:
        out = run([str(exe), *pre_args, str(model_path), str(steps), *post_args])
        st = parse_kv(out)
        bin_kib = Path(exe).stat().st_size / 1024.0
        tok_s = st["decode_steps"] * 1e9 / st["decode_total_ns"]
        pp_tok_s = (st["prefill_tokens"] * 1e9 / st["prefill_ns"]) if st.get("prefill_tokens", 1) > 1 else 0.0
        results[name] = (bin_kib, st, tok_s, pp_tok_s)
        if name == "xu-strict":
            strict_cs = st["checksum"]
        elif name == "cpp-O3":
            cpp_o3_cs = st["checksum"]
        pp_str = f"pp={pp_tok_s:6.1f} tok/s | " if st.get("prefill_tokens", 1) > 1 else ""
        print(
            f"  {name:14} bin={bin_kib:6.1f} KiB | "
            f"TTFT={st['ttft_ns']/1e3:8.1f} us | {pp_str}"
            f"P50={st['decode_p50_ns']/1e3:8.1f} us | "
            f"P99={st['decode_p99_ns']/1e3:8.1f} us | "
            f"{tok_s:7.1f} tok/s | sum={st['checksum']}"
        )
    if require_exact_with_cpp and strict_cs is not None and cpp_o3_cs is not None:
        assert strict_cs == cpp_o3_cs, f"{label}: checksum mismatch xu-strict={strict_cs} cpp-O3={cpp_o3_cs}"
        print(f"  Parity check: xu-strict checksum == cpp-O3 ({strict_cs})")
    if "xu-fast" in results and "cpp-O3" in results:
        r_strict_o3 = results["xu-strict"][2] / results["cpp-O3"][2] if "xu-strict" in results else 0.0
        r_fast_o3 = results["xu-fast"][2] / results["cpp-O3"][2]
        r_fast_fast = results["xu-fast"][2] / results["cpp-O3-fast"][2]
        msg = (
            f"  Speedup vs C++: xu-strict / cpp-O3 = {r_strict_o3:.2f}x | "
            f"xu-fast / cpp-O3 = {r_fast_o3:.2f}x | "
            f"xu-fast / cpp-O3-fast = {r_fast_fast:.2f}x"
        )
        if results["xu-fast"][3] > 0.0:
            pp_s_o3 = results["xu-strict"][3] / results["cpp-O3"][3]
            pp_f_o3 = results["xu-fast"][3] / results["cpp-O3"][3]
            pp_f_f = results["xu-fast"][3] / results["cpp-O3-fast"][3]
            msg += (
                f" || Prefill: xu-strict/cpp-O3={pp_s_o3:.2f}x | "
                f"xu-fast/cpp-O3={pp_f_o3:.2f}x | xu-fast/cpp-O3-fast={pp_f_f:.2f}x"
            )
        print(msg)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    args = parser.parse_args()
    compiler = args.compiler.resolve()
    root = Path(__file__).resolve().parents[1]
    xu_src = root / "examples/llm_engine/main.xu"

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        env = dict(os.environ, XU_STDLIB_ROOT=str(root / "src"), XU_CACHE=str(work / "cache"),
                   XU_MIR_BORROW_GATE="1", XU_KEEP_SYMBOLS="1")

        xu_base = work / "xu-baseline"
        xu_strict = work / "xu-strict"
        xu_fast = work / "xu-fast"
        build(compiler, dict(env, XU_TENSOR_FUSION="0", XU_TENSOR_FAST_MATH="0", XU_TASK_POLL="0"), xu_src, xu_base)
        build(compiler, dict(env, XU_TENSOR_FUSION="1", XU_TENSOR_FAST_MATH="0", XU_TASK_POLL="0"), xu_src, xu_strict)
        build(compiler, dict(env, XU_TENSOR_FUSION="1", XU_TENSOR_FAST_MATH="1", XU_TASK_POLL="0"), xu_src, xu_fast)

        cpp_src = work / "llm_ref.cpp"
        cpp_src.write_text(CPP_SOURCE)
        cpp_o3 = work / "cpp-O3"
        cpp_fast = work / "cpp-O3-fast"
        run(["clang++", "-std=c++17", "-O3", str(cpp_src), "-o", str(cpp_o3)])
        run(["clang++", "-std=c++17", "-O3", "-ffast-math", str(cpp_src), "-o", str(cpp_fast)])

        small_st = work / "small_f32.safetensors"
        small_gguf = work / "small_q4_0.gguf"
        small_t = generate_weight_dict(SMALL_CFG)
        write_safetensors(small_st, SMALL_CFG, small_t)
        write_gguf_q4_0(small_gguf, SMALL_CFG, small_t)

        edge_st = work / "edge_f32.safetensors"
        edge_gguf = work / "edge_q4_0.gguf"
        write_fast_edge_models(edge_st, edge_gguf, EDGE_CFG)

        full_runners = [
            ("xu-baseline", xu_base, ["bench"], ["single"]),
            ("xu-strict", xu_strict, ["bench"], ["single"]),
            ("xu-fast", xu_fast, ["bench"], ["single"]),
            ("cpp-O3", cpp_o3, [], []),
            ("cpp-O3-fast", cpp_fast, [], []),
        ]
        full_f32act_runners = [
            ("xu-baseline", xu_base, ["bench-f32act"], ["single"]),
            ("xu-strict", xu_strict, ["bench-f32act"], ["single"]),
            ("xu-fast", xu_fast, ["bench-f32act"], ["single"]),
            ("cpp-O3", cpp_o3, [], ["f32act"]),
            ("cpp-O3-fast", cpp_fast, [], ["f32act"]),
        ]
        fast_runners = [
            ("xu-strict", xu_strict, ["bench"], ["single"]),
            ("xu-fast", xu_fast, ["bench"], ["single"]),
            ("cpp-O3", cpp_o3, [], []),
            ("cpp-O3-fast", cpp_fast, [], []),
        ]
        fast_f32act_runners = [
            ("xu-strict", xu_strict, ["bench-f32act"], ["single"]),
            ("xu-fast", xu_fast, ["bench-f32act"], ["single"]),
            ("cpp-O3", cpp_o3, [], ["f32act"]),
            ("cpp-O3-fast", cpp_fast, [], ["f32act"]),
        ]

        bench_case("Small dim=256 F32 (Safetensors)", small_st, 32, full_runners)
        bench_case("Small dim=256 Q4_0xF32 (GGUF v3)", small_gguf, 32, full_f32act_runners)
        bench_case("Small dim=256 Q4_0xQ8_0 SDOT (GGUF v3)", small_gguf, 32, full_runners)
        pp32_runners = [
            ("xu-strict", xu_strict, ["bench"], ["single", "32"]),
            ("xu-fast", xu_fast, ["bench"], ["single", "32"]),
            ("cpp-O3", cpp_o3, [], ["q8act", "32"]),
            ("cpp-O3-fast", cpp_fast, [], ["q8act", "32"]),
        ]
        bench_case("Small dim=256 Q4_0xQ8_0 SDOT pp32+tg16 (GGUF v3)", small_gguf, 16, pp32_runners)
        bench_case("Edge-LLM dim=896 F32 (Safetensors)", edge_st, 16, fast_runners)
        bench_case("Edge-LLM dim=896 Q4_0xF32 (GGUF v3)", edge_gguf, 16, fast_f32act_runners)
        bench_case("Edge-LLM dim=896 Q4_0xQ8_0 SDOT (GGUF v3)", edge_gguf, 16, full_runners)
        bench_case("Edge-LLM dim=896 Q4_0xQ8_0 SDOT pp32+tg16 (GGUF v3)", edge_gguf, 16, pp32_runners)


if __name__ == "__main__":
    main()
