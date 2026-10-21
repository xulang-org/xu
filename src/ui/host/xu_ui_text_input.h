// Session-scoped IME/editing bridge. All text positions count UTF-8 bytes.
#pragma once
#include <stdint.h>
#define XU_UI_TEXT_INPUT_MAX_COUNT 64u
#define XU_UI_TEXT_INPUT_MAX_EVENTS 256u
#define XU_UI_TEXT_INPUT_MAX_EVENT_BYTES (1024u * 1024u)
#define XU_UI_TEXT_INPUT_SNAPSHOT_BYTES (112u + 32768u)
enum XuUiTextInputKind { XUTI_COMMIT=1, XUTI_PREEDIT, XUTI_CANCEL, XUTI_SELECTION, XUTI_READY, XUTI_ENDED, XUTI_FAILED, XUTI_SURROUNDING_DELETE };
enum XuUiTextInputReason { XUTI_STOPPED, XUTI_WINDOW_CLOSED, XUTI_BACKPRESSURE, XUTI_NATIVE_UNAVAILABLE, XUTI_ACTIVATION_TIMEOUT };
#ifdef __cplusplus
extern "C" {
#endif
uint64_t xu_ui_text_input_reserve(void);
void xu_ui_text_input_abandon(uint64_t);
// Roll back a newly started session when its creator cannot read metadata.
void xu_ui_text_input_abort(uint64_t);
int xu_ui_text_input_start(uint64_t, unsigned canvas, unsigned generation, const char *, unsigned length,
                            unsigned anchor, unsigned focus, const double *caret4, unsigned flags);
int xu_ui_text_input_update(uint64_t, unsigned canvas, unsigned generation, uint64_t expected_revision,
                             const char *, unsigned length, unsigned anchor, unsigned focus, const double *caret4);
int xu_ui_text_input_stop(uint64_t, unsigned canvas, unsigned generation, unsigned reason);
int xu_ui_text_input_active(uint64_t);
int xu_ui_text_input_activate(uint64_t, unsigned canvas, unsigned generation);
// Atomic owned XIS1 record. caller free(). take=1 also acknowledges a command
// marker; workers use take=0 so queries never steal native notifications.
void *xu_ui_text_input_snapshot(uint64_t, unsigned canvas, unsigned generation, int take, unsigned *length);
unsigned xu_ui_text_input_window(uint64_t);
int xu_ui_text_input_commit(uint64_t, const char *, unsigned length, unsigned start, unsigned end);
int xu_ui_text_input_compose(uint64_t, const char *, unsigned length, unsigned anchor, unsigned focus,
                              unsigned start, unsigned end);
// Snapshot-derived byte ranges must use checked mutations: a worker may have
// changed the document since the native client converted UTF-16/scalar offsets.
int xu_ui_text_input_commit_at(uint64_t, uint64_t revision, const char *, unsigned length, unsigned start, unsigned end);
int xu_ui_text_input_compose_at(uint64_t, uint64_t revision, const char *, unsigned length, unsigned anchor, unsigned focus, unsigned start, unsigned end);
int xu_ui_text_input_delete_surrounding_at(uint64_t, uint64_t revision, unsigned start, unsigned end);
int xu_ui_text_input_select_all(uint64_t);
int xu_ui_text_input_cancel(uint64_t);
int xu_ui_text_input_select(uint64_t, unsigned anchor, unsigned focus);
int xu_ui_text_input_delete_surrounding(uint64_t, unsigned start, unsigned end);
int xu_ui_text_input_erase(uint64_t, int backward);
int xu_ui_text_input_erase_count(uint64_t, int backward, unsigned count);
int xu_ui_text_input_move(uint64_t, int backward, int extend);
// Bind the immutable layout of this revision's display text. Transform maps
// layout top-left coordinates into canvas logical coordinates, before camera
// and DPI. upstream chooses the preceding grapheme edge at soft wraps/bidi.
// layout=0 explicitly unbinds; transform must then be NULL, upstream=0.
int xu_ui_text_input_bind(uint64_t, unsigned canvas, unsigned generation, uint64_t revision,
                          uint64_t layout, const double *transform6, unsigned upstream);
// mode: 0 canvas point hit, 1 caret, 2 first cluster rectangle, 3 current focus.
// result8: UTF-8 cluster index/length, trailing, inside, canvas x/y/width/height.
// Fails on stale revision, missing binding or unavailable native queries.
int xu_ui_text_input_query(uint64_t, unsigned canvas, unsigned generation, uint64_t revision,
                           unsigned mode, unsigned index, unsigned trailing, double x, double y, double *result8);
void xu_ui_text_input_poll(void);
#ifdef __cplusplus
}
#endif
