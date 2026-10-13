// Xu #ui/draw content plugin (Linux GTK4 + Cairo).
// Exports xu_draw_plugin_vtable. Command protocol: see macos_draw.swift.

#include "xu_content_abi.h"

#include <gtk/gtk.h>
#include <cairo.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <vector>
#include <string>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

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

struct Color {
  int on;
  double r, g, b, a;
};

struct Op {
  int kind;
  double x, y, w, h, x2, y2, x3, y3, radius, a0, a1, lw, size;
  Color fill, stroke;
  std::string text;
  std::vector<double> pts;
};

struct XuContentPlugin {
  XuContentHost host;
  GtkWidget *area;
  std::vector<Op> ops;
  Color bg;
  Color pen_fill;
  Color pen_stroke;
  double pen_lw;
  std::string label;
  double last_ox;
  double last_oy;
  int panning;
  double cam_x;
  double cam_y;
};

static Color color_off(void) {
  Color c;
  c.on = 0;
  c.r = c.g = c.b = 0;
  c.a = 1;
  return c;
}

static Color color_white(void) {
  Color c;
  c.on = 1;
  c.r = c.g = c.b = 1;
  c.a = 1;
  return c;
}

static Color parse_hex(const char *hex) {
  Color c = color_off();
  if (!hex || !hex[0] || hex[0] == '-') return c;
  const char *h = hex;
  if (h[0] == '#') h++;
  unsigned n = 0;
  size_t len = strlen(h);
  if (len == 6) {
    if (sscanf(h, "%x", &n) != 1) return c;
    c.on = 1;
    c.r = ((n >> 16) & 0xff) / 255.0;
    c.g = ((n >> 8) & 0xff) / 255.0;
    c.b = (n & 0xff) / 255.0;
    c.a = 1;
    return c;
  }
  if (len == 8) {
    if (sscanf(h, "%x", &n) != 1) return c;
    c.on = 1;
    c.r = ((n >> 24) & 0xff) / 255.0;
    c.g = ((n >> 16) & 0xff) / 255.0;
    c.b = ((n >> 8) & 0xff) / 255.0;
    c.a = (n & 0xff) / 255.0;
    return c;
  }
  return c;
}

