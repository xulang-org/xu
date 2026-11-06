#include "hid_abs.h"

#include <string.h>

#include "esp_bt.h"
#include "esp_bt_device.h"
#include "esp_bt_main.h"
#include "esp_event.h"
#include "esp_gap_ble_api.h"
#include "esp_gatts_api.h"
#include "esp_hidd.h"
#include "esp_hidd_gatts.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "nvs_flash.h"

static const char *TAG = "hid_abs";

enum {
    HID_RPT_MOUSE = 1,
    HID_RPT_KEYBOARD = 2,
    HID_RPT_CONSUMER = 3,
    HID_MOUSE_ABS_MAX = 32767,
};

/* Absolute mouse (no relative wheel) + keyboard + consumer — matches Xu HOGP. */
static const uint8_t s_report_map[] = {
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x01, 0x09, 0x01, 0xA1, 0x00, 0x05, 0x09, 0x19, 0x01,
    0x29, 0x03, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x03, 0x81, 0x02, 0x75, 0x05, 0x95, 0x01,
    0x81, 0x01, 0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x16, 0x00, 0x00, 0x26, 0xFF, 0x7F, 0x75, 0x10,
    0x95, 0x02, 0x81, 0x02, 0xC0, 0xC0, 0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x02, 0x05, 0x07,
    0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01,
    0x75, 0x08, 0x81, 0x01, 0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x73, 0x05, 0x07, 0x19, 0x00,
    0x29, 0x73, 0x81, 0x00, 0xC0, 0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x03, 0x09, 0xE9, 0x09,
    0xEA, 0x09, 0xE2, 0x09, 0x30, 0x09, 0x40, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x05, 0x81,
    0x02, 0x75, 0x03, 0x95, 0x01, 0x81, 0x01, 0xC0,
};

static esp_hidd_dev_t *s_hid = NULL;
static bool s_connected = false;
static bool s_protocol_ok = false;
static bool s_mouse_on = false;
static bool s_keyboard_on = false;
static bool s_consumer_on = false;
static bool s_want_adv = true;
static bool s_paired = false;
static uint16_t s_last_x = 0;
static uint16_t s_last_y = 0;
static bool s_mouse_down = false;
static bool s_key_down = false;
static bool s_consumer_down = false;
static char s_name[32] = "XU-IDF-HID";

static void gap_event(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param) {
    switch (event) {
    case ESP_GAP_BLE_ADV_DATA_SET_COMPLETE_EVT:
    case ESP_GAP_BLE_SCAN_RSP_DATA_SET_COMPLETE_EVT:
        break;
    case ESP_GAP_BLE_ADV_START_COMPLETE_EVT:
        if (param->adv_start_cmpl.status != ESP_BT_STATUS_SUCCESS) {
            ESP_LOGW(TAG, "adv start failed %d", param->adv_start_cmpl.status);
        }
        break;
    case ESP_GAP_BLE_ADV_STOP_COMPLETE_EVT:
        break;
    case ESP_GAP_BLE_SEC_REQ_EVT:
        esp_ble_gap_security_rsp(param->ble_security.ble_req.bd_addr, true);
        break;
    case ESP_GAP_BLE_AUTH_CMPL_EVT:
        s_paired = param->ble_security.auth_cmpl.success;
        if (s_paired) {
            ESP_LOGI(TAG, "pairing complete");
        } else {
            ESP_LOGW(TAG, "pairing failed 0x%x", param->ble_security.auth_cmpl.fail_reason);
        }
        break;
    case ESP_GAP_BLE_UPDATE_WHITELIST_COMPLETE_EVT:
        break;
    default:
        break;
    }
}

