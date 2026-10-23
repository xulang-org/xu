// Secondary GtkApplicationWindows. The primary shell owns the one command drain.
struct XuGtkWindow {
  unsigned id=0,generation=0;
  GtkWindow *window=NULL;
  GtkWidget *box=NULL;
  XuContentHost host={};
  XuContentPlugin *content=NULL;
  const XuContentVTable *vt=NULL;
  bool closing=false,close_guard=false;
};
static XuGtkWindow g_extra_windows[XU_UI_WINDOW_MAX_COUNT-1];
static XuGtkWindow *extra_find(unsigned id,unsigned generation) {
  for(auto &w:g_extra_windows)if(w.id==id && w.generation==generation && !w.closing)return &w;
  return NULL;
}
static const XuContentVTable *content_kind_vtable(unsigned kind) {
  if(kind==1 && xu_webview_plugin_vtable)return xu_webview_plugin_vtable();
  if(kind==2 && xu_draw_plugin_vtable)return xu_draw_plugin_vtable();
  return NULL;
}
static void extra_install(XuGtkWindow &w) {
  if(w.content || w.closing)return;
  unsigned meta[6];if(!xu_ui_window_info(w.id,w.generation,meta,NULL,0))return;
  w.vt=content_kind_vtable(meta[4]);if(!w.vt || !w.vt->create || !w.vt->install)return;
  w.content=w.vt->create(&w.host);if(w.content)w.vt->install(w.content);
}
static void extra_close(XuGtkWindow &w,bool force=false) {
  if(!w.id || w.closing)return;
  if(w.close_guard && !force){xu_ui_window_event(w.id,w.generation,"close_requested");return;}
  w.closing=true;unsigned id=w.id,generation=w.generation;
  native_menu_close(w.window);
  if(w.content && w.vt && w.vt->destroy)w.vt->destroy(w.content);
  w.content=NULL;gtk_window_destroy(w.window);xu_ui_window_closed(id,generation);
  xu_ui_window_event(id,generation,"closed");w={};
  if(g_root_closed && !xu_ui_window_count())do_quit();
}
static void extra_open(unsigned id,unsigned generation) {
  if(!xu_ui_window_claim(id,generation))return;
  XuGtkWindow *slot=NULL;for(auto &w:g_extra_windows)if(!w.id){slot=&w;break;}
  unsigned meta[6];char title[XU_UI_WINDOW_MAX_TITLE+1];
  if(!slot || !xu_ui_window_info(id,generation,meta,title,sizeof(title))){xu_ui_window_closed(id,generation);return;}
  auto &w=*slot;w.id=id;w.generation=generation;
  w.window=GTK_WINDOW(gtk_application_window_new(g_app));
  gtk_window_set_title(w.window,title);gtk_window_set_default_size(w.window,(int)meta[2],(int)meta[3]);
  w.box=gtk_box_new(GTK_ORIENTATION_VERTICAL,0);gtk_window_set_child(w.window,w.box);
  w.host={g_tmp,w.window,w.box,append_shell_event,write_tmp,
    [](const char *n,char *out,unsigned cap){read_trim_file(n,out,cap);},
    [](const char *n,char *out,unsigned cap){read_file_raw(n,out,cap);},id,id,generation};
  g_signal_connect(w.window,"close-request",G_CALLBACK(+[](GtkWindow *,gpointer data)->gboolean{extra_close(*(XuGtkWindow *)data);return TRUE;}),&w);
  g_signal_connect(w.window,"notify::is-active",G_CALLBACK(+[](GObject *object,GParamSpec *,gpointer data){auto &window=*(XuGtkWindow *)data;
    if(!window.closing)xu_ui_window_event(window.id,window.generation,gtk_window_is_active(GTK_WINDOW(object))?"focused":"blurred");}),&w);
  extra_install(w);xu_ui_window_ready(id,generation);gtk_window_present(w.window);xu_ui_window_event(id,generation,"window_ready");
}
static void extra_poll(void) {
  for(auto &w:g_extra_windows)if(w.id && !w.closing && w.content && w.vt){
    if(w.vt->on_poll)w.vt->on_poll(w.content);if(w.vt->sync_frame)w.vt->sync_frame(w.content);
  }
}
static bool extra_dispatch(const char *line) {
  unsigned id=0,generation=0;char tail=0;
  if(sscanf(line,"__window_open\t%u\t%u%c",&id,&generation,&tail)==2){extra_open(id,generation);return true;}
  if(sscanf(line,"__window_bind\t%u\t%u%c",&id,&generation,&tail)==2){
    if(id==1 && !g_root_closed){if(!g_content)maybe_install_content_plugin();}
    else if(auto *w=extra_find(id,generation))extra_install(*w);return true;
  }
  const char *raw=line;unsigned identity[2]={};
  bool scoped=xu_ui_scoped_command(line,identity,&raw);
  if(!scoped && !strncmp(line,"window\t",7))return true;
  bool marker=!scoped && xu_ui_command_owner(line,identity);
  if(!scoped && !marker)return false;
  if(identity[0]==1){
    unsigned meta[6];return g_root_closed || (scoped && !xu_ui_window_info(1,identity[1],meta,NULL,0));
  }
  const char *cmd=strip_prefix(raw);auto *w=extra_find(identity[0],identity[1]);
  bool content=!strncmp(raw,"content.",8) || !strncmp(raw,"wv.",3);
  if(w){
    if(content){if(!desktop_screens(cmd,w->id,w->generation,w->window) && !desktop_files(cmd,w->id,w->generation,w->window) && !desktop_clipboard(cmd,w->id,w->generation) && w->content && w->vt && w->vt->handle_cmd)w->vt->handle_cmd(w->content,cmd);}
    else if(!strcmp(cmd,"menu_v2"))native_menu_install(w->window,w->box,w->id,w->generation);
    else if(!strcmp(cmd,"show"))gtk_window_present(w->window);
    else if(!strcmp(cmd,"hide"))gtk_widget_set_visible(GTK_WIDGET(w->window),FALSE);
    else if(!strcmp(cmd,"close") || !strcmp(cmd,"quit"))extra_close(*w);
    else if(!strcmp(cmd,"accept_close"))extra_close(*w,true);
    else if(!strcmp(cmd,"reject_close"))xu_ui_window_event(w->id,w->generation,"close_rejected");
    else if(!strncmp(cmd,"title\t",6))gtk_window_set_title(w->window,cmd+6);
    else if(!strncmp(cmd,"size\t",5)){int width=0,height=0;if(sscanf(cmd+5,"%d\t%d%c",&width,&height,&tail)==2 && width>=40 && height>=40 && width<=16384 && height<=16384)gtk_window_set_default_size(w->window,width,height);}
    else if(!strncmp(cmd,"close_guard\t",12))w->close_guard=cmd[12]!='0';
    else if(!strcmp(cmd,"maximize"))gtk_window_maximize(w->window);
    else if(!strcmp(cmd,"unmaximize"))gtk_window_unmaximize(w->window);
    else if(!strcmp(cmd,"minimize"))gtk_window_minimize(w->window);
    else if(!strcmp(cmd,"fullscreen"))gtk_window_fullscreen(w->window);
    else if(!strcmp(cmd,"fullscreen_exit"))gtk_window_unfullscreen(w->window);
    else if(!strncmp(cmd,"resizable\t",10))gtk_window_set_resizable(w->window,cmd[10]!='0');
    else xu_ui_window_event(w->id,w->generation,"command_unsupported");
  }
  if(content){xu_ui_draw_discard_marker(cmd);xu_ui_request_discard_marker(cmd);}return true;
}
