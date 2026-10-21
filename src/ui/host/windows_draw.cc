#include "xu_ui_windows.h"
// Xu #ui/draw content plugin (Windows GDI+).
// Exports xu_draw_plugin_vtable. Command protocol: see macos_draw.swift.

#include "xu_content_abi.h"
#include "xu_draw_frame.h"
#include "xu_ui_display_list.h"
#include "xu_ui_input.h"
#include "xu_ui_requests.h"
#include "xu_ui_images.h"
#include "xu_ui_text_input.h"
#include "xu_ui_text_input_native.h"
#include <memory>
#include <unordered_map>

#include <windows.h>
#include <imm.h>
#include "xu_ui_dpi.h"
#include <gdiplus.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>

using namespace Gdiplus;
static void *compile_scene_native(const XuUiFrameLease *);
static void destroy_scene_native(void *);
static int surface_render_native(const XuUiFrameLease *,unsigned,unsigned,double,double,unsigned char *);
#include "windows_text.inc"
#include "windows_path.inc"

enum OpKind {
  OP_FILL_RECT,
  OP_STROKE_RECT,
  OP_ROUND,
  OP_DIAMOND,
  OP_LINE,
  OP_TEXT,
  OP_OVAL,
  OP_TRI,
  OP_POLY,
  OP_ARC,
  OP_PUSH,
  OP_POP,
  OP_ORIGIN,
  OP_TRANSLATE,
  OP_ROTATE,
  OP_SCALE,
  OP_CLIP_RECT,
  OP_IMAGE,
  OP_TEXT_LAYOUT,
  OP_PATH,
  OP_DISPLAY_LIST
};

struct DrawColor {
  int on;
  BYTE r, g, b, a;
};

struct DrawImage {
  XuUiBitmap *bitmap;
  std::unique_ptr<Bitmap> native;
  explicit DrawImage(XuUiBitmap *source) : bitmap(source) {
    unsigned width, height;
    auto *pixels = xu_ui_bitmap_pixels(source, &width, &height);
    xu_ui_bitmap_retain(bitmap);
    native.reset(new Bitmap((INT)width, (INT)height, (INT)width * 4, PixelFormat32bppPARGB,
                             const_cast<BYTE *>(pixels)));
  }
  ~DrawImage() { native.reset(); xu_ui_bitmap_release(bitmap); }
};

struct Op {
  int kind;
  double x, y, w, h, x2, y2, x3, y3, radius, a0, a1, lw, size;
  DrawColor fill, stroke;
  std::string text;
  std::vector<double> pts;
  std::shared_ptr<DrawImage> image;
  std::shared_ptr<XuUiText> layout;
  std::shared_ptr<DrawPath> path;
  std::shared_ptr<XuUiDisplayList> list;
  unsigned image_flags = 0;
};

struct DrawPen {
  DrawColor fill, stroke;
  double width;
};

struct DrawPrompt;
struct DrawTextInput;
struct XuContentPlugin {
  // Compiled fragments can be replayed by workers and the window together.
  // GDI+ paths/bitmaps require synchronization even for read-only rendering.
  std::mutex scene_mutex;
  XuContentHost host;
  HWND hwnd;
  std::vector<Op> ops;
  std::vector<Op> display_ops;
  std::unordered_map<XuUiBitmap *, std::weak_ptr<DrawImage>> images;
  DrawColor display_bg;
  std::string display_label;
  bool building;
  DrawColor bg;
  DrawColor pen_fill;
  DrawColor pen_stroke;
  double pen_lw;
  std::vector<DrawPen> pen_stack;
  std::string label;
  int down;
  int dragging;
  int last_x;
  int last_y;
  double cam_x;
  double cam_y;
  int pan_enabled;
  int input_enabled, pointer_inside, cursor;
  unsigned buttons;
  double input_x, input_y;
  unsigned canvas_generation;
  double device_scale;
  int metrics_width, metrics_height;
  double metrics_scale;
  bool display_logical;
  bool pending_logical;
  bool closing;
  DrawPrompt *prompt = NULL;
  std::shared_ptr<DrawTextInput> text_input;
  uint64_t text_input_id = 0;
};

static void draw_metrics(XuContentPlugin *p, int width, int height, double scale) {
  if (p->closing || width < 0 || height < 0 || !isfinite(scale) || scale <= 0) return;
  p->device_scale = scale;
  if (p->metrics_width == width && p->metrics_height == height && p->metrics_scale == scale) return;
  p->metrics_width = width; p->metrics_height = height; p->metrics_scale = scale;
  xu_ui_canvas_metrics(&p->host, width / scale, height / scale, (unsigned)width, (unsigned)height, scale, scale);
}

static const wchar_t *kClass = L"XuDrawCanvas";

static DrawColor color_off(void) {
  DrawColor c;
  c.on = 0;
  c.r = c.g = c.b = 0;
  c.a = 255;
  return c;
}

static DrawColor color_white(void) {
  DrawColor c;
  c.on = 1;
  c.r = c.g = c.b = 255;
  c.a = 255;
  return c;
}

static DrawColor parse_hex(const char *hex) {
  DrawColor c = color_off();
  if (!hex || !hex[0] || hex[0] == '-') return c;
  const char *h = hex;
  if (h[0] == '#') h++;
  unsigned n = 0;
  size_t len = strlen(h);
  if (len == 6) {
    if (sscanf(h, "%x", &n) != 1) return c;
    c.on = 1;
    c.r = (BYTE)((n >> 16) & 0xff);
    c.g = (BYTE)((n >> 8) & 0xff);
    c.b = (BYTE)(n & 0xff);
    c.a = 255;
    return c;
  }
  if (len == 8) {
    if (sscanf(h, "%x", &n) != 1) return c;
    c.on = 1;
    c.r = (BYTE)((n >> 24) & 0xff);
    c.g = (BYTE)((n >> 16) & 0xff);
    c.b = (BYTE)((n >> 8) & 0xff);
    c.a = (BYTE)(n & 0xff);
    return c;
  }
  return c;
}

static DrawColor parse_color_or_pen(const DrawColor *pen, const char *s) {
  if (s && s[0] == '.' && s[1] == 0) return *pen;
  return parse_hex(s);
}

static double parse_lw_or_pen(double pen, const char *s) {
  if (s && s[0] == '.' && s[1] == 0) return pen;
  return s && s[0] ? atof(s) : pen;
}

static int split_tabs(char *s, std::vector<char *> &out) {
  out.push_back(s);
  for (char *p = s; *p; p++) {
    if (*p == '\t') {
      *p = 0;
      out.push_back(p + 1);
    }
  }
  return (int)out.size();
}

static double num(const char *s, double d) {
  if (!s || !s[0]) return d;
  return atof(s);
}

static Gdiplus::Color gp(DrawColor c) {
  return Gdiplus::Color(c.a, c.r, c.g, c.b);
}

static void report_click(XuContentPlugin *p, int x, int y) {
  if (!p || !p->host.append_shell_event) return;
  char ev[64];
  snprintf(ev, sizeof(ev), "click\t%d\t%d", x, y);
  xu_content_event(&p->host,ev);
}

static void report_scroll(XuContentPlugin *p, int dx, int dy) {
  if (!p || !p->host.append_shell_event) return;
  char ev[64];
  snprintf(ev, sizeof(ev), "scroll\t%d\t%d", dx, dy);
  xu_content_event(&p->host,ev);
}

static void report_drag(XuContentPlugin *p, int dx, int dy) {
  if (!p || !p->host.append_shell_event) return;
  char ev[64];
  snprintf(ev, sizeof(ev), "drag\t%d\t%d", dx, dy);
  xu_content_event(&p->host,ev);
}