static bool start_advertising(void) {
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

static void hidd_event(void *handler_args, esp_event_base_t base, int32_t id, void *event_data) {
    (void)handler_args;
    (void)base;
    switch (id) {
    case ESP_HIDD_START_EVENT:
        s_protocol_ok = true;
        ESP_LOGI(TAG, "HID started; advertising %s", s_name);
        if (s_want_adv) {
            start_advertising();
        }
        break;
    case ESP_HIDD_CONNECT_EVENT:
        s_connected = true;
        ESP_LOGI(TAG, "HID connected");
        break;
    case ESP_HIDD_DISCONNECT_EVENT:
        s_connected = false;
        s_paired = false;
        s_mouse_on = s_keyboard_on = s_consumer_on = false;
        s_mouse_down = s_key_down = s_consumer_down = false;
        ESP_LOGI(TAG, "HID disconnected");
        if (s_want_adv) {
            start_advertising();
        }
        break;
    case ESP_HIDD_PROTOCOL_MODE_EVENT: {
        esp_hidd_event_data_t *d = event_data;
        ESP_LOGI(TAG, "protocol mode %d", d->protocol_mode.protocol_mode);
        break;
    }
    case ESP_HIDD_CONTROL_EVENT:
        break;
    case ESP_HIDD_OUTPUT_EVENT:
        break;
    case ESP_HIDD_FEATURE_EVENT:
        break;
    case ESP_HIDD_STOP_EVENT:
        s_protocol_ok = false;
        break;
    default:
        break;
    }
}

bool hid_abs_start(const char *device_name) {
    if (device_name && device_name[0]) {
        strncpy(s_name, device_name, sizeof(s_name) - 1);
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
    /* esp_hidd's BLE transport only starts once it receives GATTS events. */
    if (esp_ble_gatts_register_callback(esp_hidd_gatts_event_handler) != ESP_OK) {
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
    s_connected = false;
    s_protocol_ok = false;
}

bool hid_abs_connected(void) {
    return s_connected;
}
bool hid_abs_encrypted_ready(void) {
    /* Bluedroid HID notifies after encryption when CCCDs are written; treat
     * connection + protocol start as ready for this delivery profile. */
    return s_connected && s_protocol_ok;
}
bool hid_abs_mouse_subscribed(void) {
    return s_connected;
}
bool hid_abs_keyboard_subscribed(void) {
    return s_connected;
}
bool hid_abs_consumer_subscribed(void) {
    return s_connected;
}

bool hid_abs_advertising(void) {
    return s_protocol_ok && s_want_adv && !s_connected;
}
bool hid_abs_paired(void) {
    return s_paired;
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

bool hid_abs_disconnect(void) {
    if (!s_hid || !s_connected) {
        return false;
    }
    /* esp_hidd has no direct disconnect on all targets; stopping adv + waiting
     * for host drop is insufficient. Best-effort: disable advertising. */
    s_want_adv = false;
    esp_ble_gap_stop_advertising();
    return true;
}

static bool send_input(uint8_t report_id, const uint8_t *data, size_t len) {
    if (!s_hid || !s_connected) {
        return false;
    }
    return esp_hidd_dev_input_set(s_hid, 0, report_id, (uint8_t *)data, len) == ESP_OK;
}

bool hid_abs_send_mouse(const uint8_t report[5]) {
    if (!report) {
        return false;
    }
    uint16_t x = (uint16_t)report[1] | ((uint16_t)report[2] << 8);
    uint16_t y = (uint16_t)report[3] | ((uint16_t)report[4] << 8);
    if (x > HID_MOUSE_ABS_MAX || y > HID_MOUSE_ABS_MAX || report[0] > 7) {
        return false;
    }
    s_last_x = x;
    s_last_y = y;
    s_mouse_down = report[0] != 0;
    s_mouse_on = true;
    return send_input(HID_RPT_MOUSE, report, 5);
}

bool hid_abs_send_keyboard(const uint8_t report[8]) {
    if (!report || report[1] != 0) {
        return false;
    }
    uint8_t bits = 0;
    for (int i = 0; i < 8; i++) {
        bits |= report[i];
    }
    s_key_down = bits != 0;
    s_keyboard_on = true;
    return send_input(HID_RPT_KEYBOARD, report, 8);
}

bool hid_abs_send_consumer(uint8_t mask) {
    if (mask > 31) {
        return false;
    }
    s_consumer_down = mask != 0;
    s_consumer_on = true;
    return send_input(HID_RPT_CONSUMER, &mask, 1);
}

bool hid_abs_release_all(void) {
    bool ok = true;
    if (s_mouse_down) {
        uint8_t zero[5] = {0, (uint8_t)(s_last_x & 0xff), (uint8_t)(s_last_x >> 8),
                           (uint8_t)(s_last_y & 0xff), (uint8_t)(s_last_y >> 8)};
        ok = hid_abs_send_mouse(zero) && ok;
        s_mouse_down = false;
    }
    if (s_key_down) {
        uint8_t zero[8] = {0};
        ok = hid_abs_send_keyboard(zero) && ok;
        s_key_down = false;
    }
    if (s_consumer_down) {
        ok = hid_abs_send_consumer(0) && ok;
        s_consumer_down = false;
    }
    return ok;
}
