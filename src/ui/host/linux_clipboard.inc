// Bounded streaming clipboard reads. Callback state owns GObjects and a request
// ID only; it never retains a host, window arena slot or content plugin pointer.
#include <memory>
#include <algorithm>
#include <unordered_map>
struct XuClipboardRead {
  uint64_t id;
  GCancellable *cancel=g_cancellable_new();
  GInputStream *stream=NULL;
  std::string text;
  explicit XuClipboardRead(uint64_t value):id(value){}
  ~XuClipboardRead(){if(stream)g_object_unref(stream);g_object_unref(cancel);}
};
using XuClipboardReadRef=std::shared_ptr<XuClipboardRead>;
static std::unordered_map<uint64_t,XuClipboardReadRef> g_clipboard_reads;
static void clipboard_finish(const XuClipboardReadRef &op,unsigned status) {
  xu_ui_request_complete(op->id,status,op->text.data(),(unsigned)op->text.size());
  if(op->stream)g_input_stream_close_async(op->stream,G_PRIORITY_DEFAULT,NULL,NULL,NULL);
  g_clipboard_reads.erase(op->id);
}
static void clipboard_next(const XuClipboardReadRef &op);
static void clipboard_bytes(GObject *source,GAsyncResult *result,gpointer data) {
  std::unique_ptr<XuClipboardReadRef> holder((XuClipboardReadRef *)data);auto op=*holder;
  GError *error=NULL;GBytes *bytes=g_input_stream_read_bytes_finish(G_INPUT_STREAM(source),result,&error);
  if(!bytes || !xu_ui_request_alive(op->id)) {
    if(bytes)g_bytes_unref(bytes);if(error)g_error_free(error);clipboard_finish(op,XU_REQUEST_FAILED);return;
  }
  gsize size=0;const char *body=(const char *)g_bytes_get_data(bytes,&size);
  bool oversized=size>XU_UI_REQUEST_MAX_TEXT-op->text.size();
  if(!oversized && size)op->text.append(body,size);
  g_bytes_unref(bytes);
  if(oversized){op->text.clear();clipboard_finish(op,XU_REQUEST_FAILED);}
  else if(!size)clipboard_finish(op,XU_REQUEST_COMPLETED); // table validates UTF-8/NUL
  else clipboard_next(op);
}
static void clipboard_next(const XuClipboardReadRef &op) {
  // Read one byte past the limit to distinguish exactly-full from overflow.
  g_input_stream_read_bytes_async(op->stream,std::min((size_t)4096,(size_t)XU_UI_REQUEST_MAX_TEXT+1-op->text.size()),
    G_PRIORITY_DEFAULT,op->cancel,clipboard_bytes,new XuClipboardReadRef(op));
}
static void clipboard_stream(GObject *source,GAsyncResult *result,gpointer data) {
  std::unique_ptr<XuClipboardReadRef> holder((XuClipboardReadRef *)data);auto op=*holder;
  GError *error=NULL;const char *mime=NULL;
  op->stream=gdk_clipboard_read_finish(GDK_CLIPBOARD(source),result,&mime,&error);
  if(!op->stream || !xu_ui_request_alive(op->id)) {
    if(error)g_error_free(error);clipboard_finish(op,XU_REQUEST_FAILED);return;
  }
  clipboard_next(op);
}
static void desktop_clipboard_poll() {
  xu_ui_request_poll();
  // Keep a strong snapshot: a cancellation can finish an async operation.
  std::vector<XuClipboardReadRef> pending;for(auto &entry:g_clipboard_reads)pending.push_back(entry.second);
  for(auto &op:pending)if(!xu_ui_request_alive(op->id))g_cancellable_cancel(op->cancel);
}
static bool desktop_clipboard(const char *command,unsigned canvas,unsigned generation) {
  uint64_t id=0;unsigned kind=0;std::string text;
  if(!xu_request_clipboard_take(command,canvas,generation,&id,&kind,&text))return false;
  if(!kind || !xu_ui_request_alive(id))return true;
  GdkDisplay *display=gdk_display_get_default();
  if(!display){xu_ui_request_complete(id,XU_REQUEST_FAILED,"",0);return true;}
  GdkClipboard *clipboard=gdk_display_get_clipboard(display);
  if(kind==XU_REQUEST_CLIPBOARD_WRITE) {
    gdk_clipboard_set_text(clipboard,text.c_str());xu_ui_request_complete(id,XU_REQUEST_COMPLETED,"",0);
  } else if(!gdk_content_formats_contain_gtype(gdk_clipboard_get_formats(clipboard),G_TYPE_STRING) &&
      !gdk_content_formats_contain_mime_type(gdk_clipboard_get_formats(clipboard),"text/plain;charset=utf-8") &&
      !gdk_content_formats_contain_mime_type(gdk_clipboard_get_formats(clipboard),"text/plain")) {
    xu_ui_request_complete(id,XU_REQUEST_COMPLETED,"",0);
  } else if(g_clipboard_reads.size()>=XU_UI_REQUEST_MAX_PENDING)xu_ui_request_complete(id,XU_REQUEST_FAILED,"",0);
  else {
    auto op=std::make_shared<XuClipboardRead>(id);g_clipboard_reads.emplace(id,op);
    static const char *types[]={"text/plain;charset=utf-8","text/plain",NULL};
    gdk_clipboard_read_async(clipboard,types,G_PRIORITY_DEFAULT,op->cancel,clipboard_stream,new XuClipboardReadRef(op));
  }
  return true;
}
