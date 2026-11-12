#ifndef XU_GPU_SDL_RENDER_ABI_H
#define XU_GPU_SDL_RENDER_ABI_H
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
#include <stddef.h>
typedef uint8_t Uint8;
typedef int32_t Sint32;
typedef Uint32 SDL_PropertiesID;
typedef Uint32 SDL_GPUTextureUsageFlags;
typedef Uint32 SDL_GPUShaderFormat;
typedef Uint8 SDL_GPUColorComponentFlags;
typedef struct { float r, g, b, a; } SDL_FColor;
typedef struct { int x, y, w, h; } SDL_Rect;
typedef struct SDL_GPUTexture SDL_GPUTexture;
typedef struct SDL_GPUSampler SDL_GPUSampler;
typedef struct SDL_GPUShader SDL_GPUShader;
typedef struct SDL_GPUGraphicsPipeline SDL_GPUGraphicsPipeline;
typedef struct SDL_GPURenderPass SDL_GPURenderPass;
typedef enum SDL_GPUTextureType
{
    SDL_GPU_TEXTURETYPE_2D,
    SDL_GPU_TEXTURETYPE_2D_ARRAY,
    SDL_GPU_TEXTURETYPE_3D,
    SDL_GPU_TEXTURETYPE_CUBE,
    SDL_GPU_TEXTURETYPE_CUBE_ARRAY
} SDL_GPUTextureType;
typedef enum SDL_GPUTextureFormat
{
    SDL_GPU_TEXTUREFORMAT_INVALID,
    SDL_GPU_TEXTUREFORMAT_A8_UNORM,
    SDL_GPU_TEXTUREFORMAT_R8_UNORM,
    SDL_GPU_TEXTUREFORMAT_R8G8_UNORM,
    SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM,
    SDL_GPU_TEXTUREFORMAT_R16_UNORM,
    SDL_GPU_TEXTUREFORMAT_R16G16_UNORM,
    SDL_GPU_TEXTUREFORMAT_R16G16B16A16_UNORM,
    SDL_GPU_TEXTUREFORMAT_R10G10B10A2_UNORM,
    SDL_GPU_TEXTUREFORMAT_B5G6R5_UNORM,
    SDL_GPU_TEXTUREFORMAT_B5G5R5A1_UNORM,
    SDL_GPU_TEXTUREFORMAT_B4G4R4A4_UNORM,
    SDL_GPU_TEXTUREFORMAT_B8G8R8A8_UNORM,
    SDL_GPU_TEXTUREFORMAT_BC1_RGBA_UNORM,
    SDL_GPU_TEXTUREFORMAT_BC2_RGBA_UNORM,
    SDL_GPU_TEXTUREFORMAT_BC3_RGBA_UNORM,
    SDL_GPU_TEXTUREFORMAT_BC4_R_UNORM,
    SDL_GPU_TEXTUREFORMAT_BC5_RG_UNORM,
    SDL_GPU_TEXTUREFORMAT_BC7_RGBA_UNORM,
    SDL_GPU_TEXTUREFORMAT_BC6H_RGB_FLOAT,
    SDL_GPU_TEXTUREFORMAT_BC6H_RGB_UFLOAT,
    SDL_GPU_TEXTUREFORMAT_R8_SNORM,
    SDL_GPU_TEXTUREFORMAT_R8G8_SNORM,
    SDL_GPU_TEXTUREFORMAT_R8G8B8A8_SNORM,
    SDL_GPU_TEXTUREFORMAT_R16_SNORM,
    SDL_GPU_TEXTUREFORMAT_R16G16_SNORM,
    SDL_GPU_TEXTUREFORMAT_R16G16B16A16_SNORM,
    SDL_GPU_TEXTUREFORMAT_R16_FLOAT,
    SDL_GPU_TEXTUREFORMAT_R16G16_FLOAT,
    SDL_GPU_TEXTUREFORMAT_R16G16B16A16_FLOAT,
    SDL_GPU_TEXTUREFORMAT_R32_FLOAT,
    SDL_GPU_TEXTUREFORMAT_R32G32_FLOAT,
    SDL_GPU_TEXTUREFORMAT_R32G32B32A32_FLOAT,
    SDL_GPU_TEXTUREFORMAT_R11G11B10_UFLOAT,
    SDL_GPU_TEXTUREFORMAT_R8_UINT,
    SDL_GPU_TEXTUREFORMAT_R8G8_UINT,
    SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UINT,
    SDL_GPU_TEXTUREFORMAT_R16_UINT,
    SDL_GPU_TEXTUREFORMAT_R16G16_UINT,
    SDL_GPU_TEXTUREFORMAT_R16G16B16A16_UINT,
    SDL_GPU_TEXTUREFORMAT_R32_UINT,
    SDL_GPU_TEXTUREFORMAT_R32G32_UINT,
    SDL_GPU_TEXTUREFORMAT_R32G32B32A32_UINT,
    SDL_GPU_TEXTUREFORMAT_R8_INT,
    SDL_GPU_TEXTUREFORMAT_R8G8_INT,
    SDL_GPU_TEXTUREFORMAT_R8G8B8A8_INT,
    SDL_GPU_TEXTUREFORMAT_R16_INT,
    SDL_GPU_TEXTUREFORMAT_R16G16_INT,
    SDL_GPU_TEXTUREFORMAT_R16G16B16A16_INT,
    SDL_GPU_TEXTUREFORMAT_R32_INT,
    SDL_GPU_TEXTUREFORMAT_R32G32_INT,
    SDL_GPU_TEXTUREFORMAT_R32G32B32A32_INT,
    SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_B8G8R8A8_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_BC1_RGBA_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_BC2_RGBA_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_BC3_RGBA_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_BC7_RGBA_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_D16_UNORM,
    SDL_GPU_TEXTUREFORMAT_D24_UNORM,
    SDL_GPU_TEXTUREFORMAT_D32_FLOAT,
    SDL_GPU_TEXTUREFORMAT_D24_UNORM_S8_UINT,
    SDL_GPU_TEXTUREFORMAT_D32_FLOAT_S8_UINT,
    SDL_GPU_TEXTUREFORMAT_ASTC_4x4_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_5x4_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_5x5_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_6x5_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_6x6_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_8x5_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_8x6_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_8x8_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x5_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x6_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x8_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x10_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_12x10_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_12x12_UNORM,
    SDL_GPU_TEXTUREFORMAT_ASTC_4x4_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_5x4_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_5x5_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_6x5_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_6x6_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_8x5_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_8x6_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_8x8_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x5_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x6_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x8_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x10_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_12x10_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_12x12_UNORM_SRGB,
    SDL_GPU_TEXTUREFORMAT_ASTC_4x4_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_5x4_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_5x5_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_6x5_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_6x6_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_8x5_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_8x6_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_8x8_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x5_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x6_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x8_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_10x10_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_12x10_FLOAT,
    SDL_GPU_TEXTUREFORMAT_ASTC_12x12_FLOAT
} SDL_GPUTextureFormat;
typedef enum SDL_GPUVertexElementFormat
{
    SDL_GPU_VERTEXELEMENTFORMAT_INVALID,
    SDL_GPU_VERTEXELEMENTFORMAT_INT,
    SDL_GPU_VERTEXELEMENTFORMAT_INT2,
    SDL_GPU_VERTEXELEMENTFORMAT_INT3,
    SDL_GPU_VERTEXELEMENTFORMAT_INT4,
    SDL_GPU_VERTEXELEMENTFORMAT_UINT,
    SDL_GPU_VERTEXELEMENTFORMAT_UINT2,
    SDL_GPU_VERTEXELEMENTFORMAT_UINT3,
    SDL_GPU_VERTEXELEMENTFORMAT_UINT4,
    SDL_GPU_VERTEXELEMENTFORMAT_FLOAT,
    SDL_GPU_VERTEXELEMENTFORMAT_FLOAT2,
    SDL_GPU_VERTEXELEMENTFORMAT_FLOAT3,
    SDL_GPU_VERTEXELEMENTFORMAT_FLOAT4,
    SDL_GPU_VERTEXELEMENTFORMAT_BYTE2,
    SDL_GPU_VERTEXELEMENTFORMAT_BYTE4,
    SDL_GPU_VERTEXELEMENTFORMAT_UBYTE2,
    SDL_GPU_VERTEXELEMENTFORMAT_UBYTE4,
    SDL_GPU_VERTEXELEMENTFORMAT_BYTE2_NORM,
    SDL_GPU_VERTEXELEMENTFORMAT_BYTE4_NORM,
    SDL_GPU_VERTEXELEMENTFORMAT_UBYTE2_NORM,
    SDL_GPU_VERTEXELEMENTFORMAT_UBYTE4_NORM,
    SDL_GPU_VERTEXELEMENTFORMAT_SHORT2,
    SDL_GPU_VERTEXELEMENTFORMAT_SHORT4,
    SDL_GPU_VERTEXELEMENTFORMAT_USHORT2,
    SDL_GPU_VERTEXELEMENTFORMAT_USHORT4,
    SDL_GPU_VERTEXELEMENTFORMAT_SHORT2_NORM,
    SDL_GPU_VERTEXELEMENTFORMAT_SHORT4_NORM,
    SDL_GPU_VERTEXELEMENTFORMAT_USHORT2_NORM,
    SDL_GPU_VERTEXELEMENTFORMAT_USHORT4_NORM,
    SDL_GPU_VERTEXELEMENTFORMAT_HALF2,
    SDL_GPU_VERTEXELEMENTFORMAT_HALF4
} SDL_GPUVertexElementFormat;
typedef enum SDL_GPUPrimitiveType
{
    SDL_GPU_PRIMITIVETYPE_TRIANGLELIST,
    SDL_GPU_PRIMITIVETYPE_TRIANGLESTRIP,
    SDL_GPU_PRIMITIVETYPE_LINELIST,
    SDL_GPU_PRIMITIVETYPE_LINESTRIP,
    SDL_GPU_PRIMITIVETYPE_POINTLIST
} SDL_GPUPrimitiveType;
typedef enum SDL_GPUFillMode
{
    SDL_GPU_FILLMODE_FILL,
    SDL_GPU_FILLMODE_LINE
} SDL_GPUFillMode;
typedef enum SDL_GPUCullMode
{
    SDL_GPU_CULLMODE_NONE,
    SDL_GPU_CULLMODE_FRONT,
    SDL_GPU_CULLMODE_BACK
} SDL_GPUCullMode;
typedef enum SDL_GPUFrontFace
{
    SDL_GPU_FRONTFACE_COUNTER_CLOCKWISE,
    SDL_GPU_FRONTFACE_CLOCKWISE
} SDL_GPUFrontFace;
typedef enum SDL_GPUCompareOp
{
    SDL_GPU_COMPAREOP_INVALID,
    SDL_GPU_COMPAREOP_NEVER,
    SDL_GPU_COMPAREOP_LESS,
    SDL_GPU_COMPAREOP_EQUAL,
    SDL_GPU_COMPAREOP_LESS_OR_EQUAL,
    SDL_GPU_COMPAREOP_GREATER,
    SDL_GPU_COMPAREOP_NOT_EQUAL,
    SDL_GPU_COMPAREOP_GREATER_OR_EQUAL,
    SDL_GPU_COMPAREOP_ALWAYS
} SDL_GPUCompareOp;
typedef enum SDL_GPUStencilOp
{
    SDL_GPU_STENCILOP_INVALID,
    SDL_GPU_STENCILOP_KEEP,
    SDL_GPU_STENCILOP_ZERO,
    SDL_GPU_STENCILOP_REPLACE,
    SDL_GPU_STENCILOP_INCREMENT_AND_CLAMP,
    SDL_GPU_STENCILOP_DECREMENT_AND_CLAMP,
    SDL_GPU_STENCILOP_INVERT,
    SDL_GPU_STENCILOP_INCREMENT_AND_WRAP,
    SDL_GPU_STENCILOP_DECREMENT_AND_WRAP
} SDL_GPUStencilOp;
typedef enum SDL_GPUBlendOp
{
    SDL_GPU_BLENDOP_INVALID,
    SDL_GPU_BLENDOP_ADD,
    SDL_GPU_BLENDOP_SUBTRACT,
    SDL_GPU_BLENDOP_REVERSE_SUBTRACT,
    SDL_GPU_BLENDOP_MIN,
    SDL_GPU_BLENDOP_MAX
} SDL_GPUBlendOp;
typedef enum SDL_GPUBlendFactor
{
    SDL_GPU_BLENDFACTOR_INVALID,
    SDL_GPU_BLENDFACTOR_ZERO,
    SDL_GPU_BLENDFACTOR_ONE,
    SDL_GPU_BLENDFACTOR_SRC_COLOR,
    SDL_GPU_BLENDFACTOR_ONE_MINUS_SRC_COLOR,
    SDL_GPU_BLENDFACTOR_DST_COLOR,
    SDL_GPU_BLENDFACTOR_ONE_MINUS_DST_COLOR,
    SDL_GPU_BLENDFACTOR_SRC_ALPHA,
    SDL_GPU_BLENDFACTOR_ONE_MINUS_SRC_ALPHA,
    SDL_GPU_BLENDFACTOR_DST_ALPHA,
    SDL_GPU_BLENDFACTOR_ONE_MINUS_DST_ALPHA,
    SDL_GPU_BLENDFACTOR_CONSTANT_COLOR,
    SDL_GPU_BLENDFACTOR_ONE_MINUS_CONSTANT_COLOR,
    SDL_GPU_BLENDFACTOR_SRC_ALPHA_SATURATE
} SDL_GPUBlendFactor;
typedef enum SDL_GPUSampleCount
{
    SDL_GPU_SAMPLECOUNT_1,
    SDL_GPU_SAMPLECOUNT_2,
    SDL_GPU_SAMPLECOUNT_4,
    SDL_GPU_SAMPLECOUNT_8
} SDL_GPUSampleCount;
typedef enum SDL_GPUFilter
{
    SDL_GPU_FILTER_NEAREST,
    SDL_GPU_FILTER_LINEAR
} SDL_GPUFilter;
typedef enum SDL_GPUSamplerMipmapMode
{
    SDL_GPU_SAMPLERMIPMAPMODE_NEAREST,
    SDL_GPU_SAMPLERMIPMAPMODE_LINEAR
} SDL_GPUSamplerMipmapMode;
typedef enum SDL_GPUSamplerAddressMode
{
    SDL_GPU_SAMPLERADDRESSMODE_REPEAT,
    SDL_GPU_SAMPLERADDRESSMODE_MIRRORED_REPEAT,
    SDL_GPU_SAMPLERADDRESSMODE_CLAMP_TO_EDGE
} SDL_GPUSamplerAddressMode;
typedef enum SDL_GPUVertexInputRate
{
    SDL_GPU_VERTEXINPUTRATE_VERTEX,
    SDL_GPU_VERTEXINPUTRATE_INSTANCE
} SDL_GPUVertexInputRate;
typedef enum SDL_GPUShaderStage
{
    SDL_GPU_SHADERSTAGE_VERTEX,
    SDL_GPU_SHADERSTAGE_FRAGMENT
} SDL_GPUShaderStage;
typedef enum SDL_GPULoadOp
{
    SDL_GPU_LOADOP_LOAD,
    SDL_GPU_LOADOP_CLEAR,
    SDL_GPU_LOADOP_DONT_CARE
} SDL_GPULoadOp;
typedef enum SDL_GPUStoreOp
{
    SDL_GPU_STOREOP_STORE,
    SDL_GPU_STOREOP_DONT_CARE,
    SDL_GPU_STOREOP_RESOLVE,
    SDL_GPU_STOREOP_RESOLVE_AND_STORE
} SDL_GPUStoreOp;
typedef enum SDL_GPUIndexElementSize
{
    SDL_GPU_INDEXELEMENTSIZE_16BIT,
    SDL_GPU_INDEXELEMENTSIZE_32BIT
} SDL_GPUIndexElementSize;
typedef struct SDL_GPUSamplerCreateInfo
{
    SDL_GPUFilter min_filter;
    SDL_GPUFilter mag_filter;
    SDL_GPUSamplerMipmapMode mipmap_mode;
    SDL_GPUSamplerAddressMode address_mode_u;
    SDL_GPUSamplerAddressMode address_mode_v;
    SDL_GPUSamplerAddressMode address_mode_w;
    float mip_lod_bias;
    float max_anisotropy;
    SDL_GPUCompareOp compare_op;
    float min_lod;
    float max_lod;
    bool enable_anisotropy;
    bool enable_compare;
    Uint8 padding1;
    Uint8 padding2;
    SDL_PropertiesID props;
} SDL_GPUSamplerCreateInfo;
typedef struct SDL_GPUVertexBufferDescription
{
    Uint32 slot;
    Uint32 pitch;
    SDL_GPUVertexInputRate input_rate;
    Uint32 instance_step_rate;
} SDL_GPUVertexBufferDescription;
typedef struct SDL_GPUVertexAttribute
{
    Uint32 location;
    Uint32 buffer_slot;
    SDL_GPUVertexElementFormat format;
    Uint32 offset;
} SDL_GPUVertexAttribute;
typedef struct SDL_GPUVertexInputState
{
    const SDL_GPUVertexBufferDescription *vertex_buffer_descriptions;
    Uint32 num_vertex_buffers;
    const SDL_GPUVertexAttribute *vertex_attributes;
    Uint32 num_vertex_attributes;
} SDL_GPUVertexInputState;
typedef struct SDL_GPUStencilOpState
{
    SDL_GPUStencilOp fail_op;
    SDL_GPUStencilOp pass_op;
    SDL_GPUStencilOp depth_fail_op;
    SDL_GPUCompareOp compare_op;
} SDL_GPUStencilOpState;
typedef struct SDL_GPUColorTargetBlendState
{
    SDL_GPUBlendFactor src_color_blendfactor;
    SDL_GPUBlendFactor dst_color_blendfactor;
    SDL_GPUBlendOp color_blend_op;
    SDL_GPUBlendFactor src_alpha_blendfactor;
    SDL_GPUBlendFactor dst_alpha_blendfactor;
    SDL_GPUBlendOp alpha_blend_op;
    SDL_GPUColorComponentFlags color_write_mask;
    bool enable_blend;
    bool enable_color_write_mask;
    Uint8 padding1;
    Uint8 padding2;
} SDL_GPUColorTargetBlendState;
typedef struct SDL_GPUShaderCreateInfo
{
    size_t code_size;
    const Uint8 *code;
    const char *entrypoint;
    SDL_GPUShaderFormat format;
    SDL_GPUShaderStage stage;
    Uint32 num_samplers;
    Uint32 num_storage_textures;
    Uint32 num_storage_buffers;
    Uint32 num_uniform_buffers;
    SDL_PropertiesID props;
} SDL_GPUShaderCreateInfo;
typedef struct SDL_GPUTextureCreateInfo
{
    SDL_GPUTextureType type;
    SDL_GPUTextureFormat format;
    SDL_GPUTextureUsageFlags usage;
    Uint32 width;
    Uint32 height;
    Uint32 layer_count_or_depth;
    Uint32 num_levels;
    SDL_GPUSampleCount sample_count;
    SDL_PropertiesID props;
} SDL_GPUTextureCreateInfo;
typedef struct SDL_GPURasterizerState
{
    SDL_GPUFillMode fill_mode;
    SDL_GPUCullMode cull_mode;
    SDL_GPUFrontFace front_face;
    float depth_bias_constant_factor;
    float depth_bias_clamp;
    float depth_bias_slope_factor;
    bool enable_depth_bias;
    bool enable_depth_clip;
    Uint8 padding1;
    Uint8 padding2;
} SDL_GPURasterizerState;
typedef struct SDL_GPUMultisampleState
{
    SDL_GPUSampleCount sample_count;
    Uint32 sample_mask;
    bool enable_mask;
    bool enable_alpha_to_coverage;
    Uint8 padding2;
    Uint8 padding3;
} SDL_GPUMultisampleState;
typedef struct SDL_GPUDepthStencilState
{
    SDL_GPUCompareOp compare_op;
    SDL_GPUStencilOpState back_stencil_state;
    SDL_GPUStencilOpState front_stencil_state;
    Uint8 compare_mask;
    Uint8 write_mask;
    bool enable_depth_test;
    bool enable_depth_write;
    bool enable_stencil_test;
    Uint8 padding1;
    Uint8 padding2;
    Uint8 padding3;
} SDL_GPUDepthStencilState;
typedef struct SDL_GPUColorTargetDescription
{
    SDL_GPUTextureFormat format;
    SDL_GPUColorTargetBlendState blend_state;
} SDL_GPUColorTargetDescription;
typedef struct SDL_GPUGraphicsPipelineTargetInfo
{
    const SDL_GPUColorTargetDescription *color_target_descriptions;
    Uint32 num_color_targets;
    SDL_GPUTextureFormat depth_stencil_format;
    bool has_depth_stencil_target;
    Uint8 padding1;
    Uint8 padding2;
    Uint8 padding3;
} SDL_GPUGraphicsPipelineTargetInfo;
typedef struct SDL_GPUGraphicsPipelineCreateInfo
{
    SDL_GPUShader *vertex_shader;
    SDL_GPUShader *fragment_shader;
    SDL_GPUVertexInputState vertex_input_state;
    SDL_GPUPrimitiveType primitive_type;
    SDL_GPURasterizerState rasterizer_state;
    SDL_GPUMultisampleState multisample_state;
    SDL_GPUDepthStencilState depth_stencil_state;
    SDL_GPUGraphicsPipelineTargetInfo target_info;
    SDL_PropertiesID props;
} SDL_GPUGraphicsPipelineCreateInfo;
typedef struct SDL_GPUColorTargetInfo
{
    SDL_GPUTexture *texture;
    Uint32 mip_level;
    Uint32 layer_or_depth_plane;
    SDL_FColor clear_color;
    SDL_GPULoadOp load_op;
    SDL_GPUStoreOp store_op;
    SDL_GPUTexture *resolve_texture;
    Uint32 resolve_mip_level;
    Uint32 resolve_layer;
    bool cycle;
    bool cycle_resolve_texture;
    Uint8 padding1;
    Uint8 padding2;
} SDL_GPUColorTargetInfo;
typedef struct SDL_GPUDepthStencilTargetInfo
{
    SDL_GPUTexture *texture;
    float clear_depth;
    SDL_GPULoadOp load_op;
    SDL_GPUStoreOp store_op;
    SDL_GPULoadOp stencil_load_op;
    SDL_GPUStoreOp stencil_store_op;
    bool cycle;
    Uint8 clear_stencil;
    Uint8 mip_level;
    Uint8 layer;
} SDL_GPUDepthStencilTargetInfo;
typedef struct SDL_GPUBufferBinding
{
    SDL_GPUBuffer *buffer;
    Uint32 offset;
} SDL_GPUBufferBinding;
typedef struct SDL_GPUTextureSamplerBinding
{
    SDL_GPUTexture *texture;
    SDL_GPUSampler *sampler;
} SDL_GPUTextureSamplerBinding;
typedef struct SDL_GPUTextureTransferInfo
{
    SDL_GPUTransferBuffer *transfer_buffer;
    Uint32 offset;
    Uint32 pixels_per_row;
    Uint32 rows_per_layer;
} SDL_GPUTextureTransferInfo;
typedef struct SDL_GPUTextureRegion
{
    SDL_GPUTexture *texture;
    Uint32 mip_level;
    Uint32 layer;
    Uint32 x;
    Uint32 y;
    Uint32 z;
    Uint32 w;
    Uint32 h;
    Uint32 d;
} SDL_GPUTextureRegion;
typedef struct SDL_GPUViewport
{
    float x;
    float y;
    float w;
    float h;
    float min_depth;
    float max_depth;
} SDL_GPUViewport;
SDL_GPUTexture * SDL_CreateGPUTexture(
    SDL_GPUDevice *device,
    const SDL_GPUTextureCreateInfo *createinfo);
