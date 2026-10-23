// Xu UI Linux shell host (GTK4) — shell.* aligned with macOS host TMP protocol.
// Needs GTK ≥ 4.10 (GtkFileDialog / GtkAlertDialog).

#include <gtk/gtk.h>
#include <gdk/gdk.h>
#ifdef GDK_WINDOWING_X11
#include <gdk/x11/gdkx.h>
#include <X11/Xlib.h>
/* Xlib macros collide with GTK/Cairo identifiers. */
#ifdef None
#undef None
#endif
#ifdef Status
#undef Status
#endif
#ifdef Always
#undef Always
#endif
#ifdef Bool
#undef Bool
#endif
#endif
#include <cairo.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "xu_content_abi.h"
#include "xu_pack_assets.h"
#include "xu_ui_mem.h"
#include "xu_ui_commands.h"
#include "xu_ui_windows.h"
#include "xu_ui_requests.h"
#include "xu_draw_frame.h"
#include "linux_clipboard.inc"
#include "linux_files.inc"

extern "C" {
const XuContentVTable *xu_webview_plugin_vtable(void) __attribute__((weak));
const XuContentVTable *xu_draw_plugin_vtable(void) __attribute__((weak));
}

static char g_tmp[1024];
static unsigned g_root_generation=0;
static GtkWindow *g_win = NULL;
static GtkApplication *g_app = NULL;
static GtkWidget *g_area = NULL;
static GtkWidget *g_content_box = NULL;
static gboolean g_frameless = FALSE;
static gboolean g_transparent = FALSE;
static gboolean g_floating = FALSE;
static gboolean g_close_guard = FALSE;
static gboolean g_close_pending = FALSE;
static gboolean g_hidden = FALSE;
static gboolean g_resizable = TRUE;
static int g_min_w = 0, g_min_h = 0;
static guint g_poll_id = 0;
static GdkPixbuf *g_mask = NULL;
static char g_last_title[512];
static char g_last_size[64];
static char g_app_icon_sig[520];
static char g_menu_sig[512];
static char g_tray_sig[512];
static char g_menu_ids[32][64];
static char g_tray_ids[32][64];
static char g_tray_labels[32][256];
static int g_menu_n = 0;
static int g_tray_n = 0;
static GMenu *g_menubar_model = NULL;
static guint g_sni_reg_id = 0;
static gchar *g_sni_bus_name = NULL;
static GDBusConnection *g_sni_conn = NULL;
static GtkWidget *g_tray_popover = NULL;
static GdkPixbuf *g_tray_pixbuf = NULL;
static XuContentPlugin *g_content = NULL;
static const XuContentVTable *g_content_vt = NULL;
static XuContentHost g_content_host;

static void apply_app_icon(void);
static void show_desktop_notify(void);
static void menu_install_or_update(void);
static void tray_install_or_update(void);
static void native_menu_close(GtkWindow *);
static void handle_shell_cmd(const char *s);
static void drain_title_size(void);

static void write_tmp(const char *name, const char *body) {
  // Pack/oneexe: prefer in-process mailbox (no /tmp/xu_ui_* dir).
  xu_ui_mem_set(name, body ? body : "");
  if (!g_tmp[0]) return;
  char path[1200];
  snprintf(path, sizeof(path), "%s/%s", g_tmp, name);
  FILE *f = fopen(path, "w");
  if (!f) return;
  fputs(body ? body : "", f);
  fclose(f);
}

static void append_shell_event(const char *payload) {
  xu_ui_window_event(1,(payload && strcmp(payload,"ready") && strcmp(payload,"exit"))?g_root_generation:0,payload?payload:"");
  if (!g_tmp[0]) return;
  char path[1200];
  snprintf(path, sizeof(path), "%s/xu_ui_shell_event.txt", g_tmp);
  FILE *f = fopen(path, "a");
  if (!f) return;
  fprintf(f, "%s\n", payload);
  fclose(f);
}

static void read_trim_file(const char *name, char *out, size_t n) {
  out[0] = 0;
  if (xu_ui_mem_get(name, out, (unsigned)n) >= 0) {
    size_t L = strlen(out);
    while (L > 0 && (out[L - 1] == '\n' || out[L - 1] == '\r' || out[L - 1] == ' ')) {
      out[--L] = 0;
    }
    return;
  }
  if (!g_tmp[0]) return;
  char path[1200];
  snprintf(path, sizeof(path), "%s/%s", g_tmp, name);
  FILE *f = fopen(path, "r");
  if (!f) return;
  if (!fgets(out, (int)n, f)) {
    fclose(f);
    return;
  }
  fclose(f);
  size_t L = strlen(out);
  while (L > 0 && (out[L - 1] == '\n' || out[L - 1] == '\r' || out[L - 1] == ' ')) {
    out[--L] = 0;
  }
}

static void read_file_raw(const char *name, char *out, size_t n) {
  out[0] = 0;
  if (xu_ui_mem_get(name, out, (unsigned)n) >= 0) return;
  if (!g_tmp[0]) return;
  char path[1200];
  snprintf(path, sizeof(path), "%s/%s", g_tmp, name);
  FILE *f = fopen(path, "r");
  if (!f) return;
  size_t got = fread(out, 1, n - 1, f);
  fclose(f);
  out[got] = 0;
}

static void apply_frameless(gboolean on) {
  g_frameless = on;
  if (g_win) gtk_window_set_decorated(g_win, !on);
}

