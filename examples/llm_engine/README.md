# Local LLM inference in Xu

This pure-Xu CPU example runs a decoder with a paged key/value cache and a coroutine scheduler for continuous batching. Build it with the compiler and standard library from the same development checkout after Xu 0.14.0.

From the Xu repository root, point `XU` at the locally built compiler.

```sh
XU_STDLIB_ROOT="$PWD/src" XU_TENSOR_FUSION=1 "$XU" build examples/llm_engine/main.xu -o llm_engine
```

On macOS ARM64, sign the executable locally with `codesign -fs - ./llm_engine` before running it.

```sh
./llm_engine generate ./model.gguf 'ids:1,7,42' 16 0 40 --ctx 128
```

Use token IDs that exist in your model's vocabulary. The example accepts GGUF v2/v3 files with compatible F32/F16 or Q4_0 layer weights and a supported F32/F16, Q4_0 or Q8_0 output projection. It also accepts the F32 Safetensors layout used by the test fixture, including the model metadata in `__metadata__`. The example's hidden model width (`dim`) is limited to 2048.

| Command | Behavior |
| --- | --- |
| `generate MODEL PROMPT [MAX_TOKENS] [TEMP_MILLI] [TOP_K]` | Accepts text or `ids:1,7,42`. Defaults to 16 tokens, a temperature of 0 (greedy), and top-k 40. Add `--ignore-eos` to continue after the end-of-sequence token. The text path uses greedy vocabulary matching and handles GPT-2-style token bytes. Use explicit IDs when exact tokenization is needed. |
| `verify MODEL` / `verify-f32act MODEL` | Compare sequential and continuously batched results on fixed requests and check that KV pages are released. The `-f32act` mode uses float activations with quantized weights. |
| `bench MODEL [STEPS] [single] [PROMPT_LEN]` / `bench-f32act` | Measure model load, prompt prefill and decode. Pass `single` to skip the continuous-batch measurement. `bench-f32act` uses float activations. |

Pass `--ctx N` with a positive `N` to cap the model context. The default cap is 512 tokens. Keep prompts and requested generation within that limit.

`XU_TENSOR_FUSION=1` enables pattern matching for eligible loops in optimized native ARM64 and x64 builds. The compiler can lower packed quantized GEMV/GEMM and operations such as RMSNorm, RoPE and paged attention to target-specific kernels where supported. The `__xu_tensor_*` symbols are compiler internals. Set `XU_TENSOR_FAST_MATH=1` at build time to permit floating-point reassociation or fused operations in eligible kernels. Compare output against a strict build if low-bit differences matter.

The test suite creates its own model fixtures and exercises the baseline, strict fusion and fast-math builds. It covers F32 Safetensors, Q4_0 GGUF with float or Q8_0 activations, tied output weights, Qwen2.5-style GGUF with a Q8_0 output projection, batched prefill and CLI generation.

```sh
python3 scripts/test_llm_engine.py --compiler "$XU"
python3 scripts/test_tensor_opt.py --compiler "$XU"
```
