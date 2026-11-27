# `llm_engine` — Pure-Xu LLM Inference & Serving Engine

A zero-dependency Transformer inference and OpenAI-compatible HTTP serving engine written in pure Xu (`xu` stdlib + `#tensor`), compiled to native machine code (`arm64` / `x86_64`).

## Modular Package Layout (`examples/llm_engine`)

- [main.xu](main.xu): Entrypoint (`@main`), model loaders (`GGUF` / SafeTensors / HF sharded dirs), paged KV cache, SIMD/fusion forward kernels, continuous batching HTTP/SSE server, LoRA/DPO/GRPO/RLVR/Distillation trainers, speculative decoding, and perplexity.
- [vision/mod.xu](vision/mod.xu) (`@vision`): `--mmproj` ViT+MLP vision encoder with `#image/png`, `#image/jpeg`, PPM (`P6`/`P3`), 24-bit BMP, base64 `data:` URI, `http(s)://` URL, and `rgb:` decoding, center-aligned bilinear resizing, configurable `vision.image_mean` / `vision.image_std` normalization, and multi-image embedding extraction.
- [gbnf/mod.xu](gbnf/mod.xu) (`@gbnf`): GBNF grammar compiler, pre-decoded `VocabIndex` first-byte bucket mask (`O(bucket)` instead of full-vocab scans), and native JSON Schema → GBNF compiler (`--json-schema` CLI & `response_format` / `text.format` `json_schema` HTTP enforcement).
- [quantize/mod.xu](quantize/mod.xu) (`@quantize`): Multi-source offline GGUF v3 quantizer accepting single-file SafeTensors (`F32`/`F16`/`BF16`), HuggingFace directories (sharded/single + `config.json` + `tokenizer.json` + `tokenizer_config.json`), or existing `GGUF` files, emitting `q4_0`, `q8_0`, `q4_k`, `q5_k`, `q6_k`, `q4_k_m`, and `q5_k_m`.
- [models/mod.xu](models/mod.xu) (`@models`): Local model cache manager (`models list`, `models pull`, `models rm`).

## Supported Formats & Architectures

- **Model containers**: HuggingFace model directories (`config.json` + single `model.safetensors` or sharded `model.safetensors.index.json` + `tokenizer.json` / `tokenizer_config.json`, supporting `F32`, `F16`, `BF16`, `F8_E4M3`), single-file Safetensors (`F32`/`F16`/`BF16`), and streaming GGUF (`F32`, `F16`, `Q4_0`, `Q5_0`, `Q8_0` including `p4k4` SIMD layer weights, `Q4_K`, `Q5_K`, `Q6_K`, tied or untied embeddings; zero-copy `#tensor` row dots for `K`-quants/`Q5_0`/`Q8_0`, plus `--q8k-act` integer K-quant activation dots).
- **Architectures**: LLaMA, Qwen2 / Qwen3 (`qkv` biases, `qk_norm`), Gemma / Gemma2 (`final_logit_softcapping`, `attn_logit_softcapping`, `use_geglu`, `post_attention_norm`/`ffn_post_norm`, `sqrt(dim)` embedding scale), Mistral (`sliding_window`), Mixture-of-Experts / MoE (`Mixtral`, `Qwen2-MoE`, `DeepSeek-V2/V3` style — 3D packed `ffn_*_exps.weight` and split `ffn_*.{e}.weight`, Softmax/Sigmoid + routing bias, `expert_weights_norm`/`expert_weights_scale`, shared experts `ffn_*_shexp.weight` + optional `ffn_gate_inp_shexp.weight`), Multi-head Latent Attention / MLA (`DeepSeek-V2/V3/R1` `kv_lora_rank`, `q_lora_rank`, `qk_nope_head_dim`, `qk_rope_head_dim`, `v_head_dim`), **Mamba SSM & Hybrid Attention+SSM GGUF** (`ssm.conv_kernel`, `ssm.inner_size`, `ssm.state_size`, `ssm.time_step_rank`, per-slot causal `conv1d_causal_step_f32` + selective scan `ssm_scan_step_f32` recurrent states inside `PagedKvCache` supporting both pure Mamba and interleaved Transformer+Mamba layers), **Multimodal VLM (`--mmproj` ViT+MLP vision projector)** with native PNG/JPEG/PPM/BMP/`data:`/`http(s)://`/`rgb:` decoding, bilinear resizing, channel mean/std normalization, and inline `<image>` interleaving (with multi-image support), partial RoPE (`.rope.dimension_count`), interleaved RoPE (`--rope-type auto|norm|neox`), and linear/YaRN NTK-by-parts RoPE scaling (`rope.scaling.type="yarn"`, `rope.scaling.original_context_length`, `beta_fast`/`beta_slow`/`attn_factor`).
- **Tokenizers**: SentencePiece BPE (`▁` word boundaries + `<0xHH>` byte-fallback pieces), GPT-2 byte-level BPE with pre-tokenization chunking + merge ranks, greedy fallback, and explicit `ids:1,2,3` inputs.
- **Chat templates & EOS**: Auto-detected from GGUF `tokenizer.chat_template` / vocabulary markers (`ChatML`, `Llama-3`, `Gemma`, `Mistral`, or raw fallback), plus multi-EOS token matching.

