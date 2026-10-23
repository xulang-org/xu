// Shared Unicode character boundaries for the UI edit model, independent of
// native font ligatures and the platform's UTF-16 indexing. Internal C++ only.
#pragma once
#include "xu_draw_frame.h"
#include <array>
#include <vector>
#include <stdint.h>
#include <stddef.h>
namespace xu_ui_grapheme {
#include "third_party/libgrapheme/character_data.h"
#define XU_GRAPHEME_LIKELY(value) (value)
#include "third_party/libgrapheme/character.inc"
#undef XU_GRAPHEME_LIKELY

static inline bool boundaries(const char *text, unsigned length, std::vector<unsigned> *result) {
  if (!result || length > 16384 || (length && !text) || !xdf_utf8((const unsigned char *)text, length)) return false;
  std::vector<unsigned> stops; stops.reserve(length + 1u); stops.push_back(0);
  uint_least16_t state = 0; uint_least32_t previous = 0;
  for (unsigned offset = 0; offset < length;) {
    unsigned start = offset, first = (unsigned char)text[offset++], continuation;
    uint_least32_t cp;
    if (first < 0x80) { cp = first; continuation = 0; }
    else if (first < 0xe0) { cp = first & 31; continuation = 1; }
    else if (first < 0xf0) { cp = first & 15; continuation = 2; }
    else { cp = first & 7; continuation = 3; }
    while (continuation--) cp = (cp << 6) | ((unsigned char)text[offset++] & 63);
    if (start && character_break(previous, cp, &state)) stops.push_back(start);
    previous = cp;
  }
  if (length) stops.push_back(length);
  result->swap(stops); return true;
}
}
