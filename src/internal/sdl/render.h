/* Resource ownership and command recording for the portable graphics path.
 * Internal metadata spans are synchronous; no Xu pointer is retained. */
#define RENDER_FUNCTIONS(X) \
 X(SDL_CreateGPUTexture) X(SDL_ReleaseGPUTexture) X(SDL_GPUTextureSupportsFormat) \
 X(SDL_CreateGPUSampler) X(SDL_ReleaseGPUSampler) X(SDL_CreateGPUShader) X(SDL_ReleaseGPUShader) \
 X(SDL_CreateGPUGraphicsPipeline) X(SDL_ReleaseGPUGraphicsPipeline) \
 X(SDL_UploadToGPUTexture) X(SDL_DownloadFromGPUTexture) X(SDL_GenerateMipmapsForGPUTexture) \
 X(SDL_BeginGPURenderPass) X(SDL_EndGPURenderPass) X(SDL_BindGPUGraphicsPipeline) \
 X(SDL_BindGPUVertexBuffers) X(SDL_BindGPUIndexBuffer) X(SDL_BindGPUVertexSamplers) X(SDL_BindGPUFragmentSamplers) \
 X(SDL_PushGPUVertexUniformData) X(SDL_PushGPUFragmentUniformData) \
 X(SDL_DrawGPUPrimitives) X(SDL_DrawGPUIndexedPrimitives) X(SDL_SetGPUViewport) X(SDL_SetGPUScissor)
