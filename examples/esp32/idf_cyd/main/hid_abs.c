#include "hid_abs.h"

#include <stdio.h>
#include <string.h>

#include "esp_bt.h"
#include "esp_bt_device.h"
#include "esp_bt_main.h"
#include "esp_event.h"
#include "esp_gap_ble_api.h"
#include "esp_gatt_defs.h"
#include "esp_gattc_api.h"
#include "esp_gatts_api.h"
#include "esp_hidd.h"
#include "esp_hidd_gatts.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

static const char *TAG = "hid_abs";

enum {
    HID_RPT_MOUSE = 1,
    HID_RPT_KEYBOARD = 2,
    HID_RPT_CONSUMER = 3,
    HID_MOUSE_ABS_MAX = 32767,
};

/* Stage 1 BLE Provisioning GATT Service (0xFF00) attribute indices. */
enum {
    PROV_IDX_SVC = 0,
    PROV_IDX_CFG_CHAR,
    PROV_IDX_CFG_VAL,
    PROV_IDX_STS_CHAR,
    PROV_IDX_STS_VAL,
    PROV_IDX_STS_CCC,
    PROV_IDX_NB,
};

#define PROV_APP_ID 0x55

typedef struct {
    bool has_bda;
    bool connected;
    bool paired;
    uint16_t conn_id;
    esp_bd_addr_t bda;
    esp_ble_addr_type_t addr_type;
    char bda_str[18];
    char name[32];
    int32_t cur_px;
    int32_t cur_py;
    bool homed;
    uint16_t last_x;
    uint16_t last_y;
    bool mouse_down;
    uint32_t last_down_tick;
    uint32_t last_act_tick;
    bool key_down;
    bool consumer_down;
    uint16_t ccc_mouse;
    uint16_t ccc_boot_mouse;
    uint16_t ccc_keyboard;
    uint16_t ccc_consumer;
    uint16_t gap_start_hdl;
    uint16_t gap_end_hdl;
    int32_t screen_w;
    int32_t screen_h;
    int32_t max_w;
    int32_t max_h;
} hid_peer_t;

/* Standard Relative mouse (4 bytes: buttons, dx, dy, wheel) + keyboard + consumer — fully compliant with Apple iOS/iPadOS AssistiveTouch and CoreOS. */
static const uint8_t s_report_map[] = {
    // Report ID 1: Standard Relative Mouse (4 bytes: buttons, dx, dy, wheel)
    0x05, 0x01,                    // Usage Page (Generic Desktop)
    0x09, 0x02,                    // Usage (Mouse)
    0xA1, 0x01,                    // Collection (Application)
    0x85, 0x01,                    //   Report ID (1)
    0x09, 0x01,                    //   Usage (Pointer)
    0xA1, 0x00,                    //   Collection (Physical)
    0x05, 0x09,                    //     Usage Page (Button)
    0x19, 0x01,                    //     Usage Minimum (Button 1)
    0x29, 0x03,                    //     Usage Maximum (Button 3)
    0x15, 0x00,                    //     Logical Minimum (0)
    0x25, 0x01,                    //     Logical Maximum (1)
    0x75, 0x01,                    //     Report Size (1)
    0x95, 0x03,                    //     Report Count (3)
    0x81, 0x02,                    //     Input (Data, Variable, Absolute)
    0x75, 0x05,                    //     Report Size (5)
    0x95, 0x01,                    //     Report Count (1)
    0x81, 0x03,                    //     Input (Constant, Variable, Absolute) - 5-bit padding
    0x05, 0x01,                    //     Usage Page (Generic Desktop)
    0x09, 0x30,                    //     Usage (X)
    0x09, 0x31,                    //     Usage (Y)
    0x09, 0x38,                    //     Usage (Wheel)
    0x15, 0x81,                    //     Logical Minimum (-127)
    0x25, 0x7F,                    //     Logical Maximum (127)
    0x75, 0x08,                    //     Report Size (8)
    0x95, 0x03,                    //     Report Count (3)
    0x81, 0x06,                    //     Input (Data, Variable, Relative)
    0xC0,                          //   End Collection
    0xC0,                          // End Collection

    // Report ID 2: Keyboard (8 bytes)
    0x05, 0x01,                    // Usage Page (Generic Desktop)
    0x09, 0x06,                    // Usage (Keyboard)
    0xA1, 0x01,                    // Collection (Application)
    0x85, 0x02,                    //   Report ID (2)
    0x05, 0x07,                    //   Usage Page (Key Codes)
    0x19, 0xE0,                    //   Usage Minimum (224)
    0x29, 0xE7,                    //   Usage Maximum (231)
    0x15, 0x00,                    //   Logical Minimum (0)
    0x25, 0x01,                    //   Logical Maximum (1)
    0x75, 0x01,                    //   Report Size (1)
    0x95, 0x08,                    //   Report Count (8)
    0x81, 0x02,                    //   Input (Data, Variable, Absolute)
    0x95, 0x01,                    //   Report Count (1)
    0x75, 0x08,                    //   Report Size (8)
    0x81, 0x03,                    //   Input (Constant, Variable, Absolute) - Reserved byte
    0x95, 0x06,                    //   Report Count (6)
    0x75, 0x08,                    //   Report Size (8)
    0x15, 0x00,                    //   Logical Minimum (0)
    0x25, 0x73,                    //   Logical Maximum (115)
    0x05, 0x07,                    //   Usage Page (Key Codes)
    0x19, 0x00,                    //   Usage Minimum (0)
    0x29, 0x73,                    //   Usage Maximum (115)
    0x81, 0x00,                    //   Input (Data, Array, Absolute)
    0xC0,                          // End Collection

    // Report ID 3: Consumer (1 byte)
    0x05, 0x0C,                    // Usage Page (Consumer)
    0x09, 0x01,                    // Usage (Consumer Control)
    0xA1, 0x01,                    // Collection (Application)
    0x85, 0x03,                    //   Report ID (3)
    0x09, 0xE9,                    //   Usage (Volume Increment)
    0x09, 0xEA,                    //   Usage (Volume Decrement)
    0x09, 0xE2,                    //   Usage (Mute)
    0x09, 0x30,                    //   Usage (Power)
    0x09, 0x40,                    //   Usage (Menu / Home)
    0x15, 0x00,                    //   Logical Minimum (0)
    0x25, 0x01,                    //   Logical Maximum (1)
    0x75, 0x01,                    //   Report Size (1)
    0x95, 0x05,                    //   Report Count (5)
    0x81, 0x02,                    //   Input (Data, Variable, Absolute)
    0x75, 0x03,                    //   Report Size (3)
    0x95, 0x01,                    //   Report Count (1)
    0x81, 0x03,                    //   Input (Constant, Variable, Absolute) - 3-bit padding
    0xC0,                          // End Collection
};

