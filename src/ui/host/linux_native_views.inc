#include "linux_native_surface.inc"
struct XuGtkNativeView {
  unsigned id=0,generation=0,parent=0,parent_generation=0,focus_epoch=0;GtkWindow *window=NULL;
  GtkWidget *box=NULL,*layer=NULL,*clip=NULL;XuContentHost host={};XuContentPlugin *content=NULL;const XuContentVTable *vt=NULL;bool focused=false,applied=false;unsigned applied_flags=0;double geometry_cache[13]={};
};
static XuGtkNativeView g_native_children[XU_UI_NATIVE_VIEW_MAX_COUNT];
static XuGtkNativeView *native_child_find(unsigned id,unsigned generation) {for(auto &v:g_native_children)if(v.id==id&&v.generation==generation)return &v;return NULL;}
static bool native_owns_focus(XuGtkNativeView &v) {auto *focus=gtk_root_get_focus(GTK_ROOT(v.window));return focus&&(focus==v.clip||gtk_widget_is_ancestor(focus,v.clip));}
static void native_return_focus(XuGtkNativeView &v) {if(auto *canvas=gtk_widget_get_last_child(v.box))gtk_widget_grab_focus(canvas);}
static void native_child_close(XuGtkNativeView &v) {
  if(!v.id)return;if(native_owns_focus(v))native_return_focus(v);if(v.content&&v.vt&&v.vt->destroy)v.vt->destroy(v.content);
  if(v.clip)gtk_fixed_remove(GTK_FIXED(v.layer),v.clip);v={};
}
static void native_children_close_parent(unsigned parent,unsigned generation) {for(auto &v:g_native_children)if(v.id&&v.parent==parent&&v.parent_generation==generation)native_child_close(v);}
static void native_child_update(XuGtkNativeView &v) {
  unsigned m[8];double g[9];if(!xu_ui_native_view_info(v.id,v.generation,m,g))return;
  auto *canvas=gtk_widget_get_last_child(v.box);graphene_rect_t canvas_bounds=GRAPHENE_RECT_INIT(0,0,(float)gtk_widget_get_width(v.box),(float)gtk_widget_get_height(v.box));
  if(canvas && !gtk_widget_compute_bounds(canvas,v.layer,&canvas_bounds))return;
  double key[13];memcpy(key,g,72);key[9]=canvas_bounds.origin.x;key[10]=canvas_bounds.origin.y;key[11]=canvas_bounds.size.width;key[12]=canvas_bounds.size.height;
  bool changed=!v.applied||v.applied_flags!=(m[6]&3)||memcmp(v.geometry_cache,key,sizeof(key));
  if(changed){v.applied=true;v.applied_flags=m[6]&3;memcpy(v.geometry_cache,key,sizeof(key));}
  double left=fmax(g[0],fmax(g[4],0.0)),top=fmax(g[1],fmax(g[5],0.0));
  double right=fmin(g[0]+g[2],fmin(g[4]+g[6],canvas_bounds.size.width)),bottom=fmin(g[1]+g[3],fmin(g[5]+g[7],canvas_bounds.size.height));
  bool visible=(m[6]&1)&&right>left&&bottom>top,enabled=(m[6]&2)!=0;
  if((!visible||!enabled)&&native_owns_focus(v))native_return_focus(v);
  if(changed&&visible){auto *clip=(XuNativeClip *)v.clip;clip->dx=g[0]-left;clip->dy=g[1]-top;clip->width=g[2];clip->height=g[3];clip->radius=g[8];
    gtk_widget_set_size_request(v.clip,(int)ceil(right-left),(int)ceil(bottom-top));gtk_fixed_move(GTK_FIXED(v.layer),v.clip,left+canvas_bounds.origin.x,top+canvas_bounds.origin.y);gtk_widget_queue_allocate(v.clip);gtk_widget_queue_draw(v.clip);}
  if(changed){gtk_widget_set_sensitive(v.clip,enabled);gtk_widget_set_visible(v.clip,visible);}
  if(v.focus_epoch!=m[7]&&(!(m[6]&4)||(visible&&enabled))){v.focus_epoch=m[7];if((m[6]&4)&&visible&&enabled){auto *content=gtk_widget_get_first_child(((XuNativeClip *)v.clip)->child);if(content)gtk_widget_grab_focus(content);}else if(native_owns_focus(v))native_return_focus(v);}
}
static void native_child_open(unsigned parent,unsigned parent_generation,unsigned id,unsigned generation) {
  if(native_child_find(id,generation))return;unsigned m[8];if(!xu_ui_native_view_info(id,generation,m,NULL)||m[2]!=parent||m[3]!=parent_generation)return;
  GtkWindow *window=parent==1&&g_root_generation==parent_generation&&!g_root_closed?g_win:NULL;GtkWidget *box=window?g_content_box:NULL;
  if(!window){auto *owner=extra_find(parent,parent_generation);if(owner){window=owner->window;box=owner->box;}}
  const auto *vt=content_kind_vtable(1);XuGtkNativeView *slot=NULL;for(auto &v:g_native_children)if(!v.id){slot=&v;break;}
  if(!window||!box||!slot||!vt||!vt->create||!vt->install){xu_ui_native_view_event(id,generation,"load_failed\tWebView backend unavailable");xu_ui_native_view_close(id,generation);return;}
  auto &v=*slot;v.id=id;v.generation=generation;v.parent=parent;v.parent_generation=parent_generation;v.window=window;v.box=box;v.vt=vt;
  GtkWidget *overlay=gtk_widget_get_parent(box);if(!GTK_IS_OVERLAY(overlay)){
    g_object_ref(box);gtk_window_set_child(window,NULL);overlay=gtk_overlay_new();gtk_overlay_set_child(GTK_OVERLAY(overlay),box);g_object_unref(box);gtk_window_set_child(window,overlay);
  }
  v.layer=GTK_WIDGET(g_object_get_data(G_OBJECT(overlay),"xu-native-layer"));
  if(!v.layer){v.layer=GTK_WIDGET(g_object_new(xu_native_plane_get_type(),NULL));gtk_widget_set_hexpand(v.layer,TRUE);gtk_widget_set_vexpand(v.layer,TRUE);gtk_widget_set_overflow(v.layer,GTK_OVERFLOW_HIDDEN);gtk_overlay_add_overlay(GTK_OVERLAY(overlay),v.layer);gtk_overlay_set_measure_overlay(GTK_OVERLAY(overlay),v.layer,FALSE);g_object_set_data(G_OBJECT(overlay),"xu-native-layer",v.layer);}
  v.clip=GTK_WIDGET(g_object_new(xu_native_clip_get_type(),NULL));auto *clip=(XuNativeClip *)v.clip;clip->child=gtk_box_new(GTK_ORIENTATION_VERTICAL,0);gtk_widget_set_parent(clip->child,v.clip);gtk_fixed_put(GTK_FIXED(v.layer),v.clip,0,0);gtk_widget_set_visible(v.clip,FALSE);
  v.host={g_tmp,window,clip->child,append_shell_event,write_tmp,[](const char *n,char *out,unsigned cap){read_trim_file(n,out,cap);},[](const char *n,char *out,unsigned cap){read_file_raw(n,out,cap);},parent,id,generation};v.content=vt->create(&v.host);
  if(!v.content){native_child_close(v);xu_ui_native_view_event(id,generation,"load_failed\tWebView creation failed");xu_ui_native_view_close(id,generation);return;}
  auto *key=gtk_event_controller_key_new();gtk_event_controller_set_propagation_phase(key,GTK_PHASE_CAPTURE);
  g_signal_connect(key,"key-pressed",G_CALLBACK(+[](GtkEventControllerKey *,guint keyval,guint,GdkModifierType modifiers,gpointer data)->gboolean{
    auto &view=*(XuGtkNativeView *)data;if((keyval==GDK_KEY_Tab||keyval==GDK_KEY_ISO_Left_Tab)&&(modifiers&GDK_CONTROL_MASK)){
      native_return_focus(view);xu_ui_native_view_event(view.id,view.generation,(modifiers&GDK_SHIFT_MASK)?"focus_previous":"focus_next");return TRUE;}return FALSE;
  }),&v);gtk_widget_add_controller(v.clip,key);
  vt->install(v.content);native_child_update(v);xu_ui_native_view_ready(id,generation);
}
static void native_children_poll(void) {
  for(auto &v:g_native_children)if(v.id){if(!xu_ui_native_view_info(v.id,v.generation,NULL,NULL)){native_child_close(v);continue;}native_child_update(v);if(v.content&&v.vt&&v.vt->on_poll)v.vt->on_poll(v.content);
    bool focused=native_owns_focus(v);if(focused!=v.focused){v.focused=focused;xu_ui_native_view_event(v.id,v.generation,focused?"focused":"blurred");}}
}
static bool native_children_dispatch(const char *line) {
  unsigned parent=0,parent_generation=0,id=0,generation=0;char tail=0;
  if(sscanf(line,"__view_create\t%u\t%u\t%u\t%u%c",&parent,&parent_generation,&id,&generation,&tail)==4){native_child_open(parent,parent_generation,id,generation);return true;}
  if(sscanf(line,"__view_update\t%u\t%u\t%u\t%u%c",&parent,&parent_generation,&id,&generation,&tail)==4){if(auto *v=native_child_find(id,generation))native_child_update(*v);return true;}
  if(sscanf(line,"__view_close\t%u\t%u\t%u\t%u%c",&parent,&parent_generation,&id,&generation,&tail)==4){if(auto *v=native_child_find(id,generation))native_child_close(*v);return true;}
  const char *raw=line;XuGtkNativeView *v=NULL;int offset=0;
  if(!strncmp(line,"view\t",5)){if(sscanf(line,"view\t%u\t%u\t%u\t%n",&parent,&id,&generation,&offset)!=3||!offset)return true;v=native_child_find(id,generation);if(v&&v->parent!=parent)v=NULL;raw=line+offset;}
  else {unsigned owner[2]={};if(!xu_ui_command_owner(line,owner))return false;for(auto &candidate:g_native_children)if(candidate.id&&candidate.parent==owner[0]&&candidate.generation==owner[1]){v=&candidate;break;}if(!v)return false;}
  const char *command=strip_prefix(raw);if(v&&xu_ui_native_view_info(v->id,v->generation,NULL,NULL)&&v->content&&v->vt&&v->vt->handle_cmd)v->vt->handle_cmd(v->content,command);
  xu_ui_draw_discard_marker(command);xu_ui_request_discard_marker(command);return true;
}
