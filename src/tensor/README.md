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
| GGML Q8_0 | 34 bytes per 32 values | `Q8Block` |

Use `tensor.f16(value)`, `tensor.bf16(value)`, or a `tensor.fp8_*(value)`
constructor to round an F32 value to storage. Each scalar exposes its raw
`bits` and converts back with `to_f32()`. Conversions round to nearest with
ties to even. FP8 saturates finite overflow. E5M2 preserves infinities
and the finite-only FP8 formats map them to the largest value of the same
sign. FNUZ formats merge positive and negative zero.

`contiguous_view` and `strided_view` validate a layout over caller-owned
little-endian bytes. Pass the same backing bytes to read or decode methods.
Offsets are in bytes and strides are in elements. Strides are nonnegative
and zero supports broadcasting. `transpose` and positive-step `slice`
change the layout without copying the backing bytes. A rank-zero shape
describes one scalar, and any zero dimension makes the view empty.
`read_f32` takes a coordinate and `read_f32_linear` takes a logical
row-major index, including for noncontiguous views.

Use `read_q4_0` or `read_q8_0` to read a block at a byte offset.
`at` decodes an indexed value and `append_f32` decodes a whole block.
The block types expose their scale and packed or signed lanes for raw access.

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
