// Xu #ui/webview Linux content plugin (WebKitGTK 6 / GTK4).
// Linked when ContentPlugin.linux_src is registered. Exports xu_webview_plugin_vtable().
// xu://app/* → register_uri_scheme returns www + /__xu (no HTTP server).

#include "xu_content_abi.h"
#include "xu_pack_assets.h"
#include "xu_ui_mem.h"

#include <gtk/gtk.h>
#include <webkit/webkit.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>

struct XuContentPlugin {
  XuContentHost host;
  WebKitWebView *web = nullptr;
  GtkWidget *widget = nullptr;
  GtkEventController *drop = nullptr;
  bool media_muted = false;
  bool context_menu = true;
  std::string last_url;
  std::string last_html;
  int last_progress = -1;
  bool load_failed = false;
};

static void host_event(XuContentPlugin *p, const char *ev) {
  if (p && p->host.append_shell_event) xu_content_event(&p->host,ev);
}

static void host_write(XuContentPlugin *p, const char *name, const char *body) {
  if (p && p->host.write_tmp) xu_content_write(&p->host,name,body);
}

static void host_read_trim(XuContentPlugin *p, const char *name, char *out, unsigned n) {
  out[0] = 0;
  if (p && p->host.read_trim) xu_content_read(&p->host,name,out,n,true);
}

static void host_read_raw(XuContentPlugin *p, const char *name, char *out, unsigned n) {
  out[0] = 0;
  if (p && p->host.read_raw) xu_content_read(&p->host,name,out,n,false);
}

static void eval_js_raw(XuContentPlugin *p, const char *js) {
  if (!p || !p->web || !js || !js[0]) return;
  webkit_web_view_evaluate_javascript(p->web, js, -1, NULL, NULL, NULL, NULL, NULL);
}

static void on_load_changed(WebKitWebView *web, WebKitLoadEvent ev, gpointer data) {
  XuContentPlugin *p = (XuContentPlugin *)data;
  (void)web;
  if (ev == WEBKIT_LOAD_STARTED) {
    p->load_failed = false;
    p->last_progress = -1;
    host_event(p, "loading");
    host_event(p, "progress\t0");
  } else if (ev == WEBKIT_LOAD_FINISHED && !p->load_failed) {
    host_event(p, "loaded");
    if (p->media_muted) {
      eval_js_raw(p,
                  "(function(){document.querySelectorAll('video,audio').forEach(function(e){"
                  "e.muted=true;e.volume=0;});})();");
    }
  }
}

static gboolean on_load_failed(WebKitWebView *web, WebKitLoadEvent ev, const gchar *uri, GError *err,
                           gpointer data) {
  (void)web;
  (void)ev;
  (void)uri;
  (void)err;
  XuContentPlugin *p = (XuContentPlugin *)data;
  p->load_failed = true;
  host_event(p, "load_failed");
  return FALSE;
}

static gboolean on_decide_policy(WebKitWebView *web, WebKitPolicyDecision *decision,
                                 WebKitPolicyDecisionType type, gpointer data) {
  XuContentPlugin *p = (XuContentPlugin *)data;
  (void)web;
  if (type != WEBKIT_POLICY_DECISION_TYPE_NAVIGATION_ACTION) return FALSE;
  WebKitNavigationPolicyDecision *nd = WEBKIT_NAVIGATION_POLICY_DECISION(decision);
  WebKitNavigationAction *action = webkit_navigation_policy_decision_get_navigation_action(nd);
  if (webkit_navigation_action_get_navigation_type(action) != WEBKIT_NAVIGATION_TYPE_LINK_CLICKED) {
    return FALSE;
  }
  WebKitURIRequest *req = webkit_navigation_action_get_request(action);
  const char *uri = webkit_uri_request_get_uri(req);
  if (!uri) return FALSE;
  if (strncmp(uri, "http://", 7) != 0 && strncmp(uri, "https://", 8) != 0) return FALSE;
  if (strstr(uri, "127.0.0.1") || strstr(uri, "localhost") || strstr(uri, "[::1]"))
    return FALSE;
  GError *err = NULL;
  g_app_info_launch_default_for_uri(uri, NULL, &err);
  if (err) g_error_free(err);
  char ev[2200];
  snprintf(ev, sizeof(ev), "external_nav\t%s", uri);
  host_event(p, ev);
  webkit_policy_decision_ignore(decision);
  return TRUE;
}