RENDER_FUNCTIONS(DECLARE)
static bool render_loaded;
static bool load_render(void) {
    if (render_loaded) return true;
#ifdef _WIN32
#define RENDER_FIND(name) GetProcAddress(sdl_library, #name)
#else
#define RENDER_FIND(name) dlsym(sdl_library, #name)
#endif
#define RENDER_LOAD(name) p_##name = (__typeof__(name) *)RENDER_FIND(name); \
 if (!p_##name) { fail("SDL GPU runtime is missing " #name); return false; }
    RENDER_FUNCTIONS(RENDER_LOAD)
    render_loaded = true;
    return true;
}
#define COMPUTE_FUNCTIONS(X) \
 X(SDL_CreateGPUComputePipeline) X(SDL_ReleaseGPUComputePipeline) X(SDL_BeginGPUComputePass) X(SDL_EndGPUComputePass) \
 X(SDL_BindGPUComputePipeline) X(SDL_BindGPUComputeStorageBuffers) X(SDL_PushGPUComputeUniformData) X(SDL_DispatchGPUCompute)
COMPUTE_FUNCTIONS(DECLARE)
#define SURFACE_FUNCTIONS(X) \
 X(SDL_ClaimWindowForGPUDevice) X(SDL_ReleaseWindowFromGPUDevice) X(SDL_WindowSupportsGPUPresentMode) \
 X(SDL_SetGPUSwapchainParameters) X(SDL_GetGPUSwapchainTextureFormat) X(SDL_WaitAndAcquireGPUSwapchainTexture)
SURFACE_FUNCTIONS(DECLARE)
struct Surface { xu_int id, frame; Device *owner; WindowRecord *window; int format; struct Surface *next; };
enum { TEXTURE = 1, SAMPLER, SHADER, PIPELINE, COMPUTE_PIPELINE };
/* These are SDL portable limits, not engine budgets (SDL_gpu.c/sysgpu.h).
 * All backends share 16 vertex inputs, 16 samplers and 4 uniform slots. */
enum { VERTEX_SLOTS = 16, SAMPLER_SLOTS = 16, UNIFORM_SLOTS = 4, MAX_TEXTURE_2D = 16384 };
typedef struct { Uint32 samplers, count, sizes[UNIFORM_SLOTS]; } Bindings;
struct Resource {
    xu_int id, bytes;
    int kind;
    xu_uint refs;
    bool closed;
    void *gpu;
    Uint32 width, height, levels, usage;
    xu_int mip_bytes[15];
    int format, stage;
    Bindings bindings[2];
    SDL_GPUVertexBufferDescription vertices[VERTEX_SLOTS];
    Uint32 vertex_count;
    int color_format, depth_format;
    Uint32 read_buffers, write_buffers;
    struct Resource *next;
};
typedef struct Ref { void *pointer; bool buffer; struct Ref *next; } Ref;
struct Encoder {
    xu_int id, pass_id;
    SDL_GPUCommandBuffer *command;
    SDL_GPURenderPass *pass;
    SDL_GPUComputePass *compute;
    Surface *surface;
    Resource present_target;
    unsigned present_passes;
    Ref *refs;
    Resource *color, *depth, *pipeline;
    Uint32 width, height;
    Buffer *vertices[VERTEX_SLOTS], *index;
    Uint32 offsets[VERTEX_SLOTS], index_offset, index_size;
    unsigned samplers[2], uniforms[2];
    Buffer *writes[8];
    Uint32 write_count;
    unsigned compute_reads;
    struct Encoder *next;
};
static Resource *resource(Device *d, xu_int id, int kind) {
    for (Resource *r = d->resources; r; r = r->next)
        if (r->id == id && r->kind == kind && !r->closed) return r;
    fail("closed, foreign or invalid GPU graphics resource"); return NULL;
}
static Resource *allocate_resource(int kind) {
    Resource *r = calloc(1, sizeof(*r));
    if (!r) { fail("GPU resource allocation failed"); return NULL; }
    r->id = identifier(); r->kind = kind;
    if (r->id < 0) { free(r); return NULL; }
    return r;
}
static xu_int add_resource(Device *d, Resource *r) { r->next = d->resources; d->resources = r; return r->id; }
static void free_resource(Device *d, Resource *r) {
    if (r->gpu) {
        if (r->kind == TEXTURE) p_SDL_ReleaseGPUTexture(d->gpu, r->gpu);
        else if (r->kind == SAMPLER) p_SDL_ReleaseGPUSampler(d->gpu, r->gpu);
        else if (r->kind == SHADER) p_SDL_ReleaseGPUShader(d->gpu, r->gpu);
        else if (r->kind == PIPELINE) p_SDL_ReleaseGPUGraphicsPipeline(d->gpu, r->gpu);
        else p_SDL_ReleaseGPUComputePipeline(d->gpu, r->gpu);
    }
    free(r);
}
static void collect_resources(Device *d) {
    Resource **r = &d->resources;
    while (*r) {
        if ((*r)->closed && !(*r)->refs) { Resource *old = *r; *r = old->next; free_resource(d, old); }
        else r = &(*r)->next;
    }
    Buffer **b = &d->buffers;
    while (*b) {
        if ((*b)->closed && !(*b)->refs) {
            Buffer *old = *b; *b = old->next; p_SDL_ReleaseGPUBuffer(d->gpu, old->gpu); free(old);
        } else b = &(*b)->next;
    }
}
static bool retain(Encoder *e, void *pointer, bool is_buffer) {
    for (Ref *r = e->refs; r; r = r->next) if (r->pointer == pointer && r->buffer == is_buffer) return true;
    Ref *r = malloc(sizeof(*r));
    if (!r) { fail("GPU command resource retention failed"); return false; }
    *r = (Ref){pointer, is_buffer, e->refs}; e->refs = r;
    if (is_buffer) ++((Buffer *)pointer)->refs; else ++((Resource *)pointer)->refs;
    return true;
}
static Encoder *encoder(Device *d, xu_int id, bool is_pass) {
    for (Encoder *e = d->encoders; e; e = e->next)
        if (is_pass ? (e->pass && e->pass_id == id) : e->id == id) return e;
    fail(is_pass ? "closed or invalid GPU render pass" : "closed or invalid GPU command encoder"); return NULL;
}
static bool abandon_surface(Encoder *e);
static void surface_encoder_released(Encoder *e);
static bool free_encoder(Device *d, Encoder *e, bool cancel) {
    bool ok = true;
    if (e->pass) { p_SDL_EndGPURenderPass(e->pass); e->pass=NULL; }
    if (e->compute) { p_SDL_EndGPUComputePass(e->compute); e->compute=NULL; }
    if (cancel) {
        if (e->surface) ok=abandon_surface(e);
        else if (!p_SDL_CancelGPUCommandBuffer(e->command)) { sdl_fail(); ok=false; }
    }
    while (e->refs) {
        Ref *r = e->refs; e->refs = r->next;
        if (r->buffer) --((Buffer *)r->pointer)->refs; else --((Resource *)r->pointer)->refs;
        free(r);
    }
    Encoder **link = &d->encoders;
    while (*link && *link != e) link = &(*link)->next;
    if (*link) *link = e->next;
    if (e->surface) surface_encoder_released(e);
    free(e); collect_resources(d);
    return ok;
}
static bool close_graphics(Device *d) {
    bool ok=true; char first[1024];
    while (d->encoders) if (!free_encoder(d,d->encoders,true)) retain_error(&ok,first);
    while (d->resources) { Resource *r=d->resources; d->resources=r->next; free_resource(d,r); }
    return cleanup_result(ok,first);
}
static xu_int graphics_stats(Device *d, xu_int field) {
    if (field < 4 || field > 14) return fail("invalid GPU accounting field");
    xu_int total = 0;
    for (Resource *r = d->resources; r; r = r->next) {
        xu_int add = 0;
        if (!r->closed) {
            if (field == 4 && r->kind == TEXTURE) add = 1;
            if (field == 5 && r->kind == TEXTURE) add = r->bytes;
            if (field >= 6 && field <= 8 && r->kind == field - 4) add = 1;
            if (field == 11 && r->kind == COMPUTE_PIPELINE) add = 1;
        }
        if (add > LLONG_MAX - total) return fail("GPU accounting overflow");
        total += add;
    }
    for (Encoder *e = d->encoders; e; e = e->next)
        if (field == 9 || (field == 10 && e->pass) || (field == 12 && e->compute) || (field == 14 && e->surface)) ++total;
    if (field==13) for (Surface *s=d->surfaces; s; s=s->next) ++total;
    return total;
}
xu_int API(resource_close)(xu_int owner, xu_int id) {
    if (!on_main()) return -1;
    Device *d = devices; while (d && d->id != owner) d = d->next;
    if (!d) return 0;
    for (Resource *r = d->resources; r; r = r->next) if (r->id == id) { r->closed = true; break; }
    collect_resources(d); return 0;
}
static SDL_GPUTextureFormat texture_format(xu_int format) {
    static const SDL_GPUTextureFormat formats[] = {SDL_GPU_TEXTUREFORMAT_INVALID,
        SDL_GPU_TEXTUREFORMAT_R8_UNORM, SDL_GPU_TEXTUREFORMAT_R8G8_UNORM,
        SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM, SDL_GPU_TEXTUREFORMAT_R8G8B8A8_UNORM_SRGB,
        SDL_GPU_TEXTUREFORMAT_B8G8R8A8_UNORM, SDL_GPU_TEXTUREFORMAT_B8G8R8A8_UNORM_SRGB,
        SDL_GPU_TEXTUREFORMAT_R16_FLOAT, SDL_GPU_TEXTUREFORMAT_R16G16_FLOAT, SDL_GPU_TEXTUREFORMAT_R16G16B16A16_FLOAT,
        SDL_GPU_TEXTUREFORMAT_R32_FLOAT, SDL_GPU_TEXTUREFORMAT_R32G32_FLOAT, SDL_GPU_TEXTUREFORMAT_R32G32B32A32_FLOAT,
        SDL_GPU_TEXTUREFORMAT_D32_FLOAT, SDL_GPU_TEXTUREFORMAT_BC1_RGBA_UNORM, SDL_GPU_TEXTUREFORMAT_BC1_RGBA_UNORM_SRGB,
        SDL_GPU_TEXTUREFORMAT_BC3_RGBA_UNORM, SDL_GPU_TEXTUREFORMAT_BC3_RGBA_UNORM_SRGB,
        SDL_GPU_TEXTUREFORMAT_BC5_RG_UNORM, SDL_GPU_TEXTUREFORMAT_BC7_RGBA_UNORM, SDL_GPU_TEXTUREFORMAT_BC7_RGBA_UNORM_SRGB};
    return format >= 1 && format <= 20 ? formats[format] : SDL_GPU_TEXTUREFORMAT_INVALID;
}
static bool texture_usage(xu_int format, xu_int usage) {
    if (!texture_format(format) || usage < 1 || usage > 7) return false;
    if (format == 13) return (usage & 2) == 0;
    if (usage & 4) return false;
    return format < 14 || usage == 1;
}
xu_int API(texture_supports)(xu_int owner, xu_int format, xu_int usage) {
    Device *d = device(owner); if (!d || !load_render()) return -1;
    if (!texture_usage(format, usage)) return fail("invalid GPU texture format or usage combination");
    return p_SDL_GPUTextureSupportsFormat(d->gpu, texture_format(format), SDL_GPU_TEXTURETYPE_2D, (Uint32)usage) ? 1 : 0;
}
/* desc: format, width, height, mip count, usage, logical bytes. */
xu_int API(texture_new)(xu_int owner, const xu_i64_span *desc) {
    Device *d = device(owner); if (!d || !load_render()) return -1;
    if (!desc || desc->len < 7 || !desc->data) return fail("invalid GPU texture descriptor");
    const xu_int *v = desc->data;
    if (!texture_usage(v[0], v[4]) || v[1] < 1 || v[1] > MAX_TEXTURE_2D || v[2] < 1 || v[2] > MAX_TEXTURE_2D || v[5] < 1)
        return fail("invalid GPU texture size, format or usage");
    Uint32 max_levels = 1, size = (Uint32)(v[1] > v[2] ? v[1] : v[2]);
    while (size > 1) { size /= 2; ++max_levels; }
    if (v[3] < 1 || v[3] > max_levels || desc->len != 6 + v[3] || (v[0] == 13 && v[3] != 1)) return fail("invalid GPU texture mip count");
    if (!p_SDL_GPUTextureSupportsFormat(d->gpu, texture_format(v[0]), SDL_GPU_TEXTURETYPE_2D, (Uint32)v[4]))
        return fail("GPU texture format is unsupported for this usage on the selected device");
    Resource *r = allocate_resource(TEXTURE); if (!r) return -1;
    r->format = (int)v[0]; r->width = (Uint32)v[1]; r->height = (Uint32)v[2];
    for (xu_int i = 0; i < v[3]; ++i) {
        if (v[6 + i] < 1 || v[6 + i] > v[5]) { free(r); return fail("invalid GPU mip byte size"); }
        r->mip_bytes[i] = v[6 + i];
    }
    r->levels = (Uint32)v[3]; r->usage = (Uint32)v[4]; r->bytes = v[5];
    SDL_GPUTextureCreateInfo info = {SDL_GPU_TEXTURETYPE_2D, texture_format(v[0]), r->usage,
        r->width, r->height, 1, r->levels, SDL_GPU_SAMPLECOUNT_1, 0};
    r->gpu = p_SDL_CreateGPUTexture(d->gpu, &info);
    if (!r->gpu) { sdl_fail(); free(r); return -1; }
    return add_resource(d, r);
}
static Uint32 mip_extent(Uint32 size, Uint32 level) { size >>= level; return size ? size : 1; }
/* The Xu layout layer supplies tight complete mip bytes. SDL accepts zero
 * row/layer strides for tight storage, including block compressed formats. */
static xu_int texture_transfer(Device *d, Resource *r, xu_int level, xu_int size, const xu_u8_span *input) {
    if (level < 0 || level >= r->levels || size < 1 || size > UINT32_MAX || size != r->mip_bytes[level] || r->format == 13)
        return fail("invalid GPU texture transfer mip, size or depth format");
    Transfer *t = new_transfer(d, (Uint32)size, true, input == NULL); if (!t) return -1;
    if (input) {
        void *mapped = p_SDL_MapGPUTransferBuffer(d->gpu, t->staging, false);
        if (!mapped) { sdl_fail(); free_transfer(d, t); return -1; }
        memcpy(mapped, input->data, (size_t)size); p_SDL_UnmapGPUTransferBuffer(d->gpu, t->staging);
    }
    SDL_GPUCommandBuffer *command;
    SDL_GPUCopyPass *copy = begin_copy(d, t, &command); if (!copy) return -1;
    SDL_GPUTextureTransferInfo data = {t->staging, 0, 0, 0};
    SDL_GPUTextureRegion region = {r->gpu, (Uint32)level, 0, 0, 0, 0,
        mip_extent(r->width, (Uint32)level), mip_extent(r->height, (Uint32)level), 1};
    if (input) p_SDL_UploadToGPUTexture(copy, &data, &region, false);
    else p_SDL_DownloadFromGPUTexture(copy, &region, &data);
    return submit(d, t, command, copy);
}
xu_int API(texture_upload)(xu_int owner, xu_int id, xu_int level, const xu_u8_span *input) {
    Device *d = device(owner); if (!d) return -1;
    Resource *r = resource(d, id, TEXTURE); if (!r) return -1;
    if (!input || input->len < 1 || !input->data) return fail("invalid GPU texture upload bytes");
    return texture_transfer(d, r, level, input->len, input);
}
xu_int API(texture_download)(xu_int owner, xu_int id, xu_int level, xu_int size) {
    Device *d = device(owner); if (!d) return -1;
    Resource *r = resource(d, id, TEXTURE); return r ? texture_transfer(d, r, level, size, NULL) : -1;
}
xu_int API(texture_mips)(xu_int owner, xu_int id) {
    Device *d = device(owner); if (!d) return -1;
    Resource *r = resource(d, id, TEXTURE); if (!r) return -1;
    if (r->levels < 2 || (r->usage & 3) != 3 || r->format == 13 || r->format >= 14)
        return fail("GPU mip generation requires an uncompressed sampled color target with multiple levels");
    Transfer *t = new_transfer(d, 0, false, false); if (!t) return -1;
    SDL_GPUCommandBuffer *command = p_SDL_AcquireGPUCommandBuffer(d->gpu);
    if (!command) { sdl_fail(); free_transfer(d, t); return -1; }
    p_SDL_GenerateMipmapsForGPUTexture(command, r->gpu);
    t->fence = p_SDL_SubmitGPUCommandBufferAndAcquireFence(command);
    if (!t->fence) { sdl_fail(); free_transfer(d, t); return -1; }
    t->next = d->transfers; d->transfers = t; return t->id;
}
xu_int API(sampler_new)(xu_int owner, const xu_i64_span *desc, double min_lod, double max_lod) {
    Device *d = device(owner); if (!d || !load_render()) return -1;
    if (!desc || desc->len != 6 || !desc->data || !isfinite(min_lod) || !isfinite(max_lod) || min_lod < 0 || max_lod < min_lod || max_lod > 1000)
        return fail("invalid GPU sampler descriptor or LOD range");
    for (int i = 0; i < 6; ++i) if (desc->data[i] < 0 || desc->data[i] > (i < 3 ? 1 : 2)) return fail("invalid GPU sampler filter or address mode");
    Resource *r = allocate_resource(SAMPLER); if (!r) return -1;
    SDL_GPUSamplerCreateInfo info = {0};
    info.min_filter = (SDL_GPUFilter)desc->data[0]; info.mag_filter = (SDL_GPUFilter)desc->data[1];
    info.mipmap_mode = (SDL_GPUSamplerMipmapMode)desc->data[2];
    info.address_mode_u = (SDL_GPUSamplerAddressMode)desc->data[3]; info.address_mode_v = (SDL_GPUSamplerAddressMode)desc->data[4];
    info.address_mode_w = (SDL_GPUSamplerAddressMode)desc->data[5]; info.min_lod = (float)min_lod; info.max_lod = (float)max_lod;
    r->gpu = p_SDL_CreateGPUSampler(d->gpu, &info);
    if (!r->gpu) { sdl_fail(); free(r); return -1; }
    return add_resource(d, r);
}
typedef struct { char *name; unsigned char *text; const unsigned char *bytes; } ShaderSource;
static void free_shader_source(ShaderSource *source) { free(source->name); free(source->text); }
static bool prepare_shader_source(xu_int owner, xu_int format, const xu_i64_span *sizes,
                                  const xu_u8_span *entry, const xu_u8_span *code, ShaderSource *source) {
    if (format < 1 || format > 16 || (format & (format - 1)) || !(format & API(shader_formats)(owner)) ||
        !sizes || sizes->len < 0 || sizes->len > UNIFORM_SLOTS || (sizes->len && !sizes->data) ||
        !entry || entry->len < 1 || entry->len > 1024 || !entry->data ||
        !code || code->len < 1 || code->len > UINT32_MAX || !code->data) {
        fail("invalid GPU shader format, bindings, entrypoint or code"); return false;
    }
    for (xu_int i = 0; i < entry->len; ++i) if (!entry->data[i]) { fail("GPU shader entrypoint contains NUL"); return false; }
    for (xu_int i = 0; i < sizes->len; ++i) if (sizes->data[i] < 16 || sizes->data[i] > 16384 || sizes->data[i] % 16) {
        fail("GPU uniform size must be 16-byte aligned and in 16...16384"); return false;
    }
    if ((format == 1 && (code->len < 20 || code->len % 4 || memcmp(code->data, "\x03\x02\x23\x07", 4))) ||
        ((format == 2 || format == 4) && (code->len < 32 || memcmp(code->data, "DXBC", 4))) ||
        (format == 16 && (code->len < 16 || memcmp(code->data, "MTLB", 4)))) {
        fail("invalid GPU shader container"); return false;
    }
    if (format == 8 && memchr(code->data, 0, (size_t)code->len)) { fail("MSL source must not contain NUL"); return false; }
    source->name = calloc((size_t)entry->len + 1, 1);
    source->text = format == 8 ? calloc((size_t)code->len + 1, 1) : NULL;
    if (!source->name || (format == 8 && !source->text)) {
        free_shader_source(source); fail("GPU shader source allocation failed"); return false;
    }
    memcpy(source->name, entry->data, (size_t)entry->len);
    if (source->text) memcpy(source->text, code->data, (size_t)code->len);
    source->bytes = source->text ? source->text : code->data;
    return true;
}
xu_int API(shader_new)(xu_int owner, xu_int stage, xu_int format, xu_int samplers, const xu_i64_span *sizes,
                        const xu_u8_span *entry, const xu_u8_span *code) {
    Device *d = device(owner); if (!d || !load_render()) return -1;
    if (stage < 0 || stage > 1 || samplers < 0 || samplers > SAMPLER_SLOTS) return fail("invalid GPU shader stage or sampler count");
    ShaderSource source = {0};
    if (!prepare_shader_source(owner, format, sizes, entry, code, &source)) return -1;
    Resource *r = allocate_resource(SHADER);
    if (!r) { free_shader_source(&source); return -1; }
    r->stage = (int)stage; r->bindings[stage].samplers = (Uint32)samplers; r->bindings[stage].count = (Uint32)sizes->len;
    for (xu_int i = 0; i < sizes->len; ++i) r->bindings[stage].sizes[i] = (Uint32)sizes->data[i];
    SDL_GPUShaderCreateInfo info = {(size_t)code->len, source.bytes, source.name,
        (Uint32)format << 1, (SDL_GPUShaderStage)stage, (Uint32)samplers, 0, 0, (Uint32)sizes->len, 0};
    r->gpu = p_SDL_CreateGPUShader(d->gpu, &info); free_shader_source(&source);
    if (!r->gpu) { sdl_fail(); free(r); return -1; }
    return add_resource(d, r);
}
/* Public vertex formats are independent IDs, translated here. */
static SDL_GPUVertexElementFormat vertex_format(xu_int format, Uint32 *size) {
    static const SDL_GPUVertexElementFormat formats[] = {SDL_GPU_VERTEXELEMENTFORMAT_INVALID,
        SDL_GPU_VERTEXELEMENTFORMAT_FLOAT, SDL_GPU_VERTEXELEMENTFORMAT_FLOAT2, SDL_GPU_VERTEXELEMENTFORMAT_FLOAT3,
        SDL_GPU_VERTEXELEMENTFORMAT_FLOAT4, SDL_GPU_VERTEXELEMENTFORMAT_UBYTE4_NORM,
        SDL_GPU_VERTEXELEMENTFORMAT_UINT, SDL_GPU_VERTEXELEMENTFORMAT_UINT2, SDL_GPU_VERTEXELEMENTFORMAT_UINT3,
        SDL_GPU_VERTEXELEMENTFORMAT_UINT4};
    static const Uint32 sizes[] = {0, 4, 8, 12, 16, 4, 4, 8, 12, 16};
    if (format < 1 || format > 9) { *size = 0; return SDL_GPU_VERTEXELEMENTFORMAT_INVALID; }
    *size = sizes[format]; return formats[format];
}
/* state: color format, depth format (0=none), topology, cull, winding,
 * depth compare (0=disabled), depth write, blend (0=off,1=alpha,2=premul).
 * vertices: slot,pitch,input_rate; attributes: location,slot,format,offset. */
xu_int API(pipeline_new)(xu_int owner, xu_int vertex, xu_int fragment, const xu_i64_span *state,
                          const xu_i64_span *vertices, const xu_i64_span *attributes) {
    Device *d = device(owner); if (!d) return -1;
    Resource *vs = resource(d, vertex, SHADER), *fs = resource(d, fragment, SHADER);
    if (!vs || !fs) return -1;
    if (vs->stage != 0 || fs->stage != 1 || !state || state->len != 8 || !state->data ||
        !vertices || vertices->len < 0 || vertices->len > VERTEX_SLOTS * 3 || vertices->len % 3 || (vertices->len && !vertices->data) ||
        !attributes || attributes->len < 0 || attributes->len > VERTEX_SLOTS * 4 || attributes->len % 4 || (attributes->len && !attributes->data))
        return fail("invalid GPU graphics pipeline descriptor");
    const xu_int *v = state->data;
    if (!texture_format(v[0]) || v[0] == 13 || (v[1] != 0 && v[1] != 13) || v[2] < 0 || v[2] > 4 ||
        v[3] < 0 || v[3] > 2 || v[4] < 0 || v[4] > 1 || v[5] < 0 || v[5] > 8 || v[6] < 0 || v[6] > 1 ||
        (!v[1] && (v[5] || v[6])) || (!v[5] && v[6]) || v[7] < 0 || v[7] > 2)
        return fail("invalid GPU pipeline target, depth, blend or primitive state");
    if (!p_SDL_GPUTextureSupportsFormat(d->gpu, texture_format(v[0]), SDL_GPU_TEXTURETYPE_2D, 2))
        return fail("unsupported GPU pipeline color format");
    SDL_GPUVertexBufferDescription vb[VERTEX_SLOTS] = {{0}};
    SDL_GPUVertexAttribute va[VERTEX_SLOTS] = {{0}};
    unsigned slots = 0, locations = 0;
    Uint32 count = (Uint32)vertices->len / 3, pitches[VERTEX_SLOTS] = {0};
    for (Uint32 i = 0; i < count; ++i) {
        const xu_int *b = vertices->data + i * 3;
        if (b[0] < 0 || b[0] >= VERTEX_SLOTS || (slots & (1u << b[0])) || b[1] < 4 || b[1] > 2048 || b[1] % 4 || b[2] < 0 || b[2] > 1)
            return fail("invalid GPU vertex buffer slot, stride or input rate");
        vb[i] = (SDL_GPUVertexBufferDescription){(Uint32)b[0], (Uint32)b[1], (SDL_GPUVertexInputRate)b[2], 0};
        slots |= 1u << b[0]; pitches[b[0]] = (Uint32)b[1];
    }
    for (Uint32 i = 0; i < (Uint32)attributes->len / 4; ++i) {
        const xu_int *a = attributes->data + i * 4;
        Uint32 size; SDL_GPUVertexElementFormat fmt = vertex_format(a[2], &size);
        if (a[0] < 0 || a[0] >= VERTEX_SLOTS || (locations & (1u << a[0])) || a[1] < 0 || a[1] >= VERTEX_SLOTS ||
            !(slots & (1u << a[1])) || !size || a[3] < 0 || a[3] % 4 || (xu_uint)a[3] + size > pitches[a[1]])
            return fail("invalid GPU vertex attribute location, slot, format or offset");
        locations |= 1u << a[0]; va[i] = (SDL_GPUVertexAttribute){(Uint32)a[0], (Uint32)a[1], fmt, (Uint32)a[3]};
    }
    Resource *r = allocate_resource(PIPELINE); if (!r) return -1;
    r->bindings[0] = vs->bindings[0]; r->bindings[1] = fs->bindings[1];
    r->vertex_count = count; memcpy(r->vertices, vb, sizeof(vb)); r->color_format = (int)v[0]; r->depth_format = (int)v[1];
    SDL_GPUColorTargetDescription color = {0}; color.format = texture_format(v[0]);
    color.blend_state.enable_blend = v[7] != 0;
    color.blend_state.src_color_blendfactor = v[7] == 1 ? SDL_GPU_BLENDFACTOR_SRC_ALPHA : SDL_GPU_BLENDFACTOR_ONE;
    color.blend_state.dst_color_blendfactor = SDL_GPU_BLENDFACTOR_ONE_MINUS_SRC_ALPHA;
    color.blend_state.src_alpha_blendfactor = SDL_GPU_BLENDFACTOR_ONE;
    color.blend_state.dst_alpha_blendfactor = SDL_GPU_BLENDFACTOR_ONE_MINUS_SRC_ALPHA;
    color.blend_state.color_blend_op = SDL_GPU_BLENDOP_ADD; color.blend_state.alpha_blend_op = SDL_GPU_BLENDOP_ADD;
    SDL_GPUGraphicsPipelineCreateInfo info = {0}; info.vertex_shader = vs->gpu; info.fragment_shader = fs->gpu;
    info.vertex_input_state = (SDL_GPUVertexInputState){vb, count, va, (Uint32)attributes->len / 4};
    info.primitive_type = (SDL_GPUPrimitiveType)v[2]; info.rasterizer_state.cull_mode = (SDL_GPUCullMode)v[3];
    info.rasterizer_state.front_face = (SDL_GPUFrontFace)v[4]; info.rasterizer_state.enable_depth_clip = true;
    info.depth_stencil_state.enable_depth_test = v[5] != 0; info.depth_stencil_state.enable_depth_write = v[6] != 0;
    info.depth_stencil_state.compare_op = (SDL_GPUCompareOp)v[5];
    info.target_info = (SDL_GPUGraphicsPipelineTargetInfo){&color, 1, texture_format(v[1]), v[1] != 0, 0, 0, 0};
    r->gpu = p_SDL_CreateGPUGraphicsPipeline(d->gpu, &info);
    if (!r->gpu) { sdl_fail(); free(r); return -1; }
    return add_resource(d, r);
}
xu_int API(encoder_new)(xu_int owner) {
    Device *d = device(owner); if (!d || !load_render()) return -1;
    Encoder *e = calloc(1, sizeof(*e)); if (!e) return fail("GPU command encoder allocation failed");
    e->id = identifier(); if (e->id < 0) { free(e); return -1; }
    e->command = p_SDL_AcquireGPUCommandBuffer(d->gpu);
    if (!e->command) { sdl_fail(); free(e); return -1; }
    e->next = d->encoders; d->encoders = e; return e->id;
}
xu_int API(encoder_close)(xu_int owner, xu_int id) {
    if (!on_main()) return -1;
    Device *d = devices; while (d && d->id != owner) d = d->next;
    if (!d) return 0;
    for (Encoder *e = d->encoders; e; e = e->next) if (e->id == id) return free_encoder(d, e, true) ? 0 : -1;
    return 0;
}
xu_int API(encoder_submit)(xu_int owner, xu_int id) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = encoder(d, id, false); if (!e) return -1;
    if (e->pass || e->compute) return fail("end the GPU pass before submitting its encoder");
    Transfer *t = new_transfer(d, 0, false, false); if (!t) return -1;
    t->fence = p_SDL_SubmitGPUCommandBufferAndAcquireFence(e->command);
    if (!t->fence) { sdl_fail(); free_transfer(d, t); free_encoder(d, e, false); return -1; }
    free_encoder(d, e, false); t->next = d->transfers; d->transfers = t; return t->id;
}
/* desc: color ID, mip, load, store, depth ID(0=none), depth load, store.
 * Depth attachment is level zero for the SDL 3.2 baseline ABI. */
