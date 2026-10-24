#include "xu_ui_windows.h"
// Xu #ui/draw content plugin (Linux GTK4 + Cairo).
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
#include <algorithm>

#include <gtk/gtk.h>
#include <cairo.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <vector>
#include <string>
static void *compile_scene_native(const XuUiFrameLease *);
static void destroy_scene_native(void *);
static int surface_render_native(const XuUiFrameLease *,unsigned,unsigned,double,double,unsigned char *);
#include "linux_text.inc"
#include "linux_path.inc"

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
  OP_SCALE,
  OP_CLIP_RECT,
  OP_IMAGE,
  OP_TEXT_LAYOUT,
  OP_PATH,
  OP_DISPLAY_LIST
};

struct Color {
  int on;
  double r, g, b, a;
};

struct DrawImage {
  XuUiBitmap *bitmap;
  cairo_surface_t *surface;
  explicit DrawImage(XuUiBitmap *source) : bitmap(source) {
    unsigned width, height;
    auto *pixels = xu_ui_bitmap_pixels(source, &width, &height);
    xu_ui_bitmap_retain(bitmap);
    surface = cairo_image_surface_create_for_data(const_cast<unsigned char *>(pixels), CAIRO_FORMAT_ARGB32,
                                                   (int)width, (int)height, (int)width * 4);
  }
  ~DrawImage() { cairo_surface_destroy(surface); xu_ui_bitmap_release(bitmap); }
};

struct Op {
  int kind;
  double x, y, w, h, x2, y2, x3, y3, radius, a0, a1, lw, size;
  Color fill, stroke;
  std::string text;
  std::vector<double> pts;
  std::shared_ptr<DrawImage> image;
  std::shared_ptr<XuUiText> layout;
  std::shared_ptr<DrawPath> path;
  std::shared_ptr<XuUiDisplayList> list;
  unsigned image_flags = 0;
};

struct DrawPen {
  Color fill, stroke;
  double width;
};

struct DrawPrompt;
struct DrawTextInput;
struct XuContentPlugin {
  XuContentHost host;
  GtkWidget *area;
  std::vector<Op> ops;
  std::vector<Op> display_ops;
  std::unordered_map<XuUiBitmap *, std::weak_ptr<DrawImage>> images;
  Color display_bg;
  std::string display_label;
  bool building;
  Color bg;
  Color pen_fill;
  Color pen_stroke;
  double pen_lw;
  std::vector<DrawPen> pen_stack;
  std::string label;
  double last_ox;
  double last_oy;
  int panning;
  int drag_active;
  double cam_x;
  double cam_y;
  int pan_enabled;
  int input_enabled, cursor, pointer_inside;
  unsigned buttons;
  double input_x, input_y;
  std::vector<unsigned> keys;
  std::vector<GtkEventController *> controllers;
  unsigned canvas_generation;
  int metrics_width, metrics_height, metrics_scale;
  DrawPrompt *prompt = NULL;
  std::shared_ptr<DrawTextInput> text_input;
  uint64_t text_input_id = 0;
};

#include "linux_text_input.inc"

