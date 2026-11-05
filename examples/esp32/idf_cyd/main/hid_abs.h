#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

bool hid_abs_start(const char *device_name);
void hid_abs_stop(void);
bool hid_abs_connected(void);
bool hid_abs_encrypted_ready(void);
bool hid_abs_mouse_subscribed(void);
bool hid_abs_keyboard_subscribed(void);
bool hid_abs_consumer_subscribed(void);

bool hid_abs_advertising(void);
bool hid_abs_paired(void);
void hid_abs_last_mouse(uint16_t *x, uint16_t *y, bool *down);

bool hid_abs_set_advertising(bool enable);
bool hid_abs_disconnect(void);

/* Absolute mouse: buttons + little-endian X/Y in 0..32767 (5 bytes). */
bool hid_abs_send_mouse(const uint8_t report[5]);
bool hid_abs_send_keyboard(const uint8_t report[8]);
bool hid_abs_send_consumer(uint8_t mask);

/* Release held buttons at the last absolute point (never jump to 0,0). */
bool hid_abs_release_all(void);

#ifdef __cplusplus
}
#endif
