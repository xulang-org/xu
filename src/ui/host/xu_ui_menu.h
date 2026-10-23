// Structured menus are decoded completely before replacing a live native menu.
#pragma once
#include "xu_ui_mem.h"
#include <string>
#include <vector>
#include <stdlib.h>
#include <stdint.h>
struct XuMenuEntry {int parent=-1,kind=0,flags=0,key=0,mods=0,depth=0;std::string id,label;};
static inline bool xu_menu_number(const std::string &s,int *out,bool parent=false){
 if(parent && s=="-1"){*out=-1;return true;}if(s.empty()||s.size()>8)return false;unsigned n=0;
 for(char c:s){if(c<'0'||c>'9')return false;n=n*10+(c-'0');if(n>65536)return false;}*out=(int)n;return true;
}
static inline bool xu_menu_hex(const std::string &s,std::string *out){
 if(s.size()%2)return false;out->clear();for(size_t i=0;i<s.size();i+=2){int a=s[i],b=s[i+1];
 auto digit=[](int c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:-1;};a=digit(a);b=digit(b);if(a<0||b<0||!(a|b))return false;out->push_back((char)(a*16+b));}return true;
}
static inline bool xu_menu_utf8(const std::string &s){
 const auto *p=(const unsigned char *)s.data();size_t i=0;while(i<s.size()){unsigned c=p[i++],n=0,min=0;
 if(c<128)continue;if(c>=194&&c<=223){n=1;c&=31;min=128;}else if(c>=224&&c<=239){n=2;c&=15;min=2048;}else if(c>=240&&c<=244){n=3;c&=7;min=65536;}else return false;
 if(i+n>s.size())return false;while(n--){unsigned b=p[i++];if((b&192)!=128)return false;c=(c<<6)|(b&63);}if(c<min||c>0x10ffff||(c>=0xd800&&c<=0xdfff))return false;}return true;
}
static inline bool xu_menu_parse(const std::string &body,std::vector<XuMenuEntry> *out){
 if(body.size()>524288 || body.rfind("XUM1\n",0)!=0)return false;std::vector<XuMenuEntry> entries;size_t pos=5;
 while(pos<body.size()){size_t end=body.find('\n',pos);if(end==std::string::npos || entries.size()==256)return false;auto line=body.substr(pos,end-pos);pos=end+1;
  std::vector<std::string> f;size_t start=0;for(size_t i=0;i<=line.size();++i)if(i==line.size()||line[i]=='\t'){f.push_back(line.substr(start,i-start));start=i+1;}
  XuMenuEntry e;if(f.size()!=7||!xu_menu_number(f[0],&e.parent,true)||!xu_menu_number(f[1],&e.kind)||!xu_menu_number(f[2],&e.flags)||!xu_menu_number(f[3],&e.key)||!xu_menu_number(f[4],&e.mods)||!xu_menu_hex(f[5],&e.id)||!xu_menu_hex(f[6],&e.label))return false;
  if(e.parent< -1||e.parent>=(int)entries.size()||e.kind<1||e.kind>4||e.flags>3||e.mods>31||e.id.size()>64||e.label.size()>1024||!xu_menu_utf8(e.label)||
     (e.key && !((e.key>=32&&e.key<=126)||(e.key>=288&&e.key<300))))return false;
  e.depth=1;if(e.parent>=0){if(entries[e.parent].kind!=2)return false;e.depth=entries[e.parent].depth+1;}else if(e.kind!=2)return false;if(e.depth>8)return false;
  if(e.kind==3){if(!e.id.empty()||!e.label.empty()||e.key||(e.flags&2))return false;}
  else {if(e.id.empty()||e.label.empty())return false;for(char c:e.id)if(!((c>='0'&&c<='9')||(c>='a'&&c<='z')||(c>='A'&&c<='Z')||c=='_'||c=='-'||c=='.'))return false;for(auto &old:entries)if(old.id==e.id)return false;}
  if((e.flags&2)&&e.kind!=4)return false;
  if(e.kind!=1&&e.kind!=4&&((e.flags&2)||e.key||e.mods))return false;
  // Disabled ancestors disable accelerators as well as visible items.
  if(e.parent>=0 && !(entries[e.parent].flags&1))e.flags&=~1;
  entries.push_back(e);
 }
 *out=std::move(entries);return true;
}
static inline std::string xu_menu_read(unsigned id,unsigned generation){
 std::string key=id==1?"xu_ui_menu_v2.txt":"window/"+std::to_string(id)+"/"+std::to_string(generation)+"/xu_ui_menu_v2.txt";
 std::string path=":xu:/"+key;unsigned size=0;xu_ui_mem_try_read_len(path.c_str(),&size);if(!size||size>524288)return {};std::vector<char> data(size+1);int n=xu_ui_mem_get(key.c_str(),data.data(),(unsigned)data.size());return n<0?std::string():std::string(data.data(),n);
}
