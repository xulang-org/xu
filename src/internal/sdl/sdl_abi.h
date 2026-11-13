#ifndef XU_GPU_SDL_ABI_H
#define XU_GPU_SDL_ABI_H
/* Private SDL 3.2+ ABI subset. No SDL headers are required by SDK consumers.
 * Checked against upstream SDL_gpu.h in the host acceptance build.
 * These declarations are not Xu's public API. */
#ifdef XU_GPU_VERIFY_SDL
#define SDL_MAIN_HANDLED
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#else
#include <stdbool.h>
#include <stdint.h>
typedef uint32_t Uint32;
typedef struct SDL_GPUDevice SDL_GPUDevice;
typedef struct SDL_GPUBuffer SDL_GPUBuffer;
typedef struct SDL_GPUTransferBuffer SDL_GPUTransferBuffer;
typedef struct SDL_GPUCommandBuffer SDL_GPUCommandBuffer;
typedef struct SDL_GPUCopyPass SDL_GPUCopyPass;
typedef struct SDL_GPUFence SDL_GPUFence;
typedef struct { Uint32 usage, size, props; } SDL_GPUBufferCreateInfo;
typedef struct { int usage; Uint32 size, props; } SDL_GPUTransferBufferCreateInfo;
typedef struct { SDL_GPUBuffer *buffer; Uint32 offset; } SDL_GPUBufferLocation;
typedef struct { SDL_GPUBuffer *buffer; Uint32 offset, size; } SDL_GPUBufferRegion;
typedef struct { SDL_GPUTransferBuffer *transfer_buffer; Uint32 offset; } SDL_GPUTransferBufferLocation;
void SDL_SetMainReady(void);
bool SDL_IsMainThread(void);
bool SDL_InitSubSystem(Uint32 flags);
void SDL_QuitSubSystem(Uint32 flags);
const char *SDL_GetError(void);
SDL_GPUDevice *SDL_CreateGPUDevice(Uint32 formats, bool debug, const char *driver);
void SDL_DestroyGPUDevice(SDL_GPUDevice *device);
const char *SDL_GetGPUDeviceDriver(SDL_GPUDevice *device);
Uint32 SDL_GetGPUShaderFormats(SDL_GPUDevice *device);
SDL_GPUBuffer *SDL_CreateGPUBuffer(SDL_GPUDevice *, const SDL_GPUBufferCreateInfo *);
void SDL_ReleaseGPUBuffer(SDL_GPUDevice *, SDL_GPUBuffer *);
SDL_GPUTransferBuffer *SDL_CreateGPUTransferBuffer(SDL_GPUDevice *, const SDL_GPUTransferBufferCreateInfo *);
void SDL_ReleaseGPUTransferBuffer(SDL_GPUDevice *, SDL_GPUTransferBuffer *);
void *SDL_MapGPUTransferBuffer(SDL_GPUDevice *, SDL_GPUTransferBuffer *, bool);
void SDL_UnmapGPUTransferBuffer(SDL_GPUDevice *, SDL_GPUTransferBuffer *);
SDL_GPUCommandBuffer *SDL_AcquireGPUCommandBuffer(SDL_GPUDevice *);
bool SDL_CancelGPUCommandBuffer(SDL_GPUCommandBuffer *);
SDL_GPUCopyPass *SDL_BeginGPUCopyPass(SDL_GPUCommandBuffer *);
void SDL_EndGPUCopyPass(SDL_GPUCopyPass *);
void SDL_UploadToGPUBuffer(SDL_GPUCopyPass *, const SDL_GPUTransferBufferLocation *, const SDL_GPUBufferRegion *, bool);
void SDL_CopyGPUBufferToBuffer(SDL_GPUCopyPass *, const SDL_GPUBufferLocation *, const SDL_GPUBufferLocation *, Uint32, bool);
void SDL_DownloadFromGPUBuffer(SDL_GPUCopyPass *, const SDL_GPUBufferRegion *, const SDL_GPUTransferBufferLocation *);
SDL_GPUFence *SDL_SubmitGPUCommandBufferAndAcquireFence(SDL_GPUCommandBuffer *);
bool SDL_QueryGPUFence(SDL_GPUDevice *, SDL_GPUFence *);
bool SDL_WaitForGPUFences(SDL_GPUDevice *, bool, SDL_GPUFence *const *, Uint32);
void SDL_ReleaseGPUFence(SDL_GPUDevice *, SDL_GPUFence *);
bool SDL_WaitForGPUIdle(SDL_GPUDevice *);
#endif
_Static_assert(sizeof(SDL_GPUBufferCreateInfo) == 12, "SDL buffer ABI");
_Static_assert(sizeof(SDL_GPUTransferBufferCreateInfo) == 12, "SDL transfer ABI");
_Static_assert(sizeof(SDL_GPUBufferLocation) == 16, "SDL location ABI");
_Static_assert(sizeof(SDL_GPUBufferRegion) == 16, "SDL region ABI");
_Static_assert(sizeof(SDL_GPUTransferBufferLocation) == 16, "SDL staging location ABI");
#endif
