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
typedef uint16_t Uint16;
typedef struct SDL_Window SDL_Window;
typedef Uint32 SDL_WindowID;
typedef Uint64 SDL_WindowFlags;
typedef struct { Uint32 type, reserved; Uint64 timestamp; SDL_WindowID windowID; Sint32 data1, data2; } SDL_WindowEvent;
typedef struct { Uint32 type, reserved; Uint64 timestamp; } SDL_CommonEvent;
typedef struct { Uint32 type, reserved; Uint64 timestamp; SDL_WindowID windowID; Uint32 which;
    int scancode; Uint32 key; Uint16 mod, raw; bool down, repeat; } SDL_KeyboardEvent;
typedef struct { Uint32 type, reserved; Uint64 timestamp; SDL_WindowID windowID; const char *text;
    Sint32 start, length; } SDL_TextEditingEvent;
typedef struct { Uint32 type, reserved; Uint64 timestamp; SDL_WindowID windowID; const char *text; } SDL_TextInputEvent;
typedef struct { Uint32 type, reserved; Uint64 timestamp; SDL_WindowID windowID; Uint32 which, state;
    float x, y, xrel, yrel; } SDL_MouseMotionEvent;
typedef struct { Uint32 type, reserved; Uint64 timestamp; SDL_WindowID windowID; Uint32 which;
    Uint8 button; bool down; Uint8 clicks, padding; float x,y; } SDL_MouseButtonEvent;
typedef struct { Uint32 type, reserved; Uint64 timestamp; SDL_WindowID windowID; Uint32 which;
    float x,y; int direction; float mouse_x,mouse_y; Sint32 integer_x,integer_y; } SDL_MouseWheelEvent;
typedef union SDL_Event { Uint32 type; Uint64 alignment; SDL_CommonEvent common; SDL_WindowEvent window;
    SDL_KeyboardEvent key; SDL_TextEditingEvent edit; SDL_TextInputEvent text;
    SDL_MouseMotionEvent motion; SDL_MouseButtonEvent button; SDL_MouseWheelEvent wheel; Uint8 padding[128]; } SDL_Event;
typedef bool (*SDL_EventFilter)(void *, SDL_Event *);
enum { SDL_EVENT_QUIT=0x100, SDL_EVENT_WINDOW_FIRST=0x202, SDL_EVENT_WINDOW_RESIZED=0x206,
    SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED=0x207, SDL_EVENT_WINDOW_FOCUS_GAINED=0x20e,
    SDL_EVENT_WINDOW_FOCUS_LOST=0x20f, SDL_EVENT_WINDOW_CLOSE_REQUESTED=0x210, SDL_EVENT_WINDOW_LAST=0x21a,
    SDL_EVENT_KEY_DOWN=0x300, SDL_EVENT_KEY_UP=0x301, SDL_EVENT_TEXT_EDITING=0x302, SDL_EVENT_TEXT_INPUT=0x303,
    SDL_EVENT_MOUSE_MOTION=0x400, SDL_EVENT_MOUSE_BUTTON_DOWN=0x401, SDL_EVENT_MOUSE_BUTTON_UP=0x402,
    SDL_EVENT_MOUSE_WHEEL=0x403, SDL_EVENT_USER=0x8000 };
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
bool SDL_StartTextInput(SDL_Window *);
bool SDL_StopTextInput(SDL_Window *);
bool SDL_TextInputActive(SDL_Window *);
bool SDL_SetTextInputArea(SDL_Window *,const SDL_Rect *,int);
bool SDL_SetWindowRelativeMouseMode(SDL_Window *,bool);
bool SDL_GetWindowRelativeMouseMode(SDL_Window *);
bool SDL_SetWindowMouseGrab(SDL_Window *,bool);
bool SDL_GetWindowMouseGrab(SDL_Window *);
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
_Static_assert(sizeof(SDL_KeyboardEvent)==40 && offsetof(SDL_KeyboardEvent,mod)==32, "SDL keyboard ABI");
_Static_assert(sizeof(SDL_TextInputEvent)==32 && offsetof(SDL_TextInputEvent,text)==24, "SDL text ABI");
_Static_assert(sizeof(SDL_TextEditingEvent)==40 && offsetof(SDL_TextEditingEvent,start)==32, "SDL editing ABI");
_Static_assert(sizeof(SDL_MouseMotionEvent)==48 && offsetof(SDL_MouseMotionEvent,x)==28, "SDL motion ABI");
_Static_assert(sizeof(SDL_MouseButtonEvent)==40 && offsetof(SDL_MouseButtonEvent,x)==28, "SDL button ABI");
_Static_assert(offsetof(SDL_MouseWheelEvent,mouse_x)==36, "SDL wheel ABI");
_Static_assert(sizeof(SDL_Event)==128 && _Alignof(SDL_Event)==8, "SDL event ABI");
_Static_assert(sizeof(SDL_WindowEvent)==32 && offsetof(SDL_WindowEvent,windowID)==16, "SDL window event ABI");
_Static_assert(SDL_EVENT_WINDOW_CLOSE_REQUESTED==0x210, "SDL window close event ABI");
#endif
