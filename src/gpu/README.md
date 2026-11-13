# GPU resources and command recording

`#gpu` is the optional device layer of the Xu standard library. SDK
**0.12.3-dev.6** provides windowless devices, buffers, 2D textures/mips,
samplers, vertex/fragment shaders, graphics pipelines, command encoders,
render/compute passes, buffer compute pipelines, asynchronous transfers,
fences and exact byte readback.
Scene graphs, cameras, materials, PBR and rendering budgets belong to engines.
Window presentation, cube/3D textures, storage texture bindings,
multiple render targets, multisampling and stencil are not implemented here.

## Device and ownership

```xu
#gpu

$device := gpu.open(gpu.DeviceOptions{backend: gpu.AUTO, debug: false, shader_formats: 0}) or >>
$buffer := device.buffer(4, gpu.BUFFER_VERTEX) or >>
input := [u8(0), u8(127), u8(128), u8(255)]
$uploaded := device.upload(&buffer, 0, &input) or >>
$result := device.download(&buffer, 0, 4) or >>
result.wait() or >>
$output := [u8(0), u8(0), u8(0), u8(0)]
result.read($&output) or >>
assert(output[3] == u8(255))
```

All resource owners support automatic `drop` and explicit idempotent `close`;
render passes use `end`. Keep devices, resources and borrows on the application
main thread. Private IDs are never reused within a process. Closing a device
cancels its unsubmitted encoders, waits for submitted GPU work, releases its
children and invalidates all remaining owners/views. A device opens no window,
but holds a balanced SDL video reference; a display/video driver may still be
required. Other SDL users keep their own references.

`CommandEncoder` retains resources referenced by recorded commands. Closing a
bound buffer, texture, sampler or pipeline invalidates its CPU owner, while the
recorded draw can still use it. Submission/cancellation releases these command
references; SDL defers physical destruction until submitted work finishes.
Shaders may close after pipeline creation. A new binding with a closed/foreign
owner is always rejected. `TextureSlice` and `DepthAttachment` are non-owning
identities, invalid after their texture/device closes.

## Textures and transfers

Texture format IDs come from [`#gpu/layout`](layout/README.md), independently
of platform enums. `Texture2DDesc` specifies format, dimensions, levels and
SAMPLED/COLOR_TARGET/DEPTH_TARGET usage. `supports_texture_2d` queries the actual
device for a valid format/usage combination; invalid combinations throw.
Creation checks support again and may still fail to allocate. The SDL portable
2D dimension limit is 16384; it is not a GPU memory budget. `levels=0` selects
the full chain. Depth32 targets currently require one level. Each `level_layout`
uses the shared pure Xu layout with tight rows. `size_bytes` counts logical
texels/blocks, not driver allocation overhead.

`upload_texture` and `download_texture` transfer an entire tightly packed mip,
including compressed blocks, with exact lengths. Depth transfers are currently
unsupported. `generate_mips` requires a sampled, uncompressed color target and
multiple levels. Texture transfer staging must fit uint32; no four-byte length
rule is imposed on texture rows. SDL accepts tight row/layer strides and may
internally repack them for D3D12 alignment. No Xu pointer survives a native call.

Buffer transfers require in-bounds multiples of four bytes, positive sizes and
uint32 buffer sizes. Offset zero is allowed. VERTEX and INDEX buffer usage cannot
be combined. `copy` requires distinct buffers. Transfers submit before returning;
upload copies the input into owned staging synchronously. Submission order is
GPU timeline order; encoders only enter that order when submitted.

`Fence` and `Readback` expose `ready` and blocking `wait`. Completion is monotonic
after successful query/wait. `Readback.read($&[]u8)` requires completion and an
exact-size destination, leaving values unchanged on failure. Repeated reads and
waits are allowed. Closing a fence does not wait. Readback owns staging separately
from its source resource.

## Shaders and pipelines

Options request AUTO/METAL/VULKAN/D3D12; unavailable backends throw. Zero shader
formats permits all known formats when choosing a device. Explicit
SPIRV/DXBC/DXIL/MSL/METALLIB flags constrain that choice; `shader_formats` reports
the selected subset. No shader compiler or automatic source translation is
bundled. Supply device-compatible code and the entrypoint in `ShaderDesc`.
MSL source is copied and terminated internally; callers provide no NUL byte.
Binary formats receive basic container checks, then the driver validates code.

`ShaderDesc` declares stage, sampler count (0...16) and exact uniform byte sizes
(up to four slots, each 16...16384 bytes in multiples of 16). Shader declarations,
resource slots and std140-compatible uniform contents must agree with this
metadata. This is the shader author's contract; the API does not reflect or
sandbox shader code. Storage resource bindings are not yet exposed.
Follow SDL's [shader resource conventions](https://wiki.libsdl.org/SDL3/SDL_CreateGPUShader)
for each format, including Metal's reversed vertex-buffer slot numbering.

`pipeline_defaults(format)` initializes a pipeline descriptor with no vertex
inputs, blending or depth. Add explicit vertex buffer layouts and attributes;
slots/locations are unique and in 0...15, strides are four-byte aligned in
4...2048 bytes, attributes fit their stride. Input rates support vertices and
instances. Public vertex formats include float/float2/float3/float4, uint vectors
and normalized u8x4. Primitive topology, culling, winding, depth compare/write
and straight/premultiplied alpha blend are explicit. One color target and an
optional Depth32 target must match the render pass. Depth writes require a
depth test. `sampler_defaults()` returns linear/clamp sampling; filters, address
modes and finite LOD clamps (0...1000) are configurable.

