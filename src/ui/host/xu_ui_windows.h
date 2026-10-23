// Bounded process-local desktop window identities. Native widgets stay on the UI thread.
#pragma once
#ifdef __cplusplus
extern "C" {
#endif
#define XU_UI_WINDOW_MAX_COUNT 64u
#define XU_UI_WINDOW_MAX_TITLE 4096u
/* Reserve -> upload XUW1 -> claim -> ready -> close. IDs and canvas generations
 * never repeat. meta: id,generation,width,height,content_kind,state (2 queued,
 * 3 creating,4 ready). A wrong generation never consumes another window. */
int xu_ui_window_reserve(unsigned *identity2);
void xu_ui_window_abandon(unsigned id, unsigned generation);
int xu_ui_window_info(unsigned id, unsigned generation, unsigned *meta6, char *title, unsigned capacity);
int xu_ui_window_claim(unsigned id, unsigned generation);
int xu_ui_window_ready(unsigned id, unsigned generation);
void xu_ui_window_closed(unsigned id, unsigned generation);
unsigned xu_ui_window_count(void);
void xu_ui_windows_shutdown(void);
int xu_ui_canvas_valid(unsigned window, unsigned canvas, unsigned generation);
/* Resolve unscoped resource markers without taking/consuming the resource. */
int xu_ui_command_owner(const char *command, unsigned *identity2);
/* Wrap legacy shell events; typed canvas/input/request records already carry identity. */
void xu_ui_window_event(unsigned id, unsigned generation, const char *payload);
#ifdef __cplusplus
}
#endif
