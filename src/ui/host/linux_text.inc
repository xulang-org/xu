// Private font map/context per layout: worker creation never accesses GTK's
// UI-thread font map. Retained layouts only populate caches under their mutex.
#include "xu_ui_text.h"
#include <pango/pangocairo.h>
#include <mutex>
#include <new>
namespace {
struct DrawTextLayout {
  PangoFontMap *map = NULL;
  PangoLayout *layout = NULL;
  std::mutex mutex;
  std::string text;
  std::vector<unsigned> byte_offsets;
  ~DrawTextLayout() { if (layout) g_object_unref(layout); if (map) g_object_unref(map); }
};
static void *text_create_native(const char *family, unsigned family_len, const char *value, unsigned length,
                                 const double *v, double *metrics, unsigned *cost) {
  auto result = std::unique_ptr<DrawTextLayout>(new(std::nothrow) DrawTextLayout);
  if (!result) return NULL;
  result->text.assign(length ? value : "", length);
  for (const char *at = result->text.c_str(), *end = at + length; at < end; at = g_utf8_next_char(at))
    result->byte_offsets.push_back((unsigned)(at - result->text.c_str()));
  result->byte_offsets.push_back(length);
  result->map = pango_cairo_font_map_new(); if (!result->map) return NULL;
  pango_cairo_font_map_set_resolution(PANGO_CAIRO_FONT_MAP(result->map), 96);
  PangoContext *context = pango_font_map_create_context(result->map); if (!context) return NULL;
  result->layout = pango_layout_new(context); g_object_unref(context);
  if (!result->layout) return NULL;
  std::string name = family_len ? std::string(family, family_len) : "sans-serif";
  PangoFontDescription *font = pango_font_description_new();
  pango_font_description_set_family(font, name.c_str());
  pango_font_description_set_absolute_size(font, v[0] * PANGO_SCALE);
  pango_font_description_set_weight(font, (PangoWeight)(int)v[2]);
  pango_font_description_set_style(font, v[3] ? PANGO_STYLE_ITALIC : PANGO_STYLE_NORMAL);
  pango_layout_set_font_description(result->layout, font); pango_font_description_free(font);
  pango_layout_set_width(result->layout, v[1] ? (int)(v[1] * PANGO_SCALE + 0.5) : -1);
  pango_layout_set_wrap(result->layout, PANGO_WRAP_WORD_CHAR);
  pango_layout_set_auto_dir(result->layout, FALSE);
  pango_layout_set_alignment(result->layout, v[4] == 1 ? PANGO_ALIGN_CENTER : v[4] == 2 ? PANGO_ALIGN_RIGHT : PANGO_ALIGN_LEFT);
  pango_layout_set_text(result->layout, length ? value : "", (int)length);
  if (v[5]) {
    PangoAttrList *attrs = pango_attr_list_new();
    pango_attr_list_insert(attrs, pango_attr_line_height_new_absolute((int)(v[5] * PANGO_SCALE + 0.5)));
    pango_layout_set_attributes(result->layout, attrs); pango_attr_list_unref(attrs);
  }
  PangoRectangle ink, logical; pango_layout_get_extents(result->layout, &ink, &logical);
  metrics[0] = logical.width / (double)PANGO_SCALE; metrics[1] = logical.height / (double)PANGO_SCALE;
  metrics[2] = pango_layout_get_baseline(result->layout) / (double)PANGO_SCALE;
  metrics[3] = pango_layout_get_line_count(result->layout);
  metrics[4] = ink.x / (double)PANGO_SCALE; metrics[5] = ink.y / (double)PANGO_SCALE;
  metrics[6] = ink.width / (double)PANGO_SCALE; metrics[7] = ink.height / (double)PANGO_SCALE;
  *cost = 8192u + length * 128u;
  return result.release();
}
static void text_destroy_native(void *layout) { delete (DrawTextLayout *)layout; }
static int text_query_native(void *pointer, unsigned mode, unsigned index, unsigned trailing, double x, double y, double *out) {
  auto *text = (DrawTextLayout *)pointer;
  std::lock_guard<std::mutex> lock(text->mutex);
  int at = (int)index, edge = trailing ? 1 : 0;
  bool inside = true;
  if (!mode) inside = pango_layout_xy_to_index(text->layout, (int)(x * PANGO_SCALE), (int)(y * PANGO_SCALE), &at, &edge);
  if (at < 0 || (unsigned)at > text->text.size()) return 0;
  auto found = std::lower_bound(text->byte_offsets.begin(), text->byte_offsets.end(), (unsigned)at);
  if (found == text->byte_offsets.end() || *found != (unsigned)at) return 0;
  unsigned start = (unsigned)(found - text->byte_offsets.begin()), end = start;
  int count = 0; const PangoLogAttr *attrs = pango_layout_get_log_attrs_readonly(text->layout, &count);
  if (!attrs || count != (int)text->byte_offsets.size()) return 0;
  while (start && !attrs[start].is_cursor_position) --start;
  end = start;
  if (end + 1 < text->byte_offsets.size()) { ++end; while (end + 1 < text->byte_offsets.size() && !attrs[end].is_cursor_position) ++end; }
  PangoRectangle rect; pango_layout_index_to_pos(text->layout, (int)text->byte_offsets[start], &rect);
  // At a wrapped line with an inserted hyphen, xy_to_index can return the
  // final grapheme's leading flag even for a point beyond its trailing edge.
  // Use that same layout's signed advance interval to select the nearest edge.
  if (!mode && rect.width) edge = fabs(x * PANGO_SCALE - (rect.x + rect.width)) < fabs(x * PANGO_SCALE - rect.x) ? 1 : 0;
  out[0] = text->byte_offsets[start]; out[1] = text->byte_offsets[end] - out[0];
  out[2] = edge ? 1 : 0; out[3] = inside ? 1 : 0;
  out[4] = (rect.x + (edge ? rect.width : 0)) / (double)PANGO_SCALE;
  out[5] = rect.y / (double)PANGO_SCALE; out[6] = rect.height / (double)PANGO_SCALE;
  return 1;
}
}
extern "C" void xu_draw_text_init(void) {
  xu_ui_surface_set_backend_v2(surface_render_native,XU_UI_SURFACE_BATCH_RECTS);
  xu_ui_display_list_set_backend(compile_scene_native,destroy_scene_native);
  xu_ui_text_set_query_backend(text_query_native);
  xu_ui_text_set_backend(text_create_native, text_destroy_native);
}