static void paint_round(Graphics *g, Op *o) {
  GraphicsPath path;
  REAL r = (REAL)o->radius;
  REAL x = (REAL)o->x, y = (REAL)o->y, w = (REAL)o->w, h = (REAL)o->h;
  if (r * 2 > w) r = w * 0.5f;
  if (r * 2 > h) r = h * 0.5f;
  path.AddArc(x, y, r * 2, r * 2, 180, 90);
  path.AddArc(x + w - r * 2, y, r * 2, r * 2, 270, 90);
  path.AddArc(x + w - r * 2, y + h - r * 2, r * 2, r * 2, 0, 90);
  path.AddArc(x, y + h - r * 2, r * 2, r * 2, 90, 90);
  path.CloseFigure();
  if (o->fill.on) {
    SolidBrush br(gp(o->fill));
    g->FillPath(&br, &path);
  }
  if (o->stroke.on) {
    Pen pen(gp(o->stroke), (REAL)o->lw);
    g->DrawPath(&pen, &path);
  }
}

static std::wstring wide_text(const std::string &text) {
  if (text.empty()) return {};
  int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), (int)text.size(), NULL, 0);
  if (n <= 0) return {};
  std::wstring result((size_t)n, L'\0');
  if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), (int)text.size(), result.data(), n) != n) return {};
  return result;
}

struct DrawPrompt {
  XuContentPlugin *owner;
  uint64_t id;
  HWND dialog = NULL, entry = NULL, parent = NULL;
  bool finishing = false, parent_enabled = false, controls_ok = false;
  std::wstring title, seed;
};
static void finish_prompt(DrawPrompt *prompt, unsigned status) {
  if (!prompt || prompt->finishing) return;
  prompt->finishing = true;
  std::string text;
  if (status == XU_REQUEST_COMPLETED) {
    int n = GetWindowTextLengthW(prompt->entry);
    if (n > (int)XU_UI_REQUEST_MAX_TEXT) status = XU_REQUEST_FAILED;
    else if (n > 0) {
      std::vector<wchar_t> value((size_t)n + 1);
      n = GetWindowTextW(prompt->entry, value.data(), n + 1);
      int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), n, NULL, 0, NULL, NULL);
      if (bytes <= 0) status = XU_REQUEST_FAILED;
      else {
        text.resize((size_t)bytes);
        if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(), n, text.data(), bytes, NULL, NULL) != bytes)
          status = XU_REQUEST_FAILED;
      }
    }
  }
  xu_ui_request_complete(prompt->id, status, text.data(), (unsigned)text.size());
  DestroyWindow(prompt->dialog); // WM_NCDESTROY owns cleanup, including external parent closure.
}
static INT_PTR CALLBACK prompt_proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp) {
  auto *prompt = (DrawPrompt *)GetWindowLongPtrW(hwnd, DWLP_USER);
  if (message == WM_INITDIALOG) {
    prompt = (DrawPrompt *)lp; SetWindowLongPtrW(hwnd, DWLP_USER, (LONG_PTR)prompt); prompt->dialog = hwnd;
    SetWindowTextW(hwnd, prompt->title.empty() ? L"Xu" : prompt->title.c_str());
    RECT rect; GetClientRect(hwnd, &rect); double scale = xu_ui_window_scale(hwnd);
    int margin = (int)(16 * scale), height = (int)(26 * scale), button = (int)(80 * scale);
    prompt->entry = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", prompt->seed.c_str(), WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
      margin, margin, rect.right - margin * 2, height, hwnd, (HMENU)100, GetModuleHandleW(NULL), NULL);
    HWND ok = CreateWindowExW(0, L"BUTTON", L"OK", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
      rect.right - margin * 2 - button * 2, margin * 2 + height, button, height, hwnd, (HMENU)IDOK, GetModuleHandleW(NULL), NULL);
    HWND cancel = CreateWindowExW(0, L"BUTTON", L"Cancel", WS_CHILD | WS_VISIBLE | WS_TABSTOP,
      rect.right - margin - button, margin * 2 + height, button, height, hwnd, (HMENU)IDCANCEL, GetModuleHandleW(NULL), NULL);
    prompt->controls_ok = prompt->entry && ok && cancel;
    HFONT font = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    for (HWND control : {prompt->entry, ok, cancel}) if (control) SendMessageW(control, WM_SETFONT, (WPARAM)font, TRUE);
    SendMessageW(prompt->entry, EM_LIMITTEXT, XU_UI_REQUEST_MAX_TEXT, 0);
    SendMessageW(hwnd, DM_SETDEFID, IDOK, 0);
    SetFocus(prompt->entry); return FALSE;
  }
  if (!prompt) return FALSE;
  if (message == WM_COMMAND && (LOWORD(wp) == IDOK || LOWORD(wp) == IDCANCEL)) {
    finish_prompt(prompt, LOWORD(wp) == IDOK ? XU_REQUEST_COMPLETED : XU_REQUEST_CANCELLED); return TRUE;
  }
  if (message == WM_CLOSE) { finish_prompt(prompt, XU_REQUEST_CANCELLED); return TRUE; }
  if (message == WM_NCDESTROY) {
    SetWindowLongPtrW(hwnd, DWLP_USER, 0); prompt->owner->prompt = NULL;
    if (!prompt->finishing) xu_ui_request_complete(prompt->id, XU_REQUEST_CANCELLED, "", 0);
    if (prompt->parent_enabled && IsWindow(prompt->parent)) EnableWindow(prompt->parent, TRUE);
    delete prompt;
  }
  return FALSE;
}
static int show_prompt(XuContentPlugin *p, uint64_t id) {
  char *wire = xu_ui_request_take(id, p->host.canvas_id, p->canvas_generation); if (!wire) return 0;
  std::string title, seed; bool valid = xu_request_prompt_text(wire, &title, &seed); free(wire);
  HWND parent = (HWND)p->host.native_window;
  if (!valid || !IsWindow(parent) || p->closing) { xu_ui_request_complete(id, XU_REQUEST_FAILED, "", 0); return 1; }
  if (p->prompt) finish_prompt(p->prompt, XU_REQUEST_CANCELLED);
  auto *prompt = new DrawPrompt; prompt->owner = p; prompt->id = id; prompt->parent = parent;
  prompt->parent_enabled = IsWindowEnabled(parent) != FALSE; prompt->title = wide_text(title); prompt->seed = wide_text(seed);
  p->prompt = prompt;
  struct { DLGTEMPLATE dialog; WORD menu, window_class, title; } definition = {};
  definition.dialog.style = WS_POPUP | WS_CAPTION | WS_SYSMENU | DS_MODALFRAME | DS_CENTER;
  definition.dialog.cx = 240; definition.dialog.cy = 72;
  HWND dialog = CreateDialogIndirectParamW(GetModuleHandleW(NULL), &definition.dialog, parent, prompt_proc, (LPARAM)prompt);
  if (!dialog) {
    if (p->prompt == prompt) { p->prompt = NULL; delete prompt; }
    xu_ui_request_complete(id, XU_REQUEST_FAILED, "", 0); return 1;
  }
  if (!prompt->controls_ok) { finish_prompt(prompt, XU_REQUEST_FAILED); return 1; }
  EnableWindow(parent, FALSE); ShowWindow(dialog, SW_SHOW); SetFocus(prompt->entry);
  return 1;
}

