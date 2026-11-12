#define _GNU_SOURCE
#include "xu_native.h"
#include "sdl_abi.h"
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#ifdef __APPLE__
#include <pthread.h>
#else
#include <unistd.h>
#include <sys/syscall.h>
#endif
#endif

#define API(name) XU_NATIVE_SYMBOL(xu_gpu_internal_native_##name)
#define FUNCTIONS(X) \
    X(SDL_SetMainReady) X(SDL_IsMainThread) X(SDL_InitSubSystem) X(SDL_QuitSubSystem) X(SDL_GetError) \
    X(SDL_CreateGPUDevice) X(SDL_DestroyGPUDevice) X(SDL_GetGPUDeviceDriver) X(SDL_GetGPUShaderFormats) \
    X(SDL_CreateGPUBuffer) X(SDL_ReleaseGPUBuffer) X(SDL_CreateGPUTransferBuffer) X(SDL_ReleaseGPUTransferBuffer) \
    X(SDL_MapGPUTransferBuffer) X(SDL_UnmapGPUTransferBuffer) X(SDL_AcquireGPUCommandBuffer) X(SDL_CancelGPUCommandBuffer) \
    X(SDL_BeginGPUCopyPass) X(SDL_EndGPUCopyPass) X(SDL_UploadToGPUBuffer) X(SDL_CopyGPUBufferToBuffer) \
    X(SDL_DownloadFromGPUBuffer) X(SDL_SubmitGPUCommandBufferAndAcquireFence) X(SDL_QueryGPUFence) \
    X(SDL_WaitForGPUFences) X(SDL_ReleaseGPUFence) X(SDL_WaitForGPUIdle)