## Build & Run

Standard build (either entrypoint works identically):

```sh
xu build examples/llm_engine/main.xu -o llm_engine
# or:
xu build examples/llm_engine -o llm_engine
```

Tensor-optimized build (fused NEON/SIMD tensor pipelines and fast-math relaxed reductions):

```sh
xu build --tensor-fusion --tensor-fast-math -O3 examples/llm_engine/main.xu -o llm_engine
```

> **macOS Apple Silicon note**: `xu build` writes raw unsigned Mach-O binaries. On macOS ARM64, sign the executable locally before running it (`codesign -fs - ./llm_engine`), otherwise macOS will terminate it with `SIGKILL (-9)`.

## Subcommands & Flags

```sh
llm_engine <verify|verify-f32act|bench|bench-f32act|generate|perplexity|inspect|merge-lora|quantize|models|serve|train-lora|train-dpo|train-grpo|train-rlvr|train-distill> <model_dir|model.safetensors|model.gguf> [args...] \
  [--ctx N] [--stride N] [--kv-dtype f32|f16|q8_0] [--rope-type auto|norm|neox] [--max-slots N] [--api-key K] \
  [--lora PATH] [--lora-scale F] [--draft PATH] [--draft-k N] [--grammar PATH_OR_GBNF] [--json-schema PATH_OR_JSON] [--models-dir DIR] \
  [--mmproj PATH] [--image PATH_OR_URL_OR_DATA_URI] [--type q4_0|q8_0|q4_k|q5_k|q6_k|q4_k_m|q5_k_m] \
  [--verifier contains|exact|json|math] [--group-size K] [--gen-tokens N] [--temp N] \
  [--dataset PATH] [--grad-accum N] [--warmup-steps W] [--lr-schedule constant|cosine] [--dpo-beta F] \
  [--save-ckpt PATH] [--resume-ckpt PATH] \
  [--teacher PATH] [--distill-temp F] [--distill-alpha F] [--clip-eps F] [--kl-beta F] \
  [--lora-rank R] [--lora-alpha F] [--steps N] [--lr F] [--max-grad-norm G] \
  [--q8k-act] [--top-p N] [--min-p N] [--repeat-penalty N] [--presence-penalty N] [--frequency-penalty N] \
  [--seed N] [--ignore-eos]
```