static bool s_bt_stack_ready = false;
static bool s_prov_mode = false;
static char s_prov_name[32] = "XuPlay-Setup";
static hid_prov_cb_t s_prov_cb = NULL;
static esp_gatt_if_t s_prov_gatts_if = ESP_GATT_IF_NONE;
static uint16_t s_prov_handles[PROV_IDX_NB] = {0};
static bool s_prov_connected = false;
static uint16_t s_prov_conn_id = 0;
static char s_prov_rx_buf[384];
static size_t s_prov_rx_len = 0;
static char s_prov_status[160] = "{\"state\":\"provisioning\"}";

static const uint16_t s_uuid_pri_svc = ESP_GATT_UUID_PRI_SERVICE;
static const uint16_t s_uuid_char_decl = ESP_GATT_UUID_CHAR_DECLARE;
static const uint16_t s_uuid_ccc = ESP_GATT_UUID_CHAR_CLIENT_CONFIG;
static const uint16_t s_uuid_prov_svc = 0xFF00;
static const uint16_t s_uuid_prov_cfg = 0xFF01;
static const uint16_t s_uuid_prov_sts = 0xFF02;
static const uint8_t s_prop_write = ESP_GATT_CHAR_PROP_BIT_WRITE | ESP_GATT_CHAR_PROP_BIT_WRITE_NR;
static const uint8_t s_prop_read_notify = ESP_GATT_CHAR_PROP_BIT_READ | ESP_GATT_CHAR_PROP_BIT_NOTIFY;
static uint16_t s_prov_ccc_val = 0;

static const esp_gatts_attr_db_t s_prov_gatt_db[PROV_IDX_NB] = {
    [PROV_IDX_SVC] = {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&s_uuid_pri_svc, ESP_GATT_PERM_READ, sizeof(uint16_t), sizeof(s_uuid_prov_svc), (uint8_t *)&s_uuid_prov_svc}},
    [PROV_IDX_CFG_CHAR] = {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&s_uuid_char_decl, ESP_GATT_PERM_READ, 1, 1, (uint8_t *)&s_prop_write}},
    [PROV_IDX_CFG_VAL] = {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&s_uuid_prov_cfg, ESP_GATT_PERM_WRITE, 256, 0, NULL}},
    [PROV_IDX_STS_CHAR] = {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&s_uuid_char_decl, ESP_GATT_PERM_READ, 1, 1, (uint8_t *)&s_prop_read_notify}},
    [PROV_IDX_STS_VAL] = {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&s_uuid_prov_sts, ESP_GATT_PERM_READ, sizeof(s_prov_status), 24, (uint8_t *)s_prov_status}},
    [PROV_IDX_STS_CCC] = {{ESP_GATT_AUTO_RSP}, {ESP_UUID_LEN_16, (uint8_t *)&s_uuid_ccc, ESP_GATT_PERM_READ | ESP_GATT_PERM_WRITE, sizeof(uint16_t), sizeof(s_prov_ccc_val), (uint8_t *)&s_prov_ccc_val}},
};

static esp_hidd_dev_t *s_hid = NULL;
static hid_peer_t s_peers[HID_ABS_MAX_PEERS];
static esp_gatt_if_t s_hid_gatts_if = ESP_GATT_IF_NONE;
static esp_gatt_if_t s_gattc_if = ESP_GATT_IF_NONE;
static uint16_t s_mouse_handle = 0;
static uint16_t s_boot_mouse_handle = 0;
static uint16_t s_keyboard_handle = 0;
static uint16_t s_boot_kb_handle = 0;
static uint16_t s_consumer_handle = 0;

static bool s_protocol_ok = false;
static bool s_want_adv = true;
static bool s_adv_active = false;
static uint16_t s_last_x = 0;
static uint16_t s_last_y = 0;
static bool s_mouse_down = false;
static char s_name[32] = "XuPlay";

static void format_bda(const esp_bd_addr_t bda, char out[18]) {
    snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X",
             bda[0], bda[1], bda[2], bda[3], bda[4], bda[5]);
}

static int find_peer_by_bda(const esp_bd_addr_t bda) {
    for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
        if (s_peers[i].has_bda && memcmp(s_peers[i].bda, bda, ESP_BD_ADDR_LEN) == 0) {
            return i;
        }
    }
    return -1;
}

static int alloc_peer_slot(const esp_bd_addr_t bda) {
    int existing = find_peer_by_bda(bda);
    if (existing >= 0) {
        return existing;
    }
    for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
        if (!s_peers[i].has_bda) {
            return i;
        }
    }
    for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
        if (!s_peers[i].connected) {
            return i;
        }
    }
    return -1;
}

static int resolve_peer_slot(int target) {
    if (target >= 0 && target < HID_ABS_MAX_PEERS) {
        return s_peers[target].connected ? target : -1;
    }
    for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
        if (s_peers[i].connected) {
            return i;
        }
    }
    return -1;
}

static bool start_prov_advertising(void) {
    static uint8_t prov_service_uuid128[] = {
        0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80, 0x00, 0x10, 0x00, 0x00, 0x00, 0xff, 0x00, 0x00,
    };
    esp_ble_adv_data_t adv = {0};
    adv.service_uuid_len = sizeof(prov_service_uuid128);
    adv.p_service_uuid = prov_service_uuid128;
    adv.set_scan_rsp = false;
    adv.include_name = true;
    adv.appearance = 0x0000;
    adv.flag = ESP_BLE_ADV_FLAG_GEN_DISC | ESP_BLE_ADV_FLAG_BREDR_NOT_SPT;
    if (esp_ble_gap_set_device_name(s_prov_name) != ESP_OK) {
        return false;
    }
    if (esp_ble_gap_config_adv_data(&adv) != ESP_OK) {
        return false;
    }
    esp_ble_adv_params_t params = {0};
    params.adv_int_min = 0x20;
    params.adv_int_max = 0x40;
    params.adv_type = ADV_TYPE_IND;
    params.own_addr_type = BLE_ADDR_TYPE_PUBLIC;
    params.channel_map = ADV_CHNL_ALL;
    params.adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY;
    return esp_ble_gap_start_advertising(&params) == ESP_OK;
}