static void on_progress(WebKitWebView *web, GParamSpec *pspec, gpointer data) {
  (void)pspec;
  XuContentPlugin *p = (XuContentPlugin *)data;
  gdouble frac = webkit_web_view_get_estimated_load_progress(web);
  int pct = (int)(frac * 100.0 + 0.5);
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  int step = (pct == 0 || pct == 100 || p->last_progress < 0) || abs(pct - p->last_progress) >= 10;
  if (!step || pct == p->last_progress) return;
  p->last_progress = pct;
  char ev[32];
  snprintf(ev, sizeof(ev), "progress\t%d", pct);
  host_event(p, ev);
}

static gboolean on_drop(GtkDropTarget *target, const GValue *value, gdouble x, gdouble y,
                        gpointer data) {
  (void)target;
  (void)x;
  (void)y;
  XuContentPlugin *p = (XuContentPlugin *)data;
  if (!G_VALUE_HOLDS(value, GDK_TYPE_FILE_LIST)) return FALSE;
  GSList *files = (GSList *)g_value_get_boxed(value);
  std::string joined;
  for (GSList *it = files; it; it = it->next) {
    GFile *f = (GFile *)it->data;
    char *path = g_file_get_path(f);
    if (!path) continue;
    if (!joined.empty()) joined += "\t";
    joined += path;
    g_free(path);
  }
  if (joined.empty()) return FALSE;
  host_write(p, "xu_ui_drop.txt", joined.c_str());
  char ev[4096];
  snprintf(ev, sizeof(ev), "file_drop\t%s", joined.c_str());
  host_event(p, ev);
  return TRUE;
}

static XuContentPlugin *wv_create(XuContentHost *host) {
  XuContentPlugin *p = new XuContentPlugin();
  if (host) p->host = *host;
  return p;
}

static void wv_destroy(XuContentPlugin *p) {
  if (!p) return;
  if(p->web){
    g_signal_handlers_disconnect_by_data(p->web,p);
    g_object_set_data(G_OBJECT(p->web),"xu-ui-content",NULL);
    webkit_web_view_stop_loading(p->web);
  }
  if(p->drop && p->widget){g_signal_handlers_disconnect_by_data(p->drop,p);gtk_widget_remove_controller(p->widget,p->drop);p->drop=NULL;}
  if(p->widget){
    GtkWidget *parent=gtk_widget_get_parent(p->widget);
    if(parent && GTK_IS_BOX(parent))gtk_box_remove(GTK_BOX(parent),p->widget);
    else if(parent && GTK_IS_WINDOW(parent))gtk_window_set_child(GTK_WINDOW(parent),NULL);
    p->widget=NULL;p->web=NULL;
  }
  delete p;
}

static std::string read_tmp_all(XuContentPlugin *p, const char *name) {
  char buf[256 * 1024];
  host_read_raw(p, name, buf, sizeof(buf));
  return std::string(buf);
}

static std::string xu_ipc_invoke(XuContentPlugin *p, const std::string &body) {
  (void)p;
  char *raw = xu_ui_invoke_sync(body.c_str());
  if (!raw) return "ok: false\nerror: !s invoke null\n";
  std::string out(raw);
  free(raw);
  return out;
}

