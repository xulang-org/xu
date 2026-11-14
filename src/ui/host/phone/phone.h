#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void xu_phone_start(const char *platform);
void xu_phone_resize(double width, double height, double scale);
void xu_phone_insets(double top, double bottom, double left, double right, double ime_bottom);
void xu_phone_reduced_motion(int enabled);
void xu_phone_input(int kind, double x, double y, int buttons);
void xu_phone_active(int active);
void xu_phone_stop(void);
void xu_phone_redraw(void);
int xu_phone_back(void);
int xu_phone_dark(void);
int xu_phone_overlay(void);
/* Caller owns the returned UTF-8 JavaScript expression; free after use. */
char *xu_phone_poll(void);
void xu_phone_key(int kind, int key, int repeat, int modifiers);
/* Caller owns the returned ASCII-escaped JSON snapshot; free after use. */
char *xu_phone_text_input_state(void);
int xu_phone_text_input_commit(uint64_t id, uint64_t revision, const char *utf8, unsigned len);
int xu_phone_text_input_compose(uint64_t id, uint64_t revision, const char *utf8, unsigned len,
                                unsigned anchor16, unsigned focus16);
int xu_phone_text_input_finish_composing(uint64_t id, uint64_t revision);
int xu_phone_text_input_compose_region(uint64_t id, uint64_t revision, unsigned start16, unsigned end16);
int xu_phone_text_input_replace(uint64_t id, uint64_t revision, unsigned start16, unsigned end16,
                                const char *utf8, unsigned len);
int xu_phone_text_input_select(uint64_t id, uint64_t revision, unsigned anchor16, unsigned focus16);
int xu_phone_text_input_delete_surrounding(uint64_t id, uint64_t revision, unsigned before16, unsigned after16);
int xu_phone_text_input_erase(uint64_t id, uint64_t revision, int backward);
int xu_phone_text_input_move(uint64_t id, uint64_t revision, int backward, int extend);
int xu_phone_text_input_stop(uint64_t id);
#ifdef __cplusplus
}
#endif
