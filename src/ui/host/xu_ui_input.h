// Raw input ABI. Coordinates are canvas-local logical pixels (before user CTM).
#pragma once
#include "xu_content_abi.h"
#include <charconv>
#include <chrono>
#include <math.h>
#include <string>
#include <string.h>

enum XuInputKind {
  XUI_POINTER_DOWN = 72, XUI_POINTER_UP, XUI_POINTER_MOVE,
  XUI_POINTER_ENTER, XUI_POINTER_LEAVE, XUI_POINTER_CANCEL,
  XUI_KEY_DOWN, XUI_KEY_UP, XUI_POINTER_SCROLL
};
enum XuKey {
  XUI_KEY_ESCAPE = 256, XUI_KEY_TAB, XUI_KEY_ENTER, XUI_KEY_BACKSPACE,
  XUI_KEY_DELETE, XUI_KEY_LEFT, XUI_KEY_RIGHT, XUI_KEY_UP_ARROW, XUI_KEY_DOWN_ARROW,
  XUI_KEY_HOME, XUI_KEY_END, XUI_KEY_PAGE_UP, XUI_KEY_PAGE_DOWN, XUI_KEY_INSERT,
  XUI_KEY_F1 = 288
};

static inline void xu_ui_input_emit(const XuContentHost *host, unsigned kind,
    double x = 0, double y = 0, double dx = 0, double dy = 0,
    unsigned button = 0, unsigned buttons = 0, unsigned modifiers = 0,
    unsigned key = 0, unsigned scan = 0, unsigned repeat = 0, unsigned clicks = 0) {
  if (!host || !host->append_shell_event) return;
  char line[512];
  char *at = line, *end = line + sizeof(line) - 1;
  auto number = [&](auto value) {
    if (at >= end) return false;
    *at++ = '\t';
    auto result = std::to_chars(at, end, value);
    if (result.ec != std::errc()) return false;
    at = result.ptr;
    return true;
  };
  unsigned generation = host->canvas_generation;
  const char *tag = generation ? "input2" : "input";
  memcpy(at, tag, strlen(tag)); at += strlen(tag);
  for (double value : {x, y, dx, dy}) if (!isfinite(value) || fabs(value) > 1e9) return;
  auto now = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
  if (!number(kind) || !number(host->window_id ? host->window_id : 1u) ||
      !number(host->canvas_id ? host->canvas_id : 1u) ||
      (generation && !number(generation)) ||
      !number(x) || !number(y) || !number(dx) || !number(dy) ||
      !number(button) || !number(buttons) || !number(modifiers) ||
      !number(key) || !number(scan) || !number(repeat) || !number(clicks) || !number(now)) return;
  *at = 0;
  host->append_shell_event(line);
}

static inline void xu_ui_canvas_event(const XuContentHost *host, bool opened) {
  if (!host || !host->append_shell_event || !host->canvas_generation) return;
  std::string event = opened ? "canvas_ready" : "canvas_closed";
  event += "\t" + std::to_string(host->window_id) + "\t" + std::to_string(host->canvas_id) +
           "\t" + std::to_string(host->canvas_generation);
  host->append_shell_event(event.c_str());
}

// Backing dimensions describe the render buffer, not physical monitor size.
static inline void xu_ui_canvas_metrics(const XuContentHost *host, double width, double height,
                                        unsigned buffer_width, unsigned buffer_height,
                                        double scale_x, double scale_y) {
  if (!host || !host->append_shell_event || !host->canvas_generation) return;
  char line[384]; char *at = line, *end = line + sizeof(line) - 1;
  memcpy(at, "canvas_metrics", 14); at += 14;
  auto number = [&](auto value) {
    if (at >= end) return false;
    *at++ = '\t'; auto result = std::to_chars(at, end, value);
    if (result.ec != std::errc()) return false;
    at = result.ptr; return true;
  };
  if (!number(host->window_id) || !number(host->canvas_id) || !number(host->canvas_generation) ||
      !number(width) || !number(height) || !number(buffer_width) || !number(buffer_height) ||
      !number(scale_x) || !number(scale_y)) return;
  *at = 0; host->append_shell_event(line);
}
