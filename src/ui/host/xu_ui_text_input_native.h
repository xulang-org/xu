// Native-side snapshot decoder. No caller borrows pointers into the registry.
#pragma once
#include "xu_ui_text_input.h"
#include "xu_draw_frame.h"
#include <string>
#include <utility>
#include <stdlib.h>
struct XuTextInputSnapshot {
  uint64_t id=0, revision=0;
  unsigned window=0,canvas=0,generation=0,flags=0,serial=0;
  unsigned anchor=0,focus=0,start=0,end=0,preedit_anchor=0,preedit_focus=0;
  double caret[4]={};
  std::string source,preedit;
  bool composing() const { return (flags&4)!=0; }
  bool ready() const { return (flags&2)!=0; }
  static bool boundary(const std::string &text,unsigned at) {
    return at<=text.size() && (at==text.size() || ((unsigned char)text[at]&0xc0)!=0x80);
  }
  std::string display() const { return composing() ? source.substr(0,start)+preedit+source.substr(end) : source; }
  unsigned display_anchor() const { return composing() ? start+preedit_anchor : anchor; }
  unsigned display_focus() const { return composing() ? start+preedit_focus : focus; }
  bool source_index(unsigned display_index,bool after,unsigned *result) const {
    if (!result || !boundary(display(),display_index)) return false;
    if (!composing() || display_index<start) *result=display_index;
    else if (preedit.empty() && display_index==start) *result=after ? end : start;
    else if (display_index==start) *result=start;
    else if (display_index>=start+preedit.size()) *result=display_index-(unsigned)preedit.size()+(end-start);
    else *result=after ? end : start;
    return true;
  }
  bool decode(const void *data,unsigned length) {
    if (!data || length<112 || length>XU_UI_TEXT_INPUT_SNAPSHOT_BYTES) return false;
    auto *p=(const unsigned char *)data;
    if (memcmp(p,"XIS1",4) || xdf_u16(p+4)!=1 || xdf_u32(p+28)!=2 || xdf_u32(p+108)) return false;
    XuTextInputSnapshot next;
    next.flags=xdf_u16(p+6); next.id=(uint64_t)xdf_u32(p+8)|((uint64_t)xdf_u32(p+12)<<32);
    next.revision=(uint64_t)xdf_u32(p+32)|((uint64_t)xdf_u32(p+36)<<32);
    next.window=xdf_u32(p+16); next.canvas=xdf_u32(p+20); next.generation=xdf_u32(p+24);
    unsigned size=xdf_u32(p+80),marked=xdf_u32(p+84);
    if(next.flags>7 || !next.id || next.id>INT64_MAX || !next.revision || next.revision>INT64_MAX ||
       !next.window || next.window>INT32_MAX || !next.canvas || next.canvas>INT32_MAX || !next.generation ||
       size>16384 || marked>16384 || length!=112+size+marked || !xdf_utf8(p+112,size) || !xdf_utf8(p+112+size,marked)) return false;
    next.source.assign((const char *)p+112,size); next.preedit.assign((const char *)p+112+size,marked);
    next.anchor=xdf_u32(p+72);next.focus=xdf_u32(p+76);next.start=xdf_u32(p+88);next.end=xdf_u32(p+92);
    next.preedit_anchor=xdf_u32(p+96);next.preedit_focus=xdf_u32(p+100);next.serial=xdf_u32(p+104);
    if(!next.serial || !boundary(next.source,next.anchor) || !boundary(next.source,next.focus) || next.start>next.end ||
       !boundary(next.source,next.start) || !boundary(next.source,next.end) || !boundary(next.preedit,next.preedit_anchor) ||
       !boundary(next.preedit,next.preedit_focus) || size-(next.end-next.start)+marked>16384 ||
       (!next.composing() && (marked || next.start || next.end))) return false;
    for(unsigned i=0;i<4;++i) { next.caret[i]=xdf_f64(p+40+i*8); if(!isfinite(next.caret[i]) || fabs(next.caret[i])>1048576) return false; }
    if(next.caret[2]<0 || next.caret[2]>16384 || next.caret[3]<=0 || next.caret[3]>16384) return false;
    *this=std::move(next); return true;
  }
};
static inline bool xu_text_input_read(uint64_t id,unsigned canvas,unsigned generation,bool take,XuTextInputSnapshot *out) {
  if (!out) return false;
  unsigned length=0; void *wire=xu_ui_text_input_snapshot(id,canvas,generation,take?1:0,&length);
  if (!wire) return false;
  bool valid=false;
  try { valid=out->decode(wire,length) && out->id==id && out->canvas==canvas && out->generation==generation; }
  catch (...) { valid=false; }
  free(wire); return valid;
}
static inline bool xu_text_input_marker(const char *command,uint64_t *id) {
  const char prefix[]="__text_input\t";
  if (!command || !id || strncmp(command,prefix,sizeof(prefix)-1)) return false;
  const char *at=command+sizeof(prefix)-1; if(!*at) return false;
  uint64_t value=0;
  for(;*at;++at) {
    if(*at<'0' || *at>'9' || value>((uint64_t)INT64_MAX-(unsigned)(*at-'0'))/10) return false;
    value=value*10+(unsigned)(*at-'0');
  }
  if(!value) return false; *id=value; return true;
}
