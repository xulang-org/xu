// Included once after the canvas registry and image target helpers.
#include "xu_ui_text.h"
#include "xu_ui_grapheme.h"
#include <algorithm>
#include <string>
#include <unordered_map>
#include <deque>
#include <utility>
struct XuUiText {
  std::atomic<unsigned> references{1};
  uint64_t id;
  void *native;
  XuUiTextDestroy destroy;
  XuUiTextQuery query;
  char *text;
  unsigned length;
  unsigned cost;
  double metrics[8];
  std::vector<unsigned> mask_stops;
};
struct XuTextSlot {
  uint64_t id;
  unsigned state, canvas, generation;
  long long deadline;
  XuUiText *layout;
};
// Live identities grow with application demand. Erasing a user handle does not
// revoke immutable layouts retained by a frame or text-input binding.
static std::unordered_map<uint64_t, XuTextSlot> g_texts;
static std::deque<std::pair<uint64_t, long long>> g_text_expirations;
static uint64_t g_text_id = 0;
static XuUiTextCreate g_text_create = NULL;
static XuUiTextDestroy g_text_destroy = NULL;
static XuUiTextQuery g_text_query = NULL;
static std::atomic<unsigned> g_text_cost{0};
int xu_ui_text_set_backend(XuUiTextCreate create, XuUiTextDestroy destroy) {
  if (!create || !destroy) return 0;
  lock_w();
  bool valid = !g_text_create || (g_text_create == create && g_text_destroy == destroy);
  if (valid) { g_text_create = create; g_text_destroy = destroy; }
  unlock_w(); return valid ? 1 : 0;
}
int xu_ui_text_set_query_backend(XuUiTextQuery query) {
  if (!query) return 0;
  lock_w(); bool valid = !g_text_query || g_text_query == query;
  if (valid) g_text_query = query;
  unlock_w(); return valid ? 1 : 0;
}
static XuTextSlot *text_slot(uint64_t id) {
  if (!id) return NULL;
  auto at = g_texts.find(id);
  return at == g_texts.end() ? NULL : &at->second;
}
void xu_ui_text_retain(XuUiText *text) {
  if (text) text->references.fetch_add(1, std::memory_order_relaxed);
}
void xu_ui_text_release(XuUiText *text) {
  if (text && text->references.fetch_sub(1, std::memory_order_acq_rel) == 1) {
    text->destroy(text->native);
    g_text_cost.fetch_sub(text->cost, std::memory_order_relaxed); free(text->text); delete text;
  }
}
void *xu_ui_text_native(const XuUiText *text) { return text ? text->native : NULL; }
unsigned xu_ui_text_live_cost(void) { return g_text_cost.load(std::memory_order_relaxed); }
uint64_t xu_ui_text_reserve(void) {
  lock_w(); const long long now = image_now();
  // Reservations are chronological. Expire only due tokens instead of
  // scanning every live shaped layout on every new allocation.
  while (!g_text_expirations.empty() && g_text_expirations.front().second <= now) {
    const auto token = g_text_expirations.front(); g_text_expirations.pop_front();
    auto at = g_texts.find(token.first);
    if (at != g_texts.end() && at->second.state == 1 && at->second.deadline == token.second)
      g_texts.erase(at);
  }
  uint64_t id = 0;
  if (g_text_create && g_text_id < INT64_MAX) {
    const uint64_t candidate = ++g_text_id;
    try {
      XuTextSlot slot{}; slot.id = candidate; slot.state = 1; slot.deadline = now + 10000;
      if (g_texts.emplace(candidate, slot).second) {
        g_text_expirations.emplace_back(candidate, slot.deadline); id = candidate;
      }
    } catch (...) { g_texts.erase(candidate); /* Allocation failure returns zero. */ }
  }
  unlock_w(); return id;
}
void xu_ui_text_abandon(uint64_t id) {
  lock_w(); auto *slot = text_slot(id);
  if (slot && slot->state != 3) g_texts.erase(id);
  unlock_w();
}
static bool text_options(const double *v, unsigned length) {
  if (!v) return false;
  for (unsigned i = 0; i < 6; ++i) if (!isfinite(v[i])) return false;
  // Bound shaping input and native fixed-point coordinates before calling the
  // platform. Pango uses signed 32-bit values in units of 1/1024 pixel.
  return v[0] >= 1 && v[0] <= 512 && v[0] * (length + 1.0) <= 262144 &&
    v[1] >= 0 && v[1] <= 262144 && v[2] >= 100 && v[2] <= 900 && floor(v[2]) == v[2] &&
    (v[3] == 0 || v[3] == 1) && v[4] >= 0 && v[4] <= 2 && floor(v[4]) == v[4] && (v[1] > 0 || v[4] == 0) &&
    (v[5] == 0 || (v[5] >= v[0] && v[5] <= 1024)) &&
    v[5] * (length + 1.0) <= 262144;
}
static int text_create_layout(uint64_t id, unsigned canvas, unsigned generation,
                      const char *family, unsigned family_len, const char *value, unsigned length, const double *options, bool masked) {
  if (family_len > 256 || length > XU_UI_TEXT_MAX_LENGTH || (family_len && !family) || (length && !value) ||
      !xdf_utf8((const unsigned char *)family, family_len) || !xdf_utf8((const unsigned char *)value, length) ||
      !text_options(options, length)) return 0;
  unsigned actual = 0;
  lock_w(); auto *slot = text_slot(id);
  if (!slot || slot->state != 1 || !g_text_create || !image_target(canvas, generation, &actual)) { unlock_w(); return 0; }
  auto create = g_text_create; auto destroy = g_text_destroy; auto query = g_text_query;
  slot->state = 2; slot->canvas = canvas; slot->generation = actual;
  unlock_w();
  // Reserve a complete layout's declared maximum before native allocation.
  unsigned used = g_text_cost.load(std::memory_order_relaxed);
  bool charged = false;
  do { if (XU_UI_TEXT_LAYOUT_MAX_COST > XU_UI_TEXT_MAX_COST - used) break;
    charged = g_text_cost.compare_exchange_weak(used, used + XU_UI_TEXT_LAYOUT_MAX_COST, std::memory_order_relaxed);
  } while (!charged);
  auto *layout = charged ? new(std::nothrow) XuUiText{} : NULL;
  if (layout) {
    layout->id = id; layout->destroy = destroy; layout->cost = XU_UI_TEXT_LAYOUT_MAX_COST;
    layout->query = query; layout->length = length;
    layout->text = (char *)malloc(length + 1u);
    unsigned cost = 0;
    if (layout->text) {
      if (length) memcpy(layout->text, value, length); layout->text[length] = 0;
      if (masked) {
        try {
          if (xu_ui_grapheme::boundaries(value, length, &layout->mask_stops)) {
            std::string bullets;
            bullets.reserve((layout->mask_stops.size() - 1u) * 3u);
            for (size_t i = 1; i < layout->mask_stops.size(); ++i) bullets += "\xe2\x80\xa2";
            layout->native = create(family, family_len, bullets.data(), (unsigned)bullets.size(), options, layout->metrics, &cost);
          }
        } catch (...) { layout->native = NULL; }
      } else layout->native = create(family, family_len, value, length, options, layout->metrics, &cost);
    }
    unsigned overhead = length + 1u + (unsigned)sizeof(XuUiText) + (unsigned)layout->mask_stops.capacity() * sizeof(unsigned);
    bool valid = layout->native && cost > 0 && cost <= XU_UI_TEXT_LAYOUT_MAX_COST - overhead;
    for (unsigned i = 0; i < 8; ++i) if (!isfinite(layout->metrics[i]) || fabs(layout->metrics[i]) > 1048576) valid = false;
    if (layout->metrics[0] < 0 || layout->metrics[1] <= 0 || layout->metrics[2] < 0 ||
        layout->metrics[2] > layout->metrics[1] || layout->metrics[3] < 1 ||
        layout->metrics[3] > length + 1.0 || floor(layout->metrics[3]) != layout->metrics[3] ||
        layout->metrics[6] < 0 || layout->metrics[7] < 0) valid = false;
    if (!valid) {
      if (layout->native) destroy(layout->native);
      free(layout->text); delete layout; layout = NULL;
    } else {
      cost += overhead;
      g_text_cost.fetch_sub(XU_UI_TEXT_LAYOUT_MAX_COST - cost, std::memory_order_relaxed);
      layout->cost = cost;
    }
  }
  if (!layout && charged) g_text_cost.fetch_sub(XU_UI_TEXT_LAYOUT_MAX_COST, std::memory_order_relaxed);
  lock_w(); slot = text_slot(id);
  bool accepted = layout && slot && slot->state == 2 && image_target(slot->canvas, slot->generation, &actual);
  if (accepted) { slot->layout = layout; slot->state = 3; }
  else if (slot && slot->state == 2) {
    *slot = {}; slot->id = id; slot->state = 1; slot->deadline = image_now() + 10000;
    try { g_text_expirations.emplace_back(id, slot->deadline); }
    catch (...) { g_texts.erase(id); }
  }
  unlock_w(); if (!accepted) xu_ui_text_release(layout);
  return accepted ? 1 : 0;
}
int xu_ui_text_create(uint64_t id, unsigned canvas, unsigned generation,
                      const char *family, unsigned family_len, const char *value, unsigned length, const double *options) {
  return text_create_layout(id, canvas, generation, family, family_len, value, length, options, false);
}
int xu_ui_text_dispose(uint64_t id, unsigned canvas, unsigned generation) {
  lock_w(); auto *slot = text_slot(id);
  bool valid = slot && slot->state == 3 && slot->canvas == canvas &&
    (slot->generation == generation || (!generation && canvas == 1));
  XuUiText *layout = valid ? slot->layout : NULL;
  if (valid) g_texts.erase(id);
  unlock_w(); xu_ui_text_release(layout); return valid ? 1 : 0;
}
int xu_ui_text_info(uint64_t id, double *metrics, unsigned *generation) {
  if (metrics) memset(metrics, 0, sizeof(double) * 8);
  if (generation) *generation = 0;
  lock_r(); auto *slot = text_slot(id); bool valid = slot && slot->state == 3;
  if (valid) { if (metrics) memcpy(metrics, slot->layout->metrics, sizeof(double) * 8); if (generation) *generation = slot->generation; }
  unlock_r(); return valid ? 1 : 0;
}
static bool text_boundary(const XuUiText *layout, unsigned index) {
  return index <= layout->length && (index == layout->length || ((unsigned char)layout->text[index] & 0xc0) != 0x80);
}
// The caller owns a reference. Shared by handle queries and retained input
// bindings; neither path holds the registry lock while calling the shaper.
static int text_query_layout(XuUiText *layout, unsigned mode, unsigned index, unsigned trailing,
                              double x, double y, double *out) {
  if (!out) return 0;
  memset(out, 0, 7 * sizeof(double));
  if (!layout || mode > 1 || trailing > 1 || !isfinite(x) || !isfinite(y) || fabs(x) > 1048576 || fabs(y) > 1048576) return 0;
  unsigned native_index = index;
  if (mode == 1 && !layout->mask_stops.empty()) {
    auto at = std::upper_bound(layout->mask_stops.begin(), layout->mask_stops.end(), index);
    native_index = (unsigned)(at - layout->mask_stops.begin() - 1u) * 3u;
  }
  int valid = layout->query && (mode == 0 || text_boundary(layout, index)) &&
    layout->query(layout->native, mode, native_index, trailing, x, y, out);
  for (unsigned i = 0; valid && i < 7; ++i) if (!isfinite(out[i]) || fabs(out[i]) > 1048576) valid = 0;
  if (valid && !layout->mask_stops.empty()) {
    const auto &stops = layout->mask_stops;
    double end = out[0] + out[1];
    if (out[0] < 0 || out[1] < 0 || floor(out[0] / 3.0) != out[0] / 3.0 ||
        floor(end / 3.0) != end / 3.0 || end / 3.0 >= stops.size()) valid = 0;
    else {
      unsigned first = stops[(unsigned)out[0] / 3u], last = stops[(unsigned)end / 3u];
      out[0] = first; out[1] = last - first;
    }
  }
  if (valid && (out[0] < 0 || floor(out[0]) != out[0] || out[1] < 0 || floor(out[1]) != out[1] ||
      out[0] + out[1] > layout->length || !text_boundary(layout, (unsigned)out[0]) ||
      !text_boundary(layout, (unsigned)(out[0] + out[1])) || (out[2] != 0 && out[2] != 1) ||
      (out[3] != 0 && out[3] != 1) || out[6] <= 0)) valid = 0;
  if (!valid) memset(out, 0, 7 * sizeof(double));
  return valid ? 1 : 0;
}
int xu_ui_text_query(uint64_t id, unsigned canvas, unsigned generation, unsigned mode, unsigned index, unsigned trailing,
                     double x, double y, double *out) {
  if (!out) return 0;
  memset(out, 0, 7 * sizeof(double));
  if (mode > 1 || trailing > 1 || !isfinite(x) || !isfinite(y) || fabs(x) > 1048576 || fabs(y) > 1048576) return 0;
  lock_r(); auto *slot = text_slot(id);
  auto *layout = slot && slot->state == 3 && slot->canvas == canvas &&
    (slot->generation == generation || (!generation && canvas == 1)) ? slot->layout : NULL;
  if (layout) xu_ui_text_retain(layout);
  unlock_r(); if (!layout) return 0;
  int valid = text_query_layout(layout, mode, index, trailing, x, y, out);
  xu_ui_text_release(layout); if (!valid) memset(out, 0, 7 * sizeof(double));
  return valid ? 1 : 0;
}
static void text_adopt_canvas(unsigned canvas, unsigned generation) {
  if (canvas == 1) for (auto &entry : g_texts) {
    auto &slot = entry.second;
    if (slot.canvas == 1 && !slot.generation) slot.generation = generation;
  }
}
static void text_close_canvas(unsigned canvas, unsigned generation) {
  for (auto at = g_texts.begin(); at != g_texts.end();) {
    const auto &slot = at->second;
    if (slot.canvas == canvas && slot.generation == generation) {
      auto *layout = slot.layout; at = g_texts.erase(at); xu_ui_text_release(layout);
    } else ++at;
  }
}
static XuUiText *text_snapshot(uint64_t id, unsigned canvas, unsigned generation) {
  auto *slot = text_slot(id);
  if (!slot || slot->state != 3 || slot->canvas != canvas || slot->generation != generation) return NULL;
  xu_ui_text_retain(slot->layout); return slot->layout;
}
static int text_upload(const void *data, unsigned length) {
  if (!data || length < 80 || length > 80 + 256 + XU_UI_TEXT_MAX_LENGTH) return 0;
  auto *p = (const unsigned char *)data;
  if (memcmp(p, "XTL1", 4) || xdf_u16(p + 4) != 1 || xdf_u16(p + 6) > 1) return 0;
  uint64_t id = (uint64_t)xdf_u32(p + 8) | ((uint64_t)xdf_u32(p + 12) << 32);
  unsigned family = xdf_u32(p + 72), text = xdf_u32(p + 76);
  if (!id || id > INT64_MAX || family > 256 || text > XU_UI_TEXT_MAX_LENGTH || length != 80 + family + text) return 0;
  double options[6]; for (unsigned i = 0; i < 6; ++i) options[i] = xdf_f64(p + 24 + i * 8);
  return text_create_layout(id, xdf_u32(p + 16), xdf_u32(p + 20), (const char *)p + 80, family,
                           (const char *)p + 80 + family, text, options, xdf_u16(p + 6) == 1);
}
