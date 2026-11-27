# `llm_engine` — Pure-Xu LLM Inference & Serving Engine

A zero-dependency Transformer inference and OpenAI-compatible HTTP serving engine written in pure Xu (`xu` stdlib + `#tensor`), compiled to native machine code (`arm64` / `x86_64`).

## Supported Formats & Architectures

- **Model containers**: HuggingFace model directories (`config.json` + single `model.safetensors` or sharded `model.safetensors.index.json` + `tokenizer.json` / `tokenizer_config.json`, supporting `F32`, `F16`, `BF16`, `F8_E4M3`), single-file Safetensors (`F32`), and streaming GGUF (`F32`, `F16`, `Q4_0`, `Q5_0`, `Q8_0` including `p4k4` SIMD layer weights, `Q4_K`, `Q5_K`, `Q6_K`, tied or untied embeddings; zero-copy `#tensor` row dots for `K`-quants/`Q5_0`/`Q8_0`, plus `--q8k-act` integer K-quant activation dots).
- **Architectures**: LLaMA, Qwen2 / Qwen3 (`qkv` biases, `qk_norm`), Gemma / Gemma2 (`final_logit_softcapping`, `attn_logit_softcapping`, `use_geglu`, `post_attention_norm`/`ffn_post_norm`, `sqrt(dim)` embedding scale), Mistral (`sliding_window`), Mixture-of-Experts / MoE (`Mixtral`, `Qwen2-MoE`, `DeepSeek-V2/V3` style — 3D packed `ffn_*_exps.weight` and split `ffn_*.{e}.weight`, Softmax/Sigmoid + routing bias, `expert_weights_norm`/`expert_weights_scale`, shared experts `ffn_*_shexp.weight` + optional `ffn_gate_inp_shexp.weight`), Multi-head Latent Attention / MLA (`DeepSeek-V2/V3/R1` `kv_lora_rank`, `q_lora_rank`, `qk_nope_head_dim`, `qk_rope_head_dim`, `v_head_dim`), **Mamba SSM & Hybrid Attention+SSM GGUF** (`ssm.conv_kernel`, `ssm.inner_size`, `ssm.state_size`, `ssm.time_step_rank`, per-slot causal `conv1d_causal_step_f32` + selective scan `ssm_scan_step_f32` recurrent states inside `PagedKvCache` supporting both pure Mamba and interleaved Transformer+Mamba layers), partial RoPE (`.rope.dimension_count`), interleaved RoPE (`--rope-type auto|norm|neox`), and linear/YaRN NTK-by-parts RoPE scaling (`rope.scaling.type="yarn"`, `rope.scaling.original_context_length`, `beta_fast`/`beta_slow`/`attn_factor`).
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
llm_engine <verify|verify-f32act|bench|bench-f32act|generate|perplexity|inspect|merge-lora|quantize|models|serve|train-lora|train-dpo|train-grpo|train-rlvr|train-distill> <model_dir|model.safetensors|model.gguf> [args...] \
  [--ctx N] [--stride N] [--kv-dtype f32|f16|q8_0] [--rope-type auto|norm|neox] [--max-slots N] [--api-key K] \
  [--lora PATH] [--lora-scale F] [--draft PATH] [--draft-k N] [--grammar PATH_OR_GBNF] [--models-dir DIR] \
  [--type q4_0|q8_0] [--verifier contains|exact|json|math] [--group-size K] [--gen-tokens N] [--temp N] \
  [--dataset PATH] [--grad-accum N] [--warmup-steps W] [--lr-schedule constant|cosine] [--dpo-beta F] \
  [--save-ckpt PATH] [--resume-ckpt PATH] \
  [--teacher PATH] [--distill-temp F] [--distill-alpha F] [--clip-eps F] [--kl-beta F] \
  [--lora-rank R] [--lora-alpha F] [--steps N] [--lr F] [--max-grad-norm G] \
  [--q8k-act] [--top-p N] [--min-p N] [--repeat-penalty N] [--presence-penalty N] [--frequency-penalty N] \
  [--seed N] [--ignore-eos]