static std::string xu_ipc_poll(XuContentPlugin *p) {
  const char *tmp = p->host.tmp;
  if (!tmp || !tmp[0] || !strcmp(tmp, ":xu:") || !strcmp(tmp, ":mem:")) {
    unsigned len = 0; char *body = xu_ui_emit_take(&len);
    std::string message(body ? body : "", len); free(body); return message;
  }
  std::string raw = read_tmp_all(p, "xu_ui_emit_q.txt");
  if (raw.empty()) return "";
  size_t pos = raw.find('\x1e');
  if (pos == std::string::npos) {
    host_write(p, "xu_ui_emit_q.txt", "");
    return raw;
  }
  std::string msg = raw.substr(0, pos);
  host_write(p, "xu_ui_emit_q.txt", raw.substr(pos + 1).c_str());
  return msg;
}

static void xu_scheme_finish(WebKitURISchemeRequest *request, int status, const char *mime,
                             const std::string &body) {
  gpointer copy = g_malloc(body.size() > 0 ? body.size() : 1);
  if (body.size() > 0) memcpy(copy, body.data(), body.size());
  GInputStream *stream = g_memory_input_stream_new_from_data(copy, (gssize)body.size(), g_free);
  webkit_uri_scheme_request_finish(request, stream, (gint64)body.size(), mime ? mime : "text/plain");
  g_object_unref(stream);
  (void)status;
}

static std::string read_file_bytes(const char *path) {
  FILE *f = fopen(path, "rb");
  if (!f) return "";
  std::string out;
  char buf[8192];
  size_t n;
  while ((n = fread(buf, 1, sizeof(buf), f)) > 0) out.append(buf, buf + n);
  fclose(f);
  return out;
}

static const char *mime_for_path(const std::string &path) {
  auto ends = [&](const char *s) {
    size_t n = strlen(s);
    return path.size() >= n && path.compare(path.size() - n, n, s) == 0;
  };
  if (path == "/" || path.empty() || ends(".html") || ends(".htm"))
    return "text/html; charset=utf-8";
  if (ends(".css")) return "text/css; charset=utf-8";
  if (ends(".js")) return "application/javascript; charset=utf-8";
  if (ends(".json")) return "application/json; charset=utf-8";
  if (ends(".svg")) return "image/svg+xml";
  if (ends(".png")) return "image/png";
  if (ends(".jpg") || ends(".jpeg")) return "image/jpeg";
  if (ends(".webp")) return "image/webp";
  if (ends(".ico")) return "image/x-icon";
  return "application/octet-stream";
}

static bool pack_bytes(const char *rel, std::string &out) {
  const unsigned char *p = nullptr;
  unsigned n = 0;
  if (!rel || !xu_pack_find_www(rel, &p, &n) || !p || !n) return false;
  out.assign(reinterpret_cast<const char *>(p), n);
  return true;
}

static bool load_www_file(XuContentPlugin *p, const std::string &route, std::string &out) {
  std::string rel = route;
  if (rel.empty() || rel == "/") rel = "/index.html";
  if (rel.find("..") != std::string::npos) return false;
  if (rel == "/index.html") {
    std::string overlay = read_tmp_all(p, "xu_ui_www_index.html");
    if (!overlay.empty()) {
      out = overlay;
      return true;
    }
  }
  if (pack_bytes(rel.c_str(), out)) return true;
  char root[1024];
  host_read_trim(p, "xu_ui_www_root.txt", root, sizeof(root));
  if (!root[0] || strcmp(root, ":mem:") == 0) return false;
  while (!rel.empty() && rel[0] == '/') rel = rel.substr(1);
  char path[2048];
  snprintf(path, sizeof(path), "%s/%s", root, rel.c_str());
  out = read_file_bytes(path);
  return !out.empty();
}