static void apply_transparent(gboolean on) {
  g_transparent = on;
  if (!g_win) return;
  GtkCssProvider *prov = gtk_css_provider_new();
  const char *css = on
    ? "window, drawingarea { background-color: rgba(0,0,0,0); }"
    : "window { background-color: @theme_bg_color; }";
#if GTK_CHECK_VERSION(4, 12, 0)
  gtk_css_provider_load_from_string(prov, css);
#else
  gtk_css_provider_load_from_data(prov, css, -1);
#endif
  gtk_style_context_add_provider_for_display(
    gdk_display_get_default(), GTK_STYLE_PROVIDER(prov),
    GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
  g_object_unref(prov);
}

static void clear_input_region(void) {
  if (!g_win) return;
  GtkNative *native = gtk_widget_get_native(GTK_WIDGET(g_win));
  if (!native) return;
  GdkSurface *surface = gtk_native_get_surface(native);
  if (!surface) return;
  gdk_surface_set_input_region(surface, NULL);
}

static void rebuild_input_region(void) {
  if (!g_win || !g_mask) {
    clear_input_region();
    return;
  }
  GtkNative *native = gtk_widget_get_native(GTK_WIDGET(g_win));
  if (!native) return;
  GdkSurface *surface = gtk_native_get_surface(native);
  if (!surface) return;
  int pw = gdk_pixbuf_get_width(g_mask);
  int ph = gdk_pixbuf_get_height(g_mask);
  int ww = gtk_widget_get_width(GTK_WIDGET(g_win));
  int wh = gtk_widget_get_height(GTK_WIDGET(g_win));
  if (pw <= 0 || ph <= 0 || ww <= 0 || wh <= 0) return;
  if (!gdk_pixbuf_get_has_alpha(g_mask)) {
    clear_input_region();
    return;
  }
  const guchar *pixels = gdk_pixbuf_get_pixels(g_mask);
  int rowstride = gdk_pixbuf_get_rowstride(g_mask);
  int n_ch = gdk_pixbuf_get_n_channels(g_mask);
  cairo_region_t *region = cairo_region_create();
  for (int y = 0; y < ph; y++) {
    int x = 0;
    int wy = (y * wh) / ph;
    int whgt = ((y + 1) * wh) / ph - wy;
    if (whgt < 1) whgt = 1;
    while (x < pw) {
      while (x < pw && pixels[y * rowstride + x * n_ch + (n_ch - 1)] < 20) x++;
      int x0 = x;
      while (x < pw && pixels[y * rowstride + x * n_ch + (n_ch - 1)] >= 20) x++;
      if (x > x0) {
        int wx0 = (x0 * ww) / pw;
        int wx1 = (x * ww) / pw;
        if (wx1 <= wx0) wx1 = wx0 + 1;
        cairo_rectangle_int_t r = {wx0, wy, wx1 - wx0, whgt};
        cairo_region_union_rectangle(region, &r);
      }
    }
  }
  gdk_surface_set_input_region(surface, region);
  cairo_region_destroy(region);
}

static void on_draw(GtkDrawingArea *area, cairo_t *cr, int width, int height, gpointer data) {
  (void)area;
  (void)data;
  if (!g_mask) {
    if (!g_transparent) {
      cairo_set_source_rgb(cr, 0.92, 0.92, 0.94);
      cairo_paint(cr);
    }
    return;
  }
  int pw = gdk_pixbuf_get_width(g_mask);
  int ph = gdk_pixbuf_get_height(g_mask);
  if (pw <= 0 || ph <= 0) return;
  cairo_save(cr);
  cairo_scale(cr, (double)width / (double)pw, (double)height / (double)ph);
  gdk_cairo_set_source_pixbuf(cr, g_mask, 0, 0);
  cairo_paint(cr);
  cairo_restore(cr);
}

static GdkPixbuf *pixbuf_from_pack(const char *path) {
  const unsigned char *p = NULL;
  unsigned n = 0;
  GInputStream *s;
  GError *err = NULL;
  GdkPixbuf *pb;
  if (!xu_pack_file_for_path(path, &p, &n) || !p || !n) return NULL;
  s = g_memory_input_stream_new_from_data(p, (gssize)n, NULL);
  pb = gdk_pixbuf_new_from_stream(s, NULL, &err);
  g_object_unref(s);
  if (err) g_error_free(err);
  return pb;
}

static GdkPixbuf *pixbuf_from_pack_icon(void) {
  const unsigned char *p = NULL;
  unsigned n = 0;
  if (!xu_pack_icon(&p, &n) || !p || !n) return NULL;
  GInputStream *s = g_memory_input_stream_new_from_data(p, (gssize)n, NULL);
  GError *err = NULL;
  GdkPixbuf *pb = gdk_pixbuf_new_from_stream(s, NULL, &err);
  g_object_unref(s);
  if (err) g_error_free(err);
  return pb;
}

static GdkPixbuf *load_app_icon_pixbuf(const char *path_file) {
  if (path_file && path_file[0]) {
    GError *err = NULL;
    GdkPixbuf *pb = gdk_pixbuf_new_from_file(path_file, &err);
    if (!pb) {
      if (err) {
        g_error_free(err);
        err = NULL;
      }
      pb = pixbuf_from_pack(path_file);
    }
    if (pb) return pb;
  }
  GdkPixbuf *pb = pixbuf_from_pack_icon();
  if (pb) return pb;
  pb = pixbuf_from_pack("brand/xu_app_icon.png");
  if (pb) return pb;
  return pixbuf_from_pack("brand/xu_app_logo.png");
}

/* GTK4: custom window icon via GdkToplevel icon list (Wayland/X11). */
static void apply_window_icon_pixbuf(GdkPixbuf *pb) {
  if (!g_win || !pb) return;
  GtkNative *native = gtk_widget_get_native(GTK_WIDGET(g_win));
  if (!native) return;
  GdkSurface *surface = gtk_native_get_surface(native);
  if (!surface || !GDK_IS_TOPLEVEL(surface)) return;
  GdkTexture *tex = gdk_texture_new_for_pixbuf(pb);
  if (!tex) return;
  GList *list = g_list_append(NULL, tex);
  gdk_toplevel_set_icon_list(GDK_TOPLEVEL(surface), list);
  g_list_free_full(list, g_object_unref);
}

static void apply_app_icon(void) {
  if (!g_win) return;
  char path_file[1024];
  read_trim_file("xu_ui_app_icon.txt", path_file, sizeof(path_file));
  char sig[520];
  snprintf(sig, sizeof(sig), "%s", path_file);
  if (g_app_icon_sig[0] && strcmp(sig, g_app_icon_sig) == 0) return;

  GdkPixbuf *pb = load_app_icon_pixbuf(path_file);
  if (!pb) return;

  GtkNative *native = gtk_widget_get_native(GTK_WIDGET(g_win));
  GdkSurface *surface = native ? gtk_native_get_surface(native) : NULL;
  if (!surface || !GDK_IS_TOPLEVEL(surface)) {
    g_object_unref(pb);
    return; // retry after map / next poll
  }
  apply_window_icon_pixbuf(pb);
  g_object_unref(pb);
  snprintf(g_app_icon_sig, sizeof(g_app_icon_sig), "%s", sig);
}

static void apply_mask(const char *path) {
  if (!path || !path[0]) return;
  GError *err = NULL;
  GdkPixbuf *pb = gdk_pixbuf_new_from_file(path, &err);
  if (!pb) {
    if (err) {
      g_error_free(err);
      err = NULL;
    }
    pb = pixbuf_from_pack(path);
  }
  if (!pb) {
    append_shell_event("mask_failed");
    return;
  }
  if (g_mask) g_object_unref(g_mask);
  g_mask = pb;
  if (!g_frameless) apply_frameless(TRUE);
  if (!g_transparent) apply_transparent(TRUE);
  if (g_area) gtk_widget_queue_draw(g_area);
  rebuild_input_region();
}

static void clear_mask(void) {
  if (g_mask) {
    g_object_unref(g_mask);
    g_mask = NULL;
  }
  clear_input_region();
  if (g_area) gtk_widget_queue_draw(g_area);
}

static gboolean g_quitting = FALSE;
static bool g_root_closed=false;

static void do_quit(void) {
  if (g_quitting) return;
  if(!g_root_closed){
    g_root_closed=true;native_menu_close(g_win);
    if(g_content && g_content_vt && g_content_vt->destroy)g_content_vt->destroy(g_content);
    g_content=NULL;
    unsigned meta[6];if(xu_ui_window_info(1,0,meta,NULL,0))xu_ui_window_closed(1,meta[1]);
    append_shell_event("closed");if(g_win)gtk_widget_set_visible(GTK_WIDGET(g_win),FALSE);
  }
  desktop_files_poll();
  // Keep the main context running until cancelled file-dialog callbacks release
  // their GObjects. The hidden root keeps GtkApplication alive during this drain.
  if(xu_ui_window_count() || !desktop_files_idle())return;
  g_quitting=TRUE;xu_ui_windows_shutdown();xu_ui_emit_close();
  desktop_clipboard_poll();
  desktop_files_poll();
  if(g_poll_id){g_source_remove(g_poll_id);g_poll_id=0;}
  xu_ui_host_set_kick(NULL);
  if(g_win){gtk_window_destroy(g_win);g_win=NULL;g_content_box=NULL;g_area=NULL;}
  append_shell_event("exit");if(g_app)g_application_quit(G_APPLICATION(g_app));
}

static void try_move_window(int x, int y) {
#ifdef GDK_WINDOWING_X11
  if (!g_win) return;
  GtkNative *nat = gtk_widget_get_native(GTK_WIDGET(g_win));
  if (!nat) return;
  GdkSurface *surf = gtk_native_get_surface(nat);
  if (!surf || !GDK_IS_X11_SURFACE(surf)) return;
  Display *dpy = gdk_x11_display_get_xdisplay(gdk_surface_get_display(surf));
  Window xid = gdk_x11_surface_get_xid(surf);
  if (!dpy || !xid) return;
  XMoveWindow(dpy, xid, x, y);
  XFlush(dpy);
#else
  (void)x;
  (void)y;
#endif
}

static void try_urgency_hint(gboolean on) {
#ifdef GDK_WINDOWING_X11
  if (!g_win) return;
  GtkNative *nat = gtk_widget_get_native(GTK_WIDGET(g_win));
  if (!nat) return;
  GdkSurface *surf = gtk_native_get_surface(nat);
  if (surf && GDK_IS_X11_SURFACE(surf))
    gdk_x11_surface_set_urgency_hint(surf, on);
#else
  (void)on;
#endif
  if (on && g_win) gtk_window_present(g_win);
}

static void write_bounds(void) {
  int w = gtk_widget_get_width(GTK_WIDGET(g_win));
  int h = gtk_widget_get_height(GTK_WIDGET(g_win));
  char line[128];
  snprintf(line, sizeof(line), "0 0 %d %d", w, h);
  write_tmp("xu_ui_bounds.txt", line);
}

static void write_state(void) {
  gboolean zoomed = FALSE;
  gboolean fullscreen = FALSE;
  if (g_win) {
    zoomed = gtk_window_is_maximized(g_win);
    fullscreen = gtk_window_is_fullscreen(g_win);
  }
  char line[256];
  snprintf(line, sizeof(line),
           "visible=%d zoomed=%d fullscreen=%d floating=%d close_guard=%d",
           g_hidden ? 0 : 1, zoomed ? 1 : 0, fullscreen ? 1 : 0,
           g_floating ? 1 : 0, g_close_guard ? 1 : 0);
  write_tmp("xu_ui_state.txt", line);
}

static void take_screenshot(void) {
  char path[1200];
  if (g_tmp[0])
    snprintf(path, sizeof(path), "%s/xu_ui_shot.png", g_tmp);
  else
    snprintf(path, sizeof(path), "/tmp/xu_ui_shot_%d.png", (int)getpid());
  int w = gtk_widget_get_width(GTK_WIDGET(g_win));
  int h = gtk_widget_get_height(GTK_WIDGET(g_win));
  if (w < 1) w = 1;
  if (h < 1) h = 1;
  if (!g_area) {
    /* Content plugin occupies the window — write empty PNG marker path only. */
    write_tmp("xu_ui_shot.png", "");
    append_shell_event("screenshot\t");
    return;
  }
  cairo_surface_t *surf = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w, h);
  cairo_t *cr = cairo_create(surf);
  on_draw(GTK_DRAWING_AREA(g_area), cr, w, h, NULL);
  cairo_destroy(cr);
  GdkPixbuf *pb = gdk_pixbuf_get_from_surface(surf, 0, 0, w, h);
  cairo_surface_destroy(surf);
  if (pb) {
    gdk_pixbuf_save(pb, path, "png", NULL, NULL);
    g_object_unref(pb);
    write_tmp("xu_ui_shot.png", path);
    append_shell_event("screenshot\tok");
  } else {
    append_shell_event("screenshot\t");
  }
}

