// Xu #ui/draw content plugin (Windows GDI+).
// Exports xu_draw_plugin_vtable. Command protocol: see macos_draw.swift.

#include "xu_content_abi.h"

#include <windows.h>
#include <gdiplus.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>

using namespace Gdiplus;

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
  OP_SCALE
};

struct DrawColor {
  int on;
  BYTE r, g, b, a;
};

struct Op {
  int kind;
  double x, y, w, h, x2, y2, x3, y3, radius, a0, a1, lw, size;
  DrawColor fill, stroke;
  std::string text;
  std::vector<double> pts;
};

struct XuContentPlugin {
  XuContentHost host;
  HWND hwnd;
  std::vector<Op> ops;
  DrawColor bg;
  DrawColor pen_fill;
  DrawColor pen_stroke;
  double pen_lw;
  std::string label;
  int down;
  int dragging;
  int last_x;
  int last_y;
  double cam_x;
  double cam_y;
};

static XuContentPlugin *g_self = NULL;
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

static int split_tabs(char *s, char *out[], int max) {
  int n = 0;
  out[n++] = s;
  for (char *p = s; *p && n < max; p++) {
    if (*p == '\t') {
      *p = 0;
      out[n++] = p + 1;
    }
  }
  return n;
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
  p->host.append_shell_event(ev);
}

static void report_scroll(XuContentPlugin *p, int dx, int dy) {
  if (!p || !p->host.append_shell_event) return;
  char ev[64];
  snprintf(ev, sizeof(ev), "scroll\t%d\t%d", dx, dy);
  p->host.append_shell_event(ev);
}

