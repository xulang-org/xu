# GPU texture layouts

`#gpu/layout` computes 2D texture and transfer-buffer layouts without opening a
window, creating a GPU device, loading SDL, or allocating pixel payloads.

```xu
#gpu/layout

storage := layout.texture_2d(layout.RGBA8_SRGB, 2048, 2048, 0, 1, 1) or >>
assert(storage.level_count() == 12 && storage.total_bytes() == 22369620)
transfer := layout.texture_2d(layout.RGBA8_UNORM, 3, 5, 0, 256, 512) or >>
assert((transfer.level(0) or >>).row_pitch == 256)
assert((transfer.level(1) or >>).offset == 1536)
```

`levels=0` requests a full mip chain. Explicit counts range from one to the
full chain length. Each dimension halves with floor division, stopping at one.
Compressed formats round each mip independently to whole blocks. Row and mip
offset alignments are positive powers of two in bytes. Per-level sizes include
the final row's padding; the total ends at the last level's final padded row.
Invalid formats, extents, levels, alignments and signed-64-bit size overflow
return errors before any pixel allocation. The metadata array has at most 63
levels. Returned level descriptions are independent value copies.

The format catalog covers R/RG/RGBA unorm or floating formats, RGBA8/BGRA8 sRGB,
32-bit float depth, and BC1/BC3/BC5/BC7 blocks. These are Xu format IDs, not
SDL, Metal, Vulkan or Direct3D enum values. Metadata availability does not imply
hardware or usage support; the backend must query the actual device. Tight
sizes describe logical texels/blocks, not driver allocation or memory usage.
Device maximums, application budgets, copies and mip generation stay with
their respective device or renderer services.

The format and transfer concepts follow the
[SDL format definitions](https://wiki.libsdl.org/SDL3/SDL_GPUTextureFormat) and
[texture transfer description](https://wiki.libsdl.org/SDL3/SDL_GPUTextureTransferInfo).
Alignment is explicit rather than imposing one backend's padding on all users.