struct DrawPrompt {
  XuContentPlugin *owner;
  GtkWidget *dialog, *entry, *accept, *cancel;
  GtkEventController *keys;
  uint64_t id;
};
static void finish_prompt(DrawPrompt *prompt, unsigned status) {
  if (!prompt) return;
  std::string text = status == XU_REQUEST_COMPLETED ? gtk_editable_get_text(GTK_EDITABLE(prompt->entry)) : "";
  prompt->owner->prompt = NULL;
  g_signal_handlers_disconnect_by_data(prompt->dialog, prompt);
  g_signal_handlers_disconnect_by_data(prompt->accept, prompt);
  g_signal_handlers_disconnect_by_data(prompt->cancel, prompt);
  g_signal_handlers_disconnect_by_data(prompt->keys, prompt);
  xu_ui_request_complete(prompt->id, status, text.data(), (unsigned)text.size());
  gtk_window_destroy(GTK_WINDOW(prompt->dialog));
  g_object_unref(prompt->dialog);
  delete prompt;
}
static int show_prompt(XuContentPlugin *p, uint64_t id) {
  char *wire = xu_ui_request_take(id, p->host.canvas_id, p->canvas_generation);
  if (!wire) return 0;
  std::string title, seed;
  bool valid = xu_request_prompt_text(wire, &title, &seed); free(wire);
  if (!valid || !p->host.native_window || !GTK_IS_WINDOW(p->host.native_window)) {
    const char error[] = "prompt owner is unavailable";
    xu_ui_request_complete(id, XU_REQUEST_FAILED, error, sizeof(error) - 1); return 1;
  }
  if (p->prompt) finish_prompt(p->prompt, XU_REQUEST_CANCELLED);
  GtkWidget *dialog = gtk_window_new();
  g_object_ref_sink(dialog);
  gtk_window_set_title(GTK_WINDOW(dialog), title.empty() ? "Xu" : title.c_str());
  gtk_window_set_transient_for(GTK_WINDOW(dialog), GTK_WINDOW(p->host.native_window));
  gtk_window_set_modal(GTK_WINDOW(dialog), TRUE);
  gtk_window_set_resizable(GTK_WINDOW(dialog), FALSE);
  GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
  gtk_widget_set_margin_start(box, 16); gtk_widget_set_margin_end(box, 16);
  gtk_widget_set_margin_top(box, 16); gtk_widget_set_margin_bottom(box, 16);
  gtk_window_set_child(GTK_WINDOW(dialog), box);
  GtkWidget *entry = gtk_entry_new();
  gtk_entry_set_max_length(GTK_ENTRY(entry), XU_UI_REQUEST_MAX_TEXT);
  gtk_editable_set_text(GTK_EDITABLE(entry), seed.c_str());
  gtk_entry_set_activates_default(GTK_ENTRY(entry), TRUE);
  gtk_box_append(GTK_BOX(box), entry);
  GtkWidget *buttons = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
  gtk_widget_set_halign(buttons, GTK_ALIGN_END); gtk_box_append(GTK_BOX(box), buttons);
  GtkWidget *cancel = gtk_button_new_with_mnemonic("_Cancel"), *accept = gtk_button_new_with_mnemonic("_OK");
  gtk_box_append(GTK_BOX(buttons), cancel); gtk_box_append(GTK_BOX(buttons), accept);
  gtk_window_set_default_size(GTK_WINDOW(dialog), 360, -1);
  gtk_window_set_default_widget(GTK_WINDOW(dialog), accept);
  GtkEventController *keys = gtk_event_controller_key_new(); gtk_widget_add_controller(dialog, keys);
  auto *prompt = new DrawPrompt{p, dialog, entry, accept, cancel, keys, id}; p->prompt = prompt;
  g_signal_connect(accept, "clicked", G_CALLBACK(+[](GtkButton *, gpointer data) {
    finish_prompt((DrawPrompt *)data, XU_REQUEST_COMPLETED);
  }), prompt);
  g_signal_connect(cancel, "clicked", G_CALLBACK(+[](GtkButton *, gpointer data) {
    finish_prompt((DrawPrompt *)data, XU_REQUEST_CANCELLED);
  }), prompt);
  g_signal_connect(keys, "key-pressed", G_CALLBACK(+[](GtkEventControllerKey *, guint key, guint, GdkModifierType, gpointer data) -> gboolean {
    if (key != GDK_KEY_Escape) return FALSE;
    finish_prompt((DrawPrompt *)data, XU_REQUEST_CANCELLED); return TRUE;
  }), prompt);
  g_signal_connect(dialog, "close-request", G_CALLBACK(+[](GtkWindow *, gpointer data) -> gboolean {
    finish_prompt((DrawPrompt *)data, XU_REQUEST_CANCELLED); return TRUE;
  }), prompt);
  gtk_window_present(GTK_WINDOW(dialog)); gtk_widget_grab_focus(entry);
  return 1;
}

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

