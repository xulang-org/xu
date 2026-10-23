// Xu #ui/webview Windows content plugin (WebView2).
// Linked only when ContentPlugin.windows_src is registered.
// Exports xu_webview_plugin_vtable() for the shell weak-link ABI.

#include "xu_content_abi.h"
#include "xu_pack_assets.h"
#include "xu_ui_mem.h"
#include "xu_ui_web_requests.h"
#include <vector>
#include <memory>
#include <atomic>
#include "webview2_min.h"

#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>

struct XuInvokeJob;
struct XuWebViewPlugin;
struct XuPluginLife { XuWebViewPlugin *plugin=NULL;unsigned native_queries=0; };
struct XuWebViewPlugin {
  std::vector<XuInvokeJob *> invokes;
  std::shared_ptr<XuPluginLife> life=std::make_shared<XuPluginLife>();
  XuContentHost host;
  HWND child = NULL;
  HMODULE loader = NULL;
  ICoreWebView2Environment *env = nullptr;
  ICoreWebView2Controller *controller = nullptr;
  ICoreWebView2 *webview = nullptr;
  bool ready = false;
  bool media_muted = false;
  bool context_menu = true;
  bool magnify = true;
  std::string last_url;
  std::string last_html;
  int last_progress = -1;
};

// --- COM handler helpers ---
template <typename TIface, const IID *TIid>
struct ComHandler : public TIface {
  virtual ~ComHandler() = default;
  LONG refs = 1;
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppv) override {
    if (!ppv) return E_POINTER;
    if (riid == IID_IUnknown || riid == *TIid) {
      *ppv = static_cast<TIface *>(this);
      AddRef();
      return S_OK;
    }
    *ppv = nullptr;
    return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override {
    return (ULONG)InterlockedIncrement(&refs);
  }
  ULONG STDMETHODCALLTYPE Release() override {
    LONG r = InterlockedDecrement(&refs);
    if (r == 0) delete this;
    return (ULONG)r;
  }
};

static void eval_raw(XuWebViewPlugin *p, const char *js_utf8, bool want_result);
static void wv_log(const char *step);
static HRESULT put_xu_response(XuWebViewPlugin *p, ICoreWebView2WebResourceRequestedEventArgs *args,
                               int status, const char *mime, const std::string &body);
static void xu_kick_host_drain(XuWebViewPlugin *p);

static void utf8_to_wide(const char *src, std::wstring &dst) {
  if (!src) src = "";
  int n = MultiByteToWideChar(CP_UTF8, 0, src, -1, NULL, 0);
  if (n <= 0) {
    dst.clear();
    return;
  }
  dst.resize((size_t)n);
  MultiByteToWideChar(CP_UTF8, 0, src, -1, &dst[0], n);
  if (!dst.empty() && dst.back() == L'\0') dst.pop_back();
}

static void wide_to_utf8(LPCWSTR src, std::string &dst) {
  if (!src) {
    dst.clear();
    return;
  }
  int n = WideCharToMultiByte(CP_UTF8, 0, src, -1, NULL, 0, NULL, NULL);
  if (n <= 0) {
    dst.clear();
    return;
  }
  dst.resize((size_t)n);
  WideCharToMultiByte(CP_UTF8, 0, src, -1, &dst[0], n, NULL, NULL);
  if (!dst.empty() && dst.back() == '\0') dst.pop_back();
}

static void host_event(XuWebViewPlugin *p, const char *payload) {
  if (p && p->host.append_shell_event) xu_content_event(&p->host,payload);
}

static void host_write(XuWebViewPlugin *p, const char *name, const char *body) {
  if (p && p->host.write_tmp) xu_content_write(&p->host,name,body);
}

static void host_read_trim(XuWebViewPlugin *p, const char *name, char *out, unsigned n) {
  if (out && n) out[0] = 0;
  if (p && p->host.read_trim) xu_content_read(&p->host,name,out,n,true);
}

static void host_read_raw(XuWebViewPlugin *p, const char *name, char *out, unsigned n) {
  if (out && n) out[0] = 0;
  if (p && p->host.read_raw) xu_content_read(&p->host,name,out,n,false);
}

static void show_missing_message(HWND hwnd, const char *msg_utf8) {
  if (!hwnd) return;
  wchar_t w[512];
  if (!msg_utf8) msg_utf8 = "";
  MultiByteToWideChar(CP_UTF8, 0, msg_utf8, -1, w, 512);
  w[511] = 0;
  MessageBoxW(hwnd, w, L"Xu WebView2", MB_OK | MB_ICONERROR);
}

static void sync_bounds(XuWebViewPlugin *p) {
  if (!p || !p->child || !p->controller) return;
  RECT rc;
  GetClientRect(p->child, &rc);
  p->controller->put_Bounds(rc);
}

static std::string read_tmp_all(XuWebViewPlugin *p, const char *name) {
  char buf[256 * 1024];
  host_read_raw(p, name, buf, sizeof(buf));
  return std::string(buf);
}

// Same body as webview.bridge_script() — used when PE has no __xu/bridge.js and TMP is empty.
#include "xu_webview_bridge.inc"

static bool pack_bytes(const char *rel, std::string &out);

static std::string load_bridge_js(XuWebViewPlugin *p) {
  std::string out;
  if (pack_bytes("__xu/bridge.js", out) && !out.empty()) return out;
  if (pack_bytes("/__xu/bridge.js", out) && !out.empty()) return out;
  out = read_tmp_all(p, "xu_ui_bridge.js");
  if (!out.empty()) return out;
  return std::string(kXuBridgeJs);
}

// Packed :mem: index.html has no inlined bridge; inject so window.__XU__ exists
// before page onclick handlers (AddScriptToExecuteOnDocumentCreated alone can race Navigate).
static void ensure_html_has_bridge(XuWebViewPlugin *p, std::string &html) {
  // Already inlined (marker or full bridge body) — skip.
  if (html.find("__XU_BRIDGE__") != std::string::npos) return;
  if (html.find("X.invoke=function") != std::string::npos) return;
  std::string bridge = load_bridge_js(p);
  std::string tag;
  if (!bridge.empty()) {
    tag = "<script>/*__XU_BRIDGE__*/\n" + bridge + "\n</script>\n";
  } else {
    // Last resort: external script (host must serve /__xu/bridge.js).
    if (html.find("__xu/bridge.js") != std::string::npos) return;
    tag = "<script src=\"xu://app/__xu/bridge.js\"></script>\n";
  }
  size_t head = html.find("</head>");
  if (head != std::string::npos) {
    html.insert(head, tag);
  } else {
    html = tag + html;
  }
}

static std::string xu_ipc_invoke_poll(XuWebViewPlugin *p, const std::string &body) {
  (void)p;
  // Scheme invoke: sync rendezvous with Xu worker (no req/resp slot files).
  char *raw = xu_ui_invoke_sync(body.c_str());
  if (!raw) return "ok: false\nerror: !s invoke null\n";
  std::string out(raw);
  free(raw);
  return out;
}

struct XuInvokeJob {
  XuWebViewPlugin *plugin;ICoreWebView2WebResourceRequestedEventArgs *args;ICoreWebView2Deferral *deferral;uint64_t ticket;bool binary;
};
enum { WM_XU_KICK_HOST = WM_APP + 43 };
static void xu_kick_host_drain(XuWebViewPlugin *p) {
 if(!p)return;HWND shell=(HWND)p->host.native_window;if(!shell&&p->child)shell=GetParent(p->child);if(shell)PostMessageW(shell,WM_XU_KICK_HOST,0,0);
}
static void xu_invoke_finish(XuInvokeJob *job,const std::string &out){
 put_xu_response(job->plugin,job->args,200,job->binary?"application/octet-stream":"text/xun; charset=utf-8",out);
 job->deferral->Complete();job->deferral->Release();job->args->Release();delete job;
}
static void xu_invoke_poll(XuWebViewPlugin *p){
 for(size_t i=0;i<p->invokes.size();){auto *job=p->invokes[i];unsigned size=0,status=4;void *data=xu_ui_web_invoke_result(job->ticket,&size,&status);if(!data){++i;continue;}
  auto out=xu_web_response(job->binary,status,data,size);free(data);p->invokes.erase(p->invokes.begin()+i);xu_invoke_finish(job,out);
 }
}
static void xu_invoke_close(XuWebViewPlugin *p){
 xu_ui_web_invoke_close(p->host.window_id,p->host.canvas_generation);
 for(auto *job:p->invokes)xu_invoke_finish(job,xu_web_response(job->binary,3,"window closed",13));p->invokes.clear();
}
static bool xu_ipc_invoke_async(XuWebViewPlugin *p,ICoreWebView2WebResourceRequestedEventArgs *args,const std::string &body,const std::string &client_key=""){
 bool binary=xu_web_binary(body);std::string key=client_key;if(key.empty()){static uint64_t serial=0;char text[33];snprintf(text,sizeof(text),"%08x%08x%016llx",p->host.window_id,p->host.canvas_generation,(unsigned long long)++serial);key=text;}
 ICoreWebView2Deferral *deferral=NULL;if(FAILED(args->GetDeferral(&deferral))||!deferral){put_xu_response(p,args,503,"text/plain","deferral unavailable");return true;}
 uint64_t ticket=xu_ui_web_invoke_start(p->host.window_id,p->host.canvas_generation,key.c_str(),body.data(),(unsigned)body.size(),xu_web_timeout(body));
 if(!ticket){auto out=xu_web_response(binary,4,"request capacity or invalid target",34);put_xu_response(p,args,429,"application/octet-stream",out);deferral->Complete();deferral->Release();return true;}
 auto *job=new XuInvokeJob{p,args,deferral,ticket,binary};args->AddRef();p->invokes.push_back(job);return true;
}