static void xu_scheme_cb(WebKitURISchemeRequest *request, gpointer data) {
  (void)data;
  auto *web=webkit_uri_scheme_request_get_web_view(request);
  auto *p=web ? (XuContentPlugin *)g_object_get_data(G_OBJECT(web),"xu-ui-content") : NULL;
  if(!p){xu_scheme_finish(request,410,"text/plain","window closed\n");return;}
  const char *uri = webkit_uri_scheme_request_get_uri(request);
  if (!uri) {
    xu_scheme_finish(request, 400, "text/plain", "bad uri\n");
    return;
  }
  std::string u(uri);
  std::string path = "/";
  size_t host_start = 5; // xu://
  if (u.rfind("xu://", 0) == 0) {
    size_t slash = u.find('/', host_start);
    std::string host =
        (slash == std::string::npos) ? u.substr(host_start) : u.substr(host_start, slash - host_start);
    if (slash != std::string::npos) path = u.substr(slash);
    if (path.empty()) path = "/";
    if (host == "ipc") {
      path = std::string("/__xu") + (path == "/" ? "/invoke" : path);
    } else if (host != "app" && !host.empty()) {
      // xu://app.css / xu://__xu/bridge.js quirks
      path = "/" + host + (path == "/" ? "" : path);
      host = "app";
    }

    if (path.find("/__xu/invoke") != std::string::npos) {
      std::string body;
      GInputStream *in = webkit_uri_scheme_request_get_http_body(request);
      if (in) {
        char buf[4096];
        gssize n;
        while ((n = g_input_stream_read(in, buf, sizeof(buf), NULL, NULL)) > 0)
          body.append(buf, buf + n);
        g_object_unref(in);
      }
      xu_scheme_finish(request, 200, "text/xun; charset=utf-8", xu_ipc_invoke(p, body));
      return;
    }
    if (path.find("/__xu/poll") != std::string::npos) {
      xu_scheme_finish(request, 200, "text/xun; charset=utf-8", xu_ipc_poll(p));
      return;
    }
    if (path.find("/__xu/bridge.js") != std::string::npos) {
      std::string js = read_tmp_all(p, "xu_ui_bridge.js");
      xu_scheme_finish(request, js.empty() ? 404 : 200, "application/javascript; charset=utf-8",
                       js.empty() ? "/* no bridge */\n" : js);
      return;
    }
    if (path.rfind("/brand/", 0) == 0 || path == "/favicon.ico") {
      const char *fav[] = {"brand/xu_classic.svg", "brand/xu_classic.png", "brand/xu_app_logo.png",
                           "brand/xu_app_icon.png", nullptr};
      std::string one = (path == "/favicon.ico") ? std::string() : path.substr(1);
      const char *single[] = {one.c_str(), nullptr};
      const char **cands = (path == "/favicon.ico") ? fav : single;
      for (const char **it = cands; *it; ++it) {
        std::string rel(*it);
        std::string data;
        if (pack_bytes(rel.c_str(), data)) {
          xu_scheme_finish(request, 200, mime_for_path("/" + rel), data);
          return;
        }
        data = read_tmp_all(p, rel.c_str());
        if (!data.empty()) {
          xu_scheme_finish(request, 200, mime_for_path("/" + rel), data);
          return;
        }
      }
      xu_scheme_finish(request, 404, "text/plain", "icon missing\n");
      return;
    }
    if (host == "app" || host.empty()) {
      std::string body;
      if (load_www_file(p, path, body)) {
        xu_scheme_finish(request, 200, mime_for_path(path), body);
        return;
      }
      std::string html = read_tmp_all(p, "xu_ui_page.html");
      if (html.empty()) html = "<html><body>Xu: no page</body></html>";
      xu_scheme_finish(request, 200, "text/html; charset=utf-8", html);
      return;
    }
  }
  xu_scheme_finish(request, 404, "text/plain", "not found\n");
}

static bool is_app_xu_url(const char *url) {
  return url && url[0] && (strncmp(url, "xu://", 5) == 0 || strncmp(url, "http://app.xu", 13) == 0 ||
                           strncmp(url, "https://app.xu", 14) == 0);
}

static std::string normalize_app_xu_url(const char *url) {
  if (!url || !url[0]) return "xu://app/";
  if (strncmp(url, "xu://", 5) == 0) return url;
  if (strncmp(url, "http://app.xu", 13) == 0 || strncmp(url, "https://app.xu", 14) == 0) {
    const char *scheme = strstr(url, "://");
    const char *slash = scheme ? strchr(scheme + 3, '/') : NULL;
    std::string path = slash ? slash : "/";
    return std::string("xu://app") + path;
  }
  return "xu://app/";
}