static void paint_ops(XuContentPlugin *p,Graphics &g) {
  std::vector<GraphicsState> stack;
  double scale = p->display_logical ? p->device_scale : 1.0;
  g.ScaleTransform((REAL)scale, (REAL)scale);
  g.TranslateTransform((REAL)(-p->cam_x / scale), (REAL)(-p->cam_y / scale));
  Matrix canvas_base;
  g.GetTransform(&canvas_base);
  for (size_t i = 0; i < p->display_ops.size(); i++) {
    Op &o = p->display_ops[i];
    if (o.kind == OP_PUSH) {
      stack.push_back(g.Save());
    } else if (o.kind == OP_POP) {
      if (!stack.empty()) {
        g.Restore(stack.back());
        stack.pop_back();
      }
    } else if (o.kind == OP_ORIGIN) {
      g.SetTransform(&canvas_base);
    } else if (o.kind == OP_TRANSLATE) {
      g.TranslateTransform((REAL)o.x, (REAL)o.y);
    } else if (o.kind == OP_ROTATE) {
      g.RotateTransform((REAL)o.a0);
    } else if (o.kind == OP_SCALE) {
      g.ScaleTransform((REAL)o.x, (REAL)o.y);
    } else if (o.kind == OP_CLIP_RECT) {
      g.SetClip(RectF((REAL)o.x, (REAL)o.y, (REAL)o.w, (REAL)o.h), CombineModeIntersect);
    } else if(o.kind==OP_DISPLAY_LIST) {
      auto *scene=(XuContentPlugin *)xu_ui_display_list_native(o.list.get());
      std::lock_guard<std::mutex> lock(scene->scene_mutex);
      auto state=g.Save();paint_ops(scene,g);g.Restore(state);
    } else if(o.kind==OP_PATH) {
      auto &path=*o.path; unsigned flags=path.flags;
      if(!path.native->GetPointCount()) continue;
      if(flags&1) {
        Pen pen(gp(o.fill),(REAL)path.width);
        auto cap=((flags>>2)&3)==1 ? LineCapRound : ((flags>>2)&3)==2 ? LineCapSquare : LineCapFlat;
        pen.SetStartCap(cap);pen.SetEndCap(cap);
        pen.SetLineJoin(((flags>>4)&3)==1 ? LineJoinRound : ((flags>>4)&3)==2 ? LineJoinBevel : LineJoinMiter);
        pen.SetMiterLimit((REAL)path.miter);g.DrawPath(&pen,path.native.get());
      } else {SolidBrush brush(gp(o.fill));g.FillPath(&brush,path.native.get());}
    } else if (o.kind == OP_TEXT_LAYOUT) {
      auto *layout = (DrawTextLayout *)xu_ui_text_native(o.layout.get());
      std::lock_guard<std::mutex> lock(layout->mutex);
      auto saved = g.Save(); g.TranslateTransform((REAL)o.x, (REAL)o.y, MatrixOrderPrepend);
      SolidBrush brush(gp(o.fill));
      if (layout->outline->GetPointCount()) g.FillPath(&brush, layout->outline.get());
      g.Restore(saved);
    } else if (o.kind == OP_IMAGE && o.w > 0 && o.h > 0 && (o.image_flags & 65535u)) {
      GraphicsState state = g.Save();
      g.SetInterpolationMode((o.image_flags & 65536u) ? InterpolationModeBilinear : InterpolationModeNearestNeighbor);
      g.SetPixelOffsetMode(PixelOffsetModeHalf);
      ImageAttributes attributes;
      ColorMatrix alpha = {{{1,0,0,0,0}, {0,1,0,0,0}, {0,0,1,0,0},
                             {0,0,0,(REAL)((o.image_flags & 65535u) / 65535.0),0}, {0,0,0,0,1}}};
      attributes.SetColorMatrix(&alpha);
      // GDI+ Clamp uses a transparent border. Mirroring the half-pixel filter
      // footprint repeats the edge texel, matching Cairo/CoreGraphics sampling.
      attributes.SetWrapMode(WrapModeTileFlipXY);
      g.DrawImage(o.image->native.get(), RectF((REAL)o.x, (REAL)o.y, (REAL)o.w, (REAL)o.h),
                  (REAL)o.x2, (REAL)o.y2, (REAL)o.x3, (REAL)o.y3, UnitPixel, &attributes);
      g.Restore(state);
    } else if (o.kind == OP_FILL_RECT && o.fill.on) {
      SolidBrush br(gp(o.fill));
      g.FillRectangle(&br, (REAL)o.x, (REAL)o.y, (REAL)o.w, (REAL)o.h);
    } else if (o.kind == OP_STROKE_RECT && o.stroke.on) {
      Pen pen(gp(o.stroke), (REAL)o.lw);
      g.DrawRectangle(&pen, (REAL)o.x, (REAL)o.y, (REAL)o.w, (REAL)o.h);
    } else if (o.kind == OP_ROUND) {
      paint_round(&g, &o);
    } else if (o.kind == OP_DIAMOND) {
      PointF pts[4] = {
          PointF((REAL)(o.x + o.w * 0.5), (REAL)o.y),
          PointF((REAL)(o.x + o.w), (REAL)(o.y + o.h * 0.5)),
          PointF((REAL)(o.x + o.w * 0.5), (REAL)(o.y + o.h)),
          PointF((REAL)o.x, (REAL)(o.y + o.h * 0.5)),
      };
      if (o.fill.on) {
        SolidBrush br(gp(o.fill));
        g.FillPolygon(&br, pts, 4);
      }
      if (o.stroke.on) {
        Pen pen(gp(o.stroke), (REAL)o.lw);
        g.DrawPolygon(&pen, pts, 4);
      }
    } else if (o.kind == OP_LINE && o.stroke.on) {
      Pen pen(gp(o.stroke), (REAL)o.lw);
      pen.SetStartCap(LineCapRound);
      pen.SetEndCap(LineCapRound);
      g.DrawLine(&pen, (REAL)o.x, (REAL)o.y, (REAL)o.x2, (REAL)o.y2);
    } else if (o.kind == OP_TEXT && o.fill.on) {
      FontFamily ff(L"Segoe UI");
      Font font(&ff, (REAL)(o.size > 0 ? o.size : 13), FontStyleRegular, UnitPixel);
      SolidBrush br(gp(o.fill));
      std::wstring text = wide_text(o.text);
      g.DrawString(text.data(), (INT)text.size(), &font, PointF((REAL)o.x, (REAL)o.y), &br);
    } else if (o.kind == OP_OVAL) {
      if (o.fill.on) {
        SolidBrush br(gp(o.fill));
        g.FillEllipse(&br, (REAL)o.x, (REAL)o.y, (REAL)o.w, (REAL)o.h);
      }
      if (o.stroke.on) {
        Pen pen(gp(o.stroke), (REAL)o.lw);
        g.DrawEllipse(&pen, (REAL)o.x, (REAL)o.y, (REAL)o.w, (REAL)o.h);
      }
    } else if (o.kind == OP_TRI) {
      PointF pts[3] = {
          PointF((REAL)o.x, (REAL)o.y),
          PointF((REAL)o.x2, (REAL)o.y2),
          PointF((REAL)o.x3, (REAL)o.y3),
      };
      if (o.fill.on) {
        SolidBrush br(gp(o.fill));
        g.FillPolygon(&br, pts, 3);
      }
      if (o.stroke.on) {
        Pen pen(gp(o.stroke), (REAL)o.lw);
        g.DrawPolygon(&pen, pts, 3);
      }
    } else if (o.kind == OP_POLY && o.pts.size() >= 4) {
      int npts = (int)(o.pts.size() / 2);
      std::vector<PointF> pts((size_t)npts);
      for (int k = 0; k < npts; k++) {
        pts[(size_t)k] = PointF((REAL)o.pts[(size_t)(k * 2)], (REAL)o.pts[(size_t)(k * 2 + 1)]);
      }
      if (o.fill.on) {
        SolidBrush br(gp(o.fill));
        g.FillPolygon(&br, pts.data(), npts);
      }
      if (o.stroke.on) {
        Pen pen(gp(o.stroke), (REAL)o.lw);
        g.DrawPolygon(&pen, pts.data(), npts);
      }
    } else if (o.kind == OP_ARC && o.stroke.on) {
      REAL sweep = (REAL)(o.a1 - o.a0);
      Pen pen(gp(o.stroke), (REAL)o.lw);
      pen.SetStartCap(LineCapRound);
      pen.SetEndCap(LineCapRound);
      REAL d = (REAL)(o.radius * 2);
      g.DrawArc(&pen, (REAL)(o.x - o.radius), (REAL)(o.y - o.radius), d, d, (REAL)o.a0, sweep);
    }
  }
}