void SDL_ReleaseGPUTexture(
    SDL_GPUDevice *device,
    SDL_GPUTexture *texture);
bool SDL_GPUTextureSupportsFormat(
    SDL_GPUDevice *device,
    SDL_GPUTextureFormat format,
    SDL_GPUTextureType type,
    SDL_GPUTextureUsageFlags usage);
SDL_GPUSampler * SDL_CreateGPUSampler(
    SDL_GPUDevice *device,
    const SDL_GPUSamplerCreateInfo *createinfo);
void SDL_ReleaseGPUSampler(
    SDL_GPUDevice *device,
    SDL_GPUSampler *sampler);
SDL_GPUShader * SDL_CreateGPUShader(
    SDL_GPUDevice *device,
    const SDL_GPUShaderCreateInfo *createinfo);
void SDL_ReleaseGPUShader(
    SDL_GPUDevice *device,
    SDL_GPUShader *shader);
SDL_GPUGraphicsPipeline * SDL_CreateGPUGraphicsPipeline(
    SDL_GPUDevice *device,
    const SDL_GPUGraphicsPipelineCreateInfo *createinfo);
void SDL_ReleaseGPUGraphicsPipeline(
    SDL_GPUDevice *device,
    SDL_GPUGraphicsPipeline *graphics_pipeline);