static void load_app_document(XuContentPlugin *p, const char *app_url) {
  if (!p || !p->web) return;
  std::string u = normalize_app_xu_url(app_url);
  p->last_url = u;
  webkit_web_view_load_uri(p->web, u.c_str());
}

static void load_initial(XuContentPlugin *p) {
  char html[65536];
  char url[4096];
  char scheme[32];
  host_read_raw(p, "xu_ui_page.html", html, sizeof(html));
  host_read_trim(p, "xu_ui_page.url", url, sizeof(url));
  host_read_trim(p, "xu_ui_scheme.txt", scheme, sizeof(scheme));
  int remote = (strncmp(url, "http://", 7) == 0 || strncmp(url, "https://", 8) == 0) &&
               !is_app_xu_url(url);
  if (is_app_xu_url(url) || (strcmp(scheme, "xu") == 0 && !remote)) {
    load_app_document(p, url[0] ? url : "xu://app/");
    return;
  }
  if (url[0]) {
    p->last_url = url;
    webkit_web_view_load_uri(p->web, url);
    return;
  }
  if (html[0]) {
    p->last_html = html;
    webkit_web_view_load_html(p->web, html, NULL);
  } else if (strcmp(scheme, "xu") == 0) {
    load_app_document(p, "xu://app/");
  }
}

static gboolean on_context_menu(WebKitWebView *web, WebKitContextMenu *menu,
                                WebKitHitTestResult *hit, gpointer data) {
  (void)web;
  (void)menu;
  (void)hit;
  XuContentPlugin *p = (XuContentPlugin *)data;
  // TRUE = handled / suppress default menu (parity with macOS/Windows ctx off).
  return (p && !p->context_menu) ? TRUE : FALSE;
}

static void wv_install(XuContentPlugin *p) {
  if (!p || !p->host.content_parent) return;
  GtkWidget *parent = GTK_WIDGET(p->host.content_parent);
  WebKitWebContext *ctx = webkit_web_context_get_default();
  static bool registered=false;
  if(!registered){webkit_web_context_register_uri_scheme(ctx,"xu",xu_scheme_cb,NULL,NULL);registered=true;}
  WebKitWebView *web = WEBKIT_WEB_VIEW(webkit_web_view_new());
  p->web = web;
  g_object_set_data(G_OBJECT(web),"xu-ui-content",p);
  p->widget = GTK_WIDGET(web);
  gtk_widget_set_hexpand(p->widget, TRUE);
  gtk_widget_set_vexpand(p->widget, TRUE);
  GdkRGBA clear = {0, 0, 0, 0};
  webkit_web_view_set_background_color(web, &clear);

  {
    std::string bridge = read_tmp_all(p, "xu_ui_bridge.js");
    std::string src = "/*__XU_BRIDGE__*/\n" + bridge +
                      "\n(function(){if(window.__XU_CTX__===undefined)window.__XU_CTX__=true;"
                      "if(!window.__XU_CTX_HOOK__){window.__XU_CTX_HOOK__=true;"
                      "document.addEventListener('contextmenu',function(e){"
                      "if(!window.__XU_CTX__){e.preventDefault();e.stopPropagation();}"
                      "},true);}})();\n";
    WebKitUserContentManager *mgr = webkit_web_view_get_user_content_manager(web);
    WebKitUserScript *script = webkit_user_script_new(
        src.c_str(), WEBKIT_USER_CONTENT_INJECT_TOP_FRAME, WEBKIT_USER_SCRIPT_INJECT_AT_DOCUMENT_START,
        NULL, NULL);
    webkit_user_content_manager_add_script(mgr, script);
    webkit_user_script_unref(script);
  }

  g_signal_connect(web, "load-changed", G_CALLBACK(on_load_changed), p);
  g_signal_connect(web, "load-failed", G_CALLBACK(on_load_failed), p);
  g_signal_connect(web, "decide-policy", G_CALLBACK(on_decide_policy), p);
  g_signal_connect(web, "notify::estimated-load-progress", G_CALLBACK(on_progress), p);
  g_signal_connect(web, "context-menu", G_CALLBACK(on_context_menu), p);

  GtkDropTarget *drop = gtk_drop_target_new(GDK_TYPE_FILE_LIST, GDK_ACTION_COPY);
  g_signal_connect(drop, "drop", G_CALLBACK(on_drop), p);
  p->drop=GTK_EVENT_CONTROLLER(drop);
  gtk_widget_add_controller(p->widget, p->drop);

  if (GTK_IS_BOX(parent)) {
    gtk_box_append(GTK_BOX(parent), p->widget);
  } else if (GTK_IS_WINDOW(parent)) {
    gtk_window_set_child(GTK_WINDOW(parent), p->widget);
  }

  load_initial(p);
}