static void paint(XuContentPlugin *p, HDC hdc, int width, int height) {
  Graphics g(hdc);
  g.SetSmoothingMode(SmoothingModeAntiAlias);
  SolidBrush bg(Gdiplus::Color(255, p->display_bg.r, p->display_bg.g, p->display_bg.b));
  g.FillRectangle(&bg, 0, 0, width, height);
  if (p->display_ops.empty() && !p->display_label.empty()) {
    FontFamily ff(L"Segoe UI");
    Font font(&ff, 22, FontStyleBold, UnitPixel);
    SolidBrush white(Gdiplus::Color(255, 255, 255, 255));
    std::wstring text = wide_text(p->display_label);
    g.DrawString(text.data(), (INT)text.size(), &font, PointF(24, (REAL)height * 0.45f), &white);
    return;
  }
  paint_ops(p,g);
}

static unsigned input_modifiers() {
  return ((GetKeyState(VK_SHIFT) & 0x8000) ? 1u : 0u) |
         ((GetKeyState(VK_CONTROL) & 0x8000) ? 2u : 0u) |
         ((GetKeyState(VK_MENU) & 0x8000) ? 4u : 0u) |
         (((GetKeyState(VK_LWIN) | GetKeyState(VK_RWIN)) & 0x8000) ? 8u : 0u);
}
static unsigned input_key(WPARAM key) {
  if ((key >= 'A' && key <= 'Z') || (key >= '0' && key <= '9') || key == VK_SPACE) return (unsigned)key;
  if (key >= VK_F1 && key <= VK_F12) return XUI_KEY_F1 + (unsigned)(key - VK_F1);
  switch (key) {
    case VK_SHIFT: case VK_LSHIFT: case VK_RSHIFT: return 304;
    case VK_CONTROL: case VK_LCONTROL: case VK_RCONTROL: return 305;
    case VK_MENU: case VK_LMENU: case VK_RMENU: return 306;
    case VK_LWIN: case VK_RWIN: return 307;
    case VK_CAPITAL: return 308;
    case VK_ESCAPE: return XUI_KEY_ESCAPE; case VK_TAB: return XUI_KEY_TAB;
    case VK_RETURN: return XUI_KEY_ENTER; case VK_BACK: return XUI_KEY_BACKSPACE;
    case VK_DELETE: return XUI_KEY_DELETE; case VK_LEFT: return XUI_KEY_LEFT;
    case VK_RIGHT: return XUI_KEY_RIGHT; case VK_UP: return XUI_KEY_UP_ARROW;
    case VK_DOWN: return XUI_KEY_DOWN_ARROW; case VK_HOME: return XUI_KEY_HOME;
    case VK_END: return XUI_KEY_END; case VK_PRIOR: return XUI_KEY_PAGE_UP;
    case VK_NEXT: return XUI_KEY_PAGE_DOWN; case VK_INSERT: return XUI_KEY_INSERT;
    default: return 0;
  }
}
static void raw_pointer(XuContentPlugin *p, unsigned kind, double x, double y,
                        double dx = 0, double dy = 0, unsigned button = 0, unsigned clicks = 0) {
  double scale = p->device_scale;
  if (p->input_enabled && !p->closing) xu_ui_input_emit(&p->host, kind, x / scale, y / scale, dx / scale, dy / scale, button,
                                        p->buttons, input_modifiers(), 0, 0, 0, clicks);
}
static void cancel_input(XuContentPlugin *p) {
  p->buttons = 0; p->down = 0; p->dragging = 0;
  raw_pointer(p, XUI_POINTER_CANCEL, p->input_x, p->input_y);
}

#include "windows_text_input.inc"

static void close_canvas(XuContentPlugin *p) {
  if (p->closing) return;
  draw_text_input_detach(p);
  if (p->prompt) finish_prompt(p->prompt, XU_REQUEST_CANCELLED);
  cancel_input(p);
  p->closing = true;
  xu_ui_canvas_close(p->host.canvas_id, p->canvas_generation);
  xu_ui_canvas_event(&p->host, false);
}

