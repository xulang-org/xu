// Uses the invoke mutex; never calls a native toolkit under a registry lock.
#include "xu_ui_web_requests.h"
#include "xu_ui_windows.h"
#include "xu_ui_native_views.h"
#include <string>
struct XuWebRequest {uint64_t id=0;unsigned window=0,canvas=0,generation=0,state=0,status=0;bool active=false;long long deadline=0;std::string key,body,result;};
static XuWebRequest g_web_requests[XU_WEB_MAX_PENDING];
static bool g_web_stopped=false;
static uint64_t g_web_id=0;static size_t g_web_bytes=0;
static long long web_now(){return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
static void web_clear(XuWebRequest &r){g_web_bytes-=r.body.size()+r.result.size();r={};}
static void web_terminal(XuWebRequest &r,unsigned status,const char *data,unsigned size){
 g_web_bytes-=r.body.size()+r.result.size();r.body.clear();r.result.assign(data,size);g_web_bytes+=r.result.size();r.state=3;r.status=status;
}
static void web_expire(){auto now=web_now();for(auto &r:g_web_requests)if((r.state==1||r.state==2||r.state==5)&&now>=r.deadline)web_terminal(r,2,"request timed out",17);}
static XuWebRequest *web_find(uint64_t id){for(auto &r:g_web_requests)if(r.id==id&&r.state)return &r;return NULL;}
static bool web_key(const char *key){if(!key||strlen(key)!=32)return false;for(unsigned i=0;i<32;++i)if(!((key[i]>='0'&&key[i]<='9')||(key[i]>='a'&&key[i]<='f')))return false;return true;}
uint64_t xu_ui_web_invoke_start(unsigned window,unsigned generation,const char *key,const void *body,unsigned length,unsigned timeout){
 unsigned canvas=xu_ui_canvas_for_generation(window,generation);
 if(!window||!generation||!canvas||!web_key(key)||!body||!length||length>XU_WEB_MAX_BODY||timeout<1||timeout>3600000||!xu_ui_canvas_valid(window,canvas,generation))return 0;
 inv_lock();web_expire();XuWebRequest *slot=NULL;
 for(auto &r:g_web_requests){if(r.state&&r.window==window&&r.generation==generation&&r.key==key){inv_unlock();return 0;}if(!r.state&&!slot)slot=&r;}
 if(g_web_stopped||!xu_ui_canvas_valid(window,canvas,generation)||!slot||g_web_id==INT64_MAX||length>XU_WEB_MAX_BYTES-g_web_bytes){inv_unlock();return 0;}
 slot->id=++g_web_id;slot->window=window;slot->canvas=canvas;slot->generation=generation;slot->key=key;slot->body.assign((const char *)body,length);g_web_bytes+=length;slot->state=1;slot->deadline=web_now()+timeout;uint64_t id=slot->id;
 inv_unlock();wake_waiters();return id;
}
int xu_ui_web_invoke_cancel(unsigned window,unsigned generation,const char *key){
 if(!web_key(key))return 0;inv_lock();web_expire();int accepted=0;
 for(auto &r:g_web_requests)if((r.state==1||r.state==2||r.state==5)&&r.window==window&&r.generation==generation&&r.key==key){web_terminal(r,1,"request cancelled",17);accepted=1;break;}
 inv_unlock();wake_waiters();return accepted;
}
void *xu_ui_web_invoke_result(uint64_t id,unsigned *length,unsigned *status){
 if(length)*length=0;if(status)*status=4;inv_lock();web_expire();auto *r=web_find(id);char *out=NULL;
 if(r&&r->state==3){out=(char *)malloc(r->result.size()+1);if(out){memcpy(out,r->result.data(),r->result.size());out[r->result.size()]=0;if(length)*length=(unsigned)r->result.size();if(status)*status=r->status;
  if(r->active){g_web_bytes-=r->result.size();r->result.clear();r->state=4;}else web_clear(*r);}}
 inv_unlock();return out;
}
void xu_ui_web_invoke_close(unsigned window,unsigned generation){inv_lock();
 for(auto &r:g_web_requests)if(r.state&&r.window==window&&r.generation==generation){if(r.active){g_web_bytes-=r.body.size()+r.result.size();r.body.clear();r.result.clear();r.state=4;}else web_clear(r);}
 inv_unlock();wake_waiters();
}
int xu_ui_web_invoke_owner(uint64_t id,unsigned *identity){inv_lock();auto *r=web_find(id);int ok=r&&r->state!=4;if(ok){identity[0]=r->window;identity[1]=r->generation;}inv_unlock();return ok;}
static void web_target(uint64_t id,unsigned *identity) {
 memset(identity,0,12);inv_lock();auto *r=web_find(id);
 if(r && r->active && r->state==2){identity[0]=r->window;identity[1]=r->canvas;identity[2]=r->generation;}inv_unlock();
}
static bool web_pending(){inv_lock();web_expire();bool pending=false;for(auto &r:g_web_requests)if(r.state==1)pending=true;inv_unlock();return pending;}
static XuWebRequest *web_next(){XuWebRequest *next=NULL;for(auto &r:g_web_requests)if(r.state==1&&(!next||r.id<next->id))next=&r;return next;}
// Dispatch only an integer across Xu task creation. The registry keeps the
// packet alive until that worker claims it; cancellation keeps its lease bound.
static uint64_t web_dispatch_reserve(){inv_lock();web_expire();auto *r=web_next();uint64_t id=0;
 if(r){id=r->id;r->state=5;r->active=true;}inv_unlock();return id;}
static void web_worker_done(XuWebRequest &r){r.active=false;if(r.state==4)web_clear(r);}
static unsigned web_packet_length(uint64_t id){inv_lock();web_expire();auto *r=web_find(id);unsigned size=0;
 if(r&&r->active){if(r->state==5)size=32+(unsigned)r->body.size();else web_worker_done(*r);}inv_unlock();return size;}
static void web_packet_copy(uint64_t id,void *out,unsigned cap){memset(out,0,cap);inv_lock();web_expire();auto *r=web_find(id);
 if(r&&r->active){if(r->state==5&&cap>32+r->body.size()){std::string data="XWI1";auto word=[&](uint64_t n,unsigned count){for(unsigned i=0;i<count;++i)data+=(char)(n>>(i*8));};
  word(1,4);word(r->id,8);word(r->window,4);word(r->generation,4);word(r->body.size(),4);word(r->canvas,4);data+=r->body;memcpy(out,data.data(),data.size());g_web_bytes-=r->body.size();r->body.clear();r->state=2;
 }else web_worker_done(*r);}inv_unlock();}
static unsigned web_take_length(){inv_lock();web_expire();auto *r=web_next();unsigned length=r?32+(unsigned)r->body.size():0;inv_unlock();return length;}
static void web_take_copy(void *out,unsigned cap){memset(out,0,cap);inv_lock();web_expire();auto *r=web_next();
 if(r&&cap>32+r->body.size()){std::string data="XWI1";auto word=[&](uint64_t n,unsigned size){for(unsigned i=0;i<size;++i)data+=(char)(n>>(i*8));};word(1,4);word(r->id,8);word(r->window,4);word(r->generation,4);word(r->body.size(),4);word(r->canvas,4);data+=r->body;
  memcpy(out,data.data(),data.size());g_web_bytes-=r->body.size();r->body.clear();r->state=2;r->active=true;}
 inv_unlock();
}
static bool web_reply(const void *wire,unsigned size){if(!wire||size<16||size>16+XU_WEB_MAX_BODY)return false;auto *p=(const unsigned char *)wire;
 if(memcmp(p,"XWR1",4)||xu_web_word(p,12)>4)return false;uint64_t id=(uint64_t)xu_web_word(p,4)|((uint64_t)xu_web_word(p,8)<<32);bool notify=false;inv_lock();web_expire();auto *r=web_find(id);bool accepted=r&&r->active;
 if(accepted){r->active=false;if(r->state==4)web_clear(*r);else if(r->state==2){if(size-16>XU_WEB_MAX_BYTES-g_web_bytes)web_terminal(*r,4,"response capacity exceeded",26);else web_terminal(*r,xu_web_word(p,12),(const char *)p+16,size-16);notify=true;}}
 inv_unlock();if(notify){std::string marker="content.__web_reply\t"+std::to_string(id)+"\n";xu_ui_mem_append("xu_ui_cmd.txt",marker.c_str(),0);xu_ui_host_kick();}wake_waiters();return accepted;
}

void xu_ui_web_invoke_shutdown(void){inv_lock();g_web_stopped=true;
 for(auto &r:g_web_requests)if(r.state){if(r.active){g_web_bytes-=r.body.size()+r.result.size();r.body.clear();r.result.clear();r.state=4;}else web_clear(r);}
 inv_unlock();wake_waiters();
}
static bool web_running(){inv_lock();bool running=!g_web_stopped;inv_unlock();return running;}
