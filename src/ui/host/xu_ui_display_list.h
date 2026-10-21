// Immutable vector fragments. Creation pins a resource snapshot and compiles it
// once on the calling worker; replay inherits the caller CTM/clip but isolates
// its pen/state. Background-clearing commands are not allowed in fragments.
#pragma once
#include "xu_draw_frame.h"
#define XU_UI_LIST_MAX_COUNT 64u
#define XU_UI_LIST_MAX_COST (64u * 1024u * 1024u)
#define XU_UI_LIST_SINGLE_COST (16u * 1024u * 1024u)
#define XU_UI_LIST_MAX_NESTING 16u
#ifdef __cplusplus
extern "C" {
#endif
typedef struct XuUiDisplayList XuUiDisplayList;
typedef void *(*XuUiListCompile)(const XuUiFrameLease *);
typedef void (*XuUiListDestroy)(void *);
// Native callbacks must allow creation/destruction on workers, never create UI
// widgets or reenter the registry. Destroy may run during canvas revocation.
int xu_ui_display_list_set_backend(XuUiListCompile, XuUiListDestroy);
uint64_t xu_ui_display_list_reserve(void);
void xu_ui_display_list_abandon(uint64_t);
int xu_ui_display_list_create(uint64_t, const void *, unsigned);
int xu_ui_display_list_dispose(uint64_t, unsigned canvas, unsigned generation);
int xu_ui_display_list_info(uint64_t, unsigned *generation, unsigned *cost);
void xu_ui_display_list_retain(XuUiDisplayList *);
void xu_ui_display_list_release(XuUiDisplayList *);
void *xu_ui_display_list_native(const XuUiDisplayList *);
XuUiDisplayList *xu_ui_frame_list(const XuUiFrameLease *, uint64_t);
unsigned xu_ui_display_list_live_cost(void);
#ifdef __cplusplus
}
#endif
