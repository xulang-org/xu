#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "hid_abs.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "status_lcd.h"
#include "xu_host.h"

static const char *TAG = "idf_cyd";
static EventGroupHandle_t s_wifi;
static const int WIFI_OK = BIT0;

static char s_ssid[64] = CONFIG_XU_WIFI_SSID;
static char s_pass[64] = CONFIG_XU_WIFI_PASSWORD;
static char s_mqtt_uri[96] = CONFIG_XU_MQTT_URI;
static char s_mqtt_root[64] = CONFIG_XU_MQTT_ROOT;
static char s_hid_name[32] = CONFIG_XU_HID_NAME;
static char s_last_ip[16] = "";
static bool s_wifi_started = false;

static void load_nvs_config(void) {
    nvs_handle_t h;
    if (nvs_open("xu_cfg", NVS_READONLY, &h) != ESP_OK) {
        return;
    }
    size_t len;
    len = sizeof(s_ssid);
    nvs_get_str(h, "ssid", s_ssid, &len);
    len = sizeof(s_pass);
    nvs_get_str(h, "pass", s_pass, &len);
    len = sizeof(s_mqtt_uri);
    nvs_get_str(h, "mqtt_uri", s_mqtt_uri, &len);
    len = sizeof(s_mqtt_root);
    nvs_get_str(h, "mqtt_root", s_mqtt_root, &len);
    len = sizeof(s_hid_name);
    nvs_get_str(h, "hid_name", s_hid_name, &len);
    nvs_close(h);
}

static void save_nvs_config(void) {
    nvs_handle_t h;
    if (nvs_open("xu_cfg", NVS_READWRITE, &h) != ESP_OK) {
        return;
    }
    nvs_set_str(h, "ssid", s_ssid);
    nvs_set_str(h, "pass", s_pass);
    nvs_set_str(h, "mqtt_uri", s_mqtt_uri);
    nvs_set_str(h, "mqtt_root", s_mqtt_root);
    nvs_set_str(h, "hid_name", s_hid_name);
    nvs_commit(h);
    nvs_close(h);
}

static void apply_wifi_credentials(void) {
    wifi_config_t wifi = {0};
    strncpy((char *)wifi.sta.ssid, s_ssid, sizeof(wifi.sta.ssid) - 1);
    strncpy((char *)wifi.sta.password, s_pass, sizeof(wifi.sta.password) - 1);
    wifi.sta.threshold.authmode = (s_pass[0] != '\0') ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    esp_wifi_set_config(WIFI_IF_STA, &wifi);
}

/* Callback invoked when Stage 1 BLE Provisioning receives Wi-Fi & MQTT credentials on 0xFF01. */
static void on_ble_provisioned(const char *ssid, const char *pass, const char *mqtt_uri,
                               const char *mqtt_root, const char *hid_name) {
    if (ssid && ssid[0]) {
        strncpy(s_ssid, ssid, sizeof(s_ssid) - 1);
    }
    if (pass) {
        strncpy(s_pass, pass, sizeof(s_pass) - 1);
    }
    if (mqtt_uri && mqtt_uri[0]) {
        strncpy(s_mqtt_uri, mqtt_uri, sizeof(s_mqtt_uri) - 1);
    }
    if (mqtt_root && mqtt_root[0]) {
        strncpy(s_mqtt_root, mqtt_root, sizeof(s_mqtt_root) - 1);
    }
    if (hid_name && hid_name[0]) {
        strncpy(s_hid_name, hid_name, sizeof(s_hid_name) - 1);
    }
    xu_host_set_runtime_config(s_mqtt_uri, s_mqtt_root, s_hid_name, s_ssid);

    char msg[128];
    snprintf(msg, sizeof(msg), "{\"state\":\"connecting\",\"ssid\":\"%s\"}", s_ssid);
    hid_prov_notify(msg);

    status_lcd_set_wifi(STATUS_WIFI_CONNECTING, NULL);
    if (s_wifi_started) {
        esp_wifi_disconnect();
        apply_wifi_credentials();
        esp_wifi_connect();
    }
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        if (s_ssid[0] != '\0') {
            esp_wifi_connect();
        }
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected; retry");
        status_lcd_set_wifi(STATUS_WIFI_CONNECTING, NULL);
        xEventGroupClearBits(s_wifi, WIFI_OK);
        if (s_ssid[0] != '\0') {
            esp_wifi_connect();
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        ESP_LOGI(TAG, "got ip " IPSTR, IP2STR(&event->ip_info.ip));
        snprintf(s_last_ip, sizeof(s_last_ip), IPSTR, IP2STR(&event->ip_info.ip));
        status_lcd_set_wifi(STATUS_WIFI_UP, s_last_ip);
        xEventGroupSetBits(s_wifi, WIFI_OK);
    }
}

