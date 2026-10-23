// Bounded, toolkit-independent file-dialog options and path result codec.
#pragma once
#include "xu_ui_requests.h"
#include "xu_draw_frame.h"
#define XU_UI_FILE_MAX_ACTIVE 8u
#define XU_UI_FILE_MAX_PATHS 64u
struct XuUiFileFilter { std::string label;std::vector<std::string> extensions; };
struct XuUiFileOptions {
  bool multiple=false;
  std::string title,directory,name;
  std::vector<XuUiFileFilter> filters;
};
static inline bool xu_file_kind(unsigned kind){return kind>=XU_REQUEST_OPEN_FILES && kind<=XU_REQUEST_SELECT_FOLDERS;}
static inline bool xu_request_modal(unsigned kind){return kind==XU_REQUEST_PROMPT || xu_file_kind(kind);}
static inline std::vector<std::string> xu_file_fields(const std::string &text){
  std::vector<std::string> fields;size_t start=0;
  for(size_t i=0;i<=text.size();++i)if(i==text.size() || text[i]=='\t'){if(fields.size()==512)return {};fields.emplace_back(text,start,i-start);start=i+1;}
  return fields;
}
static inline bool xu_file_number(const std::string &text,unsigned limit,unsigned *out){
  if(text.empty() || text.size()>10 || (text.size()>1 && text[0]=='0'))return false;
  unsigned n=0;for(unsigned char c:text){if(c<'0' || c>'9' || c-'0'>limit || n>(limit-(c-'0'))/10)return false;n=n*10+c-'0';}
  *out=n;return true;
}
static inline bool xu_file_text(const std::string &hex,unsigned max,std::string *out){
  return hex.size()/2<=max && xu_request_unhex(hex,out) && xdf_utf8((const unsigned char *)out->data(),out->size());
}
static inline bool xu_file_absolute(const std::string &p){
  return !p.empty() && (p[0]=='/' || (p.size()>2 && ((p[0]>='a' && p[0]<='z') || (p[0]>='A' && p[0]<='Z')) && p[1]==':' && (p[2]=='\\' || p[2]=='/')) || (p.size()>2 && p[0]=='\\' && p[1]=='\\'));
}
static inline bool xu_file_extension(const std::string &ext){
  if(ext=="*")return true;
  if(ext.empty() || ext.size()>32 || ext.front()=='.' || ext.back()=='.')return false;
  unsigned char last=0;
  for(unsigned char c:ext){if(!((c>='a' && c<='z') || (c>='A' && c<='Z') || (c>='0' && c<='9') || c=='_' || c=='-' || c=='+' || (c=='.' && last!='.')))return false;last=c;}
  return true;
}
// F1 / multiple / directory_hex / name_hex / filter_count /
// repeated(label_hex / extension_count / extensions...), all tab separated.
static inline bool xu_file_options(const std::string &seed,unsigned kind,XuUiFileOptions *out){
  if(!xu_file_kind(kind) || seed.size()>XU_UI_REQUEST_MAX_TEXT)return false;
  auto fields=xu_file_fields(seed);unsigned multiple=0,count=0;
  if(fields.size()<5 || fields[0]!="F1" || !xu_file_number(fields[1],1,&multiple) ||
    !xu_file_text(fields[2],8192,&out->directory) || !xu_file_text(fields[3],1024,&out->name) || !xu_file_number(fields[4],16,&count))return false;
  if((kind==XU_REQUEST_SAVE_FILE && multiple) || (kind!=XU_REQUEST_SAVE_FILE && !out->name.empty()) ||
    (!out->directory.empty() && !xu_file_absolute(out->directory)) || out->name=="." || out->name==".." || out->name.find_first_of("/\\")!=std::string::npos ||
    (kind==XU_REQUEST_SELECT_FOLDERS && count))return false;
  out->multiple=multiple!=0;out->filters.clear();size_t cursor=5;
  for(unsigned i=0;i<count;++i){
    XuUiFileFilter filter;unsigned size=0;
    if(cursor+2>fields.size() || !xu_file_text(fields[cursor++],256,&filter.label) || filter.label.empty() || !xu_file_number(fields[cursor++],16,&size) || !size || size>fields.size()-cursor)return false;
    for(unsigned j=0;j<size;++j){if(!xu_file_extension(fields[cursor]))return false;filter.extensions.push_back(fields[cursor++]);}
    out->filters.push_back(std::move(filter));
  }
  return cursor==fields.size();
}
static inline std::string xu_file_hex(const std::string &text){
  static const char *digits="0123456789abcdef";std::string hex;hex.reserve(text.size()*2);
  for(unsigned char c:text){hex+=digits[c>>4];hex+=digits[c&15];}return hex;
}
static inline bool xu_file_result_valid(const char *data,unsigned len,unsigned kind,unsigned max_paths=XU_UI_FILE_MAX_PATHS){
  if(!data || len>XU_UI_REQUEST_MAX_TEXT)return false;
  auto fields=xu_file_fields(std::string(data,len));unsigned count=0;
  if(fields.size()<3 || fields[0]!="XUF1" || !xu_file_number(fields[1],XU_UI_FILE_MAX_PATHS,&count) || !count || count>max_paths || fields.size()!=count+2 || (kind==XU_REQUEST_SAVE_FILE && count!=1))return false;
  for(unsigned i=2;i<fields.size();++i){std::string path;if(!xu_file_text(fields[i],XU_UI_REQUEST_MAX_TEXT/2,&path) || !xu_file_absolute(path))return false;}
  return true;
}
static inline bool xu_file_result(const std::vector<std::string> &paths,std::string *out){
  if(paths.empty() || paths.size()>XU_UI_FILE_MAX_PATHS)return false;
  std::string value="XUF1\t"+std::to_string(paths.size());
  for(auto &path:paths){if(value.size()>=XU_UI_REQUEST_MAX_TEXT || path.size()>(XU_UI_REQUEST_MAX_TEXT-value.size()-1)/2 || !xu_file_absolute(path) || !xdf_utf8((const unsigned char *)path.data(),path.size()))return false;value+='\t';value+=xu_file_hex(path);}
  *out=std::move(value);return true;
}
static inline bool xu_file_take(const char *command,unsigned canvas,unsigned generation,uint64_t *id,unsigned *kind,XuUiFileOptions *options){
  if(!xu_request_marker(command,id))return false;char *wire=NULL;
  for(*kind=XU_REQUEST_OPEN_FILES;*kind<=XU_REQUEST_SELECT_FOLDERS;++*kind)if((wire=xu_ui_request_take_kind(*id,canvas,generation,*kind)))break;
  if(!wire)return false;auto fields=xu_file_fields(wire);free(wire);std::string seed;
  bool valid=fields.size()==9 && xu_file_text(fields[7],4096,&options->title) && xu_request_unhex(fields[8],&seed) && xu_file_options(seed,*kind,options);
  if(!valid){xu_ui_request_complete(*id,XU_REQUEST_FAILED,"invalid file options",20);*kind=0;}
  return true;
}
