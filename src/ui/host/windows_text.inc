// DirectWrite shapes/falls back/wraps once; GDI+ replays cached vector outlines.
// This path needs no Direct2D render target and follows the canvas CTM/clip.
#include "xu_ui_text.h"
#include <dwrite.h>
#include <d2d1.h>
#include <mutex>
#include <atomic>
#include <algorithm>
#include <new>
namespace {
struct DrawTextLayout {
  IDWriteTextLayout *layout = NULL;
  std::unique_ptr<GraphicsPath> outline;
  std::vector<unsigned> byte_offsets;
  std::vector<unsigned> clusters;
  std::mutex mutex;
  ~DrawTextLayout() { if (layout) layout->Release(); }
};
static IDWriteFactory *text_factory = NULL;
static std::once_flag text_once;
static std::wstring text_wide(const char *bytes, unsigned length) {
  if (!length) return {};
  int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, bytes, (int)length, NULL, 0);
  if (!n) return {};
  std::wstring value((size_t)n, 0);
  if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, bytes, (int)length, value.data(), n) != n) return {};
  return value;
}
struct TextOutlineSink final : ID2D1SimplifiedGeometrySink {
  std::atomic<ULONG> refs{1};
  GraphicsPath *path; unsigned *points; PointF current; FLOAT x, y;
  HRESULT status = S_OK;
  TextOutlineSink(GraphicsPath *p, unsigned *count, FLOAT a, FLOAT b) : path(p), points(count), x(a), y(b) {}
  HRESULT WINAPI QueryInterface(REFIID iid, void **out) override {
    if (!out) return E_POINTER;
    *out = NULL;
    if (iid == __uuidof(IUnknown) || iid == __uuidof(ID2D1SimplifiedGeometrySink)) { *out = this; AddRef(); return S_OK; }
    return E_NOINTERFACE;
  }
  ULONG WINAPI AddRef() override { return ++refs; }
  ULONG WINAPI Release() override { ULONG n = --refs; if (!n) delete this; return n; }
  bool admit(unsigned count) {
    if (FAILED(status)) return false;
    if (count > 65536u - *points) { status = E_OUTOFMEMORY; return false; }
    *points += count; return true;
  }
  PointF point(D2D1_POINT_2F p) {
    PointF result(p.x + x, p.y + y);
    if (!isfinite(result.X) || !isfinite(result.Y) || fabs(result.X) > 1048576 || fabs(result.Y) > 1048576) status = E_FAIL;
    return result;
  }
  void check(Status s) { if (s != Ok) status = E_FAIL; }
  void WINAPI SetFillMode(D2D1_FILL_MODE mode) override {
    check(path->SetFillMode(mode == D2D1_FILL_MODE_WINDING ? FillModeWinding : FillModeAlternate));
  }
  void WINAPI SetSegmentFlags(D2D1_PATH_SEGMENT) override {}
  void WINAPI BeginFigure(D2D1_POINT_2F start, D2D1_FIGURE_BEGIN) override {
    if (!admit(1)) return;
    current = point(start); if (SUCCEEDED(status)) check(path->StartFigure());
  }
  void WINAPI AddLines(const D2D1_POINT_2F *values, UINT32 count) override {
    if (!admit(count)) return;
    for (UINT32 i = 0; i < count && SUCCEEDED(status); ++i) {
      PointF next = point(values[i]); if (SUCCEEDED(status)) check(path->AddLine(current, next)); current = next;
    }
  }
  void WINAPI AddBeziers(const D2D1_BEZIER_SEGMENT *values, UINT32 count) override {
    if (count > 65536u / 3) { status = E_OUTOFMEMORY; return; }
    if (!admit(count * 3)) return;
    for (UINT32 i = 0; i < count && SUCCEEDED(status); ++i) {
      PointF a = point(values[i].point1), b = point(values[i].point2), c = point(values[i].point3);
      if (SUCCEEDED(status)) check(path->AddBezier(current, a, b, c)); current = c;
    }
  }
  void WINAPI EndFigure(D2D1_FIGURE_END end) override {
    if (SUCCEEDED(status) && end == D2D1_FIGURE_END_CLOSED) check(path->CloseFigure());
  }
  HRESULT WINAPI Close() override { return status; }
};
struct TextOutlineRenderer final : IDWriteTextRenderer {
  std::atomic<ULONG> refs{1};
  std::unique_ptr<GraphicsPath> path{new GraphicsPath(FillModeWinding)};
  unsigned points = 0;
  HRESULT WINAPI QueryInterface(REFIID iid, void **out) override {
    if (!out) return E_POINTER;
    *out = NULL;
    if (iid == __uuidof(IUnknown) || iid == __uuidof(IDWriteTextRenderer) || iid == __uuidof(IDWritePixelSnapping)) {
      *out = this; AddRef(); return S_OK;
    }
    return E_NOINTERFACE;
  }
  ULONG WINAPI AddRef() override { return ++refs; }
  ULONG WINAPI Release() override { ULONG n = --refs; if (!n) delete this; return n; }
  HRESULT WINAPI IsPixelSnappingDisabled(void *, BOOL *value) override { if (!value) return E_POINTER; *value = TRUE; return S_OK; }
  HRESULT WINAPI GetCurrentTransform(void *, DWRITE_MATRIX *value) override { if (!value) return E_POINTER; *value = {1,0,0,1,0,0}; return S_OK; }
  HRESULT WINAPI GetPixelsPerDip(void *, FLOAT *value) override { if (!value) return E_POINTER; *value = 1; return S_OK; }
  HRESULT WINAPI DrawGlyphRun(void *, FLOAT x, FLOAT y, DWRITE_MEASURING_MODE, const DWRITE_GLYPH_RUN *run,
                              const DWRITE_GLYPH_RUN_DESCRIPTION *, IUnknown *) override {
    auto *sink = new(std::nothrow) TextOutlineSink(path.get(), &points, x, y);
    if (!sink) return E_OUTOFMEMORY;
    HRESULT hr = run->fontFace->GetGlyphRunOutline(run->fontEmSize, run->glyphIndices, run->glyphAdvances,
      run->glyphOffsets, run->glyphCount, run->isSideways, (run->bidiLevel & 1) != 0, sink);
    if (SUCCEEDED(hr)) hr = sink->Close();
    sink->Release(); return hr;
  }
  HRESULT WINAPI DrawUnderline(void *, FLOAT, FLOAT, const DWRITE_UNDERLINE *, IUnknown *) override { return E_NOTIMPL; }
  HRESULT WINAPI DrawStrikethrough(void *, FLOAT, FLOAT, const DWRITE_STRIKETHROUGH *, IUnknown *) override { return E_NOTIMPL; }
  HRESULT WINAPI DrawInlineObject(void *, FLOAT, FLOAT, IDWriteInlineObject *, BOOL, BOOL, IUnknown *) override { return E_NOTIMPL; }
};
static void *text_create_native(const char *family, unsigned family_len, const char *value, unsigned length,
                                 const double *v, double *metrics, unsigned *cost) {
  if (!text_factory) return NULL;
  std::wstring name = family_len ? text_wide(family, family_len) : L"Segoe UI", text = text_wide(value, length);
  if ((family_len && name.empty()) || (length && text.empty())) return NULL;
  IDWriteTextFormat *format = NULL;
  HRESULT hr = text_factory->CreateTextFormat(name.c_str(), NULL, (DWRITE_FONT_WEIGHT)(int)v[2],
    v[3] ? DWRITE_FONT_STYLE_ITALIC : DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, (FLOAT)v[0], L"", &format);
  if (FAILED(hr)) return NULL;
  auto result = std::unique_ptr<DrawTextLayout>(new(std::nothrow) DrawTextLayout);
  if (!result) { format->Release(); return NULL; }
  result->byte_offsets.resize(text.size() + 1);
  for (unsigned i = 0, u = 0; i < length;) {
    unsigned byte = (unsigned char)value[i], size = byte < 0x80 ? 1 : byte < 0xe0 ? 2 : byte < 0xf0 ? 3 : 4;
    result->byte_offsets[u++] = i;
    if (size == 4) result->byte_offsets[u++] = i;
    i += size; result->byte_offsets[u] = i;
  }
  hr = format->SetWordWrapping(v[1] ? DWRITE_WORD_WRAPPING_WRAP : DWRITE_WORD_WRAPPING_NO_WRAP);
  // Public alignment is physical left/center/right; DirectWrite enums differ.
  if (SUCCEEDED(hr)) hr = format->SetTextAlignment(v[4] == 1 ? DWRITE_TEXT_ALIGNMENT_CENTER :
                                                  v[4] == 2 ? DWRITE_TEXT_ALIGNMENT_TRAILING : DWRITE_TEXT_ALIGNMENT_LEADING);
  if (SUCCEEDED(hr)) hr = text_factory->CreateTextLayout(text.data(), (UINT32)text.size(), format,
    (FLOAT)(v[1] ? v[1] : 1048576), 1048576, &result->layout);
  format->Release(); if (FAILED(hr)) return NULL;
  UINT32 cluster_count = 0;
  hr = result->layout->GetClusterMetrics(NULL, 0, &cluster_count);
  if (FAILED(hr) && hr != E_NOT_SUFFICIENT_BUFFER) return NULL;
  if (cluster_count > text.size()) return NULL;
  std::vector<DWRITE_CLUSTER_METRICS> cluster_metrics(cluster_count);
  if (cluster_count && FAILED(result->layout->GetClusterMetrics(cluster_metrics.data(), cluster_count, &cluster_count))) return NULL;
  unsigned position = 0; result->clusters.push_back(0);
  for (const auto &cluster : cluster_metrics) {
    if (!cluster.length || cluster.length > text.size() - position) return NULL;
    position += cluster.length; result->clusters.push_back(position);
  }
  if (position != text.size()) return NULL;
  DWRITE_LINE_METRICS lines[1]; UINT32 count = 0;
  hr = result->layout->GetLineMetrics(lines, 1, &count);
  if (FAILED(hr) && hr != E_NOT_SUFFICIENT_BUFFER) return NULL;
  if (!count || count > text.size() + 1) return NULL;
  std::vector<DWRITE_LINE_METRICS> all(count);
  if (FAILED(result->layout->GetLineMetrics(all.data(), count, &count))) return NULL;
  if (v[5] && FAILED(result->layout->SetLineSpacing(DWRITE_LINE_SPACING_METHOD_UNIFORM, (FLOAT)v[5], all[0].baseline))) return NULL;
  if (FAILED(result->layout->GetLineMetrics(all.data(), count, &count))) return NULL;
  DWRITE_TEXT_METRICS m = {};
  if (FAILED(result->layout->GetMetrics(&m))) return NULL;
  auto *renderer = new(std::nothrow) TextOutlineRenderer;
  if (!renderer) return NULL;
  hr = result->layout->Draw(NULL, renderer, 0, 0);
  unsigned points = renderer->points;
  if (SUCCEEDED(hr)) result->outline = std::move(renderer->path);
  renderer->Release(); if (FAILED(hr)) return NULL;
  RectF ink(0,0,0,0);
  if (points && result->outline->GetBounds(&ink) != Ok) return NULL;
  metrics[0] = m.widthIncludingTrailingWhitespace; metrics[1] = m.height; metrics[2] = all[0].baseline;
  metrics[3] = count; metrics[4] = ink.X; metrics[5] = ink.Y; metrics[6] = ink.Width; metrics[7] = ink.Height;
  *cost = 4096u + length * 32u + points * 16u;
  return result.release();
}
static void text_destroy_native(void *layout) { delete (DrawTextLayout *)layout; }
static int text_query_native(void *pointer, unsigned mode, unsigned index, unsigned trailing, double x, double y, double *out) {
  auto *text = (DrawTextLayout *)pointer;
  std::lock_guard<std::mutex> lock(text->mutex);
  DWRITE_HIT_TEST_METRICS hit = {}; BOOL edge = trailing != 0, inside = TRUE;
  HRESULT hr; unsigned position;
  if (!mode) hr = text->layout->HitTestPoint((FLOAT)x, (FLOAT)y, &edge, &inside, &hit);
  else {
    auto at = std::lower_bound(text->byte_offsets.begin(), text->byte_offsets.end(), index);
    if (at == text->byte_offsets.end() || *at != index) return 0;
    FLOAT cx, cy;
    hr = text->layout->HitTestTextPosition((UINT32)(at - text->byte_offsets.begin()), edge, &cx, &cy, &hit);
    if (SUCCEEDED(hr) && at + 1 == text->byte_offsets.end()) {
      out[0] = index; out[1] = 0; out[2] = 0; out[3] = 1;
      out[4] = cx; out[5] = cy; out[6] = hit.height; return 1;
    }
  }
  if (FAILED(hr) || hit.textPosition >= text->byte_offsets.size() ||
      hit.length > text->byte_offsets.size() - 1 - hit.textPosition) return 0;
  // Normalize scalar positions inside combining/ligature/surrogate clusters
  // with the same layout's cluster metrics before asking for caret geometry.
  auto cluster = std::upper_bound(text->clusters.begin(), text->clusters.end(), hit.textPosition);
  if (cluster == text->clusters.begin()) return 0;
  position = *--cluster;
  unsigned end = cluster + 1 != text->clusters.end() ? *(cluster + 1) : position;
  out[0] = text->byte_offsets[position];
  out[1] = text->byte_offsets[end] - out[0];
  FLOAT cx, cy; DWRITE_HIT_TEST_METRICS caret = {};
  if (FAILED(text->layout->HitTestTextPosition(position, edge, &cx, &cy, &caret))) return 0;
  out[2] = edge ? 1 : 0; out[3] = inside ? 1 : 0;
  out[4] = cx; out[5] = cy; out[6] = caret.height;
  return 1;
}
}
extern "C" void xu_draw_text_init(void) {
  std::call_once(text_once, [] {
    ULONG_PTR token = 0; GdiplusStartupInput startup;
    if (GdiplusStartup(&token, &startup, NULL) != Ok) return;
    xu_ui_surface_set_backend_v2(surface_render_native,XU_UI_SURFACE_BATCH_RECTS);
  xu_ui_display_list_set_backend(compile_scene_native,destroy_scene_native);
    // GDI+ and the shared font factory live for the process, like OS font caches.
    if (FAILED(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory), (IUnknown **)&text_factory))) return;
    xu_ui_text_set_query_backend(text_query_native);
    xu_ui_text_set_backend(text_create_native, text_destroy_native);
  });
}
