#pragma once
#include "xu_ui_requests.h"
#include <string>
#include <stdio.h>
static inline std::string xu_screen_hex(const std::string &value){static const char digits[]="0123456789abcdef";std::string out;for(unsigned char c:value){out+=digits[c>>4];out+=digits[c&15];}return out;}
static inline void xu_screen_append(std::string &out,const std::string &id,const std::string &name,unsigned flags,
 double x,double y,double w,double h,double wx,double wy,double ww,double wh,double sx,double sy){
 char values[768];snprintf(values,sizeof(values),"\t%u\t%.17g\t%.17g\t%.17g\t%.17g\t%.17g\t%.17g\t%.17g\t%.17g\t%.17g\t%.17g\n",flags,x,y,w,h,wx,wy,ww,wh,sx,sy);
 out+=xu_screen_hex(id)+"\t"+xu_screen_hex(name)+values;
}
static inline bool xu_screen_take(const char *command,unsigned canvas,unsigned generation,uint64_t *id){
 if(!xu_request_marker(command,id))return false;char *wire=xu_ui_request_take_kind(*id,canvas,generation,XU_REQUEST_SCREENS);if(!wire)return false;free(wire);return true;
}