- `verify` / `verify-f32act`: Compare sequential and continuous-batch outputs bit-for-bit across GQA/MLA/Mamba-SSM/paged-KV slots (supports `--lora` and `--mmproj --image`).
- `bench` / `bench-f32act`: Measure load time, TTFT, p50/p99 decode latency, and continuous-batch throughput.
- `perplexity <model> <prompt|ids:...|@filepath>`: Evaluate sliding-window NLL & perplexity (supports `--ctx`, `--stride`, `--kv-dtype`, `--lora`).
- `inspect <model>`: Print architecture metadata, parameter estimate, and per-token KV cache footprint across F32/F16/FP8 (plus vision encoder details with `--mmproj`).
- `merge-lora <base.safetensors> <lora_path> <out_merged.safetensors>`: Bake a PEFT SafeTensors LoRA adapter directly into F32 base weights (`--lora-scale`).
- `quantize <in.safetensors|in.gguf|hf_dir> <out.gguf> [--type q4_0|q8_0|q4_k|q5_k|q6_k|q4_k_m|q5_k_m]`: Quantize SafeTensors (`F32`/`F16`/`BF16`), HuggingFace model directories (with `config.json` & `tokenizer.json`), or existing GGUF binaries into standalone GGUF v3 binaries (including mixed-precision `q4_k_m` / `q5_k_m` with `Q6_K` sensitive projections).
- `models <list|rm|pull> ... [--models-dir DIR]`: Manage local model cache (`models list`, `models pull hf://org/repo/file.gguf name.gguf`, `models rm name.gguf`).
- `generate <model> <prompt|ids:...> [max_tokens] [temp_milli] [top_k]`: Run single-sequence generation with $O(L)$ penalties, `top_k` (unbounded), `top_p`, `min_p`, `VocabIndex`-accelerated GBNF grammar decoding (`--grammar`), JSON Schema enforcement (`--json-schema`), inline `<image>` VLM prompts (`--mmproj` + repeatable `--image`), optional `--lora <adapter>` inference, and lossless speculative decoding via `--draft <draft_model> [--draft-k N]`.
- `train-lora`, `train-dpo`, `train-grpo`, `train-rlvr`, `train-distill`: Pure-Xu LoRA post-training suite with JSONL datasets, assistant-only loss masking, gradient accumulation, warmup/cosine LR scheduling, optimizer checkpoint save/resume, and PEFT SafeTensors export.
- `serve <model> [host:port]`: Start an OpenAI, Anthropic & Ollama-compatible HTTP server with paged KV prefix caching, batched multi-slot ARM64 decode, `VocabIndex`-accelerated `grammar` and `response_format` / `text.format` `json_schema` decoding, multimodal `image_url` (`data:`, `http(s)://`, local path, `rgb:`) with inline `<image>` interleaving, SSE client-disconnect cancellation, CORS, `--api-key`, `/health`, and Prometheus `/metrics`.

## Known Limitations & Trade-offs

- **CPU-only, single-threaded tensor execution**: `llm_engine` does **not** currently dispatch to `packages/metal` GPU or CUDA/ROCm/Vulkan backends. Concurrent `xu` fibers handle HTTP/continuous-batch slots, while per-step GEMV/GEMM math runs single-threaded on CPU. Use it for small/quantized models, single-binary tools, or CI parity checks — **not** as a drop-in replacement for GPU-accelerated `vLLM` or `llama.cpp` on 7B–70B multi-user production serving.
- **Quantization speed asymmetry & missing GGUF types**: ARM64 SDOT / `p4k4` SIMD fast paths accelerate `F32`, `Q4_0`, and `Q8_0`. By contrast, `Q4_K`/`Q5_K`/`Q6_K`/`Q5_0` execute pure-Xu `#tensor` scalar/block paths (orders of magnitude slower per token than `Q4_0xQ8_0` SDOT — e.g. ~54–58 tok/s vs ~19k tok/s on test micro-models). `Q2_K`, `Q3_K`, `Q4_1`, `Q5_1`, and imatrix `IQ1`–`IQ4` GGUF types are not supported.
- **VLM `--mmproj` container format**: `vision/mod.xu` loads Xu's `F32` SafeTensors ViT+MLP projector layout (`vision.*`, `v.patch_embd.weight`, `v.blk.*`, `mm.0`/`mm.2`), not upstream `llama.cpp` `mmproj-*.gguf` binaries directly. Image decoding covers PNG, JPEG, PPM, and uncompressed 24-bit BMP (no WebP, AVIF, or HEIC).
- **GBNF & `--json-schema` boundaries**: Grammar normalization caps active branches at 64 (`wi < 512`, rule recursion depth `< 48`). `json_schema_to_gbnf` supports `type`, `properties`, `required`, `items`, `enum`, `const`, `anyOf`, and `oneOf` with fixed property emission order (required keys then optional keys); `$ref`/`$defs`, `allOf`, regex `pattern`, numeric/length bounds (`minimum`, `maxLength`, `minItems`), and arbitrary key permutations with `additionalProperties: false` are not implemented. First-byte `VocabIndex` narrows step masking but is slower than precompiled DFA/bitmask engines on 128k+ vocabularies.
- **CPU `f32` LoRA training only**: `train-lora`, `train-dpo`, `train-grpo`, `train-rlvr`, and `train-distill` run CPU `f32` LoRA updates only (no GPU or distributed training, no full-parameter pretraining; `merge-lora` exports `F32` SafeTensors).

## Verification

```sh
python3 scripts/test_llm_engine.py --compiler bin/xu
```