static bool start_advertising(void) {
    if (s_prov_mode) {
        return start_prov_advertising();
    }
    if (hid_abs_connected_count() >= HID_ABS_MAX_PEERS) {
        return true;
    }
    static uint8_t hid_service_uuid128[] = {
        0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80, 0x00, 0x10, 0x00, 0x00, 0x12, 0x18, 0x00, 0x00,
    };
    esp_ble_adv_data_t adv = {0};
    adv.service_uuid_len = sizeof(hid_service_uuid128);
    adv.p_service_uuid = hid_service_uuid128;
    adv.set_scan_rsp = false;
    adv.include_name = true;
    adv.appearance = 0x03C2; /* mouse */
    adv.flag = ESP_BLE_ADV_FLAG_GEN_DISC | ESP_BLE_ADV_FLAG_BREDR_NOT_SPT;
    if (esp_ble_gap_set_device_name(s_name) != ESP_OK) {
        return false;
    }
    if (esp_ble_gap_config_adv_data(&adv) != ESP_OK) {
        return false;
    }
    esp_ble_adv_params_t params = {0};
    params.adv_int_min = 0x20;
    params.adv_int_max = 0x40;
    params.adv_type = ADV_TYPE_IND;
    params.own_addr_type = BLE_ADDR_TYPE_PUBLIC;
    params.channel_map = ADV_CHNL_ALL;
    params.adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY;
    return esp_ble_gap_start_advertising(&params) == ESP_OK;
}

/* Simple JSON string field extractor for BLE provisioning payload. */
static void extract_json_str(const char *json, const char *key, char *out, size_t cap) {
    out[0] = '\0';
    char pat[32];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(json, pat);
    if (!p) {
        return;
    }
    p = strchr(p + strlen(pat), ':');
    if (!p) {
        return;
    }
    while (*p == ':' || *p == ' ' || *p == '\t') {
        p++;
    }
    if (*p != '"') {
        return;
    }
    p++;
    size_t i = 0;
    while (*p && *p != '"' && i + 1 < cap) {
        if (*p == '\\' && *(p + 1)) {
            p++;
        }
        out[i++] = *p++;
    }
    out[i] = '\0';
}

static void handle_prov_write(const uint8_t *data, uint16_t len) {
    if (!data || len == 0) {
        return;
    }
    if (s_prov_rx_len + len >= sizeof(s_prov_rx_buf)) {
        s_prov_rx_len = 0;
    }
    memcpy(s_prov_rx_buf + s_prov_rx_len, data, len);
    s_prov_rx_len += len;
    s_prov_rx_buf[s_prov_rx_len] = '\0';

    if (!strchr(s_prov_rx_buf, '}')) {
        return;
    }
    char ssid[64] = {0};
    char pass[64] = {0};
    char mqtt_uri[96] = {0};
    char root[64] = {0};
    char name[32] = {0};
    extract_json_str(s_prov_rx_buf, "ssid", ssid, sizeof(ssid));
    extract_json_str(s_prov_rx_buf, "pass", pass, sizeof(pass));
    extract_json_str(s_prov_rx_buf, "mqtt_uri", mqtt_uri, sizeof(mqtt_uri));
    extract_json_str(s_prov_rx_buf, "root", root, sizeof(root));
    extract_json_str(s_prov_rx_buf, "name", name, sizeof(name));
    s_prov_rx_len = 0;

    if (ssid[0] != '\0' && s_prov_cb) {
        ESP_LOGI(TAG, "BLE prov rx: ssid=%s mqtt_uri=%s root=%s name=%s", ssid, mqtt_uri, root, name);
        s_prov_cb(ssid, pass, mqtt_uri, root, name);
    }
}

static void gap_event(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param) {
    switch (event) {
    case ESP_GAP_BLE_ADV_START_COMPLETE_EVT:
        s_adv_active = (param->adv_start_cmpl.status == ESP_BT_STATUS_SUCCESS);
        if (!s_adv_active) {
            ESP_LOGW(TAG, "adv start failed %d", param->adv_start_cmpl.status);
        }
        break;
    case ESP_GAP_BLE_ADV_STOP_COMPLETE_EVT:
        s_adv_active = false;
        break;
    case ESP_GAP_BLE_SEC_REQ_EVT:
        esp_ble_gap_security_rsp(param->ble_security.ble_req.bd_addr, true);
        break;
    case ESP_GAP_BLE_AUTH_CMPL_EVT: {
        if (s_prov_mode) {
            break;
        }
        int slot = find_peer_by_bda(param->ble_security.auth_cmpl.bd_addr);
        bool ok = param->ble_security.auth_cmpl.success;
        if (slot >= 0) {
            s_peers[slot].paired = ok;
            s_peers[slot].addr_type = param->ble_security.auth_cmpl.addr_type;
            if (ok) {
                /* Request 15ms connection interval after encryption (Apple Accessory Design Guidelines) */
                esp_ble_conn_update_params_t conn_params = {
                    .min_int = 0x0c, // 12 * 1.25ms = 15 ms
                    .max_int = 0x0c, // 15 ms
                    .latency = 0,
                    .timeout = 400,  // 400 * 10ms = 4000 ms
                };
                memcpy(conn_params.bda, param->ble_security.auth_cmpl.bd_addr, ESP_BD_ADDR_LEN);
                esp_ble_gap_update_conn_params(&conn_params);

                if (s_gattc_if != ESP_GATT_IF_NONE && s_peers[slot].name[0] == 0) {
                    /* Open GATT client over the existing link to read iPhone's 0x2A00 Device Name. */
                    esp_ble_gattc_open(s_gattc_if, s_peers[slot].bda, s_peers[slot].addr_type, true);
                }
            }
        }
        if (ok) {
            ESP_LOGI(TAG, "pairing complete (slot %d)", slot);
        } else {
            ESP_LOGW(TAG, "pairing failed 0x%x", param->ble_security.auth_cmpl.fail_reason);
        }
        break;
    }
    default:
        break;
    }
}