static void open_uri(const char *uri) {
  if (!uri || !uri[0]) return;
  GError *err = NULL;
  g_app_info_launch_default_for_uri(uri, NULL, &err);
  if (err) g_error_free(err);
}

static void on_file_open_done(GObject *src, GAsyncResult *res, gpointer data) {
  (void)data;
  GError *err = NULL;
  GFile *file = gtk_file_dialog_open_finish(GTK_FILE_DIALOG(src), res, &err);
  if (file) {
    char *path = g_file_get_path(file);
    write_tmp("xu_ui_pick.txt", path ? path : "");
    char ev[1400];
    snprintf(ev, sizeof(ev), "file_picked\t%s", path ? path : "");
    append_shell_event(ev);
    g_free(path);
    g_object_unref(file);
  } else {
    write_tmp("xu_ui_pick.txt", "");
    append_shell_event("file_picked\t");
    if (err) g_error_free(err);
  }
}

static void on_folder_done(GObject *src, GAsyncResult *res, gpointer data) {
  (void)data;
  GError *err = NULL;
  GFile *file = gtk_file_dialog_select_folder_finish(GTK_FILE_DIALOG(src), res, &err);
  if (file) {
    char *path = g_file_get_path(file);
    write_tmp("xu_ui_pick.txt", path ? path : "");
    char ev[1400];
    snprintf(ev, sizeof(ev), "folder_picked\t%s", path ? path : "");
    append_shell_event(ev);
    g_free(path);
    g_object_unref(file);
  } else {
    write_tmp("xu_ui_pick.txt", "");
    append_shell_event("folder_picked\t");
    if (err) g_error_free(err);
  }
}

static void on_save_done(GObject *src, GAsyncResult *res, gpointer data) {
  (void)data;
  GError *err = NULL;
  GFile *file = gtk_file_dialog_save_finish(GTK_FILE_DIALOG(src), res, &err);
  if (file) {
    char *path = g_file_get_path(file);
    write_tmp("xu_ui_save.txt", path ? path : "");
    char ev[1400];
    snprintf(ev, sizeof(ev), "file_saved\t%s", path ? path : "");
    append_shell_event(ev);
    g_free(path);
    g_object_unref(file);
  } else {
    write_tmp("xu_ui_save.txt", "");
    append_shell_event("file_saved\t");
    if (err) g_error_free(err);
  }
}

static void on_alert_done(GObject *src, GAsyncResult *res, gpointer data) {
  int confirm = GPOINTER_TO_INT(data);
  GError *err = NULL;
  int btn = gtk_alert_dialog_choose_finish(GTK_ALERT_DIALOG(src), res, &err);
  if (confirm) {
    const char *ok = (btn == 0) ? "1" : "0";
    write_tmp("xu_ui_alert_result.txt", ok);
    char ev[32];
    snprintf(ev, sizeof(ev), "confirm\t%s", ok);
    append_shell_event(ev);
  } else {
    write_tmp("xu_ui_alert_result.txt", "ok");
    append_shell_event("alert\tok");
  }
  if (err) g_error_free(err);
}

static void show_alert(gboolean confirm) {
  char title[256], msg[4096];
  read_trim_file("xu_ui_alert_title.txt", title, sizeof(title));
  read_file_raw("xu_ui_alert_msg.txt", msg, sizeof(msg));
  GtkAlertDialog *d = gtk_alert_dialog_new("%s", title[0] ? title : "Xu");
  gtk_alert_dialog_set_detail(d, msg);
  if (confirm) {
    const char *labels[] = {"OK", "Cancel", NULL};
    gtk_alert_dialog_set_buttons(d, labels);
    gtk_alert_dialog_set_default_button(d, 0);
    gtk_alert_dialog_set_cancel_button(d, 1);
  } else {
    const char *labels[] = {"OK", NULL};
    gtk_alert_dialog_set_buttons(d, labels);
  }
  gtk_alert_dialog_choose(d, g_win, NULL, on_alert_done, GINT_TO_POINTER(confirm ? 1 : 0));
  g_object_unref(d);
}

static void clipboard_set(void) {
  char body[8192];
  read_file_raw("xu_ui_clipboard_set.txt", body, sizeof(body));
  GdkClipboard *clip = gdk_display_get_clipboard(gdk_display_get_default());
  gdk_clipboard_set_text(clip, body);
}

static void on_clipboard_text(GObject *src, GAsyncResult *res, gpointer data) {
  (void)data;
  GError *err = NULL;
  char *text = gdk_clipboard_read_text_finish(GDK_CLIPBOARD(src), res, &err);
  write_tmp("xu_ui_clipboard.txt", text ? text : "");
  g_free(text);
  if (err) g_error_free(err);
}

static void clipboard_get(void) {
  GdkClipboard *clip = gdk_display_get_clipboard(gdk_display_get_default());
  gdk_clipboard_read_text_async(clip, NULL, on_clipboard_text, NULL);
}