static Color parse_color_or_pen(const Color *pen, const char *s) {
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

static void cairo_color(cairo_t *cr, Color c) {
  cairo_set_source_rgba(cr, c.r, c.g, c.b, c.a);
}

static void fill_stroke(cairo_t *cr, Color fill, Color stroke, double lw) {
  if (fill.on) {
    cairo_color(cr, fill);
    if (stroke.on) cairo_fill_preserve(cr);
    else cairo_fill(cr);
  }
  if (stroke.on) {
    cairo_color(cr, stroke);
    cairo_set_line_width(cr, lw > 0 ? lw : 1);
    cairo_stroke(cr);
  } else if (!fill.on) {
    cairo_new_path(cr);
  }
}

static void diamond_path(cairo_t *cr, double x, double y, double w, double h) {
  cairo_move_to(cr, x + w * 0.5, y);
  cairo_line_to(cr, x + w, y + h * 0.5);
  cairo_line_to(cr, x + w * 0.5, y + h);
  cairo_line_to(cr, x, y + h * 0.5);
  cairo_close_path(cr);
}

static void round_path(cairo_t *cr, double x, double y, double w, double h, double r) {
  if (r < 0) r = 0;
  if (r * 2 > w) r = w * 0.5;
  if (r * 2 > h) r = h * 0.5;
  cairo_new_path(cr);
  cairo_arc(cr, x + w - r, y + r, r, -1.5708, 0);
  cairo_arc(cr, x + w - r, y + h - r, r, 0, 1.5708);
  cairo_arc(cr, x + r, y + h - r, r, 1.5708, 3.1416);
  cairo_arc(cr, x + r, y + r, r, 3.1416, 4.7124);
  cairo_close_path(cr);
}

static void on_draw(GtkDrawingArea *area, cairo_t *cr, int width, int height, gpointer data) {
  (void)area;
  XuContentPlugin *p = (XuContentPlugin *)data;
  cairo_set_source_rgb(cr, p->bg.r, p->bg.g, p->bg.b);
  cairo_paint(cr);
  if (p->ops.empty() && !p->label.empty()) {
    cairo_set_source_rgb(cr, 1, 1, 1);
    cairo_select_font_face(cr, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
    cairo_set_font_size(cr, 22);
    cairo_text_extents_t te;
    cairo_text_extents(cr, p->label.c_str(), &te);
    cairo_move_to(cr, (width - te.width) * 0.5 - te.x_bearing, (height + te.height) * 0.5);
    cairo_show_text(cr, p->label.c_str());
    return;
  }
  int depth = 0;
  cairo_translate(cr, -p->cam_x, -p->cam_y);
  for (size_t i = 0; i < p->ops.size(); i++) {
    Op &o = p->ops[i];
    if (o.kind == OP_PUSH) {
      cairo_save(cr);
      depth++;
    } else if (o.kind == OP_POP) {
      if (depth > 0) {
        cairo_restore(cr);
        depth--;
      }
    } else if (o.kind == OP_ORIGIN) {
      cairo_identity_matrix(cr);
    } else if (o.kind == OP_TRANSLATE) {
      cairo_translate(cr, o.x, o.y);
    } else if (o.kind == OP_ROTATE) {
      cairo_rotate(cr, o.a0 * M_PI / 180.0);
    } else if (o.kind == OP_SCALE) {
      cairo_scale(cr, o.x, o.y);
    } else if (o.kind == OP_FILL_RECT && o.fill.on) {
      cairo_color(cr, o.fill);
      cairo_rectangle(cr, o.x, o.y, o.w, o.h);
      cairo_fill(cr);
    } else if (o.kind == OP_STROKE_RECT && o.stroke.on) {
      cairo_color(cr, o.stroke);
      cairo_set_line_width(cr, o.lw);
      cairo_rectangle(cr, o.x, o.y, o.w, o.h);
      cairo_stroke(cr);
    } else if (o.kind == OP_ROUND) {
      round_path(cr, o.x, o.y, o.w, o.h, o.radius);
      fill_stroke(cr, o.fill, o.stroke, o.lw);
    } else if (o.kind == OP_DIAMOND) {
      diamond_path(cr, o.x, o.y, o.w, o.h);
      fill_stroke(cr, o.fill, o.stroke, o.lw);
    } else if (o.kind == OP_LINE && o.stroke.on) {
      cairo_color(cr, o.stroke);
      cairo_set_line_width(cr, o.lw);
      cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND);
      cairo_move_to(cr, o.x, o.y);
      cairo_line_to(cr, o.x2, o.y2);
      cairo_stroke(cr);
    } else if (o.kind == OP_TEXT && o.fill.on) {
      cairo_color(cr, o.fill);
      cairo_select_font_face(cr, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
      cairo_set_font_size(cr, o.size > 0 ? o.size : 13);
      cairo_move_to(cr, o.x, o.y + o.size);
      cairo_show_text(cr, o.text.c_str());
    } else if (o.kind == OP_OVAL) {
      cairo_save(cr);
      cairo_translate(cr, o.x + o.w * 0.5, o.y + o.h * 0.5);
      double sx = o.w * 0.5;
      double sy = o.h * 0.5;
      if (sx < 1e-6) sx = 1e-6;
      if (sy < 1e-6) sy = 1e-6;
      cairo_scale(cr, sx, sy);
      cairo_new_path(cr);
      cairo_arc(cr, 0, 0, 1, 0, 2 * M_PI);
      double slw = o.lw / ((sx + sy) * 0.5);
      if (o.fill.on) {
        cairo_color(cr, o.fill);
        if (o.stroke.on) cairo_fill_preserve(cr);
        else cairo_fill(cr);
      }
      if (o.stroke.on) {
        cairo_color(cr, o.stroke);
        cairo_set_line_width(cr, slw > 0 ? slw : 1);
        cairo_stroke(cr);
      }
      cairo_restore(cr);
    } else if (o.kind == OP_TRI) {
      cairo_move_to(cr, o.x, o.y);
      cairo_line_to(cr, o.x2, o.y2);
      cairo_line_to(cr, o.x3, o.y3);
      cairo_close_path(cr);
      fill_stroke(cr, o.fill, o.stroke, o.lw);
    } else if (o.kind == OP_POLY && o.pts.size() >= 4) {
      cairo_move_to(cr, o.pts[0], o.pts[1]);
      for (size_t k = 2; k + 1 < o.pts.size(); k += 2) {
        cairo_line_to(cr, o.pts[k], o.pts[k + 1]);
      }
      cairo_close_path(cr);
      fill_stroke(cr, o.fill, o.stroke, o.lw);
    } else if (o.kind == OP_ARC && o.stroke.on) {
      cairo_color(cr, o.stroke);
      cairo_set_line_width(cr, o.lw);
      cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND);
      cairo_new_path(cr);
      cairo_arc(cr, o.x, o.y, o.radius, o.a0 * M_PI / 180.0, o.a1 * M_PI / 180.0);
      cairo_stroke(cr);
    }
  }
  while (depth > 0) {
    cairo_restore(cr);
    depth--;
  }
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

static gboolean on_scroll(GtkEventControllerScroll *c, gdouble dx, gdouble dy, gpointer data) {
  (void)c;
  int sx = (int)dx;
  int sy = (int)dy;
  if (sx == 0 && dx != 0) sx = dx > 0 ? 16 : -16;
  if (sy == 0 && dy != 0) sy = dy > 0 ? 16 : -16;
  if (sx != 0 || sy != 0) {
    XuContentPlugin *p = (XuContentPlugin *)data;
    p->cam_x -= (double)sx;
    p->cam_y -= (double)sy;
    if (p->area) gtk_widget_queue_draw(p->area);
    report_scroll(p, sx, sy);
  }
  return TRUE;
}

static void on_drag_begin(GtkGestureDrag *g, gdouble x, gdouble y, gpointer data) {
  (void)g;
  (void)x;
  (void)y;
  XuContentPlugin *p = (XuContentPlugin *)data;
  p->last_ox = 0;
  p->last_oy = 0;
  p->panning = 0;
}

static void on_drag_update(GtkGestureDrag *g, gdouble ox, gdouble oy, gpointer data) {
  (void)g;
  XuContentPlugin *p = (XuContentPlugin *)data;
  int dx = (int)(ox - p->last_ox);
  int dy = (int)(oy - p->last_oy);
  p->last_ox = ox;
  p->last_oy = oy;
  if (dx != 0 || dy != 0) {
    p->panning = 1;
    p->cam_x -= (double)dx;
    p->cam_y -= (double)dy;
    if (p->area) gtk_widget_queue_draw(p->area);
    report_drag(p, dx, dy);
  }
}

static void on_drag_end(GtkGestureDrag *g, gdouble ox, gdouble oy, gpointer data) {
  XuContentPlugin *p = (XuContentPlugin *)data;
  if (p->panning) return;
  (void)ox;
  (void)oy;
  double sx = 0, sy = 0;
  if (gtk_gesture_drag_get_start_point(g, &sx, &sy)) {
    report_click(p, (int)sx, (int)sy);
  }
}

static void reset_pen(XuContentPlugin *p) {
  p->pen_fill = color_white();
  p->pen_stroke = color_white();
  p->pen_lw = 1;
}

static XuContentPlugin *draw_create(XuContentHost *host) {
  XuContentPlugin *p = new XuContentPlugin();
  if (host) p->host = *host;
  p->area = NULL;
  p->bg.on = 1;
  p->bg.r = p->bg.g = p->bg.b = 0.10;
  p->bg.a = 1;
  reset_pen(p);
  return p;
}

static void draw_destroy(XuContentPlugin *p) {
  delete p;
}

static void draw_install(XuContentPlugin *p) {
  GtkWidget *parent = (GtkWidget *)p->host.content_parent;
  if (!parent) return;
  p->area = gtk_drawing_area_new();
  gtk_widget_set_hexpand(p->area, TRUE);
  gtk_widget_set_vexpand(p->area, TRUE);
  gtk_drawing_area_set_draw_func(GTK_DRAWING_AREA(p->area), on_draw, p, NULL);
  GtkEventController *scroll = gtk_event_controller_scroll_new(GTK_EVENT_CONTROLLER_SCROLL_BOTH_AXES);
  g_signal_connect(scroll, "scroll", G_CALLBACK(on_scroll), p);
  gtk_widget_add_controller(p->area, scroll);
  GtkGesture *drag = gtk_gesture_drag_new();
  g_signal_connect(drag, "drag-begin", G_CALLBACK(on_drag_begin), p);
  g_signal_connect(drag, "drag-update", G_CALLBACK(on_drag_update), p);
  g_signal_connect(drag, "drag-end", G_CALLBACK(on_drag_end), p);
  gtk_widget_add_controller(p->area, GTK_EVENT_CONTROLLER(drag));
  gtk_box_append(GTK_BOX(parent), p->area);
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
    if (p->area) gtk_widget_queue_draw(p->area);
    return 1;
  }
  if (strcmp(cmd, "draw_clear") == 0) {
    p->ops.clear();
    p->label.clear();
    p->bg.r = p->bg.g = p->bg.b = 0.10;
    p->bg.a = 1;
    reset_pen(p);
    if (p->area) gtk_widget_queue_draw(p->area);
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
      p->bg.r = p->bg.g = p->bg.b = 0.10;
      p->bg.a = 1;
    }
    return 1;
  }
  if (strcmp(f[0], "label") == 0 && n >= 2) {
    p->label = f[1];
    if (p->ops.empty() && p->area) gtk_widget_queue_draw(p->area);
    return 1;
  }
  if (strcmp(f[0], "color") == 0 && n >= 2) {
    Color c = parse_hex(f[1]);
    if (c.on) {
      p->pen_fill = c;
      p->pen_stroke = c;
    }
    return 1;
  }
  if (strcmp(f[0], "fill") == 0 && n >= 2) {
    Color c = parse_hex(f[1]);
    if (c.on) p->pen_fill = c;
    return 1;
  }
  if (strcmp(f[0], "stroke") == 0 && n >= 2) {
    Color c = parse_hex(f[1]);
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
  if (p->area) gtk_widget_queue_draw(p->area);
}
static void draw_eval(XuContentPlugin *p, const char *js) {
  (void)p;
  (void)js;
}

static const XuContentVTable g_vt = {
    draw_create, draw_destroy, draw_install, draw_handle, draw_poll, draw_sync, draw_eval,
};

extern "C" const XuContentVTable *xu_draw_plugin_vtable(void) { return &g_vt; }
