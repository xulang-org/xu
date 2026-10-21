// Included after immutable frame leases and resource snapshot helpers.
struct XuUiDisplayList {
  std::atomic<unsigned> references{1};
  uint64_t id=0; unsigned cost=0;
  XuUiFrameLease *frame=NULL;
  void *native=NULL; XuUiListDestroy destroy=NULL;
};
struct XuListSlot {
  uint64_t id=0; unsigned state=0,canvas=0,generation=0;
  long long deadline=0; XuUiDisplayList *list=NULL;
};
static XuListSlot g_lists[XU_UI_LIST_MAX_COUNT];
static uint64_t g_list_id=0;
static XuUiListCompile g_list_compile=NULL;
static XuUiListDestroy g_list_destroy=NULL;
static std::atomic<unsigned> g_list_cost{0};
static XuUiFrameLease *draw_copy_frame(const void *,unsigned);
static XuListSlot *list_slot(uint64_t id) {
  if(!id)return NULL;auto *slot=&g_lists[id&(XU_UI_LIST_MAX_COUNT-1)];return slot->id==id ? slot : NULL;
}
int xu_ui_display_list_set_backend(XuUiListCompile compile,XuUiListDestroy destroy) {
  if(!compile || !destroy)return 0;lock_w();
  bool ok=!g_list_compile || (g_list_compile==compile && g_list_destroy==destroy);
  if(ok){g_list_compile=compile;g_list_destroy=destroy;}unlock_w();return ok;
}
void xu_ui_display_list_retain(XuUiDisplayList *list) {if(list)list->references.fetch_add(1,std::memory_order_relaxed);}
void xu_ui_display_list_release(XuUiDisplayList *list) {
  if(list && list->references.fetch_sub(1,std::memory_order_acq_rel)==1) {
    if(list->native)list->destroy(list->native);
    xu_ui_frame_release(list->frame);g_list_cost.fetch_sub(list->cost,std::memory_order_relaxed);delete list;
  }
}
void *xu_ui_display_list_native(const XuUiDisplayList *list) {return list ? list->native : NULL;}
unsigned xu_ui_display_list_live_cost(void) {return g_list_cost.load(std::memory_order_relaxed);}
XuUiDisplayList *xu_ui_frame_list(const XuUiFrameLease *frame,uint64_t id) {
  if(!frame || !id)return NULL;auto *list=frame->lists[id&(XU_UI_LIST_MAX_COUNT-1)];return list && list->id==id ? list : NULL;
}
static XuUiDisplayList *display_list_snapshot(uint64_t id,unsigned canvas,unsigned generation) {
  auto *slot=list_slot(id);
  if(!slot || slot->state!=3 || slot->canvas!=canvas || slot->generation!=generation)return NULL;
  xu_ui_display_list_retain(slot->list);return slot->list;
}
static bool list_alive(const XuListSlot &slot) {
  if(slot.canvas==1 && !slot.generation)return true;
  unsigned actual=0;return image_target(slot.canvas,slot.generation,&actual);
}
static void list_adopt_canvas(unsigned canvas,unsigned generation) {
  if(canvas==1)for(auto &slot:g_lists)if(slot.canvas==1 && !slot.generation)slot.generation=generation;
}
static void list_close_canvas(unsigned canvas,unsigned generation) {
  for(auto &slot:g_lists)if(slot.canvas==canvas && slot.generation==generation) {
    auto *list=slot.list;slot={};xu_ui_display_list_release(list);
  }
}
// Validate expanded work and cumulative transforms outside the registry lock.
// An origin within a fragment restores its caller's base, not global identity.
static bool draw_walk(const XuUiFrameLease *frame,XuDrawTransform base,unsigned &work,unsigned nesting,bool background) {
  if(nesting>XU_UI_LIST_MAX_NESTING || !xdf_transform_valid(&base))return false;
  XuDrawTransform transform=base,stack[256];unsigned depth=0,cursor=32;
  while(cursor<frame->len) {
    if(!work)return false;--work;
    auto *record=(const unsigned char *)frame->body+cursor;unsigned op=xdf_u16(record);
    if(op==XDF_BACKGROUND && !background)return false;
    // Immutable frames were already wire-validated. Expanding composition must
    // count every record, but need not rescan path coordinates or UTF-8 bytes.
    if(op!=XDF_DISPLAY_LIST && (op<XDF_SAVE || op>XDF_SCALE)) {cursor+=xdf_u32(record+4);continue;}
    XuDrawCommand c;if(xdf_next(frame->body,frame->len,&cursor,&c)!=1)return false;
    if(c.opcode==XDF_SAVE)stack[depth++]=transform;
    else if(c.opcode==XDF_RESTORE)transform=stack[--depth];
    else if(c.opcode==XDF_ORIGIN)transform=base;
    else if(c.opcode==XDF_DISPLAY_LIST) {
      auto *child=xu_ui_frame_list(frame,c.image_id);
      if(!child || !draw_walk(child->frame,transform,work,nesting+1,false))return false;
    } else if(!xdf_transform_apply(&transform,&c))return false;
  }
  return !depth;
}
static bool draw_composition_valid(const XuUiFrameLease *frame,bool background=true) {
  unsigned work=XU_DRAW_FRAME_MAX_COMMANDS-(background?0:1);return draw_walk(frame,xdf_identity(),work,background?0:1,background);
}
uint64_t xu_ui_display_list_reserve(void) {
  lock_w();long long now=image_now();
  for(auto &slot:g_lists)if(slot.state==1 && slot.deadline<=now)slot={};
  uint64_t id=0;
  if(g_list_compile)for(unsigned i=0;i<XU_UI_LIST_MAX_COUNT && g_list_id<INT64_MAX;++i) {
    uint64_t candidate=++g_list_id;auto &slot=g_lists[candidate&(XU_UI_LIST_MAX_COUNT-1)];
    if(slot.id)continue;slot.id=id=candidate;slot.state=1;slot.deadline=now+10000;break;
  }
  unlock_w();return id;
}
void xu_ui_display_list_abandon(uint64_t id) {
  lock_w();auto *slot=list_slot(id);if(slot && slot->state!=3)*slot={};unlock_w();
}
int xu_ui_display_list_create(uint64_t id,const void *data,unsigned len) {
  auto *frame=draw_copy_frame(data,len);if(!frame)return 0;
  auto *p=(const unsigned char *)frame->body;unsigned canvas=xdf_u32(p+16),generation=xdf_u32(p+20),actual=0;
  lock_w();auto *slot=list_slot(id);
  bool valid=slot && slot->state==1 && g_list_compile && image_target(canvas,generation,&actual);
  if(valid) {slot->state=2;slot->canvas=canvas;slot->generation=actual;valid=draw_snapshot_images(frame,canvas,actual);}
  auto compile=g_list_compile;auto destroy=g_list_destroy;unlock_w();
  uint64_t cost=(uint64_t)len+xdf_u32(p+12)*512ull;
  for(const auto &path:frame->paths)cost+=(path.prepared.empty()?path.length:path.prepared.size())*4ull;
  bool charged=false;
  if(valid && cost<=XU_UI_LIST_SINGLE_COST && draw_composition_valid(frame,false)) {
    unsigned used=g_list_cost.load(std::memory_order_relaxed);
    do {if(cost>XU_UI_LIST_MAX_COST-used)break;
      charged=g_list_cost.compare_exchange_weak(used,used+(unsigned)cost,std::memory_order_relaxed);
    }while(!charged);
  }
  XuUiDisplayList *list=charged ? new(std::nothrow) XuUiDisplayList : NULL;
  if(list) {
    list->id=id;list->frame=frame;list->cost=(unsigned)cost;list->destroy=destroy;
    try {list->native=compile(frame);}catch(...){list->native=NULL;}
  } else {xu_ui_frame_release(frame);if(charged)g_list_cost.fetch_sub((unsigned)cost,std::memory_order_relaxed);}
  lock_w();slot=list_slot(id);
  bool accepted=list && list->native && slot && slot->state==2 && list_alive(*slot);
  if(accepted){slot->list=list;slot->state=3;}
  else if(slot && slot->state==2){slot->state=1;slot->canvas=slot->generation=0;slot->deadline=image_now()+10000;}
  unlock_w();if(!accepted)xu_ui_display_list_release(list);return accepted;
}
int xu_ui_display_list_dispose(uint64_t id,unsigned canvas,unsigned generation) {
  lock_w();auto *slot=list_slot(id);
  bool valid=slot && slot->state==3 && slot->canvas==canvas && (slot->generation==generation || (!generation && canvas==1));
  XuUiDisplayList *list=NULL;if(valid){list=slot->list;*slot={};}unlock_w();xu_ui_display_list_release(list);return valid;
}
int xu_ui_display_list_info(uint64_t id,unsigned *generation,unsigned *cost) {
  lock_r();auto *slot=list_slot(id);bool valid=slot && slot->state==3;
  if(generation)*generation=valid?slot->generation:0;if(cost)*cost=valid?slot->list->cost:0;unlock_r();return valid;
}
static int display_list_upload(const void *data,unsigned len) {
  if(!data || len<48 || len>16+XU_DRAW_FRAME_MAX_BYTES)return 0;auto *p=(const unsigned char *)data;
  if(memcmp(p,"XDL1",4) || xdf_u32(p+4)!=1)return 0;
  uint64_t id=(uint64_t)xdf_u32(p+8)|((uint64_t)xdf_u32(p+12)<<32);
  return xu_ui_display_list_create(id,p+16,len-16);
}