static void drain_title_size(void) {
  char title[512], size_raw[64];
  read_trim_file("xu_ui_title.txt", title, sizeof(title));
  if (title[0] && strcmp(title, g_last_title) != 0) {
    snprintf(g_last_title, sizeof(g_last_title), "%s", title);
    gtk_window_set_title(g_win, title);
  }
  read_trim_file("xu_ui_size.txt", size_raw, sizeof(size_raw));
  if (size_raw[0] && strcmp(size_raw, g_last_size) != 0) {
    int w = 0, h = 0;
    if (sscanf(size_raw, "%d %d", &w, &h) == 2 && w > 0 && h > 0) {
      snprintf(g_last_size, sizeof(g_last_size), "%s", size_raw);
      gtk_window_set_default_size(g_win, w, h);
    }
  }
  apply_app_icon();
}

#include "linux_screens.inc"
#include "linux_menus.inc"
static void handle_shell_cmd(const char *s) {
  if(!strcmp(s,"menu_v2")){unsigned meta[6]={};xu_ui_window_info(1,0,meta,NULL,0);native_menu_install(g_win,g_content_box,1,meta[1]);return;}
  if(g_root_closed)return;
  if(!strcmp(s,"close")){gtk_window_close(g_win);return;}
  if(!strncmp(s,"title\t",6)){write_tmp("xu_ui_title.txt",s+6);drain_title_size();return;}
  if(!strncmp(s,"size\t",5)){int width=0,height=0;char tail=0;
    if(sscanf(s+5,"%d\t%d%c",&width,&height,&tail)==2 && width>=40 && height>=40 && width<=16384 && height<=16384){char size[40];snprintf(size,sizeof(size),"%d %d",width,height);write_tmp("xu_ui_size.txt",size);drain_title_size();}return;
  }
  if (strcmp(s, "show") == 0) {
    g_hidden = FALSE;
    gtk_widget_set_visible(GTK_WIDGET(g_win), TRUE);
    gtk_window_present(g_win);
    return;
  }
  if (strcmp(s, "hide") == 0) {
    g_hidden = TRUE;
    gtk_widget_set_visible(GTK_WIDGET(g_win), FALSE);
    return;
  }
  if (strcmp(s, "minimize") == 0) {
    gtk_window_minimize(g_win);
    return;
  }
  if (strcmp(s, "maximize") == 0) {
    gtk_window_maximize(g_win);
    return;
  }
  if (strcmp(s, "unmaximize") == 0) {
    gtk_window_unmaximize(g_win);
    return;
  }
  if (strcmp(s, "quit") == 0) {
    do_quit();
    return;
  }
  if (strcmp(s, "bounce") == 0) {
    try_urgency_hint(TRUE);
    return;
  }
  if (strcmp(s, "center") == 0) {
    if (g_win) {
      int w = gtk_widget_get_width(GTK_WIDGET(g_win));
      int h = gtk_widget_get_height(GTK_WIDGET(g_win));
      if (w < 1) w = 800;
      if (h < 1) h = 560;
      GdkDisplay *disp = gdk_display_get_default();
      GdkMonitor *mon = NULL;
      if (disp) {
        GListModel *list = gdk_display_get_monitors(disp);
        if (list && g_list_model_get_n_items(list) > 0)
          mon = GDK_MONITOR(g_list_model_get_item(list, 0));
      }
      if (mon) {
        GdkRectangle geo;
        gdk_monitor_get_geometry(mon, &geo);
        int x = geo.x + (geo.width - w) / 2;
        int y = geo.y + (geo.height - h) / 2;
        char line[64];
        snprintf(line, sizeof(line), "%d %d", x, y);
        write_tmp("xu_ui_position.txt", line);
        try_move_window(x, y);
        g_object_unref(mon);
      }
      gtk_window_present(g_win);
    }
    return;
  }
  if (strcmp(s, "fullscreen") == 0) {
    gtk_window_fullscreen(g_win);
    return;
  }
  if (strcmp(s, "fullscreen_exit") == 0) {
    gtk_window_unfullscreen(g_win);
    return;
  }
  if (strcmp(s, "float") == 0) {
    g_floating = TRUE;
    /* GTK4 dropped keep-above; flag still reported via get_state. */
    if (g_win) gtk_window_present(g_win);
    return;
  }
  if (strcmp(s, "unfloat") == 0) {
    g_floating = FALSE;
    return;
  }
  if (strcmp(s, "pick_file") == 0) {
    GtkFileDialog *d = gtk_file_dialog_new();
    gtk_file_dialog_open(d, g_win, NULL, on_file_open_done, NULL);
    g_object_unref(d);
    return;
  }
  if (strcmp(s, "pick_folder") == 0) {
    GtkFileDialog *d = gtk_file_dialog_new();
    gtk_file_dialog_select_folder(d, g_win, NULL, on_folder_done, NULL);
    g_object_unref(d);
    return;
  }
  if (strcmp(s, "save_file") == 0) {
    GtkFileDialog *d = gtk_file_dialog_new();
    char name[256];
    read_trim_file("xu_ui_save_name.txt", name, sizeof(name));
    if (name[0]) gtk_file_dialog_set_initial_name(d, name);
    gtk_file_dialog_save(d, g_win, NULL, on_save_done, NULL);
    g_object_unref(d);
    return;
  }
  if (strcmp(s, "screenshot") == 0) {
    take_screenshot();
    return;
  }
  if (strcmp(s, "screenshot_clipboard") == 0) {
    take_screenshot();
    char path[1200];
    read_trim_file("xu_ui_shot.png", path, sizeof(path));
    if (!path[0]) {
      if (g_tmp[0]) snprintf(path, sizeof(path), "%s/xu_ui_shot.png", g_tmp);
      else snprintf(path, sizeof(path), "/tmp/xu_ui_shot_%d.png", (int)getpid());
    }
    GError *err = NULL;
    GdkPixbuf *pb = gdk_pixbuf_new_from_file(path, &err);
    if (!pb) {
      if (err) g_error_free(err);
      append_shell_event("screenshot\t");
      return;
    }
    GdkTexture *tex = gdk_texture_new_for_pixbuf(pb);
    g_object_unref(pb);
    if (tex) {
      GdkClipboard *clip = gdk_display_get_clipboard(gdk_display_get_default());
      GdkContentProvider *cp = gdk_content_provider_new_typed(GDK_TYPE_TEXTURE, tex);
      gdk_clipboard_set_content(clip, cp);
      g_object_unref(cp);
      g_object_unref(tex);
      append_shell_event("screenshot\tclipboard");
    } else {
      append_shell_event("screenshot\t");
    }
    return;
  }
  if (strcmp(s, "alert") == 0) {
    show_alert(FALSE);
    return;
  }
  if (strcmp(s, "confirm") == 0) {
    show_alert(TRUE);
    return;
  }
  if (strcmp(s, "notify") == 0) {
    show_desktop_notify();
    return;
  }
  if (strcmp(s, "accept_close") == 0) {
    g_close_guard = FALSE;
    g_close_pending = FALSE;
    do_quit();
    return;
  }
  if (strcmp(s, "reject_close") == 0) {
    g_close_pending = FALSE;
    append_shell_event("close_rejected");
    return;
  }
  if (strcmp(s, "get_bounds") == 0) {
    write_bounds();
    return;
  }
  if (strcmp(s, "get_state") == 0) {
    write_state();
    return;
  }
  if (strcmp(s, "clipboard_set") == 0) {
    clipboard_set();
    return;
  }
  if (strcmp(s, "clipboard_get") == 0) {
    clipboard_get();
    return;
  }
  if (strcmp(s, "open_external") == 0) {
    char url[2048];
    read_trim_file("xu_ui_open_url.txt", url, sizeof(url));
    open_uri(url);
    return;
  }
  if (strcmp(s, "open_path") == 0 || strcmp(s, "reveal_path") == 0) {
    char p[2048];
    read_trim_file("xu_ui_path.txt", p, sizeof(p));
    if (!p[0]) {
      read_trim_file(strcmp(s, "open_path") == 0 ? "xu_ui_open_path.txt" : "xu_ui_reveal_path.txt",
                     p, sizeof(p));
    }
    if (p[0]) {
      if (strcmp(s, "reveal_path") == 0) {
        char parent[2048];
        snprintf(parent, sizeof(parent), "%s", p);
        char *slash = strrchr(parent, '/');
        if (slash && slash != parent) *slash = 0;
        char uri[2200];
        snprintf(uri, sizeof(uri), "file://%s", parent[0] ? parent : "/");
        open_uri(uri);
      } else {
        char uri[2200];
        snprintf(uri, sizeof(uri), "file://%s", p);
        open_uri(uri);
      }
    }
    return;
  }
  if (strncmp(s, "frameless\t", 10) == 0) {
    apply_frameless(s[10] != '0');
    return;
  }
  if (strncmp(s, "transparent\t", 12) == 0) {
    apply_transparent(s[12] != '0');
    return;
  }
  if (strncmp(s, "opacity\t", 8) == 0) {
    double o = atof(s + 8);
    if (o < 0.15) o = 0.15;
    if (o > 1.0) o = 1.0;
    gtk_widget_set_opacity(GTK_WIDGET(g_win), o);
    return;
  }
  if (strncmp(s, "mask\t", 5) == 0) {
    apply_mask(s + 5);
    return;
  }
  if (strcmp(s, "mask_clear") == 0) {
    clear_mask();
    return;
  }
  if (strncmp(s, "titlebar\t", 9) == 0) {
    apply_frameless(s[9] == '0');
    return;
  }
  if (strncmp(s, "close_guard\t", 12) == 0) {
    g_close_guard = s[12] != '0';
    return;
  }
  if (strncmp(s, "shadow\t", 7) == 0) {
    return;
  }
  if (strncmp(s, "appearance\t", 11) == 0) {
    const char *mode = s + 11;
    GtkSettings *st = gtk_settings_get_default();
    if (st) {
      gboolean dark = (g_ascii_strcasecmp(mode, "dark") == 0);
      g_object_set(st, "gtk-application-prefer-dark-theme", dark, NULL);
    }
    return;
  }
  if (strncmp(s, "all_spaces\t", 11) == 0) {
    return;
  }
  if (strncmp(s, "dock_badge", 10) == 0) {
    return;
  }
  if (strncmp(s, "minsize\t", 8) == 0) {
    int w = 0, h = 0;
    sscanf(s + 8, "%d\t%d", &w, &h);
    g_min_w = w;
    g_min_h = h;
    if (g_win && w > 0 && h > 0) {
      gtk_widget_set_size_request(GTK_WIDGET(g_win), w, h);
    }
    return;
  }
  if (strncmp(s, "resizable\t", 10) == 0) {
    g_resizable = s[10] != '0';
    gtk_window_set_resizable(g_win, g_resizable);
    return;
  }
  if (strncmp(s, "position\t", 9) == 0) {
    int x = 0, y = 0;
    if (sscanf(s + 9, "%d\t%d", &x, &y) == 2) {
      char line[64];
      snprintf(line, sizeof(line), "%d %d", x, y);
      write_tmp("xu_ui_position.txt", line);
      try_move_window(x, y);
      if (g_win) gtk_window_present(g_win);
    }
    return;
  }
}