static std::string xu_ipc_poll(XuWebViewPlugin *p) {
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

static std::string stream_to_string(IStream *st) {
  if (!st) return "";
  std::string out;
  char buf[4096];
  ULONG n = 0;
  while (SUCCEEDED(st->Read(buf, sizeof(buf), &n)) && n > 0) {
    if(out.size()+n>XU_WEB_MAX_BODY)return {};
    out.append(buf, buf + n);
    n = 0;
  }
  return out;
}

static HRESULT put_xu_response(XuWebViewPlugin *p, ICoreWebView2WebResourceRequestedEventArgs *args,
                               int status, const char *mime, const std::string &body) {
  if (!p || !p->env || !args) return E_FAIL;
  HGLOBAL h = GlobalAlloc(GMEM_MOVEABLE, body.size() > 0 ? body.size() : 1);
  if (!h) return E_OUTOFMEMORY;
  void *mem = GlobalLock(h);
  if (mem && body.size() > 0) memcpy(mem, body.data(), body.size());
  if (mem) GlobalUnlock(h);
  IStream *stream = nullptr;
  if (FAILED(CreateStreamOnHGlobal(h, TRUE, &stream)) || !stream) {
    GlobalFree(h);
    return E_FAIL;
  }
  wchar_t hdrs[640];
  _snwprintf(hdrs, 640,
             L"Content-Type: %hs\r\nAccess-Control-Allow-Origin: *\r\n"
             L"Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
             L"Access-Control-Allow-Headers: Content-Type\r\n",
             mime ? mime : "text/plain");
  ICoreWebView2WebResourceResponse *resp = nullptr;
  HRESULT hr = p->env->CreateWebResourceResponse(stream, status, status == 204 ? L"No Content" : L"OK", hdrs, &resp);
  stream->Release();
  if (SUCCEEDED(hr) && resp) {
    args->put_Response(resp);
    resp->Release();
  }
  return hr;
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

static bool load_www_file(XuWebViewPlugin *p, const std::string &route, std::string &out) {
  std::string rel = route;
  if (rel.empty() || rel == "/") rel = "/index.html";
  if (rel.find("..") != std::string::npos) return false;
  if (rel == "/index.html") {
    std::string overlay = read_tmp_all(p, "xu_ui_www_index.html");
    if (!overlay.empty()) {
      out = overlay;
      ensure_html_has_bridge(p, out);
      return true;
    }
  }
  if (pack_bytes(rel.c_str(), out)) {
    if (rel == "/index.html" || rel == "/" ||
        (rel.size() >= 5 && rel.compare(rel.size() - 5, 5, ".html") == 0)) {
      ensure_html_has_bridge(p, out);
    }
    return true;
  }
  char root[1024];
  host_read_trim(p, "xu_ui_www_root.txt", root, sizeof(root));
  if (!root[0] || strcmp(root, ":mem:") == 0) return false;
  while (!rel.empty() && rel[0] == '/') rel = rel.substr(1);
  char path[2048];
  snprintf(path, sizeof(path), "%s/%s", root, rel.c_str());
  out = read_file_bytes(path);
  if (out.empty()) return false;
  if (rel.size() >= 5 && rel.compare(rel.size() - 5, 5, ".html") == 0) {
    ensure_html_has_bridge(p, out);
  }
  return true;
}

static bool xu_is_app_uri(const std::string &uri) {
  if (uri.rfind("xu://", 0) == 0) return true;
  if (uri.rfind("http://app.xu", 0) == 0) return true; // legacy
  if (uri.rfind("https://app.xu", 0) == 0) return true; // legacy
  return false;
}

static bool xu_parse_app_uri(const std::string &uri, std::string &host, std::string &path) {
  host.clear();
  path = "/";
  size_t scheme = 0;
  if (uri.rfind("http://", 0) == 0) scheme = 7;
  else if (uri.rfind("https://", 0) == 0) scheme = 8;
  else if (uri.rfind("xu://", 0) == 0) scheme = 5;
  else return false;
  size_t slash = uri.find('/', scheme);
  host = (slash == std::string::npos) ? uri.substr(scheme) : uri.substr(scheme, slash - scheme);
  // strip port if any
  size_t colon = host.find(':');
  if (colon != std::string::npos) host = host.substr(0, colon);
  if (slash != std::string::npos) path = uri.substr(slash);
  if (path.empty()) path = "/";
  return true;
}

static bool xu_handle_uri(XuWebViewPlugin *p, ICoreWebView2WebResourceRequestedEventArgs *args,
                          const std::string &uri, const std::string &method,
                          const std::string &req_body) {
  if (!xu_is_app_uri(uri)) return false;
  std::string host, path;
  if (!xu_parse_app_uri(uri, host, path)) return false;
  // Fold WK/WebView2 quirks: xu://app.css → path /app.css; xu://__xu/invoke → /__xu/invoke
  if (host == "ipc") {
    path = std::string("/__xu") + (path == "/" ? "/invoke" : path);
  } else if (host != "app" && host != "app.xu" && !host.empty()) {
    path = "/" + host + (path == "/" ? "" : path);
    host = "app";
  }

  if(path.rfind("/__xu/cancel2/",0)==0){xu_ui_web_invoke_cancel(p->host.window_id,p->host.canvas_generation,path.substr(14).c_str());xu_invoke_poll(p);put_xu_response(p,args,200,"text/plain","cancelled");return true;}
  if(path.rfind("/__xu/invoke2/",0)==0){if(method!="POST"){put_xu_response(p,args,405,"text/plain","POST required");return true;}return xu_ipc_invoke_async(p,args,req_body,path.substr(14));}
  if (path == "/__xu/invoke" ||
      (path.size() >= 12 && path.compare(path.size() - 12, 12, "/__xu/invoke") == 0)) {
    // OPTIONS preflight (some WebView2 builds) — do not block on IPC.
    if (method == "OPTIONS" || method == "options") {
      put_xu_response(p, args, 204, "text/plain", "");
      return true;
    }
    // Only POST carries an invoke body; GET/etc. must not enter the Xu worker.
    if (method != "POST" && method != "post") {
      put_xu_response(p, args, 405, "text/xun; charset=utf-8",
                      "ok: false\nerror: !s invoke method not allowed\n");
      return true;
    }
    xu_ipc_invoke_async(p, args, req_body);
    return true;
  }
  if (path == "/__xu/poll" ||
      (path.size() >= 10 && path.compare(path.size() - 10, 10, "/__xu/poll") == 0)) {
    put_xu_response(p, args, 200, "text/xun; charset=utf-8", xu_ipc_poll(p));
    return true;
  }
  if (path == "/__xu/bridge.js" ||
      (path.size() >= 14 && path.compare(path.size() - 14, 14, "/__xu/bridge.js") == 0)) {
    std::string js = load_bridge_js(p);
    put_xu_response(p, args, js.empty() ? 404 : 200, "application/javascript; charset=utf-8",
                    js.empty() ? "/* no bridge */\n" : js);
    return true;
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
        put_xu_response(p, args, 200, mime_for_path("/" + rel), data);
        return true;
      }
      data = read_tmp_all(p, rel.c_str());
      if (!data.empty()) {
        put_xu_response(p, args, 200, mime_for_path("/" + rel), data);
        return true;
      }
    }
    put_xu_response(p, args, 404, "text/plain", "icon missing\n");
    return true;
  }
  // http://app.xu/* or xu://app/*
  if (host == "app.xu" || host == "app" || host.empty()) {
    std::string body;
    if (load_www_file(p, path, body)) {
      put_xu_response(p, args, 200, mime_for_path(path), body);
      return true;
    }
    std::string html = read_tmp_all(p, "xu_ui_page.html");
    if (html.empty()) html = "<html><body>Xu: no page</body></html>";
    ensure_html_has_bridge(p, html);
    put_xu_response(p, args, 200, "text/html; charset=utf-8", html);
    return true;
  }
  put_xu_response(p, args, 404, "text/plain", "not found\n");
  return true;
}

