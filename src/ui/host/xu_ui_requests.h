// Canvas-scoped asynchronous desktop requests. All UI widgets stay on the host thread.
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define XU_UI_REQUEST_MAX_PENDING 64u
#define XU_UI_REQUEST_MAX_TEXT 65536u
#define XU_UI_REQUEST_MAX_QUEUED_BYTES (1024u * 1024u)
enum { XU_REQUEST_PROMPT = 1, XU_REQUEST_CLIPBOARD_READ = 2, XU_REQUEST_CLIPBOARD_WRITE = 3,
       XU_REQUEST_OPEN_FILES = 4, XU_REQUEST_SAVE_FILE = 5, XU_REQUEST_SELECT_FOLDERS = 6 };
enum { XU_REQUEST_COMPLETED = 0, XU_REQUEST_CANCELLED = 1, XU_REQUEST_FAILED = 2,
       XU_REQUEST_UNSUPPORTED = 3, XU_REQUEST_TIMED_OUT = 4 };
/* Reserve before submit; IDs are never reused. Abandon an unused reservation. */
uint64_t xu_ui_request_reserve(void);
void xu_ui_request_abandon(uint64_t id);
/* Wire: id/window/canvas/generation/kind/timeout_ms/private_result/title_hex/seed_hex,
 * separated by tabs. UTF-8 strings are hex encoded; NUL is rejected. */
int xu_ui_request_submit(const void *wire, unsigned length);
/* Atomically admit a queued request for this exact canvas generation. Owned result,
 * caller free(). A wrong target never consumes the request. */
char *xu_ui_request_take(uint64_t id, unsigned canvas, unsigned generation);
/* Exact-kind admission lets the shell handle desktop services without consuming
 * a prompt belonging to a content plugin. Zero/mismatched kinds never consume. */
char *xu_ui_request_take_kind(uint64_t id, unsigned canvas, unsigned generation, unsigned kind);
int xu_ui_request_alive(uint64_t id);
int xu_ui_request_complete(uint64_t id, unsigned status, const char *text, unsigned length);
int xu_ui_request_cancel(uint64_t id);
/* Private-result compatibility wait: 1 ready, 0 timed out, -1 missing/wrong mode. */
int xu_ui_request_wait(uint64_t id, int timeout_ms);
void xu_ui_request_poll(void);
void xu_ui_request_discard_marker(const char *command);
#ifdef __cplusplus
}
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>
static inline bool xu_request_id(const char *text, uint64_t *id) {
  if (!text || !*text) return false;
  uint64_t value = 0;
  for (; *text; ++text) {
    if (*text < '0' || *text > '9' || value > (INT64_MAX - (unsigned)(*text - '0')) / 10u) return false;
    value = value * 10u + (unsigned)(*text - '0');
  }
  *id = value;
  return value != 0;
}
static inline bool xu_request_marker(const char *command, uint64_t *id) {
  const char prefix[] = "__request\t";
  return command && strncmp(command, prefix, sizeof(prefix) - 1) == 0 &&
         xu_request_id(command + sizeof(prefix) - 1, id);
}
static inline int xu_request_hex_digit(unsigned char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}
static inline bool xu_request_unhex(const std::string &hex, std::string *text) {
  if (hex.size() % 2 || hex.size() / 2 > XU_UI_REQUEST_MAX_TEXT) return false;
  text->clear(); text->reserve(hex.size() / 2);
  for (size_t i = 0; i < hex.size(); i += 2) {
    int a = xu_request_hex_digit(hex[i]), b = xu_request_hex_digit(hex[i + 1]);
    if (a < 0 || b < 0 || (a == 0 && b == 0)) return false;
    text->push_back((char)(a * 16 + b));
  }
  return true;
}
static inline bool xu_request_prompt_text(const char *wire, std::string *title, std::string *seed) {
  std::vector<std::string> fields;
  const char *start = wire;
  for (const char *p = wire;; ++p) {
    if (*p == '\t' || !*p) { fields.emplace_back(start, p - start); start = p + 1; }
    if (!*p) break;
  }
  return fields.size() == 9 && fields[4] == "1" &&
         xu_request_unhex(fields[7], title) && xu_request_unhex(fields[8], seed);
}
/* The request table has already validated UTF-8, ownership and the service shape.
 * Return true only when this shell admitted a clipboard operation. */
static inline bool xu_request_clipboard_take(const char *command, unsigned canvas,
    unsigned generation, uint64_t *id, unsigned *kind, std::string *text) {
  if (!xu_request_marker(command, id)) return false;
  char *wire = xu_ui_request_take_kind(*id, canvas, generation, XU_REQUEST_CLIPBOARD_READ);
  *kind = XU_REQUEST_CLIPBOARD_READ;
  if (!wire) { wire = xu_ui_request_take_kind(*id, canvas, generation, XU_REQUEST_CLIPBOARD_WRITE); *kind = XU_REQUEST_CLIPBOARD_WRITE; }
  if (!wire) return false;
  const char *seed = strrchr(wire, '\t');
  bool valid = seed && xu_request_unhex(seed + 1, text);
  free(wire);
  if (!valid) { xu_ui_request_complete(*id, XU_REQUEST_FAILED, "invalid clipboard request", 25); *kind = 0; }
  return true;
}
#endif