static LRESULT CALLBACK wnd_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
  XuContentPlugin *p = (XuContentPlugin *)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
  if (p && msg == WM_NCDESTROY) {
    close_canvas(p); p->hwnd = NULL;
    SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
    return DefWindowProcW(hwnd, msg, wp, lp);
  }
  if (p && (msg == WM_SIZE || msg == WM_DPICHANGED_AFTERPARENT)) {
    RECT rect; GetClientRect(hwnd, &rect);
    draw_metrics(p, rect.right, rect.bottom, xu_ui_window_scale(hwnd));
    InvalidateRect(hwnd, NULL, FALSE);
    auto client = p->text_input; if (client) client->refresh();
  }
  if (p && msg == WM_SETFOCUS) draw_text_input_focus(p);
  if (p && p->input_enabled && msg == WM_GETDLGCODE) return DLGC_WANTALLKEYS | DLGC_WANTCHARS;
  if (p && msg == WM_SETCURSOR && LOWORD(lp) == HTCLIENT) {
    const unsigned cursors[] = {32512, 32513, 32515, 32649, 32644, 32645};
    SetCursor(LoadCursorW(NULL, MAKEINTRESOURCEW(cursors[p->cursor])));
    return TRUE;
  }
  if (p && (msg == WM_KILLFOCUS || (msg == WM_CAPTURECHANGED && (p->down || p->buttons)))) cancel_input(p);
  if (p && (msg == WM_KEYDOWN || msg == WM_KEYUP || msg == WM_SYSKEYDOWN || msg == WM_SYSKEYUP)) {
    if (p->input_enabled) xu_ui_input_emit(&p->host,
      (msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN) ? XUI_KEY_DOWN : XUI_KEY_UP,
      0, 0, 0, 0, 0, p->buttons, input_modifiers(), input_key(wp),
      (unsigned)(((lp >> 16) & 255) | (((lp >> 24) & 1) << 8)), (msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN) && ((lp >> 30) & 1));
  }
  if (p && p->input_enabled && (msg == WM_LBUTTONDOWN || msg == WM_LBUTTONDBLCLK || msg == WM_RBUTTONDOWN ||
            msg == WM_RBUTTONDBLCLK || msg == WM_MBUTTONDOWN || msg == WM_MBUTTONDBLCLK)) {
    unsigned button = (msg == WM_LBUTTONDOWN || msg == WM_LBUTTONDBLCLK) ? 1u :
                      (msg == WM_RBUTTONDOWN || msg == WM_RBUTTONDBLCLK) ? 2u : 3u;
    draw_text_input_grab_focus(p);
    p->buttons |= 1u << (button - 1);
    SetCapture(hwnd);
    unsigned clicks = (msg == WM_LBUTTONDBLCLK || msg == WM_RBUTTONDBLCLK || msg == WM_MBUTTONDBLCLK) ? 2u : 1u;
    raw_pointer(p, XUI_POINTER_DOWN, (short)LOWORD(lp), (short)HIWORD(lp), 0, 0, button, clicks);
    if (msg == WM_LBUTTONDBLCLK) msg = WM_LBUTTONDOWN;
  }
  if (p && p->input_enabled && (msg == WM_LBUTTONUP || msg == WM_RBUTTONUP || msg == WM_MBUTTONUP)) {
    unsigned button = msg == WM_LBUTTONUP ? 1u : msg == WM_RBUTTONUP ? 2u : 3u;
    p->buttons &= ~(1u << (button - 1));
    raw_pointer(p, XUI_POINTER_UP, (short)LOWORD(lp), (short)HIWORD(lp), 0, 0, button);
    if (button != 1 && !p->buttons) ReleaseCapture();
  }
  if (p && msg == WM_MOUSEMOVE) {
    double x = (short)LOWORD(lp), y = (short)HIWORD(lp);
    if (!p->pointer_inside) {
      p->pointer_inside = 1; p->input_x = x; p->input_y = y;
      TRACKMOUSEEVENT tracking = {sizeof(tracking), TME_LEAVE, hwnd, 0};
      TrackMouseEvent(&tracking);
      raw_pointer(p, XUI_POINTER_ENTER, x, y);
    }
    raw_pointer(p, XUI_POINTER_MOVE, x, y, x - p->input_x, y - p->input_y);
    p->input_x = x; p->input_y = y;
  }
  if (p && msg == WM_MOUSELEAVE) {
    p->pointer_inside = 0;
    raw_pointer(p, XUI_POINTER_LEAVE, p->input_x, p->input_y);
  }
  if (msg == WM_LBUTTONDOWN && p) {
    if (p->text_input_id) draw_text_input_grab_focus(p);
    p->down = 1;
    p->dragging = 0;
    p->last_x = (int)(short)LOWORD(lp);
    p->last_y = (int)(short)HIWORD(lp);
    SetCapture(hwnd);
    return 0;
  }
  if (msg == WM_MOUSEMOVE && p && p->down) {
    int x = (int)(short)LOWORD(lp);
    int y = (int)(short)HIWORD(lp);
    int dx = x - p->last_x;
    int dy = y - p->last_y;
    if (dx != 0 || dy != 0) {
      p->dragging = 1;
      p->last_x = x;
      p->last_y = y;
      if (p->pan_enabled) {
        p->cam_x -= (double)dx;
        p->cam_y -= (double)dy;
        InvalidateRect(hwnd, NULL, FALSE);
      }
      report_drag(p, dx, dy);
    }
    return 0;
  }
  if (msg == WM_LBUTTONUP && p) {
    int x = (int)(short)LOWORD(lp);
    int y = (int)(short)HIWORD(lp);
    int was_down = p->down;
    p->down = 0;
    ReleaseCapture();
    if (was_down && !p->dragging) report_click(p, x, y);
    p->dragging = 0;
    return 0;
  }
  if (msg == WM_MOUSEWHEEL && p) {
    int d = GET_WHEEL_DELTA_WPARAM(wp);
    if (d == 0) return 0;
    int dy = -(d / 6);
    if (dy == 0) dy = d > 0 ? -8 : 8;
    if (p->pan_enabled) {
      p->cam_y -= (double)dy;
      InvalidateRect(hwnd, NULL, FALSE);
    }
    raw_pointer(p, XUI_POINTER_SCROLL, p->input_x, p->input_y, 0, dy);
    report_scroll(p, 0, dy);
    return 0;
  }
  if (msg == WM_MOUSEHWHEEL && p) {
    int d = GET_WHEEL_DELTA_WPARAM(wp);
    if (d == 0) return 0;
    int dx = d / 6;
    if (dx == 0) dx = d > 0 ? 8 : -8;
    if (p->pan_enabled) {
      p->cam_x -= (double)dx;
      InvalidateRect(hwnd, NULL, FALSE);
    }
    raw_pointer(p, XUI_POINTER_SCROLL, p->input_x, p->input_y, dx, 0);
    report_scroll(p, dx, 0);
    return 0;
  }
  if (msg == WM_PAINT && p) {
    PAINTSTRUCT ps;
    HDC hdc = BeginPaint(hwnd, &ps);
    RECT rc;
    GetClientRect(hwnd, &rc);
    paint(p, hdc, rc.right - rc.left, rc.bottom - rc.top);
    EndPaint(hwnd, &ps);
    return 0;
  }
  if (msg == WM_ERASEBKGND) return 1;
  return DefWindowProcW(hwnd, msg, wp, lp);
}

static void ensure_class(void) {
  static int done = 0;
  if (done) return;
  WNDCLASSW wc;
  memset(&wc, 0, sizeof(wc));
  wc.style = CS_DBLCLKS;
  wc.lpfnWndProc = wnd_proc;
  wc.hInstance = GetModuleHandleW(NULL);
  wc.hCursor = LoadCursor(NULL, IDC_ARROW);
  wc.lpszClassName = kClass;
  RegisterClassW(&wc);
  done = 1;
}

static void reset_pen(XuContentPlugin *p) {
  p->pen_stack.clear();
  p->pen_fill = color_white();
  p->pen_stroke = color_white();
  p->pen_lw = 1;
}

static XuContentPlugin *draw_create(XuContentHost *host) {
  XuContentPlugin *p = new XuContentPlugin();
  if (host) p->host = *host;
  if (!p->host.window_id) p->host.window_id = 1;
  if (!p->host.canvas_id) p->host.canvas_id = 1;
  p->canvas_generation = p->host.canvas_generation ?
      (xu_ui_canvas_valid(p->host.window_id,p->host.canvas_id,p->host.canvas_generation) ? p->host.canvas_generation : 0) :
      xu_ui_canvas_open(p->host.window_id, p->host.canvas_id);
  if (!p->canvas_generation) { delete p; return NULL; }
  p->host.canvas_generation = p->canvas_generation;
  p->device_scale = 1;
  p->metrics_width = p->metrics_height = -1;
  p->hwnd = NULL;
  p->bg.on = 1;
  p->bg.r = p->bg.g = p->bg.b = 26;
  p->bg.a = 255;
  p->pan_enabled = 1;
  p->display_bg = p->bg;
  p->building = false;
  reset_pen(p);
  return p;
}

static void draw_destroy(XuContentPlugin *p) {
  if (!p) return;
  close_canvas(p);
  if (p->hwnd) DestroyWindow(p->hwnd);
  delete p;
}

static void draw_install(XuContentPlugin *p) {
  ensure_class();
  HWND parent = (HWND)p->host.content_parent;
  if (!parent) parent = (HWND)p->host.native_window;
  if (!parent) return;
  RECT rc;
  GetClientRect(parent, &rc);
  p->hwnd = CreateWindowExW(0, kClass, L"", WS_CHILD | WS_VISIBLE, 0, 0,
                            rc.right - rc.left, rc.bottom - rc.top, parent, NULL,
                            GetModuleHandleW(NULL), NULL);
  SetWindowLongPtrW(p->hwnd, GWLP_USERDATA, (LONG_PTR)p);
  if (p->hwnd) {
    xu_ui_canvas_event(&p->host, true);
    RECT actual; GetClientRect(p->hwnd, &actual);
    draw_metrics(p, actual.right, actual.bottom, xu_ui_window_scale(p->hwnd));
  }
}

