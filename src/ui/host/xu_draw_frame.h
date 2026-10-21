// Versioned little-endian draw frames. No C++ object layout crosses the ABI.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <math.h>

#define XU_DRAW_FRAME_MAX_BYTES (4u * 1024u * 1024u)
#define XU_DRAW_FRAME_MAX_COMMANDS 100000u
#define XU_DRAW_FRAME_MAX_PENDING 3u
#define XU_DRAW_FRAME_HEADER_BYTES 32u
#define XU_DRAW_TRANSFORM_LIMIT 1.0e9
#define XU_DRAW_MAX_CANVASES 64u

enum XuDrawOpcode {
  XDF_BACKGROUND = 1, XDF_COLOR, XDF_FILL, XDF_STROKE, XDF_WIDTH,
  XDF_SAVE, XDF_RESTORE, XDF_ORIGIN, XDF_TRANSLATE, XDF_ROTATE, XDF_SCALE,
  XDF_CLIP_RECT, XDF_RECT, XDF_RECT_LINE, XDF_FILL_RECT, XDF_STROKE_RECT,
  XDF_LINE, XDF_TEXT, XDF_CIRCLE, XDF_ELLIPSE, XDF_TRIANGLE, XDF_IMAGE, XDF_TEXT_LAYOUT, XDF_PATH, XDF_DISPLAY_LIST
};

typedef struct XuDrawCommand {
  unsigned opcode;
  unsigned rgba;
  double values[8];
  const char *text;
  unsigned text_len;
  uint64_t image_id;
} XuDrawCommand;

// Column-vector affine transform: (a*x + c*y + tx, b*x + d*y + ty).
// Frame transforms are relative to the host's camera/DPI transform. Checking
// each scalar alone is insufficient: repeated legal scales can overflow the
// native CTM or destroy its inverse, including before a later origin/pop.
typedef struct XuDrawTransform { double a, b, c, d, tx, ty; } XuDrawTransform;

static inline XuDrawTransform xdf_identity(void) {
  XuDrawTransform result = {1, 0, 0, 1, 0, 0};
  return result;
}

static inline int xdf_inverse_bounded(double a, double b, double c, double d, double limit) {
  double det = a * d - b * c;
  return isfinite(det) && det != 0 && fabs(d / det) <= limit &&
         fabs(b / det) <= limit && fabs(c / det) <= limit && fabs(a / det) <= limit;
}

static inline int xdf_transform_valid(const XuDrawTransform *t) {
  const double values[] = {t->a, t->b, t->c, t->d, t->tx, t->ty};
  for (unsigned i = 0; i < 6; ++i) {
    if (!isfinite(values[i]) || fabs(values[i]) > XU_DRAW_TRANSFORM_LIMIT) return 0;
  }
  if (!xdf_inverse_bounded(t->a, t->b, t->c, t->d, XU_DRAW_TRANSFORM_LIMIT)) return 0;
  // GDI+ uses float matrix coefficients. Reject a CTM which becomes singular
  // there even if its double representation remains invertible. The tolerance
  // permits the rounding of an otherwise legal 1e-9 scale at the boundary.
  return xdf_inverse_bounded((float)t->a, (float)t->b, (float)t->c, (float)t->d,
                             XU_DRAW_TRANSFORM_LIMIT * 1.000001);
}

static inline int xdf_transform_apply(XuDrawTransform *t, const XuDrawCommand *command) {
  XuDrawTransform previous = *t;
  const double *v = command->values;
  switch (command->opcode) {
    case XDF_ORIGIN: *t = xdf_identity(); break;
    case XDF_TRANSLATE:
      t->tx += previous.a * v[0] + previous.c * v[1];
      t->ty += previous.b * v[0] + previous.d * v[1];
      break;
    case XDF_ROTATE: {
      double radians = v[0] * 0.017453292519943295;
      double c = cos(radians), s = sin(radians);
      t->a = previous.a * c + previous.c * s;
      t->b = previous.b * c + previous.d * s;
      t->c = previous.c * c - previous.a * s;
      t->d = previous.d * c - previous.b * s;
      break;
    }
    case XDF_SCALE:
      t->a *= v[0]; t->b *= v[0]; t->c *= v[1]; t->d *= v[1];
      break;
    default: return 1;
  }
  return xdf_transform_valid(t);
}