```

- `verify` / `verify-f32act`: Compare sequential and continuous-batch outputs bit-for-bit across GQA/MLA/Mamba-SSM/paged-KV slots (supports `--lora`).
- `bench` / `bench-f32act`: Measure load time, TTFT, p50/p99 decode latency, and continuous-batch throughput.
- `perplexity <model> <prompt|ids:...|@filepath>`: Evaluate sliding-window NLL & perplexity (supports `--ctx`, `--stride`, `--kv-dtype`, `--lora`).
- `inspect <model>`: Print architecture metadata, parameter estimate, and per-token KV cache footprint across F32/F16/FP8.
- `merge-lora <base.safetensors> <lora_path> <out_merged.safetensors>`: Bake a PEFT SafeTensors LoRA adapter directly into F32 base weights (`--lora-scale`).
- `quantize <in.safetensors> <out.gguf> [--type q4_0|q8_0]`: Quantize an F32 SafeTensors checkpoint (including `merge-lora` outputs) into a standalone GGUF v3 binary (`Q4_0` or `Q8_0`), closing the pure-Xu train -> merge -> quantize -> serve loop.
- `models <list|rm|pull> ... [--models-dir DIR]`: Manage local model cache (`models list`, `models pull hf://org/repo/file.gguf name.gguf`, `models rm name.gguf`).
- `generate <model> <prompt|ids:...> [max_tokens] [temp_milli] [top_k]`: Run single-sequence generation with $O(L)$ penalties, `top_k` (unbounded), `top_p`, `min_p`, generic GBNF grammar-constrained decoding via `--grammar <path|rule>`, optional `--lora <adapter>` inference, and lossless speculative decoding via `--draft <draft_model> [--draft-k N]` (batched target verification + KV rollback + greedy/rejection sampling).
- `train-lora <base_model> [prompt|ids:...] <out_adapter.safetensors>`: Pure-Xu LoRA SFT fine-tuning of `lm_head` using `#tensor` training & backprop primitives (`lora_add_f32`, `cross_entropy_grad_f32`, `lora_backward_f32`, `grad_clip_norm_f32` via `--max-grad-norm`, `adamw_step_f32`), supporting JSONL datasets (`--dataset`), assistant-only loss masking, gradient accumulation (`--grad-accum`), warmup/cosine LR scheduling (`--warmup-steps`, `--lr-schedule`), AdamW state checkpoint save/resume (`--save-ckpt`, `--resume-ckpt`), and PEFT-compatible SafeTensors adapter export.
- `train-dpo <base_model> <pairs_jsonl|prompt|chosen|rejected> <out_adapter.safetensors>`: Pure-Xu Direct Preference Optimization using `tensor.dpo_loss_grad_f32` with frozen reference log-probs and SafeTensors export (`--dpo-beta`).
- `train-grpo <base_model> <groups_jsonl> <out_adapter.safetensors>`: Pure-Xu Group Relative Policy Optimization using `tensor.grpo_advantages_f32` & `tensor.ppo_clip_grad_f32` (`--clip-eps`, `--kl-beta`).
- `train-rlvr <base_model> <tasks_jsonl> <out_adapter.safetensors>`: Online Reinforcement Learning with Verifiable Rewards (samples `group-size` completions live from the active LoRA policy, scores deterministically via `--verifier contains|exact|json|math`, and updates via `grpo_advantages_f32` + `ppo_clip_grad_f32` + AdamW).
- `train-distill <student_model> [prompt|ids:...] <out_adapter.safetensors> --teacher <teacher_model>`: Pure-Xu knowledge distillation blending hard cross-entropy (`cross_entropy_grad_f32`) with temperature-scaled soft KL (`kl_div_grad_f32`, `--distill-temp`, `--distill-alpha`).
- `serve <model> [host:port]`: Start an OpenAI, Anthropic & Ollama-compatible HTTP server with paged KV prefix caching, batched multi-slot ARM64 decode, SSE client-disconnect cancellation (`SO_NOSIGPIPE`/`SIGPIPE`), unique request `id` & Unix `created` timestamps, CORS (`OPTIONS` preflight including `x-api-key` and `anthropic-version`), and optional `Authorization: Bearer <key>` / `x-api-key` enforcement (`--api-key`).
  - `GET /health` & `GET /metrics` (Prometheus exposition counters/gauges)
  - `GET /v1/models`
  - `POST /v1/completions` (`stream`, `stream_options.include_usage`, `stop`, `max_completion_tokens`, `logprobs`, `top_logprobs`, `response_format`, `logit_bias`, `top_k`, `top_p`, `min_p`, `repeat_penalty`, `presence_penalty`, `frequency_penalty`, `seed`)
  - `POST /v1/chat/completions` (auto-formatted via detected chat template; `<think>...</think>` extracted to `reasoning_content` sync + SSE; supports `tools` -> `tool_calls` sync + SSE `delta.tool_calls`, multi-turn `assistant.tool_calls` + `role:"tool"` messages, `response_format` `"json_object"` / `"json_schema"`, `logit_bias`, `logprobs`/`top_logprobs`)
  - `POST /v1/responses` (OpenAI Responses API compatible, sync + SSE `response.output_text.delta`/`response.output_item.done`/`response.completed`, `instructions`, `previous_response_id` 64-entry stateful continuation cache, structured `input` items including `function_call` / `function_call_output`, `tools`, `max_output_tokens`, `text.format`)
  - `POST /v1/messages` (Anthropic Messages API compatible, sync + SSE `message_start`/`content_block_*`/`message_delta`/`message_stop`, `thinking`/`text`/`tool_use` blocks, `tools` with `input_schema`, multi-turn `tool_result` blocks, `stop_sequences`)
  - `POST /v1/embeddings` (`input` as string or batch string array)
  - `GET /api/tags`, `POST /api/generate`, & `POST /api/chat` (Ollama-compatible sync JSON and `application/x-ndjson` streaming)

## Verification

```sh
python3 scripts/test_llm_engine.py --compiler bin/xu
```
