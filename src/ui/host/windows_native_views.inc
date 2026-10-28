// Real child HWNDs; the clipped outer panel never changes the page viewport.
struct XuWinNativeView {
  unsigned id=0,generation=0,parent=0,parent_generation=0,focus_epoch=0;
  HWND outer=NULL,inner=NULL,window=NULL;
  XuContentHost host={};XuContentPlugin *content=NULL;const XuContentVTable *vt=NULL;
  bool focused=false,applied=false;unsigned applied_flags=0;double geometry_cache[12]={};
};
static XuWinNativeView g_native_children[XU_UI_NATIVE_VIEW_MAX_COUNT];
static XuWinNativeView *native_child_find(unsigned id,unsigned generation) {
  for(auto &v:g_native_children)if(v.id==id&&v.generation==generation)return &v;return NULL;
}
static void native_return_focus(XuWinNativeView &v) {
  HWND canvas=FindWindowExW(v.window,NULL,L"XuDrawCanvas",NULL);SetFocus(canvas?canvas:v.window);
}
static bool native_owns_focus(const XuWinNativeView &v) {HWND focused=GetFocus();return focused&&(focused==v.outer||IsChild(v.outer,focused));}
static void native_child_close(XuWinNativeView &v) {
  if(!v.id)return;if(native_owns_focus(v))native_return_focus(v);
  if(v.content&&v.vt&&v.vt->destroy)v.vt->destroy(v.content);
  if(IsWindow(v.outer))DestroyWindow(v.outer);v={};
}
static void native_children_close_parent(unsigned parent,unsigned generation) {
  for(auto &v:g_native_children)if(v.id&&v.parent==parent&&v.parent_generation==generation)native_child_close(v);
}
static void native_child_update(XuWinNativeView &v) {
  unsigned m[8];double g[9];if(!xu_ui_native_view_info(v.id,v.generation,m,g))return;
  double scale=xu_ui_window_scale(v.window);RECT client={};GetClientRect(v.window,&client);
  double key[12];memcpy(key,g,72);key[9]=scale;key[10]=client.right;key[11]=client.bottom;
  bool changed=!v.applied||v.applied_flags!=(m[6]&3)||memcmp(v.geometry_cache,key,sizeof(key));
  if(changed){v.applied=true;v.applied_flags=m[6]&3;memcpy(v.geometry_cache,key,sizeof(key));}
  RECT full={(LONG)lround(g[0]*scale),(LONG)lround(g[1]*scale),(LONG)lround((g[0]+g[2])*scale),(LONG)lround((g[1]+g[3])*scale)};
  RECT requested={(LONG)ceil(g[4]*scale),(LONG)ceil(g[5]*scale),(LONG)floor((g[4]+g[6])*scale),(LONG)floor((g[5]+g[7])*scale)},clip={};
  IntersectRect(&clip,&full,&requested);IntersectRect(&clip,&clip,&client);
  bool visible=(m[6]&1)&&!IsRectEmpty(&clip);bool enabled=(m[6]&2)!=0;
  if((!visible||!enabled)&&native_owns_focus(v))native_return_focus(v);
  if(changed&&visible){SetWindowPos(v.outer,HWND_TOP,clip.left,clip.top,clip.right-clip.left,clip.bottom-clip.top,SWP_NOACTIVATE);
    SetWindowPos(v.inner,NULL,full.left-clip.left,full.top-clip.top,full.right-full.left,full.bottom-full.top,SWP_NOZORDER|SWP_NOACTIVATE);
    int radius=(int)lround(g[8]*scale);SetWindowRgn(v.inner,radius?CreateRoundRectRgn(0,0,full.right-full.left+1,full.bottom-full.top+1,radius*2,radius*2):NULL,TRUE);}
  if(changed){EnableWindow(v.outer,enabled);ShowWindow(v.outer,visible?SW_SHOWNOACTIVATE:SW_HIDE);}
  if(v.focus_epoch!=m[7]&&(!(m[6]&4)||(visible&&enabled))){v.focus_epoch=m[7];if((m[6]&4)&&visible&&enabled){if(v.vt&&v.vt->handle_cmd)v.vt->handle_cmd(v.content,"native_focus");}else if(native_owns_focus(v))native_return_focus(v);}
  if(changed&&v.content&&v.vt&&v.vt->sync_frame)v.vt->sync_frame(v.content);
}
static void native_child_open(unsigned parent,unsigned parent_generation,unsigned id,unsigned generation) {
  if(native_child_find(id,generation))return;unsigned m[8];if(!xu_ui_native_view_info(id,generation,m,NULL)||m[2]!=parent||m[3]!=parent_generation)return;
  HWND window=parent==1&&g_root_generation==parent_generation&&!g_root_closed?g_hwnd:NULL;
  if(!window){auto *owner=extra_find(parent,parent_generation);if(owner)window=owner->window;}
  auto *vt=content_kind_vtable(1);XuWinNativeView *slot=NULL;for(auto &v:g_native_children)if(!v.id){slot=&v;break;}
  if(!window||!vt||!vt->create||!vt->install||!slot){xu_ui_native_view_event(id,generation,"load_failed\tWebView backend unavailable");xu_ui_native_view_close(id,generation);return;}
  auto &v=*slot;v.id=id;v.generation=generation;v.parent=parent;v.parent_generation=parent_generation;v.window=window;v.vt=vt;
  v.outer=CreateWindowExW(0,L"STATIC",L"",WS_CHILD|WS_CLIPCHILDREN|WS_CLIPSIBLINGS,0,0,0,0,window,NULL,GetModuleHandleW(NULL),NULL);
  v.inner=CreateWindowExW(0,L"STATIC",L"",WS_CHILD|WS_VISIBLE|WS_CLIPCHILDREN,0,0,0,0,v.outer,NULL,GetModuleHandleW(NULL),NULL);
  if(!v.outer||!v.inner){native_child_close(v);xu_ui_native_view_event(id,generation,"load_failed\tNative WebView container creation failed");xu_ui_native_view_close(id,generation);return;}
  v.host={g_tmp,window,v.inner,append_shell_event,write_tmp,[](const char *n,char *out,unsigned cap){read_trim_file(n,out,cap);},[](const char *n,char *out,unsigned cap){read_file_raw(n,out,cap);},parent,id,generation};
  v.content=vt->create(&v.host);if(!v.content){native_child_close(v);xu_ui_native_view_event(id,generation,"load_failed\tWebView creation failed");xu_ui_native_view_close(id,generation);return;}
  vt->install(v.content);native_child_update(v);xu_ui_native_view_ready(id,generation);
}
static void native_children_poll(void) {
  for(auto &v:g_native_children)if(v.id){if(!xu_ui_native_view_info(v.id,v.generation,NULL,NULL)){native_child_close(v);continue;}native_child_update(v);
    if(v.content&&v.vt&&v.vt->on_poll)v.vt->on_poll(v.content);bool focused=native_owns_focus(v);if(focused!=v.focused){v.focused=focused;xu_ui_native_view_event(v.id,v.generation,focused?"focused":"blurred");}}
}
static bool native_children_key(MSG *msg) {
  if(msg->message!=WM_KEYDOWN||msg->wParam!=VK_TAB||GetKeyState(VK_CONTROL)>=0)return false;
  for(auto &v:g_native_children)if(v.id&&native_owns_focus(v)){native_return_focus(v);xu_ui_native_view_event(v.id,v.generation,GetKeyState(VK_SHIFT)<0?"focus_previous":"focus_next");return true;}return false;
}
static bool native_children_dispatch(const char *line) {
  unsigned parent=0,parent_generation=0,id=0,generation=0;char tail=0;
  if(sscanf(line,"__view_create\t%u\t%u\t%u\t%u%c",&parent,&parent_generation,&id,&generation,&tail)==4){native_child_open(parent,parent_generation,id,generation);return true;}
  if(sscanf(line,"__view_update\t%u\t%u\t%u\t%u%c",&parent,&parent_generation,&id,&generation,&tail)==4){if(auto *v=native_child_find(id,generation))native_child_update(*v);return true;}
  if(sscanf(line,"__view_close\t%u\t%u\t%u\t%u%c",&parent,&parent_generation,&id,&generation,&tail)==4){if(auto *v=native_child_find(id,generation))native_child_close(*v);return true;}
  const char *raw=line;XuWinNativeView *v=NULL;int offset=0;
  if(!strncmp(line,"view\t",5)){if(sscanf(line,"view\t%u\t%u\t%u\t%n",&parent,&id,&generation,&offset)!=3||!offset)return true;v=native_child_find(id,generation);if(v&&v->parent!=parent)v=NULL;raw=line+offset;}
  else {unsigned owner[2]={};if(!xu_ui_command_owner(line,owner))return false;for(auto &candidate:g_native_children)if(candidate.id&&candidate.parent==owner[0]&&candidate.generation==owner[1]){v=&candidate;break;}if(!v)return false;}
  const char *command=strip_prefix(raw);if(v&&xu_ui_native_view_info(v->id,v->generation,NULL,NULL)&&v->content&&v->vt&&v->vt->handle_cmd)v->vt->handle_cmd(v->content,command);
  xu_ui_draw_discard_marker(command);xu_ui_request_discard_marker(command);return true;
}