struct WebResourceHandler
    : public ComHandler<ICoreWebView2WebResourceRequestedEventHandler,
                        &IID_ICoreWebView2WebResourceRequestedEventHandler> {
  std::shared_ptr<XuPluginLife> life;
  explicit WebResourceHandler(XuWebViewPlugin *p) : life(p->life) {}
  HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *sender,
                                   ICoreWebView2WebResourceRequestedEventArgs *args) override {
    auto *plugin=life->plugin;if(!plugin)return S_OK;
    (void)sender;
    if (!plugin || !args) return S_OK;
    ICoreWebView2WebResourceRequest *req = nullptr;
    if (FAILED(args->get_Request(&req)) || !req) return S_OK;
    LPWSTR wuri = nullptr, wmethod = nullptr;
    req->get_Uri(&wuri);
    req->get_Method(&wmethod);
    std::string uri, method, body;
    wide_to_utf8(wuri, uri);
    wide_to_utf8(wmethod, method);
    if (wuri) CoTaskMemFree(wuri);
    if (wmethod) CoTaskMemFree(wmethod);
    IStream *content = nullptr;
    if (SUCCEEDED(req->get_Content(&content)) && content) {
      body = stream_to_string(content);
      content->Release();
    }
    req->Release();
    if (!xu_handle_uri(plugin, args, uri, method, body)) {
      char line[512];
      snprintf(line, sizeof(line), "xu_webview: unhandled %s", uri.c_str());
      wv_log(line);
    } else {
      char line[512];
      snprintf(line, sizeof(line), "xu_webview: served %s", uri.c_str());
      wv_log(line);
    }
    return S_OK;
  }
};

static void emit_progress(XuWebViewPlugin *p, int pct) {
  if (!p) return;
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  bool step = (pct == 0 || pct == 100 || p->last_progress < 0) ||
              abs(pct - p->last_progress) >= 10;
  if (!step || pct == p->last_progress) return;
  p->last_progress = pct;
  char line[64];
  snprintf(line, sizeof(line), "progress\t%d", pct);
  host_event(p, line);
  char js[512];
  snprintf(js, sizeof(js),
           "(function(){var bar=document.getElementById('xu_prog');var "
           "fill=document.getElementById('xu_prog_fill');var "
           "label=document.getElementById('xu_prog_label');if(bar)bar.style.opacity='1';"
           "if(fill)fill.style.width='%d%%';if(label)label.textContent='loading %d%%';"
           "if(%d>=100){setTimeout(function(){if(bar)bar.style.opacity='0';},400);}})();",
           pct, pct, pct);
  eval_raw(p, js, false);
}

struct NavStartingHandler
    : public ComHandler<ICoreWebView2NavigationStartingEventHandler,
                        &IID_ICoreWebView2NavigationStartingEventHandler> {
  std::shared_ptr<XuPluginLife> life;
  explicit NavStartingHandler(XuWebViewPlugin *p) : life(p->life) {}
  HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *sender,
                                   ICoreWebView2NavigationStartingEventArgs *args) override {
    auto *plugin=life->plugin;if(!plugin)return S_OK;
    (void)sender;
    if (!plugin || !args) return S_OK;
    xu_invoke_close(plugin);
    plugin->last_progress = -1;
    host_event(plugin, "loading");
    host_event(plugin, "progress\t0");
    LPWSTR uri = nullptr;
    if (SUCCEEDED(args->get_Uri(&uri)) && uri) {
      std::string u;
      wide_to_utf8(uri, u);
      CoTaskMemFree(uri);
      // External http(s) off localhost → shell open + cancel (link-like).
      BOOL user = FALSE;
      args->get_IsUserInitiated(&user);
      if (user && (u.rfind("http://", 0) == 0 || u.rfind("https://", 0) == 0)) {
        std::string host;
        size_t start = u.find("://");
        if (start != std::string::npos) {
          start += 3;
          size_t end = u.find_first_of("/?#", start);
          host = (end == std::string::npos) ? u.substr(start) : u.substr(start, end - start);
          for (char &c : host)
            if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
        }
        if (host != "127.0.0.1" && host != "localhost" && host != "::1") {
          std::string path = u;
          size_t path_i = u.find('/', u.find("://") + 3);
          if (path_i != std::string::npos) path = u.substr(path_i);
          else path = "/";
          for (char &c : path)
            if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
          const char *dl[] = {".pdf", ".zip", ".exe", ".msi", ".7z", ".rar",
                              ".iso", ".csv", ".xlsx", ".docx", nullptr};
          bool downloadish = false;
          for (int i = 0; dl[i]; i++) {
            if (path.size() >= strlen(dl[i]) &&
                path.compare(path.size() - strlen(dl[i]), strlen(dl[i]), dl[i]) == 0) {
              downloadish = true;
              break;
            }
          }
          if (!downloadish) {
            std::wstring wu;
            utf8_to_wide(u.c_str(), wu);
            ShellExecuteW(NULL, L"open", wu.c_str(), NULL, NULL, SW_SHOWNORMAL);
            std::string ev = "external_nav\t" + u;
            host_event(plugin, ev.c_str());
            args->put_Cancel(TRUE);
            return S_OK;
          }
        }
      }
    }
    emit_progress(plugin, 0);
    return S_OK;
  }
};

struct NavCompletedHandler
    : public ComHandler<ICoreWebView2NavigationCompletedEventHandler,
                        &IID_ICoreWebView2NavigationCompletedEventHandler> {
  std::shared_ptr<XuPluginLife> life;
  explicit NavCompletedHandler(XuWebViewPlugin *p) : life(p->life) {}
  HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *sender,
                                   ICoreWebView2NavigationCompletedEventArgs *args) override {
    auto *plugin=life->plugin;if(!plugin)return S_OK;
    (void)sender;
    if (!plugin) return S_OK;
    BOOL ok = FALSE;
    if (args) args->get_IsSuccess(&ok);
    if (ok) {
      host_event(plugin, "loaded");
      emit_progress(plugin, 100);
      if (plugin->media_muted) {
        eval_raw(plugin,
                 "(function(){document.querySelectorAll('video,audio').forEach(function(e){"
                 "e.muted=true;e.defaultMuted=true;e.volume=0;});})();",
                 false);
      }
    } else {
      host_event(plugin, "load_failed");
    }
    sync_bounds(plugin);
    return S_OK;
  }
};

struct NewWindowHandler
    : public ComHandler<ICoreWebView2NewWindowRequestedEventHandler,
                        &IID_ICoreWebView2NewWindowRequestedEventHandler> {
  std::shared_ptr<XuPluginLife> life;
  explicit NewWindowHandler(XuWebViewPlugin *p) : life(p->life) {}
  HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2 *sender,
                                   ICoreWebView2NewWindowRequestedEventArgs *args) override {
    auto *plugin=life->plugin;if(!plugin)return S_OK;
    (void)sender;
    if (!args) return S_OK;
    LPWSTR uri = nullptr;
    if (SUCCEEDED(args->get_Uri(&uri)) && uri) {
      std::string u;
      wide_to_utf8(uri, u);
      CoTaskMemFree(uri);
      std::wstring wu;
      utf8_to_wide(u.c_str(), wu);
      ShellExecuteW(NULL, L"open", wu.c_str(), NULL, NULL, SW_SHOWNORMAL);
      if (plugin) {
        std::string ev = "external_nav\t" + u;
        host_event(plugin, ev.c_str());
      }
    }
    args->put_Handled(TRUE);
    return S_OK;
  }
};

struct EnvCreatedHandler
    : public ComHandler<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler,
                        &IID_ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler> {
  std::shared_ptr<XuPluginLife> life;
  explicit EnvCreatedHandler(XuWebViewPlugin *p) : life(p->life) {}
  HRESULT STDMETHODCALLTYPE Invoke(HRESULT errorCode,
                                   ICoreWebView2Environment *createdEnvironment) override;
};