#define XU_MENU_MAX 32
#define XU_TRAY_MAX 32

static void post_menu_invoke(const char *id) {
  if (!id || !id[0]) return;
  char pending[32];
  read_trim_file("xu_ui_ipc_req.txt", pending, sizeof(pending));
  if (!pending[0]) {
    char body[640];
    snprintf(body, sizeof(body), "name: menu\npayload: %s\n", id);
    write_tmp("xu_ui_ipc_req.txt", body);
  }
  char ev[320];
  snprintf(ev, sizeof(ev), "menu_clicked\t%s", id);
  append_shell_event(ev);
}

static void post_tray_invoke(const char *id) {
  if (!id || !id[0]) return;
  char pending[32];
  read_trim_file("xu_ui_ipc_req.txt", pending, sizeof(pending));
  if (!pending[0]) {
    char body[640];
    snprintf(body, sizeof(body), "name: tray\npayload: %s\n", id);
    write_tmp("xu_ui_ipc_req.txt", body);
  }
  char ev[320];
  snprintf(ev, sizeof(ev), "tray_menu_clicked\t%s", id);
  append_shell_event(ev);
}

static void on_app_menu_activate(GSimpleAction *action, GVariant *param, gpointer user) {
  (void)action;
  (void)user;
  const char *id = param ? g_variant_get_string(param, NULL) : NULL;
  if (!id) return;
  if (strcmp(id, "quit") == 0) {
    post_menu_invoke(id);
    do_quit();
    return;
  }
  if (strcmp(id, "about") == 0) {
    GtkAlertDialog *d = gtk_alert_dialog_new("Xu WebView UI");
    gtk_alert_dialog_set_detail(d, "Xu desktop host (GTK4)");
    gtk_alert_dialog_show(d, g_win);
    g_object_unref(d);
  }
  if (strcmp(id, "devtools") == 0) {
    if (g_content && g_content_vt && g_content_vt->handle_cmd)
      g_content_vt->handle_cmd(g_content, "devtools");
    post_menu_invoke(id);
    return;
  }
  post_menu_invoke(id);
}

static int g_menu_action_ready = 0;
static int g_tray_action_ready = 0;

static void menu_install_or_update(void) {
  unsigned menu_meta[6]={};xu_ui_window_info(1,0,menu_meta,NULL,0);if(native_menu_install(g_win,g_content_box,1,menu_meta[1])||g_structured_menus.count(g_win))return;
  if (!g_app || !g_win) return;
  char items[4096];
  read_file_raw("xu_ui_menu.txt", items, sizeof(items));
  char sig[512];
  snprintf(sig, sizeof(sig), "%s", items);
  if (g_menubar_model && strcmp(sig, g_menu_sig) == 0) return;

  g_menu_n = 0;
  if (g_menubar_model) {
    gtk_application_set_menubar(g_app, NULL);
    g_object_unref(g_menubar_model);
    g_menubar_model = NULL;
  }

  if (!g_menu_action_ready) {
    GSimpleAction *act = g_simple_action_new("xu_menu", G_VARIANT_TYPE_STRING);
    g_signal_connect(act, "activate", G_CALLBACK(on_app_menu_activate), NULL);
    g_action_map_add_action(G_ACTION_MAP(g_app), G_ACTION(act));
    g_object_unref(act);
    g_menu_action_ready = 1;
  }

  GMenu *menubar = g_menu_new();
  GMenu *app = g_menu_new();
  if (!items[0]) {
    g_menu_append(app, "About", "app.xu_menu('about')");
    snprintf(g_menu_ids[0], sizeof(g_menu_ids[0]), "about");
    g_menu_append(app, "Quit", "app.xu_menu('quit')");
    snprintf(g_menu_ids[1], sizeof(g_menu_ids[1]), "quit");
    g_menu_n = 2;
  } else {
    char *p = items;
    while (*p && g_menu_n < XU_MENU_MAX) {
      char *line = p;
      while (*p && *p != '\n' && *p != '\r') p++;
      char save = *p;
      if (*p) {
        *p = 0;
        p++;
        if (save == '\r' && *p == '\n') p++;
      }
      while (*line == ' ') line++;
      if (!line[0]) continue;
      char *tab = strchr(line, '\t');
      const char *label = (tab && tab[1]) ? tab + 1 : line;
      if (tab) *tab = 0;
      snprintf(g_menu_ids[g_menu_n], sizeof(g_menu_ids[0]), "%s", line);
      char detailed[160];
      snprintf(detailed, sizeof(detailed), "app.xu_menu('%s')", line);
      g_menu_append(app, label, detailed);
      g_menu_n++;
    }
  }
  g_menu_append_submenu(menubar, "Xu", G_MENU_MODEL(app));
  g_object_unref(app);
  GMenu *view = g_menu_new();
  g_menu_append(view, "Developer Tools", "app.xu_menu('devtools')");
  g_menu_append_submenu(menubar, "View", G_MENU_MODEL(view));
  g_object_unref(view);

  gtk_application_set_menubar(g_app, G_MENU_MODEL(menubar));
  gtk_application_window_set_show_menubar(GTK_APPLICATION_WINDOW(g_win), TRUE);
  g_menubar_model = menubar;
  snprintf(g_menu_sig, sizeof(g_menu_sig), "%s", sig);
}