#define DECLARE(name) static __typeof__(name) *p_##name;
FUNCTIONS(DECLARE)
static bool loaded;
static _Thread_local char error_text[1024];
static xu_int fail(const char *message) {
    snprintf(error_text, sizeof(error_text), "%s", message ? message : "GPU operation failed");
    return -1;
}
static xu_int sdl_fail(void) { return fail(p_SDL_GetError()); }
static bool on_main(void) {
#ifdef __APPLE__
    if (!pthread_main_np()) { fail("GPU operations require the application main thread"); return false; }
#elif defined(__linux__)
    if (syscall(SYS_gettid) != getpid()) { fail("GPU operations require the application main thread"); return false; }
#endif
    if (loaded && !p_SDL_IsMainThread()) { fail("GPU operations require the application main thread"); return false; }
    return true;
}
static bool load_sdl(void) {
    if (!on_main()) return false;
    if (loaded) return true;
#ifdef _WIN32
    DWORD capacity = GetEnvironmentVariableW(L"XU_GPU_SDL_LIBRARY", NULL, 0);
    wchar_t *path = capacity ? calloc(capacity, sizeof(*path)) : NULL;
    if (capacity && !path) { fail("GPU library path allocation failed"); return false; }
    if (path) {
        DWORD length = GetEnvironmentVariableW(L"XU_GPU_SDL_LIBRARY", path, capacity);
        if (!length || length >= capacity) {
            free(path); fail("GPU library path changed while loading"); return false;
        }
    }
    HMODULE library = LoadLibraryW(path ? path : L"SDL3.dll");
    free(path);
#define FIND(name) GetProcAddress(library, #name)
#define UNLOAD() FreeLibrary(library)
#else
    const char *override = getenv("XU_GPU_SDL_LIBRARY");
    void *library = NULL;
    if (override && *override) library = dlopen(override, RTLD_NOW | RTLD_LOCAL);
#ifdef __APPLE__
    const char *names[] = {"libSDL3.dylib", "/opt/homebrew/lib/libSDL3.dylib", "/usr/local/lib/libSDL3.dylib"};
#else
    const char *names[] = {"libSDL3.so.0", "libSDL3.so"};
#endif
    if (!override || !*override) {
        for (size_t i = 0; !library && i < sizeof(names) / sizeof(names[0]); ++i)
            library = dlopen(names[i], RTLD_NOW | RTLD_LOCAL);
    }
#define FIND(name) dlsym(library, #name)
#define UNLOAD() dlclose(library)
#endif
    if (!library) { fail("SDL 3 GPU runtime unavailable; install SDL3 or set XU_GPU_SDL_LIBRARY"); return false; }
#define LOAD(name) p_##name = (__typeof__(name) *)FIND(name); \
    if (!p_##name) { fail("SDL 3 GPU runtime is missing " #name); UNLOAD(); return false; }
    FUNCTIONS(LOAD)
    p_SDL_SetMainReady();
    loaded = true; // Process-lifetime loader; device/subsystem references are separate.
    return true;
}
typedef struct Buffer {
    xu_int id;
    Uint32 size;
    SDL_GPUBuffer *gpu;
    struct Buffer *next;
} Buffer;
typedef struct Transfer {
    xu_int id;
    Uint32 size;
    bool download, complete;
    SDL_GPUTransferBuffer *staging;
    SDL_GPUFence *fence;
    struct Transfer *next;
} Transfer;
typedef struct Device {
    xu_int id;
    SDL_GPUDevice *gpu;
    Buffer *buffers;
    Transfer *transfers;
    struct Device *next;
} Device;
static Device *devices;
static xu_uint next_id = 1;
static xu_int identifier(void) {
    if (next_id > LLONG_MAX) return fail("GPU resource identity space exhausted");
    return (xu_int)next_id++;
}
static Device *device(xu_int id) {
    if (!on_main()) return NULL;
    for (Device *d = devices; d; d = d->next) if (d->id == id) return d;
    fail("closed or invalid GPU device"); return NULL;
}
static Buffer *buffer(Device *d, xu_int id) {
    for (Buffer *b = d->buffers; b; b = b->next) if (b->id == id) return b;
    fail("closed, foreign or invalid GPU buffer"); return NULL;
}
static Transfer *transfer(Device *d, xu_int id) {
    for (Transfer *t = d->transfers; t; t = t->next) if (t->id == id) return t;
    fail("closed, foreign or invalid GPU submission"); return NULL;
}
static bool region(Buffer *b, xu_int offset, xu_int size) {
    if (offset < 0 || size <= 0 || offset > b->size || size > b->size - offset || offset % 4 || size % 4) {
        fail("GPU transfer requires an in-bounds, positive, four-byte-aligned region"); return false;
    }
    return true;
}
static void free_transfer(Device *d, Transfer *t) {
    if (t->fence) p_SDL_ReleaseGPUFence(d->gpu, t->fence);
    if (t->staging) p_SDL_ReleaseGPUTransferBuffer(d->gpu, t->staging);
    free(t);
}
static Transfer *new_transfer(Device *d, Uint32 size, bool staging, bool download) {
    Transfer *t = calloc(1, sizeof(*t));
    if (!t) { fail("GPU submission allocation failed"); return NULL; }
    t->id = identifier(); t->size = size; t->download = download;
    if (t->id < 0) { free(t); return NULL; }
    if (staging) {
        SDL_GPUTransferBufferCreateInfo info = {download ? 1 : 0, size, 0};
        t->staging = p_SDL_CreateGPUTransferBuffer(d->gpu, &info);
        if (!t->staging) { sdl_fail(); free(t); return NULL; }
    }
    return t;
}
static SDL_GPUCopyPass *begin_copy(Device *d, Transfer *t, SDL_GPUCommandBuffer **command) {
    *command = p_SDL_AcquireGPUCommandBuffer(d->gpu);
    SDL_GPUCopyPass *copy = *command ? p_SDL_BeginGPUCopyPass(*command) : NULL;
    if (!copy) {
        sdl_fail();
        if (*command) p_SDL_CancelGPUCommandBuffer(*command);
        free_transfer(d, t);
    }
    return copy;
}
static xu_int submit(Device *d, Transfer *t, SDL_GPUCommandBuffer *command, SDL_GPUCopyPass *copy) {
    p_SDL_EndGPUCopyPass(copy);
    // Submission consumes the command even if fence acquisition fails.
    t->fence = p_SDL_SubmitGPUCommandBufferAndAcquireFence(command);
    if (!t->fence) { sdl_fail(); free_transfer(d, t); return -1; }
    t->next = d->transfers; d->transfers = t;
    return t->id;
}
xu_int API(error_len)(void) { return (xu_int)strlen(error_text); }
xu_int API(error_byte)(xu_int i) {
    return i >= 0 && (xu_uint)i < strlen(error_text) ? (unsigned char)error_text[i] : 0;
}
xu_int API(open)(xu_int backend, xu_int debug, xu_int formats) {
    if (backend < 0 || backend > 3 || debug < 0 || debug > 1 || formats < 0 || formats > 31)
        return fail("invalid GPU device options");
    if (!load_sdl()) return -1;
    Device *d = calloc(1, sizeof(*d));
    if (!d) return fail("GPU device allocation failed");
    d->id = identifier();
    if (d->id < 0) { free(d); return -1; }
    // Balanced reference; closing this device cannot shut down other SDL users.
    if (!p_SDL_InitSubSystem(0x20u)) { sdl_fail(); free(d); return -1; }
    const char *drivers[] = {NULL, "metal", "vulkan", "direct3d12"};
    d->gpu = p_SDL_CreateGPUDevice((Uint32)(formats ? formats : 31) << 1, debug != 0, drivers[backend]);
    if (!d->gpu) { sdl_fail(); p_SDL_QuitSubSystem(0x20u); free(d); return -1; }
    d->next = devices; devices = d;
    return d->id;
}
xu_int API(close)(xu_int id) {
    if (!on_main()) return -1;
    Device **link = &devices;
    while (*link && (*link)->id != id) link = &(*link)->next;
    if (!*link) return 0;
    Device *d = *link;
    bool ok = p_SDL_WaitForGPUIdle(d->gpu);
    if (!ok) sdl_fail();
    while (d->transfers) { Transfer *t = d->transfers; d->transfers = t->next; free_transfer(d, t); }
    while (d->buffers) { Buffer *b = d->buffers; d->buffers = b->next; p_SDL_ReleaseGPUBuffer(d->gpu, b->gpu); free(b); }
    p_SDL_DestroyGPUDevice(d->gpu);
    p_SDL_QuitSubSystem(0x20u);
    *link = d->next; free(d);
    return ok ? 0 : -1;
}
xu_int API(backend)(xu_int id) {
    Device *d = device(id); if (!d) return -1;
    const char *name = p_SDL_GetGPUDeviceDriver(d->gpu);
    if (name && !strcmp(name, "metal")) return 1;
    if (name && !strcmp(name, "vulkan")) return 2;
    if (name && !strcmp(name, "direct3d12")) return 3;
    return fail("unrecognized GPU backend");
}
xu_int API(shader_formats)(xu_int id) {
    Device *d = device(id); return d ? ((p_SDL_GetGPUShaderFormats(d->gpu) >> 1) & 31) : -1;
}
xu_int API(buffer_new)(xu_int owner, xu_int size, xu_int usage) {
    Device *d = device(owner); if (!d) return -1;
    if (size <= 0 || size > UINT32_MAX || size % 4 || usage < 1 || usage > 63 || (usage & 3) == 3)
        return fail("invalid GPU buffer size, alignment or usage");
    Buffer *b = calloc(1, sizeof(*b));
    if (!b) return fail("GPU buffer allocation failed");
    b->id = identifier(); b->size = (Uint32)size;
    if (b->id < 0) { free(b); return -1; }
    SDL_GPUBufferCreateInfo info = {(Uint32)usage, (Uint32)size, 0};
    b->gpu = p_SDL_CreateGPUBuffer(d->gpu, &info);
    if (!b->gpu) { sdl_fail(); free(b); return -1; }
    b->next = d->buffers; d->buffers = b;
    return b->id;
}
xu_int API(buffer_close)(xu_int owner, xu_int id) {
    if (!on_main()) return -1;
    Device *d = devices;
    while (d && d->id != owner) d = d->next;
    if (!d) return 0;
    Buffer **link = &d->buffers;
    while (*link && (*link)->id != id) link = &(*link)->next;
    if (!*link) return 0;
    Buffer *b = *link; *link = b->next;
    // SDL defers release until already-submitted work stops using the buffer.
    p_SDL_ReleaseGPUBuffer(d->gpu, b->gpu); free(b);
    return 0;
}
xu_int API(upload)(xu_int owner, xu_int id, xu_int offset, const xu_u8_span *input) {
    Device *d = device(owner); if (!d) return -1;
    Buffer *b = buffer(d, id); if (!b) return -1;
    if (!input || !input->data || !region(b, offset, input->len)) return fail("invalid GPU upload byte span or region");
    Transfer *t = new_transfer(d, (Uint32)input->len, true, false); if (!t) return -1;
    void *mapped = p_SDL_MapGPUTransferBuffer(d->gpu, t->staging, false);
    if (!mapped) { sdl_fail(); free_transfer(d, t); return -1; }
    memcpy(mapped, input->data, (size_t)input->len);
    p_SDL_UnmapGPUTransferBuffer(d->gpu, t->staging);
    SDL_GPUCommandBuffer *command;
    SDL_GPUCopyPass *copy = begin_copy(d, t, &command); if (!copy) return -1;
    SDL_GPUTransferBufferLocation src = {t->staging, 0};
    SDL_GPUBufferRegion dst = {b->gpu, (Uint32)offset, (Uint32)input->len};
    p_SDL_UploadToGPUBuffer(copy, &src, &dst, false);
    return submit(d, t, command, copy);
}
xu_int API(copy)(xu_int owner, xu_int source, xu_int source_offset, xu_int destination, xu_int destination_offset, xu_int size) {
    Device *d = device(owner); if (!d) return -1;
    Buffer *src = buffer(d, source); if (!src) return -1;
    Buffer *dst = buffer(d, destination); if (!dst) return -1;
    if (src == dst) return fail("GPU copy requires distinct buffers");
    if (!region(src, source_offset, size) || !region(dst, destination_offset, size)) return -1;
    Transfer *t = new_transfer(d, 0, false, false); if (!t) return -1;
    SDL_GPUCommandBuffer *command;
    SDL_GPUCopyPass *copy = begin_copy(d, t, &command); if (!copy) return -1;
    SDL_GPUBufferLocation from = {src->gpu, (Uint32)source_offset}, to = {dst->gpu, (Uint32)destination_offset};
    p_SDL_CopyGPUBufferToBuffer(copy, &from, &to, (Uint32)size, false);
    return submit(d, t, command, copy);
}
xu_int API(download)(xu_int owner, xu_int id, xu_int offset, xu_int size) {
    Device *d = device(owner); if (!d) return -1;
    Buffer *b = buffer(d, id); if (!b || !region(b, offset, size)) return -1;
    Transfer *t = new_transfer(d, (Uint32)size, true, true); if (!t) return -1;
    SDL_GPUCommandBuffer *command;
    SDL_GPUCopyPass *copy = begin_copy(d, t, &command); if (!copy) return -1;
    SDL_GPUBufferRegion src = {b->gpu, (Uint32)offset, (Uint32)size};
    SDL_GPUTransferBufferLocation dst = {t->staging, 0};
    p_SDL_DownloadFromGPUBuffer(copy, &src, &dst);
    return submit(d, t, command, copy);
}
xu_int API(ready)(xu_int owner, xu_int id) {
    Device *d = device(owner); if (!d) return -1;
    Transfer *t = transfer(d, id); if (!t) return -1;
    if (!t->complete) t->complete = p_SDL_QueryGPUFence(d->gpu, t->fence);
    return t->complete ? 1 : 0;
}
xu_int API(wait)(xu_int owner, xu_int id) {
    Device *d = device(owner); if (!d) return -1;
    Transfer *t = transfer(d, id); if (!t) return -1;
    if (t->complete) return 0;
    if (!p_SDL_WaitForGPUFences(d->gpu, true, &t->fence, 1)) return sdl_fail();
    t->complete = true;
    return 0;
}
xu_int API(read)(xu_int owner, xu_int id, const xu_u8_span_mut *output) {
    Device *d = device(owner); if (!d) return -1;
    Transfer *t = transfer(d, id); if (!t) return -1;
    if (!t->download || !output || !output->data || output->len != t->size) return fail("GPU readback requires an exact-size mutable byte span");
    if (!t->complete) t->complete = p_SDL_QueryGPUFence(d->gpu, t->fence);
    if (!t->complete) return fail("GPU readback is not complete");
    void *mapped = p_SDL_MapGPUTransferBuffer(d->gpu, t->staging, false);
    if (!mapped) return sdl_fail();
    memcpy(output->data, mapped, t->size);
    p_SDL_UnmapGPUTransferBuffer(d->gpu, t->staging);
    return output->len;
}
xu_int API(transfer_close)(xu_int owner, xu_int id) {
    if (!on_main()) return -1;
    Device *d = devices;
    while (d && d->id != owner) d = d->next;
    if (!d) return 0;
    Transfer **link = &d->transfers;
    while (*link && (*link)->id != id) link = &(*link)->next;
    if (!*link) return 0;
    Transfer *t = *link; *link = t->next; free_transfer(d, t);
    return 0;
}
xu_int API(stats)(xu_int owner, xu_int field) {
    Device *d = device(owner); if (!d) return -1;
    xu_int total = 0;
    if (field < 0 || field > 3) return fail("invalid GPU accounting field");
    for (Buffer *b = d->buffers; b; b = b->next) {
        xu_int add = field == 0 ? 1 : field == 1 ? b->size : 0;
        if (add > LLONG_MAX - total) return fail("GPU accounting overflow"); total += add;
    }
    for (Transfer *t = d->transfers; t; t = t->next) {
        xu_int add = field == 2 ? 1 : field == 3 && t->staging ? t->size : 0;
        if (add > LLONG_MAX - total) return fail("GPU accounting overflow"); total += add;
    }
    return total;
}