static void report_drag(XuContentPlugin *p, int dx, int dy) {
  if (!p || !p->host.append_shell_event) return;
  char ev[64];
  snprintf(ev, sizeof(ev), "drag\t%d\t%d", dx, dy);
  p->host.append_shell_event(ev);
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

static void paint(XuContentPlugin *p, HDC hdc, int width, int height) {
  Graphics g(hdc);
  g.SetSmoothingMode(SmoothingModeAntiAlias);
  SolidBrush bg(Gdiplus::Color(255, p->bg.r, p->bg.g, p->bg.b));
  g.FillRectangle(&bg, 0, 0, width, height);
  if (p->ops.empty() && !p->label.empty()) {
    FontFamily ff(L"Segoe UI");
    Font font(&ff, 22, FontStyleBold, UnitPixel);
    SolidBrush white(Gdiplus::Color(255, 255, 255, 255));
    wchar_t wbuf[512];
    MultiByteToWideChar(CP_UTF8, 0, p->label.c_str(), -1, wbuf, 512);
    g.DrawString(wbuf, -1, &font, PointF(24, (REAL)height * 0.45f), &white);
    return;
  }
  std::vector<GraphicsState> stack;
  g.TranslateTransform(-(REAL)p->cam_x, -(REAL)p->cam_y);
  for (size_t i = 0; i < p->ops.size(); i++) {
    Op &o = p->ops[i];
    if (o.kind == OP_PUSH) {
      stack.push_back(g.Save());
    } else if (o.kind == OP_POP) {
      if (!stack.empty()) {
        g.Restore(stack.back());
        stack.pop_back();
      }
    } else if (o.kind == OP_ORIGIN) {
      g.ResetTransform();
    } else if (o.kind == OP_TRANSLATE) {
      g.TranslateTransform((REAL)o.x, (REAL)o.y);
    } else if (o.kind == OP_ROTATE) {
      g.RotateTransform((REAL)o.a0);
    } else if (o.kind == OP_SCALE) {
      g.ScaleTransform((REAL)o.x, (REAL)o.y);
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
      wchar_t wbuf[1024];
      MultiByteToWideChar(CP_UTF8, 0, o.text.c_str(), -1, wbuf, 1024);
      g.DrawString(wbuf, -1, &font, PointF((REAL)o.x, (REAL)o.y), &br);
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

static LRESULT CALLBACK wnd_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
  XuContentPlugin *p = (XuContentPlugin *)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
  if (msg == WM_LBUTTONDOWN && p) {
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
      p->cam_x -= (double)dx;
      p->cam_y -= (double)dy;
      report_drag(p, dx, dy);
      InvalidateRect(hwnd, NULL, FALSE);
    }
    return 0;
  }
  if (msg == WM_LBUTTONUP && p) {
    int x = (int)(short)LOWORD(lp);
    int y = (int)(short)HIWORD(lp);
    p->down = 0;
    ReleaseCapture();
    if (!p->dragging) report_click(p, x, y);
    p->dragging = 0;
    return 0;
  }
  if (msg == WM_MOUSEWHEEL && p) {
    int d = GET_WHEEL_DELTA_WPARAM(wp);
    int dy = -(d / 6);
    if (dy == 0) dy = d > 0 ? -8 : 8;
    p->cam_y -= (double)dy;
    report_scroll(p, 0, dy);
    InvalidateRect(hwnd, NULL, FALSE);
    return 0;
  }
  if (msg == WM_MOUSEHWHEEL && p) {
    int d = GET_WHEEL_DELTA_WPARAM(wp);
    int dx = d / 6;
    if (dx == 0) dx = d > 0 ? 8 : -8;
    p->cam_x -= (double)dx;
    report_scroll(p, dx, 0);
    InvalidateRect(hwnd, NULL, FALSE);
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
  wc.lpfnWndProc = wnd_proc;
  wc.hInstance = GetModuleHandleW(NULL);
  wc.hCursor = LoadCursor(NULL, IDC_ARROW);
  wc.lpszClassName = kClass;
  RegisterClassW(&wc);
  done = 1;
}

static void reset_pen(XuContentPlugin *p) {
  p->pen_fill = color_white();
  p->pen_stroke = color_white();
  p->pen_lw = 1;
}

static XuContentPlugin *draw_create(XuContentHost *host) {
  XuContentPlugin *p = new XuContentPlugin();
  if (host) p->host = *host;
  p->hwnd = NULL;
  p->bg.on = 1;
  p->bg.r = p->bg.g = p->bg.b = 26;
  p->bg.a = 255;
  reset_pen(p);
  g_self = p;
  return p;
}

static void draw_destroy(XuContentPlugin *p) {
  if (p->hwnd) DestroyWindow(p->hwnd);
  if (g_self == p) g_self = NULL;
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

static int draw_handle(XuContentPlugin *p, const char *cmd) {
  if (!cmd) return 0;
  if (strcmp(cmd, "begin") == 0) {
    p->ops.clear();
    reset_pen(p);
    return 1;
  }
  if (strcmp(cmd, "present") == 0) {
    if (p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE);
    return 1;
  }
  if (strcmp(cmd, "draw_clear") == 0) {
    p->ops.clear();
    p->label.clear();
    p->bg.r = p->bg.g = p->bg.b = 26;
    p->bg.a = 255;
    reset_pen(p);
    if (p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE);
    return 1;
  }
  if (strcmp(cmd, "push") == 0) {
    Op o = blank_op();
    o.kind = OP_PUSH;
    p->ops.push_back(o);
    return 1;
  }
  if (strcmp(cmd, "pop") == 0) {
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
  char buf[8192];
  snprintf(buf, sizeof(buf), "%s", cmd);
  char *f[64];
  int n = split_tabs(buf, f, 64);
  if (strcmp(f[0], "bgcolor") == 0 && n >= 2) {
    p->bg = parse_hex(f[1]);
    if (!p->bg.on) {
      p->bg.on = 1;
      p->bg.r = p->bg.g = p->bg.b = 26;
      p->bg.a = 255;
    }
    return 1;
  }
  if (strcmp(f[0], "label") == 0 && n >= 2) {
    p->label = f[1];
    if (p->ops.empty() && p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE);
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
    if (p->host.append_shell_event) p->host.append_shell_event("prompt\t");
    return 1;
  }
  return 0;
}

static void draw_poll(XuContentPlugin *p) { (void)p; }
static void draw_sync(XuContentPlugin *p) {
  if (p->hwnd) InvalidateRect(p->hwnd, NULL, FALSE);
}
static void draw_eval(XuContentPlugin *p, const char *js) {
  (void)p;
  (void)js;
}

static const XuContentVTable g_vt = {
    draw_create, draw_destroy, draw_install, draw_handle, draw_poll, draw_sync, draw_eval,
};

extern "C" const XuContentVTable *xu_draw_plugin_vtable(void) { return &g_vt; }