static inline unsigned xdf_u32(const unsigned char *p) {
  return (unsigned)p[0] | ((unsigned)p[1] << 8) |
         ((unsigned)p[2] << 16) | ((unsigned)p[3] << 24);
}
static inline unsigned xdf_u16(const unsigned char *p) {
  return (unsigned)p[0] | ((unsigned)p[1] << 8);
}
static inline double xdf_f64(const unsigned char *p) {
  uint64_t bits = (uint64_t)xdf_u32(p) | ((uint64_t)xdf_u32(p + 4) << 32);
  double value;
  memcpy(&value, &bits, sizeof(value));
  return value;
}
static inline int xdf_utf8(const unsigned char *p, unsigned n) {
  for (unsigned i = 0; i < n;) {
    unsigned c = p[i++], need, value, minimum;
    if (c < 0x80) { if (c == 0) return 0; continue; }
    if (c >= 0xc2 && c <= 0xdf) { need = 1; value = c & 31; minimum = 0x80; }
    else if (c >= 0xe0 && c <= 0xef) { need = 2; value = c & 15; minimum = 0x800; }
    else if (c >= 0xf0 && c <= 0xf4) { need = 3; value = c & 7; minimum = 0x10000; }
    else return 0;
    if (need > n - i) return 0;
    while (need--) {
      unsigned b = p[i++];
      if ((b & 0xc0) != 0x80) return 0;
      value = (value << 6) | (b & 63);
    }
    if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) return 0;
  }
  return 1;
}

#define XU_DRAW_PATH_MAX_BYTES (2u * 1024u * 1024u)
#define XU_DRAW_PATH_MAX_SEGMENTS 32768u
#define XU_DRAW_PATH_MAX_DASHES 32u
enum XuPathVerb { XUP_MOVE=1, XUP_LINE, XUP_QUAD, XUP_CUBIC, XUP_CLOSE };
// PATH payload: flags, RGBA, segment count, dash count, width/miter/phase/
// flatten tolerance (four f64), dash lengths, then verb+f64 coordinate records.
// flags: stroke=1, even-odd fill=2, cap<<2, join<<4 (butt/miter=0,
// round=1, square/bevel=2). Closing ends the figure; another move is required.
// All lengths use logical units. Positive dash phase consumes that much of the
// pattern at each figure's start. Curved dashes use bounded shared flattening.
static inline unsigned xup_values(unsigned verb) {
  return verb==XUP_MOVE || verb==XUP_LINE ? 2 : verb==XUP_QUAD ? 4 : verb==XUP_CUBIC ? 6 : 0;
}
static inline int xup_validate(const void *data,unsigned len) {
  if(!data || len<48 || len>48+XU_DRAW_PATH_MAX_DASHES*8+XU_DRAW_PATH_MAX_BYTES) return 0;
  const unsigned char *p=(const unsigned char *)data;
  unsigned flags=xdf_u32(p),count=xdf_u32(p+8),dashes=xdf_u32(p+12);
  if((flags&~63u) || ((flags>>2)&3)>2 || ((flags>>4)&3)>2 || count>XU_DRAW_PATH_MAX_SEGMENTS ||
     dashes>XU_DRAW_PATH_MAX_DASHES || (dashes&1) || len<48+dashes*8) return 0;
  double width=xdf_f64(p+16),miter=xdf_f64(p+24),phase=xdf_f64(p+32),tolerance=xdf_f64(p+40);
  if(flags&1) {
    if((flags&2) || !isfinite(width) || width<1e-6 || width>16384 || !isfinite(miter) || miter<1 || miter>1024 ||
       !isfinite(phase) || fabs(phase)>1e9 || !isfinite(tolerance) || tolerance<1e-6 || tolerance>16) return 0;
  } else if((flags&~2u) || dashes || width!=0 || miter!=0 || phase!=0 || tolerance!=0) return 0;
  for(unsigned i=0;i<dashes;++i) {
    double length=xdf_f64(p+48+i*8); if(!isfinite(length) || length<1e-6 || length>16384) return 0;
  }
  unsigned cursor=48+dashes*8,first=cursor; int open=0;
  for(unsigned i=0;i<count;++i) {
    if(len-cursor<4) return 0;
    unsigned verb=xdf_u32(p+cursor),n=xup_values(verb); cursor+=4;
    if(verb<XUP_MOVE || verb>XUP_CLOSE || (!open && verb!=XUP_MOVE) || n*8>len-cursor) return 0;
    open=verb!=XUP_CLOSE;
    for(unsigned j=0;j<n;++j) { double value=xdf_f64(p+cursor+j*8); if(!isfinite(value) || fabs(value)>1e9) return 0; }
    cursor+=n*8;
  }
  return cursor==len && cursor-first<=XU_DRAW_PATH_MAX_BYTES;
}