static void on_eval_done(GObject *src, GAsyncResult *res, gpointer data) {
  (void)data;
  auto *pl=(XuContentPlugin *)g_object_get_data(src,"xu-ui-content");
  GError *err = NULL;
  JSCValue *val = webkit_web_view_evaluate_javascript_finish(WEBKIT_WEB_VIEW(src), res, &err);
  std::string out;
  if (err) {
    out = std::string("err:") + err->message;
    g_error_free(err);
  } else if (val) {
    if (jsc_value_is_string(val)) {
      char *s = jsc_value_to_string(val);
      out = s ? s : "";
      g_free(s);
    } else if (jsc_value_is_number(val)) {
      char buf[64];
      snprintf(buf, sizeof(buf), "%g", jsc_value_to_double(val));
      out = buf;
    } else if (jsc_value_is_boolean(val)) {
      out = jsc_value_to_boolean(val) ? "true" : "false";
    }
  }
  if(val)g_object_unref(val);
  host_write(pl, "xu_ui_eval_result.txt", out.c_str());
}

static void on_find_done(GObject *src, GAsyncResult *res, gpointer data) {
  (void)data;
  auto *pl=(XuContentPlugin *)g_object_get_data(src,"xu-ui-content");
  GError *err = NULL;
  JSCValue *val = webkit_web_view_evaluate_javascript_finish(WEBKIT_WEB_VIEW(src), res, &err);
  const char *out = "0";
  if (!err && val && jsc_value_is_boolean(val) && jsc_value_to_boolean(val)) out = "1";
  if (err) g_error_free(err);
  if(val)g_object_unref(val);
  host_write(pl, "xu_ui_find_result.txt", out);
}

static void drain_eval(XuContentPlugin *p) {
  char js[65536];
  host_read_raw(p, "xu_ui_eval.js", js, sizeof(js));
  size_t L = strlen(js);
  while (L > 0 && (js[L - 1] == '\n' || js[L - 1] == '\r' || js[L - 1] == ' ')) js[--L] = 0;
  if (!js[0]) return;
  host_write(p, "xu_ui_eval.js", "");
  char want[32];
  host_read_trim(p, "xu_ui_eval_want.txt", want, sizeof(want));
  host_write(p, "xu_ui_eval_want.txt", "");
  if (strcmp(want, "1") == 0) {
    webkit_web_view_evaluate_javascript(p->web, js, -1, NULL, NULL, NULL, on_eval_done, NULL);
  } else {
    eval_js_raw(p, js);
  }
}

static void drain_page(XuContentPlugin *p) {
  char url[4096], html[65536], scheme[32];
  host_read_trim(p, "xu_ui_page.url", url, sizeof(url));
  host_read_raw(p, "xu_ui_page.html", html, sizeof(html));
  host_read_trim(p, "xu_ui_scheme.txt", scheme, sizeof(scheme));
  int remote = (strncmp(url, "http://", 7) == 0 || strncmp(url, "https://", 8) == 0) &&
               !is_app_xu_url(url);
  if (url[0] && p->last_url != url) {
    if (is_app_xu_url(url) || (strcmp(scheme, "xu") == 0 && !remote)) {
      load_app_document(p, url);
    } else {
      p->last_url = url;
      p->last_html.clear();
      webkit_web_view_load_uri(p->web, url);
    }
    return;
  }
  if (html[0] && p->last_html != html) {
    if (strcmp(scheme, "xu") == 0 && !remote) {
      load_app_document(p, url[0] ? url : "xu://app/");
      return;
    }
    p->last_html = html;
    p->last_url.clear();
    webkit_web_view_load_html(p->web, html, NULL);
  }
}

