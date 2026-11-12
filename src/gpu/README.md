# GPU device and transfers

`#gpu` is an optional, source-backed standard-library device layer, introduced
in SDK **0.12.3-dev.3**. This first slice provides windowless devices, buffers,
asynchronous upload/copy/download, completion fences and readback. Rendering,
compute dispatch, textures, shaders, pipelines and presentation are subsequent
slices; their names are not placeholder APIs in this package.

```xu
#gpu

options := gpu.DeviceOptions{backend: gpu.AUTO, debug: false, shader_formats: 0}
$device := gpu.open(options) or >>
$buffer := device.buffer(4, gpu.BUFFER_VERTEX) or >>
input := [u8(0), u8(127), u8(128), u8(255)]
$uploaded := device.upload(&buffer, 0, &input) or >>
$result := device.download(&buffer, 0, 4) or >>
result.wait() or >>
$output := [u8(0), u8(0), u8(0), u8(0)]
result.read($&output) or >>
assert(output[3] == u8(255))
```

Resource owners use `drop` or explicit `close()`. Keep devices, their resources
and all borrows on the application main thread. A device opens no window but
initializes a balanced SDL video reference; a platform display/video driver
may still be required. It does not own other users' SDL subsystem references.
Closing a device waits for its GPU work and invalidates all children. IDs are
private and never reused within the process. Driver resources referenced by
submitted work are released when safe, even if their CPU owners close earlier.

Transfers submit before returning. Upload copies `&[]u8` into owned staging
before returning and retains no Xu pointer. Copy requires distinct buffers.
Buffer sizes, offsets and transfer lengths are positive/in-bounds multiples
of four bytes (offset zero is allowed). Buffer sizes fit an unsigned 32-bit
descriptor; actual device allocation may fail below that representation limit.
Zero-length transfers are errors. Buffer usage flags can be combined where
the backend permits; VERTEX and INDEX cannot be combined.

`Fence` and `Readback` expose `ready()` and blocking `wait()`. Completion is
monotonic after a successful query/wait. Readback is separate from the original
buffer owner; `read($&[]u8)` requires completion and an exact-size destination.
Failure leaves its values unchanged. Repeated reads/waits are allowed until
close. Upload/copy fences can be closed without waiting. `Stats` reports live
buffer/submission owners and logical buffer/staging bytes, including completed
submissions still owned by callers; it does not report physical GPU memory.

Options request AUTO, METAL, VULKAN or D3D12; unavailable backends return errors.
`shader_formats=0` permits all known formats when choosing a backend; explicit
SPIRV/DXBC/DXIL/MSL/METALLIB flags constrain that selection. `shader_formats()`
reports the selected device's formats, not a bundled shader compiler. These
are Xu constants; the private backend maps them to SDL values.

Importing `#gpu` compiles its private C backend with the chosen SDK's sibling
`xu-native` and a platform C compiler. SDK source includes its small, private
SDL ABI subset; consumers do not need SDL development headers or application
`native:` declarations. `XU_NATIVE_CC` selects the C compiler. Link/runtime SDK
requirements are the same as other native executable builds. This slice supports
64-bit hosted macOS/Linux/Windows executables; native imports cannot currently
be emitted as standalone application objects (`--emit-obj`). The SDL 3.2+
runtime is loaded only by `open`; `XU_GPU_SDL_LIBRARY` selects an explicit
library path and disables fallback searching. Missing libraries, devices and
unsupported options return errors. The loader library is cached for process
lifetime. [`#gpu/layout`](layout/README.md) stays pure Xu and needs neither C
tools nor SDL.

Device runtime acceptance currently covers macOS arm64 Metal. Installed-SDK
checks exercise backend compilation, byte-span ABI and missing-runtime errors
without pretending the CI hosts provide GPU hardware. GPU backends on other
platforms require their own execution evidence.

The resource/timeline contracts follow the SDL definitions for
[buffer release](https://wiki.libsdl.org/SDL3/SDL_ReleaseGPUBuffer),
[buffer copy](https://wiki.libsdl.org/SDL3/SDL_CopyGPUBufferToBuffer) and
[fence completion](https://wiki.libsdl.org/SDL3/SDL_QueryGPUFence).