// Cursor starts at 32. Returns 1, 0 at end, or -1 for an invalid record.
static inline int xdf_next(const void *data, unsigned len, unsigned *cursor, XuDrawCommand *out) {
  if (!data || !cursor || !out || *cursor < 32 || *cursor > len) return -1;
  if (*cursor == len) return 0;
  if (len - *cursor < 8) return -1;
  const unsigned char *p = (const unsigned char *)data + *cursor;
  unsigned op = xdf_u16(p), size = xdf_u32(p + 4), nv = 0, color = 0, text = 0, image = 0;
  if (xdf_u16(p + 2) != 0 || size < 8 || size > len - *cursor) return -1;
  if(op==XDF_PATH) {
    if(!xup_validate(p+8,size-8)) return -1;
    memset(out,0,sizeof(*out)); out->opcode=op; out->rgba=xdf_u32(p+12);
    out->text=(const char *)p+8; out->text_len=size-8; *cursor+=size; return 1;
  }
  switch (op) {
    case XDF_BACKGROUND: case XDF_COLOR: case XDF_FILL: case XDF_STROKE: color = 1; break;
    case XDF_WIDTH: case XDF_ROTATE: nv = 1; break;
    case XDF_SAVE: case XDF_RESTORE: case XDF_ORIGIN: break;
    case XDF_TRANSLATE: case XDF_SCALE: nv = 2; break;
    case XDF_CLIP_RECT: case XDF_RECT: case XDF_RECT_LINE: case XDF_ELLIPSE: nv = 4; break;
    case XDF_FILL_RECT: nv = 4; color = 1; break;
    case XDF_STROKE_RECT: case XDF_LINE: nv = 5; color = 1; break;
    case XDF_TEXT: nv = 3; color = 1; text = 1; break;
    case XDF_CIRCLE: nv = 3; break;
    case XDF_TRIANGLE: nv = 6; break;
    case XDF_IMAGE: nv = 8; color = 1; image = 1; break;
    case XDF_TEXT_LAYOUT: nv = 2; color = 1; image = 1; break;
    case XDF_DISPLAY_LIST: image = 1; break;
    default: return -1;
  }
  unsigned fixed = 8 + image * 8 + nv * 8 + color * 4;
  if (text ? size < fixed : size != fixed) return -1;
  memset(out, 0, sizeof(*out));
  out->opcode = op;
  p += 8;
  if (image) {
    out->image_id = (uint64_t)xdf_u32(p) | ((uint64_t)xdf_u32(p + 4) << 32);
    if (!out->image_id || out->image_id > INT64_MAX) return -1;
    p += 8;
  }
  for (unsigned i = 0; i < nv; ++i) {
    out->values[i] = xdf_f64(p + i * 8);
    if (!isfinite(out->values[i]) || fabs(out->values[i]) > 1.0e9) return -1;
  }
  if (color) out->rgba = xdf_u32(p + nv * 8);
  if (text) {
    out->text = (const char *)p + nv * 8 + 4;
    out->text_len = size - fixed;
    if (!xdf_utf8((const unsigned char *)out->text, out->text_len)) return -1;
  }
  if (op == XDF_IMAGE && ((out->rgba & ~0x1ffffu) || out->values[0] < 0 || out->values[1] < 0 ||
                out->values[2] <= 0 || out->values[3] <= 0 || out->values[6] < 0 || out->values[7] < 0)) return -1;
  if ((op == XDF_BACKGROUND && (out->rgba & 255) != 255) ||
      (op == XDF_WIDTH && out->values[0] <= 0) ||
      ((op == XDF_STROKE_RECT || op == XDF_LINE) && out->values[4] <= 0) ||
      (op == XDF_TEXT && out->values[2] <= 0) ||
      (op == XDF_CIRCLE && out->values[2] < 0) ||
      ((op == XDF_CLIP_RECT || op == XDF_RECT || op == XDF_RECT_LINE ||
        op == XDF_ELLIPSE || op == XDF_FILL_RECT || op == XDF_STROKE_RECT) &&
       (out->values[2] < 0 || out->values[3] < 0)) ||
      (op == XDF_SCALE && (fabs(out->values[0]) < 1.0e-9 || fabs(out->values[1]) < 1.0e-9))) return -1;
  // A large angle is valid, but converting it directly to a native float can
  // lose whole degrees. All interpreters receive the same reduced angle.
  if (op == XDF_ROTATE) out->values[0] = fmod(out->values[0], 360.0);
  *cursor += size;
  return 1;
}