static xu_int begin_render_pass(Encoder *e, Resource *color, xu_int mip, xu_int load, xu_int store,
                                Resource *depth, xu_int depth_load, xu_int depth_store,
                                double red, double green, double blue, double alpha, double clear_depth) {
    if (e->pass || e->compute || !isfinite(red) || !isfinite(green) || !isfinite(blue) || !isfinite(alpha) ||
        !isfinite(clear_depth) || clear_depth<0 || clear_depth>1 || fabs(red)>3.4e38 || fabs(green)>3.4e38 || fabs(blue)>3.4e38 || fabs(alpha)>3.4e38)
        return fail("invalid GPU render pass state or clear values");
    if (!(color->usage&2) || mip<0 || mip>=color->levels || load<0 || load>2 || store<0 || store>1 ||
        depth_load<0 || depth_load>2 || depth_store<0 || depth_store>1) return fail("invalid GPU render attachment usage, mip or operations");
    Uint32 width=mip_extent(color->width,(Uint32)mip), height=mip_extent(color->height,(Uint32)mip);
    if (depth && (!(depth->usage&4) || depth->width!=width || depth->height!=height)) return fail("GPU depth attachment extent or usage mismatch");
    xu_int pass_id=identifier(); if (pass_id<0) return -1;
    if ((color!=&e->present_target && !retain(e,color,false)) || (depth && !retain(e,depth,false))) return -1;
    SDL_GPUColorTargetInfo target={0}; target.texture=color->gpu; target.mip_level=(Uint32)mip;
    target.load_op=(SDL_GPULoadOp)load; target.store_op=(SDL_GPUStoreOp)store;
    target.clear_color=(SDL_FColor){(float)red,(float)green,(float)blue,(float)alpha};
    SDL_GPUDepthStencilTargetInfo z={0};
    if (depth) { z.texture=depth->gpu; z.clear_depth=(float)clear_depth; z.load_op=(SDL_GPULoadOp)depth_load; z.store_op=(SDL_GPUStoreOp)depth_store; }
    e->pass=p_SDL_BeginGPURenderPass(e->command,&target,1,depth ? &z : NULL);
    if (!e->pass) return sdl_fail();
    e->pass_id=pass_id; e->color=color; e->depth=depth; e->pipeline=NULL; e->width=width; e->height=height;
    memset(e->vertices,0,sizeof(e->vertices)); e->index=NULL;
    memset(e->samplers,0,sizeof(e->samplers)); memset(e->uniforms,0,sizeof(e->uniforms));
    return pass_id;
}
xu_int API(pass_begin)(xu_int owner, xu_int id, const xu_i64_span *desc, double red, double green, double blue, double alpha, double clear_depth) {
    Device *d=device(owner); if (!d) return -1;
    Encoder *e=encoder(d,id,false); if (!e) return -1;
    if (e->surface || !desc || desc->len!=7 || !desc->data) return fail("invalid GPU offscreen render descriptor or encoder");
    const xu_int *v=desc->data;
    Resource *color=resource(d,v[0],TEXTURE); if (!color) return -1;
    Resource *depth=v[4] ? resource(d,v[4],TEXTURE) : NULL; if (v[4] && !depth) return -1;
    return begin_render_pass(e,color,v[1],v[2],v[3],depth,v[5],v[6],red,green,blue,alpha,clear_depth);
}
xu_int API(pass_end)(xu_int owner, xu_int id) {
    if (!on_main()) return -1;
    Device *d = devices; while (d && d->id != owner) d = d->next;
    if (!d) return 0;
    for (Encoder *e = d->encoders; e; e = e->next) if (e->pass && e->pass_id == id) {
        p_SDL_EndGPURenderPass(e->pass); e->pass = NULL; return 0;
    }
    return 0;
}
xu_int API(pass_pipeline)(xu_int owner, xu_int id, xu_int pipeline) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = encoder(d, id, true); Resource *r = resource(d, pipeline, PIPELINE); if (!e || !r) return -1;
    if (r->color_format != e->color->format || r->depth_format != (e->depth ? e->depth->format : 0)) return fail("GPU pipeline attachment formats do not match render pass");
    if (!retain(e, r, false)) return -1;
    p_SDL_BindGPUGraphicsPipeline(e->pass, r->gpu); e->pipeline = r;
    /* Require explicit bindings after each pipeline change, preventing stale
     * shader-layout state from satisfying a different pipeline's contract. */
    memset(e->vertices, 0, sizeof(e->vertices)); e->index = NULL;
    memset(e->samplers, 0, sizeof(e->samplers)); memset(e->uniforms, 0, sizeof(e->uniforms));
    return 0;
}
xu_int API(pass_buffer)(xu_int owner, xu_int id, xu_int buffer_id, xu_int slot, xu_int offset, xu_int index_size) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = encoder(d, id, true); Buffer *b = buffer(d, buffer_id); if (!e || !b) return -1;
    if (!e->pipeline || offset < 0 || offset >= b->size || offset % (index_size ? index_size : 4) || slot < 0 || slot >= VERTEX_SLOTS ||
        (index_size != 0 && index_size != 2 && index_size != 4) || !(b->usage & (index_size ? 2u : 1u))) return fail("invalid GPU vertex/index binding, offset or usage");
    if (!retain(e, b, true)) return -1;
    SDL_GPUBufferBinding binding = {b->gpu, (Uint32)offset};
    if (index_size) {
        p_SDL_BindGPUIndexBuffer(e->pass, &binding, index_size == 2 ? SDL_GPU_INDEXELEMENTSIZE_16BIT : SDL_GPU_INDEXELEMENTSIZE_32BIT);
        e->index = b; e->index_offset = (Uint32)offset; e->index_size = (Uint32)index_size;
    } else { p_SDL_BindGPUVertexBuffers(e->pass, (Uint32)slot, &binding, 1); e->vertices[slot] = b; e->offsets[slot] = (Uint32)offset; }
    return 0;
}
xu_int API(pass_sampler)(xu_int owner, xu_int id, xu_int stage, xu_int slot, xu_int texture, xu_int sampler) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = encoder(d, id, true); Resource *t = resource(d, texture, TEXTURE), *s = resource(d, sampler, SAMPLER);
    if (!e || !t || !s) return -1;
    if (!e->pipeline || stage < 0 || stage > 1 || slot < 0 || slot >= e->pipeline->bindings[stage].samplers || !(t->usage & 1) || t == e->color || t == e->depth)
        return fail("GPU sampler binding is undeclared, not sampled or aliases an active attachment");
    if (!retain(e, t, false) || !retain(e, s, false)) return -1;
    SDL_GPUTextureSamplerBinding binding = {t->gpu, s->gpu};
    if (stage == 0) p_SDL_BindGPUVertexSamplers(e->pass, (Uint32)slot, &binding, 1);
    else p_SDL_BindGPUFragmentSamplers(e->pass, (Uint32)slot, &binding, 1);
    e->samplers[stage] |= 1u << slot; return 0;
}
xu_int API(pass_uniform)(xu_int owner, xu_int id, xu_int stage, xu_int slot, const xu_u8_span *data) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = encoder(d, id, true); if (!e) return -1;
    if (!e->pipeline || stage < 0 || stage > 1 || slot < 0 || slot >= e->pipeline->bindings[stage].count ||
        !data || !data->data || data->len != e->pipeline->bindings[stage].sizes[slot]) return fail("GPU uniform binding requires its declared exact byte size");
    if (stage == 0) p_SDL_PushGPUVertexUniformData(e->command, (Uint32)slot, data->data, (Uint32)data->len);
    else p_SDL_PushGPUFragmentUniformData(e->command, (Uint32)slot, data->data, (Uint32)data->len);
    e->uniforms[stage] |= 1u << slot; return 0;
}
xu_int API(pass_rect)(xu_int owner, xu_int id, xu_int x, xu_int y, xu_int width, xu_int height, xu_int scissor) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = encoder(d, id, true); if (!e) return -1;
    if (x < 0 || y < 0 || width < 1 || height < 1 || x > e->width || y > e->height || width > e->width - x || height > e->height - y)
        return fail("GPU viewport/scissor must fit the render attachment");
    if (scissor) { SDL_Rect rect = {(int)x, (int)y, (int)width, (int)height}; p_SDL_SetGPUScissor(e->pass, &rect); }
    else { SDL_GPUViewport viewport = {(float)x, (float)y, (float)width, (float)height, 0, 1}; p_SDL_SetGPUViewport(e->pass, &viewport); }
    return 0;
}
xu_int API(pass_draw)(xu_int owner, xu_int id, xu_int count, xu_int first, xu_int instances, xu_int first_instance, xu_int indexed, xu_int vertex_offset) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = encoder(d, id, true); if (!e) return -1;
    if (!e->pipeline || count < 1 || count > UINT32_MAX || first < 0 || first > UINT32_MAX || count > UINT32_MAX - first ||
        instances < 1 || instances > UINT32_MAX || first_instance < 0 || first_instance > UINT32_MAX || instances > UINT32_MAX - first_instance ||
        vertex_offset < INT32_MIN || vertex_offset > INT32_MAX) return fail("invalid GPU draw range or missing pipeline");
    Resource *p = e->pipeline;
    for (int stage = 0; stage < 2; ++stage) {
        if (e->samplers[stage] != ((1u << p->bindings[stage].samplers) - 1) || e->uniforms[stage] != ((1u << p->bindings[stage].count) - 1))
            return fail("GPU draw has missing sampler or uniform bindings");
    }
    for (Uint32 i = 0; i < p->vertex_count; ++i) {
        SDL_GPUVertexBufferDescription *v = &p->vertices[i]; Buffer *b = e->vertices[v->slot];
        if (!b) return fail("GPU draw has missing vertex buffers");
        xu_uint elements = v->input_rate == SDL_GPU_VERTEXINPUTRATE_INSTANCE ? (xu_uint)(first_instance + instances) : indexed ? 1 : (xu_uint)(first + count);
        if (elements * v->pitch > b->size - e->offsets[v->slot]) return fail("GPU draw exceeds vertex/instance buffer bounds");
    }
    if (indexed) {
        if (!e->index || (xu_uint)(first + count) * e->index_size > e->index->size - e->index_offset) return fail("GPU indexed draw exceeds index buffer bounds");
        /* Index values and shader memory accesses remain the shader author's
         * contract; GPU-owned buffer contents are not read on the CPU. */
        p_SDL_DrawGPUIndexedPrimitives(e->pass, (Uint32)count, (Uint32)instances, (Uint32)first, (Sint32)vertex_offset, (Uint32)first_instance);
    } else p_SDL_DrawGPUPrimitives(e->pass, (Uint32)count, (Uint32)instances, (Uint32)first, (Uint32)first_instance);
    return 0;
}
