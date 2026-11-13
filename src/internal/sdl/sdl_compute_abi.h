#ifndef XU_GPU_SDL_COMPUTE_ABI_H
#define XU_GPU_SDL_COMPUTE_ABI_H
/* Altered declaration subset from SDL 3.4.14 SDL_gpu.h, not an SDL SDK.
 * SDL copyright (C) 1997-2026 Sam Lantinga <slouken@libsdl.org>.
 * This software is provided 'as-is', without any express or implied warranty.
 * In no event will the authors be held liable for any damages arising from
 * the use of this software. Permission is granted to anyone to use this
 * software for any purpose, including commercial applications, and to alter
 * it and redistribute it freely, subject to the following restrictions:
 * 1. The origin of this software must not be misrepresented; you must not
 * claim that you wrote the original software. If you use this software in a
 * product, an acknowledgment in the product documentation would be
 * appreciated but is not required.
 * 2. Altered source versions must be plainly marked as such, and must not
 * be misrepresented as being the original software.
 * 3. This notice may not be removed or altered from any source distribution.
 */
#ifndef XU_GPU_VERIFY_SDL
typedef struct SDL_GPUComputePipeline SDL_GPUComputePipeline;
typedef struct SDL_GPUComputePass SDL_GPUComputePass;
typedef struct SDL_GPUStorageTextureReadWriteBinding SDL_GPUStorageTextureReadWriteBinding;
typedef struct {
    size_t code_size;
    const Uint8 *code;
    const char *entrypoint;
    SDL_GPUShaderFormat format;
    Uint32 num_samplers, num_readonly_storage_textures, num_readonly_storage_buffers;
    Uint32 num_readwrite_storage_textures, num_readwrite_storage_buffers, num_uniform_buffers;
    Uint32 threadcount_x, threadcount_y, threadcount_z;
    SDL_PropertiesID props;
} SDL_GPUComputePipelineCreateInfo;
typedef struct {
    SDL_GPUBuffer *buffer;
    bool cycle;
    Uint8 padding1, padding2, padding3;
} SDL_GPUStorageBufferReadWriteBinding;
SDL_GPUComputePipeline *SDL_CreateGPUComputePipeline(SDL_GPUDevice *, const SDL_GPUComputePipelineCreateInfo *);
void SDL_ReleaseGPUComputePipeline(SDL_GPUDevice *, SDL_GPUComputePipeline *);
SDL_GPUComputePass *SDL_BeginGPUComputePass(SDL_GPUCommandBuffer *, const SDL_GPUStorageTextureReadWriteBinding *, Uint32,
    const SDL_GPUStorageBufferReadWriteBinding *, Uint32);
void SDL_EndGPUComputePass(SDL_GPUComputePass *);
void SDL_BindGPUComputePipeline(SDL_GPUComputePass *, SDL_GPUComputePipeline *);
void SDL_BindGPUComputeStorageBuffers(SDL_GPUComputePass *, Uint32, SDL_GPUBuffer *const *, Uint32);
void SDL_PushGPUComputeUniformData(SDL_GPUCommandBuffer *, Uint32, const void *, Uint32);
void SDL_DispatchGPUCompute(SDL_GPUComputePass *, Uint32, Uint32, Uint32);
#endif
_Static_assert(sizeof(SDL_GPUComputePipelineCreateInfo) == 72 && _Alignof(SDL_GPUComputePipelineCreateInfo) == 8, "SDL compute pipeline ABI");
_Static_assert(sizeof(SDL_GPUStorageBufferReadWriteBinding) == 16 && _Alignof(SDL_GPUStorageBufferReadWriteBinding) == 8, "SDL compute buffer binding ABI");
#endif
