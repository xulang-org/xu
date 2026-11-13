#ifndef XU_SDL_WINDOW_ABI_H
#define XU_SDL_WINDOW_ABI_H
#include <stddef.h>
/* Altered declaration subset from SDL 3.4.14 video/event/GPU headers, not an SDL SDK.
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
typedef uint64_t Uint64;
typedef struct SDL_Window SDL_Window;
typedef Uint32 SDL_WindowID;
typedef Uint64 SDL_WindowFlags;
typedef struct { Uint32 type, reserved; Uint64 timestamp; SDL_WindowID windowID; Sint32 data1, data2; } SDL_WindowEvent;
typedef union SDL_Event { Uint32 type; Uint64 alignment; SDL_WindowEvent window; Uint8 padding[128]; } SDL_Event;
typedef bool (*SDL_EventFilter)(void *, SDL_Event *);
enum { SDL_EVENT_QUIT=0x100, SDL_EVENT_WINDOW_FIRST=0x202, SDL_EVENT_WINDOW_CLOSE_REQUESTED=0x210,
       SDL_EVENT_WINDOW_LAST=0x21a, SDL_EVENT_USER=0x8000 };
#define SDL_WINDOW_HIDDEN 0x8ull
#define SDL_WINDOW_RESIZABLE 0x20ull
#define SDL_WINDOW_MINIMIZED 0x40ull
#define SDL_WINDOW_INPUT_FOCUS 0x200ull
#define SDL_WINDOW_HIGH_PIXEL_DENSITY 0x2000ull
SDL_Window *SDL_CreateWindow(const char *, int, int, SDL_WindowFlags);
void SDL_DestroyWindow(SDL_Window *);
SDL_WindowID SDL_GetWindowID(SDL_Window *);
SDL_WindowFlags SDL_GetWindowFlags(SDL_Window *);
bool SDL_GetWindowSize(SDL_Window *, int *, int *);
bool SDL_GetWindowSizeInPixels(SDL_Window *, int *, int *);
bool SDL_SetWindowSize(SDL_Window *, int, int);
bool SDL_ShowWindow(SDL_Window *);
bool SDL_HideWindow(SDL_Window *);
bool SDL_MinimizeWindow(SDL_Window *);
bool SDL_RestoreWindow(SDL_Window *);
void SDL_PumpEvents(void);
void SDL_FilterEvents(SDL_EventFilter, void *);
SDL_Window *SDL_GetWindowFromEvent(const SDL_Event *);
typedef enum { SDL_GPU_PRESENTMODE_VSYNC, SDL_GPU_PRESENTMODE_IMMEDIATE, SDL_GPU_PRESENTMODE_MAILBOX } SDL_GPUPresentMode;
typedef enum { SDL_GPU_SWAPCHAINCOMPOSITION_SDR, SDL_GPU_SWAPCHAINCOMPOSITION_SDR_LINEAR,
    SDL_GPU_SWAPCHAINCOMPOSITION_HDR_EXTENDED_LINEAR, SDL_GPU_SWAPCHAINCOMPOSITION_HDR10_ST2084 } SDL_GPUSwapchainComposition;
bool SDL_ClaimWindowForGPUDevice(SDL_GPUDevice *, SDL_Window *);
void SDL_ReleaseWindowFromGPUDevice(SDL_GPUDevice *, SDL_Window *);
bool SDL_WindowSupportsGPUPresentMode(SDL_GPUDevice *, SDL_Window *, SDL_GPUPresentMode);
bool SDL_SetGPUSwapchainParameters(SDL_GPUDevice *, SDL_Window *, SDL_GPUSwapchainComposition, SDL_GPUPresentMode);
SDL_GPUTextureFormat SDL_GetGPUSwapchainTextureFormat(SDL_GPUDevice *, SDL_Window *);
bool SDL_WaitAndAcquireGPUSwapchainTexture(SDL_GPUCommandBuffer *, SDL_Window *, SDL_GPUTexture **, Uint32 *, Uint32 *);
bool SDL_SubmitGPUCommandBuffer(SDL_GPUCommandBuffer *);
#endif
_Static_assert(sizeof(SDL_Event)==128 && _Alignof(SDL_Event)==8, "SDL event ABI");
_Static_assert(sizeof(SDL_WindowEvent)==32 && offsetof(SDL_WindowEvent,windowID)==16, "SDL window event ABI");
_Static_assert(SDL_EVENT_WINDOW_CLOSE_REQUESTED==0x210, "SDL window close event ABI");
#endif