static Op blank_op(void) {
  Op o;
  o.kind = 0;
  o.x = o.y = o.w = o.h = o.x2 = o.y2 = o.x3 = o.y3 = o.radius = o.a0 = o.a1 = 0;
  o.lw = 1;
  o.size = 13;
  o.fill = color_off();
  o.stroke = color_off();
  o.text.clear();
  o.pts.clear();
  return o;
}


static DrawColor frame_color(unsigned rgba) {
  DrawColor color = {};
  color.on = 1;
  color.r = (BYTE)(rgba >> 24); color.g = (BYTE)(rgba >> 16);
  color.b = (BYTE)(rgba >> 8); color.a = (BYTE)rgba;
  return color;
}

// Validate before touching either the pending legacy list or the visible frame.
static int draw_apply_frame(XuContentPlugin *p, const void *data, unsigned len, const XuUiFrameLease *lease = NULL) {
  if (!xdf_validate(data, len)) return 0;
  const unsigned char *header = (const unsigned char *)data;
  if (xdf_u32(header + 16) != p->host.canvas_id ||
      (xdf_u16(header + 4) == 2 && xdf_u32(header + 20) != p->canvas_generation)) return 0;
  try {
  std::vector<Op> next;
  next.reserve(xdf_u32((const unsigned char *)data + 12));
  DrawColor bg = p->display_bg, fill = color_white(), stroke = color_white();
  double width = 1;
  std::vector<DrawPen> stack;
  unsigned cursor = 32;
  XuDrawCommand c;
  for (auto it = p->images.begin(); it != p->images.end();) {
    if (it->second.expired()) it = p->images.erase(it); else ++it;
  }
  while(cursor<len) {
    unsigned offset=cursor;
    if(xdf_next(data,len,&cursor,&c)!=1) return 0;
    const double *v = c.values;
    Op o = blank_op();
    switch (c.opcode) {
      case XDF_BACKGROUND: bg = frame_color(c.rgba); continue;
      case XDF_COLOR: fill = stroke = frame_color(c.rgba); continue;
      case XDF_FILL: fill = frame_color(c.rgba); continue;
      case XDF_STROKE: stroke = frame_color(c.rgba); continue;
      case XDF_WIDTH: width = v[0]; continue;
      case XDF_SAVE: stack.push_back({fill, stroke, width}); o.kind = OP_PUSH; break;
      case XDF_RESTORE:
        fill = stack.back().fill; stroke = stack.back().stroke; width = stack.back().width;
        stack.pop_back(); o.kind = OP_POP; break;
      case XDF_ORIGIN: o.kind = OP_ORIGIN; break;
      case XDF_TRANSLATE: o.kind = OP_TRANSLATE; o.x = v[0]; o.y = v[1]; break;
      case XDF_ROTATE: o.kind = OP_ROTATE; o.a0 = v[0]; break;
      case XDF_SCALE: o.kind = OP_SCALE; o.x = v[0]; o.y = v[1]; break;
      case XDF_CLIP_RECT: o.kind = OP_CLIP_RECT; o.x = v[0]; o.y = v[1]; o.w = v[2]; o.h = v[3]; break;
      case XDF_RECT: case XDF_FILL_RECT:
        o.kind = OP_FILL_RECT; o.x = v[0]; o.y = v[1]; o.w = v[2]; o.h = v[3];
        o.fill = c.opcode == XDF_RECT ? fill : frame_color(c.rgba); break;
      case XDF_RECT_LINE: case XDF_STROKE_RECT:
        o.kind = OP_STROKE_RECT; o.x = v[0]; o.y = v[1]; o.w = v[2]; o.h = v[3];
        o.stroke = c.opcode == XDF_RECT_LINE ? stroke : frame_color(c.rgba);
        o.lw = c.opcode == XDF_RECT_LINE ? width : v[4]; break;
      case XDF_LINE:
        o.kind = OP_LINE; o.x = v[0]; o.y = v[1]; o.x2 = v[2]; o.y2 = v[3];
        o.lw = v[4]; o.stroke = frame_color(c.rgba); break;
      case XDF_TEXT:
        o.kind = OP_TEXT; o.x = v[0]; o.y = v[1]; o.size = v[2];
        o.fill = frame_color(c.rgba); o.text.assign(c.text, c.text_len); break;
      case XDF_CIRCLE:
        o.kind = OP_OVAL; o.x = v[0] - v[2]; o.y = v[1] - v[2];
        o.w = o.h = v[2] * 2; o.fill = fill; break;
      case XDF_ELLIPSE:
        o.kind = OP_OVAL; o.x = v[0]; o.y = v[1]; o.w = v[2]; o.h = v[3]; o.fill = fill; break;
      case XDF_TRIANGLE:
        o.kind = OP_TRI; o.x = v[0]; o.y = v[1]; o.x2 = v[2]; o.y2 = v[3];
        o.x3 = v[4]; o.y3 = v[5]; o.fill = fill; break;
      case XDF_IMAGE: {
        auto *bitmap = xu_ui_frame_bitmap(lease, c.image_id); if (!bitmap) return 0;
        o.image = p->images[bitmap].lock();
        if (!o.image) {
          o.image = std::make_shared<DrawImage>(bitmap);
          if (o.image->native->GetLastStatus() != Ok) return 0;
          p->images[bitmap] = o.image;
        }
        o.kind = OP_IMAGE; o.x2 = v[0]; o.y2 = v[1]; o.x3 = v[2]; o.y3 = v[3];
        o.x = v[4]; o.y = v[5]; o.w = v[6]; o.h = v[7]; o.image_flags = c.rgba; break;
      }
      case XDF_TEXT_LAYOUT: {
        auto *layout = xu_ui_frame_text(lease, c.image_id); if (!layout) return 0;
        xu_ui_text_retain(layout); o.layout = std::shared_ptr<XuUiText>(layout, xu_ui_text_release);
        o.kind = OP_TEXT_LAYOUT; o.x = v[0]; o.y = v[1]; o.fill = frame_color(c.rgba); break;
      }
      case XDF_DISPLAY_LIST: {
        auto *list=xu_ui_frame_list(lease,c.image_id);if(!list || !xu_ui_display_list_native(list))return 0;
        xu_ui_display_list_retain(list);o.list=std::shared_ptr<XuUiDisplayList>(list,xu_ui_display_list_release);
        o.kind=OP_DISPLAY_LIST;break;
      }
      case XDF_PATH: {
        unsigned size=0;auto *payload=(const unsigned char *)xu_ui_frame_path(lease,offset,&size);
        if(!payload || !xup_validate(payload,size) || xdf_u32(payload+12)) return 0;
        o.path=std::make_shared<DrawPath>(payload);if(!o.path->valid) return 0;
        o.kind=OP_PATH;o.fill=frame_color(c.rgba);break;
      }
      default: return 0;
    }
    next.push_back(std::move(o));
  }
  p->display_ops.swap(next);
  p->display_logical = true;
  p->pending_logical = false;
  p->display_bg = p->bg = bg;
  p->display_label.clear(); p->label.clear();
  p->ops.clear(); p->building = false;
  reset_pen(p);
  if (p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE);
  return 1;
  } catch(...) { return 0; }
}

