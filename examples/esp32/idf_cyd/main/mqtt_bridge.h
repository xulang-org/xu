#pragma once

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const char *broker_uri; /* mqtt://IPv4:1883 */
    const char *topic_root; /* xu/esp32/cyd */
} mqtt_bridge_cfg_t;

bool mqtt_bridge_start(const mqtt_bridge_cfg_t *cfg);
void mqtt_bridge_stop(void);
bool mqtt_bridge_ready(void);

#ifdef __cplusplus
}
#endif
