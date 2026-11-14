#include "phone.h"
#include "../xu_ui_commands.h"
#include "../xu_draw_frame.h"
#include "../xu_ui_input.h"
#include "../xu_ui_text.h"
#include "../xu_ui_text_input.h"
#include "../xu_ui_images.h"
#include "../xu_ui_display_list.h"
#include <algorithm>
#include <cmath>
#include <mutex>
#include <string>
#include <vector>

static std::mutex host_lock;
static unsigned generation;
static double width = 390, height = 844, scale = 1;
static double inset_top = 0, inset_bottom = 0, inset_left = 0, inset_right = 0, inset_ime = 0;
static bool input_enabled, redraw, reduced_motion;
static std::string last_frame, last_insets;
static XuContentHost content{};
static void event(const char *line) { xu_ui_mem_append("xu_ui_shell_event.txt", line, 1); }
static std::string number(double n) { char b[64]; snprintf(b, sizeof(b), "%.17g", n); return b; }
static std::string quote(const char *s, unsigned n) {
  std::string out="\"";
  auto escape=[&](unsigned value){char b[8];snprintf(b,sizeof(b),"\\u%04x",value);out+=b;};
  for(unsigned i=0;i<n;){
    unsigned c=(unsigned char)s[i++];
    if(c=='"'||c=='\\'){out+='\\';out+=(char)c;}
    else if(c<32||c=='<'||c=='>'||c=='&')escape(c);
    else if(c<128)out+=(char)c;
    else {
      unsigned count=c<224?1:c<240?2:3;
      unsigned value=c&((1u<<(6-count))-1);
      for(unsigned j=0;j<count && i<n;++j)value=(value<<6)|((unsigned char)s[i++]&63);
      if(value<65536)escape(value);
      else {value-=65536;escape(0xd800+(value>>10));escape(0xdc00+(value&1023));}
    }
  }
  return out+'"';
}
// Canvas text uses the browser host's bounded text profile. Keep font metrics
// explicit; native shaping/IME is not claimed by this Phone rendering backend.
struct Text { std::string value, family; double size, line, width, weight, italic, align; };
static void *text_create(const char *family, unsigned family_len, const char *s, unsigned n,
                         const double *options, double *metrics, unsigned *cost) {
  auto *t = new Text{std::string(s,n),std::string(family?family:"",family_len),options[0],options[5]>0 ? options[5] : options[0]*1.2,options[1],options[2],options[3],options[4]};
  unsigned glyphs=0;
  for (unsigned i=0;i<n;++i) if (((unsigned char)s[i]&0xc0)!=0x80) ++glyphs;
  double w=glyphs*t->size*.6;
  if(t->width>0)w=std::min(w,t->width);
  metrics[0]=w; metrics[1]=t->line; metrics[2]=t->size*.8; metrics[3]=1;
  metrics[4]=0; metrics[5]=0; metrics[6]=w; metrics[7]=t->line;
  *cost=sizeof(Text)+n+family_len; return t;
}
static void text_destroy(void *p) { delete (Text *)p; }
static std::string frame(const XuUiFrameLease *lease, unsigned depth=0);
static void *list_create(const XuUiFrameLease *lease) { return new std::string(frame(lease,1)); }
static void list_destroy(void *p) { delete (std::string *)p; }
extern "C" void xu_draw_text_init() {
  xu_ui_text_set_backend(text_create,text_destroy);
  xu_ui_display_list_set_backend(list_create,list_destroy);
}
static std::string frame(const XuUiFrameLease *lease, unsigned depth) {
  if (depth>16) return "[]";
  unsigned length=0, cursor=32;
  const void *data=xu_ui_frame_data(lease,&length);
  std::string out="["; bool first=true; XuDrawCommand c{};
  while (xdf_next(data,length,&cursor,&c)==1) {
    if(!first)out+=','; first=false;
    out+='['+std::to_string(c.opcode)+','+std::to_string(c.rgba);
    for(double v:c.values)out+=','+number(v);
    if(c.opcode==XDF_TEXT)out+=','+quote(c.text,c.text_len);
    else if(c.opcode==XDF_TEXT_LAYOUT) {
      auto *text=xu_ui_frame_text(lease,c.image_id);
      auto *native=text?(Text *)xu_ui_text_native(text):nullptr;
      out+=','+(native?quote(native->value.data(),native->value.size()):"\"\"");
      out+=','+number(native?native->size:12);
      if(native)out+=",["+number(native->width)+','+number(native->weight)+','+number(native->italic)+','+number(native->align)+','+quote(native->family.data(),native->family.size())+']';
    } else if(c.opcode==XDF_PATH) {
      const auto *p=(const unsigned char *)c.text;
      unsigned flags=xdf_u32(p), n=xdf_u32(p+8), dashes=xdf_u32(p+12), pos=48+dashes*8;
      out+=",["+std::to_string(flags)+','+number(xdf_f64(p+16))+','+number(xdf_f64(p+24))+','+number(xdf_f64(p+32))+",[";
      for(unsigned i=0;i<dashes;++i){if(i)out+=',';out+=number(xdf_f64(p+48+i*8));}
      out+="],[";
      for(unsigned i=0;i<n;++i){if(i)out+=',';unsigned verb=xdf_u32(p+pos);pos+=4;out+='['+std::to_string(verb);
        for(unsigned j=0;j<xup_values(verb);++j){out+=','+number(xdf_f64(p+pos));pos+=8;}out+=']';}
      out+="]]";
    } else if(c.opcode==XDF_DISPLAY_LIST) {
      auto *list=xu_ui_frame_list(lease,c.image_id);
      auto *native=list?(std::string *)xu_ui_display_list_native(list):nullptr;
      out+=','+(native?*native:"[]");
    } else if(c.opcode==XDF_IMAGE) {
      unsigned w=0,h=0; auto *bitmap=xu_ui_frame_bitmap(lease,c.image_id);
      const auto *pixels=xu_ui_bitmap_pixels(bitmap,&w,&h);
      out+=",["+std::to_string(w)+','+std::to_string(h)+",[";
      if(pixels)for(unsigned i=0;i<w*h*4;++i){if(i)out+=',';out+=std::to_string(pixels[i]);}
      out+="]]";
    }
    out+=']';
  }
  return out+']';
}
extern "C" void xu_phone_resize(double w,double h,double s) {
  if(!std::isfinite(w)||!std::isfinite(h)||!std::isfinite(s)||w<=0||h<=0||s<=0)return;
  std::lock_guard<std::mutex> guard(host_lock);width=w;height=h;scale=s;
  if(generation)xu_ui_canvas_metrics(&content,w,h,(unsigned)(w*s),(unsigned)(h*s),s,s);
}
static double clamp_inset(double v) {
  if(!std::isfinite(v)||v<=0.0)return 0.0;
  return std::round(v*100.0)/100.0;
}
extern "C" void xu_phone_insets(double top,double bottom,double left,double right,double ime_bottom) {
  double t=clamp_inset(top),b=clamp_inset(bottom),l=clamp_inset(left),r=clamp_inset(right),ime=clamp_inset(ime_bottom);
  std::string encoded=number(t)+'\t'+number(b)+'\t'+number(l)+'\t'+number(r)+'\t'+number(ime);
  std::lock_guard<std::mutex> guard(host_lock);
  inset_top=t;inset_bottom=b;inset_left=l;inset_right=r;inset_ime=ime;
  bool changed=encoded!=last_insets;
  last_insets=encoded;
  xu_ui_mem_set("phone_insets",encoded.c_str());
  if(changed&&generation)xu_ui_canvas_metrics(&content,width,height,(unsigned)(width*scale),(unsigned)(height*scale),scale,scale);
}
extern "C" void xu_phone_reduced_motion(int enabled) {
  bool on=enabled!=0;
  std::lock_guard<std::mutex> guard(host_lock);
  bool changed=on!=reduced_motion;
  reduced_motion=on;
  xu_ui_mem_set("phone_reduced_motion",on?"1":"0");
  if(changed&&generation)event(("canvas_preferences\t1\t1\t"+std::to_string(generation)+(on?"\t1":"\t0")).c_str());
}
extern "C" void xu_phone_input(int kind,double x,double y,int buttons) {
  std::lock_guard<std::mutex> guard(host_lock);
  if(input_enabled && generation && kind>=72 && kind<=77)
    xu_ui_input_emit(&content,(unsigned)kind,x,y,0,0,1,buttons,0,0,0,0,kind==73?1:0);
}
extern "C" int xu_phone_overlay() {
  char enabled[4]{};
  return xu_ui_mem_get("phone_overlay",enabled,sizeof(enabled))==1 && enabled[0]=='1';
}
extern "C" int xu_phone_dark() {
  char enabled[4]{};
  return xu_ui_mem_get("phone_dark",enabled,sizeof(enabled))==1 && enabled[0]=='1';
}
extern "C" int xu_phone_back() {
  char enabled[4]{};
  if(xu_ui_mem_get("phone_back_enabled",enabled,sizeof(enabled))!=1 || enabled[0]!='1')return 0;
  event("navigate_back");return 1;
}
extern "C" void xu_phone_redraw() { std::lock_guard<std::mutex> guard(host_lock);redraw=true; }
extern "C" char *xu_phone_poll() {
  std::lock_guard<std::mutex> guard(host_lock);
  std::string next;
  if(!generation) {
    unsigned meta[6]{};
    if(xu_ui_window_info(1,0,meta,nullptr,0) && meta[4]==2 && xu_ui_window_claim(1,meta[1])) {
      generation=meta[1]; xu_draw_text_init();
      content.window_id=1;content.canvas_id=1;content.canvas_generation=generation;content.append_shell_event=event;
      xu_ui_window_ready(1,generation);
      xu_ui_window_event(1,generation,"window_ready");
      xu_ui_canvas_event(&content,true);
      xu_ui_canvas_metrics(&content,width,height,(unsigned)(width*scale),(unsigned)(height*scale),scale,scale);
      event("ready");
    }
  }
  std::string commands=xu_ui_take_commands(":xu:");
  size_t start=0;
  while(start<commands.size()) {
    auto end=commands.find('\n',start);if(end==std::string::npos)end=commands.size();
    std::string line=commands.substr(start,end-start);start=end+1;
    unsigned identity[2]{};const char *command=line.c_str();
    if(xu_ui_scoped_command(command,identity,&command) && (identity[0]!=1||identity[1]!=generation))continue;
    if(!strncmp(command,"content.",8))command+=8;
    else if(!strncmp(command,"shell.",6))command+=6;
    if(!strncmp(command,"__draw_frame\t",13)) {
      auto ticket=strtoull(command+13,nullptr,10);
      auto *lease=xu_ui_draw_acquire_for(ticket,1,generation);
      if(lease){next=frame(lease);xu_ui_frame_release(lease);}
    } else if(!strncmp(command,"input_enabled\t",14))input_enabled=strcmp(command+14,"0")!=0;
    else if(!strncmp(command,"__request\t",10)) {
      uint64_t id=0;
      if(xu_request_id(command+10,&id)) {
        char *wire=xu_ui_request_take(id,1,generation);
        if(wire){free(wire);xu_ui_request_complete(id,XU_REQUEST_UNSUPPORTED,"unavailable on Phone",20);}
      }
    } else if(!strncmp(command,"__text_input\t",13)) {
      uint64_t id=0;
      if(xu_request_id(command+13,&id))xu_ui_text_input_stop(id,1,generation,XUTI_NATIVE_UNAVAILABLE);
    }
    else if(!strcmp(command,"close")||!strcmp(command,"quit_app"))xu_phone_stop();
    else if(!strcmp(command,"motion_preferences"))event(("canvas_preferences\t1\t1\t"+std::to_string(generation)+(reduced_motion?"\t1":"\t0")).c_str());
    else if(!strncmp(command,"__window_open\t1\t",16)||!strncmp(command,"__window_bind\t1\t",16)||!strncmp(command,"cursor\t",7)||!strncmp(command,"pan_enabled\t",12)||!strcmp(command,"show")){}
    else if(!line.empty())xu_ui_window_event(1,generation,"command_unsupported");
  }
  if(!next.empty())last_frame=next;
  else if(redraw)next=last_frame;
  redraw=false;
  return next.empty()?nullptr:strdup(next.c_str());
}