## Command state

Acquire `device.command_encoder()`, call `begin_render(color, depth)`, set the
pipeline, bind resources, draw, end the pass, then submit to receive a fence.
Color attachments use `texture.view(mip)` with LOAD/CLEAR/DISCARD and
STORE/DONT_STORE. `gpu.no_depth()` omits depth; `depth_attachment` specifies mip
zero and a [0,1] clear value. Attachment extents must match. Clear components
are finite floats, permitting HDR values. Contents discarded or never written
are undefined, as are shader reads of uninitialized resources.

An encoder permits one active pass at a time and multiple sequential passes.
Submitting with an active pass fails without consuming the encoder. A driver
submission failure may consume it; close/drop remains safe. Ending a pass is
idempotent. Closing/dropping an encoder ends any active pass and cancels all its
commands. Ending a pass after parent cancellation/device closure is harmless;
further commands on it throw.

Set the pipeline before binding buffers, samplers or uniform data. Every pipeline
change resets required bindings. Draws reject missing bindings, wrong usages,
foreign/closed identities, incompatible targets and invalid ranges before calling
SDL. Sampling an active attachment is rejected even at another mip. Vertex and
instance ranges and index byte ranges are checked; index *values* and shader
memory accesses remain the author's responsibility. Index offsets align to their
2/4-byte element size. Viewport/scissor rectangles use integer attachment pixels
and must fit its extent. Uniform calls synchronously copy exactly the declared
byte size; draws never retain a borrowed Xu array.

`Stats` reports live buffer/texture/sampler/shader/graphics and compute pipeline/encoder/pass owners,
logical buffer/texture/staging bytes and owned submissions. Closed resources
retained by commands and physical driver allocations are excluded. Completed
submissions remain counted until closed. It is not a physical VRAM meter.

## Buffer compute

`ComputePipelineDesc` supplies shader format/entrypoint, read/write buffer counts,
exact uniform sizes and local thread dimensions. Buffer counts are 0...8 each;
uniform slots follow the graphics limits above. Local dimensions are positive,
x/y at most 1024, z at most 64, and their product at most 1024. These portable
interface limits do not guarantee device support; pipeline creation can still
fail. Dimensions and resource metadata must match the compiled shader.
Sampler and storage texture bindings are not yet exposed for compute.

Begin a pass with `encoder.begin_compute(&writes)`, where each write slot uses
`gpu.write_buffer(&buffer, cycle)`. Write buffers require COMPUTE_STORAGE_WRITE;
duplicate write targets are rejected. `cycle=true` permits SDL to replace an
in-use backing allocation, discarding previous contents. Use false to preserve
data needed by a subsequent pass. Pipeline write counts must match the pass.
Set a compute pipeline, bind every declared `read_buffer(slot, &buffer)` and
`uniform(slot, &bytes)`, then `dispatch(groups_x, groups_y, groups_z)` and `end`.
Read buffers require COMPUTE_STORAGE_READ and cannot alias a write binding.
Changing pipelines resets required read/uniform bindings. Dispatch dimensions
are 1...65535 groups per axis; shader bounds checks remain the author's contract.

Render and compute passes cannot overlap on an encoder. Multiple sequential
passes share submission order and retained resources. There is no implicit
barrier between dispatches within one compute pass: end the pass before a
dependent dispatch in a new pass. See the [SDL synchronization contract](https://wiki.libsdl.org/SDL3/SDL_BeginGPUComputePass).
Shader resource indices follow [SDL's compute conventions](https://wiki.libsdl.org/SDL3/SDL_CreateGPUComputePipeline):
with buffer-only compute, SPIR-V uses sets 0/1/2 for read/write/uniform bindings;
HLSL uses t/space0, u/space1 and b/space2; Metal buffer indices place uniforms
first, then read buffers, then write buffers.

Compute owners support the same close/drop and early-release behavior as
graphics owners. `compute_pipeline_count` and `compute_pass_count` are separate
from graphics pipeline/render-pass counts. Real Metal acceptance checks 1027
exact uint32 results across dependent passes, render/compute transitions,
invalid bindings/states and 128 cancellation/drop cycles. Failure injection
covers all 13 native allocation steps in the exercised transaction and 11 driver failure paths with cleanup
and retry; injected results are not additional hardware/platform evidence.

## Build and evidence

Importing `#gpu` compiles its private C backend using the selected SDK's sibling
`xu-native` and compatible Clang toolchain (`XU_NATIVE_CC` may select it). The SDK
contains a small private SDL ABI declaration subset, so applications need no SDL
headers or `native:` mapping. Native executable builds support 64-bit hosted
macOS/Linux/Windows; `--emit-obj` with native imports is currently unsupported.
SDL 3.2+ is loaded only by device creation; rendering symbols load on first use.
`XU_GPU_SDL_LIBRARY` selects an explicit path and disables fallback. Missing
libraries/symbols/devices/options throw. The library stays loaded for process life.
The pure `#gpu/layout` needs neither C tools nor SDL.

Actual hardware validation covers macOS arm64 Metal, including exact odd-sized
pixel readback, compressed mip transfers, sampled indexed/instanced rendering,
uniforms, depth load/store, alpha blending, cancellation and early owner release.
Installed-SDK checks cover backend compilation, mixed scalar/byte-span ABI and
missing-runtime errors; they do not establish GPU hardware availability on CI or
Vulkan/D3D12 execution. Engine renderers can adopt this layer as their required
capabilities become available.