static void paint_ops(XuContentPlugin *p,cairo_t *cr) {
  cairo_save(cr);
  int depth = 0;
  cairo_translate(cr, -p->cam_x, -p->cam_y);
  cairo_matrix_t canvas_base;
  cairo_get_matrix(cr, &canvas_base);
  for (size_t i = 0; i < p->display_ops.size(); i++) {
    Op &o = p->display_ops[i];
    if (o.kind == OP_PUSH) {
      cairo_save(cr);
      depth++;
    } else if (o.kind == OP_POP) {
      if (depth > 0) {
        cairo_restore(cr);
        depth--;
      }
    } else if (o.kind == OP_ORIGIN) {
      cairo_set_matrix(cr, &canvas_base);
    } else if (o.kind == OP_TRANSLATE) {
      cairo_translate(cr, o.x, o.y);
    } else if (o.kind == OP_ROTATE) {
      cairo_rotate(cr, o.a0 * M_PI / 180.0);
    } else if (o.kind == OP_SCALE) {
      cairo_scale(cr, o.x, o.y);
    } else if (o.kind == OP_CLIP_RECT) {
      cairo_rectangle(cr, o.x, o.y, o.w, o.h);
      cairo_clip(cr);
    } else if(o.kind==OP_DISPLAY_LIST) {
      paint_ops((XuContentPlugin *)xu_ui_display_list_native(o.list.get()),cr);
    } else if(o.kind==OP_PATH) {
      cairo_save(cr); cairo_new_path(cr); cairo_color(cr,o.fill); cairo_append_path(cr,&o.path->native);
      unsigned flags=o.path->flags;
      if(flags&1) {
        cairo_set_dash(cr,NULL,0,0);cairo_set_line_width(cr,o.path->width);cairo_set_miter_limit(cr,o.path->miter);
        cairo_set_line_cap(cr,((flags>>2)&3)==1 ? CAIRO_LINE_CAP_ROUND : ((flags>>2)&3)==2 ? CAIRO_LINE_CAP_SQUARE : CAIRO_LINE_CAP_BUTT);
        cairo_set_line_join(cr,((flags>>4)&3)==1 ? CAIRO_LINE_JOIN_ROUND : ((flags>>4)&3)==2 ? CAIRO_LINE_JOIN_BEVEL : CAIRO_LINE_JOIN_MITER);
        cairo_stroke(cr);
      } else {cairo_set_fill_rule(cr,(flags&2) ? CAIRO_FILL_RULE_EVEN_ODD : CAIRO_FILL_RULE_WINDING);cairo_fill(cr);}
      cairo_restore(cr);
    } else if (o.kind == OP_TEXT_LAYOUT) {
      auto *layout = (DrawTextLayout *)xu_ui_text_native(o.layout.get());
      std::lock_guard<std::mutex> lock(layout->mutex);
      cairo_save(cr); cairo_color(cr, o.fill); cairo_move_to(cr, o.x, o.y);
      pango_cairo_show_layout(cr, layout->layout); cairo_restore(cr);
    } else if (o.kind == OP_IMAGE && o.w > 0 && o.h > 0 && (o.image_flags & 65535u)) {
      cairo_save(cr);
      cairo_rectangle(cr, o.x, o.y, o.w, o.h); cairo_clip(cr);
      cairo_translate(cr, o.x, o.y); cairo_scale(cr, o.w / o.x3, o.h / o.y3);
      cairo_set_source_surface(cr, o.image->surface, -o.x2, -o.y2);
      auto *pattern = cairo_get_source(cr);
      cairo_pattern_set_filter(pattern, (o.image_flags & 65536u) ? CAIRO_FILTER_BILINEAR : CAIRO_FILTER_NEAREST);
      cairo_pattern_set_extend(pattern, CAIRO_EXTEND_PAD);
      cairo_paint_with_alpha(cr, (o.image_flags & 65535u) / 65535.0);
      cairo_restore(cr);
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
  cairo_restore(cr);
}

static void on_draw(GtkDrawingArea *area, cairo_t *cr, int width, int height, gpointer data) {
  XuContentPlugin *p = (XuContentPlugin *)data;
  int scale = area ? gtk_widget_get_scale_factor(GTK_WIDGET(area)) : 1;
  if (width != p->metrics_width || height != p->metrics_height || scale != p->metrics_scale) {
    p->metrics_width = width; p->metrics_height = height; p->metrics_scale = scale;
    xu_ui_canvas_metrics(&p->host, width, height, (unsigned)width * scale, (unsigned)height * scale, scale, scale);
  }
  cairo_set_source_rgb(cr, p->display_bg.r, p->display_bg.g, p->display_bg.b);
  cairo_paint(cr);
  if (p->display_ops.empty() && !p->display_label.empty()) {
    cairo_set_source_rgb(cr, 1, 1, 1);
    cairo_select_font_face(cr, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_BOLD);
    cairo_set_font_size(cr, 22);
    cairo_text_extents_t te;
    cairo_text_extents(cr, p->display_label.c_str(), &te);
    cairo_move_to(cr, (width - te.width) * 0.5 - te.x_bearing, (height + te.height) * 0.5);
    cairo_show_text(cr, p->display_label.c_str());
    return;
  }
  paint_ops(p,cr);
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

static unsigned input_modifiers(GdkModifierType state) {
  return ((state & GDK_SHIFT_MASK) ? 1u : 0u) | ((state & GDK_CONTROL_MASK) ? 2u : 0u) |
         ((state & GDK_ALT_MASK) ? 4u : 0u) | ((state & (GDK_META_MASK | GDK_SUPER_MASK)) ? 8u : 0u);
}
static unsigned input_key(guint key) {
  key = gdk_keyval_to_upper(key);
  if ((key >= 'A' && key <= 'Z') || (key >= '0' && key <= '9') || key == ' ') return key;
  if (key >= GDK_KEY_F1 && key <= GDK_KEY_F12) return XUI_KEY_F1 + key - GDK_KEY_F1;
  switch (key) {
    case GDK_KEY_Escape: return XUI_KEY_ESCAPE; case GDK_KEY_Tab: case GDK_KEY_ISO_Left_Tab: return XUI_KEY_TAB;
    case GDK_KEY_Return: case GDK_KEY_KP_Enter: return XUI_KEY_ENTER; case GDK_KEY_BackSpace: return XUI_KEY_BACKSPACE;
    case GDK_KEY_Delete: return XUI_KEY_DELETE; case GDK_KEY_Left: return XUI_KEY_LEFT;
    case GDK_KEY_Right: return XUI_KEY_RIGHT; case GDK_KEY_Up: return XUI_KEY_UP_ARROW;
    case GDK_KEY_Down: return XUI_KEY_DOWN_ARROW; case GDK_KEY_Home: return XUI_KEY_HOME;
    case GDK_KEY_End: return XUI_KEY_END; case GDK_KEY_Page_Up: return XUI_KEY_PAGE_UP;
    case GDK_KEY_Page_Down: return XUI_KEY_PAGE_DOWN; case GDK_KEY_Insert: return XUI_KEY_INSERT;
    case GDK_KEY_Shift_L: case GDK_KEY_Shift_R: return 304;
    case GDK_KEY_Control_L: case GDK_KEY_Control_R: return 305;
    case GDK_KEY_Alt_L: case GDK_KEY_Alt_R: return 306;
    case GDK_KEY_Meta_L: case GDK_KEY_Meta_R: case GDK_KEY_Super_L: case GDK_KEY_Super_R: return 307;
    case GDK_KEY_Caps_Lock: return 308;
    default: return 0;
  }
}
static unsigned controller_modifiers(GtkEventController *controller) {
  return controller ? input_modifiers(gtk_event_controller_get_current_event_state(controller)) : 0;
}
static void raw_pointer(XuContentPlugin *p, unsigned kind, double x, double y,
                        double dx = 0, double dy = 0, unsigned button = 0,
                        unsigned clicks = 0, unsigned modifiers = 0) {
  if (p->input_enabled) xu_ui_input_emit(&p->host, kind, x, y, dx, dy, button,
                                        p->buttons, modifiers, 0, 0, 0, clicks);
}
static void cancel_input(XuContentPlugin *p) {
  p->buttons = 0; p->panning = 0; p->drag_active = 0; p->keys.clear();
  raw_pointer(p, XUI_POINTER_CANCEL, p->input_x, p->input_y);
}
static void input_enter(GtkEventControllerMotion *c, double x, double y, gpointer data) {
  auto *p = (XuContentPlugin *)data;
  p->input_x = x; p->input_y = y; p->pointer_inside = 1;
  raw_pointer(p, XUI_POINTER_ENTER, x, y, 0, 0, 0, 0, controller_modifiers(GTK_EVENT_CONTROLLER(c)));
}
static void input_motion(GtkEventControllerMotion *c, double x, double y, gpointer data) {
  auto *p = (XuContentPlugin *)data;
  if (!p->pointer_inside) input_enter(c, x, y, data);
  raw_pointer(p, XUI_POINTER_MOVE, x, y, x - p->input_x, y - p->input_y, 0, 0, controller_modifiers(GTK_EVENT_CONTROLLER(c)));
  p->input_x = x; p->input_y = y;
}
static void input_leave(GtkEventControllerMotion *c, gpointer data) {
  auto *p = (XuContentPlugin *)data; p->pointer_inside = 0;
  raw_pointer(p, XUI_POINTER_LEAVE, p->input_x, p->input_y, 0, 0, 0, 0, controller_modifiers(GTK_EVENT_CONTROLLER(c)));
}
static void input_pressed(GtkGestureClick *click, int count, double x, double y, gpointer data) {
  auto *p = (XuContentPlugin *)data;
  unsigned native = gtk_gesture_single_get_current_button(GTK_GESTURE_SINGLE(click));
  unsigned button = native == 1 ? 1u : native == 3 ? 2u : native == 2 ? 3u : 0u;
  if (!button) return;
  if (p->area) gtk_widget_grab_focus(p->area);
  p->buttons |= 1u << (button - 1);
  raw_pointer(p, XUI_POINTER_DOWN, x, y, 0, 0, button, (unsigned)count, controller_modifiers(GTK_EVENT_CONTROLLER(click)));
}
static void input_released(GtkGestureClick *click, int count, double x, double y, gpointer data) {
  auto *p = (XuContentPlugin *)data;
  unsigned native = gtk_gesture_single_get_current_button(GTK_GESTURE_SINGLE(click));
  unsigned button = native == 1 ? 1u : native == 3 ? 2u : native == 2 ? 3u : 0u;
  if (!button) return;
  p->buttons &= ~(1u << (button - 1));
  raw_pointer(p, XUI_POINTER_UP, x, y, 0, 0, button, (unsigned)count, controller_modifiers(GTK_EVENT_CONTROLLER(click)));
}
static gboolean input_key_pressed(GtkEventControllerKey *controller, guint key, guint scan, GdkModifierType state, gpointer data) {
  auto *p = (XuContentPlugin *)data;
  auto found = std::find(p->keys.begin(), p->keys.end(), scan);
  bool repeat = found != p->keys.end();
  if (!repeat) p->keys.push_back(scan);
  if (p->input_enabled) xu_ui_input_emit(&p->host, XUI_KEY_DOWN, 0, 0, 0, 0, 0, p->buttons,
                                        input_modifiers(state), input_key(key), scan, repeat);
  if (draw_text_input_key(p, controller, key, state, true)) return TRUE;
  return p->input_enabled ? TRUE : FALSE;
}
static void input_key_released(GtkEventControllerKey *controller, guint key, guint scan, GdkModifierType state, gpointer data) {
  auto *p = (XuContentPlugin *)data;
  p->keys.erase(std::remove(p->keys.begin(), p->keys.end(), scan), p->keys.end());
  if (p->input_enabled) xu_ui_input_emit(&p->host, XUI_KEY_UP, 0, 0, 0, 0, 0, p->buttons,
                                        input_modifiers(state), input_key(key), scan);
  draw_text_input_key(p, controller, key, state, false);
}
static void input_focus_enter(GtkEventControllerFocus *, gpointer data) { draw_text_input_focus((XuContentPlugin *)data, true); }
static void input_focus_leave(GtkEventControllerFocus *, gpointer data) {
  auto *p = (XuContentPlugin *)data;
  draw_text_input_blur(p); cancel_input(p);
}
static void input_cancel(GtkGesture *, GdkEventSequence *, gpointer data) { cancel_input((XuContentPlugin *)data); }

static gboolean on_scroll(GtkEventControllerScroll *c, gdouble dx, gdouble dy, gpointer data) {
  XuContentPlugin *input = (XuContentPlugin *)data;
  if (dx != 0 || dy != 0) {
    double unit = 20;
#if GTK_CHECK_VERSION(4, 8, 0)
    GdkEvent *event = c ? gtk_event_controller_get_current_event(GTK_EVENT_CONTROLLER(c)) : NULL;
    if (event && gdk_scroll_event_get_unit(event) == GDK_SCROLL_UNIT_SURFACE) unit = 1;
#endif
    raw_pointer(input, XUI_POINTER_SCROLL, input->input_x, input->input_y, dx * unit, dy * unit,
                0, 0, controller_modifiers(c ? GTK_EVENT_CONTROLLER(c) : NULL));
  }
  int sx = (int)dx;
  int sy = (int)dy;
  if (sx == 0 && dx != 0) sx = dx > 0 ? 16 : -16;
  if (sy == 0 && dy != 0) sy = dy > 0 ? 16 : -16;
  if (sx != 0 || sy != 0) {
    XuContentPlugin *p = (XuContentPlugin *)data;
    if (p->pan_enabled) {
      p->cam_x -= (double)sx;
      p->cam_y -= (double)sy;
      if (p->area) gtk_widget_queue_draw(p->area);
    }
    report_scroll(p, sx, sy);
  }
  return TRUE;
}

static void on_drag_begin(GtkGestureDrag *g, gdouble x, gdouble y, gpointer data) {
  (void)g;
  (void)x;
  (void)y;
  XuContentPlugin *p = (XuContentPlugin *)data;
  p->drag_active = 1;
  p->last_ox = 0;
  p->last_oy = 0;
  p->panning = 0;
}

static void on_drag_update(GtkGestureDrag *g, gdouble ox, gdouble oy, gpointer data) {
  (void)g;
  XuContentPlugin *p = (XuContentPlugin *)data;
  if (!p->drag_active) return;
  int dx = (int)(ox - p->last_ox);
  int dy = (int)(oy - p->last_oy);
  p->last_ox = ox;
  p->last_oy = oy;
  if (dx != 0 || dy != 0) {
    p->panning = 1;
    if (p->pan_enabled) {
      p->cam_x -= (double)dx;
      p->cam_y -= (double)dy;
      if (p->area) gtk_widget_queue_draw(p->area);
    }
    report_drag(p, dx, dy);
  }
}

static void on_drag_end(GtkGestureDrag *g, gdouble ox, gdouble oy, gpointer data) {
  XuContentPlugin *p = (XuContentPlugin *)data;
  if (!p->drag_active) return;
  p->drag_active = 0;
  if (p->panning) return;
  (void)ox;
  (void)oy;
  double sx = 0, sy = 0;
  if (gtk_gesture_drag_get_start_point(g, &sx, &sy)) {
    report_click(p, (int)sx, (int)sy);
  }
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
  p->metrics_width = p->metrics_height = -1;
  p->area = NULL;
  p->bg.on = 1;
  p->bg.r = p->bg.g = p->bg.b = 0.10;
  p->bg.a = 1;
  p->pan_enabled = 0;
  p->display_bg = p->bg;
  p->building = false;
  reset_pen(p);
  return p;
}

static void draw_destroy(XuContentPlugin *p) {
  if (!p) return;
  draw_text_input_detach(p);
  if (p->prompt) finish_prompt(p->prompt, XU_REQUEST_CANCELLED);
  cancel_input(p);
  xu_ui_canvas_close(p->host.canvas_id, p->canvas_generation);
  xu_ui_canvas_event(&p->host, false);
  if (p->area) {
    gtk_drawing_area_set_draw_func(GTK_DRAWING_AREA(p->area), NULL, NULL, NULL);
    for (auto *controller : p->controllers) {
      g_signal_handlers_disconnect_by_data(controller, p);
      gtk_widget_remove_controller(p->area, controller);
    }
    p->controllers.clear();
    GtkWidget *parent = gtk_widget_get_parent(p->area);
    if (parent && GTK_IS_BOX(parent)) gtk_box_remove(GTK_BOX(parent), p->area);
    g_object_unref(p->area);
    p->area = NULL;
  }
  delete p;
}

static void draw_install(XuContentPlugin *p) {
  if (p->area) return;
  GtkWidget *parent = (GtkWidget *)p->host.content_parent;
  if (!parent) return;
  p->area = gtk_drawing_area_new();
  g_object_ref_sink(p->area); // plugin owns a reference independently of its parent
  gtk_widget_set_focusable(p->area, TRUE);
  gtk_widget_set_hexpand(p->area, TRUE);
  gtk_widget_set_vexpand(p->area, TRUE);
  gtk_drawing_area_set_draw_func(GTK_DRAWING_AREA(p->area), on_draw, p, NULL);
  GtkEventController *scroll = gtk_event_controller_scroll_new(GTK_EVENT_CONTROLLER_SCROLL_BOTH_AXES);
  g_signal_connect(scroll, "scroll", G_CALLBACK(on_scroll), p);
  gtk_widget_add_controller(p->area, scroll);
  p->controllers.push_back(scroll);
  GtkGesture *drag = gtk_gesture_drag_new();
  g_signal_connect(drag, "drag-begin", G_CALLBACK(on_drag_begin), p);
  g_signal_connect(drag, "drag-update", G_CALLBACK(on_drag_update), p);
  g_signal_connect(drag, "drag-end", G_CALLBACK(on_drag_end), p);
  gtk_widget_add_controller(p->area, GTK_EVENT_CONTROLLER(drag));
  p->controllers.push_back(GTK_EVENT_CONTROLLER(drag));
  GtkEventController *motion = gtk_event_controller_motion_new();
  g_signal_connect(motion, "enter", G_CALLBACK(input_enter), p);
  g_signal_connect(motion, "motion", G_CALLBACK(input_motion), p);
  g_signal_connect(motion, "leave", G_CALLBACK(input_leave), p);
  gtk_widget_add_controller(p->area, motion);
  p->controllers.push_back(motion);
  GtkGesture *click = gtk_gesture_click_new();
  gtk_gesture_single_set_button(GTK_GESTURE_SINGLE(click), 0);
  g_signal_connect(click, "pressed", G_CALLBACK(input_pressed), p);
  g_signal_connect(click, "released", G_CALLBACK(input_released), p);
  g_signal_connect(click, "cancel", G_CALLBACK(input_cancel), p);
  gtk_widget_add_controller(p->area, GTK_EVENT_CONTROLLER(click));
  p->controllers.push_back(GTK_EVENT_CONTROLLER(click));
  gtk_gesture_group(drag, click);
  GtkEventController *keys = gtk_event_controller_key_new();
  g_signal_connect(keys, "key-pressed", G_CALLBACK(input_key_pressed), p);
  g_signal_connect(keys, "key-released", G_CALLBACK(input_key_released), p);
  gtk_widget_add_controller(p->area, keys);
  p->controllers.push_back(keys);
  GtkEventController *focus = gtk_event_controller_focus_new();
  g_signal_connect(focus, "enter", G_CALLBACK(input_focus_enter), p);
  g_signal_connect(focus, "leave", G_CALLBACK(input_focus_leave), p);
  gtk_widget_add_controller(p->area, focus);
  p->controllers.push_back(focus);
  gtk_box_append(GTK_BOX(parent), p->area);
  xu_ui_canvas_event(&p->host, true);
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


static Color frame_color(unsigned rgba) {
  Color color = {};
  color.on = 1;
  color.r = ((rgba >> 24) & 255) / 255.0;
  color.g = ((rgba >> 16) & 255) / 255.0;
  color.b = ((rgba >> 8) & 255) / 255.0;
  color.a = (rgba & 255) / 255.0;
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
  Color bg = p->display_bg, fill = color_white(), stroke = color_white();
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
          if (cairo_surface_status(o.image->surface) != CAIRO_STATUS_SUCCESS) return 0;
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
        o.path=std::make_shared<DrawPath>(payload);o.kind=OP_PATH;o.fill=frame_color(c.rgba);break;
      }
      default: return 0;
    }
    next.push_back(std::move(o));
  }
  p->display_ops.swap(next);
  p->display_bg = p->bg = bg;
  p->display_label.clear(); p->label.clear();
  p->ops.clear(); p->building = false;
  reset_pen(p);
  if (p->area) gtk_widget_queue_draw(p->area);
  return 1;
  } catch(...) { return 0; }
}