/* GATT Client callback: reads GAP Device Name (0x2A00) so XuPlay can auto-match AirPlay phone_name. */
static void gattc_event(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if, esp_ble_gattc_cb_param_t *param) {
    switch (event) {
    case ESP_GATTC_REG_EVT:
        if (param->reg.status == ESP_GATT_OK) {
            s_gattc_if = gattc_if;
        }
        break;
    case ESP_GATTC_OPEN_EVT: {
        if (param->open.status != ESP_GATT_OK) {
            break;
        }
        esp_bt_uuid_t gap_uuid = {
            .len = ESP_UUID_LEN_16,
            .uuid = {.uuid16 = 0x1800},
        };
        esp_ble_gattc_search_service(gattc_if, param->open.conn_id, &gap_uuid);
        break;
    }
    case ESP_GATTC_SEARCH_RES_EVT: {
        for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
            if (s_peers[i].connected && s_peers[i].conn_id == param->search_res.conn_id) {
                s_peers[i].gap_start_hdl = param->search_res.start_handle;
                s_peers[i].gap_end_hdl = param->search_res.end_handle;
            }
        }
        break;
    }
    case ESP_GATTC_SEARCH_CMPL_EVT: {
        for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
            if (s_peers[i].connected && s_peers[i].conn_id == param->search_cmpl.conn_id &&
                s_peers[i].gap_end_hdl > 0) {
                uint16_t count = 1;
                esp_gattc_char_elem_t elem;
                esp_bt_uuid_t name_uuid = {
                    .len = ESP_UUID_LEN_16,
                    .uuid = {.uuid16 = ESP_GATT_UUID_GAP_DEVICE_NAME},
                };
                if (esp_ble_gattc_get_char_by_uuid(gattc_if, param->search_cmpl.conn_id,
                                                   s_peers[i].gap_start_hdl, s_peers[i].gap_end_hdl,
                                                   name_uuid, &elem, &count) == ESP_OK &&
                    count > 0) {
                    esp_ble_gattc_read_char(gattc_if, param->search_cmpl.conn_id,
                                            elem.char_handle, ESP_GATT_AUTH_REQ_NONE);
                }
            }
        }
        break;
    }
    case ESP_GATTC_READ_CHAR_EVT: {
        if (param->read.status == ESP_GATT_OK && param->read.value_len > 0) {
            for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
                if (s_peers[i].connected && s_peers[i].conn_id == param->read.conn_id) {
                    size_t n = param->read.value_len;
                    if (n >= sizeof(s_peers[i].name)) {
                        n = sizeof(s_peers[i].name) - 1;
                    }
                    memcpy(s_peers[i].name, param->read.value, n);
                    s_peers[i].name[n] = '\0';
                    ESP_LOGI(TAG, "slot %d phone name: %s (%s)", i, s_peers[i].name, s_peers[i].bda_str);
                }
            }
        }
        /* The GATT client channel shares the ACL link with the HID service on
         * classic Bluetooth, so it must stay open: closing it tears down the
         * phone's own link (reason 0x16). */
        break;
    }
    default:
        break;
    }
}

