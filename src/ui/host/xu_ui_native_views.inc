// Included after the window registry. All native toolkit work stays outside locks.
#include "xu_ui_native_views.h"
struct XuUiNativeView {
  unsigned id=0,generation=0,parent=0,parent_generation=0,kind=0,state=0,flags=2,focus_epoch=0;
  uint64_t page_revision=0;
  double geometry[9]={};
};
static XuUiNativeView g_native_views[XU_UI_NATIVE_VIEW_MAX_COUNT];
static unsigned g_native_view_serial=0;
static XuUiNativeView *native_view_find(unsigned id,unsigned generation) {
  for(auto &view:g_native_views)if(view.id==id && view.generation==generation)return &view;
  return NULL;
}
unsigned xu_ui_canvas_for_generation(unsigned window,unsigned generation) {
  lock_r();unsigned canvas=0;
  for(auto &c:g_canvases)if(c.window_id==window && c.generation==generation){canvas=c.canvas_id;break;}
  unlock_r();return canvas;
}
int xu_ui_native_view_info(unsigned id,unsigned generation,unsigned *meta,double *geometry) {
  if(meta)memset(meta,0,32);if(geometry)memset(geometry,0,72);
  lock_r();auto *view=native_view_find(id,generation);bool ok=view && view->state;
  if(ok){if(meta){unsigned values[]={view->id,view->generation,view->parent,view->parent_generation,view->kind,view->state,view->flags,view->focus_epoch};memcpy(meta,values,32);}
    if(geometry)memcpy(geometry,view->geometry,72);}
  unlock_r();return ok;
}
uint64_t xu_ui_native_view_revision(unsigned id,unsigned generation) {
  lock_r();auto *view=native_view_find(id,generation);uint64_t revision=view?view->page_revision:0;unlock_r();return revision;
}
static int native_view_marker_unlocked(const char *operation,const XuUiNativeView &view) {
  char marker[128];int n=snprintf(marker,sizeof(marker),"__view_%s\t%u\t%u\t%u\t%u\n",operation,view.parent,view.parent_generation,view.id,view.generation);
  return n>0 && (unsigned)n<sizeof(marker) && slot_append_unlocked("xu_ui_cmd.txt",marker,(unsigned)n,0);
}
static void native_view_reserve(unsigned parent,unsigned parent_generation,unsigned kind,unsigned *identity) {
  identity[0]=identity[1]=0;
  if(kind!=1)return;
  lock_w();auto *window=window_find(parent,parent_generation);XuUiNativeView *slot=NULL;
  for(auto &candidate:g_native_views)if(!candidate.id){slot=&candidate;break;}
  if(!window || window->state<2 || window->kind!=2 || !slot || g_windows_stopped || g_native_view_serial==0x3fffffffu){unlock_w();return;}
  unsigned id=XU_UI_NATIVE_VIEW_ID_BASE+(++g_native_view_serial);*slot={};slot->id=id;slot->parent=parent;slot->parent_generation=parent_generation;slot->kind=kind;
  unlock_w();unsigned generation=xu_ui_canvas_open(parent,id);
  lock_w();window=window_find(parent,parent_generation);
  bool ok=generation && slot->id==id && window && window->state>=2 && !g_windows_stopped;
  if(ok){slot->generation=generation;slot->state=1;ok=native_view_marker_unlocked("create",*slot)!=0;}
  if(!ok){if(slot->id==id)*slot={};}else {identity[0]=id;identity[1]=generation;}
  unlock_w();
  if(!ok && generation)xu_ui_canvas_close(id,generation);
  if(ok){wake_waiters();xu_ui_host_kick();}
}
static bool native_view_reserve_key(const char *key,unsigned *identity) {
  const char *prefix="__native_view_reserve/";size_t prefix_size=strlen(prefix);
  if(strncmp(key,prefix,prefix_size))return false;
  const char *cursor=key+prefix_size;uint64_t values[3]={};
  for(unsigned i=0;i<3;++i){const char *end=i<2?strchr(cursor,'/'):cursor+strlen(cursor);
    if(!end || !request_number(cursor,(unsigned)(end-cursor),UINT32_MAX,&values[i])){identity[0]=identity[1]=0;return true;}
    cursor=end+(i<2?1:0);}
  native_view_reserve((unsigned)values[0],(unsigned)values[1],(unsigned)values[2],identity);return true;
}
int xu_ui_native_view_ready(unsigned id,unsigned generation) {
  lock_w();auto *view=native_view_find(id,generation);bool ok=view && view->state==1;if(ok)view->state=2;unlock_w();
  if(ok)xu_ui_native_view_event(id,generation,"ready");return ok;
}
void xu_ui_native_view_event(unsigned id,unsigned generation,const char *payload) {
  if(!payload)return;size_t length=strlen(payload);if(length>65536 || !xdf_utf8((const unsigned char *)payload,(unsigned)length))return;
  lock_r();auto *view=native_view_find(id,generation);unsigned parent=view?view->parent:0;unlock_r();if(!parent)return;
  static const char digits[]="0123456789abcdef";
  std::string event="view\t"+std::to_string(parent)+"\t"+std::to_string(id)+"\t"+std::to_string(generation)+"\t";
  event.reserve(event.size()+length*2+1);
  for(size_t i=0;i<length;++i){unsigned c=(unsigned char)payload[i];event+=digits[c>>4];event+=digits[c&15];}
  xu_ui_mem_append("xu_ui_shell_event.txt",event.c_str(),1);
}
void xu_ui_native_view_close(unsigned id,unsigned generation) {
  lock_w();auto *view=native_view_find(id,generation);unsigned parent=0;
  if(view){parent=view->parent;native_view_marker_unlocked("close",*view);*view={};
    char prefix[48];snprintf(prefix,sizeof(prefix),"view/%u/%u/",id,generation);size_t size=strlen(prefix);
    for(auto &slot:g_slots)if(slot.used && !strncmp(slot.name,prefix,size)){free(slot.body);memset(&slot,0,sizeof(slot));}}
  unlock_w();if(parent){xu_ui_web_invoke_close(parent,generation);xu_ui_canvas_close(id,generation);wake_waiters();xu_ui_host_kick();}
}
static void native_views_close_parent(unsigned parent,unsigned generation) {
  unsigned identities[XU_UI_NATIVE_VIEW_MAX_COUNT][2]={},count=0;
  lock_r();for(auto &view:g_native_views)if(view.id && view.parent==parent && view.parent_generation==generation){identities[count][0]=view.id;identities[count++][1]=view.generation;}unlock_r();
  for(unsigned i=0;i<count;++i)xu_ui_native_view_close(identities[i][0],identities[i][1]);
}
static int native_view_update(const void *data,unsigned size) {
  if(!data || size!=96)return 0;auto *p=(const unsigned char *)data;
  unsigned id=xdf_u32(p+8),generation=xdf_u32(p+12),flags=xdf_u32(p+16),epoch=xdf_u32(p+20);
  if(memcmp(p,"XNV1",4) || xdf_u32(p+4)!=1 || flags>7)return 0;
  double values[9];for(unsigned i=0;i<9;++i){uint64_t bits=(uint64_t)xdf_u32(p+24+i*8)|((uint64_t)xdf_u32(p+28+i*8)<<32);memcpy(&values[i],&bits,8);
    if(!isfinite(values[i]) || fabs(values[i])>1000000.0)return 0;}
  if(values[2]<0 || values[3]<0 || values[6]<0 || values[7]<0 || values[8]<0 || values[8]>256)return 0;
  lock_w();auto *view=native_view_find(id,generation);bool ok=view && view->state;
  if(ok){XuUiNativeView next=*view;next.flags=flags;next.focus_epoch=epoch;memcpy(next.geometry,values,72);
    ok=native_view_marker_unlocked("update",next)!=0;if(ok)*view=next;}
  unlock_w();if(ok){wake_waiters();xu_ui_host_kick();}return ok;
}
static int native_view_slot_write(const void *data,unsigned size) {
  if(!data || size<24 || size>24+64+1048576)return 0;auto *p=(const unsigned char *)data;
  unsigned id=xdf_u32(p+8),generation=xdf_u32(p+12),name_size=xdf_u32(p+16),body_size=xdf_u32(p+20);
  if(memcmp(p,"XVS1",4) || xdf_u32(p+4)!=1 || name_size<7 || name_size>64 || body_size>1048576 || size!=24+name_size+body_size || memcmp(p+24,"xu_ui_",6))return 0;
  for(unsigned i=0;i<name_size;++i){unsigned c=p[24+i];if(!((c>='a' && c<='z') || (c>='0' && c<='9') || c=='_' || c=='.'))return 0;}
  const char *body=(const char *)p+24+name_size;if(memchr(body,0,body_size) || !xdf_utf8((const unsigned char *)body,body_size))return 0;
  std::string key="view/"+std::to_string(id)+"/"+std::to_string(generation)+"/"+std::string((const char *)p+24,name_size);if(key.size()>XU_UI_MEM_MAX_NAME)return 0;
  lock_w();auto *view=native_view_find(id,generation);bool ok=view && view->state && view->page_revision!=UINT64_MAX && slot_set_unlocked(alloc_slot_unlocked(key.c_str()),body,body_size);
  if(ok && ((name_size==15 && !memcmp(p+24,"xu_ui_page.html",15)) || (name_size==14 && !memcmp(p+24,"xu_ui_page.url",14))))++view->page_revision;unlock_w();
  if(ok){wake_waiters();xu_ui_host_kick();}return ok;
}
static int native_view_command(const void *data,unsigned size) {
  if(!data || !size || size>65536 || memchr(data,0,size) || memchr(data,'\n',size) || memchr(data,'\r',size))return 0;
  auto *p=(const char *)data;unsigned ends[2]={},count=0;
  for(unsigned i=0;i<size && count<2;++i)if(p[i]=='\t')ends[count++]=i;
  uint64_t id=0,generation=0;
  if(count!=2 || !request_number(p,ends[0],0x7fffffff,&id) || !request_number(p+ends[0]+1,ends[1]-ends[0]-1,UINT32_MAX,&generation) || ends[1]+1==size)return 0;
  lock_w();auto *view=native_view_find((unsigned)id,(unsigned)generation);bool ok=view && view->state;
  if(ok){std::string command="view\t"+std::to_string(view->parent)+"\t"+std::to_string(id)+"\t"+std::to_string(generation)+"\tcontent."+std::string(p+ends[1]+1,size-ends[1]-1)+"\n";
    ok=slot_append_unlocked("xu_ui_cmd.txt",command.data(),(unsigned)command.size(),0);}
  unlock_w();if(ok){wake_waiters();xu_ui_host_kick();}return ok;
}