struct ControllerCreatedHandler
    : public ComHandler<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler,
                        &IID_ICoreWebView2CreateCoreWebView2ControllerCompletedHandler> {
  std::shared_ptr<XuPluginLife> life;
  explicit ControllerCreatedHandler(XuWebViewPlugin *p) : life(p->life) {}
  HRESULT STDMETHODCALLTYPE Invoke(HRESULT errorCode,
                                   ICoreWebView2Controller *createdController) override;
};

struct EvalHandler
    : public ComHandler<ICoreWebView2ExecuteScriptCompletedHandler,
                        &IID_ICoreWebView2ExecuteScriptCompletedHandler> {
  std::shared_ptr<XuPluginLife> life;
  bool want = false;uint64_t request=0;
  bool counted=false;
  explicit EvalHandler(XuWebViewPlugin *p, bool w,uint64_t id=0) : life(p->life), want(w),request(id) {if(id){++life->native_queries;counted=true;}}
  ~EvalHandler(){if(counted)--life->native_queries;}
  void finish_query(){if(counted){--life->native_queries;counted=false;}}
  HRESULT STDMETHODCALLTYPE Invoke(HRESULT errorCode, LPCWSTR resultObjectAsJson) override {
    finish_query();auto *plugin=life->plugin;if(!plugin)return S_OK;
    if (!want || !plugin) return S_OK;
    std::string out;
    if (FAILED(errorCode)) {
      out = "err:execute_script_failed";
    } else if (resultObjectAsJson) {
      wide_to_utf8(resultObjectAsJson, out);
      // JSON string results arrive quoted; peel simple "..." form.
      if (out.size() >= 2 && out.front() == '"' && out.back() == '"') {
        std::string decoded;
        if(!xu_web_unquote(out,&decoded)){if(request)xu_web_native_complete(request,false,"invalid JSON result");return S_OK;}
        out=std::move(decoded);
      } else if (out == "null") {
        out.clear();
      }
    }
    if(request)xu_web_native_complete(request,SUCCEEDED(errorCode),out);
    else host_write(plugin, "xu_ui_eval_result.txt", out.c_str());
    return S_OK;
  }
};

struct CookiesHandler
    : public ComHandler<ICoreWebView2GetCookiesCompletedHandler,
                        &IID_ICoreWebView2GetCookiesCompletedHandler> {
  std::shared_ptr<XuPluginLife> life;
  uint64_t request=0;
  bool counted=false;
  explicit CookiesHandler(XuWebViewPlugin *p,uint64_t id=0) : life(p->life),request(id) {if(id){++life->native_queries;counted=true;}}
  ~CookiesHandler(){if(counted)--life->native_queries;}
  void finish_query(){if(counted){--life->native_queries;counted=false;}}
  HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2CookieList *list) override {
    finish_query();auto *plugin=life->plugin;if(!plugin)return S_OK;
    if (!plugin) return S_OK;
    std::string body;
    UINT count = 0;
    if (SUCCEEDED(result) && list && SUCCEEDED(list->get_Count(&count))) {
      for (UINT i = 0; i < count; i++) {
        ICoreWebView2Cookie *c = nullptr;
        if (FAILED(list->GetValueAtIndex(i, &c)) || !c) continue;
        LPWSTR name = nullptr, value = nullptr, domain = nullptr, path = nullptr;
        c->get_Name(&name);
        c->get_Value(&value);
        c->get_Domain(&domain);
        c->get_Path(&path);
        std::string n, v, d, pa;
        wide_to_utf8(name, n);
        wide_to_utf8(value, v);
        wide_to_utf8(domain, d);
        wide_to_utf8(path, pa);
        if (name) CoTaskMemFree(name);
        if (value) CoTaskMemFree(value);
        if (domain) CoTaskMemFree(domain);
        if (path) CoTaskMemFree(path);
        if (!body.empty()) body.push_back('\n');
        body += n + "=" + v + ";domain=" + d + ";path=" + pa;
        c->Release();
      }
    }
    if(request){xu_web_native_complete(request,SUCCEEDED(result),body);return S_OK;}
    host_write(plugin, "xu_ui_cookies.txt", body.c_str());
    char js[128];
    snprintf(js, sizeof(js),
             "var el=document.getElementById('out');if(el)el.textContent='cookies: %u';", count);
    eval_raw(plugin, js, false);
    return S_OK;
  }
};

static void eval_raw(XuWebViewPlugin *p, const char *js_utf8, bool want_result) {
  if (!p || !p->webview || !js_utf8) return;
  std::wstring wjs;
  utf8_to_wide(js_utf8, wjs);
  auto *h = new EvalHandler(p, want_result);
  p->webview->ExecuteScript(wjs.c_str(), h);
  h->Release();
}

static void load_initial(XuWebViewPlugin *p) {
  if (!p || !p->webview) return;
  char html[256 * 1024];
  char url[8192];
  char scheme[32];
  host_read_raw(p, "xu_ui_page.html", html, sizeof(html));
  host_read_trim(p, "xu_ui_page.url", url, sizeof(url));
  host_read_trim(p, "xu_ui_scheme.txt", scheme, sizeof(scheme));
  {
    char line[256];
    snprintf(line, sizeof(line), "xu_webview: load_initial url=%s scheme=%s html_len=%u pack_www=%d",
             url[0] ? url : "(empty)", scheme[0] ? scheme : "(empty)",
             (unsigned)strlen(html), xu_pack_has_www());
    wv_log(line);
  }
  int remote = (strncmp(url, "http://", 7) == 0 || strncmp(url, "https://", 8) == 0) &&
               !(strncmp(url, "http://app.xu", 13) == 0 || strncmp(url, "https://app.xu", 14) == 0 ||
                 strncmp(url, "xu://", 5) == 0);
  if (url[0] && (strncmp(url, "xu://", 5) == 0 || strncmp(url, "http://app.xu", 13) == 0 ||
                 strncmp(url, "https://app.xu", 14) == 0)) {
    p->last_url = url;
    p->last_html.clear();
    std::wstring wu;
    if (strncmp(url, "http://app.xu", 13) == 0 || strncmp(url, "https://app.xu", 14) == 0) {
      const char *sch = strstr(url, "://");
      const char *slash = sch ? strchr(sch + 3, '/') : nullptr;
      std::string mapped = std::string("xu://app") + (slash ? slash : "/");
      utf8_to_wide(mapped.c_str(), wu);
      p->last_url = mapped;
    } else {
      utf8_to_wide(url, wu);
    }
    wv_log("xu_webview: Navigate xu:// (or mapped)");
    p->webview->Navigate(wu.c_str());
    return;
  }
  if (scheme[0] == 'x' && !remote) {
    p->last_url = "xu://app/";
    p->last_html.clear();
    wv_log("xu_webview: Navigate xu://app/ (scheme flag)");
    p->webview->Navigate(L"xu://app/");
    return;
  }
  if (url[0]) {
    p->last_url = url;
    p->last_html.clear();
    std::wstring wu;
    utf8_to_wide(url, wu);
    wv_log("xu_webview: Navigate remote/other url");
    p->webview->Navigate(wu.c_str());
    return;
  }
  if (html[0]) {
    p->last_html = html;
    p->last_url.clear();
    std::wstring wh;
    utf8_to_wide(html, wh);
    wv_log("xu_webview: NavigateToString html");
    p->webview->NavigateToString(wh.c_str());
  } else if (scheme[0] == 'x') {
    p->last_url = "xu://app/";
    p->last_html.clear();
    wv_log("xu_webview: Navigate xu://app/ (fallback)");
    p->webview->Navigate(L"xu://app/");
  }
}

