/* Presentation owns its acquired command and swapchain image as one frame.
 * Swapchain images never enter the ordinary texture owner/view registry. */
static bool surface_loaded;
static bool load_surface(void) {
    if (surface_loaded) return true;
#ifdef _WIN32
#define SURFACE_FIND(name) GetProcAddress(sdl_library, #name)
#else
#define SURFACE_FIND(name) dlsym(sdl_library, #name)
#endif
#define SURFACE_LOAD(name) p_##name=(__typeof__(name) *)SURFACE_FIND(name); \
 if (!p_##name) { fail("SDL runtime is missing " #name); return false; }
    SURFACE_FUNCTIONS(SURFACE_LOAD)
    surface_loaded=true; return true;
}
static Surface *surface_record(Device *d, xu_int id) {
    for (Surface *s=d->surfaces; s; s=s->next) if (s->id==id) return s;
    fail("closed, foreign or invalid GPU surface"); return NULL;
}
static int surface_format(Device *d, WindowRecord *w) {
    SDL_GPUTextureFormat native=p_SDL_GetGPUSwapchainTextureFormat(d->gpu,w->native);
    for (int format=1; format<=20; ++format) if (texture_format(format)==native) return format;
    fail("GPU swapchain format is not represented by gpu/layout"); return 0;
}
static void surface_encoder_released(Encoder *e) { if (e->surface->frame==e->id) e->surface->frame=0; }
static bool abandon_surface(Encoder *e) {
    bool ok=true; char first[1024];
    SDL_GPUColorTargetInfo target={0}; target.texture=e->present_target.gpu;
    target.load_op=SDL_GPU_LOADOP_CLEAR; target.store_op=SDL_GPU_STOREOP_STORE;
    target.clear_color=(SDL_FColor){0,0,0,1};
    SDL_GPURenderPass *clear=p_SDL_BeginGPURenderPass(e->command,&target,1,NULL);
    if (clear) p_SDL_EndGPURenderPass(clear);
    else { sdl_fail(); retain_error(&ok,first); }
    /* Acquired images cannot be cancelled. Submission consumes the command
     * even on failure; finish this obligation without allocating a fence. */
    if (!p_SDL_SubmitGPUCommandBuffer(e->command)) { sdl_fail(); retain_error(&ok,first); }
    return cleanup_result(ok,first);
}
static bool destroy_surface(Surface *s, bool wait) {
    Device *d=s->owner; bool ok=true; char first[1024];
    if (s->frame) {
        Encoder *e=encoder(d,s->frame,false);
        if (e && !free_encoder(d,e,true)) retain_error(&ok,first);
    }
    if (wait && !p_SDL_WaitForGPUIdle(d->gpu)) { sdl_fail(); retain_error(&ok,first); }
    p_SDL_ReleaseWindowFromGPUDevice(d->gpu,s->window->native);
    s->window->binding=NULL; s->window->release_binding=NULL;
    Surface **link=&d->surfaces; while (*link && *link!=s) link=&(*link)->next;
    if (*link) *link=s->next;
    free(s); return cleanup_result(ok,first);
}
static bool release_window_surface(void *binding) { return destroy_surface(binding,true); }
static bool close_surfaces(Device *d) {
    bool ok=true; char first[1024];
    while (d->surfaces) if (!destroy_surface(d->surfaces,false)) retain_error(&ok,first);
    return cleanup_result(ok,first);
}
xu_int API(surface_new)(xu_int owner, xu_int window_id, xu_int mode) {
    Device *d=device(owner); if (!d || !load_render() || !load_surface()) return -1;
    WindowRecord *w=window_record(window_id); if (!w) return -1;
    if (w->binding || mode<0 || mode>2) return fail("window already bound or invalid present mode");
    Surface *s=calloc(1,sizeof(*s)); if (!s) return fail("GPU surface allocation failed");
    s->id=identifier(); if (s->id<0) { free(s); return -1; }
    if (!p_SDL_ClaimWindowForGPUDevice(d->gpu,w->native)) { sdl_fail(); free(s); return -1; }
    if (!p_SDL_WindowSupportsGPUPresentMode(d->gpu,w->native,(SDL_GPUPresentMode)mode)) {
        fail("GPU present mode is unsupported for this window"); p_SDL_ReleaseWindowFromGPUDevice(d->gpu,w->native); free(s); return -1;
    }
    if (mode && !p_SDL_SetGPUSwapchainParameters(d->gpu,w->native,SDL_GPU_SWAPCHAINCOMPOSITION_SDR,(SDL_GPUPresentMode)mode)) {
        sdl_fail(); p_SDL_ReleaseWindowFromGPUDevice(d->gpu,w->native); free(s); return -1;
    }
    int format=surface_format(d,w);
    if (!format) { p_SDL_ReleaseWindowFromGPUDevice(d->gpu,w->native); free(s); return -1; }
    s->owner=d; s->window=w; s->format=format; s->next=d->surfaces; d->surfaces=s;
    w->binding=s; w->release_binding=release_window_surface;
    return s->id;
}
xu_int API(surface_close)(xu_int owner, xu_int id) {
    if (!on_main()) return -1;
    Device *d=devices; while (d && d->id!=owner) d=d->next;
    if (!d) return 0;
    for (Surface *s=d->surfaces; s; s=s->next) if (s->id==id) return destroy_surface(s,true) ? 0 : -1;
    return 0;
}
xu_int API(surface_format)(xu_int owner, xu_int id) {
    Device *d=device(owner); if (!d) return -1;
    Surface *s=surface_record(d,id); return s ? s->format : -1;
}
xu_int API(surface_supports_mode)(xu_int owner, xu_int id, xu_int mode) {
    Device *d=device(owner); if (!d) return -1;
    Surface *s=surface_record(d,id); if (!s) return -1;
    if (mode<0 || mode>2) return fail("invalid GPU present mode");
    return p_SDL_WindowSupportsGPUPresentMode(d->gpu,s->window->native,(SDL_GPUPresentMode)mode) ? 1 : 0;
}
xu_int API(surface_mode)(xu_int owner, xu_int id, xu_int mode) {
    Device *d=device(owner); if (!d) return -1;
    Surface *s=surface_record(d,id); if (!s) return -1;
    if (s->frame || mode<0 || mode>2) return fail("invalid present mode or reconfiguration with acquired frame");
    if (!p_SDL_WindowSupportsGPUPresentMode(d->gpu,s->window->native,(SDL_GPUPresentMode)mode)) return fail("unsupported GPU present mode");
    if (!p_SDL_SetGPUSwapchainParameters(d->gpu,s->window->native,SDL_GPU_SWAPCHAINCOMPOSITION_SDR,(SDL_GPUPresentMode)mode)) return sdl_fail();
    int format=surface_format(d,s->window);
    if (!format) { char first[1024]; memcpy(first,error_text,1024); destroy_surface(s,true); memcpy(error_text,first,1024); return -1; }
    s->format=format; return 0;
}
xu_int API(frame_acquire)(xu_int owner, xu_int id, const xu_i64_span_mut *output) {
    Device *d=device(owner); if (!d) return -1;
    Surface *s=surface_record(d,id); if (!s) return -1;
    if (s->frame || s->window->closed || !output || output->len!=3 || !output->data)
        return fail("GPU surface already has an acquired frame or invalid frame output");
    xu_int handle=API(encoder_new)(owner); if (handle<0) return -1;
    Encoder *e=encoder(d,handle,false); SDL_GPUTexture *image=NULL; Uint32 width=0,height=0;
    if (!p_SDL_WaitAndAcquireGPUSwapchainTexture(e->command,s->window->native,&image,&width,&height)) {
        sdl_fail(); char first[1024]; memcpy(first,error_text,1024);
        free_encoder(d,e,true); memcpy(error_text,first,1024); return -1;
    }
    if (!image) {
        if (!free_encoder(d,e,true)) return -1;
        memset(output->data,0,3*sizeof(xu_int)); return 0;
    }
    /* Mark acquisition before any later failure: all cleanup must submit. */
    e->surface=s; s->frame=e->id; e->present_target.gpu=image;
    int format=surface_format(d,s->window);
    if (!format || !width || !height) {
        if (format) fail("GPU acquired an empty swapchain image");
        char first[1024]; memcpy(first,error_text,1024);
        free_encoder(d,e,true); memcpy(error_text,first,1024); return -1;
    }
    e->present_target.kind=TEXTURE; e->present_target.format=format;
    e->present_target.width=width; e->present_target.height=height; e->present_target.levels=1; e->present_target.usage=2;
    xu_int values[]={width,height,format}; memcpy(output->data,values,sizeof(values));
    return e->id;
}
xu_int API(frame_begin)(xu_int owner, xu_int id, const xu_i64_span *desc,
                       double red,double green,double blue,double alpha,double clear_depth) {
    Device *d=device(owner); if (!d) return -1;
    Encoder *e=encoder(d,id,false); if (!e) return -1;
    if (!e->surface || !desc || desc->len!=4 || !desc->data || (!e->present_passes && desc->data[0]==0))
        return fail("invalid GPU frame descriptor or LOAD before initial render");
    const xu_int *v=desc->data;
    Resource *depth=v[1] ? resource(d,v[1],TEXTURE) : NULL; if (v[1] && !depth) return -1;
    xu_int pass=begin_render_pass(e,&e->present_target,0,v[0],0,depth,v[2],v[3],red,green,blue,alpha,clear_depth);
    if (pass>0) ++e->present_passes;
    return pass;
}
xu_int API(frame_submit)(xu_int owner, xu_int id) {
    Device *d=device(owner); if (!d) return -1;
    Encoder *e=encoder(d,id,false); if (!e) return -1;
    if (!e->surface || !e->present_passes) return fail("GPU frame needs a render pass before presentation");
    return API(encoder_submit)(owner,id);
}
xu_int API(frame_close)(xu_int owner, xu_int id) { return API(encoder_close)(owner,id); }