static void *compile_scene_native(const XuUiFrameLease *lease) {
  unsigned len=0;auto *data=(const unsigned char *)xu_ui_frame_data(lease,&len);if(!data)return NULL;
  std::unique_ptr<XuContentPlugin> scene(new(std::nothrow) XuContentPlugin{});if(!scene)return NULL;
  scene->host.canvas_id=xdf_u32(data+16);scene->canvas_generation=xdf_u32(data+20);
  if(!draw_apply_frame(scene.get(),data,len,lease))return NULL;return scene.release();
}
static void destroy_scene_native(void *scene) {delete (XuContentPlugin *)scene;}

static int surface_render_native(const XuUiFrameLease *lease,unsigned width,unsigned height,double logical_width,
                                 double logical_height,unsigned char *pixels) {
  unsigned len=0; auto *data=(const unsigned char *)xu_ui_frame_data(lease,&len);
  if(!data || !pixels) return 0;
  XuContentPlugin scene{};
  scene.host.canvas_id=xdf_u32(data+16); scene.canvas_generation=xdf_u32(data+20);
  if(!draw_apply_frame(&scene,data,len,lease)) return 0;
  auto *surface=cairo_image_surface_create_for_data(pixels,CAIRO_FORMAT_ARGB32,width,height,width*4);
  auto *cr=cairo_create(surface);
  cairo_scale(cr,width/logical_width,height/logical_height);
  cairo_color(cr,scene.display_bg); cairo_paint(cr);
  paint_ops(&scene,cr);
  cairo_surface_flush(surface);
  bool ok=cairo_status(cr)==CAIRO_STATUS_SUCCESS && cairo_surface_status(surface)==CAIRO_STATUS_SUCCESS;
  cairo_destroy(cr); cairo_surface_destroy(surface);
  return ok ? 1 : 0;
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
  if (!cmd) return 0;
  uint64_t request = 0;
  if (xu_text_input_marker(cmd, &request)) return draw_text_input_command(p, request);
  if (xu_request_marker(cmd, &request)) return show_prompt(p, request);
  if (strncmp(cmd, "input_enabled\t", 14) == 0) {
    if (strcmp(cmd + 14, "0") == 0) { cancel_input(p); p->input_enabled = 0; }
    else { p->input_enabled = 1; p->pointer_inside = 0; }
    return 1;
  }
  if (strcmp(cmd, "motion_preferences") == 0) {
    gboolean animations = TRUE;
    GtkSettings *settings = p->area ? gtk_widget_get_settings(p->area) : gtk_settings_get_default();
    if (settings) g_object_get(settings, "gtk-enable-animations", &animations, NULL);
    char event[128];
    snprintf(event, sizeof(event), "canvas_preferences\t%u\t%u\t%u\t%d", p->host.window_id, p->host.canvas_id, p->canvas_generation, animations ? 0 : 1);
    xu_content_event(&p->host, event);
    return 1;
  }
  if (strncmp(cmd, "cursor\t", 7) == 0) {
    if (cmd[7] < '0' || cmd[7] > '5' || cmd[8]) return 0;
    const char *cursors[] = {"default", "text", "crosshair", "pointer", "ew-resize", "ns-resize"};
    p->cursor = cmd[7] - '0';
    if (p->area) gtk_widget_set_cursor_from_name(p->area, cursors[p->cursor]);
    return 1;
  }
  if (strncmp(cmd, "__draw_frame\t", 13) == 0) return draw_take_frame(p, cmd);
  if (strncmp(cmd, "pan_enabled\t", 12) == 0) {
    p->pan_enabled = strcmp(cmd + 12, "0") != 0;
    if (!p->pan_enabled) p->cam_x = p->cam_y = 0;
    if (p->area) gtk_widget_queue_draw(p->area);
    return 1;
  }
  if (strcmp(cmd, "begin") == 0) {
    p->ops.clear();
    p->building = true;
    reset_pen(p);
    return 1;
  }
  if (strcmp(cmd, "present") == 0) {
    p->display_ops = p->ops;
    p->display_bg = p->bg;
    p->display_label = p->label;
    p->building = false;
    if (p->area) gtk_widget_queue_draw(p->area);
    return 1;
  }
  if (strcmp(cmd, "cancel") == 0) {
    p->ops = p->display_ops;
    p->bg = p->display_bg;
    p->label = p->display_label;
    p->building = false;
    reset_pen(p);
    return 1;
  }
  if (strcmp(cmd, "draw_clear") == 0) {
    p->ops.clear();
    p->label.clear();
    p->bg.r = p->bg.g = p->bg.b = 0.10;
    p->bg.a = 1;
    p->display_ops.clear();
    p->display_label.clear();
    p->display_bg = p->bg;
    p->building = false;
    reset_pen(p);
    if (p->area) gtk_widget_queue_draw(p->area);
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
      p->bg.r = p->bg.g = p->bg.b = 0.10;
      p->bg.a = 1;
    }
    if (!p->building) { p->display_bg = p->bg; if (p->area) gtk_widget_queue_draw(p->area); }
    return 1;
  }
  if (strcmp(f[0], "label") == 0 && n >= 2) {
    p->label = f[1];
    if (!p->building) { p->display_label = p->label; if (p->area) gtk_widget_queue_draw(p->area); }
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
static void draw_sync(XuContentPlugin *p) { (void)p; }
static void draw_eval(XuContentPlugin *p, const char *js) {
  (void)p;
  (void)js;
}

static const XuContentVTable g_vt = {
    draw_create, draw_destroy, draw_install, draw_handle, draw_poll, draw_sync, draw_eval,
};

extern "C" const XuContentVTable *xu_draw_plugin_vtable(void) { return &g_vt; }
