// Opaque bytes, bounded pending table and exact window generation ownership.
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define XU_WEB_MAX_PENDING 64u
#define XU_WEB_MAX_BODY (1024u*1024u)
#define XU_WEB_MAX_BYTES (8u*1024u*1024u)
uint64_t xu_ui_web_invoke_start(unsigned window,unsigned generation,const char *key32,const void *body,unsigned length,unsigned timeout_ms);
int xu_ui_web_invoke_cancel(unsigned window,unsigned generation,const char *key32);
// Detaches one terminal result on the owning UI thread. Caller free().
// 0 success, 1 cancelled, 2 timed out, 3 window closed, 4 failed.
void *xu_ui_web_invoke_result(uint64_t id,unsigned *length,unsigned *status);
void xu_ui_web_invoke_shutdown(void);
void xu_ui_web_invoke_close(unsigned window,unsigned generation);
int xu_ui_web_invoke_owner(uint64_t id,unsigned *identity);
#ifdef __cplusplus
}
#include <string>
#include <string.h>
static inline unsigned xu_web_word(const void *data,unsigned offset){auto *p=(const unsigned char *)data+offset;return p[0]|((unsigned)p[1]<<8)|((unsigned)p[2]<<16)|((unsigned)p[3]<<24);}
static inline bool xu_web_binary(const std::string &body){return body.size()>=16 && !memcmp(body.data(),"XWV1",4);}
static inline unsigned xu_web_timeout(const std::string &body){return xu_web_binary(body)?xu_web_word(body.data(),4):30000;}
static inline std::string xu_web_response(bool binary,unsigned status,const void *data,unsigned size){
 std::string out;if(!binary){if(status)return "ok: false\nerror: !s request "+std::to_string(status)+"\n";return std::string((const char *)data,size);}
 out="XWO1";for(unsigned n:{status,size})for(unsigned i=0;i<4;++i)out+=(char)(n>>(i*8));out.append((const char *)data,size);return out;
}
#endif
#ifdef __cplusplus
// JSON string literal for a host-pushed legacy notification record.
static inline std::string xu_web_json(const std::string &value){
 static const char digits[]="0123456789abcdef";std::string out="\"";
 for(unsigned char c:value){if(c=='"'||c=='\\'){out+='\\';out+=(char)c;}else if(c<32){out+="\\u00";out+=digits[c>>4];out+=digits[c&15];}else out+=(char)c;}return out+'"';
}
// WebView2 returns JSON, including UTF-16 surrogate escapes inside strings.
static inline bool xu_web_unquote(const std::string &json,std::string *out){
 if(json.size()<2||json.front()!='"'||json.back()!='"')return false;out->clear();
 auto hex=[](char c)->int{return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;};
 auto scalar=[&](size_t &i,unsigned *n){if(i+4>=json.size())return false;*n=0;for(unsigned j=0;j<4;++j){int d=hex(json[++i]);if(d<0)return false;*n=(*n<<4)|(unsigned)d;}return true;};
 for(size_t i=1;i+1<json.size();++i){unsigned c=(unsigned char)json[i];if(c<32||c=='"')return false;
  if(c!='\\'){out->push_back((char)c);continue;}if(++i+1>=json.size())return false;c=(unsigned char)json[i];
  if(c=='"'||c=='\\'||c=='/')out->push_back((char)c);
  else if(c=='b')out->push_back('\b');else if(c=='f')out->push_back('\f');else if(c=='n')out->push_back('\n');else if(c=='r')out->push_back('\r');else if(c=='t')out->push_back('\t');
  else if(c=='u'){unsigned n=0;if(!scalar(i,&n))return false;
   if(n>=0xd800&&n<=0xdbff){if(i+2>=json.size()||json[i+1]!='\\'||json[i+2]!='u')return false;i+=2;unsigned low=0;if(!scalar(i,&low)||low<0xdc00||low>0xdfff)return false;n=0x10000+((n-0xd800)<<10)+(low-0xdc00);}
   else if(n>=0xdc00&&n<=0xdfff)return false;
   if(n<128)out->push_back((char)n);else if(n<2048){out->push_back((char)(0xc0|(n>>6)));out->push_back((char)(0x80|(n&63)));}
   else if(n<65536){out->push_back((char)(0xe0|(n>>12)));out->push_back((char)(0x80|((n>>6)&63)));out->push_back((char)(0x80|(n&63)));}
   else{out->push_back((char)(0xf0|(n>>18)));out->push_back((char)(0x80|((n>>12)&63)));out->push_back((char)(0x80|((n>>6)&63)));out->push_back((char)(0x80|(n&63)));}
  }else return false;
 }return true;
}
#endif
#ifdef __cplusplus
#include "xu_ui_requests.h"
static inline bool xu_web_native_take(const char *command,unsigned canvas,unsigned generation,uint64_t *id,unsigned *kind,std::string *value){
 if(!xu_request_marker(command,id))return false;char *wire=NULL;for(*kind=8;*kind<=12;++*kind){wire=xu_ui_request_take_kind(*id,canvas,generation,*kind);if(wire)break;}if(!wire)return false;
 const char *seed=strrchr(wire,'\t');bool ok=seed&&xu_request_unhex(seed+1,value);free(wire);if(!ok){xu_ui_request_complete(*id,XU_REQUEST_FAILED,"invalid request",15);*kind=0;}return true;
}
static inline void xu_web_native_complete(uint64_t id,bool success,const std::string &value){
 if(!xu_ui_request_alive(id))return;
 if(value.size()>XU_UI_REQUEST_MAX_TEXT)xu_ui_request_complete(id,XU_REQUEST_FAILED,"result exceeds 64 KiB",21);
 else if(!xu_ui_request_complete(id,success?XU_REQUEST_COMPLETED:XU_REQUEST_FAILED,value.data(),(unsigned)value.size()))xu_ui_request_complete(id,XU_REQUEST_FAILED,"invalid native result",21);
}
static inline bool xu_web_cookie_fields(const std::string &value,std::string *name,std::string *text,std::string *domain){
 std::vector<std::string> fields;size_t start=0;for(size_t i=0;i<=value.size();++i)if(i==value.size()||value[i]=='\t'){fields.push_back(value.substr(start,i-start));start=i+1;}
 return fields.size()==4&&fields[0]=="C1"&&xu_request_unhex(fields[1],name)&&xu_request_unhex(fields[2],text)&&xu_request_unhex(fields[3],domain)&&!name->empty()&&!domain->empty();
}
#endif
