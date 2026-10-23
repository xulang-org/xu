// Included after the canvas and text-input registries. No native calls under g_lock.
#include "xu_ui_windows.h"
struct XuUiWindowSlot {
  unsigned id=0,generation=0,width=0,height=0,kind=0,state=0;
  char title[XU_UI_WINDOW_MAX_TITLE+1]={};
};
static XuUiWindowSlot g_windows[XU_UI_WINDOW_MAX_COUNT];
static unsigned g_window_id=0;
static bool g_windows_stopped=false;
static XuUiWindowSlot *window_find(unsigned id,unsigned generation) {
  for(auto &w:g_windows) if(w.id==id && w.generation==generation)return &w;
  return NULL;
}
int xu_ui_canvas_valid(unsigned window,unsigned canvas,unsigned generation) {
  lock_r();bool valid=false;
  for(auto &c:g_canvases)if(c.window_id==window && c.canvas_id==canvas && c.generation==generation){valid=true;break;}
  unlock_r();return valid;
}
int xu_ui_window_reserve(unsigned *identity) {
  if(!identity)return 0;
  identity[0]=identity[1]=0;
  lock_w();XuUiWindowSlot *slot=NULL;
  for(auto &w:g_windows)if(!w.id){slot=&w;break;}
  if(!slot || g_windows_stopped || g_window_id==0x7fffffffu){unlock_w();return 0;}
  unsigned id=++g_window_id;*slot={};slot->id=id;slot->state=1;unlock_w();
  unsigned generation=xu_ui_canvas_open(id,id);
  lock_w();
  if(!generation || slot->id!=id || slot->state!=1 || g_windows_stopped){
    if(slot->id==id)*slot={};unlock_w();if(generation)xu_ui_canvas_close(id,generation);return 0;
  }
  slot->generation=generation;identity[0]=id;identity[1]=generation;unlock_w();return 1;
}
void xu_ui_window_abandon(unsigned id,unsigned generation) {
  lock_w();auto *w=window_find(id,generation);bool release=w && w->state==1;
  if(release)*w={};unlock_w();if(release)xu_ui_canvas_close(id,generation);
}
static int window_upload(const void *data,unsigned size) {
  if(!data || size<32 || size>32+XU_UI_WINDOW_MAX_TITLE)return 0;
  auto *p=(const unsigned char *)data;
  unsigned id=xdf_u32(p+8),generation=xdf_u32(p+12),width=xdf_u32(p+16),height=xdf_u32(p+20),kind=xdf_u32(p+24),length=xdf_u32(p+28);
  if(memcmp(p,"XUW1",4) || xdf_u32(p+4)!=1 || width<40 || height<40 || width>16384 || height>16384 || kind>3 ||
      length!=size-32 || !length || !xdf_utf8(p+32,length) || memchr(p+32,0,length))return 0;
  lock_w();auto *w=window_find(id,generation);bool ok=w && w->state==1;
  char marker[80];int n=snprintf(marker,sizeof(marker),"__window_open\t%u\t%u\n",id,generation);
  if(ok && id!=1)ok=slot_append_unlocked("xu_ui_cmd.txt",marker,(unsigned)n,0);
  if(ok){w->width=width;w->height=height;w->kind=kind;memcpy(w->title,p+32,length);w->title[length]=0;w->state=2;}
  unlock_w();if(ok){wake_waiters();xu_ui_host_kick();}return ok;
}
static int window_bind(const void *data,unsigned size) {
  if(!data || size!=12)return 0;auto *p=(const unsigned char *)data;
  unsigned id=xdf_u32(p),generation=xdf_u32(p+4),kind=xdf_u32(p+8);
  if(!kind || kind>3)return 0;
  lock_w();auto *w=window_find(id,generation);bool ok=w && w->state>=2 && (!w->kind || w->kind==kind);
  if(ok && !w->kind){char marker[80];int n=snprintf(marker,sizeof(marker),"__window_bind\t%u\t%u\n",id,generation);
    ok=slot_append_unlocked("xu_ui_cmd.txt",marker,(unsigned)n,0);if(ok)w->kind=kind;}
  unlock_w();if(ok){wake_waiters();xu_ui_host_kick();}return ok;
}
int xu_ui_window_info(unsigned id,unsigned generation,unsigned *meta,char *title,unsigned cap) {
  if(meta)memset(meta,0,24);if(title && cap)title[0]=0;
  lock_r();auto *w=window_find(id,generation);
  if(!generation)for(auto &candidate:g_windows)if(candidate.id==id){w=&candidate;break;}
  bool ok=w && w->state>=2;
  if(ok){if(meta){meta[0]=w->id;meta[1]=w->generation;meta[2]=w->width;meta[3]=w->height;meta[4]=w->kind;meta[5]=w->state;}
    if(title && cap){unsigned length=(unsigned)strlen(w->title);if(length>=cap)ok=false;else memcpy(title,w->title,length+1);}}
  unlock_r();return ok;
}
int xu_ui_window_claim(unsigned id,unsigned generation) {
  lock_w();auto *w=window_find(id,generation);bool ok=w && w->state==2;if(ok)w->state=3;unlock_w();return ok;
}
int xu_ui_window_ready(unsigned id,unsigned generation) {
  lock_w();auto *w=window_find(id,generation);bool ok=w && w->state==3;if(ok)w->state=4;unlock_w();return ok;
}
unsigned xu_ui_window_count(void){lock_r();unsigned count=0;for(auto &w:g_windows)if(w.state>=2)++count;unlock_r();return count;}
void xu_ui_window_closed(unsigned id,unsigned generation) {
  lock_w();auto *w=window_find(id,generation);bool release=w!=NULL;if(w)*w={};
  // Scoped slots cannot survive a window or exhaust the mailbox after repeated opens.
  char prefix[48];snprintf(prefix,sizeof(prefix),"window/%u/%u/",id,generation);size_t length=strlen(prefix);
  if(release)for(auto &s:g_slots)if(s.used && !strncmp(s.name,prefix,length)){free(s.body);memset(&s,0,sizeof(s));}
  unlock_w();if(release)xu_ui_canvas_close(id,generation);
}
void xu_ui_windows_shutdown(void) {
  unsigned identities[XU_UI_WINDOW_MAX_COUNT][2]={};
  lock_w();g_windows_stopped=true;unsigned count=0;
  for(auto &w:g_windows)if(w.id){identities[count][0]=w.id;identities[count++][1]=w.generation;}
  unlock_w();for(unsigned i=0;i<count;++i)xu_ui_window_closed(identities[i][0],identities[i][1]);
}
void xu_ui_window_event(unsigned id,unsigned generation,const char *payload) {
  if(!payload)return;
  if(!id || !generation || !strncmp(payload,"input",5) || !strncmp(payload,"canvas_",7) || !strncmp(payload,"request\t",8) || !strncmp(payload,"text_edit\t",10)){
    xu_ui_mem_append("xu_ui_shell_event.txt",payload,1);return;
  }
  // Native callbacks may emit a terminal closed event after registry revocation.
  size_t length=strlen(payload);if(length>XU_UI_MEM_MAX_PAYLOAD-80)return;
  std::string event="window\t"+std::to_string(id)+"\t"+std::to_string(generation)+"\t"+payload;
  xu_ui_mem_append("xu_ui_shell_event.txt",event.c_str(),1);
}
int xu_ui_command_owner(const char *command,unsigned *identity) {
  if(!command || !identity)return 0;identity[0]=identity[1]=0;
  const char *s=command;
  if(!strncmp(s,"content.",8))s+=8;else if(!strncmp(s,"wv.",3))s+=3;
  uint64_t id=0;bool found=false;lock_r();
  if(!strncmp(s,"__draw_frame\t",13) && xu_request_id(s+13,&id)){
    for(auto &f:g_draw_pending)if(f.lease && f.ticket==id){identity[0]=f.window_id;identity[1]=f.generation;found=true;break;}
  }else if(xu_request_marker(s,&id)){auto *r=request_find(id);if(r){identity[0]=r->window;identity[1]=r->generation;found=true;}}
  else if(!strncmp(s,"__text_input\t",13) && xu_request_id(s+13,&id)){auto *slot=input_slot(id);if(slot){identity[0]=slot->window;identity[1]=slot->generation;found=true;}}
  unlock_r();return found;
}
static int window_slot_write(const void *data,unsigned size) {
  if(!data || size<24 || size>24+64+1024*1024)return 0;
  auto *p=(const unsigned char *)data;unsigned id=xdf_u32(p+8),generation=xdf_u32(p+12),name_size=xdf_u32(p+16),body_size=xdf_u32(p+20);
  if(memcmp(p,"XWS1",4) || xdf_u32(p+4)!=1 || name_size<7 || name_size>64 || body_size>1024*1024 || size!=24+name_size+body_size || memcmp(p+24,"xu_ui_",6))return 0;
  for(unsigned i=0;i<name_size;++i){unsigned c=p[24+i];if(!((c>='a' && c<='z') || (c>='0' && c<='9') || c=='_' || c=='.'))return 0;}
  std::string name((const char *)p+24,name_size);
  std::string key=id==1 ? name : "window/"+std::to_string(id)+"/"+std::to_string(generation)+"/"+name;
  if(key.size()>XU_UI_MEM_MAX_NAME)return 0;
  lock_w();auto *w=window_find(id,generation);bool ok=w && w->state>=2 && slot_set_unlocked(alloc_slot_unlocked(key.c_str()),(const char *)p+24+name_size,body_size);
  unlock_w();if(ok){wake_waiters();xu_ui_host_kick();}return ok;
}
static int window_command(const void *data,unsigned size) {
  if(!data || !size || size>65536 || memchr(data,0,size) || memchr(data,'\n',size) || memchr(data,'\r',size))return 0;
  auto *p=(const char *)data;unsigned ends[2]={},count=0;
  for(unsigned i=0;i<size && count<2;++i)if(p[i]=='\t')ends[count++]=i;
  uint64_t id=0,gen=0;
  if(count!=2 || !request_number(p,ends[0],0x7fffffff,&id) || !request_number(p+ends[0]+1,ends[1]-ends[0]-1,UINT32_MAX,&gen) || ends[1]+1==size)return 0;
  std::string command="window\t"+std::string(p,size)+"\n";
  lock_w();auto *w=window_find((unsigned)id,(unsigned)gen);bool ok=w && w->state>=2 && slot_append_unlocked("xu_ui_cmd.txt",command.data(),(unsigned)command.size(),0);
  unlock_w();if(ok){wake_waiters();xu_ui_host_kick();}return ok;
}
