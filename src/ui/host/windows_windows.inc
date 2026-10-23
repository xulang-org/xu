// Each secondary top-level HWND owns its plugin; the primary HWND owns the pump.
struct XuWinWindow {
  unsigned id=0,generation=0;
  HWND window=NULL;
  XuContentHost host={};
  XuContentPlugin *content=NULL;
  const XuContentVTable *vt=NULL;
  bool closing=false,close_guard=false,fullscreen=false;
  RECT restore={};
  DWORD restore_style=WS_OVERLAPPEDWINDOW;
  int min_width=0,min_height=0;
};
static XuWinWindow g_extra_windows[XU_UI_WINDOW_MAX_COUNT-1];
static XuWinWindow *extra_find(unsigned id,unsigned generation) {
  for(auto &w:g_extra_windows)if(w.id==id && w.generation==generation && !w.closing)return &w;
  return NULL;
}
static const XuContentVTable *content_kind_vtable(unsigned kind) {
  if(kind==1 && xu_webview_plugin_vtable)return xu_webview_plugin_vtable();
  if(kind==2 && xu_draw_plugin_vtable)return xu_draw_plugin_vtable();
  return NULL;
}
static void extra_install(XuWinWindow &w) {
  if(w.content || w.closing)return;unsigned meta[6];if(!xu_ui_window_info(w.id,w.generation,meta,NULL,0))return;
  w.vt=content_kind_vtable(meta[4]);if(!w.vt || !w.vt->create || !w.vt->install)return;
  w.content=w.vt->create(&w.host);if(w.content)w.vt->install(w.content);
}
static void extra_close(XuWinWindow &w,bool force=false) {
  if(!w.id || w.closing)return;
  if(w.close_guard && !force){xu_ui_window_event(w.id,w.generation,"close_requested");return;}
  w.closing=true;unsigned id=w.id,generation=w.generation;
  native_menu_close(w.window);
  desktop_files_close_owner(id,generation);
  if(w.content && w.vt && w.vt->destroy)w.vt->destroy(w.content);w.content=NULL;
  xu_ui_window_closed(id,generation);xu_ui_window_event(id,generation,"closed");
  if(desktop_files_owner_idle(id,generation)){if(IsWindow(w.window))DestroyWindow(w.window);w={};}
  else ShowWindow(w.window,SW_HIDE);
  if(g_root_closed && !xu_ui_window_count())do_quit();
}
static LRESULT CALLBACK ExtraWndProc(HWND hwnd,UINT message,WPARAM wp,LPARAM lp) {
  auto *w=(XuWinWindow *)GetWindowLongPtrW(hwnd,GWLP_USERDATA);
  if(message==WM_NCCREATE){w=(XuWinWindow *)((CREATESTRUCTW *)lp)->lpCreateParams;w->window=hwnd;SetWindowLongPtrW(hwnd,GWLP_USERDATA,(LONG_PTR)w);}
  if(w && !w->closing){
    if(message==WM_COMMAND && native_menu_command(hwnd,LOWORD(wp)))return 0;
    if(message==WM_CLOSE){extra_close(*w);return 0;}
    if(message==WM_GETMINMAXINFO){
      auto *limits=(MINMAXINFO *)lp;
      if(w->min_width || w->min_height){SIZE size=xu_ui_outer_for_client(hwnd,w->min_width,w->min_height,(DWORD)GetWindowLongPtrW(hwnd,GWL_STYLE),(DWORD)GetWindowLongPtrW(hwnd,GWL_EXSTYLE),FALSE);limits->ptMinTrackSize.x=size.cx;limits->ptMinTrackSize.y=size.cy;}
      return 0;
    }
    if(message==WM_SETFOCUS || message==WM_KILLFOCUS)xu_ui_window_event(w->id,w->generation,message==WM_SETFOCUS?"focused":"blurred");
    if(message==WM_SIZE){if(w->content && w->vt && w->vt->sync_frame)w->vt->sync_frame(w->content);
      char event[80];double scale=xu_ui_window_scale(hwnd);RECT client={};GetClientRect(hwnd,&client);snprintf(event,sizeof(event),"resized\t%d\t%d",(int)((client.right-client.left)/scale),(int)((client.bottom-client.top)/scale));xu_ui_window_event(w->id,w->generation,event);return 0;}
    if(message==WM_DPICHANGED){const RECT *r=(const RECT *)lp;if(r)SetWindowPos(hwnd,NULL,r->left,r->top,r->right-r->left,r->bottom-r->top,SWP_NOACTIVATE|SWP_NOZORDER);if(w->content && w->vt && w->vt->sync_frame)w->vt->sync_frame(w->content);return 0;}
    if(message==WM_NCDESTROY){extra_close(*w,true);return 0;}
  }
  return DefWindowProcW(hwnd,message,wp,lp);
}
static void extra_open(unsigned id,unsigned generation) {
  if(!xu_ui_window_claim(id,generation))return;
  XuWinWindow *slot=NULL;for(auto &w:g_extra_windows)if(!w.id){slot=&w;break;}
  unsigned meta[6];char title[XU_UI_WINDOW_MAX_TITLE+1];
  if(!slot || !xu_ui_window_info(id,generation,meta,title,sizeof(title))){xu_ui_window_closed(id,generation);return;}
  static bool registered=false;HINSTANCE instance=GetModuleHandleW(NULL);
  if(!registered){WNDCLASSW cls={};cls.hInstance=instance;cls.lpfnWndProc=ExtraWndProc;cls.lpszClassName=L"XuUiManagedWindow";cls.hCursor=LoadCursor(NULL,IDC_ARROW);cls.hbrBackground=(HBRUSH)(COLOR_WINDOW+1);registered=RegisterClassW(&cls)!=0;}
  if(!registered){xu_ui_window_closed(id,generation);return;}
  auto &w=*slot;w.id=id;w.generation=generation;
  wchar_t wide[XU_UI_WINDOW_MAX_TITLE+1];utf8_to_wide(title,wide,XU_UI_WINDOW_MAX_TITLE+1);
  SIZE outer=outer_size_for_client((int)meta[2],(int)meta[3],WS_OVERLAPPEDWINDOW,WS_EX_APPWINDOW,FALSE);
  w.window=CreateWindowExW(WS_EX_APPWINDOW,L"XuUiManagedWindow",wide,WS_OVERLAPPEDWINDOW,CW_USEDEFAULT,CW_USEDEFAULT,outer.cx,outer.cy,NULL,NULL,instance,&w);
  if(!w.window){xu_ui_window_closed(id,generation);w={};return;}
  outer=outer_size_for_client((int)meta[2],(int)meta[3],WS_OVERLAPPEDWINDOW,WS_EX_APPWINDOW,FALSE,w.window);
  SetWindowPos(w.window,NULL,0,0,outer.cx,outer.cy,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE);
  w.host={g_tmp,w.window,w.window,append_shell_event,write_tmp,
    [](const char *n,char *out,unsigned cap){read_trim_file(n,out,cap);},
    [](const char *n,char *out,unsigned cap){read_file_raw(n,out,cap);},id,id,generation};
  extra_install(w);xu_ui_window_ready(id,generation);ShowWindow(w.window,SW_SHOW);UpdateWindow(w.window);xu_ui_window_event(id,generation,"window_ready");
}
static void extra_poll(void) {
  for(auto &w:g_extra_windows)if(w.id && w.closing && desktop_files_owner_idle(w.id,w.generation)){if(IsWindow(w.window))DestroyWindow(w.window);w={};}
  for(auto &w:g_extra_windows)if(w.id && !w.closing && w.content && w.vt){if(w.vt->on_poll)w.vt->on_poll(w.content);if(w.vt->sync_frame)w.vt->sync_frame(w.content);}
}
static bool extra_dispatch(const char *line) {
  unsigned id=0,generation=0;char tail=0;
  if(sscanf(line,"__window_open\t%u\t%u%c",&id,&generation,&tail)==2){extra_open(id,generation);return true;}
  if(sscanf(line,"__window_bind\t%u\t%u%c",&id,&generation,&tail)==2){
    if(id==1 && !g_root_closed){if(!g_content)maybe_install_content_plugin();}
    else if(auto *w=extra_find(id,generation))extra_install(*w);return true;
  }
  const char *raw=line;unsigned identity[2]={};bool scoped=xu_ui_scoped_command(line,identity,&raw);
  if(!scoped && !strncmp(line,"window\t",7))return true;
  bool marker=!scoped && xu_ui_command_owner(line,identity);
  if(!scoped && !marker)return false;
  if(identity[0]==1){unsigned meta[6];return g_root_closed || (scoped && !xu_ui_window_info(1,identity[1],meta,NULL,0));}
  const char *cmd=strip_prefix(raw);auto *w=extra_find(identity[0],identity[1]);bool content=!strncmp(raw,"content.",8) || !strncmp(raw,"wv.",3);
  if(w){
    if(content){if(!desktop_screens(cmd,w->id,w->generation,w->window) && !desktop_files(cmd,w->id,w->generation,w->window) && !desktop_clipboard(cmd,w->id,w->generation) && w->content && w->vt && w->vt->handle_cmd)w->vt->handle_cmd(w->content,cmd);}
    else if(!strcmp(cmd,"menu_v2"))native_menu_install(w->window,w->id,w->generation);
    else if(!strcmp(cmd,"show")){ShowWindow(w->window,SW_SHOW);SetForegroundWindow(w->window);}
    else if(!strcmp(cmd,"hide"))ShowWindow(w->window,SW_HIDE);
    else if(!strcmp(cmd,"close") || !strcmp(cmd,"quit"))extra_close(*w);
    else if(!strcmp(cmd,"accept_close"))extra_close(*w,true);
    else if(!strcmp(cmd,"reject_close"))xu_ui_window_event(w->id,w->generation,"close_rejected");
    else if(!strncmp(cmd,"title\t",6)){wchar_t title[XU_UI_WINDOW_MAX_TITLE+1];utf8_to_wide(cmd+6,title,XU_UI_WINDOW_MAX_TITLE+1);SetWindowTextW(w->window,title);}
    else if(!strncmp(cmd,"size\t",5)){int width=0,height=0;if(sscanf(cmd+5,"%d\t%d%c",&width,&height,&tail)==2 && width>=40 && height>=40 && width<=16384 && height<=16384){SIZE size=outer_size_for_client(width,height,(DWORD)GetWindowLongPtrW(w->window,GWL_STYLE),(DWORD)GetWindowLongPtrW(w->window,GWL_EXSTYLE),FALSE,w->window);SetWindowPos(w->window,NULL,0,0,size.cx,size.cy,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE);}}
    else if(!strncmp(cmd,"close_guard\t",12))w->close_guard=cmd[12]!='0';
    else if(!strcmp(cmd,"maximize"))ShowWindow(w->window,SW_MAXIMIZE);
    else if(!strcmp(cmd,"unmaximize"))ShowWindow(w->window,SW_RESTORE);
    else if(!strcmp(cmd,"minimize"))ShowWindow(w->window,SW_MINIMIZE);
    else if(!strcmp(cmd,"fullscreen")){
      if(!w->fullscreen){w->fullscreen=true;GetWindowRect(w->window,&w->restore);w->restore_style=(DWORD)GetWindowLongPtrW(w->window,GWL_STYLE);
        MONITORINFO info={};info.cbSize=sizeof(info);GetMonitorInfoW(MonitorFromWindow(w->window,MONITOR_DEFAULTTONEAREST),&info);
        SetWindowLongPtrW(w->window,GWL_STYLE,w->restore_style & ~WS_OVERLAPPEDWINDOW);
        SetWindowPos(w->window,NULL,info.rcMonitor.left,info.rcMonitor.top,info.rcMonitor.right-info.rcMonitor.left,info.rcMonitor.bottom-info.rcMonitor.top,SWP_FRAMECHANGED|SWP_NOZORDER);
      }
    }
    else if(!strcmp(cmd,"fullscreen_exit")){
      if(w->fullscreen){w->fullscreen=false;SetWindowLongPtrW(w->window,GWL_STYLE,w->restore_style);SetWindowPos(w->window,NULL,w->restore.left,w->restore.top,w->restore.right-w->restore.left,w->restore.bottom-w->restore.top,SWP_FRAMECHANGED|SWP_NOZORDER);}
    }
    else if(!strncmp(cmd,"resizable\t",10)){
      LONG_PTR style=GetWindowLongPtrW(w->window,GWL_STYLE);
      if(cmd[10]=='0')style &= ~(WS_THICKFRAME|WS_MAXIMIZEBOX);else style|=WS_THICKFRAME|WS_MAXIMIZEBOX;
      SetWindowLongPtrW(w->window,GWL_STYLE,style);SetWindowPos(w->window,NULL,0,0,0,0,SWP_FRAMECHANGED|SWP_NOMOVE|SWP_NOSIZE|SWP_NOZORDER);
    }
    else if(!strncmp(cmd,"minsize\t",8)){
      int width=0,height=0;if(sscanf(cmd+8,"%d\t%d%c",&width,&height,&tail)==2 && width>=0 && height>=0 && width<=16384 && height<=16384){w->min_width=width;w->min_height=height;}
    }
    else if(!strcmp(cmd,"float") || !strcmp(cmd,"unfloat"))SetWindowPos(w->window,!strcmp(cmd,"float")?HWND_TOPMOST:HWND_NOTOPMOST,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE);
    else if(!strcmp(cmd,"center")){
      MONITORINFO info={};info.cbSize=sizeof(info);GetMonitorInfoW(MonitorFromWindow(w->window,MONITOR_DEFAULTTONEAREST),&info);RECT bounds={};GetWindowRect(w->window,&bounds);
      SetWindowPos(w->window,NULL,info.rcWork.left+((info.rcWork.right-info.rcWork.left)-(bounds.right-bounds.left))/2,info.rcWork.top+((info.rcWork.bottom-info.rcWork.top)-(bounds.bottom-bounds.top))/2,0,0,SWP_NOSIZE|SWP_NOZORDER);
    }
    else if(!strncmp(cmd,"position\t",9)){int x=0,y=0;if(sscanf(cmd+9,"%d\t%d%c",&x,&y,&tail)==2)SetWindowPos(w->window,NULL,x,y,0,0,SWP_NOSIZE|SWP_NOZORDER);}
    else xu_ui_window_event(w->id,w->generation,"command_unsupported");
  }
  if(content){xu_ui_draw_discard_marker(cmd);xu_ui_request_discard_marker(cmd);}return true;
}
