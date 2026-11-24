// Internal document model for the UI host. The owner serializes access and admits
// each returned event atomically with the mutation (rollback on backpressure).
// Native callbacks operate on this state before the worker acknowledges edits.
#pragma once
#include "xu_ui_grapheme.h"
#include <algorithm>
#include <string>
#include <limits.h>

enum XuUiEditKind { XUE_NONE, XUE_COMMIT, XUE_PREEDIT, XUE_CANCEL, XUE_SELECTION, XUE_SURROUNDING_DELETE=8 };
struct XuUiEditChange {
  unsigned kind = XUE_NONE;
  uint64_t revision = 0;
  unsigned start = 0, end = 0, anchor = 0, focus = 0;
  std::string text;
};

class XuUiEditModel {
  std::string text_, preedit_;
  std::vector<unsigned> stops_{0};
  uint64_t revision_ = 0;
  unsigned anchor_ = 0, focus_ = 0, replacement_start_ = 0, replacement_end_ = 0;
  unsigned preedit_anchor_ = 0, preedit_focus_ = 0;
  bool composing_ = false;
  static bool valid(const char *data, unsigned length) {
    return length <= 16384 && (!length || data) && xdf_utf8((const unsigned char *)data, length);
  }
  static bool boundary(const std::string &text, unsigned offset) {
    return offset <= text.size() && (offset == text.size() || ((unsigned char)text[offset] & 0xc0) != 0x80);
  }
  bool writable(XuUiEditChange *change) const { return change && revision_ && revision_ < INT64_MAX; }
  bool noop(XuUiEditChange *change) const {
    if (!change || !revision_) return false;
    *change = {}; change->revision = revision_; return true;
  }
  unsigned floor_stop(unsigned index) const {
    auto at = std::upper_bound(stops_.begin(), stops_.end(), index);
    return at == stops_.begin() ? 0 : *--at;
  }
  unsigned ceil_stop(unsigned index) const {
    auto at = std::lower_bound(stops_.begin(), stops_.end(), index);
    return at == stops_.end() ? (unsigned)text_.size() : *at;
  }
  enum StopClass { SC_NL = 0, SC_WS = 1, SC_PUNCT = 2, SC_WORD = 3 };
  static unsigned decode_cp(const std::string &s, unsigned at) {
    unsigned char b = (unsigned char)s[at];
    if (b < 0x80u) return b;
    unsigned cp = 0; int cont = 0;
    if (b < 0xe0u) { cp = b & 31u; cont = 1; }
    else if (b < 0xf0u) { cp = b & 15u; cont = 2; }
    else { cp = b & 7u; cont = 3; }
    for (int i = 1; i <= cont && at + (unsigned)i < s.size(); ++i)
      cp = (cp << 6) | ((unsigned char)s[at + (unsigned)i] & 63u);
    return cp;
  }
  StopClass stop_class(unsigned stop_idx) const {
    unsigned pos = stops_[stop_idx];
    if (pos >= text_.size()) return SC_WS;
    unsigned cp = decode_cp(text_, pos);
    if (cp == '\n' || cp == '\r' || cp == 0x2028u || cp == 0x2029u) return SC_NL;
    if (cp <= 0x20u || cp == 0x7fu || cp == 0xa0u || (cp >= 0x2000u && cp <= 0x200bu) || cp == 0x3000u) return SC_WS;
    if (cp < 0x80u) {
      bool is_word = (cp >= '0' && cp <= '9') || (cp >= 'A' && cp <= 'Z') || (cp >= 'a' && cp <= 'z') || cp == '_';
      return is_word ? SC_WORD : SC_PUNCT;
    }
    if ((cp >= 0x2010u && cp <= 0x2027u) || (cp >= 0x3001u && cp <= 0x3003u) ||
        (cp >= 0x3008u && cp <= 0x301fu) || (cp >= 0xff01u && cp <= 0xff0fu) ||
        (cp >= 0xff1au && cp <= 0xff20u) || (cp >= 0xff3bu && cp <= 0xff40u) ||
        (cp >= 0xff5bu && cp <= 0xff65u)) return SC_PUNCT;
    return SC_WORD;
  }
  unsigned stop_index_of(unsigned offset) const {
    unsigned floored = floor_stop(offset);
    return (unsigned)(std::lower_bound(stops_.begin(), stops_.end(), floored) - stops_.begin());
  }
  unsigned word_boundary(unsigned offset, bool backward) const {
    unsigned idx = stop_index_of(offset);
    unsigned last = (unsigned)stops_.size() - 1u;
    if (backward) {
      if (idx == 0) return 0;
      if (stop_class(idx - 1u) == SC_NL) return stops_[idx - 1u];
      while (idx > 0 && stop_class(idx - 1u) == SC_WS) --idx;
      if (idx > 0 && stop_class(idx - 1u) != SC_NL) {
        StopClass cls = stop_class(idx - 1u);
        while (idx > 0 && stop_class(idx - 1u) == cls) --idx;
      }
      return stops_[idx];
    }
    if (idx >= last) return (unsigned)text_.size();
    if (stop_class(idx) == SC_NL) return stops_[idx + 1u];
    while (idx < last && stop_class(idx) == SC_WS) ++idx;
    if (idx < last && stop_class(idx) != SC_NL) {
      StopClass cls = stop_class(idx);
      while (idx < last && stop_class(idx) == cls) ++idx;
    }
    return stops_[idx];
  }
  unsigned line_boundary(unsigned offset, bool to_end) const {
    unsigned pos = to_end ? ceil_stop(offset) : floor_stop(offset);
    if (to_end) {
      while (pos < text_.size() && text_[pos] != '\n' && text_[pos] != '\r') ++pos;
      return floor_stop(pos);
    }
    while (pos > 0 && text_[pos - 1u] != '\n' && text_[pos - 1u] != '\r') --pos;
    return ceil_stop(pos);
  }
public:
  uint64_t revision() const { return revision_; }
  const std::string &text() const { return text_; }
  unsigned anchor() const { return anchor_; }
  unsigned focus() const { return focus_; }
  bool composing() const { return composing_; }
  const std::string &preedit() const { return preedit_; }
  unsigned replacement_start() const { return replacement_start_; }
  unsigned replacement_end() const { return replacement_end_; }
  unsigned preedit_anchor() const { return preedit_anchor_; }
  unsigned preedit_focus() const { return preedit_focus_; }
  std::string display_text() const {
    return composing_ ? text_.substr(0,replacement_start_) + preedit_ + text_.substr(replacement_end_) : text_;
  }
  unsigned display_anchor() const { return composing_ ? replacement_start_ + preedit_anchor_ : anchor_; }
  unsigned display_focus() const { return composing_ ? replacement_start_ + preedit_focus_ : focus_; }