static void wifi_init_sta(void) {
    s_wifi = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    if (s_ssid[0] != '\0') {
        apply_wifi_credentials();
    }
    ESP_ERROR_CHECK(esp_wifi_start());
    s_wifi_started = true;
}

void app_main(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    load_nvs_config();
    xu_host_set_runtime_config(s_mqtt_uri, s_mqtt_root, s_hid_name, s_ssid);

    ESP_LOGI(TAG, "Xu IDF CYD — Two-Stage BLE Provisioning -> BLE HID");
    if (!xu_host_init()) {
        ESP_LOGE(TAG, "Xu runtime init failed");
        return;
    }
    if (!status_lcd_start()) {
        ESP_LOGW(TAG, "status screen unavailable; continuing headless");
    }

    /* Check BOOT button (GPIO0) to allow forcing BLE Wi-Fi provisioning at boot. */
    gpio_reset_pin(GPIO_NUM_0);
    gpio_set_direction(GPIO_NUM_0, GPIO_MODE_INPUT);
    gpio_set_pull_mode(GPIO_NUM_0, GPIO_PULLUP_ONLY);
    bool force_prov = (gpio_get_level(GPIO_NUM_0) == 0);

    wifi_init_sta();

    bool wifi_ready = false;
    if (!force_prov && s_ssid[0] != '\0') {
        ESP_LOGI(TAG, "Connecting to Wi-Fi SSID '%s' (10s timeout before BLE Provisioning)...", s_ssid);
        EventBits_t bits = xEventGroupWaitBits(s_wifi, WIFI_OK, pdFALSE, pdTRUE, pdMS_TO_TICKS(10000));
        wifi_ready = (bits & WIFI_OK) != 0;
    }

    /* Stage 1: If Wi-Fi is not connected yet, enter BLE Provisioning Mode (do NOT start HID yet!). */
    if (!wifi_ready) {
        uint8_t mac[6] = {0};
        esp_read_mac(mac, ESP_MAC_BT);
        char setup_name[32];
        snprintf(setup_name, sizeof(setup_name), "XuPlay-Setup-%02X%02X", mac[4], mac[5]);
        ESP_LOGW(TAG, "Wi-Fi not connected; starting Stage 1 BLE Provisioning as '%s' (Service 0xFF00)", setup_name);
        status_lcd_set_wifi(STATUS_WIFI_FAILED, setup_name);
        hid_prov_start(setup_name, on_ble_provisioned);

        /* Wait until Wi-Fi connects (via BLE-provisioned credentials or router recovery). */
        xEventGroupWaitBits(s_wifi, WIFI_OK, pdFALSE, pdTRUE, portMAX_DELAY);

        char ok_msg[128];
        snprintf(ok_msg, sizeof(ok_msg), "{\"state\":\"connected\",\"ip\":\"%s\",\"root\":\"%s\"}", s_last_ip, s_mqtt_root);
        hid_prov_notify(ok_msg);
        vTaskDelay(pdMS_TO_TICKS(300));
        hid_prov_stop();
    }

    /* Persist working Wi-Fi & MQTT configuration to NVS. */
    save_nvs_config();
    xu_host_set_runtime_config(s_mqtt_uri, s_mqtt_root, s_hid_name, s_ssid);

    /* Stage 2: Wi-Fi is connected! Start Xu MQTT app and switch BLE into Multi-Peer HID Mode. */
    if (!xu_host_start()) {
        ESP_LOGE(TAG, "Xu app start failed");
        return;
    }
    if (!hid_abs_start(s_hid_name)) {
        ESP_LOGE(TAG, "HID start failed");
        return;
    }
    ESP_LOGI(TAG, "Stage 2 HID ready: Wi-Fi IP=%s MQTT=%s root=%s HID=%s",
             s_last_ip, s_mqtt_uri, s_mqtt_root, s_hid_name);
}