/* Intercepts GATTS events for both Stage 1 (Provisioning 0xFF00) and Stage 2 (Multi-Peer HID 0x1812). */
static void gatts_event(esp_gatts_cb_event_t event, esp_gatt_if_t gatts_if, esp_ble_gatts_cb_param_t *param) {
    /* Route Stage 1 BLE Provisioning GATT events first. */
    if (event == ESP_GATTS_REG_EVT && param->reg.app_id == PROV_APP_ID) {
        if (param->reg.status == ESP_GATT_OK) {
            s_prov_gatts_if = gatts_if;
            esp_ble_gatts_create_attr_tab(s_prov_gatt_db, gatts_if, PROV_IDX_NB, 0);
        }
        return;
    }
    if (s_prov_gatts_if != ESP_GATT_IF_NONE && gatts_if == s_prov_gatts_if) {
        switch (event) {
        case ESP_GATTS_CREAT_ATTR_TAB_EVT:
            if (param->add_attr_tab.status == ESP_GATT_OK && param->add_attr_tab.num_handle == PROV_IDX_NB) {
                memcpy(s_prov_handles, param->add_attr_tab.handles, sizeof(s_prov_handles));
                esp_ble_gatts_start_service(s_prov_handles[PROV_IDX_SVC]);
                ESP_LOGI(TAG, "BLE Provisioning GATT service started (%s)", s_prov_name);
                start_prov_advertising();
            }
            break;
        case ESP_GATTS_CONNECT_EVT:
            s_prov_connected = true;
            s_prov_conn_id = param->connect.conn_id;
            s_prov_rx_len = 0;
            ESP_LOGI(TAG, "BLE Provisioning client connected (conn_id=%u)", s_prov_conn_id);
            break;
        case ESP_GATTS_DISCONNECT_EVT:
            s_prov_connected = false;
            if (s_prov_mode) {
                start_prov_advertising();
            }
            break;
        case ESP_GATTS_WRITE_EVT:
            if (param->write.handle == s_prov_handles[PROV_IDX_CFG_VAL]) {
                handle_prov_write(param->write.value, param->write.len);
            }
            break;
        default:
            break;
        }
        return;
    }

    if (s_prov_mode) {
        return;
    }

    esp_hidd_gatts_event_handler(event, gatts_if, param);

    switch (event) {
    case ESP_GATTS_CREAT_ATTR_TAB_EVT:
        /* HID service table has 11 base attrs + mouse(4) + kbd(4) + consumer(4) = 23 handles. */
        if (param->add_attr_tab.status == ESP_GATT_OK && param->add_attr_tab.num_handle >= 23) {
            s_hid_gatts_if = gatts_if;
            s_mouse_handle = param->add_attr_tab.handles[12];
            s_keyboard_handle = param->add_attr_tab.handles[16];
            s_consumer_handle = param->add_attr_tab.handles[20];
            ESP_LOGI(TAG, "HID handles ready (num=%u): mouse=%u kbd=%u consumer=%u",
                     param->add_attr_tab.num_handle, s_mouse_handle, s_keyboard_handle, s_consumer_handle);
            for (int h = 0; h < param->add_attr_tab.num_handle; h++) {
                ESP_LOGI(TAG, "  handle[%d] = %u", h, param->add_attr_tab.handles[h]);
            }
        }
        break;
    case ESP_GATTS_WRITE_EVT: {
        if (s_hid_gatts_if != ESP_GATT_IF_NONE && gatts_if == s_hid_gatts_if) {
            int slot = -1;
            for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
                if (s_peers[i].connected && s_peers[i].conn_id == param->write.conn_id) {
                    slot = i;
                    break;
                }
            }
            uint16_t val = (param->write.len >= 2) ? ((uint16_t)param->write.value[0] | ((uint16_t)param->write.value[1] << 8)) :
                           (param->write.len == 1 ? param->write.value[0] : 0);
            ESP_LOGI(TAG, "GATTS WRITE: slot=%d conn=%u hdl=%u len=%u val=0x%04x",
                     slot, param->write.conn_id, param->write.handle, param->write.len, val);
            if (slot >= 0) {
                if (param->write.handle == s_mouse_handle + 1) {
                    s_peers[slot].ccc_mouse = val;
                    ESP_LOGI(TAG, "slot %d (%s) CCC mouse -> 0x%04x", slot, s_peers[slot].bda_str, val);
                } else if (param->write.handle == s_keyboard_handle + 1) {
                    s_peers[slot].ccc_keyboard = val;
                    ESP_LOGI(TAG, "slot %d (%s) CCC kbd -> 0x%04x", slot, s_peers[slot].bda_str, val);
                } else if (param->write.handle == s_consumer_handle + 1) {
                    s_peers[slot].ccc_consumer = val;
                    ESP_LOGI(TAG, "slot %d (%s) CCC consumer -> 0x%04x", slot, s_peers[slot].bda_str, val);
                }
            }
        }
        break;
    }
    case ESP_GATTS_CONNECT_EVT: {
        if (s_hid_gatts_if != ESP_GATT_IF_NONE && gatts_if != s_hid_gatts_if) {
            break;
        }
        int slot = alloc_peer_slot(param->connect.remote_bda);
        if (slot >= 0) {
            s_peers[slot].has_bda = true;
            s_peers[slot].connected = true;
            s_peers[slot].conn_id = param->connect.conn_id;
            memcpy(s_peers[slot].bda, param->connect.remote_bda, ESP_BD_ADDR_LEN);
            format_bda(param->connect.remote_bda, s_peers[slot].bda_str);
            s_peers[slot].mouse_down = false;
            s_peers[slot].key_down = false;
            s_peers[slot].consumer_down = false;
            s_peers[slot].homed = false;
            s_peers[slot].cur_px = 0;
            s_peers[slot].cur_py = 0;
            esp_ble_set_encryption(param->connect.remote_bda, ESP_BLE_SEC_ENCRYPT_NO_MITM);

            /* Request 15ms connection interval as recommended by Apple Accessory Design Guidelines for HID */
            esp_ble_conn_update_params_t conn_params = {
                .min_int = 0x0c, // 12 * 1.25ms = 15 ms
                .max_int = 0x0c, // 15 ms
                .latency = 0,
                .timeout = 400,  // 400 * 10ms = 4000 ms
            };
            memcpy(conn_params.bda, param->connect.remote_bda, ESP_BD_ADDR_LEN);
            esp_ble_gap_update_conn_params(&conn_params);

            ESP_LOGI(TAG, "peer connected: slot=%d conn_id=%u bda=%s (active=%d/%d)",
                     slot, param->connect.conn_id, s_peers[slot].bda_str,
                     hid_abs_connected_count(), HID_ABS_MAX_PEERS);
        }
        s_adv_active = false;
        if (s_want_adv && hid_abs_connected_count() < HID_ABS_MAX_PEERS) {
            start_advertising();
        }
        break;
    }
    case ESP_GATTS_DISCONNECT_EVT: {
        if (s_hid_gatts_if != ESP_GATT_IF_NONE && gatts_if != s_hid_gatts_if) {
            break;
        }
        int slot = find_peer_by_bda(param->disconnect.remote_bda);
        if (slot >= 0) {
            s_peers[slot].connected = false;
            s_peers[slot].mouse_down = false;
            s_peers[slot].key_down = false;
            s_peers[slot].consumer_down = false;
            s_peers[slot].homed = false;
            s_peers[slot].cur_px = 0;
            s_peers[slot].cur_py = 0;
            ESP_LOGI(TAG, "peer disconnected: slot=%d bda=%s reason=0x%x (active=%d/%d)",
                     slot, s_peers[slot].bda_str, param->disconnect.reason,
                     hid_abs_connected_count(), HID_ABS_MAX_PEERS);
        }
        if (s_want_adv && hid_abs_connected_count() < HID_ABS_MAX_PEERS) {
            start_advertising();
        }
        break;
    }
    default:
        break;
    }
}

static void hidd_event(void *handler_args, esp_event_base_t base, int32_t id, void *event_data) {
    (void)handler_args;
    (void)base;
    (void)event_data;
    switch (id) {
    case ESP_HIDD_START_EVENT:
        s_protocol_ok = true;
        ESP_LOGI(TAG, "HID started; advertising %s (up to %d phones)", s_name, HID_ABS_MAX_PEERS);
        if (s_want_adv) {
            start_advertising();
        }
        break;
    case ESP_HIDD_STOP_EVENT:
        s_protocol_ok = false;
        break;
    default:
        break;
    }
}

static bool ensure_bt_stack(void) {
    if (s_bt_stack_ready) {
        return true;
    }
    ESP_ERROR_CHECK(esp_bt_controller_mem_release(ESP_BT_MODE_CLASSIC_BT));
    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    if (esp_bt_controller_init(&bt_cfg) != ESP_OK) {
        return false;
    }
    if (esp_bt_controller_enable(ESP_BT_MODE_BLE) != ESP_OK) {
        return false;
    }
    if (esp_bluedroid_init() != ESP_OK || esp_bluedroid_enable() != ESP_OK) {
        return false;
    }
    if (esp_ble_gap_register_callback(gap_event) != ESP_OK) {
        return false;
    }
    /* Headless: bond with "Just Works" so phones accept the HID without a passkey. */
    esp_ble_auth_req_t auth_req = ESP_LE_AUTH_REQ_SC_BOND;
    esp_ble_io_cap_t iocap = ESP_IO_CAP_NONE;
    uint8_t init_key = ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK;
    uint8_t rsp_key = ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK;
    uint8_t key_size = 16;
    esp_ble_gap_set_security_param(ESP_BLE_SM_AUTHEN_REQ_MODE, &auth_req, 1);
    esp_ble_gap_set_security_param(ESP_BLE_SM_IOCAP_MODE, &iocap, 1);
    esp_ble_gap_set_security_param(ESP_BLE_SM_SET_INIT_KEY, &init_key, 1);
    esp_ble_gap_set_security_param(ESP_BLE_SM_SET_RSP_KEY, &rsp_key, 1);
    esp_ble_gap_set_security_param(ESP_BLE_SM_MAX_KEY_SIZE, &key_size, 1);

    if (esp_ble_gattc_register_callback(gattc_event) == ESP_OK) {
        esp_ble_gattc_app_register(0);
    }
    if (esp_ble_gatts_register_callback(gatts_event) != ESP_OK) {
        return false;
    }
    s_bt_stack_ready = true;
    return true;
}

