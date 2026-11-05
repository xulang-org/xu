#include "mqtt_bridge.h"

#include <stdio.h>
#include <string.h>

#include "control_parse.h"
#include "esp_log.h"
#include "hid_abs.h"
#include "mqtt_client.h"

static const char *TAG = "mqtt_bridge";

typedef struct {
    char id[65];
    char payload[513];
    char result[192];
} seen_op_t;

static esp_mqtt_client_handle_t s_client;
static char s_root[64];
static char s_cmd[96];
static char s_result[96];
static char s_status[96];
static seen_op_t s_seen[16];
static int s_seen_count;
static bool s_ready;

static void remember(const char *id, const char *payload, const char *result) {
    if (s_seen_count >= 16) {
        memmove(&s_seen[0], &s_seen[1], sizeof(seen_op_t) * 15);
        s_seen_count = 15;
    }
    seen_op_t *slot = &s_seen[s_seen_count++];
    memset(slot, 0, sizeof(*slot));
    strncpy(slot->id, id, sizeof(slot->id) - 1);
    strncpy(slot->payload, payload, sizeof(slot->payload) - 1);
    strncpy(slot->result, result, sizeof(slot->result) - 1);
}

static const char *find_cached(const char *id, const char *payload) {
    for (int i = 0; i < s_seen_count; i++) {
        if (strcmp(s_seen[i].id, id) == 0) {
            if (strcmp(s_seen[i].payload, payload) != 0) {
                return "id_conflict";
            }
            return s_seen[i].result;
        }
    }
    return NULL;
}

static void publish_result(const char *id, const char *status) {
    char body[256];
    snprintf(body, sizeof(body), "{\"id\":\"%s\",\"result\":\"%s\"}", id, status);
    esp_mqtt_client_publish(s_client, s_result, body, 0, 1, 0);
}

static void publish_status(void) {
    char body[320];
    snprintf(body, sizeof(body),
             "{\"online\":true,\"wifi\":true,\"ble_connected\":%s,\"encrypted\":%s,"
             "\"advertising\":true,\"keyboard\":%s,\"mouse\":%s,\"consumer\":%s}",
             hid_abs_connected() ? "true" : "false",
             hid_abs_encrypted_ready() ? "true" : "false",
             hid_abs_keyboard_subscribed() ? "true" : "false",
             hid_abs_mouse_subscribed() ? "true" : "false",
             hid_abs_consumer_subscribed() ? "true" : "false");
    esp_mqtt_client_publish(s_client, s_status, body, 0, 1, 1);
}

static const char *apply_command(const xu_command_t *cmd) {
    switch (cmd->op) {
    case XU_OP_STATUS:
        return "ok";
    case XU_OP_ADVERTISING_START:
        return hid_abs_set_advertising(true) ? "queued" : "busy_controller";
    case XU_OP_ADVERTISING_STOP:
        return hid_abs_set_advertising(false) ? "queued" : "busy_controller";
    case XU_OP_DISCONNECT:
        if (!hid_abs_connected()) {
            return "already_disconnected";
        }
        return hid_abs_disconnect() ? "queued" : "busy_controller";
    case XU_OP_RELEASE_ALL:
        return hid_abs_release_all() ? "queued" : "busy_controller";
    case XU_OP_KEYBOARD:
        if (!hid_abs_keyboard_subscribed()) {
            return "not_ready";
        }
        return hid_abs_send_keyboard(cmd->report) ? "queued" : "busy_controller";
    case XU_OP_MOUSE:
        if (!hid_abs_mouse_subscribed()) {
            return "not_ready";
        }
        return hid_abs_send_mouse(cmd->report) ? "queued" : "busy_controller";
    case XU_OP_CONSUMER:
        if (!hid_abs_consumer_subscribed()) {
            return "not_ready";
        }
        return hid_abs_send_consumer(cmd->report[0]) ? "queued" : "busy_controller";
    default:
        return "invalid_command";
    }
}