void SDL_UploadToGPUTexture(
    SDL_GPUCopyPass *copy_pass,
    const SDL_GPUTextureTransferInfo *source,
    const SDL_GPUTextureRegion *destination,
    bool cycle);
void SDL_DownloadFromGPUTexture(
    SDL_GPUCopyPass *copy_pass,
    const SDL_GPUTextureRegion *source,
    const SDL_GPUTextureTransferInfo *destination);
void SDL_GenerateMipmapsForGPUTexture(
    SDL_GPUCommandBuffer *command_buffer,
    SDL_GPUTexture *texture);
SDL_GPURenderPass * SDL_BeginGPURenderPass(
    SDL_GPUCommandBuffer *command_buffer,
    const SDL_GPUColorTargetInfo *color_target_infos,
    Uint32 num_color_targets,
    const SDL_GPUDepthStencilTargetInfo *depth_stencil_target_info);
void SDL_EndGPURenderPass(
    SDL_GPURenderPass *render_pass);
void SDL_BindGPUGraphicsPipeline(
    SDL_GPURenderPass *render_pass,
    SDL_GPUGraphicsPipeline *graphics_pipeline);
void SDL_BindGPUVertexBuffers(
    SDL_GPURenderPass *render_pass,
    Uint32 first_slot,
    const SDL_GPUBufferBinding *bindings,
    Uint32 num_bindings);
