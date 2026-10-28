// Native children of a draw canvas. Handles and generations never repeat.
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define XU_UI_NATIVE_VIEW_MAX_COUNT 32u
#define XU_UI_NATIVE_VIEW_ID_BASE 0x40000000u
/* meta: id,generation,parent_window,parent_generation,kind,state,flags,focus_epoch.
 * geometry: frame x/y/w/h, clip x/y/w/h, corner radius, in logical top-left units.
 * state 1=creating, 2=ready. flags: visible=1, enabled=2, focused=4. */
int xu_ui_native_view_info(unsigned id,unsigned generation,unsigned *meta8,double *geometry9);
uint64_t xu_ui_native_view_revision(unsigned id,unsigned generation);
int xu_ui_native_view_ready(unsigned id,unsigned generation);
void xu_ui_native_view_close(unsigned id,unsigned generation);
void xu_ui_native_view_event(unsigned id,unsigned generation,const char *payload);
unsigned xu_ui_canvas_for_generation(unsigned window,unsigned generation);
#ifdef __cplusplus
}
#endif
