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
#include <atomic>
#include <climits>
#include <cstddef>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

static std::mutex host_lock;
static unsigned generation;
static double width = 390, height = 844, scale = 1;
static double inset_top = 0, inset_bottom = 0, inset_left = 0, inset_right = 0, inset_ime = 0;
static bool input_enabled, redraw, reduced_motion, system_dark;
static double font_scale_val = 1.0;
static uint64_t active_input_id = 0;
static std::string last_frame, last_insets;
static std::unordered_map<uint64_t, unsigned> uploaded_images;
static XuContentHost content{};
static std::atomic<xu_phone_clipboard_read_fn> g_clipboard_read{nullptr};
static std::atomic<xu_phone_clipboard_write_fn> g_clipboard_write{nullptr};
extern "C" __attribute__((weak)) void xu_phone_wake(void) {}
static void event(const char *line) {
  xu_ui_mem_append("xu_ui_shell_event.txt", line, 1);
  xu_phone_wake();
}
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
      return 0.84;
    case 'M': case 'W':
      return 0.90;
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
static bool codepoint_is_cjk_break(unsigned cp) {
  return (cp >= 0x2e80 && cp <= 0x9fff) || (cp >= 0xac00 && cp <= 0xd7af) ||
         (cp >= 0xf900 && cp <= 0xfaff) || (cp >= 0xff00 && cp <= 0xff60) ||
         (cp >= 0xffe0 && cp <= 0xffee) || cp >= 0x1f000;
}
// Canvas text renders via WebView 2D canvas and queries grapheme clusters using
// matched proportional/CJK advance estimates so caret placement, multiline wrapping,
// and hit testing work consistently across single-line and wrapped layouts.
struct Text {
  struct Cluster { unsigned start, length, line; double x0, x1, y0, y1; };
  struct Line { unsigned start, end, cluster_start, cluster_end; double width, origin_x, y; };
  std::string value, family;
  double size, line, width, weight, italic, align, total_width, total_height, origin_x;
  bool multiline;
  std::vector<Line> lines;
  std::vector<Cluster> clusters;
};
static void *text_create(const char *family, unsigned family_len, const char *s, unsigned n,
                         const double *options, double *metrics, unsigned *cost) {
  double sz = (options && std::isfinite(options[0]) && options[0] > 0) ? options[0] : 12.0;
  double explicit_lh = (options && std::isfinite(options[5]) && options[5] > 0) ? options[5] : 0.0;
  bool has_nl = s && n && (memchr(s, '\n', n) != nullptr || memchr(s, '\r', n) != nullptr);
  bool multiline = (explicit_lh > 0.0) || has_nl;
  double ln = explicit_lh > 0.0 ? explicit_lh : (has_nl ? sz * 1.4 : sz * 1.2);
  double wrap_w = (options && std::isfinite(options[1]) && options[1] > 0) ? options[1] : 0.0;
  auto *t = new Text{std::string(s ? s : "", n), std::string(family ? family : "", family_len),
                     sz, ln, wrap_w, options ? options[2] : 400.0,
                     options ? options[3] : 0.0, options ? options[4] : 0.0, 0.0, ln, 0.0, multiline, {}, {}};
  struct Raw { unsigned start, len, cp; double w; bool is_nl, is_space, is_break; };
  std::vector<Raw> raw;
  double weight_scale = t->weight >= 600.0 ? 1.03 : 1.0;
  std::vector<unsigned> stops;
  if (n && s && xu_ui_grapheme::boundaries(s, n, &stops) && stops.size() >= 2) {
    raw.reserve(stops.size() - 1u);
    for (size_t i = 0; i + 1 < stops.size(); ++i) {
      unsigned start = stops[i], len = stops[i + 1] - stops[i];
      unsigned adv = 0;
      unsigned cp = decode_utf8(s, n, start, &adv);
      bool is_nl = (s[start] == '\n' || s[start] == '\r');
      bool is_space = !is_nl && (cp == ' ' || cp == '\t');
      double w = is_nl ? 0.0 : (codepoint_width_factor(cp) * t->size * weight_scale);
      raw.push_back(Raw{start, len, cp, w, is_nl, is_space, is_space || codepoint_is_cjk_break(cp)});
    }
  } else if (n && s) {
    for (unsigned i = 0; i < n;) {
      unsigned adv = 0;
      unsigned cp = decode_utf8(s, n, i, &adv);
      if (!adv) break;
      bool is_nl = (cp == '\n' || cp == '\r');
      bool is_space = !is_nl && (cp == ' ' || cp == '\t');
      double w = is_nl ? 0.0 : (codepoint_width_factor(cp) * t->size * weight_scale);
      raw.push_back(Raw{i, adv, cp, w, is_nl, is_space, is_space || codepoint_is_cjk_break(cp)});
      i += adv;
    }
  }
  auto line_origin = [&](double line_w) -> double {
    if (t->width <= 0.0) return 0.0;
    if (t->align == 1.0) return std::max(0.0, (t->width - line_w) * 0.5);
    if (t->align == 2.0) return std::max(0.0, t->width - line_w);
    return 0.0;
  };
  t->clusters.reserve(raw.size());
  if (!t->multiline || raw.empty()) {
    double cursor = 0.0;
    for (const auto &rc : raw) {
      t->clusters.push_back(Text::Cluster{rc.start, rc.len, 0u, cursor, cursor + rc.w, 0.0, t->line});
      cursor += rc.w;
    }
    double ox = line_origin(cursor);
    if (ox > 0.0) {
      for (auto &c : t->clusters) { c.x0 += ox; c.x1 += ox; }
    }
    t->origin_x = ox;
    t->total_width = cursor;
    t->total_height = t->line;
    t->lines.push_back(Text::Line{0u, n, 0u, (unsigned)t->clusters.size(), cursor, ox, 0.0});
  } else {
    size_t pos = 0;
    bool ended_with_nl = false;
    while (pos < raw.size()) {
      unsigned line_idx = (unsigned)t->lines.size();
      double line_y = (double)line_idx * t->line;
      size_t start_idx = pos;
      double cur_w = 0.0;
      ptrdiff_t last_break = -1;
      bool hit_nl = false;
      bool wrapped = false;
      while (pos < raw.size()) {
        if (raw[pos].is_nl) {
          hit_nl = true;
          ++pos;
          break;
        }
        if (t->width > 0.0 && cur_w + raw[pos].w > t->width && pos > start_idx) {
          if (last_break >= (ptrdiff_t)start_idx) pos = (size_t)last_break + 1;
          wrapped = true;
          break;
        }
        cur_w += raw[pos].w;
        if (raw[pos].is_break) last_break = (ptrdiff_t)pos;
        ++pos;
      }
      size_t end_idx = pos;
      // Preserve continuation leading spaces as zero-width clusters if soft-wrapped right after space.
      unsigned cstart = (unsigned)t->clusters.size();
      double visible_w = 0.0;
      size_t vis_end = end_idx;
      if (hit_nl && vis_end > start_idx && raw[vis_end - 1].is_nl) --vis_end;
      if (wrapped) {
        while (vis_end > start_idx && raw[vis_end - 1].is_space) --vis_end;
      }
      for (size_t j = start_idx; j < vis_end; ++j) visible_w += raw[j].w;
      double ox = line_origin(visible_w);
      double cx = ox;
      for (size_t j = start_idx; j < end_idx; ++j) {
        double adv_w = (j < vis_end) ? raw[j].w : 0.0;
        t->clusters.push_back(Text::Cluster{raw[j].start, raw[j].len, line_idx, cx, cx + adv_w, line_y, line_y + t->line});
        cx += adv_w;
      }
      unsigned cend = (unsigned)t->clusters.size();
      unsigned byte_start = raw[start_idx].start;
      unsigned byte_end = raw[end_idx - 1].start + raw[end_idx - 1].len;
      t->lines.push_back(Text::Line{byte_start, byte_end, cstart, cend, visible_w, ox, line_y});
      ended_with_nl = hit_nl && (pos == raw.size());
      if (wrapped) {
        while (pos < raw.size() && raw[pos].is_space) {
          t->clusters.push_back(Text::Cluster{raw[pos].start, raw[pos].len, line_idx, cx, cx, line_y, line_y + t->line});
          t->lines.back().cluster_end = (unsigned)t->clusters.size();
          t->lines.back().end = raw[pos].start + raw[pos].len;
          ++pos;
        }
      }
    }
    if (ended_with_nl || t->lines.empty()) {
      unsigned line_idx = (unsigned)t->lines.size();
      double line_y = (double)line_idx * t->line;
      double ox = line_origin(0.0);
      unsigned cs = (unsigned)t->clusters.size();
      t->lines.push_back(Text::Line{n, n, cs, cs, 0.0, ox, line_y});
    }
    double max_w = 0.0;
    double min_ox = t->lines.empty() ? 0.0 : t->lines[0].origin_x;
    for (const auto &ln_info : t->lines) {
      max_w = std::max(max_w, ln_info.width);
      min_ox = std::min(min_ox, ln_info.origin_x);
    }
    t->total_width = max_w;
    t->origin_x = min_ox;
    t->total_height = (double)t->lines.size() * t->line;
  }
  double w = t->width > 0 ? std::min(t->total_width, t->width) : t->total_width;
  double h = t->total_height;
  metrics[0] = w; metrics[1] = h; metrics[2] = t->size * 0.8; metrics[3] = (double)t->lines.size();
  metrics[4] = t->origin_x; metrics[5] = 0; metrics[6] = w; metrics[7] = h;
  *cost = (unsigned)(sizeof(Text) + n + family_len + t->clusters.size() * sizeof(Text::Cluster));
  return t;
}
static void text_destroy(void *p) { delete (Text *)p; }
static int text_query_native(void *pointer, unsigned mode, unsigned index, unsigned trailing,
                             double x, double y, double *out) {
  if (!pointer || !out || mode > 1 || trailing > 1) return 0;
  auto *t = (const Text *)pointer;
  if (t->clusters.empty() || t->lines.empty()) {
    double h = t->lines.empty() ? t->line : t->total_height;
    out[0] = 0; out[1] = 0; out[2] = (mode == 1 && trailing) ? 1 : 0;
    out[3] = (mode == 1 || (x >= 0.0 && x <= std::max(t->width, 1.0) && y >= 0.0 && y <= h)) ? 1 : 0;
    out[4] = t->origin_x; out[5] = 0; out[6] = t->line;
    return 1;
  }
  if (mode == 0) {
    size_t line_idx = 0;
    if (y > 0.0 && t->lines.size() > 1) {
      size_t cand = (size_t)std::floor(y / t->line);
      line_idx = std::min(cand, t->lines.size() - 1u);
    }
    const auto &ln = t->lines[line_idx];
    bool inside_y = y >= 0.0 && y <= t->total_height;
    bool inside = inside_y && x >= ln.origin_x && x <= ln.origin_x + ln.width;
    if (ln.cluster_start >= ln.cluster_end) {
      out[0] = ln.start; out[1] = 0; out[2] = 0;
      out[3] = inside_y && x >= ln.origin_x && x <= ln.origin_x + std::max(t->width, 1.0) ? 1 : 0;
      out[4] = ln.origin_x; out[5] = ln.y; out[6] = t->line;
      return 1;
    }
    unsigned cstart = ln.cluster_start;
    unsigned cend = ln.cluster_end;
    const Text::Cluster *chosen = &t->clusters[cend - 1u];
    unsigned tr = 1;
    double caret_x = chosen->x1;
    if (x <= t->clusters[cstart].x0) {
      chosen = &t->clusters[cstart]; tr = 0; caret_x = chosen->x0;
    } else if (x < t->clusters[cend - 1u].x1) {
      for (unsigned ci = cstart; ci < cend; ++ci) {
        const auto &c = t->clusters[ci];
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
    out[3] = inside ? 1 : 0; out[4] = caret_x; out[5] = chosen->y0; out[6] = t->line;
    return 1;
  }
  const auto &last = t->clusters.back();
  unsigned end_byte = last.start + last.length;
  if (index >= end_byte) {
    const auto &last_ln = t->lines.back();
    out[0] = end_byte; out[1] = 0; out[2] = trailing ? 1 : 0; out[3] = 1;
    out[4] = (last_ln.cluster_start == last_ln.cluster_end) ? last_ln.origin_x : last.x1;
    out[5] = last_ln.y; out[6] = t->line;
    return 1;
  }
  for (const auto &c : t->clusters) {
    if (index < c.start + c.length) {
      out[0] = c.start; out[1] = c.length; out[2] = trailing ? 1 : 0; out[3] = 1;
      out[4] = trailing ? c.x1 : c.x0; out[5] = c.y0; out[6] = t->line;
      return 1;
    }
  }
  return 0;
}
static std::string base64_encode(const unsigned char *data, size_t len) {
  static constexpr char kTab[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::string out;
  out.reserve(((len + 2) / 3) * 4);
  for (size_t i = 0; i < len; i += 3) {
    unsigned b0 = data[i];
    unsigned b1 = (i + 1 < len) ? data[i + 1] : 0;
    unsigned b2 = (i + 2 < len) ? data[i + 2] : 0;
    unsigned v = (b0 << 16) | (b1 << 8) | b2;
    out.push_back(kTab[(v >> 18) & 63]);
    out.push_back(kTab[(v >> 12) & 63]);
    out.push_back(i + 1 < len ? kTab[(v >> 6) & 63] : '=');
    out.push_back(i + 2 < len ? kTab[v & 63] : '=');
  }
  return out;
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
      if(native)out+=",["+number(native->width)+','+number(native->weight)+','+number(native->italic)+','+number(native->align)+','+quote(native->family.data(),native->family.size())+','+number(native->line)+','+(native->multiline?"1":"0")+']';
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
      unsigned rev=xu_ui_bitmap_revision(bitmap);
      if(pixels && w>0 && h>0) {
        bool cached=false;
        if(depth==0) {
          auto it=uploaded_images.find(c.image_id);
          if(it!=uploaded_images.end() && it->second==rev) cached=true;
          else uploaded_images[c.image_id]=rev;
        }
        if(cached) {
          out+=",["+std::to_string(w)+','+std::to_string(h)+','+std::to_string(c.image_id)+']';
        } else {
          size_t total=(size_t)w*(size_t)h*4u;
          std::vector<unsigned char> rgba(total);
          for(size_t i=0;i<total;i+=4) {
            unsigned a=pixels[i+3];
            rgba[i]=(unsigned char)(a?std::min(255u,(unsigned)pixels[i+2]*255u/a):0u);
            rgba[i+1]=(unsigned char)(a?std::min(255u,(unsigned)pixels[i+1]*255u/a):0u);
            rgba[i+2]=(unsigned char)(a?std::min(255u,(unsigned)pixels[i]*255u/a):0u);
            rgba[i+3]=(unsigned char)a;
          }
          std::string b64=base64_encode(rgba.data(),rgba.size());
          out+=",["+std::to_string(w)+','+std::to_string(h)+','+std::to_string(c.image_id)+",\""+b64+"\"]";
        }
      } else {
        out+=",[0,0,0,\"\"]";
      }
    }
    out+=']';
  }
  if(depth==0 && !uploaded_images.empty()) {
    std::vector<uint64_t> evicted;
    for(auto it=uploaded_images.begin();it!=uploaded_images.end();) {
      if(!xu_ui_image_info(it->first,nullptr,nullptr,nullptr)) {
        evicted.push_back(it->first);
        it=uploaded_images.erase(it);
      } else {
        ++it;
      }
    }
    if(!evicted.empty()) {
      if(!first)out+=',';
      out+="[26,0,0,0,0,0,0,0,0,0,[";
      for(size_t i=0;i<evicted.size();++i) {
        if(i)out+=',';
        out+=std::to_string(evicted[i]);
      }
      out+="]]";
    }
  }
  return out+']';
}
extern "C" void xu_phone_resize(double w,double h,double s) {
  if(!std::isfinite(w)||!std::isfinite(h)||!std::isfinite(s)||w<=0||h<=0||s<=0)return;
  std::lock_guard<std::mutex> guard(host_lock);width=w;height=h;scale=s;
  if(generation){xu_ui_canvas_metrics(&content,w,h,(unsigned)(w*s),(unsigned)(h*s),s,s);xu_phone_wake();}
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
  if(changed&&generation){xu_ui_canvas_metrics(&content,width,height,(unsigned)(width*scale),(unsigned)(height*scale),scale,scale);xu_phone_wake();}
}
extern "C" void xu_phone_reduced_motion(int enabled) {
  bool on=enabled!=0;
  std::lock_guard<std::mutex> guard(host_lock);
  bool changed=on!=reduced_motion;
  reduced_motion=on;
  xu_ui_mem_set("phone_reduced_motion",on?"1":"0");
  if(changed&&generation)event(("canvas_preferences\t1\t1\t"+std::to_string(generation)+(on?"\t1":"\t0")).c_str());
}
extern "C" void xu_phone_system_appearance(int dark) {
  bool on=dark!=0;
  std::lock_guard<std::mutex> guard(host_lock);
  bool changed=on!=system_dark;
  system_dark=on;
  xu_ui_mem_set("phone_system_dark",on?"1":"0");
  if(changed&&generation)event(("canvas_preferences\t1\t1\t"+std::to_string(generation)+(reduced_motion?"\t1":"\t0")).c_str());
}
extern "C" void xu_phone_font_scale(double s) {
  double v=(!std::isfinite(s)||s<=0.0)?1.0:std::max(0.5,std::min(3.0,s));
  v=std::round(v*100.0)/100.0;
  std::lock_guard<std::mutex> guard(host_lock);
  bool changed=std::fabs(v-font_scale_val)>0.005;
  font_scale_val=v;
  xu_ui_mem_set("phone_font_scale",number(v).c_str());
  if(changed&&generation){
    xu_ui_canvas_metrics(&content,width,height,(unsigned)(width*scale),(unsigned)(height*scale),scale,scale);
    event(("canvas_preferences\t1\t1\t"+std::to_string(generation)+(reduced_motion?"\t1":"\t0")).c_str());
  }
}
extern "C" void xu_phone_input_event(int kind,double x,double y,int button,int buttons,int modifiers,int click_count) {
  std::lock_guard<std::mutex> guard(host_lock);
  if(input_enabled && generation && kind>=72 && kind<=77) {
    xu_ui_input_emit(&content,(unsigned)kind,x,y,0,0,(unsigned)button,(unsigned)buttons,(unsigned)modifiers,0,0,0,(unsigned)click_count);
    xu_phone_wake();
  }
}
extern "C" void xu_phone_input(int kind,double x,double y,int buttons) {
  xu_phone_input_event(kind,x,y,1,buttons,0,kind==73?1:0);
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
  if (generation && (kind == XUI_KEY_DOWN || kind == XUI_KEY_UP)) {
    xu_ui_input_emit(&content, (unsigned)kind, 0, 0, 0, 0, 0, 0, (unsigned)modifiers, (unsigned)key, 0, (unsigned)repeat, 0);
    xu_phone_wake();
  }
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
  out += ",\"keyboard\":" + std::to_string(snap.keyboard_type());
  out += ",\"return_key\":" + std::to_string(snap.return_key());
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
  int rc = !revision ? xu_ui_text_input_commit(target, data, len, UINT_MAX, UINT_MAX)
                     : xu_ui_text_input_commit_at(target, revision, data, len, UINT_MAX, UINT_MAX);
  if (rc) xu_phone_wake();
  return rc;
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
  int rc = !revision ? xu_ui_text_input_compose(target, pre.data(), (unsigned)pre.size(), a8, f8, UINT_MAX, UINT_MAX)
                     : xu_ui_text_input_compose_at(target, revision, pre.data(), (unsigned)pre.size(), a8, f8, UINT_MAX, UINT_MAX);
  if (rc) xu_phone_wake();
  return rc;
}
extern "C" int xu_phone_text_input_finish_composing(uint64_t id, uint64_t revision) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  XuTextInputSnapshot snap;
  if (!xu_text_input_read(target, 1, gen, true, &snap)) return 0;
  if (revision && snap.revision != revision) return 0;
  if (!snap.composing()) return 1;
  int rc = xu_ui_text_input_commit_at(target, snap.revision, snap.preedit.data(), (unsigned)snap.preedit.size(), UINT_MAX, UINT_MAX);
  if (rc) xu_phone_wake();
  return rc;
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
  int rc = xu_ui_text_input_compose_at(target, snap.revision, slice.data(), (unsigned)slice.size(), caret, caret, s8, e8);
  if (rc) xu_phone_wake();
  return rc;
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
  int rc = xu_ui_text_input_commit_at(target, snap.revision, utf8 ? utf8 : "", len, s8, e8);
  if (rc) xu_phone_wake();
  return rc;
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
      int rc = xu_ui_text_input_compose_at(target, snap.revision, snap.preedit.data(), (unsigned)snap.preedit.size(),
                                           d_a8 - snap.start, d_f8 - snap.start, UINT_MAX, UINT_MAX);
      if (rc) xu_phone_wake();
      return rc;
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
  int rc = xu_ui_text_input_select(target, s_a8, s_f8);
  if (rc) xu_phone_wake();
  return rc;
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
  xu_phone_wake();
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
    if (snap.preedit.empty()) {
      int rc = xu_ui_text_input_cancel(target);
      if (rc) xu_phone_wake();
      return rc;
    }
    std::vector<unsigned> stops;
    if (xu_ui_grapheme::boundaries(snap.preedit.data(), (unsigned)snap.preedit.size(), &stops) && stops.size() >= 2) {
      unsigned next_len = stops[stops.size() - 2];
      int rc = !next_len ? xu_ui_text_input_cancel(target)
                         : xu_ui_text_input_compose_at(target, snap.revision, snap.preedit.data(), next_len,
                                                       next_len, next_len, UINT_MAX, UINT_MAX);
      if (rc) xu_phone_wake();
      return rc;
    }
    int rc = xu_ui_text_input_cancel(target);
    if (rc) xu_phone_wake();
    return rc;
  }
  int rc = xu_ui_text_input_erase(target, backward ? 1 : 0);
  if (rc) xu_phone_wake();
  return rc;
}
extern "C" int xu_phone_text_input_move(uint64_t id, uint64_t revision, int backward, int extend) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  if (revision) {
    XuTextInputSnapshot snap;
    if (!xu_text_input_read(target, 1, gen, true, &snap) || snap.revision != revision) return 0;
  }
  int rc = xu_ui_text_input_move(target, backward ? 1 : 0, extend ? 1 : 0);
  if (rc) xu_phone_wake();
  return rc;
}
extern "C" int xu_phone_text_input_stop(uint64_t id) {
  unsigned gen = 0;
  uint64_t target = resolve_input_id(id, &gen);
  if (!target) return 0;
  {
    std::lock_guard<std::mutex> guard(host_lock);
    if (active_input_id == target) active_input_id = 0;
  }
  int rc = xu_ui_text_input_stop(target, 1, gen, XUTI_STOPPED);
  if (rc) xu_phone_wake();
  return rc;
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
    xu_phone_wake();
    return 1;
  }
  char enabled[4]{};
  if(xu_ui_mem_get("phone_back_enabled",enabled,sizeof(enabled))!=1 || enabled[0]!='1')return 0;
  event("navigate_back");return 1;
}
extern "C" void xu_phone_haptic(int kind) {
  if (kind < XU_HAPTIC_SELECTION || kind > XU_HAPTIC_ERROR) return;
  xu_ui_mem_set("phone_haptic", std::to_string(kind).c_str());
}
extern "C" int xu_phone_haptic_take() {
  unsigned len = 0;
  char *raw = xu_ui_mem_take("phone_haptic", &len);
  if (!raw) return 0;
  int kind = 0;
  if (len == 1 && raw[0] >= '1' && raw[0] <= '4') kind = raw[0] - '0';
  free(raw);
  return kind;
}
extern "C" void xu_phone_set_clipboard(xu_phone_clipboard_read_fn read_fn, xu_phone_clipboard_write_fn write_fn) {
  g_clipboard_read.store(read_fn, std::memory_order_release);
  g_clipboard_write.store(write_fn, std::memory_order_release);
}
extern "C" void xu_phone_redraw() {
  {
    std::lock_guard<std::mutex> guard(host_lock);
    redraw=true;
  }
  xu_phone_wake();
}
extern "C" void xu_phone_renderer_reset() {
  {
    std::lock_guard<std::mutex> guard(host_lock);
    uploaded_images.clear();
    last_frame.clear();
    redraw=true;
    if(generation) {
      xu_ui_canvas_metrics(&content,width,height,(unsigned)(width*scale),(unsigned)(height*scale),scale,scale);
    }
  }
  xu_phone_wake();
}
extern "C" char *xu_phone_poll() {
  struct PendingClipboard { uint64_t id; unsigned kind; std::string text; };
  std::vector<PendingClipboard> clipboard_ops;
  std::string next;
  {
    std::lock_guard<std::mutex> guard(host_lock);
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
        uint64_t cid=0; unsigned ckind=0; std::string ctext;
        if(xu_request_clipboard_take(command,1,generation,&cid,&ckind,&ctext)) {
          if(ckind) clipboard_ops.push_back(PendingClipboard{cid,ckind,std::move(ctext)});
        } else {
          uint64_t id=0;
          if(xu_request_id(command+10,&id)) {
            char *wire=xu_ui_request_take(id,1,generation);
            if(wire){free(wire);xu_ui_request_complete(id,XU_REQUEST_UNSUPPORTED,"unavailable on Phone",20);}
          }
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
  }
  for (const auto &op : clipboard_ops) {
    if (op.kind == XU_REQUEST_CLIPBOARD_WRITE) {
      auto write_fn = g_clipboard_write.load(std::memory_order_acquire);
      if (!write_fn) {
        xu_ui_request_complete(op.id, XU_REQUEST_UNSUPPORTED, "unavailable on Phone", 20);
      } else {
        int rc = write_fn(op.text.data(), (unsigned)op.text.size());
        if (rc > 0) xu_ui_request_complete(op.id, XU_REQUEST_COMPLETED, "", 0);
        else if (rc < 0) xu_ui_request_complete(op.id, XU_REQUEST_UNSUPPORTED, "unavailable on Phone", 20);
        else xu_ui_request_complete(op.id, XU_REQUEST_FAILED, "clipboard write failed", 22);
      }
    } else if (op.kind == XU_REQUEST_CLIPBOARD_READ) {
      auto read_fn = g_clipboard_read.load(std::memory_order_acquire);
      if (!read_fn) {
        xu_ui_request_complete(op.id, XU_REQUEST_UNSUPPORTED, "unavailable on Phone", 20);
      } else {
        std::string buf(XU_UI_REQUEST_MAX_TEXT, '\0');
        unsigned out_len = 0;
        int rc = read_fn(&buf[0], XU_UI_REQUEST_MAX_TEXT, &out_len);
        if (rc > 0 && out_len <= XU_UI_REQUEST_MAX_TEXT) {
          xu_ui_request_complete(op.id, XU_REQUEST_COMPLETED, buf.data(), out_len);
        } else if (rc < 0) {
          xu_ui_request_complete(op.id, XU_REQUEST_UNSUPPORTED, "unavailable on Phone", 20);
        } else {
          xu_ui_request_complete(op.id, XU_REQUEST_FAILED, "clipboard read failed", 21);
        }
      }
    }
  }
  return next.empty()?nullptr:strdup(next.c_str());
}
