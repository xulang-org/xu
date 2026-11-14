#pragma once
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
#ifdef __cplusplus
}
#endif