static void show_desktop_notify(void) {
  char title[256], body[4096];
  read_trim_file("xu_ui_notify_title.txt", title, sizeof(title));
  read_file_raw("xu_ui_notify_body.txt", body, sizeof(body));
  if (!title[0]) snprintf(title, sizeof(title), "Xu");
  if (g_app) {
    GNotification *n = g_notification_new(title);
    if (body[0]) g_notification_set_body(n, body);
    g_application_send_notification(G_APPLICATION(g_app), "xu-notify", n);
    g_object_unref(n);
  } else if (g_win) {
    try_urgency_hint(TRUE);
  }
  append_shell_event("notify\tok");
}

static void tray_on_item(GSimpleAction *action, GVariant *param, gpointer user) {
  (void)action;
  (void)user;
  const char *id = param ? g_variant_get_string(param, NULL) : NULL;
  if (!id) return;
  if (strcmp(id, "quit") == 0) {
    post_tray_invoke(id);
    do_quit();
    return;
  }
  if (strcmp(id, "show") == 0) {
    g_hidden = FALSE;
    gtk_widget_set_visible(GTK_WIDGET(g_win), TRUE);
    gtk_window_present(g_win);
  } else if (strcmp(id, "hide") == 0) {
    g_hidden = TRUE;
    gtk_widget_set_visible(GTK_WIDGET(g_win), FALSE);
  }
  post_tray_invoke(id);
}

static void tray_show_menu_at_pointer(void) {
  if (!g_win || g_tray_n <= 0) return;
  GMenu *menu = g_menu_new();
  for (int i = 0; i < g_tray_n; i++) {
    const char *label = g_tray_labels[i][0] ? g_tray_labels[i] : g_tray_ids[i];
    char detailed[160];
    snprintf(detailed, sizeof(detailed), "app.xu_tray('%s')", g_tray_ids[i]);
    g_menu_append(menu, label, detailed);
  }
  if (g_tray_popover) {
    gtk_widget_unparent(g_tray_popover);
    g_tray_popover = NULL;
  }
  g_tray_popover = gtk_popover_menu_new_from_model(G_MENU_MODEL(menu));
  g_object_unref(menu);
  gtk_widget_set_parent(g_tray_popover, GTK_WIDGET(g_win));
  gtk_popover_popup(GTK_POPOVER(g_tray_popover));
}

static void sni_method_call(GDBusConnection *conn, const gchar *sender, const gchar *path,
                            const gchar *iface, const gchar *method, GVariant *params,
                            GDBusMethodInvocation *inv, gpointer user) {
  (void)conn;
  (void)sender;
  (void)path;
  (void)iface;
  (void)params;
  (void)user;
  if (g_strcmp0(method, "Activate") == 0 || g_strcmp0(method, "SecondaryActivate") == 0) {
    g_hidden = FALSE;
    gtk_widget_set_visible(GTK_WIDGET(g_win), TRUE);
    gtk_window_present(g_win);
    g_dbus_method_invocation_return_value(inv, NULL);
    return;
  }
  if (g_strcmp0(method, "ContextMenu") == 0) {
    tray_show_menu_at_pointer();
    g_dbus_method_invocation_return_value(inv, NULL);
    return;
  }
  if (g_strcmp0(method, "Scroll") == 0) {
    g_dbus_method_invocation_return_value(inv, NULL);
    return;
  }
  g_dbus_method_invocation_return_error(inv, G_DBUS_ERROR, G_DBUS_ERROR_UNKNOWN_METHOD,
                                        "unknown method %s", method);
}

static GVariant *sni_get_property(GDBusConnection *conn, const gchar *sender, const gchar *path,
                                  const gchar *iface, const gchar *prop, GError **err, gpointer user) {
  (void)conn;
  (void)sender;
  (void)path;
  (void)iface;
  (void)err;
  (void)user;
  if (g_strcmp0(prop, "Category") == 0) return g_variant_new_string("ApplicationStatus");
  if (g_strcmp0(prop, "Id") == 0) return g_variant_new_string("xu-ui");
  if (g_strcmp0(prop, "Title") == 0) {
    char tip[256];
    read_trim_file("xu_ui_tray_tip.txt", tip, sizeof(tip));
    return g_variant_new_string(tip[0] ? tip : "Xu");
  }
  if (g_strcmp0(prop, "Status") == 0) return g_variant_new_string("Active");
  if (g_strcmp0(prop, "WindowId") == 0) return g_variant_new_uint32(0);
  if (g_strcmp0(prop, "IconName") == 0) return g_variant_new_string("");
  if (g_strcmp0(prop, "IconPixmap") == 0) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE("a(iiay)"));
    if (g_tray_pixbuf) {
      int w = gdk_pixbuf_get_width(g_tray_pixbuf);
      int h = gdk_pixbuf_get_height(g_tray_pixbuf);
      int stride = gdk_pixbuf_get_rowstride(g_tray_pixbuf);
      const guchar *px = gdk_pixbuf_get_pixels(g_tray_pixbuf);
      int nch = gdk_pixbuf_get_n_channels(g_tray_pixbuf);
      GVariantBuilder bytes;
      g_variant_builder_init(&bytes, G_VARIANT_TYPE("ay"));
      for (int y = 0; y < h; y++) {
        const guchar *row = px + y * stride;
        for (int x = 0; x < w; x++) {
          const guchar *p = row + x * nch;
          guchar a = nch >= 4 ? p[3] : 255;
          guchar r = p[0], g = p[1], bl = p[2];
          g_variant_builder_add(&bytes, "y", a);
          g_variant_builder_add(&bytes, "y", r);
          g_variant_builder_add(&bytes, "y", g);
          g_variant_builder_add(&bytes, "y", bl);
        }
      }
      g_variant_builder_add(&b, "(ii@ay)", w, h, g_variant_builder_end(&bytes));
    }
    return g_variant_builder_end(&b);
  }
  if (g_strcmp0(prop, "OverlayIconName") == 0 || g_strcmp0(prop, "AttentionIconName") == 0 ||
      g_strcmp0(prop, "AttentionMovieName") == 0)
    return g_variant_new_string("");
  if (g_strcmp0(prop, "OverlayIconPixmap") == 0 || g_strcmp0(prop, "AttentionIconPixmap") == 0) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE("a(iiay)"));
    return g_variant_builder_end(&b);
  }
  if (g_strcmp0(prop, "ToolTip") == 0) {
    char tip[256];
    read_trim_file("xu_ui_tray_tip.txt", tip, sizeof(tip));
    GVariantBuilder icons;
    g_variant_builder_init(&icons, G_VARIANT_TYPE("a(iiay)"));
    return g_variant_new("(s@a(iiay)ss)", "", g_variant_builder_end(&icons), tip[0] ? tip : "Xu", "");
  }
  if (g_strcmp0(prop, "ItemIsMenu") == 0) return g_variant_new_boolean(FALSE);
  if (g_strcmp0(prop, "Menu") == 0) return g_variant_new_object_path("/StatusNotifierItem/menu");
  return NULL;
}

