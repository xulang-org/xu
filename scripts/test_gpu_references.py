#!/usr/bin/env python3
"""Real Metal gate for non-owning GPU identities and recorded-command lifetime."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

SOURCE = '''@main
#gpu
#gpu/layout
#encoding/binary
fn code(text string) []u8 { $out := []u8{}
    for i in 0:text.len { out.push(u8(text[i])) }
    << out }
fn bad_buffer(ref gpu.BufferRef) bool { ref.validate() or(err){ << true }
    << false }
fn bad_texture(ref gpu.TextureRef) bool { ref.validate() or(err){ << true }
    << false }
fn bad_sampler(ref gpu.SamplerRef) bool { ref.validate() or(err){ << true }
    << false }
fn bad_device(ref gpu.DeviceRef) bool { ref.validate() or(err){ << true }
    << false }
fn foreign(ref gpu.DeviceRef, buffer gpu.BufferRef) bool { ref.validate_buffer(buffer) or(err){ << true }
    << false }
fn bad_index(pass &gpu.RenderPass, ref gpu.BufferRef) bool { pass.index_buffer_ref(ref,0,0) or(err){ << true }
    << false }
fn bad_binding(pass &gpu.RenderPass, ref gpu.BufferRef) bool { pass.vertex_buffer_ref(0,ref,0) or(err){ << true }
    << false }
fn run() int {
    assert(bad_device(gpu.DeviceRef{}) && bad_buffer(gpu.BufferRef{}) && bad_texture(gpu.TextureRef{}) && bad_sampler(gpu.SamplerRef{}))
    $device := gpu.open(gpu.DeviceOptions{backend: gpu.METAL,debug: true,shader_formats: gpu.SHADER_MSL}) or >>
    owner := device.reference()
    owner.validate() or >>
    assert(owner.same(device.reference()) && !owner.same(gpu.DeviceRef{}))
    $other := gpu.open(gpu.DeviceOptions{backend: gpu.METAL,debug: true,shader_formats: gpu.SHADER_MSL}) or >>
    $vertex := device.buffer(24,gpu.BUFFER_VERTEX) or >>
    $index := device.buffer(12,gpu.BUFFER_INDEX) or >>
    $bytes := []u8{}
    for i in 0:24 { bytes.push(u8(0)) }
    order := binary.little_endian()
    for i in 0:6 { values := [-1.0,-1.0,3.0,-1.0,-1.0,3.0]
        order.put_f32($&bytes,i*4,values[i]) or >> }
    $indices := []u8{}
    for i in 0:12 { indices.push(u8(0)) }
    for i in 0:3 { order.put_u32_bytes($&indices,i*4,i) or >> }
    $upload := device.upload(&vertex,0,&bytes) or >>
    upload.close() or >>
    $upload_index := device.upload(&index,0,&indices) or >>
    upload_index.close() or >>
    $image := device.texture_2d(gpu.Texture2DDesc{format: layout.RGBA8_UNORM,width: 1,height: 1,levels: 1,usage: gpu.TEXTURE_SAMPLED}) or >>
    pixel := [u8(17),u8(131),u8(239),u8(255)]
    $upload_image := device.upload_texture(&image,0,&pixel) or >>
    upload_image.close() or >>
    $sampler := device.sampler(gpu.sampler_defaults()) or >>
    $target := device.texture_2d(gpu.Texture2DDesc{format: layout.RGBA8_UNORM,width: 4,height: 4,levels: 1,usage: gpu.TEXTURE_COLOR_TARGET}) or >>
    refs := [vertex.reference(),index.reference()]
    sampled := image.reference()
    filtering := sampler.reference()
    owner.validate_buffer(refs[0]) or >>
    owner.validate_texture(sampled) or >>
    owner.validate_sampler(filtering) or >>
    assert(refs[0].size_bytes()==24 && foreign(other.reference(),refs[0]))
    vs_code := code("#include <metal_stdlib>\\nusing namespace metal;struct V{float2 p [[attribute(0)]];};vertex float4 main0(V v [[stage_in]]) {return float4(v.p,0,1);}")
    fs_code := code("#include <metal_stdlib>\\nusing namespace metal;fragment float4 main0(texture2d<float> t [[texture(0)]],sampler s [[sampler(0)]]) {return t.sample(s,float2(0.5));}")
    vs_desc := gpu.ShaderDesc{stage: gpu.VERTEX,format: gpu.SHADER_MSL,entrypoint: "main0",samplers: 0,uniform_sizes: []int{}}
    fs_desc := gpu.ShaderDesc{stage: gpu.FRAGMENT,format: gpu.SHADER_MSL,entrypoint: "main0",samplers: 1,uniform_sizes: []int{}}
    $vs := device.shader(&vs_desc,&vs_code) or >>
    $fs := device.shader(&fs_desc,&fs_code) or >>
    $desc := gpu.pipeline_defaults(layout.RGBA8_UNORM)
    desc.vertex_buffers = [gpu.VertexBufferLayout{slot: 0,stride: 8,rate: gpu.PER_VERTEX}]
    desc.attributes = [gpu.VertexAttribute{location: 0,slot: 0,format: gpu.FLOAT2,offset: 0}]
    $pipeline := device.graphics_pipeline(&vs,&fs,&desc) or >>
    $encoder := device.command_encoder() or >>
    attachment := gpu.ColorAttachment{view: target.view(0) or >>,load: gpu.CLEAR,store: gpu.STORE,clear: gpu.Color{r: 0.0,g: 0.0,b: 0.0,a: 1.0}}
    $pass := encoder.begin_render(attachment,gpu.no_depth()) or >>
    pass.pipeline(&pipeline) or >>
    assert(bad_index(&pass,refs[1]))
    pass.vertex_buffer_ref(0,refs[0],0) or >>
    pass.index_buffer_ref(refs[1],0,gpu.INDEX32) or >>
    pass.sampler_ref(gpu.FRAGMENT,0,sampled,filtering) or >>
    pass.draw_indexed(3,0,0,1,0) or >>
    pass.end() or >>
    // CPU ownership ends, while the recorded draw still retains allocations.
    vertex.close() or >>
    index.close() or >>
    image.close() or >>
    sampler.close() or >>
    assert(bad_buffer(refs[0]) && bad_buffer(refs[1]) && bad_texture(sampled) && bad_sampler(filtering))
    $probe := device.command_encoder() or >>
    $probe_pass := probe.begin_render(attachment,gpu.no_depth()) or >>
    probe_pass.pipeline(&pipeline) or >>
    assert(bad_binding(&probe_pass,refs[0]))
    probe_pass.end() or >>
    probe.close() or >>
    $fence := encoder.submit() or >>
    fence.wait() or >>
    fence.close() or >>
    $read := device.download_texture(&target,0) or >>
    read.wait() or >>
    $pixels := []u8{}
    for i in 0:64 { pixels.push(u8(0)) }
    read.read($&pixels) or >>
    for i in 0:16 { assert(pixels[i*4]==u8(17) && pixels[i*4+1]==u8(131) && pixels[i*4+2]==u8(239) && pixels[i*4+3]==u8(255)) }
    read.close() or >>
    stats := device.stats() or >>
    assert(stats.buffer_count==0 && stats.texture_count==1 && stats.sampler_count==0)
    device.close() or >>
    assert(bad_device(owner) && bad_buffer(refs[0]) && bad_texture(sampled))
    $fresh := other.buffer(24,gpu.BUFFER_VERTEX) or >>
    assert(foreign(other.reference(),refs[0]))
    fresh.reference().validate() or >>
    other.close() or >>
    println("PASS: typed GPU references, zero/stale/foreign validation, invalid index size, closed-but-retained rejection, exact Metal pixels and completion lifetime")
    << 0
}
fn main() int { << run() or(err){ eprintln(err.msg())
    << 1 } }
'''


def main():
    if platform.system() != 'Darwin':
        raise SystemExit('This real-device gate requires macOS Metal; installed-SDK API checks cover all native targets separately.')
    with tempfile.TemporaryDirectory(prefix='xu GPU references ') as directory:
        root = Path(directory)
        (root/'main.xu').write_text(SOURCE)
        program = root/'references'
        for level in ('-O0','-O2','-O3'):
            subprocess.run([os.environ.get('XU','xu'),'build',str(root/'main.xu'),level,'-o',str(program)],cwd=root,check=True,timeout=60)
            subprocess.run([str(program)],cwd=root,check=True,timeout=60)


if __name__ == '__main__':
    main()