static void handle_cmd(const char *data, int len, bool retained) {
    if (retained) {
        publish_result("", "retained_rejected");
        return;
    }
    char tmp[513];
    if (len < 0 || len >= (int)sizeof(tmp)) {
        publish_result("", "invalid_command");
        return;
    }
    memcpy(tmp, data, (size_t)len);
    tmp[len] = 0;
    xu_command_t cmd = xu_control_parse(tmp, (size_t)len);
    if (!cmd.valid) {
        publish_result("", "invalid_command");
        return;
    }
    const char *cached = find_cached(cmd.id, tmp);
    if (cached) {
        if (strcmp(cached, "id_conflict") == 0) {
            publish_result(cmd.id, "id_conflict");
        } else {
            esp_mqtt_client_publish(s_client, s_result, cached, 0, 1, 0);
        }
        return;
    }
    const char *status = apply_command(&cmd);
    char body[320];
    if (cmd.op == XU_OP_STATUS) {
        snprintf(body, sizeof(body),
                 "{\"id\":\"%s\",\"result\":\"ok\",\"state\":{\"ble_connected\":%s,\"encrypted\":%s,"
                 "\"keyboard\":%s,\"mouse\":%s,\"consumer\":%s}}",
                 cmd.id, hid_abs_connected() ? "true" : "false",
                 hid_abs_encrypted_ready() ? "true" : "false",
                 hid_abs_keyboard_subscribed() ? "true" : "false",
                 hid_abs_mouse_subscribed() ? "true" : "false",
                 hid_abs_consumer_subscribed() ? "true" : "false");
        esp_mqtt_client_publish(s_client, s_result, body, 0, 1, 0);
        remember(cmd.id, tmp, body);
        return;
    }
    snprintf(body, sizeof(body), "{\"id\":\"%s\",\"result\":\"%s\"}", cmd.id, status);
    esp_mqtt_client_publish(s_client, s_result, body, 0, 1, 0);
    remember(cmd.id, tmp, body);
    ESP_LOGI(TAG, "cmd %s -> %s", cmd.id, status);
}

static void mqtt_event(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    (void)handler_args;
    (void)base;
    esp_mqtt_event_handle_t event = event_data;
    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED:
        s_ready = true;
        esp_mqtt_client_subscribe(s_client, s_cmd, 1);
        publish_status();
        ESP_LOGI(TAG, "MQTT connected; subscribed %s", s_cmd);
        break;
    case MQTT_EVENT_DISCONNECTED:
        s_ready = false;
        ESP_LOGW(TAG, "MQTT disconnected");
        break;
    case MQTT_EVENT_DATA:
        if (event->topic_len == (int)strlen(s_cmd) && memcmp(event->topic, s_cmd, event->topic_len) == 0) {
            handle_cmd(event->data, event->data_len, event->retain == 1);
        }
        break;
    default:
        break;
    }
}

bool mqtt_bridge_start(const mqtt_bridge_cfg_t *cfg) {
    if (!cfg || !cfg->broker_uri || !cfg->topic_root) {
        return false;
    }
    strncpy(s_root, cfg->topic_root, sizeof(s_root) - 1);
    snprintf(s_cmd, sizeof(s_cmd), "%s/cmd", s_root);
    snprintf(s_result, sizeof(s_result), "%s/result", s_root);
    snprintf(s_status, sizeof(s_status), "%s/status", s_root);

    esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri = cfg->broker_uri,
        .session.last_will =
            {
                .topic = s_status,
                .msg = "0",
                .msg_len = 1,
                .qos = 1,
                .retain = true,
            },
    };
    s_client = esp_mqtt_client_init(&mqtt_cfg);
    if (!s_client) {
        return false;
    }
    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, mqtt_event, NULL);
    return esp_mqtt_client_start(s_client) == ESP_OK;
}

void mqtt_bridge_stop(void) {
    if (s_client) {
        esp_mqtt_client_stop(s_client);
        esp_mqtt_client_destroy(s_client);
        s_client = NULL;
    }
    s_ready = false;
}

bool mqtt_bridge_ready(void) {
    return s_ready;
}
