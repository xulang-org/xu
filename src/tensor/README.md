# Tensor storage

Import `#tensor` for fixed-width floating-point storage, dense tensor views,
and GGML quantization blocks.

| Storage | Size | Xu type |
| --- | --- | --- |
| IEEE binary16 | 2 bytes per element | `F16` |
| bfloat16 | 2 bytes per element | `BF16` |
| FP8 E4M3FN, E5M2 | 1 byte per element | `Fp8E4M3Fn`, `Fp8E5M2` |
| FP8 E4M3FNUZ, E5M2FNUZ | 1 byte per element | `Fp8E4M3Fnuz`, `Fp8E5M2Fnuz` |
| GGML Q4_0 | 18 bytes per 32 values | `Q4Block` |
| GGML Q5_0 | 22 bytes per 32 values | `Q5Block` |
| GGML Q8_0 | 34 bytes per 32 values | `Q8Block` |
| GGML Q4_K | 144 bytes per 256 values | `Q4KBlock` |
| GGML Q5_K | 176 bytes per 256 values | `Q5KBlock` |
| GGML Q6_K | 210 bytes per 256 values | `Q6KBlock` |

Use `tensor.f16(value)`, `tensor.bf16(value)`, or a `tensor.fp8_*(value)`
constructor to round an F32 value to storage. Each scalar exposes its raw
`bits` and converts back with `to_f32()`. Conversions round to nearest with
ties to even. FP8 saturates finite overflow. E5M2 preserves infinities
and the finite-only FP8 formats map them to the largest value of the same
sign. FNUZ formats merge positive and negative zero.

`contiguous_view` and `strided_view` validate a layout over caller-owned
little-endian bytes. Pass the same backing bytes to read or decode methods.
Offsets are in bytes and strides are in elements. Strides are nonnegative
and zero supports broadcasting. `transpose`, `permute`, `reshape`, and positive-step `slice`
change the layout without copying the backing bytes. A rank-zero shape
describes one scalar, and any zero dimension makes the view empty.
`read_f32` takes a coordinate and `read_f32_linear` takes a logical
row-major index, including for noncontiguous views. `read_f32_bytes` and
`write_f32_bytes` support zero-copy reads and writes over caller-owned `[]u8` buffers.

Use `read_q4_0`, `read_q5_0`, `read_q8_0`, `read_q4_k`, `read_q5_k`, or `read_q6_k` to read a block at a
byte offset. `at` decodes an indexed value, `append_f32` decodes a whole block,
and `q4_k_dot_f32`, `dot_q5_k_bytes_f32`, `q6_k_dot_f32`, `q5_0_dot_f32`, `q8_0_dot_f32`, whole-row
`dot_{q4_k,q5_k,q6_k,q5_0,q8_0}_row_f32`, plus integer K-quant activation helpers
`quantize_q8_k_row` / `dot_{q4_k,q5_k,q6_k}_q8_k_row_f32` perform zero-copy inner products
directly over backing bytes; `quantize_q5_0_row` and `dequant_{f16,bf16}_to_f32`
handle packed Q5_0 writes and bulk 16-bit decoding.
The block types expose their scales and packed lanes for raw access.

## Numerical kernels (`ops.xu`)

`#tensor` also provides 47 composable pure-Xu numerical primitives in `ops.xu`:
`dot_f32`, `axpy_f32`, `vadd_f32`, `vsub_f32`, `vmul_f32`, `vscale_f32`,
`silu_f32`, `gelu_f32`, `rmsnorm_f32`, `add_rmsnorm_f32`, `layernorm_f32`,
`l2_normalize_f32`, `cosine_similarity_f32`, `topk_f32`, `topk_cosine_f32`,
`moe_router_f32`, `softmax_f32`, `log_softmax_f32`, `swiglu_f32`, `geglu_f32`,
`rope_f32`, `rope_interleaved_f32`, `rope_yarn_f32`, `matvec_f32`, `matmul_f32`,
`argmax_f32`, `quantize_q8_0`, `quantize_q4_0_row`, `cross_entropy_grad_f32`,
`adamw_step_f32`, `lora_add_f32`, `lora_backward_f32`, `rmsnorm_backward_f32`,
`swiglu_backward_f32`, `layernorm_backward_f32`, `softmax_backward_f32`,
`grad_clip_norm_f32`, `kl_div_grad_f32`, `dpo_loss_grad_f32`,
`grpo_advantages_f32`, `conv1d_causal_step_f32`, `ssm_scan_step_f32`,
`linear_attn_step_f32`, `ppo_clip_grad_f32`, `conv2d_patch_embed_f32`,
`mha_sdpa_f32`, and `avg_pool2d_f32`. Each
core loop uses the canonical shape recognized by `XU_TENSOR_FUSION=1` so the
compiler lowers eligible kernels directly to ARM64 NEON / x86-64 SSE2 stubs
when bounds and aliasing checks pass.

## Inference

The [LLM engine](../../examples/llm_engine/main.xu) accepts F32, F16, BF16
and all four FP8 formats in Safetensors checkpoints. Dense F16, BF16 and
E4M3FN GGUF weights also retain their on-disk widths in memory. CPU
inference decodes low-precision values to F32 for arithmetic and accumulation.

```sh
xu run examples/llm_engine/main.xu -- verify model.safetensors --kv-dtype bf16
```

The paged key/value cache defaults to `f32`. It also accepts `f16`, `bf16`,
`fp8_e4m3fn`, `fp8_e5m2`, `fp8_e4m3fnuz`, and `fp8_e5m2fnuz`. The 16-bit
and 8-bit formats use one-half and one-quarter of the F32 key/value storage,
respectively. Cache rounding can affect logits and generated tokens.
`verify` reports `kv_storage_bytes` and `compact_weight_bytes`.
