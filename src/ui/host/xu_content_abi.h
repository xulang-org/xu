// Shared content-plugin ABI for Linux/Windows UI hosts (#ui/webview, #ui/draw, …).
// macOS uses XuContentPlugin (Swift); L/W link one plugin .cc that exports a vtable.
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

typedef struct XuContentPlugin XuContentPlugin;

typedef struct XuContentHost {
  const char *tmp;
  void *native_window; /* GtkWindow* or HWND */
  void *content_parent; /* GtkWidget* box or HWND parent */
  void (*append_shell_event)(const char *payload);
  void (*write_tmp)(const char *name, const char *body);
  void (*read_trim)(const char *name, char *out, unsigned n);
  void (*read_raw)(const char *name, char *out, unsigned n);
} XuContentHost;

typedef struct XuContentVTable {
  XuContentPlugin *(*create)(XuContentHost *host);
  void (*destroy)(XuContentPlugin *p);
  /* Install into host->content_parent (GTK: append child; Win: create child HWND). */
  void (*install)(XuContentPlugin *p);
  /* Return 1 if command handled. */
  int (*handle_cmd)(XuContentPlugin *p, const char *cmd);
  void (*on_poll)(XuContentPlugin *p);
  void (*sync_frame)(XuContentPlugin *p);
  void (*eval_js)(XuContentPlugin *p, const char *js);
} XuContentVTable;

/* Strong symbols provided by linked plugin .cc; weak in shell when absent. */
const XuContentVTable *xu_webview_plugin_vtable(void);
const XuContentVTable *xu_draw_plugin_vtable(void);

#ifdef __cplusplus
}
#endif