bool hid_prov_start(const char *setup_name, hid_prov_cb_t cb) {
    if (!ensure_bt_stack()) {
        return false;
    }
    if (setup_name && setup_name[0]) {
        strncpy(s_prov_name, setup_name, sizeof(s_prov_name) - 1);
    }
    s_prov_cb = cb;
    s_prov_mode = true;
    snprintf(s_prov_status, sizeof(s_prov_status), "{\"state\":\"provisioning\",\"dev\":\"%s\"}", s_prov_name);
    if (s_prov_gatts_if == ESP_GATT_IF_NONE) {
        return esp_ble_gatts_app_register(PROV_APP_ID) == ESP_OK;
    }
    return start_prov_advertising();
}

void hid_prov_notify(const char *json_status) {
    if (!json_status) {
        return;
    }
    strncpy(s_prov_status, json_status, sizeof(s_prov_status) - 1);
    s_prov_status[sizeof(s_prov_status) - 1] = '\0';
    if (s_prov_gatts_if != ESP_GATT_IF_NONE && s_prov_handles[PROV_IDX_STS_VAL] != 0) {
        esp_ble_gatts_set_attr_value(s_prov_handles[PROV_IDX_STS_VAL], strlen(s_prov_status), (const uint8_t *)s_prov_status);
        if (s_prov_connected) {
            esp_ble_gatts_send_indicate(s_prov_gatts_if, s_prov_conn_id, s_prov_handles[PROV_IDX_STS_VAL],
                                        strlen(s_prov_status), (uint8_t *)s_prov_status, false);
        }
    }
}

void hid_prov_stop(void) {
    if (!s_prov_mode) {
        return;
    }
    s_prov_mode = false;
    esp_ble_gap_stop_advertising();
    if (s_prov_gatts_if != ESP_GATT_IF_NONE) {
        if (s_prov_connected) {
            esp_ble_gatts_close(s_prov_gatts_if, s_prov_conn_id);
            s_prov_connected = false;
        }
        if (s_prov_handles[PROV_IDX_SVC] != 0) {
            esp_ble_gatts_stop_service(s_prov_handles[PROV_IDX_SVC]);
            esp_ble_gatts_delete_service(s_prov_handles[PROV_IDX_SVC]);
        }
        esp_ble_gatts_app_unregister(s_prov_gatts_if);
        s_prov_gatts_if = ESP_GATT_IF_NONE;
        memset(s_prov_handles, 0, sizeof(s_prov_handles));
    }
    ESP_LOGI(TAG, "BLE Provisioning stopped; ready to switch to BLE HID mode");
}

bool hid_prov_active(void) {
    return s_prov_mode;
}

bool hid_abs_start(const char *device_name) {
    if (s_prov_mode) {
        hid_prov_stop();
    }
    memset(s_peers, 0, sizeof(s_peers));
    if (device_name && device_name[0]) {
        strncpy(s_name, device_name, sizeof(s_name) - 1);
    }
    if (!ensure_bt_stack()) {
        return false;
    }
    static esp_hid_raw_report_map_t report_maps[] = {
        {.data = s_report_map, .len = sizeof(s_report_map)},
    };
    esp_hid_device_config_t config = {
        .vendor_id = 0x18D1,
        .product_id = 0x5025,
        .version = 0x0100,
        .device_name = s_name,
        .manufacturer_name = "XuLang",
        .serial_number = "xu-idf-cyd",
        .report_maps = report_maps,
        .report_maps_len = 1,
    };
    if (esp_hidd_dev_init(&config, ESP_HID_TRANSPORT_BLE, hidd_event, &s_hid) != ESP_OK) {
        return false;
    }
    return true;
}

void hid_abs_stop(void) {
    if (s_hid) {
        esp_hidd_dev_deinit(s_hid);
        s_hid = NULL;
    }
    memset(s_peers, 0, sizeof(s_peers));
    s_protocol_ok = false;
}

int hid_abs_connected_count(void) {
    int n = 0;
    for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
        if (s_peers[i].connected) {
            n++;
        }
    }
    return n;
}

bool hid_abs_peer_connected(int slot) {
    return slot >= 0 && slot < HID_ABS_MAX_PEERS && s_peers[slot].connected;
}

bool hid_abs_peer_ready(int slot) {
    return hid_abs_peer_connected(slot) && s_protocol_ok;
}

const char *hid_abs_peer_bda(int slot) {
    if (slot < 0 || slot >= HID_ABS_MAX_PEERS || !s_peers[slot].has_bda) {
        return "";
    }
    return s_peers[slot].bda_str;
}

const char *hid_abs_peer_name(int slot) {
    if (slot < 0 || slot >= HID_ABS_MAX_PEERS || !s_peers[slot].has_bda) {
        return "";
    }
    return s_peers[slot].name;
}

bool hid_abs_connected(void) {
    return hid_abs_connected_count() > 0;
}

bool hid_abs_encrypted_ready(void) {
    return hid_abs_connected() && s_protocol_ok;
}

bool hid_abs_mouse_subscribed(void) {
    return hid_abs_connected();
}

bool hid_abs_keyboard_subscribed(void) {
    return hid_abs_connected();
}

bool hid_abs_consumer_subscribed(void) {
    return hid_abs_connected();
}

bool hid_abs_advertising(void) {
    return s_protocol_ok && s_want_adv && hid_abs_connected_count() < HID_ABS_MAX_PEERS;
}

bool hid_abs_paired(void) {
    for (int i = 0; i < HID_ABS_MAX_PEERS; i++) {
        if (s_peers[i].connected && s_peers[i].paired) {
            return true;
        }
    }
    return false;
}