HRESULT STDMETHODCALLTYPE ControllerCreatedHandler::Invoke(
    HRESULT errorCode, ICoreWebView2Controller *createdController) {
  auto *plugin=life->plugin;if(!plugin){if(createdController)createdController->Close();return S_OK;}
  if (!plugin) return S_OK;
  if (FAILED(errorCode) || !createdController) {
    show_missing_message(plugin->child,
                         "WebView2 controller creation failed.\n"
                         "Install Microsoft Edge WebView2 Runtime.");
    return S_OK;
  }
  plugin->controller = createdController;
  plugin->controller->AddRef();
  plugin->controller->get_CoreWebView2(&plugin->webview);
  if (!plugin->webview) {
    show_missing_message(plugin->child, "WebView2 CoreWebView2 unavailable.");
    return S_OK;
  }
  plugin->controller->put_IsVisible(TRUE);
  sync_bounds(plugin);

  ICoreWebView2Settings *settings = nullptr;
  if (SUCCEEDED(plugin->webview->get_Settings(&settings)) && settings) {
    settings->put_AreDevToolsEnabled(TRUE);
    settings->put_IsZoomControlEnabled(TRUE);
    settings->put_AreDefaultContextMenusEnabled(plugin->context_menu ? TRUE : FALSE);
    settings->Release();
  }

  EventRegistrationToken tok{};
  auto *ns = new NavStartingHandler(plugin);
  plugin->webview->add_NavigationStarting(ns, &tok);
  ns->Release();
  auto *nc = new NavCompletedHandler(plugin);
  plugin->webview->add_NavigationCompleted(nc, &tok);
  nc->Release();
  auto *nw = new NewWindowHandler(plugin);
  plugin->webview->add_NewWindowRequested(nw, &tok);
  nw->Release();

  plugin->webview->AddWebResourceRequestedFilter(L"xu://*", COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL);
  plugin->webview->AddWebResourceRequestedFilter(L"http://app.xu/*",
                                                 COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL); // legacy
  plugin->webview->AddWebResourceRequestedFilter(L"https://app.xu/*",
                                                 COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL); // legacy
  auto *wr = new WebResourceHandler(plugin);
  plugin->webview->add_WebResourceRequested(wr, &tok);
  wr->Release();

  // Inject XUN bridge; Navigate only after registration completes (avoids race where
  // page scripts run before window.__XU__ exists).
  {
    std::string bridge = load_bridge_js(plugin);
    if (!bridge.empty()) {
      // Persist context-menu hook across navigations (same model as macOS WKUserScript).
      std::string src = "/*__XU_BRIDGE__*/\n" + bridge +
                        "\n(function(){if(window.__XU_CTX__===undefined)window.__XU_CTX__=true;"
                        "if(!window.__XU_CTX_HOOK__){window.__XU_CTX_HOOK__=true;"
                        "document.addEventListener('contextmenu',function(e){"
                        "if(!window.__XU_CTX__){e.preventDefault();e.stopPropagation();}"
                        "},true);}})();\n";
      std::wstring wjs;
      utf8_to_wide(src.c_str(), wjs);
      struct ScriptReadyHandler
          : public ComHandler<ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler,
                              &IID_ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler> {
        std::shared_ptr<XuPluginLife> life;
        explicit ScriptReadyHandler(XuWebViewPlugin *p) : life(p->life) {}
        HRESULT STDMETHODCALLTYPE Invoke(HRESULT errorCode, LPCWSTR id) override {
    auto *plugin=life->plugin;if(!plugin)return S_OK;
          (void)errorCode;
          (void)id;
          if (plugin) {
            plugin->ready = true;
            load_initial(plugin);
          }
          return S_OK;
        }
      };
      auto *done = new ScriptReadyHandler(plugin);
      HRESULT ahr = plugin->webview->AddScriptToExecuteOnDocumentCreated(wjs.c_str(), done);
      done->Release();
      if (FAILED(ahr)) {
        wv_log("xu_webview: AddScriptToExecuteOnDocumentCreated failed; navigate anyway");
        plugin->ready = true;
        load_initial(plugin);
      }
      return S_OK;
    }
  }

  plugin->ready = true;
  load_initial(plugin);
  return S_OK;
}

HRESULT STDMETHODCALLTYPE EnvCreatedHandler::Invoke(HRESULT errorCode,
                                                    ICoreWebView2Environment *createdEnvironment) {
  auto *plugin=life->plugin;if(!plugin)return S_OK;
  if (!plugin) return S_OK;
  if (FAILED(errorCode) || !createdEnvironment) {
    show_missing_message(plugin->child,
                         "WebView2 environment creation failed.\n"
                         "Install Microsoft Edge WebView2 Runtime\n"
                         "(Evergreen; required on the machine).");
    return S_OK;
  }
  plugin->env = createdEnvironment;
  plugin->env->AddRef();
  auto *h = new ControllerCreatedHandler(plugin);
  plugin->env->CreateCoreWebView2Controller(plugin->child, h);
  h->Release();
  return S_OK;
}

static LRESULT CALLBACK ChildWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
  XuWebViewPlugin *p = (XuWebViewPlugin *)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
  switch (msg) {
  case WM_SIZE:
    if (p) sync_bounds(p);
    return 0;
  case WM_DROPFILES: {
    if (!p) break;
    HDROP drop = (HDROP)wParam;
    UINT n = DragQueryFileW(drop, 0xFFFFFFFF, NULL, 0);
    std::string joined;
    for (UINT i = 0; i < n; i++) {
      wchar_t wpath[2048];
      DragQueryFileW(drop, i, wpath, 2048);
      std::string u;
      wide_to_utf8(wpath, u);
      if (!joined.empty()) joined.push_back('\t');
      joined += u;
    }
    DragFinish(drop);
    host_write(p, "xu_ui_drop.txt", joined.c_str());
    std::string ev = "file_drop\t" + joined;
    host_event(p, ev.c_str());
    return 0;
  }
  }
  return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static void ensure_child_class(void) {
  static bool once = false;
  if (once) return;
  once = true;
  WNDCLASSW wc;
  ZeroMemory(&wc, sizeof(wc));
  wc.lpfnWndProc = ChildWndProc;
  wc.hInstance = GetModuleHandleW(NULL);
  wc.lpszClassName = L"XuWebViewContent";
  wc.hCursor = LoadCursor(NULL, IDC_ARROW);
  wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
  RegisterClassW(&wc);
}

static XuWebViewPlugin *plugin_create(XuContentHost *host) {
  auto *p = new XuWebViewPlugin();p->life->plugin=p;
  if (host) p->host = *host;
  return p;
}

static void plugin_destroy(XuWebViewPlugin *p) {
  if (!p) return;
  p->life->plugin=NULL;xu_invoke_close(p);
  if (p->controller) {
    p->controller->Close();
    p->controller->Release();
    p->controller = nullptr;
  }
  if (p->webview) {
    p->webview->Release();
    p->webview = nullptr;
  }
  if (p->env) {
    p->env->Release();
    p->env = nullptr;
  }
  if (p->child) {
    DestroyWindow(p->child);
    p->child = NULL;
  }
  if (p->loader) {
    FreeLibrary(p->loader);
    p->loader = NULL;
  }
  delete p;
}

static void wv_log(const char *step) {
  OutputDebugStringA(step);
  OutputDebugStringA("\n");
  const char *logp = getenv("XU_UI_LOG");
  if (logp && logp[0]) {
    FILE *f = fopen(logp, "a");
    if (f) {
      fprintf(f, "%s\r\n", step);
      fclose(f);
    }
  }
  fprintf(stderr, "%s\n", step);
  fflush(stderr);
}

static LPWSTR xu_cotask_dup(LPCWSTR s) {
  if (!s) s = L"";
  size_t n = (wcslen(s) + 1) * sizeof(wchar_t);
  LPWSTR out = (LPWSTR)CoTaskMemAlloc(n);
  if (out) memcpy(out, s, n);
  return out;
}