  bool initialize(const char *data, unsigned length, unsigned anchor, unsigned focus) {
    if (revision_ || !valid(data,length)) return false;
    std::string text(length ? data : "", length); std::vector<unsigned> stops;
    if (!boundary(text,anchor) || !boundary(text,focus) || !xu_ui_grapheme::boundaries(text.data(),length,&stops)) return false;
    text_.swap(text); stops_.swap(stops); anchor_=anchor; focus_=focus; revision_=1; return true;
  }
  // Programmatic changes are compare-and-swap, so a stale worker snapshot
  // cannot overwrite a later native commit. Resetting active composition
  // requires ending the input session and creating a fresh session token.
  bool update(uint64_t expected, const char *data, unsigned length, unsigned anchor, unsigned focus) {
    if (!revision_ || expected != revision_ || !valid(data,length)) return false;
    std::string text(length ? data : "", length);
    if (!boundary(text,anchor) || !boundary(text,focus)) return false;
    if (text==text_ && anchor==anchor_ && focus==focus_) return true;
    if (composing_ || revision_==INT64_MAX) return false;
    std::vector<unsigned> stops; if (!xu_ui_grapheme::boundaries(text.data(),length,&stops)) return false;
    text_.swap(text); stops_.swap(stops); anchor_=anchor; focus_=focus; ++revision_; return true;
  }
  bool compose(const char *data, unsigned length, unsigned anchor, unsigned focus, XuUiEditChange *change,
               unsigned start=UINT_MAX, unsigned end=UINT_MAX) {
    if (!writable(change) || !valid(data,length)) return false;
    if (start==UINT_MAX && end==UINT_MAX) {
      start=composing_ ? replacement_start_ : std::min(anchor_,focus_);
      end=composing_ ? replacement_end_ : std::max(anchor_,focus_);
    }
    if (start>end || !boundary(text_,start) || !boundary(text_,end) || text_.size()-(end-start)+length>16384) return false;
    std::string value(length ? data : "",length);
    if (!boundary(value,anchor) || !boundary(value,focus)) return false;
    XuUiEditChange next; next.kind=XUE_PREEDIT; next.revision=revision_+1;
    next.start=start; next.end=end; next.anchor=anchor; next.focus=focus; next.text=value;
    preedit_.swap(value); preedit_anchor_=anchor; preedit_focus_=focus;
    replacement_start_=start; replacement_end_=end; composing_=true; ++revision_;
    *change=std::move(next); return true;
  }
  bool commit(const char *data, unsigned length, XuUiEditChange *change, unsigned start=UINT_MAX, unsigned end=UINT_MAX) {
    if (!writable(change) || !valid(data,length)) return false;
    if (start==UINT_MAX && end==UINT_MAX) {
      start=composing_ ? replacement_start_ : std::min(anchor_,focus_);
      end=composing_ ? replacement_end_ : std::max(anchor_,focus_);
    }
    if (start>end || !boundary(text_,start) || !boundary(text_,end) || text_.size()-(end-start)+length>16384) return false;
    std::string value(length ? data : "",length), result=text_.substr(0,start)+value+text_.substr(end);
    std::vector<unsigned> stops;
    if (!xu_ui_grapheme::boundaries(result.data(),(unsigned)result.size(),&stops)) return false;
    XuUiEditChange next; next.kind=XUE_COMMIT; next.revision=revision_+1; next.start=start; next.end=end;
    next.anchor=next.focus=start+length; next.text=std::move(value);
    text_.swap(result); stops_.swap(stops); anchor_=focus_=start+length;
    preedit_.clear(); composing_=false; replacement_start_=replacement_end_=preedit_anchor_=preedit_focus_=0;
    ++revision_; *change=std::move(next); return true;
  }
  bool cancel(XuUiEditChange *change) {
    if (!composing_) return noop(change);
    if (!writable(change)) return false;
    XuUiEditChange next; next.kind=XUE_CANCEL; next.revision=revision_+1; next.start=replacement_start_; next.end=replacement_end_;
    next.anchor=anchor_; next.focus=focus_;
    composing_=false; preedit_.clear(); replacement_start_=replacement_end_=preedit_anchor_=preedit_focus_=0;
    ++revision_; *change=std::move(next); return true;
  }
  bool select(unsigned anchor, unsigned focus, XuUiEditChange *change) {
    if (composing_ || !writable(change) || !boundary(text_,anchor) || !boundary(text_,focus)) return false;
    if (anchor==anchor_ && focus==focus_) return noop(change);
    XuUiEditChange next; next.kind=XUE_SELECTION; next.revision=revision_+1; next.anchor=anchor; next.focus=focus;
    anchor_=anchor; focus_=focus; ++revision_; *change=std::move(next); return true;
  }
  // IMEs may delete surrounding committed characters while keeping preedit.
  // These explicit scalar ranges differ from a user's grapheme Backspace.
  bool delete_surrounding(unsigned start,unsigned end,XuUiEditChange *change) {
    if (!writable(change) || start>end || !boundary(text_,start) || !boundary(text_,end)) return false;
    if (start==end) return noop(change);
    std::string result=text_.substr(0,start)+text_.substr(end); std::vector<unsigned> stops;
    if (!xu_ui_grapheme::boundaries(result.data(),(unsigned)result.size(),&stops)) return false;
    auto adjust=[&](unsigned index) { return index<=start ? index : index>=end ? index-(end-start) : start; };
    XuUiEditChange next; next.kind=XUE_SURROUNDING_DELETE; next.revision=revision_+1;
    next.start=start; next.end=end; next.anchor=adjust(anchor_); next.focus=adjust(focus_);
    text_.swap(result); stops_.swap(stops); anchor_=next.anchor; focus_=next.focus;
    if (composing_) { replacement_start_=adjust(replacement_start_); replacement_end_=adjust(replacement_end_); }
    ++revision_; *change=std::move(next); return true;
  }
  bool erase(bool backward, XuUiEditChange *change, unsigned count=1) {
    if (composing_ || !writable(change) || !count || count>16384) return false;
    unsigned start=std::min(anchor_,focus_), end=std::max(anchor_,focus_);
    unsigned first=0,last=0,extra=count;
    if (start!=end) {
      first=(unsigned)(std::lower_bound(stops_.begin(),stops_.end(),floor_stop(start))-stops_.begin());
      last=(unsigned)(std::lower_bound(stops_.begin(),stops_.end(),ceil_stop(end))-stops_.begin());
      --extra;
    } else if (backward) {
      if (!start) return noop(change);
      first=last=(unsigned)(std::lower_bound(stops_.begin(),stops_.end(),start)-stops_.begin());
    } else {
      auto at=std::upper_bound(stops_.begin(),stops_.end(),start);
      if (at==stops_.end()) return noop(change);
      first=last=(unsigned)(at-stops_.begin()-1);
    }
    if (backward) first=extra>first ? 0 : first-extra;
    else last=std::min((unsigned)stops_.size()-1,last+extra);
    return commit("",0,change,stops_[first],stops_[last]);
  }
  // Logical movement. Visual bidi/vertical navigation uses the text layout.
  bool move(bool backward, bool extend, XuUiEditChange *change) {
    if (composing_ || !writable(change)) return false;
    unsigned next=focus_;
    if (!extend && anchor_!=focus_) next=backward ? floor_stop(std::min(anchor_,focus_)) : ceil_stop(std::max(anchor_,focus_));
    else if (backward) {
      auto at=std::lower_bound(stops_.begin(),stops_.end(),focus_);
      if (at!=stops_.begin()) next=*(at-1);
    } else {
      auto at=std::upper_bound(stops_.begin(),stops_.end(),focus_);
      if (at!=stops_.end()) next=*at;
    }
    return select(extend ? anchor_ : next,next,change);
  }
  bool move_word(bool backward, bool extend, XuUiEditChange *change) {
    if (composing_ || !writable(change)) return false;
    unsigned base = (!extend && anchor_ != focus_)
      ? (backward ? floor_stop(std::min(anchor_, focus_)) : ceil_stop(std::max(anchor_, focus_)))
      : focus_;
    unsigned next = word_boundary(base, backward);
    return select(extend ? anchor_ : next, next, change);
  }
  bool erase_word(bool backward, XuUiEditChange *change) {
    if (composing_ || !writable(change)) return false;
    unsigned start = std::min(anchor_, focus_), end = std::max(anchor_, focus_);
    if (start != end) return commit("", 0, change, floor_stop(start), ceil_stop(end));
    unsigned bound = word_boundary(start, backward);
    if (bound == start) return noop(change);
    return commit("", 0, change, std::min(bound, start), std::max(bound, start));
  }
  bool move_line(bool to_end, bool extend, XuUiEditChange *change) {
    if (composing_ || !writable(change)) return false;
    unsigned base = (!extend && anchor_ != focus_)
      ? (to_end ? ceil_stop(std::max(anchor_, focus_)) : floor_stop(std::min(anchor_, focus_)))
      : focus_;
    unsigned next = line_boundary(base, to_end);
    return select(extend ? anchor_ : next, next, change);
  }
  bool erase_line(bool backward, XuUiEditChange *change) {
    if (composing_ || !writable(change)) return false;
    unsigned start = std::min(anchor_, focus_), end = std::max(anchor_, focus_);
    if (start != end) return commit("", 0, change, floor_stop(start), ceil_stop(end));
    unsigned bound = line_boundary(start, !backward);
    if (bound == start) return noop(change);
    return commit("", 0, change, std::min(bound, start), std::max(bound, start));
  }
  bool move_document(bool to_end, bool extend, XuUiEditChange *change) {
    if (composing_ || !writable(change)) return false;
    unsigned next = to_end ? (unsigned)text_.size() : 0u;
    return select(extend ? anchor_ : next, next, change);
  }
};
