#pragma once

#include <stdbool.h>

/* Allocate the 64 KiB Xu heap and initialise the Xu object. Call early,
 * before Wi-Fi/BT fragment internal RAM. */
bool xu_host_init(void);

/* Update runtime configuration (loaded from NVS or BLE provisioning). */
void xu_host_set_runtime_config(const char *mqtt_uri, const char *mqtt_root,
                                const char *hid_name, const char *wifi_ssid);

/* Start the Xu task (MQTT client + command handling, written in Xu under xu/). */
bool xu_host_start(void);
