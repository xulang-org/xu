#!/usr/bin/env python3
"""Real Metal gate for modern GPU features: storage resources, compute textures, MRT, R32_UINT, indirect draw/dispatch."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

SOURCE = '''@main
#gpu
#gpu/layout
#encoding/binary

fn code(text string) []u8 {
    $out := []u8{}
    for i in 0:text.len { out.push(u8(text[i])) }
    << out
}

fn bad_r32_blend(device &gpu.Device, vs &gpu.Shader, fs &gpu.Shader) bool {
    $desc := gpu.pipeline_defaults(layout.R32_UINT)
    desc.blend = gpu.BLEND_ALPHA
    targets := [gpu.ColorTargetDesc{format: layout.R32_UINT, blend: gpu.BLEND_ALPHA}]
    p := device.graphics_pipeline_targets(vs, fs, &desc, &targets) or (err) { << true }
    << false
}

fn bad_empty_targets(encoder &gpu.CommandEncoder) bool {
    colors := []gpu.ColorAttachment{}
    p := encoder.begin_render_targets(&colors, gpu.no_depth()) or (err) { << true }
    << false
}

fn run() int {
    assert(layout.R32_UINT == 21)
    r32_info := layout.format_info(layout.R32_UINT) or >>
    assert(r32_info.block_bytes == 4 && r32_info.block_width == 1 && !r32_info.depth && !r32_info.srgb)

    $device := gpu.open(gpu.DeviceOptions{backend: gpu.METAL, debug: true, shader_formats: gpu.SHADER_MSL}) or >>
    order := binary.little_endian()

    assert(device.supports_texture_2d(layout.R32_UINT, gpu.TEXTURE_COLOR_TARGET))
    assert(device.supports_texture_2d(layout.RGBA8_UNORM, gpu.TEXTURE_SAMPLED | gpu.TEXTURE_COMPUTE_STORAGE_READ | gpu.TEXTURE_COMPUTE_STORAGE_WRITE | gpu.TEXTURE_GRAPHICS_STORAGE_READ))

    // 1. Sampled source texture (1x1) & compute read-only storage texture (1x1) & compute RW output texture (2x2).
    $sampled_src := device.texture_2d(gpu.Texture2DDesc{format: layout.RGBA8_UNORM, width: 1, height: 1, levels: 1, usage: gpu.TEXTURE_SAMPLED}) or >>
    $up1 := device.upload_texture(&sampled_src, 0, &[u8(40), u8(60), u8(80), u8(255)]) or >>
    up1.wait() or >>
    up1.close() or >>

    $ro_tex := device.texture_2d(gpu.Texture2DDesc{format: layout.RGBA8_UNORM, width: 1, height: 1, levels: 1, usage: gpu.TEXTURE_COMPUTE_STORAGE_READ | gpu.TEXTURE_GRAPHICS_STORAGE_READ}) or >>
    $up2 := device.upload_texture(&ro_tex, 0, &[u8(10), u8(20), u8(30), u8(0)]) or >>
    up2.wait() or >>
    up2.close() or >>

    $rw_tex := device.texture_2d(gpu.Texture2DDesc{format: layout.RGBA8_UNORM, width: 2, height: 2, levels: 1, usage: gpu.TEXTURE_COMPUTE_STORAGE_WRITE | gpu.TEXTURE_GRAPHICS_STORAGE_READ}) or >>
    $sampler := device.sampler(gpu.sampler_defaults()) or >>

    // 2. Buffers for indirect dispatch, indirect indexed draw, and graphics storage read.
    // Indirect dispatch buffer (12 bytes): [1, 1, 1] written by Compute Pass 1, consumed by Compute Pass 2 via dispatch_indirect!
    $dispatch_buf := device.buffer(16, gpu.BUFFER_INDIRECT | gpu.BUFFER_COMPUTE_STORAGE_WRITE) or >>
    // Indirect draw args (20 bytes) + 1 packed tint vec4 (16 bytes) -> separate buffers for clarity.
    $indirect_draw_buf := device.buffer(32, gpu.BUFFER_INDIRECT | gpu.BUFFER_COMPUTE_STORAGE_WRITE) or >>
    $gfx_storage_buf := device.buffer(64, gpu.BUFFER_GRAPHICS_STORAGE_READ | gpu.BUFFER_COMPUTE_STORAGE_WRITE) or >>
    $dummy_ro_buf := device.buffer(16, gpu.BUFFER_COMPUTE_STORAGE_READ) or >>
    $rb_init := []u8{}
    for i in 0:16 { rb_init.push(u8(0)) }
    order.put_u32_bytes($&rb_init, 0, 100) or >>
    $up_rb := device.upload(&dummy_ro_buf, 0, &rb_init) or >>
    up_rb.wait() or >>
    up_rb.close() or >>

    // Index buffer for 1 fullscreen/viewport triangle (indices 0, 1, 2).
    $index_buf := device.buffer(12, gpu.BUFFER_INDEX) or >>
    $idx_bytes := []u8{}
    for i in 0:12 { idx_bytes.push(u8(0)) }
    for i in 0:3 { order.put_u32_bytes($&idx_bytes, i * 4, i) or >> }
    $up_idx := device.upload(&index_buf, 0, &idx_bytes) or >>
    up_idx.wait() or >>
    up_idx.close() or >>

    // Compute shader 1: writes dispatch_indirect args [1, 1, 1].
    cs_prep_code := code("#include <metal_stdlib>\\nusing namespace metal;\\nkernel void main0(device uint* dispatch_args [[buffer(0)]]) {\\ndispatch_args[0] = 1u;\\ndispatch_args[1] = 1u;\\ndispatch_args[2] = 1u;\\n}\\n")
    cs_prep_desc := gpu.ComputePipelineDesc{
        format: gpu.SHADER_MSL, entrypoint: "main0",
        read_buffers: 0, write_buffers: 1, uniform_sizes: []int{},
        threads_x: 1, threads_y: 1, threads_z: 1
    }
    $cs_prep := device.compute_pipeline(&cs_prep_desc, &cs_prep_code) or >>

    // Compute shader 2 (ComputeResourcesDesc):
    // MSL order: [[buffer]]: uniforms (0), readonly storage (1), readwrite storage (2, 3)
    //            [[texture]]: sampled (0), readonly storage (1), readwrite storage (2)
    //            [[sampler]]: sampler (0)
    cs_build_code := code("#include <metal_stdlib>\\nusing namespace metal;\\nstruct Params { uint prim_id; uint pad0; uint pad1; uint pad2; };\\nkernel void main0(constant Params& u [[buffer(0)]], device const uint* ro_buf [[buffer(1)]], device uint* indirect_args [[buffer(2)]], device float4* vert_and_color [[buffer(3)]], texture2d<float> samp_tex [[texture(0)]], texture2d<float> ro_tex [[texture(1)]], texture2d<float, access::write> rw_tex [[texture(2)]], sampler s [[sampler(0)]], uint2 gid [[thread_position_in_grid]]) {\\nfloat4 c = samp_tex.sample(s, float2(0.5)) + ro_tex.read(uint2(0, 0));\\nrw_tex.write(c, gid);\\nif (gid.x == 0 && gid.y == 0) {\\nindirect_args[0] = 3u;\\nindirect_args[1] = 1u;\\nindirect_args[2] = 0u;\\nindirect_args[3] = 0u;\\nindirect_args[4] = ro_buf[0] - 100u;\\nvert_and_color[0] = float4(-1.0, -1.0, 0.0, 1.0);\\nvert_and_color[1] = float4( 3.0, -1.0, 0.0, 1.0);\\nvert_and_color[2] = float4(-1.0,  3.0, 0.0, 1.0);\\nvert_and_color[3] = float4(float(u.prim_id), 0.0, 0.0, 0.0);\\n}\\n}\\n")
    cs_build_desc := gpu.ComputeResourcesDesc{
        format: gpu.SHADER_MSL, entrypoint: "main0",
        samplers: 1, read_textures: 1, read_buffers: 1,
        write_textures: 1, write_buffers: 2,
        uniform_sizes: [16],
        threads_x: 2, threads_y: 2, threads_z: 1
    }
    $cs_build := device.compute_pipeline_with_resources(&cs_build_desc, &cs_build_code) or >>

    // 3. Graphics shaders using vertex storage buffer + fragment storage texture + fragment storage buffer + MRT (RGBA8 + R32_UINT) + depth!
    vs_code := code("#include <metal_stdlib>\\nusing namespace metal;\\nstruct VOut { float4 pos [[position]]; };\\nvertex VOut main0(uint vid [[vertex_id]], device const float4* verts [[buffer(0)]]) {\\nVOut o;\\no.pos = verts[vid];\\nreturn o;\\n}\\n")
    fs_code := code("#include <metal_stdlib>\\nusing namespace metal;\\nstruct FOut { float4 color [[color(0)]]; uint id [[color(1)]]; };\\nfragment FOut main0(texture2d<float> stex [[texture(0)]], device const float4* buf [[buffer(0)]]) {\\nFOut o;\\no.color = stex.read(uint2(0, 0));\\no.id = uint(buf[3].x);\\nreturn o;\\n}\\n")
    fs_depth_only_code := code("#include <metal_stdlib>\\nusing namespace metal;\\nfragment void main0() {}\\n")

    vs_desc := gpu.ShaderResourcesDesc{stage: gpu.VERTEX, format: gpu.SHADER_MSL, entrypoint: "main0", samplers: 0, storage_textures: 0, storage_buffers: 1, uniform_sizes: []int{}}
    fs_desc := gpu.ShaderResourcesDesc{stage: gpu.FRAGMENT, format: gpu.SHADER_MSL, entrypoint: "main0", samplers: 0, storage_textures: 1, storage_buffers: 1, uniform_sizes: []int{}}
    fs_depth_desc := gpu.ShaderResourcesDesc{stage: gpu.FRAGMENT, format: gpu.SHADER_MSL, entrypoint: "main0", samplers: 0, storage_textures: 0, storage_buffers: 0, uniform_sizes: []int{}}

    $vs := device.shader_with_resources(&vs_desc, &vs_code) or >>
    $fs := device.shader_with_resources(&fs_desc, &fs_code) or >>
    $fs_depth := device.shader_with_resources(&fs_depth_desc, &fs_depth_only_code) or >>

    assert(bad_r32_blend(&device, &vs, &fs))

    $mrt_desc := gpu.pipeline_defaults(layout.RGBA8_UNORM)
    mrt_desc.depth_format = layout.DEPTH32_FLOAT
    mrt_desc.depth_compare = gpu.LESS_EQUAL
    mrt_desc.depth_write = true
    mrt_targets := [gpu.ColorTargetDesc{format: layout.RGBA8_UNORM, blend: gpu.BLEND_DISABLED}, gpu.ColorTargetDesc{format: layout.R32_UINT, blend: gpu.BLEND_DISABLED}]
    $mrt_pipe := device.graphics_pipeline_targets(&vs, &fs, &mrt_desc, &mrt_targets) or >>

    $depth_desc := gpu.pipeline_defaults(0)
    depth_desc.depth_format = layout.DEPTH32_FLOAT
    depth_desc.depth_compare = gpu.LESS_EQUAL
    depth_desc.depth_write = true
    no_targets := []gpu.ColorTargetDesc{}
    $depth_pipe := device.graphics_pipeline_targets(&vs, &fs_depth, &depth_desc, &no_targets) or >>

    $color_out := device.texture_2d(gpu.Texture2DDesc{format: layout.RGBA8_UNORM, width: 2, height: 2, levels: 1, usage: gpu.TEXTURE_COLOR_TARGET}) or >>
    $id_out := device.texture_2d(gpu.Texture2DDesc{format: layout.R32_UINT, width: 2, height: 2, levels: 1, usage: gpu.TEXTURE_COLOR_TARGET}) or >>
    $depth_out := device.texture_2d(gpu.Texture2DDesc{format: layout.DEPTH32_FLOAT, width: 2, height: 2, levels: 1, usage: gpu.TEXTURE_DEPTH_TARGET}) or >>

    $encoder := device.command_encoder() or >>
    assert(bad_empty_targets(&encoder))

    // Compute Pass 1: write indirect dispatch dimensions [1, 1, 1].
    cp1_writes := [gpu.write_buffer(&dispatch_buf, true)]
    $cp1 := encoder.begin_compute(&cp1_writes) or >>
    cp1.pipeline(&cs_prep) or >>
    cp1.dispatch(1, 1, 1) or >>
    cp1.end() or >>

    // Compute Pass 2: dispatch_indirect -> reads sampler, ro_tex, ro_buf; writes rw_tex, indirect_draw_buf, gfx_storage_buf.
    cp2_tex_writes := [gpu.write_texture(&rw_tex, 0, 0, true)]
    cp2_buf_writes := [gpu.write_buffer(&indirect_draw_buf, true), gpu.write_buffer(&gfx_storage_buf, true)]
    $cp2 := encoder.begin_compute_with_resources(&cp2_tex_writes, &cp2_buf_writes) or >>
    cp2.pipeline(&cs_build) or >>
    cp2.sampler(0, &sampled_src, &sampler) or >>
    cp2.read_texture(0, &ro_tex) or >>
    cp2.read_buffer(0, &dummy_ro_buf) or >>
    $unif := []u8{}
    for i in 0:16 { unif.push(u8(0)) }
    order.put_u32_bytes($&unif, 0, 777) or >>
    cp2.uniform(0, &unif) or >>
    cp2.dispatch_indirect(&dispatch_buf, 0) or >>
    cp2.end() or >>

    // Render Pass 1: depth-only prepass (0 color attachments!).
    no_colors := []gpu.ColorAttachment{}
    $rp_depth := encoder.begin_render_targets(&no_colors, gpu.depth_attachment(&depth_out, gpu.CLEAR, gpu.STORE, 1.0)) or >>
    rp_depth.pipeline(&depth_pipe) or >>
    rp_depth.storage_buffer(gpu.VERTEX, 0, &gfx_storage_buf) or >>
    rp_depth.index_buffer(&index_buf, 0, gpu.INDEX32) or >>
    rp_depth.draw_indexed_indirect(&indirect_draw_buf, 0, 1) or >>
    rp_depth.end() or >>

    // Render Pass 2: MRT color (RGBA8_UNORM) + ID (R32_UINT) using graphics storage buffers/textures + draw_indexed_indirect!
    v0 := color_out.view(0) or >>
    v1 := id_out.view(0) or >>
    mrt_colors := [gpu.ColorAttachment{view: v0, load: gpu.CLEAR, store: gpu.STORE, clear: gpu.Color{r: 0.0, g: 0.0, b: 0.0, a: 1.0}}, gpu.ColorAttachment{view: v1, load: gpu.CLEAR, store: gpu.STORE, clear: gpu.Color{r: 0.0, g: 0.0, b: 0.0, a: 0.0}}]
    $rp_mrt := encoder.begin_render_targets(&mrt_colors, gpu.depth_attachment(&depth_out, gpu.LOAD, gpu.DONT_STORE, 1.0)) or >>
    rp_mrt.pipeline(&mrt_pipe) or >>
    rp_mrt.storage_buffer(gpu.VERTEX, 0, &gfx_storage_buf) or >>
    rp_mrt.storage_texture(gpu.FRAGMENT, 0, &rw_tex) or >>
    rp_mrt.storage_buffer(gpu.FRAGMENT, 0, &gfx_storage_buf) or >>
    rp_mrt.index_buffer(&index_buf, 0, gpu.INDEX32) or >>
    rp_mrt.draw_indexed_indirect(&indirect_draw_buf, 0, 1) or >>
    rp_mrt.end() or >>

    $fence := encoder.submit() or >>
    fence.wait() or >>
    fence.close() or >>

    // Readback and verify all 3 outputs: rw_tex (50, 80, 110, 255), color_out (50, 80, 110, 255), id_out (777u)!
    $dl_rw := device.download_texture(&rw_tex, 0) or >>
    dl_rw.wait() or >>
    $rw_px := []u8{}
    for i in 0:16 { rw_px.push(u8(0)) }
    dl_rw.read($&rw_px) or >>
    dl_rw.close() or >>
    for i in 0:4 {
        assert(rw_px[i * 4] == u8(50) && rw_px[i * 4 + 1] == u8(80) && rw_px[i * 4 + 2] == u8(110) && rw_px[i * 4 + 3] == u8(255))
    }

    $dl_col := device.download_texture(&color_out, 0) or >>
    dl_col.wait() or >>
    $col_px := []u8{}
    for i in 0:16 { col_px.push(u8(0)) }
    dl_col.read($&col_px) or >>
    dl_col.close() or >>
    for i in 0:4 {
        assert(col_px[i * 4] == u8(50) && col_px[i * 4 + 1] == u8(80) && col_px[i * 4 + 2] == u8(110) && col_px[i * 4 + 3] == u8(255))
    }

    $dl_id := device.download_texture(&id_out, 0) or >>
    dl_id.wait() or >>
    $id_bytes := []u8{}
    for i in 0:16 { id_bytes.push(u8(0)) }
    dl_id.read($&id_bytes) or >>
    dl_id.close() or >>
    for i in 0:4 {
        got := order.get_u32_bytes(&id_bytes, i * 4) or >>
        assert(got == 777)
    }

    println("PASS: Metal modern GPU gate (ComputeResources + dispatch_indirect + R32_UINT MRT + depth-only pass + VS/FS storage + draw_indexed_indirect)")
    << 0
}

fn main() int {
    << run() or (err) {
        eprintln(err.msg())
        << 1
    }
}
'''


def main():
    if platform.system() != 'Darwin':
        raise SystemExit('This real-device gate requires macOS Metal.')
    with tempfile.TemporaryDirectory(prefix='xu GPU modern ') as directory:
        root = Path(directory)
        (root / 'main.xu').write_text(SOURCE)
        program = root / 'modern_gpu'
        for flag in ('--no-opt', '--release'):
            subprocess.run(
                [os.environ.get('XU', 'xu'), 'build', str(root / 'main.xu'), flag, '-o', str(program)],
                cwd=root,
                check=True,
                timeout=60,
            )
            subprocess.run([str(program)], cwd=root, check=True, timeout=60)


if __name__ == '__main__':
    main()