static void apply_bgcolor(XuContentPlugin *p, const char *hex) {
  if (!hex || !hex[0]) return;
  const char *h = hex;
  if (h[0] == '#') h++;
  unsigned r = 0, g = 0, b = 0;
  if (strlen(h) != 6 || sscanf(h, "%02x%02x%02x", &r, &g, &b) != 3) return;
  GdkRGBA rgba;
  rgba.red = r / 255.0;
  rgba.green = g / 255.0;
  rgba.blue = b / 255.0;
  rgba.alpha = 1.0;
  webkit_web_view_set_background_color(p->web, &rgba);
  char js[256];
  snprintf(js, sizeof(js),
           "(function(){var s=document.getElementById('__xu_bg_css');if(!s){s=document.createElement('style');"
           "s.id='__xu_bg_css';document.documentElement.appendChild(s);}s.textContent="
           "'html,body{background:#%s !important}';})();",
           h);
  eval_js_raw(p, js);
}

static int wv_handle_cmd(XuContentPlugin *p, const char *s) {
  if (!p || !p->web || !s) return 0;
  if (strcmp(s, "reload") == 0) {
    webkit_web_view_reload(p->web);
    return 1;
  }
  if (strcmp(s, "back") == 0) {
    webkit_web_view_go_back(p->web);
    return 1;
  }
  if (strcmp(s, "forward") == 0) {
    webkit_web_view_go_forward(p->web);
    return 1;
  }
  if (strcmp(s, "stop") == 0) {
    webkit_web_view_stop_loading(p->web);
    return 1;
  }
  if (strcmp(s, "print") == 0) {
    WebKitPrintOperation *op = webkit_print_operation_new(p->web);
    webkit_print_operation_run_dialog(op, GTK_WINDOW(p->host.native_window));
    g_object_unref(op);
    return 1;
  }
  if (strcmp(s, "clear_cache") == 0) {
    WebKitWebsiteDataManager *dm =
      webkit_network_session_get_website_data_manager(webkit_web_view_get_network_session(p->web));
    webkit_website_data_manager_clear(dm, WEBKIT_WEBSITE_DATA_ALL, 0, NULL, NULL, NULL);
    host_event(p, "cache_cleared");
    return 1;
  }
  if (strcmp(s, "cookies_clear") == 0) {
    WebKitWebsiteDataManager *dm =
      webkit_network_session_get_website_data_manager(webkit_web_view_get_network_session(p->web));
    webkit_website_data_manager_clear(dm, WEBKIT_WEBSITE_DATA_COOKIES, 0, NULL, NULL, NULL);
    host_event(p, "cookies_cleared");
    return 1;
  }
  if (strcmp(s, "cookies_get") == 0) {
    host_write(p, "xu_ui_cookies.txt", "");
    return 1;
  }
  if (strcmp(s, "cookie_set") == 0) {
    return 1;
  }
  if (strncmp(s, "magnify\t", 8) == 0) return 1;
  if (strcmp(s, "mute") == 0) {
    p->media_muted = true;
    eval_js_raw(p,
                "(function(){document.querySelectorAll('video,audio').forEach(function(e){"
                "e.muted=true;e.volume=0;});})();");
    return 1;
  }
  if (strcmp(s, "unmute") == 0) {
    p->media_muted = false;
    eval_js_raw(p,
                "(function(){document.querySelectorAll('video,audio').forEach(function(e){"
                "e.muted=false;e.volume=1;});})();");
    return 1;
  }
  if (strncmp(s, "bgcolor\t", 8) == 0) {
    apply_bgcolor(p, s + 8);
    return 1;
  }
  if (strncmp(s, "context_menu\t", 13) == 0) {
    p->context_menu = s[13] != '0';
    char js[640];
    snprintf(js, sizeof(js),
             "(function(){"
             "window.__XU_CTX__=%s;"
             "if(!window.__XU_CTX_HOOK__){"
             "window.__XU_CTX_HOOK__=true;"
             "document.addEventListener('contextmenu',function(e){"
             "if(!window.__XU_CTX__){e.preventDefault();e.stopPropagation();}"
             "},true);"
             "}"
             "})();",
             p->context_menu ? "true" : "false");
    eval_js_raw(p, js);
    return 1;
  }
  if (strcmp(s, "find") == 0) {
    char text[1024];
    host_read_trim(p, "xu_ui_find.txt", text, sizeof(text));
    if (!text[0]) {
      host_write(p, "xu_ui_find_result.txt", "0");
      return 1;
    }
    char esc[2048];
    size_t j = 0;
    for (size_t i = 0; text[i] && j + 2 < sizeof(esc); i++) {
      if (text[i] == '\\' || text[i] == '\'') esc[j++] = '\\';
      esc[j++] = text[i];
    }
    esc[j] = 0;
    char js[4096];
    snprintf(js, sizeof(js), "window.find('%s',false,false,true,false,false,false)", esc);
    webkit_web_view_evaluate_javascript(p->web, js, -1, NULL, NULL, NULL, on_find_done, NULL);
    return 1;
  }
  if (strcmp(s, "find_clear") == 0) {
    eval_js_raw(p, "if(window.getSelection){var s=window.getSelection();if(s)s.removeAllRanges();}");
    return 1;
  }
  if (strcmp(s, "inject_css") == 0) {
    char css[65536];
    host_read_raw(p, "xu_ui_inject.css", css, sizeof(css));
    if (!css[0]) return 1;
    std::string esc;
    for (const char *c = css; *c; c++) {
      if (*c == '\\' || *c == '`' || *c == '$') esc += '\\';
      esc += *c;
    }
    std::string js =
      "(function(){var s=document.getElementById('__xu_inject_css');if(!s){s=document.createElement('style');"
      "s.id='__xu_inject_css';document.documentElement.appendChild(s);}s.textContent=`" +
      esc + "`;})();";
    eval_js_raw(p, js.c_str());
    return 1;
  }
  if (strcmp(s, "set_ua") == 0) {
    char ua[1024];
    host_read_trim(p, "xu_ui_ua.txt", ua, sizeof(ua));
    WebKitSettings *st = webkit_web_view_get_settings(p->web);
    if (ua[0]) webkit_settings_set_user_agent(st, ua);
    return 1;
  }
  if (strcmp(s, "devtools") == 0) {
    WebKitSettings *st = webkit_web_view_get_settings(p->web);
    webkit_settings_set_enable_developer_extras(st, TRUE);
    WebKitWebInspector *ins = webkit_web_view_get_inspector(p->web);
    if (ins) webkit_web_inspector_show(ins);
    return 1;
  }
  if (strncmp(s, "zoom\t", 5) == 0) {
    double z = atof(s + 5);
    if (z > 0.1 && z < 10.0) webkit_web_view_set_zoom_level(p->web, z);
    return 1;
  }
  return 0;
}

static void wv_on_poll(XuContentPlugin *p) {
  if (!p || !p->web) return;
  drain_eval(p);
  drain_page(p);
}

static void wv_sync_frame(XuContentPlugin *p) {
  (void)p;
}

static void wv_eval_js(XuContentPlugin *p, const char *js) {
  eval_js_raw(p, js);
}

static const XuContentVTable g_wv_vt = {
  wv_create, wv_destroy, wv_install, wv_handle_cmd, wv_on_poll, wv_sync_frame, wv_eval_js,
};

extern "C" const XuContentVTable *xu_webview_plugin_vtable(void) {
  return &g_wv_vt;
}