static void *compile_scene_native(const XuUiFrameLease *lease) {
  unsigned len=0;auto *data=(const unsigned char *)xu_ui_frame_data(lease,&len);if(!data)return NULL;
  std::unique_ptr<XuContentPlugin> scene(new(std::nothrow) XuContentPlugin{});if(!scene)return NULL;
  scene->host.canvas_id=xdf_u32(data+16);scene->canvas_generation=xdf_u32(data+20);
  scene->device_scale=1;
  if(!draw_apply_frame(scene.get(),data,len,lease))return NULL;return scene.release();
}
static void destroy_scene_native(void *scene) {delete (XuContentPlugin *)scene;}

static int surface_render_native(const XuUiFrameLease *lease,unsigned width,unsigned height,double logical_width,
                                 double logical_height,unsigned char *pixels) {
  unsigned len=0; auto *data=(const unsigned char *)xu_ui_frame_data(lease,&len);
  if(!data || !pixels) return 0;
  XuContentPlugin scene{};
  scene.host.canvas_id=xdf_u32(data+16); scene.canvas_generation=xdf_u32(data+20);
  // Unit scale in paint_ops; the explicit offscreen density is independent of
  // the window, and may differ slightly on each axis due to ceil rounding.
  scene.device_scale=1;
  if(!draw_apply_frame(&scene,data,len,lease)) return 0;
  Bitmap bitmap(width,height,width*4,PixelFormat32bppPARGB,pixels);
  if(bitmap.GetLastStatus()!=Ok) return 0;
  Graphics g(&bitmap); g.SetSmoothingMode(SmoothingModeAntiAlias);
  g.Clear(gp(scene.display_bg));
  g.ScaleTransform((REAL)(width/logical_width),(REAL)(height/logical_height));
  paint_ops(&scene,g); g.Flush(FlushIntentionSync);
  return g.GetLastStatus()==Ok ? 1 : 0;
}

static int draw_take_frame(XuContentPlugin *p, const char *cmd) {
  const char *ticket = cmd + 13;
  if (!*ticket) return 0;
  uint64_t id = 0;
  for (const char *q = ticket; *q; ++q) {
    if (*q < '0' || *q > '9' || id > (UINT64_MAX - (unsigned)(*q - '0')) / 10u) return 0;
    id = id * 10u + (unsigned)(*q - '0');
  }
  unsigned len = 0;
  auto *lease = xu_ui_draw_acquire_for(id, p->host.canvas_id, p->canvas_generation);
  const void *data = xu_ui_frame_data(lease, &len);
  int ok = draw_apply_frame(p, data, len, lease);
  xu_ui_frame_release(lease);
  return ok;
}

