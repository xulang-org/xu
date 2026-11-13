/* Buffer compute shares encoder ownership and retained resources with render.
 * No source pointer or borrowed span survives a synchronous ABI call. */
static bool compute_loaded;
static bool load_compute(void) {
    if (compute_loaded) return true;
#ifdef _WIN32
#define COMPUTE_FIND(name) GetProcAddress(sdl_library, #name)
#else
#define COMPUTE_FIND(name) dlsym(sdl_library, #name)
#endif
#define COMPUTE_LOAD(name) p_##name = (__typeof__(name) *)COMPUTE_FIND(name); \
 if (!p_##name) { fail("SDL GPU runtime is missing " #name); return false; }
    COMPUTE_FUNCTIONS(COMPUTE_LOAD)
    compute_loaded = true;
    return true;
}
enum { COMPUTE_STORAGE_SLOTS = 8, COMPUTE_THREADS = 1024, COMPUTE_THREADS_Z = 64, COMPUTE_GROUPS = 65535 };
/* desc: format, readonly buffers, readwrite buffers, local threads x/y/z. */
xu_int API(compute_pipeline_new)(xu_int owner, const xu_i64_span *desc, const xu_i64_span *sizes,
                               const xu_u8_span *entry, const xu_u8_span *code) {
    Device *d = device(owner); if (!d || !load_compute()) return -1;
    if (!desc || desc->len != 6 || !desc->data) return fail("invalid GPU compute descriptor");
    const xu_int *v = desc->data;
    if (v[1] < 0 || v[1] > COMPUTE_STORAGE_SLOTS || v[2] < 0 || v[2] > COMPUTE_STORAGE_SLOTS ||
        v[3] < 1 || v[3] > COMPUTE_THREADS || v[4] < 1 || v[4] > COMPUTE_THREADS || v[5] < 1 || v[5] > COMPUTE_THREADS_Z ||
        v[3] * v[4] * v[5] > COMPUTE_THREADS) return fail("invalid GPU compute binding counts or local thread dimensions");
    ShaderSource source = {0};
    if (!prepare_shader_source(owner, v[0], sizes, entry, code, &source)) return -1;
    Resource *r = allocate_resource(COMPUTE_PIPELINE);
    if (!r) { free_shader_source(&source); return -1; }
    r->read_buffers = (Uint32)v[1]; r->write_buffers = (Uint32)v[2]; r->bindings[0].count = (Uint32)sizes->len;
    for (xu_int i = 0; i < sizes->len; ++i) r->bindings[0].sizes[i] = (Uint32)sizes->data[i];
    SDL_GPUComputePipelineCreateInfo info = {0};
    info.code_size = (size_t)code->len; info.code = source.bytes; info.entrypoint = source.name; info.format = (Uint32)v[0] << 1;
    info.num_readonly_storage_buffers = r->read_buffers; info.num_readwrite_storage_buffers = r->write_buffers;
    info.num_uniform_buffers = r->bindings[0].count;
    info.threadcount_x = (Uint32)v[3]; info.threadcount_y = (Uint32)v[4]; info.threadcount_z = (Uint32)v[5];
    r->gpu = p_SDL_CreateGPUComputePipeline(d->gpu, &info); free_shader_source(&source);
    if (!r->gpu) { sdl_fail(); free(r); return -1; }
    return add_resource(d, r);
}
static Encoder *compute_pass(Device *d, xu_int id) {
    for (Encoder *e = d->encoders; e; e = e->next) if (e->compute && e->pass_id == id) return e;
    fail("closed or invalid GPU compute pass"); return NULL;
}
/* Write bindings: buffer ID, cycle boolean. All validation precedes SDL calls. */
xu_int API(compute_begin)(xu_int owner, xu_int id, const xu_i64_span *writes) {
    Device *d = device(owner); if (!d || !load_compute()) return -1;
    Encoder *e = encoder(d, id, false); if (!e) return -1;
    if (e->pass || e->compute || !writes || writes->len < 0 || writes->len > COMPUTE_STORAGE_SLOTS * 2 ||
        writes->len % 2 || (writes->len && !writes->data)) return fail("invalid GPU compute pass state or write bindings");
    Uint32 count = (Uint32)writes->len / 2;
    SDL_GPUStorageBufferReadWriteBinding bindings[COMPUTE_STORAGE_SLOTS] = {0};
    Buffer *buffers[COMPUTE_STORAGE_SLOTS];
    for (Uint32 i = 0; i < count; ++i) {
        Buffer *b = buffer(d, writes->data[i * 2]); if (!b) return -1;
        xu_int cycle = writes->data[i * 2 + 1];
        if (!(b->usage & 32) || cycle < 0 || cycle > 1) return fail("invalid GPU compute write usage or cycle flag");
        for (Uint32 j = 0; j < i; ++j) if (buffers[j] == b) return fail("duplicate GPU compute write buffer");
        buffers[i] = b; bindings[i].buffer = b->gpu; bindings[i].cycle = cycle != 0;
    }
    xu_int pass_id = identifier(); if (pass_id < 0) return -1;
    for (Uint32 i = 0; i < count; ++i) if (!retain(e, buffers[i], true)) return -1;
    e->compute = p_SDL_BeginGPUComputePass(e->command, NULL, 0, bindings, count);
    if (!e->compute) return sdl_fail();
    e->pass_id = pass_id; e->write_count = count; e->pipeline = NULL; e->compute_reads = 0; e->uniforms[0] = 0;
    for (Uint32 i = 0; i < count; ++i) e->writes[i] = buffers[i];
    return pass_id;
}
xu_int API(compute_pipeline)(xu_int owner, xu_int id, xu_int pipeline) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = compute_pass(d, id); Resource *r = resource(d, pipeline, COMPUTE_PIPELINE); if (!e || !r) return -1;
    if (r->write_buffers != e->write_count) return fail("GPU compute pipeline write count does not match pass");
    if (!retain(e, r, false)) return -1;
    p_SDL_BindGPUComputePipeline(e->compute, r->gpu); e->pipeline = r; e->compute_reads = 0; e->uniforms[0] = 0;
    return 0;
}
xu_int API(compute_buffer)(xu_int owner, xu_int id, xu_int slot, xu_int buffer_id) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = compute_pass(d, id); Buffer *b = buffer(d, buffer_id); if (!e || !b) return -1;
    if (!e->pipeline || slot < 0 || slot >= e->pipeline->read_buffers || !(b->usage & 16))
        return fail("GPU compute read buffer is undeclared or has invalid usage");
    for (Uint32 i = 0; i < e->write_count; ++i) if (e->writes[i] == b) return fail("GPU compute read buffer aliases a write binding");
    if (!retain(e, b, true)) return -1;
    p_SDL_BindGPUComputeStorageBuffers(e->compute, (Uint32)slot, &b->gpu, 1); e->compute_reads |= 1u << slot;
    return 0;
}
xu_int API(compute_uniform)(xu_int owner, xu_int id, xu_int slot, const xu_u8_span *data) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = compute_pass(d, id); if (!e) return -1;
    if (!e->pipeline || slot < 0 || slot >= e->pipeline->bindings[0].count || !data || !data->data ||
        data->len != e->pipeline->bindings[0].sizes[slot]) return fail("GPU compute uniform requires its declared exact byte size");
    p_SDL_PushGPUComputeUniformData(e->command, (Uint32)slot, data->data, (Uint32)data->len); e->uniforms[0] |= 1u << slot;
    return 0;
}
xu_int API(compute_dispatch)(xu_int owner, xu_int id, xu_int x, xu_int y, xu_int z) {
    Device *d = device(owner); if (!d) return -1;
    Encoder *e = compute_pass(d, id); if (!e) return -1;
    if (!e->pipeline || x < 1 || x > COMPUTE_GROUPS || y < 1 || y > COMPUTE_GROUPS || z < 1 || z > COMPUTE_GROUPS)
        return fail("invalid GPU compute dispatch range or missing pipeline");
    if (e->compute_reads != ((1u << e->pipeline->read_buffers) - 1) || e->uniforms[0] != ((1u << e->pipeline->bindings[0].count) - 1))
        return fail("GPU compute dispatch has missing buffer or uniform bindings");
    p_SDL_DispatchGPUCompute(e->compute, (Uint32)x, (Uint32)y, (Uint32)z);
    return 0;
}
xu_int API(compute_end)(xu_int owner, xu_int id) {
    if (!on_main()) return -1;
    Device *d = devices; while (d && d->id != owner) d = d->next;
    if (!d) return 0;
    for (Encoder *e = d->encoders; e; e = e->next) if (e->compute && e->pass_id == id) {
        p_SDL_EndGPUComputePass(e->compute); e->compute = NULL; return 0;
    }
    return 0;
}