void hid_abs_last_mouse(uint16_t *x, uint16_t *y, bool *down) {
    *x = s_last_x;
    *y = s_last_y;
    *down = s_mouse_down;
}

bool hid_abs_set_advertising(bool enable) {
    s_want_adv = enable;
    if (!s_protocol_ok) {
        return true;
    }
    if (enable) {
        return start_advertising();
    }
    return esp_ble_gap_stop_advertising() == ESP_OK;
}

bool hid_abs_disconnect_to(int target) {
    int slot = resolve_peer_slot(target);
    if (slot < 0) {
        return false;
    }
    if (s_hid_gatts_if != ESP_GATT_IF_NONE) {
        return esp_ble_gatts_close(s_hid_gatts_if, s_peers[slot].conn_id) == ESP_OK;
    }
    return false;
}

bool hid_abs_disconnect(void) {
    return hid_abs_disconnect_to(-1);
}

static uint16_t report_handle_for(uint8_t report_id) {
    switch (report_id) {
    case HID_RPT_MOUSE: return s_mouse_handle;
    case HID_RPT_KEYBOARD: return s_keyboard_handle;
    case HID_RPT_CONSUMER: return s_consumer_handle;
    default: return 0;
    }
}

static bool send_input_to(int slot, uint8_t report_id, const uint8_t *data, size_t len) {
    if (slot < 0 || slot >= HID_ABS_MAX_PEERS || !s_peers[slot].connected) {
        return false;
    }
    uint16_t handle = report_handle_for(report_id);
    if (s_hid_gatts_if != ESP_GATT_IF_NONE && handle != 0) {
        esp_err_t err = ESP_FAIL;
        for (int retry = 0; retry < 10; retry++) {
            err = esp_ble_gatts_send_indicate(s_hid_gatts_if, s_peers[slot].conn_id,
                                              handle, len, (uint8_t *)data, false);
            if (err == ESP_OK) {
                return true;
            }
            vTaskDelay(pdMS_TO_TICKS(20));
        }
        ESP_LOGW(TAG, "send_indicate timeout: slot=%d conn=%u hdl=%u len=%u res=%d",
                 slot, s_peers[slot].conn_id, handle, (unsigned)len, err);
        return false;
    }
    if (!s_hid) {
        return false;
    }
    esp_err_t err = esp_hidd_dev_input_set(s_hid, 0, report_id, (uint8_t *)data, len);
    return err == ESP_OK;
}

static bool send_mouse_rel_to(int slot, uint8_t buttons, int8_t dx, int8_t dy, int8_t wheel) {
    if (slot < 0 || slot >= HID_ABS_MAX_PEERS || !s_peers[slot].connected) {
        return false;
    }
    uint8_t rpt[4] = {buttons, (uint8_t)dx, (uint8_t)dy, (uint8_t)wheel};
    return send_input_to(slot, HID_RPT_MOUSE, rpt, 4);
}