void SDL_BindGPUIndexBuffer(
    SDL_GPURenderPass *render_pass,
    const SDL_GPUBufferBinding *binding,
    SDL_GPUIndexElementSize index_element_size);
void SDL_BindGPUVertexSamplers(
    SDL_GPURenderPass *render_pass,
    Uint32 first_slot,
    const SDL_GPUTextureSamplerBinding *texture_sampler_bindings,
    Uint32 num_bindings);
void SDL_BindGPUFragmentSamplers(
    SDL_GPURenderPass *render_pass,
    Uint32 first_slot,
    const SDL_GPUTextureSamplerBinding *texture_sampler_bindings,
    Uint32 num_bindings);
void SDL_PushGPUVertexUniformData(
    SDL_GPUCommandBuffer *command_buffer,
    Uint32 slot_index,
    const void *data,
    Uint32 length);
void SDL_PushGPUFragmentUniformData(
    SDL_GPUCommandBuffer *command_buffer,
    Uint32 slot_index,
    const void *data,
    Uint32 length);
void SDL_DrawGPUPrimitives(
    SDL_GPURenderPass *render_pass,
    Uint32 num_vertices,
    Uint32 num_instances,
    Uint32 first_vertex,
    Uint32 first_instance);
void SDL_DrawGPUIndexedPrimitives(
    SDL_GPURenderPass *render_pass,
    Uint32 num_indices,
    Uint32 num_instances,
    Uint32 first_index,
    Sint32 vertex_offset,
    Uint32 first_instance);
