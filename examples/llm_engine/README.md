# `llm_engine` — Pure-Xu LLM Inference & Serving Engine

A zero-dependency Transformer inference and OpenAI-compatible HTTP serving engine written in pure Xu (`xu` stdlib + `#tensor`), compiled to native machine code (`arm64` / `x86_64`).

## Supported Formats & Architectures

- **Model containers**: Safetensors (`F32` weights + JSON config) and streaming GGUF (`F32`, `F16`, `Q4_0`, `Q5_0`, `Q8_0`, `Q4_K`, `Q6_K`, tied or untied embeddings).
- **Architectures**: LLaMA, Qwen2 / Qwen3 (`qkv` biases, `qk_norm`), Gemma / Gemma2 (`final_logit_softcapping`), Mistral, and custom `head_dim` / `dim` / GQA models (`rope.freq_base`, `rope.scaling.factor`).
- **Tokenizers**: SentencePiece BPE (`▁` word boundaries + `<0xHH>` byte-fallback pieces), GPT-2 byte-level BPE with pre-tokenization chunking + merge ranks, greedy fallback, and explicit `ids:1,2,3` inputs.
- **Chat templates & EOS**: Auto-detected from GGUF `tokenizer.chat_template` / vocabulary markers (`ChatML`, `Llama-3`, `Gemma`, `Mistral`, or raw fallback), plus multi-EOS token matching.

## Build & Run

Standard build:

```sh
xu build examples/llm_engine/main.xu -o llm_engine
```

Tensor-optimized build (fused NEON/SIMD tensor pipelines and fast-math relaxed reductions):

```sh
xu build --tensor-fusion --tensor-fast-math -O3 examples/llm_engine/main.xu -o llm_engine
```

## Subcommands & Flags

```sh
llm_engine <verify|verify-f32act|bench|bench-f32act|generate|serve> <model.safetensors|model.gguf> [args...] \
  [--ctx N] [--kv-dtype f32|f16|q8_0] [--max-slots N] [--api-key K] \
  [--top-p N] [--min-p N] [--repeat-penalty N] [--presence-penalty N] [--frequency-penalty N] \
  [--seed N] [--ignore-eos]
```

- `verify` / `verify-f32act`: Compare sequential and continuous-batch outputs bit-for-bit across GQA/paged-KV slots.
- `bench` / `bench-f32act`: Measure load time, TTFT, p50/p99 decode latency, and continuous-batch throughput.
- `generate <model> <prompt|ids:...> [max_tokens] [temp_milli] [top_k]`: Run single-sequence generation with $O(L)$ penalties, `top_k` (unbounded), `top_p`, and `min_p`.
- `serve <model> [host:port]`: Start an OpenAI-compatible HTTP server with paged KV prefix caching, batched multi-slot ARM64 decode, SSE client-disconnect cancellation, CORS (`OPTIONS` preflight), and optional `Authorization: Bearer <key>` enforcement (`--api-key`).
  - `GET /health`
  - `GET /v1/models`
  - `POST /v1/completions` (`stream`, `stream_options.include_usage`, `stop`, `top_k`, `top_p`, `min_p`, `repeat_penalty`, `presence_penalty`, `frequency_penalty`, `seed`)
  - `POST /v1/chat/completions` (auto-formatted via detected chat template)
  - `POST /v1/embeddings` (`input` as string or batch string array)

## Verification

```sh
python3 scripts/test_llm_engine.py --compiler bin/xu
```
