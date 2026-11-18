#ifdef __ANDROID__
#define SDL_MAIN_HANDLED 1
#include <pthread.h>
#else
#define SDL_MAIN_USE_CALLBACKS 1
#endif
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include "native/host/phone/game.h"
#include "callback_inbox.h"
#include <stdatomic.h>
#include "resources.h"

#define XU_EXPORT __attribute__((used, visibility("default")))

static _Atomic bool stopping, background;
static _Atomic long long resume_epoch;

XU_EXPORT long long xu_phone_game_resume_epoch(void) { return atomic_load(&resume_epoch); }
XU_EXPORT int xu_phone_game_set_trap_back(int enabled) {
    return SDL_SetHint(SDL_HINT_ANDROID_TRAP_BACK_BUTTON, enabled ? "1" : "0") ? 0 : -1;
}

/* Pin and resolve every SDL 3 symbol needed by Xu's pure-Xu SDL backend so
 * static iOS archives retain them even under release symbol stripping. */
typedef struct {
    const char *name;
    void *fn;
} XuSdlSymEntry;

#define XU_SDL_SYM(fn) {#fn, (void *)(uintptr_t)&fn}
static const XuSdlSymEntry xu_sdl_sym_table[] = {
    XU_SDL_SYM(SDL_SetMainReady),
    XU_SDL_SYM(SDL_IsMainThread),
    XU_SDL_SYM(SDL_InitSubSystem),
    XU_SDL_SYM(SDL_QuitSubSystem),
    XU_SDL_SYM(SDL_GetError),
    XU_SDL_SYM(SDL_CreateWindow),
    XU_SDL_SYM(SDL_DestroyWindow),
    XU_SDL_SYM(SDL_GetWindowID),
    XU_SDL_SYM(SDL_GetWindowFlags),
    XU_SDL_SYM(SDL_GetWindowSize),
    XU_SDL_SYM(SDL_GetWindowSizeInPixels),
    XU_SDL_SYM(SDL_GetWindowSafeArea),
    XU_SDL_SYM(SDL_SetWindowSize),
    XU_SDL_SYM(SDL_ShowWindow),
    XU_SDL_SYM(SDL_HideWindow),
    XU_SDL_SYM(SDL_MinimizeWindow),
    XU_SDL_SYM(SDL_RestoreWindow),
    XU_SDL_SYM(SDL_PumpEvents),
    XU_SDL_SYM(SDL_FilterEvents),
    XU_SDL_SYM(SDL_GetWindowFromEvent),
    XU_SDL_SYM(SDL_StartTextInput),
    XU_SDL_SYM(SDL_StopTextInput),
    XU_SDL_SYM(SDL_TextInputActive),
    XU_SDL_SYM(SDL_SetTextInputArea),
    XU_SDL_SYM(SDL_SetWindowRelativeMouseMode),
    XU_SDL_SYM(SDL_GetWindowRelativeMouseMode),
    XU_SDL_SYM(SDL_SetWindowMouseGrab),
    XU_SDL_SYM(SDL_GetWindowMouseGrab),
    XU_SDL_SYM(SDL_GetWindowSurface),
    XU_SDL_SYM(SDL_CreateSurfaceFrom),
    XU_SDL_SYM(SDL_BlitSurface),
    XU_SDL_SYM(SDL_DestroySurface),
    XU_SDL_SYM(SDL_UpdateWindowSurface),
    XU_SDL_SYM(SDL_CreateGPUDevice),
    XU_SDL_SYM(SDL_DestroyGPUDevice),
    XU_SDL_SYM(SDL_GetGPUDeviceDriver),
    XU_SDL_SYM(SDL_GetGPUShaderFormats),
    XU_SDL_SYM(SDL_CreateGPUBuffer),
    XU_SDL_SYM(SDL_ReleaseGPUBuffer),
    XU_SDL_SYM(SDL_CreateGPUTransferBuffer),
    XU_SDL_SYM(SDL_ReleaseGPUTransferBuffer),
    XU_SDL_SYM(SDL_MapGPUTransferBuffer),
    XU_SDL_SYM(SDL_UnmapGPUTransferBuffer),
    XU_SDL_SYM(SDL_AcquireGPUCommandBuffer),
    XU_SDL_SYM(SDL_CancelGPUCommandBuffer),
    XU_SDL_SYM(SDL_BeginGPUCopyPass),
    XU_SDL_SYM(SDL_EndGPUCopyPass),
    XU_SDL_SYM(SDL_UploadToGPUBuffer),
    XU_SDL_SYM(SDL_CopyGPUBufferToBuffer),
    XU_SDL_SYM(SDL_DownloadFromGPUBuffer),
    XU_SDL_SYM(SDL_SubmitGPUCommandBufferAndAcquireFence),
    XU_SDL_SYM(SDL_QueryGPUFence),
    XU_SDL_SYM(SDL_WaitForGPUFences),
    XU_SDL_SYM(SDL_ReleaseGPUFence),
    XU_SDL_SYM(SDL_WaitForGPUIdle),
    XU_SDL_SYM(SDL_SubmitGPUCommandBuffer),
    XU_SDL_SYM(SDL_CreateGPUTexture),
    XU_SDL_SYM(SDL_ReleaseGPUTexture),
    XU_SDL_SYM(SDL_GPUTextureSupportsFormat),
    XU_SDL_SYM(SDL_CreateGPUSampler),
    XU_SDL_SYM(SDL_ReleaseGPUSampler),
    XU_SDL_SYM(SDL_CreateGPUShader),
    XU_SDL_SYM(SDL_ReleaseGPUShader),
    XU_SDL_SYM(SDL_CreateGPUGraphicsPipeline),
    XU_SDL_SYM(SDL_ReleaseGPUGraphicsPipeline),
    XU_SDL_SYM(SDL_UploadToGPUTexture),
    XU_SDL_SYM(SDL_DownloadFromGPUTexture),
    XU_SDL_SYM(SDL_GenerateMipmapsForGPUTexture),
    XU_SDL_SYM(SDL_BeginGPURenderPass),
    XU_SDL_SYM(SDL_EndGPURenderPass),
    XU_SDL_SYM(SDL_BindGPUGraphicsPipeline),
    XU_SDL_SYM(SDL_BindGPUVertexBuffers),
    XU_SDL_SYM(SDL_BindGPUIndexBuffer),
    XU_SDL_SYM(SDL_BindGPUVertexSamplers),
    XU_SDL_SYM(SDL_BindGPUFragmentSamplers),
    XU_SDL_SYM(SDL_PushGPUVertexUniformData),
    XU_SDL_SYM(SDL_PushGPUFragmentUniformData),
    XU_SDL_SYM(SDL_DrawGPUPrimitives),
    XU_SDL_SYM(SDL_DrawGPUIndexedPrimitives),
    XU_SDL_SYM(SDL_SetGPUViewport),
    XU_SDL_SYM(SDL_SetGPUScissor),
    XU_SDL_SYM(SDL_CreateGPUComputePipeline),
    XU_SDL_SYM(SDL_ReleaseGPUComputePipeline),
    XU_SDL_SYM(SDL_BeginGPUComputePass),
    XU_SDL_SYM(SDL_EndGPUComputePass),
    XU_SDL_SYM(SDL_BindGPUComputePipeline),
    XU_SDL_SYM(SDL_BindGPUComputeStorageBuffers),
    XU_SDL_SYM(SDL_PushGPUComputeUniformData),
    XU_SDL_SYM(SDL_DispatchGPUCompute),
    XU_SDL_SYM(SDL_ClaimWindowForGPUDevice),
    XU_SDL_SYM(SDL_ReleaseWindowFromGPUDevice),
    XU_SDL_SYM(SDL_WindowSupportsGPUPresentMode),
    XU_SDL_SYM(SDL_SetGPUSwapchainParameters),
    XU_SDL_SYM(SDL_GetGPUSwapchainTextureFormat),
    XU_SDL_SYM(SDL_WaitAndAcquireGPUSwapchainTexture)
};
#undef XU_SDL_SYM