static int draw_handle(XuContentPlugin *p, const char *cmd) {
  uint64_t request = 0;
  if (xu_text_input_marker(cmd, &request)) return draw_text_input_command(p, request);
  if (xu_request_marker(cmd, &request)) return show_prompt(p, request);
  if (!cmd) return 0;
  if (strncmp(cmd, "input_enabled\t", 14) == 0) {
    if (strcmp(cmd + 14, "0") == 0) { cancel_input(p); p->input_enabled = 0; }
    else { p->input_enabled = 1; p->pointer_inside = 0; }
    return 1;
  }
  if (strncmp(cmd, "cursor\t", 7) == 0) {
    if (cmd[7] < '0' || cmd[7] > '5' || cmd[8]) return 0;
    p->cursor = cmd[7] - '0';
    return 1;
  }
  if (strncmp(cmd, "__draw_frame\t", 13) == 0) return draw_take_frame(p, cmd);
  if (strncmp(cmd, "pan_enabled\t", 12) == 0) {
    p->pan_enabled = strcmp(cmd + 12, "0") != 0;
    if (!p->pan_enabled) {
      p->cam_x = 0;
      p->cam_y = 0;
    }
    if (p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE);
    return 1;
  }
  if (strcmp(cmd, "begin") == 0) {
    p->pending_logical = false;
    p->ops.clear();
    p->building = true;
    reset_pen(p);
    return 1;
  }
  if (strcmp(cmd, "present") == 0) {
    p->display_logical = p->pending_logical;
    p->display_ops = p->ops;
    p->display_bg = p->bg;
    p->display_label = p->label;
    p->building = false;
    if (p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE);
    return 1;
  }
  if (strcmp(cmd, "cancel") == 0) {
    p->pending_logical = p->display_logical;
    p->ops = p->display_ops;
    p->bg = p->display_bg;
    p->label = p->display_label;
    p->building = false;
    reset_pen(p);
    return 1;
  }
  if (strcmp(cmd, "draw_clear") == 0) {
    p->pending_logical = p->display_logical = false;
    p->ops.clear();
    p->label.clear();
    p->bg.r = p->bg.g = p->bg.b = 26;
    p->bg.a = 255;
    p->display_ops.clear();
    p->display_label.clear();
    p->display_bg = p->bg;
    p->building = false;
    reset_pen(p);
    if (p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE);
    return 1;
  }
  if (strcmp(cmd, "push") == 0) {
    if (p->pen_stack.size() >= 256) return 0;
    p->pen_stack.push_back({p->pen_fill, p->pen_stroke, p->pen_lw});
    Op o = blank_op();
    o.kind = OP_PUSH;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(cmd, "pop") == 0) {
    if (p->pen_stack.empty()) return 0;
    DrawPen pen = p->pen_stack.back();
    p->pen_stack.pop_back();
    p->pen_fill = pen.fill;
    p->pen_stroke = pen.stroke;
    p->pen_lw = pen.width;
    Op o = blank_op();
    o.kind = OP_POP;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(cmd, "origin") == 0) {
    Op o = blank_op();
    o.kind = OP_ORIGIN;
    p->ops.push_back(o);
    return 1;
  }
  std::string buffer(cmd);
  std::vector<char *> f;
  int n = split_tabs(buffer.data(), f);
  if (strcmp(f[0], "bgcolor") == 0 && n >= 2) {
    p->bg = parse_hex(f[1]);
    if (!p->bg.on) {
      p->bg.on = 1;
      p->bg.r = p->bg.g = p->bg.b = 26;
      p->bg.a = 255;
    }
    if (!p->building) { p->display_bg = p->bg; if (p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE); }
    return 1;
  }
  if (strcmp(f[0], "label") == 0 && n >= 2) {
    p->label = f[1];
    if (!p->building) { p->display_label = p->label; if (p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE); }
    return 1;
  }
  if (strcmp(f[0], "color") == 0 && n >= 2) {
    DrawColor c = parse_hex(f[1]);
    if (c.on) {
      p->pen_fill = c;
      p->pen_stroke = c;
    }
    return 1;
  }
  if (strcmp(f[0], "fill") == 0 && n >= 2) {
    DrawColor c = parse_hex(f[1]);
    if (c.on) p->pen_fill = c;
    return 1;
  }
  if (strcmp(f[0], "stroke") == 0 && n >= 2) {
    DrawColor c = parse_hex(f[1]);
    if (c.on) p->pen_stroke = c;
    return 1;
  }
  if (strcmp(f[0], "width") == 0 && n >= 2) {
    p->pen_lw = num(f[1], 1);
    return 1;
  }
  if (strcmp(f[0], "translate") == 0 && n >= 3) {
    Op o = blank_op();
    o.kind = OP_TRANSLATE;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "rotate") == 0 && n >= 2) {
    Op o = blank_op();
    o.kind = OP_ROTATE;
    o.a0 = num(f[1], 0);
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "scale") == 0 && n >= 3) {
    Op o = blank_op();
    o.kind = OP_SCALE;
    o.x = num(f[1], 100) / 100.0;
    o.y = num(f[2], 100) / 100.0;
    p->ops.push_back(o);
    return 1;
  }
  Op o = blank_op();
  if (strcmp(f[0], "clip_rect") == 0 && n == 5) {
    o.kind = OP_CLIP_RECT;
    o.x = num(f[1], 0); o.y = num(f[2], 0);
    o.w = num(f[3], 0); o.h = num(f[4], 0);
    if (o.w < 0 || o.h < 0) return 0;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "fill_rect") == 0 && n >= 6) {
    o.kind = OP_FILL_RECT;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.w = num(f[3], 0);
    o.h = num(f[4], 0);
    o.fill = parse_hex(f[5]);
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "stroke_rect") == 0 && n >= 6) {
    o.kind = OP_STROKE_RECT;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.w = num(f[3], 0);
    o.h = num(f[4], 0);
    o.stroke = parse_hex(f[5]);
    o.lw = n >= 7 ? num(f[6], 1) : 1;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "rect") == 0 && n >= 5) {
    o.kind = OP_FILL_RECT;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.w = num(f[3], 0);
    o.h = num(f[4], 0);
    o.fill = p->pen_fill;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "rect_line") == 0 && n >= 5) {
    o.kind = OP_STROKE_RECT;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.w = num(f[3], 0);
    o.h = num(f[4], 0);
    o.stroke = p->pen_stroke;
    o.lw = p->pen_lw;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "round_rect") == 0 && n >= 9) {
    o.kind = OP_ROUND;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.w = num(f[3], 0);
    o.h = num(f[4], 0);
    o.radius = num(f[5], 8);
    o.fill = parse_hex(f[6]);
    o.stroke = parse_hex(f[7]);
    o.lw = num(f[8], 1);
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "diamond") == 0 && n >= 8) {
    o.kind = OP_DIAMOND;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.w = num(f[3], 0);
    o.h = num(f[4], 0);
    o.fill = parse_hex(f[5]);
    o.stroke = parse_hex(f[6]);
    o.lw = num(f[7], 1);
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "line") == 0 && n >= 6) {
    o.kind = OP_LINE;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.x2 = num(f[3], 0);
    o.y2 = num(f[4], 0);
    o.stroke = parse_hex(f[5]);
    o.lw = n >= 7 ? num(f[6], 1) : 1;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "text") == 0 && n >= 6) {
    o.kind = OP_TEXT;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.size = num(f[3], 13);
    o.fill = parse_hex(f[4]);
    o.text = f[5];
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "circle_line") == 0 && n >= 4) {
    double r = num(f[3], 0);
    o.kind = OP_OVAL;
    o.x = num(f[1], 0) - r;
    o.y = num(f[2], 0) - r;
    o.w = r * 2;
    o.h = r * 2;
    o.stroke = p->pen_stroke;
    o.lw = p->pen_lw;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "circle") == 0 && n >= 4) {
    double r = num(f[3], 0);
    o.kind = OP_OVAL;
    o.x = num(f[1], 0) - r;
    o.y = num(f[2], 0) - r;
    o.w = r * 2;
    o.h = r * 2;
    if (n >= 7) {
      o.fill = parse_color_or_pen(&p->pen_fill, f[4]);
      o.stroke = parse_color_or_pen(&p->pen_stroke, f[5]);
      o.lw = parse_lw_or_pen(p->pen_lw, f[6]);
    } else {
      o.fill = p->pen_fill;
    }
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "ellipse_line") == 0 && n >= 5) {
    o.kind = OP_OVAL;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.w = num(f[3], 0);
    o.h = num(f[4], 0);
    o.stroke = p->pen_stroke;
    o.lw = p->pen_lw;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "ellipse") == 0 && n >= 5) {
    o.kind = OP_OVAL;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.w = num(f[3], 0);
    o.h = num(f[4], 0);
    if (n >= 8) {
      o.fill = parse_color_or_pen(&p->pen_fill, f[5]);
      o.stroke = parse_color_or_pen(&p->pen_stroke, f[6]);
      o.lw = parse_lw_or_pen(p->pen_lw, f[7]);
    } else {
      o.fill = p->pen_fill;
    }
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "triangle_line") == 0 && n >= 7) {
    o.kind = OP_TRI;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.x2 = num(f[3], 0);
    o.y2 = num(f[4], 0);
    o.x3 = num(f[5], 0);
    o.y3 = num(f[6], 0);
    o.stroke = p->pen_stroke;
    o.lw = p->pen_lw;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "triangle") == 0 && n >= 7) {
    o.kind = OP_TRI;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.x2 = num(f[3], 0);
    o.y2 = num(f[4], 0);
    o.x3 = num(f[5], 0);
    o.y3 = num(f[6], 0);
    if (n >= 10) {
      o.fill = parse_color_or_pen(&p->pen_fill, f[7]);
      o.stroke = parse_color_or_pen(&p->pen_stroke, f[8]);
      o.lw = parse_lw_or_pen(p->pen_lw, f[9]);
    } else {
      o.fill = p->pen_fill;
    }
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "poly") == 0 && n >= 6) {
    o.kind = OP_POLY;
    o.fill = parse_color_or_pen(&p->pen_fill, f[1]);
    o.stroke = parse_color_or_pen(&p->pen_stroke, f[2]);
    o.lw = parse_lw_or_pen(p->pen_lw, f[3]);
    for (int i = 4; i + 1 < n; i += 2) {
      o.pts.push_back(num(f[i], 0));
      o.pts.push_back(num(f[i + 1], 0));
    }
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "arc") == 0 && n >= 7) {
    o.kind = OP_ARC;
    o.x = num(f[1], 0);
    o.y = num(f[2], 0);
    o.radius = num(f[3], 0);
    o.a0 = num(f[4], 0);
    o.a1 = num(f[5], 0);
    o.stroke = parse_color_or_pen(&p->pen_stroke, f[6]);
    o.lw = n >= 8 ? parse_lw_or_pen(p->pen_lw, f[7]) : p->pen_lw;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(f[0], "prompt") == 0) {
    if (p->host.append_shell_event) xu_content_event(&p->host,"prompt\t");
    return 1;
  }
  return 0;
}

static void draw_poll(XuContentPlugin *p) {
  xu_ui_text_input_poll();
  draw_text_input_poll(p);
  xu_ui_request_poll();
  if (p->prompt && !xu_ui_request_alive(p->prompt->id)) finish_prompt(p->prompt, XU_REQUEST_CANCELLED);
}
static void draw_sync(XuContentPlugin *p) {
  if (!p->hwnd) return;
  RECT parent, current;
  GetClientRect(GetParent(p->hwnd), &parent); GetClientRect(p->hwnd, &current);
  if (parent.right != current.right || parent.bottom != current.bottom)
    MoveWindow(p->hwnd, 0, 0, parent.right, parent.bottom, TRUE);
  double scale = xu_ui_window_scale(p->hwnd);
  bool scale_changed = p->device_scale != scale;
  draw_metrics(p, parent.right, parent.bottom, scale);
  if (scale_changed) InvalidateRect(p->hwnd, NULL, FALSE);
}
static void draw_eval(XuContentPlugin *p, const char *js) {
  (void)p;
  (void)js;
}

static const XuContentVTable g_vt = {
    draw_create, draw_destroy, draw_install, draw_handle, draw_poll, draw_sync, draw_eval,
};

extern "C" const XuContentVTable *xu_draw_plugin_vtable(void) { return &g_vt; }