static void home_cursor_to(int slot) {
    if (slot < 0 || slot >= HID_ABS_MAX_PEERS || !s_peers[slot].connected) {
        return;
    }
    ESP_LOGI(TAG, "homing cursor slot %d to (0,0)", slot);
    /* 6 packets of (-80, -80) with 20ms delay = -480 counts.
     * Guarantees clamping to (0,0) from any position on screen without GATT buffer overflow. */
    for (int i = 0; i < 6; i++) {
        send_mouse_rel_to(slot, 0, -80, -80, 0);
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    vTaskDelay(pdMS_TO_TICKS(25));
    /* Tiny nudge (+2, +2) to release iOS AssistiveTouch edge-lock/docking */
    send_mouse_rel_to(slot, 0, 2, 2, 0);
    vTaskDelay(pdMS_TO_TICKS(15));
    s_peers[slot].cur_px = 2;
    s_peers[slot].cur_py = 2;
    s_peers[slot].homed = true;
}

static void calc_calibrated_bounds(int w, int h, int32_t *out_w, int32_t *out_h) {
    if (w <= 0 || h <= 0) {
        w = 1080;
        h = 1920;
    }
    /* Dynamic screen bounds calibrated directly from AirPlay video resolution (w, h):
     * AssistiveTouch step-24 physical sensitivity:
     * - Horizontal: max_w = (w * 5) / 24   (iPhone 13 mini 888 -> 185, iPhone 8 1080 -> 225)
     * - Vertical:   max_h = (h * 39) / 128  (1920 portrait lines -> 585)
     * Adapts dynamically to any AirPlay stream resolution (w, h) without hardcoded device IDs. */
    int32_t max_w = ((int32_t)w * 5) / 24;
    int32_t max_h = ((int32_t)h * 39) / 128;
    if (max_w < 50) max_w = 50;
    if (max_h < 150) max_h = 150;
    *out_w = max_w;
    *out_h = max_h;
}

bool hid_abs_set_screen_size(int target, int w, int h) {
    int slot = resolve_peer_slot(target);
    if (slot < 0 || w <= 0 || h <= 0) {
        return false;
    }
    s_peers[slot].screen_w = w;
    s_peers[slot].screen_h = h;
    int32_t max_w = 0, max_h = 0;
    calc_calibrated_bounds(w, h, &max_w, &max_h);
    s_peers[slot].max_w = max_w;
    s_peers[slot].max_h = max_h;
    ESP_LOGI(TAG, "slot %d screen size set to %dx%d (calibrated max_w=%d, max_h=%d)",
             slot, w, h, (int)max_w, (int)max_h);
    return true;
}

bool hid_abs_send_mouse_to(int target, const uint8_t report[5]) {
    if (!report) {
        return false;
    }
    int slot = resolve_peer_slot(target);
    if (slot < 0) {
        return false;
    }
    uint8_t btn = report[0] & 7;
    uint16_t x = (uint16_t)report[1] | ((uint16_t)report[2] << 8);
    uint16_t y = (uint16_t)report[3] | ((uint16_t)report[4] << 8);
    if (x > HID_MOUSE_ABS_MAX || y > HID_MOUSE_ABS_MAX) {
        return false;
    }

    /* Dynamic screen points calibration based on AirPlay video stream dimensions */
    int32_t max_w = s_peers[slot].max_w;
    int32_t max_h = s_peers[slot].max_h;
    if (max_w <= 0 || max_h <= 0) {
        int32_t sw = s_peers[slot].screen_w;
        int32_t sh = s_peers[slot].screen_h;
        calc_calibrated_bounds(sw, sh, &max_w, &max_h);
        s_peers[slot].max_w = max_w;
        s_peers[slot].max_h = max_h;
    }

    int32_t target_px = ((int32_t)x * max_w) / 32767;
    int32_t target_py = ((int32_t)y * max_h) / 32767;

    uint32_t now = (uint32_t)xTaskGetTickCount();
    /* Re-home if idle > 1500ms to eliminate accumulated drift and recover from external touches */
    if (s_peers[slot].homed && (now - s_peers[slot].last_act_tick > pdMS_TO_TICKS(1500))) {
        s_peers[slot].homed = false;
    }
    s_peers[slot].last_act_tick = now;

    ESP_LOGI(TAG, "mouse slot=%d btn=%d in=(%u,%u) target=(%d,%d) cur=(%d,%d) homed=%d",
             slot, btn, x, y, (int)target_px, (int)target_py, (int)s_peers[slot].cur_px, (int)s_peers[slot].cur_py, s_peers[slot].homed);

    /* Home cursor to (0,0) upon initial connection, idle expiration, explicit (0,0),
     * or at the start of any new discrete click to ensure 0 cumulative drift. */
    bool starting_new_press = (btn != 0 && !s_peers[slot].mouse_down);
    if (!s_peers[slot].homed || starting_new_press || (x == 0 && y == 0 && btn == 0)) {
        home_cursor_to(slot);
        if (x == 0 && y == 0 && btn == 0) {
            s_last_x = 0;
            s_last_y = 0;
            return true;
        }
    }

    /* Move incrementally from current cursor to target coordinate.
     * Step size 24 with 20ms pacing stays strictly linear and eliminates ballistic pointer acceleration. */
    int32_t d_px = target_px - s_peers[slot].cur_px;
    int32_t d_py = target_py - s_peers[slot].cur_py;
    int steps_sent = 0;

    while (d_px != 0 || d_py != 0) {
        int8_t step_x = (d_px > 24) ? 24 : ((d_px < -24) ? -24 : (int8_t)d_px);
        int8_t step_y = (d_py > 24) ? 24 : ((d_py < -24) ? -24 : (int8_t)d_py);

        bool ok = send_mouse_rel_to(slot, s_peers[slot].mouse_down ? btn : 0, step_x, step_y, 0);
        if (!ok) {
            ESP_LOGW(TAG, "send_mouse_rel_to fail slot=%d dx=%d dy=%d", slot, step_x, step_y);
            vTaskDelay(pdMS_TO_TICKS(15));
            continue;
        }
        d_px -= step_x;
        d_py -= step_y;
        s_peers[slot].cur_px += step_x;
        s_peers[slot].cur_py += step_y;
        steps_sent++;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    ESP_LOGI(TAG, "mouse moved: steps=%d cur=(%d,%d) target=(%d,%d)",
             steps_sent, (int)s_peers[slot].cur_px, (int)s_peers[slot].cur_py, (int)target_px, (int)target_py);

    /* Handle button down / up transitions with proper debouncing for AssistiveTouch */
    if (btn != 0 && !s_peers[slot].mouse_down) {
        send_mouse_rel_to(slot, btn, 0, 0, 0);
        s_peers[slot].last_down_tick = (uint32_t)xTaskGetTickCount();
        s_peers[slot].mouse_down = true;
    } else if (btn == 0 && s_peers[slot].mouse_down) {
        uint32_t now = (uint32_t)xTaskGetTickCount();
        uint32_t elapsed_ticks = now - s_peers[slot].last_down_tick;
        if (elapsed_ticks < 10) {
            vTaskDelay(10 - elapsed_ticks);
        }
        send_mouse_rel_to(slot, 0, 0, 0, 0);
        s_peers[slot].mouse_down = false;
    }

    s_peers[slot].last_x = x;
    s_peers[slot].last_y = y;
    s_last_x = x;
    s_last_y = y;
    s_mouse_down = (btn != 0);
    return true;
}

bool hid_abs_send_mouse(const uint8_t report[5]) {
    return hid_abs_send_mouse_to(-1, report);
}

bool hid_abs_send_keyboard_to(int target, const uint8_t report[8]) {
    if (!report || report[1] != 0) {
        return false;
    }
    int slot = resolve_peer_slot(target);
    if (slot < 0) {
        return false;
    }
    uint8_t bits = 0;
    for (int i = 0; i < 8; i++) {
        bits |= report[i];
    }
    s_peers[slot].key_down = bits != 0;
    return send_input_to(slot, HID_RPT_KEYBOARD, report, 8);
}

bool hid_abs_send_keyboard(const uint8_t report[8]) {
    return hid_abs_send_keyboard_to(-1, report);
}

bool hid_abs_send_consumer_to(int target, uint8_t mask) {
    if (mask > 31) {
        return false;
    }
    int slot = resolve_peer_slot(target);
    if (slot < 0) {
        return false;
    }
    s_peers[slot].consumer_down = mask != 0;
    return send_input_to(slot, HID_RPT_CONSUMER, &mask, 1);
}

bool hid_abs_send_consumer(uint8_t mask) {
    return hid_abs_send_consumer_to(-1, mask);
}

bool hid_abs_release_all_to(int target) {
    bool ok = true;
    int start = (target >= 0 && target < HID_ABS_MAX_PEERS) ? target : 0;
    int end = (target >= 0 && target < HID_ABS_MAX_PEERS) ? (target + 1) : HID_ABS_MAX_PEERS;
    for (int i = start; i < end; i++) {
        if (!s_peers[i].connected) {
            continue;
        }
        if (s_peers[i].mouse_down) {
            send_mouse_rel_to(i, 0, 0, 0, 0);
            s_peers[i].mouse_down = false;
        }
        if (s_peers[i].key_down) {
            uint8_t zero[8] = {0};
            ok = hid_abs_send_keyboard_to(i, zero) && ok;
            s_peers[i].key_down = false;
        }
        if (s_peers[i].consumer_down) {
            ok = hid_abs_send_consumer_to(i, 0) && ok;
            s_peers[i].consumer_down = false;
        }
    }
    return ok;
}

bool hid_abs_release_all(void) {
    return hid_abs_release_all_to(-1);
}