static const GDBusInterfaceVTable g_sni_vtable = {
    sni_method_call, sni_get_property, NULL, {0}
};

static const char *g_sni_xml =
    "<node>"
    "  <interface name='org.kde.StatusNotifierItem'>"
    "    <method name='ContextMenu'><arg type='i' name='x' direction='in'/>"
    "      <arg type='i' name='y' direction='in'/></method>"
    "    <method name='Activate'><arg type='i' name='x' direction='in'/>"
    "      <arg type='i' name='y' direction='in'/></method>"
    "    <method name='SecondaryActivate'><arg type='i' name='x' direction='in'/>"
    "      <arg type='i' name='y' direction='in'/></method>"
    "    <method name='Scroll'><arg type='i' name='delta' direction='in'/>"
    "      <arg type='s' name='orientation' direction='in'/></method>"
    "    <property name='Category' type='s' access='read'/>"
    "    <property name='Id' type='s' access='read'/>"
    "    <property name='Title' type='s' access='read'/>"
    "    <property name='Status' type='s' access='read'/>"
    "    <property name='WindowId' type='u' access='read'/>"
    "    <property name='IconName' type='s' access='read'/>"
    "    <property name='IconPixmap' type='a(iiay)' access='read'/>"
    "    <property name='OverlayIconName' type='s' access='read'/>"
    "    <property name='OverlayIconPixmap' type='a(iiay)' access='read'/>"
    "    <property name='AttentionIconName' type='s' access='read'/>"
    "    <property name='AttentionIconPixmap' type='a(iiay)' access='read'/>"
    "    <property name='AttentionMovieName' type='s' access='read'/>"
    "    <property name='ToolTip' type='(sa(iiay)ss)' access='read'/>"
    "    <property name='ItemIsMenu' type='b' access='read'/>"
    "    <property name='Menu' type='o' access='read'/>"
    "    <signal name='NewTitle'/>"
    "    <signal name='NewIcon'/>"
    "    <signal name='NewAttentionIcon'/>"
    "    <signal name='NewOverlayIcon'/>"
    "    <signal name='NewToolTip'/>"
    "    <signal name='NewStatus'><arg type='s' name='status'/></signal>"
    "  </interface>"
    "</node>";

static void tray_ensure_sni(void) {
  if (g_sni_reg_id) return;
  GError *err = NULL;
  g_sni_conn = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, &err);
  if (!g_sni_conn) {
    if (err) g_error_free(err);
    return;
  }
  g_sni_bus_name = g_strdup_printf("org.kde.StatusNotifierItem-%d-1", (int)getpid());
  GBusNameOwnerFlags flags = G_BUS_NAME_OWNER_FLAGS_NONE;
  g_bus_own_name_on_connection(g_sni_conn, g_sni_bus_name, flags, NULL, NULL, NULL, NULL);
  GDBusNodeInfo *info = g_dbus_node_info_new_for_xml(g_sni_xml, &err);
  if (!info) {
    if (err) g_error_free(err);
    return;
  }
  g_sni_reg_id = g_dbus_connection_register_object(
      g_sni_conn, "/StatusNotifierItem", info->interfaces[0], &g_sni_vtable, NULL, NULL, &err);
  g_dbus_node_info_unref(info);
  if (!g_sni_reg_id) {
    if (err) g_error_free(err);
    return;
  }
  g_dbus_connection_call(g_sni_conn, "org.kde.StatusNotifierWatcher",
                         "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                         "RegisterStatusNotifierItem", g_variant_new("(s)", g_sni_bus_name),
                         NULL, G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL, NULL);
}

static void tray_install_or_update(void) {
  if (!g_app || !g_win) return;
  char tip[256], items[4096], icon_path[1024];
  read_trim_file("xu_ui_tray_tip.txt", tip, sizeof(tip));
  read_file_raw("xu_ui_tray.txt", items, sizeof(items));
  read_trim_file("xu_ui_tray_icon.txt", icon_path, sizeof(icon_path));
  if (!items[0]) return;
  char sig[512];
  snprintf(sig, sizeof(sig), "%s|%s|%s", tip, items, icon_path);
  if (strcmp(sig, g_tray_sig) == 0) return;

  g_tray_n = 0;
  char *p = items;
  while (*p && g_tray_n < XU_TRAY_MAX) {
    char *line = p;
    while (*p && *p != '\n' && *p != '\r') p++;
    char save = *p;
    if (*p) {
      *p = 0;
      p++;
      if (save == '\r' && *p == '\n') p++;
    }
    while (*line == ' ') line++;
    if (!line[0]) continue;
    char *tab = strchr(line, '\t');
    const char *label = (tab && tab[1]) ? tab + 1 : line;
    if (tab) *tab = 0;
    snprintf(g_tray_ids[g_tray_n], sizeof(g_tray_ids[0]), "%s", line);
    snprintf(g_tray_labels[g_tray_n], sizeof(g_tray_labels[0]), "%s", label);
    g_tray_n++;
  }
  if (g_tray_n == 0) return;

  if (!g_tray_action_ready) {
    GSimpleAction *tact = g_simple_action_new("xu_tray", G_VARIANT_TYPE_STRING);
    g_signal_connect(tact, "activate", G_CALLBACK(tray_on_item), NULL);
    g_action_map_add_action(G_ACTION_MAP(g_app), G_ACTION(tact));
    g_object_unref(tact);
    g_tray_action_ready = 1;
  }

  if (g_tray_pixbuf) {
    g_object_unref(g_tray_pixbuf);
    g_tray_pixbuf = NULL;
  }
  g_tray_pixbuf = load_app_icon_pixbuf(icon_path);
  tray_ensure_sni();
  if (g_sni_conn && g_sni_reg_id) {
    g_dbus_connection_emit_signal(g_sni_conn, NULL, "/StatusNotifierItem",
                                  "org.kde.StatusNotifierItem", "NewIcon", NULL, NULL);
    g_dbus_connection_emit_signal(g_sni_conn, NULL, "/StatusNotifierItem",
                                  "org.kde.StatusNotifierItem", "NewToolTip", NULL, NULL);
  }
  snprintf(g_tray_sig, sizeof(g_tray_sig), "%s", sig);
}

static const char *strip_prefix(const char *raw) {
  if (strncmp(raw, "shell.", 6) == 0) return raw + 6;
  if (strncmp(raw, "content.", 8) == 0) return raw + 8;
  if (strncmp(raw, "wv.", 3) == 0) return raw + 3;
  return raw;
}

static void maybe_install_content_plugin(void);
#include "linux_windows.inc"

static gboolean drain_cmds(gpointer data) {
  (void)data;
  desktop_clipboard_poll();
  desktop_files_poll();
  if(!g_root_closed)drain_title_size();
  extra_poll();
  if(g_root_closed && !xu_ui_window_count()){
    do_quit();if(g_quitting)return G_SOURCE_REMOVE;
  }
  tray_install_or_update();
  menu_install_or_update();
  if (g_content && g_content_vt && g_content_vt->on_poll) {
    g_content_vt->on_poll(g_content);
  }
  if (g_content && g_content_vt && g_content_vt->sync_frame) {
    g_content_vt->sync_frame(g_content);
  }
  std::string commands = xu_ui_take_commands(g_tmp);
  char *buf = commands.data();
  if (!buf[0]) return G_SOURCE_CONTINUE;
  char *save = NULL;
  char *line = strtok_r(buf, "\n", &save);
  while (line) {
    while (*line == ' ') line++;
    if (*line) {
      if(!strcmp(line,"shell.quit_app")){
        for(auto &window:g_extra_windows)extra_close(window,true);
        xu_ui_windows_shutdown();
        do_quit();return G_SOURCE_CONTINUE;
      }
      if(extra_dispatch(line)){line=strtok_r(NULL,"\n",&save);continue;}
      unsigned identity[2];const char *unscoped=line;
      xu_ui_scoped_command(line,identity,&unscoped);
      const char *cmd = strip_prefix(unscoped);
      int to_content = (strncmp(unscoped, "wv.", 3) == 0 || strncmp(unscoped, "content.", 8) == 0);
      if (to_content) {
        if (!desktop_screens(cmd,1,g_root_generation,g_win) && !desktop_files(cmd,1,g_root_generation,g_win) && !desktop_clipboard(cmd,1,g_root_generation) && g_content && g_content_vt && g_content_vt->handle_cmd) {
          g_content_vt->handle_cmd(g_content, cmd);
        }
        xu_ui_draw_discard_marker(cmd);
        xu_ui_request_discard_marker(cmd);
      } else {
        handle_shell_cmd(cmd);
      }
    }
    line = strtok_r(NULL, "\n", &save);
  }
  return G_SOURCE_CONTINUE;
}