XU_EXPORT void *xu_phone_sdl_sym(const char *name) {
    if (!name) return NULL;
    size_t n = sizeof(xu_sdl_sym_table) / sizeof(xu_sdl_sym_table[0]);
    for (size_t i = 0; i < n; ++i) {
        if (strcmp(xu_sdl_sym_table[i].name, name) == 0) return xu_sdl_sym_table[i].fn;
    }
    return NULL;
}

static void handle_sdl_event(const SDL_Event *event) {
    if (event->type == SDL_EVENT_QUIT || event->type == SDL_EVENT_TERMINATING ||
        event->type == SDL_EVENT_WINDOW_CLOSE_REQUESTED) atomic_store(&stopping, true);
    if (event->type == SDL_EVENT_WILL_ENTER_BACKGROUND) {
        atomic_store(&background, true);
        xu_sdl_callback_suspend();
    }
    if (event->type == SDL_EVENT_DID_ENTER_FOREGROUND) {
        atomic_fetch_add(&resume_epoch, 1);
        atomic_store(&background, false);
    }
    xu_sdl_callback_event(event);
}

#ifdef __ANDROID__
static bool immediate_sdl_event(Uint32 type) {
    switch (type) {
    case SDL_EVENT_TERMINATING:
    case SDL_EVENT_LOW_MEMORY:
    case SDL_EVENT_WILL_ENTER_BACKGROUND:
    case SDL_EVENT_DID_ENTER_BACKGROUND:
    case SDL_EVENT_WILL_ENTER_FOREGROUND:
    case SDL_EVENT_DID_ENTER_FOREGROUND:
        return true;
    default:
        return false;
    }
}
static bool SDLCALL android_event_watch(void *userdata, SDL_Event *event) {
    (void)userdata;
    if (immediate_sdl_event(event->type)) handle_sdl_event(event);
    return true;
}
static int android_pump_frame(void) {
    for (;;) {
        SDL_PumpEvents();
        SDL_Event events[16];
        for (;;) {
            int count = SDL_PeepEvents(events, 16, SDL_GETEVENT, SDL_EVENT_FIRST, SDL_EVENT_LAST);
            if (count <= 0) break;
            for (int i = 0; i < count; ++i) {
                if (!immediate_sdl_event(events[i].type)) handle_sdl_event(&events[i]);
            }
        }
        if (atomic_load(&stopping)) return 0;
        if (!atomic_load(&background)) return 1;
        SDL_Delay(16);
    }
}
static void *android_worker_main(void *arg) {
    (void)arg;
    atomic_store(&stopping, false);
    atomic_store(&background, false);
    SDL_SetMainReady();
    if (!SDL_Init(SDL_INIT_VIDEO)) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "SDL initialization: %s", SDL_GetError());
        return (void *)1;
    }
    xu_sdl_callback_begin();
    if (!prepare_resources()) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "Xu resource preparation failed: %s", SDL_GetError());
        xu_sdl_callback_end();
        SDL_Quit();
        return (void *)1;
    }
    SDL_AddEventWatch(android_event_watch, NULL);
    long status = xu_phone_game_run_android(android_pump_frame);
    SDL_RemoveEventWatch(android_event_watch, NULL);
    if (status != 0) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "Xu game: Xu application returned a failure status (%ld)", status);
    }
    xu_sdl_callback_end();
    SDL_Quit();
    return (void *)(intptr_t)(status ? 1 : 0);
}
SDLMAIN_DECLSPEC int SDLCALL SDL_main(int argc, char *argv[]) {
    (void)argc; (void)argv;
    pthread_attr_t attr;
    if (pthread_attr_init(&attr) != 0) return 1;
    if (pthread_attr_setstacksize(&attr, 8 * 1024 * 1024) != 0) {
        pthread_attr_destroy(&attr);
        return 1;
    }
    pthread_t worker;
    int rc = pthread_create(&worker, &attr, android_worker_main, NULL);
    pthread_attr_destroy(&attr);
    if (rc != 0) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "Xu game worker thread creation failed: %d", rc);
        return 1;
    }
    void *exit_value = NULL;
    pthread_join(worker, &exit_value);
    return (int)(intptr_t)exit_value;
}
#else
static SDL_AppResult result(int status) {
    if (status == XU_GAME_READY) return SDL_APP_CONTINUE;
    if (status == XU_GAME_DONE) return SDL_APP_SUCCESS;
    SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "Xu game: %s", xu_phone_game_error());
    return SDL_APP_FAILURE;
}
SDL_AppResult SDL_AppInit(void **state, int argc, char **argv) {
    (void)argc; (void)argv;
    if (!SDL_Init(SDL_INIT_VIDEO)) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "SDL initialization: %s", SDL_GetError());
        return SDL_APP_FAILURE;
    }
    xu_sdl_callback_begin();
    if (!prepare_resources()) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "Xu resource preparation failed: %s", SDL_GetError());
        return SDL_APP_FAILURE;
    }
    XuPhoneGame *game = NULL;
    int status = xu_phone_game_create(&game);
    *state = game;
    return result(status);
}
SDL_AppResult SDL_AppEvent(void *state, SDL_Event *event) {
    (void)state;
    handle_sdl_event(event);
    return SDL_APP_CONTINUE;
}
SDL_AppResult SDL_AppIterate(void *state) {
    XuPhoneGame *game = state;
    if (atomic_load(&stopping)) return result(xu_phone_game_stop(game));
    if (atomic_load(&background)) { SDL_Delay(16); return SDL_APP_CONTINUE; }
    return result(xu_phone_game_step(game));
}
void SDL_AppQuit(void *state, SDL_AppResult status) {
    (void)status;
    XuPhoneGame *game = state;
    if (game) {
        xu_phone_game_stop(game);
        if (xu_phone_game_destroy(game) != XU_GAME_DONE)
            SDL_LogError(SDL_LOG_CATEGORY_APPLICATION, "Xu shutdown: %s", xu_phone_game_error());
    }
    xu_sdl_callback_end();
}
#endif