// Minimal EnvironmentOptions + CustomSchemeRegistration so Navigate("xu://…") works.
struct XuCustomSchemeReg : public ICoreWebView2CustomSchemeRegistration {
  LONG refs = 1;
  BOOL treat_secure = TRUE;
  BOOL has_authority = TRUE;
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppv) override {
    if (!ppv) return E_POINTER;
    if (riid == IID_IUnknown || riid == IID_ICoreWebView2CustomSchemeRegistration) {
      *ppv = static_cast<ICoreWebView2CustomSchemeRegistration *>(this);
      AddRef();
      return S_OK;
    }
    *ppv = nullptr;
    return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return (ULONG)InterlockedIncrement(&refs); }
  ULONG STDMETHODCALLTYPE Release() override {
    LONG r = InterlockedDecrement(&refs);
    if (r == 0) delete this;
    return (ULONG)r;
  }
  HRESULT STDMETHODCALLTYPE get_SchemeName(LPWSTR *value) override {
    if (!value) return E_POINTER;
    *value = xu_cotask_dup(L"xu");
    return *value ? S_OK : E_OUTOFMEMORY;
  }
  HRESULT STDMETHODCALLTYPE get_TreatAsSecure(BOOL *value) override {
    if (!value) return E_POINTER;
    *value = treat_secure;
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE put_TreatAsSecure(BOOL value) override {
    treat_secure = value;
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE GetAllowedOrigins(UINT32 *count, LPWSTR **origins) override {
    if (!count || !origins) return E_POINTER;
    *count = 1;
    *origins = (LPWSTR *)CoTaskMemAlloc(sizeof(LPWSTR));
    if (!*origins) return E_OUTOFMEMORY;
    (*origins)[0] = xu_cotask_dup(L"*");
    return (*origins)[0] ? S_OK : E_OUTOFMEMORY;
  }
  HRESULT STDMETHODCALLTYPE SetAllowedOrigins(UINT32, LPCWSTR *) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE get_HasAuthorityComponent(BOOL *value) override {
    if (!value) return E_POINTER;
    *value = has_authority;
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE put_HasAuthorityComponent(BOOL value) override {
    has_authority = value;
    return S_OK;
  }
};

struct XuEnvOptions : public ICoreWebView2EnvironmentOptions,
                      public ICoreWebView2EnvironmentOptions4 {
  LONG refs = 1;
  ICoreWebView2CustomSchemeRegistration *scheme = nullptr;
  XuEnvOptions() {
    scheme = new XuCustomSchemeReg();
  }
  ~XuEnvOptions() {
    if (scheme) scheme->Release();
  }
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void **ppv) override {
    if (!ppv) return E_POINTER;
    if (riid == IID_IUnknown || riid == IID_ICoreWebView2EnvironmentOptions) {
      *ppv = static_cast<ICoreWebView2EnvironmentOptions *>(this);
      AddRef();
      return S_OK;
    }
    if (riid == IID_ICoreWebView2EnvironmentOptions4) {
      *ppv = static_cast<ICoreWebView2EnvironmentOptions4 *>(this);
      AddRef();
      return S_OK;
    }
    *ppv = nullptr;
    return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return (ULONG)InterlockedIncrement(&refs); }
  ULONG STDMETHODCALLTYPE Release() override {
    LONG r = InterlockedDecrement(&refs);
    if (r == 0) delete this;
    return (ULONG)r;
  }
  HRESULT STDMETHODCALLTYPE get_AdditionalBrowserArguments(LPWSTR *value) override {
    if (!value) return E_POINTER;
    *value = xu_cotask_dup(L"");
    return *value ? S_OK : E_OUTOFMEMORY;
  }
  HRESULT STDMETHODCALLTYPE put_AdditionalBrowserArguments(LPCWSTR) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE get_Language(LPWSTR *value) override {
    if (!value) return E_POINTER;
    *value = xu_cotask_dup(L"");
    return *value ? S_OK : E_OUTOFMEMORY;
  }
  HRESULT STDMETHODCALLTYPE put_Language(LPCWSTR) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE get_TargetCompatibleBrowserVersion(LPWSTR *value) override {
    if (!value) return E_POINTER;
    *value = xu_cotask_dup(L"95.0.1020.0");
    return *value ? S_OK : E_OUTOFMEMORY;
  }
  HRESULT STDMETHODCALLTYPE put_TargetCompatibleBrowserVersion(LPCWSTR) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE get_AllowSingleSignOnUsingOSPrimaryAccount(BOOL *allow) override {
    if (!allow) return E_POINTER;
    *allow = FALSE;
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE put_AllowSingleSignOnUsingOSPrimaryAccount(BOOL) override {
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE GetCustomSchemeRegistrations(
      UINT32 *count, ICoreWebView2CustomSchemeRegistration ***regs) override {
    if (!count || !regs) return E_POINTER;
    *count = scheme ? 1u : 0u;
    if (!scheme) {
      *regs = nullptr;
      return S_OK;
    }
    *regs = (ICoreWebView2CustomSchemeRegistration **)CoTaskMemAlloc(
        sizeof(ICoreWebView2CustomSchemeRegistration *));
    if (!*regs) return E_OUTOFMEMORY;
    (*regs)[0] = scheme;
    scheme->AddRef();
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE SetCustomSchemeRegistrations(
      UINT32, ICoreWebView2CustomSchemeRegistration **) override {
    return S_OK;
  }
};

static void plugin_install(XuWebViewPlugin *p) {
  if (!p) return;
  wv_log("xu_webview: plugin_install");
  ensure_child_class();
  wv_log("xu_webview: child class ok");
  HWND parent = (HWND)(p->host.content_parent ? p->host.content_parent : p->host.native_window);
  if (!parent) {
    wv_log("xu_webview: no parent hwnd");
    return;
  }
  RECT rc;
  GetClientRect(parent, &rc);
  p->child = CreateWindowExW(0, L"XuWebViewContent", L"", WS_CHILD | WS_VISIBLE,
                             0, 0, rc.right - rc.left, rc.bottom - rc.top, parent, NULL,
                             GetModuleHandleW(NULL), NULL);
  if (!p->child) {
    wv_log("xu_webview: CreateWindowEx child failed");
    return;
  }
  SetWindowLongPtrW(p->child, GWLP_USERDATA, (LONG_PTR)p);
  DragAcceptFiles(p->child, TRUE);
  wv_log("xu_webview: child hwnd ok");

  auto create = xu_load_webview2_create_env(&p->loader);
  if (!create) {
    wv_log("xu_webview: loader missing");
    show_missing_message(p->child,
                         "WebView2Loader bootstrap missing.\n"
                         "Repack with: xu build AppDir --target windows-x64 --desktop\n"
                         "(embeds Loader from dist/windows-x64-ui/_build/)\n"
                         "and install Edge WebView2 Runtime.");
    return;
  }
  wv_log("xu_webview: loader ok, creating env");

  // User data: never under xu_ui_*; use LocalAppData\\XuWebView2 or default.
  wchar_t user_data_w[MAX_PATH];
  user_data_w[0] = 0;
  {
    char ud[MAX_PATH];
    ud[0] = 0;
    DWORD n = GetEnvironmentVariableA("LOCALAPPDATA", ud, MAX_PATH);
    if (n > 0 && n < MAX_PATH) {
      char full[MAX_PATH];
      snprintf(full, sizeof(full), "%s\\XuWebView2", ud);
      CreateDirectoryA(full, NULL);
      MultiByteToWideChar(CP_UTF8, 0, full, -1, user_data_w, MAX_PATH);
      user_data_w[MAX_PATH - 1] = 0;
    }
  }
  auto *opts = new XuEnvOptions();
  auto *h = new EnvCreatedHandler(p);
  wv_log("xu_webview: EnvCreatedHandler new ok (xu:// scheme registered)");
  HRESULT hr = create(nullptr, user_data_w[0] ? user_data_w : nullptr, opts, h);
  opts->Release();
  h->Release();
  if (FAILED(hr)) {
    wv_log("xu_webview: CreateCoreWebView2Environment failed");
    show_missing_message(p->child,
                         "CreateCoreWebView2EnvironmentWithOptions failed.\n"
                         "Install Microsoft Edge WebView2 Runtime.");
  } else {
    wv_log("xu_webview: CreateCoreWebView2Environment scheduled");
  }
}

static ICoreWebView2CookieManager *get_cookie_manager(XuWebViewPlugin *p) {
  if (!p || !p->webview) return nullptr;
  ICoreWebView2_2 *v2 = nullptr;
  if (FAILED(p->webview->QueryInterface(IID_ICoreWebView2_2, (void **)&v2)) || !v2)
    return nullptr;
  ICoreWebView2CookieManager *cm = nullptr;
  v2->get_CookieManager(&cm);
  v2->Release();
  return cm;
}

static void drain_eval(XuWebViewPlugin *p) {
  if (!p || !p->ready) return;
  char js[256 * 1024];
  host_read_raw(p, "xu_ui_eval.js", js, sizeof(js));
  // Trim trailing whitespace
  size_t L = strlen(js);
  while (L > 0 && (js[L - 1] == '\n' || js[L - 1] == '\r' || js[L - 1] == ' ')) js[--L] = 0;
  if (!js[0]) return;
  host_write(p, "xu_ui_eval.js", "");
  char want[32];
  host_read_trim(p, "xu_ui_eval_want.txt", want, sizeof(want));
  host_write(p, "xu_ui_eval_want.txt", "");
  eval_raw(p, js, want[0] == '1');
}

static void drain_page(XuWebViewPlugin *p) {
  if (!p || !p->ready || !p->webview) return;
  char url[8192], html[256 * 1024];
  host_read_trim(p, "xu_ui_page.url", url, sizeof(url));
  host_read_raw(p, "xu_ui_page.html", html, sizeof(html));
  if (url[0] && p->last_url != url) {
    p->last_url = url;
    p->last_html.clear();
    std::wstring wu;
    utf8_to_wide(url, wu);
    p->webview->Navigate(wu.c_str());
    return;
  }
  if (html[0] && p->last_html != html) {
    p->last_html = html;
    p->last_url.clear();
    std::wstring wh;
    utf8_to_wide(html, wh);
    p->webview->NavigateToString(wh.c_str());
  }
}

static void clear_cache(XuWebViewPlugin *p) {
  if (!p || !p->webview) return;
  ICoreWebView2CookieManager *cm = get_cookie_manager(p);
  if (cm) {
    cm->DeleteAllCookies();
    cm->Release();
  }
  // Best-effort CDP cache clear (handler optional on some runtimes — skip if awkward).
  host_event(p, "cache_cleared");
}

static void cookies_clear(XuWebViewPlugin *p) {
  ICoreWebView2CookieManager *cm = get_cookie_manager(p);
  if (cm) {
    cm->DeleteAllCookies();
    cm->Release();
  }
  host_event(p, "cookies_cleared");
  eval_raw(p, "var el=document.getElementById('out');if(el)el.textContent='cookies cleared';",
           false);
}

static void cookies_get(XuWebViewPlugin *p) {
  ICoreWebView2CookieManager *cm = get_cookie_manager(p);
  if (!cm) {
    host_write(p, "xu_ui_cookies.txt", "");
    return;
  }
  auto *h = new CookiesHandler(p);
  cm->GetCookies(nullptr, h);
  h->Release();
  cm->Release();
}

static void cookie_set(XuWebViewPlugin *p) {
  char raw[4096];
  host_read_trim(p, "xu_ui_cookie_set.txt", raw, sizeof(raw));
  // name\tvalue[\tdomain]
  char *name = raw;
  char *value = nullptr;
  char *domain = nullptr;
  char *t1 = strchr(raw, '\t');
  if (t1) {
    *t1 = 0;
    value = t1 + 1;
    char *t2 = strchr(value, '\t');
    if (t2) {
      *t2 = 0;
      domain = t2 + 1;
    }
  }
  if (!name[0] || !value) return;
  if (!domain || !domain[0]) domain = (char *)"127.0.0.1";
  ICoreWebView2CookieManager *cm = get_cookie_manager(p);
  if (!cm) return;
  std::wstring wn, wv, wd;
  utf8_to_wide(name, wn);
  utf8_to_wide(value, wv);
  utf8_to_wide(domain, wd);
  ICoreWebView2Cookie *c = nullptr;
  if (SUCCEEDED(cm->CreateCookie(wn.c_str(), wv.c_str(), wd.c_str(), L"/", &c)) && c) {
    cm->AddOrUpdateCookie(c);
    c->Release();
    std::string ev = std::string("cookie_set\t") + name;
    host_event(p, ev.c_str());
    char js[256];
    snprintf(js, sizeof(js),
             "var el=document.getElementById('out');if(el)el.textContent='cookie set: %s';", name);
    eval_raw(p, js, false);
  }
  cm->Release();
}

static void apply_bgcolor(XuWebViewPlugin *p, const char *hex) {
  if (!p || !hex) return;
  while (*hex == '#' || *hex == ' ') hex++;
  unsigned r = 0, g = 0, b = 0;
  if (strlen(hex) >= 6) sscanf(hex, "%02x%02x%02x", &r, &g, &b);
  ICoreWebView2Controller2 *c2 = nullptr;
  if (p->controller &&
      SUCCEEDED(p->controller->QueryInterface(IID_ICoreWebView2Controller2, (void **)&c2)) && c2) {
    COREWEBVIEW2_COLOR col;
    col.A = 255;
    col.R = (BYTE)r;
    col.G = (BYTE)g;
    col.B = (BYTE)b;
    c2->put_DefaultBackgroundColor(col);
    c2->Release();
  }
  char js[512];
  snprintf(js, sizeof(js),
           "(function(){var s=document.getElementById('__xu_bg_css');if(!s){s=document.createElement("
           "'style');s.id='__xu_bg_css';document.documentElement.appendChild(s);}s.textContent="
           "'html,body{background:#%02x%02x%02x !important;background-image:none !important}';"
           "var el=document.getElementById('out');if(el)el.textContent='bg #%02x%02x%02x';})();",
           r, g, b, r, g, b);
  eval_raw(p, js, false);
}

static void find_in_page(XuWebViewPlugin *p) {
  char text[4096];
  host_read_trim(p, "xu_ui_find.txt", text, sizeof(text));
  if (!text[0]) {
    host_write(p, "xu_ui_find_result.txt", "0");
    eval_raw(p, "if(window.getSelection){var s=window.getSelection();if(s)s.removeAllRanges();}",
             false);
    return;
  }
  // Escape for JS string.
  std::string esc;
  for (const char *c = text; *c; c++) {
    if (*c == '\\' || *c == '\'') {
      esc.push_back('\\');
      esc.push_back(*c);
    } else if (*c == '\n') {
      esc += "\\n";
    } else {
      esc.push_back(*c);
    }
  }
  std::string js = "window.find('" + esc + "',false,false,true,false,false,false)";
  // Use eval with result want via temp — write result asynchronously.
  std::wstring wjs;
  utf8_to_wide(js.c_str(), wjs);
  struct FindHandler
      : public ComHandler<ICoreWebView2ExecuteScriptCompletedHandler,
                          &IID_ICoreWebView2ExecuteScriptCompletedHandler> {
    std::shared_ptr<XuPluginLife> life;
    explicit FindHandler(XuWebViewPlugin *p) : life(p->life) {}
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT errorCode, LPCWSTR resultObjectAsJson) override {
    auto *plugin=life->plugin;if(!plugin)return S_OK;
      const char *v = "0";
      if (SUCCEEDED(errorCode) && resultObjectAsJson) {
        std::string s;
        wide_to_utf8(resultObjectAsJson, s);
        if (s == "true") v = "1";
      }
      if (plugin) host_write(plugin, "xu_ui_find_result.txt", v);
      return S_OK;
    }
  };
  auto *h = new FindHandler(p);
  p->webview->ExecuteScript(wjs.c_str(), h);
  h->Release();
}

static void inject_css(XuWebViewPlugin *p) {
  char css[256 * 1024];
  host_read_raw(p, "xu_ui_inject.css", css, sizeof(css));
  if (!css[0]) return;
  std::string esc;
  for (const char *c = css; *c; c++) {
    if (*c == '\\' || *c == '`' || *c == '$') {
      esc.push_back('\\');
      esc.push_back(*c);
    } else {
      esc.push_back(*c);
    }
  }
  std::string js =
      "(function(){var s=document.getElementById('__xu_inject_css');if(!s){s=document.createElement("
      "'style');s.id='__xu_inject_css';document.documentElement.appendChild(s);}s.textContent=`" +
      esc + "`;})();";
  eval_raw(p, js.c_str(), false);
}

static void set_ua(XuWebViewPlugin *p) {
  char ua[2048];
  host_read_trim(p, "xu_ui_ua.txt", ua, sizeof(ua));
  ICoreWebView2Settings *settings = nullptr;
  if (!p->webview || FAILED(p->webview->get_Settings(&settings)) || !settings) return;
  ICoreWebView2Settings2 *s2 = nullptr;
  if (SUCCEEDED(settings->QueryInterface(IID_ICoreWebView2Settings2, (void **)&s2)) && s2) {
    std::wstring wua;
    utf8_to_wide(ua, wua);
    s2->put_UserAgent(wua.c_str());
    s2->Release();
  }
  settings->Release();
}

static void set_context_menu(XuWebViewPlugin *p, bool on) {
  p->context_menu = on;
  ICoreWebView2Settings *settings = nullptr;
  if (p->webview && SUCCEEDED(p->webview->get_Settings(&settings)) && settings) {
    // Takes effect only after the next top-level navigation (WebView2 quirk).
    settings->put_AreDefaultContextMenusEnabled(on ? TRUE : FALSE);
    settings->Release();
  }
  // Immediate parity with macOS: JS preventDefault (settings alone are not live).
  char js[768];
  snprintf(js, sizeof(js),
           "(function(){"
           "window.__XU_CTX__=%s;"
           "if(!window.__XU_CTX_HOOK__){"
           "window.__XU_CTX_HOOK__=true;"
           "document.addEventListener('contextmenu',function(e){"
           "if(!window.__XU_CTX__){e.preventDefault();e.stopPropagation();}"
           "},true);"
           "}"
           "var el=document.getElementById('out');"
           "if(el)el.textContent='context menu %s';"
           "})();",
           on ? "true" : "false", on ? "on" : "off");
  eval_raw(p, js, false);
}

static void set_muted(XuWebViewPlugin *p, bool muted) {
  p->media_muted = muted;
  const char *flag = muted ? "true" : "false";
  const char *label = muted ? "muted" : "unmuted";
  char js[1024];
  snprintf(js, sizeof(js),
           "(function(){window.__XU_MUTED__=%s;document.querySelectorAll('video,audio').forEach("
           "function(e){e.muted=%s;e.defaultMuted=%s;e.volume=%s;});"
           "var b=document.getElementById('xu_mute_badge');if(b){b.textContent='%s';"
           "b.style.background=%s;b.style.opacity='1';}"
           "var el=document.getElementById('out');if(el)el.textContent='%s';})();",
           flag, flag, flag, muted ? "0" : "1", label, muted ? "'#7f1d1d'" : "'#14532d'", label);
  eval_raw(p, js, false);
}

static bool native_web_request(XuWebViewPlugin *p,const char *command){
 uint64_t id=0;unsigned kind=0;std::string value;if(!xu_web_native_take(command,p->host.canvas_id,p->host.canvas_generation,&id,&kind,&value))return false;
 if(!kind)return true;if(!p->ready||!p->webview){xu_web_native_complete(id,false,"WebView is not ready");return true;}
 if(p->life->native_queries>=XU_UI_REQUEST_MAX_PENDING){xu_web_native_complete(id,false,"native query capacity exceeded");return true;}
 if(kind==8||kind==9){auto script=kind==9?"(function(){return window.find("+xu_web_json(value)+")?1:0;})()":value;
  std::wstring wide;utf8_to_wide(script.c_str(),wide);auto *handler=new EvalHandler(p,true,id);HRESULT hr=p->webview->ExecuteScript(wide.c_str(),handler);handler->Release();if(FAILED(hr))xu_web_native_complete(id,false,"JavaScript evaluation failed");return true;}
 auto *manager=get_cookie_manager(p);if(!manager){xu_web_native_complete(id,false,"cookie manager unavailable");return true;}
 if(kind==10){auto *handler=new CookiesHandler(p,id);HRESULT hr=manager->GetCookies(NULL,handler);handler->Release();if(FAILED(hr))xu_web_native_complete(id,false,"cookie read failed");}
 else if(kind==12)xu_web_native_complete(id,SUCCEEDED(manager->DeleteAllCookies()),"");
 else{std::string name,text,domain;if(!xu_web_cookie_fields(value,&name,&text,&domain))xu_web_native_complete(id,false,"invalid cookie fields");
  else {std::wstring wn,wv,wd;utf8_to_wide(name.c_str(),wn);utf8_to_wide(text.c_str(),wv);utf8_to_wide(domain.c_str(),wd);ICoreWebView2Cookie *cookie=NULL;
   HRESULT hr=manager->CreateCookie(wn.c_str(),wv.c_str(),wd.c_str(),L"/",&cookie);if(SUCCEEDED(hr)&&cookie){hr=manager->AddOrUpdateCookie(cookie);cookie->Release();}xu_web_native_complete(id,SUCCEEDED(hr),"");}}
 manager->Release();return true;
}

static int plugin_handle_cmd(XuWebViewPlugin *p, const char *cmd) {
  if(p && native_web_request(p,cmd))return 1;
  if(p && !strncmp(cmd,"__web_reply\t",12)){xu_invoke_poll(p);return 1;}
  if (!p || !cmd) return 0;
  if (strcmp(cmd, "reload") == 0) {
    if (p->webview) p->webview->Reload();
    return 1;
  }
  if (strcmp(cmd, "back") == 0) {
    if (p->webview) {
      BOOL can = FALSE;
      p->webview->get_CanGoBack(&can);
      if (can) p->webview->GoBack();
    }
    return 1;
  }
  if (strcmp(cmd, "forward") == 0) {
    if (p->webview) {
      BOOL can = FALSE;
      p->webview->get_CanGoForward(&can);
      if (can) p->webview->GoForward();
    }
    return 1;
  }
  if (strcmp(cmd, "stop") == 0) {
    if (p->webview) p->webview->Stop();
    return 1;
  }
  if (strcmp(cmd, "print") == 0) {
    eval_raw(p, "window.print()", false);
    return 1;
  }
  if (strcmp(cmd, "clear_cache") == 0) {
    clear_cache(p);
    return 1;
  }
  if (strcmp(cmd, "cookies_get") == 0) {
    cookies_get(p);
    return 1;
  }
  if (strcmp(cmd, "cookies_clear") == 0) {
    cookies_clear(p);
    return 1;
  }
  if (strcmp(cmd, "cookie_set") == 0) {
    cookie_set(p);
    return 1;
  }
  if (strncmp(cmd, "magnify\t", 8) == 0) {
    p->magnify = cmd[8] != '0';
    ICoreWebView2Settings *settings = nullptr;
    if (p->webview && SUCCEEDED(p->webview->get_Settings(&settings)) && settings) {
      settings->put_IsZoomControlEnabled(p->magnify ? TRUE : FALSE);
      settings->Release();
    }
    if (!p->magnify && p->controller) p->controller->put_ZoomFactor(1.0);
    return 1;
  }
  if (strcmp(cmd, "mute") == 0) {
    set_muted(p, true);
    return 1;
  }
  if (strcmp(cmd, "unmute") == 0) {
    set_muted(p, false);
    return 1;
  }
  if (strncmp(cmd, "bgcolor\t", 8) == 0) {
    apply_bgcolor(p, cmd + 8);
    return 1;
  }
  if (strncmp(cmd, "context_menu\t", 13) == 0) {
    set_context_menu(p, cmd[13] != '0');
    return 1;
  }
  if (strcmp(cmd, "find") == 0) {
    find_in_page(p);
    return 1;
  }
  if (strcmp(cmd, "find_clear") == 0) {
    host_write(p, "xu_ui_find_result.txt", "0");
    eval_raw(p, "if(window.getSelection){var s=window.getSelection();if(s)s.removeAllRanges();}",
             false);
    return 1;
  }
  if (strcmp(cmd, "inject_css") == 0) {
    inject_css(p);
    return 1;
  }
  if (strcmp(cmd, "set_ua") == 0) {
    set_ua(p);
    return 1;
  }
  if (strcmp(cmd, "devtools") == 0) {
    if (p->webview) p->webview->OpenDevToolsWindow();
    return 1;
  }
  if (strncmp(cmd, "zoom\t", 5) == 0) {
    double z = atof(cmd + 5);
    if (z > 0.1 && z < 10.0 && p->controller) p->controller->put_ZoomFactor(z);
    return 1;
  }
  return 0;
}

static void plugin_on_poll(XuWebViewPlugin *p) {
  if (!p) return;
  xu_invoke_poll(p);
  drain_eval(p);
  drain_page(p);
  // The unscoped compatibility bus belongs to the primary window only.
  if(p->host.window_id==1)for(unsigned i=0;i<16;++i){auto event=xu_ipc_poll(p);if(event.empty())break;
    auto script="window.__XU__&&window.__XU__._accept&&window.__XU__._accept("+xu_web_json(event)+");";
    eval_raw(p,script.c_str(),false);
  }

}

static void plugin_sync_frame(XuWebViewPlugin *p) {
  if (!p || !p->child) return;
  HWND parent = GetParent(p->child);
  if (!parent) return;
  RECT rc;
  GetClientRect(parent, &rc);
  SetWindowPos(p->child, NULL, 0, 0, rc.right - rc.left, rc.bottom - rc.top,
               SWP_NOZORDER | SWP_NOACTIVATE);
  sync_bounds(p);
}

static void plugin_eval_js(XuWebViewPlugin *p, const char *js) {
  eval_raw(p, js, false);
}

static const XuContentVTable g_webview_vtable = {
  [](XuContentHost *host)->XuContentPlugin *{return reinterpret_cast<XuContentPlugin *>(plugin_create(host));},
  [](XuContentPlugin *p){plugin_destroy(reinterpret_cast<XuWebViewPlugin *>(p));},
  [](XuContentPlugin *p){plugin_install(reinterpret_cast<XuWebViewPlugin *>(p));},
  [](XuContentPlugin *p,const char *text)->int{return plugin_handle_cmd(reinterpret_cast<XuWebViewPlugin *>(p),text);},
  [](XuContentPlugin *p){plugin_on_poll(reinterpret_cast<XuWebViewPlugin *>(p));},
  [](XuContentPlugin *p){plugin_sync_frame(reinterpret_cast<XuWebViewPlugin *>(p));},
  [](XuContentPlugin *p,const char *text){plugin_eval_js(reinterpret_cast<XuWebViewPlugin *>(p),text);},
};

extern "C" const XuContentVTable *xu_webview_plugin_vtable(void) { return &g_webview_vtable; }
