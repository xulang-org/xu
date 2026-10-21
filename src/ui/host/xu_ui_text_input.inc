// Included by xu_ui_mem.cc after request helpers. Uses the shared registry
// lock, atomic command append, and deferred shell-event wake flag.
#include "xu_ui_text_input.h"
#include "xu_ui_edit_model.h"
#include <memory>
enum { INPUT_RESERVED=1, INPUT_ACTIVE, INPUT_END_PENDING };
struct XuInputBinding {
  XuUiText *layout=NULL;
  uint64_t revision=0;
  XuDrawTransform transform=xdf_identity();
  unsigned focus=0, upstream=0;
  double focus_geometry[8]={};
  ~XuInputBinding() { xu_ui_text_release(layout); }
};
struct XuTextInputSlot {
  uint64_t id=0;
  unsigned state=0, window=0, canvas=0, generation=0, flags=0, serial=0;
  bool queued=false, activated=false;
  long long deadline=0;
  double caret[4]={};
  std::unique_ptr<XuUiEditModel> model;
  std::shared_ptr<XuInputBinding> binding;
};
struct XuTextInputEvent {
  bool live=false, terminal=false;
  unsigned kind=0, length=0;
  uint64_t session=0;
  int next=-1;
  char *data=NULL;
  char inline_data[224]={};
};
static XuTextInputSlot g_text_inputs[XU_UI_TEXT_INPUT_MAX_COUNT];
static uint64_t g_text_input_id=0;
static XuTextInputEvent g_text_input_events[XU_UI_TEXT_INPUT_MAX_EVENTS+XU_UI_TEXT_INPUT_MAX_COUNT];
static int g_text_input_head=-1, g_text_input_tail=-1;
static unsigned g_text_input_event_bytes=0;
static_assert((XU_UI_TEXT_INPUT_MAX_COUNT & (XU_UI_TEXT_INPUT_MAX_COUNT-1))==0,"input slots must be a power of two");
static XuTextInputSlot *input_slot(uint64_t id) {
  if (!id) return NULL;
  auto *slot=&g_text_inputs[id & (XU_UI_TEXT_INPUT_MAX_COUNT-1u)];
  return slot->id==id ? slot : NULL;
}
static bool input_owner(const XuTextInputSlot *slot,unsigned canvas,unsigned generation) {
  return slot && slot->canvas==canvas && slot->generation==generation;
}
static void input_flush(void) {
  while (g_text_input_head>=0) {
    auto &event=g_text_input_events[g_text_input_head];
    const char *data=event.terminal ? event.inline_data : event.data;
    if (!slot_append_unlocked("xu_ui_shell_event.txt",data,event.length,0)) break;
    g_shell_event_wake=true;
    g_text_input_head=event.next; if (g_text_input_head<0) g_text_input_tail=-1;
    if (event.terminal) {
      auto *slot=input_slot(event.session);
      if (slot && slot->state==INPUT_END_PENDING) *slot={};
    } else { g_text_input_event_bytes-=event.length; free(event.data); }
    event={};
  }
}
static bool input_event(XuTextInputSlot &slot,unsigned kind,uint64_t revision,unsigned start,unsigned end,
                         unsigned anchor,unsigned focus,unsigned reason,const char *text,unsigned length,bool terminal=false) {
  char prefix[200];
  int n=snprintf(prefix,sizeof(prefix),"text_edit\t%u\t%u\t%u\t%u\t%llu\t%llu\t%u\t%u\t%u\t%u\t%u\t",
    kind,slot.window,slot.canvas,slot.generation,(unsigned long long)slot.id,(unsigned long long)revision,
    start,end,anchor,focus,reason);
  if (n<=0 || (unsigned)n>=sizeof(prefix) || length>16384 || (terminal && length)) return false;
  unsigned size=(unsigned)n+length*2u+1u;
  int index=-1;
  if (!terminal && kind==XUTI_PREEDIT && g_text_input_tail>=0) {
    auto &tail=g_text_input_events[g_text_input_tail];
    if (!tail.terminal && tail.kind==kind && tail.session==slot.id) index=g_text_input_tail;
  }
  bool replace=index>=0;
  unsigned old_size=replace ? g_text_input_events[index].length : 0;
  if (!terminal && size>XU_UI_TEXT_INPUT_MAX_EVENT_BYTES-(g_text_input_event_bytes-old_size)) return false;
  if (index<0) {
    unsigned first=terminal ? XU_UI_TEXT_INPUT_MAX_EVENTS : 0;
    unsigned count=terminal ? XU_UI_TEXT_INPUT_MAX_COUNT : XU_UI_TEXT_INPUT_MAX_EVENTS;
    for(unsigned i=first;i<first+count;++i) if(!g_text_input_events[i].live) { index=(int)i; break; }
  }
  if (index<0) return false;
  auto &event=g_text_input_events[index];
  char *body=terminal ? event.inline_data : (char *)malloc(size+1u);
  if (!body || (terminal && size>=sizeof(event.inline_data))) return false;
  memcpy(body,prefix,(unsigned)n); const char hex[]="0123456789abcdef";
  for(unsigned i=0;i<length;++i) { unsigned c=(unsigned char)text[i]; body[n+i*2]=hex[c>>4]; body[n+i*2+1]=hex[c&15]; }
  body[size-1]='\n'; body[size]=0;
  if (replace) { free(event.data); g_text_input_event_bytes-=old_size; }
  else {
    event.next=-1;
    if (g_text_input_tail>=0) g_text_input_events[g_text_input_tail].next=index;
    else g_text_input_head=index;
    g_text_input_tail=index;
  }
  event.live=true; event.terminal=terminal; event.kind=kind; event.session=slot.id; event.length=size;
  if (!terminal) { event.data=body; g_text_input_event_bytes+=size; }
  return true;
}
static void input_end(XuTextInputSlot &slot,unsigned reason) {
  if (slot.state!=INPUT_ACTIVE) return;
  unsigned kind=reason>=XUTI_BACKPRESSURE ? XUTI_FAILED : XUTI_ENDED;
  uint64_t revision=slot.model->revision(); if (revision<INT64_MAX) ++revision;
  // Every active/end-pending slot owns one of 64 reserved terminal positions.
  bool accepted=input_event(slot,kind,revision,0,0,slot.model->anchor(),slot.model->focus(),reason,NULL,0,true);
  if (!accepted) abort(); // A violated internal reservation invariant, never a recoverable allocation path.
  slot.state=INPUT_END_PENDING; slot.activated=false; slot.queued=false;
  slot.binding.reset();
  input_flush();
}
static bool input_caret(const double *v) {
  if (!v) return false;
  for(unsigned i=0;i<4;++i) if(!isfinite(v[i]) || fabs(v[i])>1048576) return false;
  return v[2]>=0 && v[2]<=16384 && v[3]>0 && v[3]<=16384;
}
static void input_expire(void) {
  long long now=image_now();
  for(auto &slot:g_text_inputs) {
    if(slot.state==INPUT_RESERVED && slot.deadline<=now) slot={};
    else if(slot.state==INPUT_ACTIVE && !slot.activated && slot.deadline<=now) input_end(slot,XUTI_ACTIVATION_TIMEOUT);
  }
  input_flush();
}
static bool input_marker(XuTextInputSlot &slot) {
  if (slot.queued) return true;
  char marker[64]; int n=snprintf(marker,sizeof(marker),"content.__text_input\t%llu\n",(unsigned long long)slot.id);
  if (n<=0 || (unsigned)n>=sizeof(marker) || !slot_append_unlocked("xu_ui_cmd.txt",marker,(unsigned)n,0)) return false;
  slot.queued=true; return true;
}
uint64_t xu_ui_text_input_reserve(void) {
  lock_w(); input_expire(); long long now=image_now();
  uint64_t id=0;
  for(unsigned i=0;i<XU_UI_TEXT_INPUT_MAX_COUNT && g_text_input_id<INT64_MAX;++i) {
    uint64_t candidate=++g_text_input_id;
    auto &slot=g_text_inputs[candidate & (XU_UI_TEXT_INPUT_MAX_COUNT-1u)];
    if (slot.id) continue;
    slot.id=id=candidate; slot.state=INPUT_RESERVED; slot.deadline=now+10000; break;
  }
  event_unlock(); return id;
}
void xu_ui_text_input_abandon(uint64_t id) {
  lock_w(); auto *slot=input_slot(id); if(slot && slot->state==INPUT_RESERVED) *slot={}; event_unlock();
}
void xu_ui_text_input_abort(uint64_t id) {
  lock_w(); auto *slot=input_slot(id);
  if(slot && slot->state==INPUT_RESERVED) *slot={};
  else if(slot) input_end(*slot,XUTI_NATIVE_UNAVAILABLE);
  event_unlock(); xu_ui_host_kick();
}
int xu_ui_text_input_start(uint64_t id,unsigned canvas,unsigned generation,const char *text,unsigned length,
                            unsigned anchor,unsigned focus,const double *caret,unsigned flags) {
  if (!input_caret(caret) || flags>1) return 0;
  std::unique_ptr<XuUiEditModel> model;
  try { model.reset(new XuUiEditModel); if(!model->initialize(text,length,anchor,focus)) return 0; }
  catch (...) { return 0; }
  lock_w(); input_expire(); auto *slot=input_slot(id); unsigned actual=0,window=0;
  bool valid=slot && slot->state==INPUT_RESERVED && image_target(canvas,generation,&actual) && actual;
  for(const auto &other:g_text_inputs) if(other.state==INPUT_ACTIVE && other.canvas==canvas && other.generation==actual) valid=false;
  for(const auto &target:g_canvases) if(target.canvas_id==canvas && target.generation==actual) window=target.window_id;
  if (valid && window) {
    slot->window=window; slot->canvas=canvas; slot->generation=actual;
    valid=input_marker(*slot);
    if (valid) {
      slot->state=INPUT_ACTIVE; slot->flags=flags; slot->serial=1; slot->model=std::move(model);
      slot->deadline=image_now()+5000;
      memcpy(slot->caret,caret,sizeof(slot->caret));
    } else { slot->window=slot->canvas=slot->generation=0; }
  } else valid=false;
  event_unlock(); if(valid) { wake_waiters(); xu_ui_host_kick(); } return valid ? 1 : 0;
}
int xu_ui_text_input_update(uint64_t id,unsigned canvas,unsigned generation,uint64_t expected,const char *text,unsigned length,
                             unsigned anchor,unsigned focus,const double *caret) {
  if (!input_caret(caret)) return 0;
  lock_w(); input_expire(); auto *slot=input_slot(id); bool valid=input_owner(slot,canvas,generation) && slot->state==INPUT_ACTIVE && slot->serial<UINT32_MAX;
  if (valid) try {
    auto next=std::unique_ptr<XuUiEditModel>(new XuUiEditModel(*slot->model));
    valid=next->update(expected,text,length,anchor,focus) && input_marker(*slot);
    if(valid) {
      if(next->revision()!=slot->model->revision()) slot->binding.reset();
      slot->model=std::move(next); memcpy(slot->caret,caret,sizeof(slot->caret)); ++slot->serial;
    }
  } catch (...) { valid=false; }
  event_unlock(); if(valid) { wake_waiters(); xu_ui_host_kick(); } return valid ? 1 : 0;
}
static bool input_geometry(const XuInputBinding &binding,unsigned mode,unsigned index,unsigned trailing,
                             double x,double y,double *out) {
  const auto &m=binding.transform;
  if(mode==3) { index=binding.focus; trailing=0; }
  if(mode==3 && binding.upstream && index) {
    std::vector<unsigned> stops;
    if(!xu_ui_grapheme::boundaries(binding.layout->text,binding.layout->length,&stops)) return false;
    auto at=std::lower_bound(stops.begin(),stops.end(),index);
    if(at==stops.end() || *at!=index || at==stops.begin()) return false;
    index=*--at; trailing=1;
  }
  double hit[7]={};
  if(mode==0) {
    double det=m.a*m.d-m.b*m.c, dx=x-m.tx, dy=y-m.ty;
    double local_x=(m.d*dx-m.c*dy)/det, local_y=(-m.b*dx+m.a*dy)/det;
    if(!text_query_layout(binding.layout,0,0,0,local_x,local_y,hit)) return false;
  } else if(!text_query_layout(binding.layout,1,index,mode==2 ? 0 : trailing,0,0,hit)) return false;
  if(mode==3 && hit[0]+(hit[2] ? hit[1] : 0)!=binding.focus) return false;
  double left=hit[4],top=hit[5],width=1,height=hit[6];
  if(mode==2 && hit[1]>0) {
    double edge[7]={};
    if(!text_query_layout(binding.layout,1,(unsigned)hit[0],1,0,0,edge) || edge[0]!=hit[0] || edge[1]!=hit[1]) return false;
    // A newline has no horizontal span. Its first line owns the rectangle;
    // do not accidentally include every line between two insertion edges.
    if(edge[5]==top && edge[6]==height) { left=std::min(left,edge[4]); width=std::max(1.0,fabs(edge[4]-hit[4])); }
  }
  double min_x=INFINITY,min_y=INFINITY,max_x=-INFINITY,max_y=-INFINITY;
  for(unsigned i=0;i<4;++i) {
    double px=left+((i&1) ? width : 0),py=top+((i&2) ? height : 0);
    double cx=m.a*px+m.c*py+m.tx,cy=m.b*px+m.d*py+m.ty;
    if(!isfinite(cx) || !isfinite(cy)) return false;
    min_x=std::min(min_x,cx); max_x=std::max(max_x,cx); min_y=std::min(min_y,cy); max_y=std::max(max_y,cy);
  }
  double rect[4]={min_x,min_y,max_x-min_x,max_y-min_y};
  if(!input_caret(rect)) return false;
  memcpy(out,hit,4*sizeof(double)); memcpy(out+4,rect,sizeof(rect)); return true;
}
int xu_ui_text_input_bind(uint64_t id,unsigned canvas,unsigned generation,uint64_t revision,
                           uint64_t layout,const double *transform,unsigned upstream) {
  if(!revision || revision>INT64_MAX || upstream>1 || (!layout && (transform || upstream))) return 0;
  XuDrawTransform matrix=xdf_identity();
  if(layout) {
    if(!transform) return 0;
    matrix={transform[0],transform[1],transform[2],transform[3],transform[4],transform[5]};
    if(!xdf_transform_valid(&matrix)) return 0;
  }
  std::shared_ptr<XuInputBinding> binding;
  unsigned serial=0;
  lock_w(); input_expire(); auto *slot=input_slot(id);
  bool valid=input_owner(slot,canvas,generation) && slot->state==INPUT_ACTIVE && slot->model->revision()==revision && slot->serial<UINT32_MAX;
  if(valid && layout) try {
    binding=std::make_shared<XuInputBinding>(); binding->layout=text_snapshot(layout,canvas,generation);
    auto display=slot->model->display_text();
    valid=binding->layout && display.size()==binding->layout->length && !memcmp(display.data(),binding->layout->text,display.size());
    if(valid) { binding->transform=matrix; binding->revision=revision; binding->focus=slot->model->display_focus(); binding->upstream=upstream; }
  } catch(...) { valid=false; }
  if(valid) serial=slot->serial;
  event_unlock();
  double result[8]={};
  // Native shapers can block or reenter. Never hold the registry lock here.
  if(valid && binding) try { valid=input_geometry(*binding,3,0,0,0,0,result); } catch(...) { valid=false; }
  if(!valid) return 0;
  if(binding) memcpy(binding->focus_geometry,result,sizeof(result));
  lock_w(); input_expire(); slot=input_slot(id);
  valid=input_owner(slot,canvas,generation) && slot->state==INPUT_ACTIVE && slot->model->revision()==revision && slot->serial==serial && input_marker(*slot);
  if(valid) {
    slot->binding=std::move(binding); ++slot->serial;
    // Keep the application's explicit fallback separate from bound geometry.
    // A subsequent edit must not turn an expired layout rectangle into the
    // fallback for a newer document revision.
  }
  event_unlock(); if(valid) { wake_waiters(); xu_ui_host_kick(); } return valid ? 1 : 0;
}
int xu_ui_text_input_query(uint64_t id,unsigned canvas,unsigned generation,uint64_t revision,unsigned mode,
                            unsigned index,unsigned trailing,double x,double y,double *out) {
  if(!out) return 0;
  memset(out,0,8*sizeof(double));
  if(!revision || revision>INT64_MAX || mode>3 || trailing>1 || !isfinite(x) || !isfinite(y) || fabs(x)>1048576 || fabs(y)>1048576) return 0;
  std::shared_ptr<XuInputBinding> binding;
  lock_r(); auto *slot=input_slot(id);
  if(input_owner(slot,canvas,generation) && slot->state==INPUT_ACTIVE && slot->model->revision()==revision) binding=slot->binding;
  unlock_r(); if(!binding || binding->revision!=revision) return 0;
  double result[8]={}; bool valid=false;
  // The immutable binding caches its focus rectangle at admission. Native
  // polling and camera/DPI changes need no repeated font-engine query.
  if(mode==3) { memcpy(result,binding->focus_geometry,sizeof(result)); valid=true; }
  else try { valid=input_geometry(*binding,mode,index,trailing,x,y,result); } catch(...) { return 0; }
  lock_r(); slot=input_slot(id);
  valid=valid && input_owner(slot,canvas,generation) && slot->state==INPUT_ACTIVE && slot->model->revision()==revision && slot->binding==binding;
  unlock_r(); if(valid) memcpy(out,result,sizeof(result)); return valid ? 1 : 0;
}
int xu_ui_text_input_stop(uint64_t id,unsigned canvas,unsigned generation,unsigned reason) {
  if (!id || reason>XUTI_ACTIVATION_TIMEOUT) return 0;
  lock_w(); auto *slot=input_slot(id); bool valid=id<=g_text_input_id;
  if(slot) {
    valid=input_owner(slot,canvas,generation) && slot->state!=INPUT_RESERVED;
    if(valid) input_end(*slot,reason);
  }
  event_unlock(); if(valid) { wake_waiters(); xu_ui_host_kick(); } return valid ? 1 : 0;
}
int xu_ui_text_input_active(uint64_t id) {
  xu_ui_text_input_poll();
  lock_r(); auto *slot=input_slot(id); bool active=slot && slot->state==INPUT_ACTIVE; unlock_r(); return active ? 1 : 0;
}
unsigned xu_ui_text_input_window(uint64_t id) {
  lock_r(); auto *slot=input_slot(id); unsigned window=slot ? slot->window : 0; unlock_r(); return window;
}
int xu_ui_text_input_activate(uint64_t id,unsigned canvas,unsigned generation) {
  lock_w(); input_expire(); auto *slot=input_slot(id); bool valid=input_owner(slot,canvas,generation) && slot->state==INPUT_ACTIVE;
  if(valid && !slot->activated) {
    valid=input_event(*slot,XUTI_READY,slot->model->revision(),0,0,slot->model->anchor(),slot->model->focus(),0,NULL,0);
    if(valid) { slot->activated=true; input_flush(); }
    else input_end(*slot,XUTI_BACKPRESSURE);
  }
  event_unlock(); return valid ? 1 : 0;
}
template<typename Edit> static int input_edit(uint64_t id,Edit edit,uint64_t expected=0) {
  lock_w(); auto *slot=input_slot(id); bool valid=slot && slot->state==INPUT_ACTIVE && slot->activated && (!expected || slot->model->revision()==expected);
  if(valid) try {
    auto next=std::unique_ptr<XuUiEditModel>(new XuUiEditModel(*slot->model)); XuUiEditChange change;
    valid=edit(*next,&change);
    if(valid && change.kind) {
      valid=input_event(*slot,change.kind,change.revision,change.start,change.end,change.anchor,change.focus,0,
                          change.text.data(),(unsigned)change.text.size());
      if(valid) { slot->binding.reset(); slot->model=std::move(next); input_flush(); }
      else input_end(*slot,XUTI_BACKPRESSURE);
    }
  } catch (...) { valid=false; input_end(*slot,XUTI_BACKPRESSURE); }
  event_unlock(); return valid ? 1 : 0;
}
int xu_ui_text_input_commit(uint64_t id,const char *text,unsigned length,unsigned start,unsigned end) {
  return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.commit(text,length,e,start,end); });
}
int xu_ui_text_input_compose(uint64_t id,const char *text,unsigned length,unsigned anchor,unsigned focus,unsigned start,unsigned end) {
  return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.compose(text,length,anchor,focus,e,start,end); });
}
int xu_ui_text_input_commit_at(uint64_t id,uint64_t revision,const char *text,unsigned length,unsigned start,unsigned end) {
  if(!revision) return 0;
  return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.commit(text,length,e,start,end); },revision);
}
int xu_ui_text_input_compose_at(uint64_t id,uint64_t revision,const char *text,unsigned length,unsigned anchor,unsigned focus,unsigned start,unsigned end) {
  if(!revision) return 0;
  return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.compose(text,length,anchor,focus,e,start,end); },revision);
}
int xu_ui_text_input_delete_surrounding_at(uint64_t id,uint64_t revision,unsigned start,unsigned end) {
  if(!revision) return 0;
  return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.delete_surrounding(start,end,e); },revision);
}
int xu_ui_text_input_select_all(uint64_t id) {
  return input_edit(id,[](XuUiEditModel &m,XuUiEditChange *e) { return !m.composing() && m.select(0,(unsigned)m.text().size(),e); });
}
int xu_ui_text_input_cancel(uint64_t id) { return input_edit(id,[](XuUiEditModel &m,XuUiEditChange *e) { return m.cancel(e); }); }
int xu_ui_text_input_select(uint64_t id,unsigned a,unsigned f) { return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.select(a,f,e); }); }
int xu_ui_text_input_delete_surrounding(uint64_t id,unsigned start,unsigned end) { return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.delete_surrounding(start,end,e); }); }
int xu_ui_text_input_erase(uint64_t id,int backward) { return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.erase(backward!=0,e); }); }
int xu_ui_text_input_erase_count(uint64_t id,int backward,unsigned count) { return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.erase(backward!=0,e,count); }); }
int xu_ui_text_input_move(uint64_t id,int backward,int extend) { return input_edit(id,[&](XuUiEditModel &m,XuUiEditChange *e) { return m.move(backward!=0,extend!=0,e); }); }
static void input_close_canvas(unsigned canvas,unsigned generation) {
  for(auto &slot:g_text_inputs) if(slot.state==INPUT_ACTIVE && slot.canvas==canvas && slot.generation==generation) input_end(slot,XUTI_WINDOW_CLOSED);
}
void xu_ui_text_input_poll(void) { lock_w(); input_expire(); event_unlock(); }
static unsigned input_snapshot_size(const XuTextInputSlot &slot) {
  return 112u+(unsigned)slot.model->text().size()+(unsigned)slot.model->preedit().size();
}
static void input_snapshot_copy(const XuTextInputSlot &slot,void *output,unsigned capacity) {
  auto *p=(unsigned char *)output; memset(p,0,capacity);
  memcpy(p,"XIS1",4);
  auto word=[&](unsigned at,uint64_t value,unsigned bytes=4) { for(unsigned i=0;i<bytes;++i) p[at+i]=(unsigned char)(value>>(i*8)); };
  word(4,1,2); word(6,slot.flags|(slot.activated?2:0)|(slot.model->composing()?4:0),2);
  word(8,slot.id,8); word(16,slot.window); word(20,slot.canvas); word(24,slot.generation); word(28,slot.state);
  word(32,slot.model->revision(),8);
  for(unsigned i=0;i<4;++i) { uint64_t bits; memcpy(&bits,&slot.caret[i],8); word(40+i*8,bits,8); }
  word(72,slot.model->anchor()); word(76,slot.model->focus());
  word(80,slot.model->text().size()); word(84,slot.model->preedit().size());
  word(88,slot.model->replacement_start()); word(92,slot.model->replacement_end());
  word(96,slot.model->preedit_anchor()); word(100,slot.model->preedit_focus()); word(104,slot.serial);
  if(!slot.model->text().empty()) memcpy(p+112,slot.model->text().data(),slot.model->text().size());
  if(!slot.model->preedit().empty()) memcpy(p+112+slot.model->text().size(),slot.model->preedit().data(),slot.model->preedit().size());
}
void *xu_ui_text_input_snapshot(uint64_t id,unsigned canvas,unsigned generation,int take,unsigned *length) {
  if(length) *length=0;
  lock_w(); input_expire(); auto *slot=input_slot(id);
  bool valid=input_owner(slot,canvas,generation) && slot->state==INPUT_ACTIVE;
  unsigned size=valid ? input_snapshot_size(*slot) : 0;
  void *result=valid ? malloc(size+1u) : NULL;
  if(result) { input_snapshot_copy(*slot,result,size+1u); if(take) slot->queued=false; if(length) *length=size; }
  event_unlock(); return result;
}
static void input_info_copy(uint64_t id,void *out,unsigned capacity) {
  if(!out || capacity<XU_UI_TEXT_INPUT_SNAPSHOT_BYTES+1u) return;
  lock_w(); input_expire(); auto *slot=input_slot(id);
  if(slot && slot->state==INPUT_ACTIVE) input_snapshot_copy(*slot,out,XU_UI_TEXT_INPUT_SNAPSHOT_BYTES+1u);
  else { memset(out,0,XU_UI_TEXT_INPUT_SNAPSHOT_BYTES+1u); memcpy(out,"XIS1",4); }
  event_unlock();
}
static int input_upload(const void *data,unsigned length) {
  if(!data || length<80 || length>80+16384) return 0;
  auto *p=(const unsigned char *)data;
  if(memcmp(p,"XTI1",4) || xdf_u16(p+4)!=1 || xdf_u32(p+72)>16384 || length!=80+xdf_u32(p+72)) return 0;
  unsigned mode=xdf_u16(p+6), canvas=xdf_u32(p+16),generation=xdf_u32(p+20);
  uint64_t id=(uint64_t)xdf_u32(p+8)|((uint64_t)xdf_u32(p+12)<<32);
  uint64_t expected=(uint64_t)xdf_u32(p+24)|((uint64_t)xdf_u32(p+28)<<32);
  if(!id || id>INT64_MAX || expected>INT64_MAX) return 0;
  double caret[4];for(unsigned i=0;i<4;++i)caret[i]=xdf_f64(p+32+i*8);
  unsigned anchor=xdf_u32(p+64),focus=xdf_u32(p+68),size=xdf_u32(p+72),flags=xdf_u32(p+76);
  if(mode==0 && !expected) return xu_ui_text_input_start(id,canvas,generation,(const char *)p+80,size,anchor,focus,caret,flags);
  if(mode==1 && !flags) return xu_ui_text_input_update(id,canvas,generation,expected,(const char *)p+80,size,anchor,focus,caret);
  if(mode==2 && !expected && !size && !anchor && !focus && !caret[0] && !caret[1] && !caret[2] && !caret[3])
    return xu_ui_text_input_stop(id,canvas,generation,flags);
  return 0;
}
static int input_bind_upload(const void *data,unsigned length) {
  if(!data || length!=96) return 0;
  auto *p=(const unsigned char *)data;
  if(memcmp(p,"XIB1",4) || xdf_u16(p+4)!=1 || xdf_u16(p+6)>1 || xdf_u32(p+92)) return 0;
  auto wide=[&](unsigned at) { return (uint64_t)xdf_u32(p+at)|((uint64_t)xdf_u32(p+at+4)<<32); };
  double transform[6]; for(unsigned i=0;i<6;++i) transform[i]=xdf_f64(p+40+i*8);
  unsigned mode=xdf_u16(p+6),upstream=xdf_u32(p+88);
  if(!wide(8) || wide(8)>INT64_MAX || wide(32)>INT64_MAX) return 0;
  if(mode==1) {
    if(wide(32) || upstream) return 0;
    for(auto scalar:transform) if(scalar!=0) return 0;
  } else if(!wide(32)) return 0;
  return xu_ui_text_input_bind(wide(8),xdf_u32(p+16),xdf_u32(p+20),wide(24),wide(32),mode ? NULL : transform,upstream);
}
