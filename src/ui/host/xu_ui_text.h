// Immutable text layouts. Coordinates and font sizes are logical pixels.
#pragma once
#include <stdint.h>
#define XU_UI_TEXT_MAX_LENGTH 16384u
#define XU_UI_TEXT_MAX_COST (32u * 1024u * 1024u)
#define XU_UI_TEXT_LAYOUT_MAX_COST (4u * 1024u * 1024u)
#ifdef __cplusplus
extern "C" {
#endif
typedef struct XuUiText XuUiText;
// options: size, wrap width (0 = no wrap), weight (100..900), italic (0/1),
// alignment (0 left, 1 center, 2 right), line height (0 = native default).
// metrics: advance width, height, first baseline, line count, ink x/y/w/h.
// Callbacks own no UI widgets and must permit creation/destruction on workers.
// They must not reenter this bridge; destroy can run during canvas revocation.
// cost accounts retained native layout/geometry, excluding OS font caches.
typedef void *(*XuUiTextCreate)(const char *, unsigned, const char *, unsigned,
                               const double *, double *, unsigned *);
typedef void (*XuUiTextDestroy)(void *);
// query modes: 0 point hit, 1 caret at UTF-8 byte index + trailing edge.
// result: cluster byte index/length, trailing, inside, caret x/y/height.
typedef int (*XuUiTextQuery)(void *, unsigned, unsigned, unsigned, double, double, double *);
int xu_ui_text_set_backend(XuUiTextCreate, XuUiTextDestroy);
int xu_ui_text_set_query_backend(XuUiTextQuery);
// Called by the pack entry before Xu initializers, including startup layouts.
void xu_draw_text_init(void);
uint64_t xu_ui_text_reserve(void);
void xu_ui_text_abandon(uint64_t);
int xu_ui_text_create(uint64_t, unsigned canvas, unsigned generation,
                      const char *family, unsigned family_length,
                      const char *text, unsigned text_length, const double *options6);
int xu_ui_text_dispose(uint64_t, unsigned canvas, unsigned generation);
int xu_ui_text_info(uint64_t, double *metrics8, unsigned *generation);
int xu_ui_text_query(uint64_t, unsigned canvas, unsigned generation, unsigned mode,
                     unsigned index, unsigned trailing, double x, double y, double *result7);
void xu_ui_text_retain(XuUiText *);
void xu_ui_text_release(XuUiText *);
// The caller holds a reference or frame lease for the duration of access.
void *xu_ui_text_native(const XuUiText *);
unsigned xu_ui_text_live_cost(void);
#ifdef __cplusplus
}
#endif