static inline int xdf_validate(const void *data, unsigned len) {
  if (!data || len < 32 || len > XU_DRAW_FRAME_MAX_BYTES) return 0;
  const unsigned char *p = (const unsigned char *)data;
  unsigned version = xdf_u16(p + 4), canvas = xdf_u32(p + 16), generation = xdf_u32(p + 20);
  if (memcmp(p, "XDF1", 4) || xdf_u16(p + 6) != 0 || xdf_u32(p + 8) != len) return 0;
  // v1 is the legacy default canvas. v2 binds an explicit live generation.
  if (version == 1 ? (canvas != 1 || generation != 0) :
      (version != 2 || !canvas || canvas > 0x7fffffffu || !generation)) return 0;
  unsigned count = xdf_u32(p + 12), cursor = 32, depth = 0;
  if (count > XU_DRAW_FRAME_MAX_COMMANDS) return 0;
  XuDrawTransform transform = xdf_identity(), stack[256];
  for (unsigned i = 0; i < count; ++i) {
    XuDrawCommand command;
    if (xdf_next(data, len, &cursor, &command) != 1) return 0;
    if (command.opcode == XDF_SAVE) {
      if (depth == 256) return 0;
      stack[depth++] = transform;
    } else if (command.opcode == XDF_RESTORE) {
      if (!depth) return 0;
      transform = stack[--depth];
    } else if (!xdf_transform_apply(&transform, &command)) return 0;
  }
  return cursor == len && depth == 0;
}

#ifdef __cplusplus
extern "C" {
#endif
// Register a unique live canvas. A reused ID receives a new nonzero generation;
// duplicate live IDs, invalid identities and exhaustion return zero.
unsigned xu_ui_canvas_open(unsigned window_id, unsigned canvas_id);
// Closing a matching generation also releases its queued frame payloads.
void xu_ui_canvas_close(unsigned canvas_id, unsigned generation);
// Atomic ownership transfer from the bounded frame queue. Caller free().
void *xu_ui_draw_take(uint64_t ticket, unsigned *out_len);
// Wrong target/generation leaves the pending frame available for its owner.
void *xu_ui_draw_take_for(uint64_t ticket, unsigned canvas_id, unsigned generation, unsigned *out_len);
// Owned frame snapshot. Bitmap pointers are borrowed until release; native
// display lists must retain a bitmap before releasing their lease.
typedef struct XuUiFrameLease XuUiFrameLease;
typedef struct XuUiText XuUiText;
typedef struct XuUiBitmap XuUiBitmap;
XuUiFrameLease *xu_ui_draw_acquire_for(uint64_t ticket, unsigned canvas_id, unsigned generation);
const void *xu_ui_frame_data(const XuUiFrameLease *, unsigned *out_len);
XuUiBitmap *xu_ui_frame_bitmap(const XuUiFrameLease *, uint64_t image_id);
XuUiText *xu_ui_frame_text(const XuUiFrameLease *, uint64_t layout_id);
// Prepared path payload for the PATH record at this byte offset. Borrowed
// until frame release. Dash expansion is performed once on the submitter,
// outside registry locks, before the frame is admitted to the native thread.
const void *xu_ui_frame_path(const XuUiFrameLease *, unsigned record_offset, unsigned *out_len);
void xu_ui_frame_release(XuUiFrameLease *);
// Worker-safe offscreen renderer. Only one backend can be installed; repeated
// installation of the same function is harmless. Borrowed lease/output live
// until return. Write tightly packed top-left premultiplied BGRA8, sRGB bytes.
// No widgets, camera, window DPI or shell events may be used by this callback.
typedef int (*XuUiSurfaceRender)(const XuUiFrameLease *, unsigned, unsigned, double, double, unsigned char *);
int xu_ui_surface_set_backend(XuUiSurfaceRender);
// Native backends may opt into the shared exact opaque-rectangle fast path.
// Other backends retain the original callback-only contract. Flags are fixed
// at installation, and can never be changed under active calls.
#define XU_UI_SURFACE_BATCH_RECTS 1u
int xu_ui_surface_set_backend_v2(XuUiSurfaceRender, unsigned flags);
// Immutable cache in an image slot. The frame is copied and its resource
// versions are pinned atomically; rendering never holds the registry lock.
int xu_ui_surface_create(uint64_t id, unsigned pixel_width, unsigned pixel_height,
                         double logical_width, double logical_height, const void *frame, unsigned frame_len);

unsigned xu_ui_draw_window(uint64_t ticket);
// Drop a ticket marker after dispatch if no draw plugin consumed it.
void xu_ui_draw_discard_marker(const char *command);
// Flat decoder for Swift. All output arrays must have the documented capacity.
int xu_ui_draw_next(const void *data, unsigned len, unsigned *cursor,
                    double *values8, unsigned *meta2, const char **text, unsigned *text_len);
int xu_ui_draw_next_v2(const void *data, unsigned len, unsigned *cursor,
                    double *values8, unsigned *meta2, const char **text, unsigned *text_len, uint64_t *image_id);
#ifdef __cplusplus
}
#endif