static gboolean on_close(GtkWindow *w, gpointer user) {
  (void)w;
  (void)user;
  if (g_close_guard) {
    if (!g_close_pending) {
      g_close_pending = TRUE;
      append_shell_event("close_requested");
    }
    return TRUE;
  }
  do_quit();
  return TRUE;
}

static void on_map(GtkWidget *w, gpointer user) {
  (void)w;
  (void)user;
  rebuild_input_region();
  apply_app_icon();
}

static void host_write_tmp(const char *name, const char *body) { write_tmp(name, body); }
static void host_append_event(const char *payload) { append_shell_event(payload); }
static void host_read_trim(const char *name, char *out, unsigned n) {
  read_trim_file(name, out, (size_t)n);
}
static void host_read_raw(const char *name, char *out, unsigned n) {
  read_file_raw(name, out, (size_t)n);
}

static const XuContentVTable *resolve_content_vtable(void) {
  unsigned meta[6];if(xu_ui_window_info(1,0,meta,NULL,0))return content_kind_vtable(meta[4]);
  char kind[16];read_trim_file("xu_ui_content_kind.txt",kind,sizeof(kind));
  if(kind[0])return content_kind_vtable((unsigned)atoi(kind));
  char boot[256];
  read_trim_file("xu_ui_plugin_bootstrap.txt", boot, sizeof(boot));
  if (strcmp(boot, "XuWebViewPluginBootstrap") == 0) {
    if (xu_webview_plugin_vtable) return xu_webview_plugin_vtable();
    return NULL;
  }
  if (strcmp(boot, "XuDrawPluginBootstrap") == 0) {
    if (xu_draw_plugin_vtable) return xu_draw_plugin_vtable();
    return NULL;
  }
  return NULL;
}

static void maybe_install_content_plugin(void) {
  g_content_vt = resolve_content_vtable();
  if (!g_content_vt || !g_content_vt->create || !g_content_vt->install) return;
  memset(&g_content_host, 0, sizeof(g_content_host));
  g_content_host.tmp = g_tmp;
  g_content_host.window_id = 1;
  g_content_host.canvas_id = 1;
  unsigned meta[6];if(xu_ui_window_info(1,0,meta,NULL,0))g_content_host.canvas_generation=meta[1];
  g_content_host.native_window = (void *)g_win;
  g_content_host.content_parent = (void *)g_content_box;
  g_content_host.append_shell_event = host_append_event;
  g_content_host.write_tmp = host_write_tmp;
  g_content_host.read_trim = host_read_trim;
  g_content_host.read_raw = host_read_raw;
  g_content = g_content_vt->create(&g_content_host);
  if (g_content) g_content_vt->install(g_content);
}

static void activate(GApplication *app, gpointer user) {
  (void)user;
  g_app = GTK_APPLICATION(app);
  g_last_title[0] = 0;
  g_last_size[0] = 0;
  g_app_icon_sig[0] = 0;
  char title[512];
  char size_raw[64];
  read_trim_file("xu_ui_title.txt", title, sizeof(title));
  read_trim_file("xu_ui_size.txt", size_raw, sizeof(size_raw));
  if (!title[0]) snprintf(title, sizeof(title), "Xu");
  int width = 800, height = 560;
  sscanf(size_raw, "%d %d", &width, &height);
  if (width < 40) width = 40;
  if (height < 40) height = 40;
  snprintf(g_last_title, sizeof(g_last_title), "%s", title);
  snprintf(g_last_size, sizeof(g_last_size), "%s", size_raw);

  g_win = GTK_WINDOW(gtk_application_window_new(GTK_APPLICATION(app)));
  gtk_window_set_title(g_win, title);
  gtk_window_set_default_size(g_win, width, height);

  char chrome[32];
  read_trim_file("xu_ui_frameless.txt", chrome, sizeof(chrome));
  if (chrome[0] == '1') apply_frameless(TRUE);
  read_trim_file("xu_ui_transparent.txt", chrome, sizeof(chrome));
  if (chrome[0] == '1') apply_transparent(TRUE);
  read_trim_file("xu_ui_close_guard.txt", chrome, sizeof(chrome));
  if (chrome[0] == '1') g_close_guard = TRUE;

  g_content_box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
  gtk_window_set_child(g_win, g_content_box);

  unsigned identity[6];if(xu_ui_window_info(1,0,identity,NULL,0)){g_root_generation=identity[1];xu_ui_window_claim(1,identity[1]);}
  maybe_install_content_plugin();
  if(identity[1])xu_ui_window_ready(1,identity[1]);
  if (!g_content) {
    g_area = gtk_drawing_area_new();
    gtk_drawing_area_set_draw_func(GTK_DRAWING_AREA(g_area), on_draw, NULL, NULL);
    gtk_widget_set_hexpand(g_area, TRUE);
    gtk_widget_set_vexpand(g_area, TRUE);
    gtk_box_append(GTK_BOX(g_content_box), g_area);
  }

  char mask_path[1024];
  read_trim_file("xu_ui_mask_path.txt", mask_path, sizeof(mask_path));
  if (mask_path[0]) apply_mask(mask_path);

  g_signal_connect(g_win, "close-request", G_CALLBACK(on_close), NULL);
  g_signal_connect(g_win, "map", G_CALLBACK(on_map), NULL);
  gtk_window_present(g_win);
  apply_app_icon();
  menu_install_or_update();
  tray_install_or_update();
  append_shell_event("window_ready");
  append_shell_event("ready");
  xu_ui_host_set_kick([]() {
    g_idle_add(
        [](gpointer) -> gboolean {
          drain_cmds(NULL);
          return G_SOURCE_REMOVE;
        },
        NULL);
  });
  g_poll_id = g_timeout_add(200, drain_cmds, NULL);
}

extern "C" int xu_ui_host_run(const char *tmp_dir) {
  g_quitting = FALSE;
  xu_ui_emit_start();
  const char *tmp = tmp_dir;
  if (!tmp || !tmp[0]) tmp = getenv("XU_UI_TMP");
  // Pack/oneexe: no /tmp/xu_ui_* workdir — mailbox is xu_ui_mem (g_tmp empty).
  if (tmp && tmp[0] && strcmp(tmp, ":xu:") != 0 && strcmp(tmp, ":mem:") != 0) {
    snprintf(g_tmp, sizeof(g_tmp), "%s", tmp);
  } else {
    g_tmp[0] = 0;
  }

  GtkApplication *app = gtk_application_new("dev.xu.uihost", G_APPLICATION_DEFAULT_FLAGS);
  g_signal_connect(app, "activate", G_CALLBACK(activate), NULL);
  int status = g_application_run(G_APPLICATION(app), 0, NULL);
  if (g_mask) g_object_unref(g_mask);
  g_object_unref(app);
  return status;
}

#if !defined(XU_UI_STATIC)
int main(int argc, char **argv) {
  (void)argc;
  (void)argv;
  return xu_ui_host_run(NULL);
}
#endif
