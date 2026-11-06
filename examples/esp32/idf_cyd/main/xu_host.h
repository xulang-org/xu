#pragma once

#include <stdbool.h>

/* Allocate the 64 KiB Xu heap and initialise the Xu object. Call early,
 * before Wi-Fi/BT fragment internal RAM. */
bool xu_host_init(void);

/* Start the Xu task (MQTT client + command handling, written in Xu under xu/). */
bool xu_host_start(void);
