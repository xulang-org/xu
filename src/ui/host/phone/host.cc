#include "phone.h"
#include "../xu_ui_commands.h"
#include "../xu_draw_frame.h"
#include "../xu_ui_input.h"
#include "../xu_ui_text.h"
#include "../xu_ui_text_input.h"
#include "../xu_ui_text_input_native.h"
#include "../xu_ui_grapheme.h"
#include "../xu_ui_images.h"
#include "../xu_ui_display_list.h"
#include <algorithm>
#include <climits>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

static std::mutex host_lock;
static unsigned generation;
static double width = 390, height = 844, scale = 1;
static double inset_top = 0, inset_bottom = 0, inset_left = 0, inset_right = 0, inset_ime = 0;
static bool input_enabled, redraw, reduced_motion;
static uint64_t active_input_id = 0;
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
static unsigned decode_utf8(const char *s, unsigned n, unsigned offset, unsigned *advance) {
  if (!s || offset >= n) { if (advance) *advance = 0; return 0; }
  unsigned c = (unsigned char)s[offset];
  if (c < 0x80) { if (advance) *advance = 1; return c; }
  unsigned cont = c < 0xe0 ? 1 : c < 0xf0 ? 2 : 3;
  if (offset + cont >= n) { if (advance) *advance = n - offset; return 0xfffd; }
  unsigned cp = c & ((1u << (6u - cont)) - 1u);
  for (unsigned i = 1; i <= cont; ++i) cp = (cp << 6u) | ((unsigned char)s[offset + i] & 63u);
  if (advance) *advance = cont + 1u;
  return cp;
}
static double codepoint_width_factor(unsigned cp) {
  if (cp == ' ') return 0.28;
  switch (cp) {
    case '.': case ',': case ':': case ';': case '!': case '?': case '\'': case '"':
    case '`': case '|': case 'i': case 'l': case 'I': case 'j': case '(': case ')':
    case '[': case ']':
      return 0.34;
    case 'f': case 'r': case 't': case '-': case '/': case '\\':
      return 0.42;
    case 'm': case 'w':
      return 0.82;
    case 'M': case 'W':
      return 0.84;
    default:
      break;
  }
  if (cp >= 'A' && cp <= 'Z') return 0.68;
  if ((cp >= 'a' && cp <= 'z') || (cp >= '0' && cp <= '9')) return 0.56;
  if (cp < 0x1100) return 0.56;
  if ((cp >= 0x2e80 && cp <= 0x9fff) || (cp >= 0xac00 && cp <= 0xd7af) ||
      (cp >= 0xf900 && cp <= 0xfaff) || (cp >= 0xff00 && cp <= 0xff60) ||
      (cp >= 0xffe0 && cp <= 0xffee) || cp >= 0x1f000) return 1.0;
  return 0.58;
}
// Canvas text renders via WebView 2D canvas and queries grapheme clusters using
// matched proportional/CJK advance estimates so caret placement and hit testing work cleanly.
struct Text {
  struct Cluster { unsigned start, length; double x0, x1; };
  std::string value, family;
  double size, line, width, weight, italic, align, total_width, origin_x;
  std::vector<Cluster> clusters;
};
static void *text_create(const char *family, unsigned family_len, const char *s, unsigned n,
                         const double *options, double *metrics, unsigned *cost) {
  double sz = (options && std::isfinite(options[0]) && options[0] > 0) ? options[0] : 12.0;
  double ln = (options && std::isfinite(options[5]) && options[5] > 0) ? options[5] : sz * 1.2;
  auto *t = new Text{std::string(s ? s : "", n), std::string(family ? family : "", family_len),
                     sz, ln, options ? options[1] : 0.0, options ? options[2] : 400.0,
                     options ? options[3] : 0.0, options ? options[4] : 0.0, 0.0, 0.0, {}};
  std::vector<unsigned> stops;
  if (n && s && xu_ui_grapheme::boundaries(s, n, &stops) && stops.size() >= 2) {
    double cursor = 0.0;
    double weight_scale = t->weight >= 600.0 ? 1.03 : 1.0;
    t->clusters.reserve(stops.size() - 1u);
    for (size_t i = 0; i + 1 < stops.size(); ++i) {
      unsigned start = stops[i], len = stops[i + 1] - stops[i];
      unsigned adv = 0;
      unsigned cp = decode_utf8(s, n, start, &adv);
      double w = codepoint_width_factor(cp) * t->size * weight_scale;
      t->clusters.push_back(Text::Cluster{start, len, cursor, cursor + w});
      cursor += w;
    }
    t->total_width = cursor;
  } else if (n && s) {
    unsigned glyphs = 0;
    for (unsigned i = 0; i < n; ++i) if (((unsigned char)s[i] & 0xc0) != 0x80) ++glyphs;
    t->total_width = glyphs * t->size * 0.6;
  }
  if (t->width > 0) {
    if (t->align == 1.0) t->origin_x = std::max(0.0, (t->width - t->total_width) * 0.5);
    else if (t->align == 2.0) t->origin_x = std::max(0.0, t->width - t->total_width);
    if (t->origin_x > 0.0) {
      for (auto &c : t->clusters) { c.x0 += t->origin_x; c.x1 += t->origin_x; }
    }
  }
  double w = t->width > 0 ? std::min(t->total_width, t->width) : t->total_width;
  metrics[0] = w; metrics[1] = t->line; metrics[2] = t->size * 0.8; metrics[3] = 1;
  metrics[4] = t->origin_x; metrics[5] = 0; metrics[6] = w; metrics[7] = t->line;
  *cost = (unsigned)(sizeof(Text) + n + family_len + t->clusters.size() * sizeof(Text::Cluster));
  return t;
}
static void text_destroy(void *p) { delete (Text *)p; }
static int text_query_native(void *pointer, unsigned mode, unsigned index, unsigned trailing,
                             double x, double y, double *out) {
  if (!pointer || !out || mode > 1 || trailing > 1) return 0;
  auto *t = (const Text *)pointer;
  if (t->clusters.empty()) {
    out[0] = 0; out[1] = 0; out[2] = (mode == 1 && trailing) ? 1 : 0;
    out[3] = (mode == 1 || (x >= 0.0 && x <= std::max(t->width, 1.0) && y >= 0.0 && y <= t->line)) ? 1 : 0;
    out[4] = t->origin_x; out[5] = 0; out[6] = t->line;
    return 1;
  }
  if (mode == 0) {
    bool inside = y >= 0.0 && y <= t->line && x >= t->origin_x && x <= t->origin_x + t->total_width;
    const Text::Cluster *chosen = &t->clusters.back();
    unsigned tr = 1;
    double caret_x = chosen->x1;
    if (x <= t->clusters.front().x0) {
      chosen = &t->clusters.front(); tr = 0; caret_x = chosen->x0;
    } else if (x < t->clusters.back().x1) {
      for (const auto &c : t->clusters) {
        if (x <= c.x1) {
          chosen = &c;
          double mid = (c.x0 + c.x1) * 0.5;
          tr = x >= mid ? 1 : 0;
          caret_x = tr ? c.x1 : c.x0;
          break;
        }
      }
    }
    out[0] = chosen->start; out[1] = chosen->length; out[2] = tr;
    out[3] = inside ? 1 : 0; out[4] = caret_x; out[5] = 0; out[6] = t->line;
    return 1;
  }
  const auto &last = t->clusters.back();
  unsigned end_byte = last.start + last.length;
  if (index >= end_byte) {
    out[0] = end_byte; out[1] = 0; out[2] = trailing ? 1 : 0; out[3] = 1;
    out[4] = last.x1; out[5] = 0; out[6] = t->line;
    return 1;
  }
  for (const auto &c : t->clusters) {
    if (index < c.start + c.length) {
      out[0] = c.start; out[1] = c.length; out[2] = trailing ? 1 : 0; out[3] = 1;
      out[4] = trailing ? c.x1 : c.x0; out[5] = 0; out[6] = t->line;
      return 1;
    }
  }
  return 0;
}
static std::string frame(const XuUiFrameLease *lease, unsigned depth=0);
static void *list_create(const XuUiFrameLease *lease) { return new std::string(frame(lease,1)); }
static void list_destroy(void *p) { delete (std::string *)p; }
extern "C" void xu_draw_text_init() {
  xu_ui_text_set_query_backend(text_query_native);
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
static unsigned utf8_to_utf16_pos(const std::string &s, unsigned byte_pos) {
  unsigned limit = std::min(byte_pos, (unsigned)s.size());
  unsigned u16 = 0;
  for (unsigned i = 0; i < limit;) {
    unsigned adv = 0;
    unsigned cp = decode_utf8(s.data(), limit, i, &adv);
    if (!adv) break;
    u16 += (cp >= 0x10000u) ? 2u : 1u;
    i += adv;
  }
  return u16;
}
static unsigned utf16_to_utf8_pos(const std::string &s, unsigned u16_pos, bool snap_end) {
  unsigned u16 = 0, i = 0, n = (unsigned)s.size();
  while (i < n) {
    if (u16 >= u16_pos) return i;
    unsigned adv = 0;
    unsigned cp = decode_utf8(s.data(), n, i, &adv);
    if (!adv) break;
    unsigned u16_len = (cp >= 0x10000u) ? 2u : 1u;
    if (u16 + u16_len > u16_pos) return snap_end ? (i + adv) : i;
    u16 += u16_len;
    i += adv;
  }
  return n;
}
static uint64_t resolve_input_id(uint64_t id, unsigned *out_gen) {
  uint64_t target = 0;
  unsigned gen = 0;
  {
    std::lock_guard<std::mutex> guard(host_lock);
    gen = generation;
    if (gen && active_input_id && (!id || id == active_input_id)) target = active_input_id;
  }
  if (!target) return 0;
  if (!xu_ui_text_input_active(target)) {
    std::lock_guard<std::mutex> guard(host_lock);
    if (active_input_id == target) active_input_id = 0;
    return 0;
  }
  if (out_gen) *out_gen = gen;
  return target;
}
extern "C" void xu_phone_key(int kind, int key, int repeat, int modifiers) {
  std::lock_guard<std::mutex> guard(host_lock);
  if (generation && (kind == XUI_KEY_DOWN || kind == XUI_KEY_UP))
    xu_ui_input_emit(&content, (unsigned)kind, 0, 0, 0, 0, 0, 0, (unsigned)modifiers, (unsigned)key, 0, (unsigned)repeat, 0);
}
extern "C" char *xu_phone_text_input_state() {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(0, &gen);
  if (!target) return strdup("{\"active\":false}");
  XuTextInputSnapshot snap;
  if (!xu_text_input_read(target, 1, gen, true, &snap)) {
    std::lock_guard<std::mutex> guard(host_lock);
    if (active_input_id == target) active_input_id = 0;
    return strdup("{\"active\":false}");
  }
  double caret[4] = {snap.caret[0], snap.caret[1], snap.caret[2], snap.caret[3]};
  double bound_rect[8]{};
  if (xu_ui_text_input_query(target, 1, gen, snap.revision, 3, 0, 0, 0.0, 0.0, bound_rect) &&
      bound_rect[7] > 0.0) {
    for (int i = 0; i < 4; ++i) caret[i] = bound_rect[4 + i];
  }
  std::string display = snap.display();
  std::string out = "{";
  out += "\"active\":true";
  out += ",\"id\":" + std::to_string(snap.id);
  out += ",\"revision\":" + std::to_string(snap.revision);
  out += ",\"serial\":" + std::to_string(snap.serial);
  out += ",\"flags\":" + std::to_string(snap.flags);
  out += std::string(",\"multiline\":") + ((snap.flags & 1u) ? "true" : "false");
  out += std::string(",\"password\":") + (snap.password() ? "true" : "false");
  out += std::string(",\"composing\":") + (snap.composing() ? "true" : "false");
  out += ",\"text\":" + quote(snap.source.data(), (unsigned)snap.source.size());
  out += ",\"preedit\":" + quote(snap.preedit.data(), (unsigned)snap.preedit.size());
  out += ",\"display\":" + quote(display.data(), (unsigned)display.size());
  out += ",\"anchor16\":" + std::to_string(utf8_to_utf16_pos(snap.source, snap.anchor));
  out += ",\"focus16\":" + std::to_string(utf8_to_utf16_pos(snap.source, snap.focus));
  out += ",\"start16\":" + std::to_string(utf8_to_utf16_pos(snap.source, snap.start));
  out += ",\"end16\":" + std::to_string(utf8_to_utf16_pos(snap.source, snap.end));
  out += ",\"preedit_anchor16\":" + std::to_string(utf8_to_utf16_pos(snap.preedit, snap.preedit_anchor));
  out += ",\"preedit_focus16\":" + std::to_string(utf8_to_utf16_pos(snap.preedit, snap.preedit_focus));
  out += ",\"display_anchor16\":" + std::to_string(utf8_to_utf16_pos(display, snap.display_anchor()));
  out += ",\"display_focus16\":" + std::to_string(utf8_to_utf16_pos(display, snap.display_focus()));
  out += ",\"caret\":[" + number(caret[0]) + "," + number(caret[1]) + "," + number(caret[2]) + "," + number(caret[3]) + "]";
  out += "}";
  return strdup(out.c_str());
}
extern "C" int xu_phone_text_input_commit(uint64_t id, uint64_t revision, const char *utf8, unsigned len) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target || (len && !utf8)) return 0;
  const char *data = utf8 ? utf8 : "";
  if (!revision) return xu_ui_text_input_commit(target, data, len, UINT_MAX, UINT_MAX);
  return xu_ui_text_input_commit_at(target, revision, data, len, UINT_MAX, UINT_MAX);
}
extern "C" int xu_phone_text_input_compose(uint64_t id, uint64_t revision, const char *utf8, unsigned len,
                                           unsigned anchor16, unsigned focus16) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target || (len && !utf8)) return 0;
  std::string pre(utf8 ? utf8 : "", len);
  if (!xdf_utf8((const unsigned char *)pre.data(), (unsigned)pre.size())) return 0;
  unsigned a8 = utf16_to_utf8_pos(pre, anchor16, false);
  unsigned f8 = utf16_to_utf8_pos(pre, focus16, false);
  if (!revision) return xu_ui_text_input_compose(target, pre.data(), (unsigned)pre.size(), a8, f8, UINT_MAX, UINT_MAX);
  return xu_ui_text_input_compose_at(target, revision, pre.data(), (unsigned)pre.size(), a8, f8, UINT_MAX, UINT_MAX);
}
extern "C" int xu_phone_text_input_finish_composing(uint64_t id, uint64_t revision) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  XuTextInputSnapshot snap;
  if (!xu_text_input_read(target, 1, gen, true, &snap)) return 0;
  if (revision && snap.revision != revision) return 0;
  if (!snap.composing()) return 1;
  return xu_ui_text_input_commit_at(target, snap.revision, snap.preedit.data(), (unsigned)snap.preedit.size(), UINT_MAX, UINT_MAX);
}
extern "C" int xu_phone_text_input_compose_region(uint64_t id, uint64_t revision, unsigned start16, unsigned end16) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  if (start16 > end16) std::swap(start16, end16);
  XuTextInputSnapshot snap;
  if (!xu_text_input_read(target, 1, gen, true, &snap)) return 0;
  if (revision && snap.revision != revision) return 0;
  if (snap.composing()) {
    if (!xu_ui_text_input_commit_at(target, snap.revision, snap.preedit.data(), (unsigned)snap.preedit.size(), UINT_MAX, UINT_MAX))
      return 0;
    if (!xu_text_input_read(target, 1, gen, true, &snap)) return 0;
  }
  unsigned s8 = utf16_to_utf8_pos(snap.source, start16, false);
  unsigned e8 = utf16_to_utf8_pos(snap.source, end16, true);
  if (s8 > e8) std::swap(s8, e8);
  std::string slice = snap.source.substr(s8, e8 - s8);
  unsigned caret = (snap.focus >= s8 && snap.focus <= e8) ? (snap.focus - s8) : (unsigned)slice.size();
  return xu_ui_text_input_compose_at(target, snap.revision, slice.data(), (unsigned)slice.size(), caret, caret, s8, e8);
}
extern "C" int xu_phone_text_input_replace(uint64_t id, uint64_t revision, unsigned start16, unsigned end16,
                                           const char *utf8, unsigned len) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target || (len && !utf8)) return 0;
  if (start16 > end16) std::swap(start16, end16);
  XuTextInputSnapshot snap;
  if (!xu_text_input_read(target, 1, gen, true, &snap)) return 0;
  if (revision && snap.revision != revision) return 0;
  std::string display = snap.display();
  unsigned d_s8 = utf16_to_utf8_pos(display, start16, false);
  unsigned d_e8 = utf16_to_utf8_pos(display, end16, true);
  unsigned s8 = 0, e8 = 0;
  if (!snap.source_index(d_s8, false, &s8) || !snap.source_index(d_e8, true, &e8)) return 0;
  if (s8 > e8) std::swap(s8, e8);
  return xu_ui_text_input_commit_at(target, snap.revision, utf8 ? utf8 : "", len, s8, e8);
}
extern "C" int xu_phone_text_input_select(uint64_t id, uint64_t revision, unsigned anchor16, unsigned focus16) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  XuTextInputSnapshot snap;
  if (!xu_text_input_read(target, 1, gen, true, &snap)) return 0;
  if (revision && snap.revision != revision) return 0;
  std::string display = snap.display();
  unsigned d_a8 = utf16_to_utf8_pos(display, anchor16, false);
  unsigned d_f8 = utf16_to_utf8_pos(display, focus16, false);
  if (snap.composing()) {
    unsigned pre_end = snap.start + (unsigned)snap.preedit.size();
    if (d_a8 >= snap.start && d_a8 <= pre_end && d_f8 >= snap.start && d_f8 <= pre_end) {
      return xu_ui_text_input_compose_at(target, snap.revision, snap.preedit.data(), (unsigned)snap.preedit.size(),
                                         d_a8 - snap.start, d_f8 - snap.start, UINT_MAX, UINT_MAX);
    }
    if (!xu_ui_text_input_commit_at(target, snap.revision, snap.preedit.data(), (unsigned)snap.preedit.size(), UINT_MAX, UINT_MAX))
      return 0;
    if (!xu_text_input_read(target, 1, gen, true, &snap)) return 0;
    display = snap.display();
    d_a8 = utf16_to_utf8_pos(display, anchor16, false);
    d_f8 = utf16_to_utf8_pos(display, focus16, false);
  }
  unsigned s_a8 = 0, s_f8 = 0;
  if (!snap.source_index(d_a8, false, &s_a8) || !snap.source_index(d_f8, false, &s_f8)) return 0;
  return xu_ui_text_input_select(target, s_a8, s_f8);
}
extern "C" int xu_phone_text_input_delete_surrounding(uint64_t id, uint64_t revision, unsigned before16, unsigned after16) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  if (!before16 && !after16) return 1;
  XuTextInputSnapshot snap;
  if (!xu_text_input_read(target, 1, gen, true, &snap)) return 0;
  if (revision && snap.revision != revision) return 0;
  unsigned pivot_before = snap.composing() ? snap.start : std::min(snap.anchor, snap.focus);
  unsigned pivot_after = snap.composing() ? snap.end : std::max(snap.anchor, snap.focus);
  uint64_t cur_rev = snap.revision;
  if (after16 > 0 && pivot_after < snap.source.size()) {
    unsigned after_u16 = utf8_to_utf16_pos(snap.source, pivot_after);
    unsigned end_u16 = after_u16 + after16;
    unsigned del_end = utf16_to_utf8_pos(snap.source, end_u16, true);
    if (del_end > pivot_after) {
      if (!xu_ui_text_input_delete_surrounding_at(target, cur_rev, pivot_after, del_end)) return 0;
      ++cur_rev;
    }
  }
  if (before16 > 0 && pivot_before > 0) {
    unsigned before_u16 = utf8_to_utf16_pos(snap.source, pivot_before);
    unsigned start_u16 = before16 >= before_u16 ? 0u : (before_u16 - before16);
    unsigned del_start = utf16_to_utf8_pos(snap.source, start_u16, false);
    if (del_start < pivot_before) {
      if (!xu_ui_text_input_delete_surrounding_at(target, cur_rev, del_start, pivot_before)) return 0;
    }
  }
  return 1;
}
extern "C" int xu_phone_text_input_erase(uint64_t id, uint64_t revision, int backward) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  XuTextInputSnapshot snap;
  if (!xu_text_input_read(target, 1, gen, true, &snap)) return 0;
  if (revision && snap.revision != revision) return 0;
  if (snap.composing()) {
    if (!backward) return 0;
    if (snap.preedit.empty()) return xu_ui_text_input_cancel(target);
    std::vector<unsigned> stops;
    if (xu_ui_grapheme::boundaries(snap.preedit.data(), (unsigned)snap.preedit.size(), &stops) && stops.size() >= 2) {
      unsigned next_len = stops[stops.size() - 2];
      if (!next_len) return xu_ui_text_input_cancel(target);
      return xu_ui_text_input_compose_at(target, snap.revision, snap.preedit.data(), next_len,
                                         next_len, next_len, UINT_MAX, UINT_MAX);
    }
    return xu_ui_text_input_cancel(target);
  }
  return xu_ui_text_input_erase(target, backward ? 1 : 0);
}
extern "C" int xu_phone_text_input_move(uint64_t id, uint64_t revision, int backward, int extend) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  if (revision) {
    XuTextInputSnapshot snap;
    if (!xu_text_input_read(target, 1, gen, true, &snap) || snap.revision != revision) return 0;
  }
  return xu_ui_text_input_move(target, backward ? 1 : 0, extend ? 1 : 0);
}
extern "C" int xu_phone_text_input_stop(uint64_t id) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  {
    std::lock_guard<std::mutex> guard(host_lock);
    if (active_input_id == target) active_input_id = 0;
  }
  return xu_ui_text_input_stop(target, 1, gen, XUTI_STOPPED);
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
  uint64_t input_id = 0;
  unsigned gen = 0;
  {
    std::lock_guard<std::mutex> guard(host_lock);
    if (active_input_id && xu_ui_text_input_active(active_input_id)) {
      input_id = active_input_id;
      gen = generation;
      active_input_id = 0;
    }
  }
  if (input_id) {
    xu_ui_text_input_stop(input_id, 1, gen, XUTI_STOPPED);
    return 1;
  }
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
      if(xu_request_id(command+13,&id)) {
        if(active_input_id && active_input_id!=id) xu_ui_text_input_stop(active_input_id,1,generation,XUTI_STOPPED);
        if(xu_ui_text_input_activate(id,1,generation)) active_input_id=id;
        else if(active_input_id==id) active_input_id=0;
      }
    }
    else if(!strcmp(command,"close")||!strcmp(command,"quit_app")){active_input_id=0;xu_phone_stop();}
    else if(!strcmp(command,"motion_preferences"))event(("canvas_preferences\t1\t1\t"+std::to_string(generation)+(reduced_motion?"\t1":"\t0")).c_str());
    else if(!strncmp(command,"__window_open\t1\t",16)||!strncmp(command,"__window_bind\t1\t",16)||!strncmp(command,"cursor\t",7)||!strncmp(command,"pan_enabled\t",12)||!strcmp(command,"show")){}
    else if(!line.empty())xu_ui_window_event(1,generation,"command_unsupported");
  }
  xu_ui_text_input_poll();
  if(active_input_id && !xu_ui_text_input_active(active_input_id)) active_input_id=0;
  if(!next.empty())last_frame=next;
  else if(redraw)next=last_frame;
  redraw=false;
  return next.empty()?nullptr:strdup(next.c_str());
}