void SDL_SetGPUViewport(
    SDL_GPURenderPass *render_pass,
    const SDL_GPUViewport *viewport);
void SDL_SetGPUScissor(
    SDL_GPURenderPass *render_pass,
    const SDL_Rect *scissor);
#endif
_Static_assert(sizeof(SDL_GPUSamplerCreateInfo) == 52 && _Alignof(SDL_GPUSamplerCreateInfo) == 4, "SDL_GPUSamplerCreateInfo ABI");
_Static_assert(sizeof(SDL_GPUVertexBufferDescription) == 16 && _Alignof(SDL_GPUVertexBufferDescription) == 4, "SDL_GPUVertexBufferDescription ABI");
_Static_assert(sizeof(SDL_GPUVertexAttribute) == 16 && _Alignof(SDL_GPUVertexAttribute) == 4, "SDL_GPUVertexAttribute ABI");
_Static_assert(sizeof(SDL_GPUVertexInputState) == 32 && _Alignof(SDL_GPUVertexInputState) == 8, "SDL_GPUVertexInputState ABI");
_Static_assert(sizeof(SDL_GPUStencilOpState) == 16 && _Alignof(SDL_GPUStencilOpState) == 4, "SDL_GPUStencilOpState ABI");
_Static_assert(sizeof(SDL_GPUColorTargetBlendState) == 32 && _Alignof(SDL_GPUColorTargetBlendState) == 4, "SDL_GPUColorTargetBlendState ABI");
_Static_assert(sizeof(SDL_GPUShaderCreateInfo) == 56 && _Alignof(SDL_GPUShaderCreateInfo) == 8, "SDL_GPUShaderCreateInfo ABI");
_Static_assert(sizeof(SDL_GPUTextureCreateInfo) == 36 && _Alignof(SDL_GPUTextureCreateInfo) == 4, "SDL_GPUTextureCreateInfo ABI");
_Static_assert(sizeof(SDL_GPURasterizerState) == 28 && _Alignof(SDL_GPURasterizerState) == 4, "SDL_GPURasterizerState ABI");
_Static_assert(sizeof(SDL_GPUMultisampleState) == 12 && _Alignof(SDL_GPUMultisampleState) == 4, "SDL_GPUMultisampleState ABI");
_Static_assert(sizeof(SDL_GPUDepthStencilState) == 44 && _Alignof(SDL_GPUDepthStencilState) == 4, "SDL_GPUDepthStencilState ABI");
_Static_assert(sizeof(SDL_GPUColorTargetDescription) == 36 && _Alignof(SDL_GPUColorTargetDescription) == 4, "SDL_GPUColorTargetDescription ABI");
_Static_assert(sizeof(SDL_GPUGraphicsPipelineTargetInfo) == 24 && _Alignof(SDL_GPUGraphicsPipelineTargetInfo) == 8, "SDL_GPUGraphicsPipelineTargetInfo ABI");
_Static_assert(sizeof(SDL_GPUGraphicsPipelineCreateInfo) == 168 && _Alignof(SDL_GPUGraphicsPipelineCreateInfo) == 8, "SDL_GPUGraphicsPipelineCreateInfo ABI");
_Static_assert(sizeof(SDL_GPUColorTargetInfo) == 64 && _Alignof(SDL_GPUColorTargetInfo) == 8, "SDL_GPUColorTargetInfo ABI");
_Static_assert(sizeof(SDL_GPUDepthStencilTargetInfo) == 32 && _Alignof(SDL_GPUDepthStencilTargetInfo) == 8, "SDL_GPUDepthStencilTargetInfo ABI");
_Static_assert(sizeof(SDL_GPUBufferBinding) == 16 && _Alignof(SDL_GPUBufferBinding) == 8, "SDL_GPUBufferBinding ABI");
_Static_assert(sizeof(SDL_GPUTextureSamplerBinding) == 16 && _Alignof(SDL_GPUTextureSamplerBinding) == 8, "SDL_GPUTextureSamplerBinding ABI");
_Static_assert(sizeof(SDL_GPUTextureTransferInfo) == 24 && _Alignof(SDL_GPUTextureTransferInfo) == 8, "SDL_GPUTextureTransferInfo ABI");
_Static_assert(sizeof(SDL_GPUTextureRegion) == 40 && _Alignof(SDL_GPUTextureRegion) == 8, "SDL_GPUTextureRegion ABI");
_Static_assert(sizeof(SDL_GPUViewport) == 24 && _Alignof(SDL_GPUViewport) == 4, "SDL_GPUViewport ABI");
#endif
