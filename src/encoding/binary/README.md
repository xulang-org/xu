# Binary byte order and floating-point storage

`Endian` supports little/big byte order. SDK **0.12.3-dev.5** adds tight `[]u8`
integer and floating interfaces. Existing integer methods on `[]int` retain
their behavior; the `_bytes` suffix distinguishes the new integer storage.
No native library, C compiler, GPU or UI dependency is required.

```xu
#encoding/binary

$bytes := [u8(0), u8(0), u8(0), u8(0)]
order := binary.little_endian()
order.put_f32($&bytes, 0, 0.5) or >>
value := order.get_f32(&bytes, 0) or >>
assert(value == 0.5)
```

- `get_u16_bytes/get_u32_bytes/get_u64_bytes` read unsigned bit patterns in Xu
  `int`; a high-bit u64 pattern is represented by a negative int.
- `get_i16_bytes/get_i32_bytes/get_i64_bytes` sign-extend the stored integer.
- `put_u16_bytes/put_u32_bytes/put_u64_bytes` and their `put_i*` counterparts
  write the low 16/32/64 bits. They do not reject out-of-width integer bits.
- `get_f32/put_f32` expand/round IEEE binary32 storage to/from Xu `f64` values.
  Xu does not gain a binary32 numeric type. Encoding rounds to nearest with
  ties to even, supports gradual underflow and yields signed infinity on
  overflow. NaN encoding retains the sign/high payload and sets the quiet bit.
- `get_f64/put_f64` preserve all IEEE binary64 bits, including signed zero and
  NaN payloads. No arithmetic conversion or finite-value restriction is applied.

Every call validates the complete region before reading/writing. Negative,
truncated and huge offsets throw; failed writes leave array values unchanged.
Unaligned offsets are supported. Successful writes return the byte count.
Mutable borrows preserve Xu copy-on-write snapshots. Functions do not retain
references, resize the array or add alignment/struct padding. GPU uniform,
vertex or file layouts remain explicit caller responsibilities.

See [`#math` value/bit conversion](../../math/README.md) for precise NaN semantics.
Wire byte order is explicit; `native_endian()` currently returns little endian,
matching the supported targets, and is not a substitute for a protocol format.
