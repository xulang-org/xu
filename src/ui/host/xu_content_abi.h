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
  unsigned window_id;
  unsigned canvas_id;
  unsigned canvas_generation;
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

#ifdef __cplusplus
#include "xu_ui_mem.h"
#include "xu_ui_windows.h"
#include "xu_ui_native_views.h"
#include <stdio.h>
#include <string.h>
static inline void xu_content_event(const XuContentHost *host,const char *payload) {
  if(!host || !payload)return;
  if(host->canvas_id!=host->window_id)xu_ui_native_view_event(host->canvas_id,host->canvas_generation,payload);
  else if(host->window_id>1)xu_ui_window_event(host->window_id,host->canvas_generation,payload);
  else if(host->append_shell_event)host->append_shell_event(payload);
}
static inline bool xu_content_key(const XuContentHost *host,const char *name,char *key,unsigned cap) {
  if(!host || !name || !key || !cap)return false;
  int n=host->canvas_id!=host->window_id ? snprintf(key,cap,"view/%u/%u/%s",host->canvas_id,host->canvas_generation,name) : host->window_id>1 ? snprintf(key,cap,"window/%u/%u/%s",host->window_id,host->canvas_generation,name) : snprintf(key,cap,"%s",name);
  return n>0 && (unsigned)n<cap;
}
static inline void xu_content_write(const XuContentHost *host,const char *name,const char *body) {
  if(!host)return;
  if(host->window_id<=1 && host->canvas_id==host->window_id){if(host->write_tmp)host->write_tmp(name,body);return;}
  if(host->canvas_id!=host->window_id){if(!xu_ui_native_view_info(host->canvas_id,host->canvas_generation,NULL,NULL))return;}
  else {unsigned meta[6];if(!xu_ui_window_info(host->window_id,host->canvas_generation,meta,NULL,0))return;}
  char key[XU_UI_MEM_MAX_NAME+1];if(xu_content_key(host,name,key,sizeof(key)))xu_ui_mem_set(key,body?body:"");
}
static inline void xu_content_read(const XuContentHost *host,const char *name,char *out,unsigned cap,bool trim) {
  if(!out || !cap)return;out[0]=0;if(!host)return;
  if(host->window_id<=1 && host->canvas_id==host->window_id){auto read=trim?host->read_trim:host->read_raw;if(read)read(name,out,cap);return;}
  char key[XU_UI_MEM_MAX_NAME+1];if(xu_content_key(host,name,key,sizeof(key)))xu_ui_mem_get(key,out,cap);
  // Immutable app-wide bridge/assets configuration; page URL/HTML remain per window.
  if(!out[0] && ((host->canvas_id==host->window_id && !strcmp(name,"xu_ui_scheme.txt")) || !strcmp(name,"xu_ui_www_root.txt") || !strcmp(name,"xu_ui_bridge.js")))xu_ui_mem_get(name,out,cap);
  if(trim){unsigned size=(unsigned)strlen(out);while(size && (out[size-1]=='\n' || out[size-1]=='\r' || out[size-1]==' ' || out[size-1]=='\t'))out[--size]=0;}
}
#endif
