// Immutable, canvas-scoped bitmap resources. No native/C++ layout crosses this ABI.
#pragma once
#include <stdint.h>
#define XU_UI_IMAGE_MAX_COUNT 256u
#define XU_UI_IMAGE_MAX_BYTES (64u * 1024u * 1024u)
#define XU_UI_IMAGE_MAX_DIMENSION 16384u
#ifdef __cplusplus
extern "C" {
#endif
typedef struct XuUiBitmap XuUiBitmap;
uint64_t xu_ui_image_reserve(void);
void xu_ui_image_abandon(uint64_t id);
int xu_ui_image_create_rgba(uint64_t id, unsigned canvas, unsigned generation, unsigned width, unsigned height,
                            unsigned stride, const void *rgba, unsigned length);
// PNG/JPEG from memory. Decoding is bounded separately from retained pixels.
int xu_ui_image_create_encoded(uint64_t id, unsigned canvas, unsigned generation, const void *encoded, unsigned length);
int xu_ui_image_load_file(uint64_t id, unsigned canvas, unsigned generation, const char *utf8_path, unsigned length);
int xu_ui_image_update_rgba(uint64_t id, unsigned canvas, unsigned generation, unsigned width, unsigned height,
                            unsigned stride, const void *rgba, unsigned length);
int xu_ui_surface_composite(uint64_t id,unsigned canvas,unsigned generation,uint64_t backdrop,uint64_t source,unsigned mode,unsigned opacity);
int xu_ui_image_dispose(uint64_t id, unsigned canvas, unsigned generation);
int xu_ui_image_info(uint64_t id, unsigned *width, unsigned *height, unsigned *generation);
/* Pixels are tightly packed top-left premultiplied BGRA8. The caller must hold
 * a bitmap reference (or an owned frame lease) while accessing this pointer. */
const unsigned char *xu_ui_bitmap_pixels(const XuUiBitmap *, unsigned *width, unsigned *height);
void xu_ui_bitmap_retain(XuUiBitmap *);
void xu_ui_bitmap_release(XuUiBitmap *);
unsigned xu_ui_image_live_bytes(void);
#ifdef __cplusplus
}
#endif
