# IEEE value and bit conversion

SDK **0.12.3-dev.5** adds safe value/bit helpers alongside the existing math API:

| Function | Contract |
| --- | --- |
| `float64_bits(f64) int` | Reinterpret all binary64 bits, including signed zero and every NaN payload/signaling bit. Xu int carries the signed 64-bit pattern. |
| `float64_from_bits(int) f64` | Exact inverse reinterpretation; no arithmetic, allocation or pointer escapes. |
| `float32_bits(f64) int` | Convert Xu binary64 to binary32, returning a zero-extended 32-bit pattern. Round to nearest, ties to even; gradual underflow; signed infinity on overflow. |
| `float32_from_bits(int) f64` | Interpret the low 32 bits as binary32 and expand exactly to Xu binary64. High input int bits are ignored. |

Binary32 decoding preserves the zero sign, infinities and the entire binary32
NaN payload/signaling bit in corresponding binary64 positions. Binary32 encoding
quiets NaNs, retaining sign and high payload bits. Thus signaling NaNs are quiet
after a binary32 decode/encode round trip. Use raw integer byte storage when
preserving an arbitrary binary32 payload without conversion is required.
Subsequent floating arithmetic may also quiet NaNs.

The runtime supplies the existing memory-safe binary64 representation mechanism.
Binary32 rounding/expansion are ordinary Xu integer algorithms and do not depend
on the host FPU rounding mode. There is no new numeric type, foreign library,
GPU dependency or general unsafe pointer API. Supported backends share Xu's
64-bit numeric value representation, including on targets with 32-bit pointers.

`abs`, `copysign` and `signbit` now inspect/modify sign bits rather than comparing
values. This corrects negative-zero magnitude handling and negative NaN signs:
`abs(-0.0)` is positive zero; `copysign` accepts a NaN sign source; `signbit`
reports its sign even for NaNs. Magnitude payload bits are preserved.

For explicit endian storage in tight byte arrays, use
[`#encoding/binary`](../encoding/binary/README.md).
