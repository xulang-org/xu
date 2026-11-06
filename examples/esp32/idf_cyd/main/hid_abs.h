#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HID_ABS_MAX_PEERS 4

typedef void (*hid_prov_cb_t)(const char *ssid, const char *pass, const char *mqtt_uri,
                              const char *mqtt_root, const char *hid_name);

/* Stage 1 (Before Wi-Fi is connected): BLE Wi-Fi Provisioning GATT Service (0xFF00). */
bool hid_prov_start(const char *setup_name, hid_prov_cb_t cb);
void hid_prov_notify(const char *json_status);
void hid_prov_stop(void);
bool hid_prov_active(void);

/* Stage 2 (After Wi-Fi is connected): Multi-peer BLE HID Service (0x1812). */
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

/* Multi-peer queries and targeted control (slot in 0..HID_ABS_MAX_PEERS-1, or -1 for default). */
int hid_abs_connected_count(void);
bool hid_abs_peer_connected(int slot);
bool hid_abs_peer_ready(int slot);
const char *hid_abs_peer_bda(int slot);
const char *hid_abs_peer_name(int slot);

bool hid_abs_disconnect_to(int target);
bool hid_abs_release_all_to(int target);
bool hid_abs_send_mouse_to(int target, const uint8_t report[5]);
bool hid_abs_send_keyboard_to(int target, const uint8_t report[8]);
bool hid_abs_send_consumer_to(int target, uint8_t mask);

/* Absolute mouse: buttons + little-endian X/Y in 0..32767 (5 bytes). */
bool hid_abs_send_mouse(const uint8_t report[5]);
bool hid_abs_send_keyboard(const uint8_t report[8]);
bool hid_abs_send_consumer(uint8_t mask);

/* Release held buttons at the last absolute point (never jump to 0,0). */
bool hid_abs_release_all(void);

#ifdef __cplusplus
}
#endif
