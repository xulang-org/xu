#include <stdio.h>
#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "hid_abs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "status_lcd.h"
#include "xu_host.h"

static const char *TAG = "idf_cyd";
static EventGroupHandle_t s_wifi;
static const int WIFI_OK = BIT0;

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected; retry");
        status_lcd_set_wifi(STATUS_WIFI_CONNECTING, NULL);
        xEventGroupClearBits(s_wifi, WIFI_OK);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        ESP_LOGI(TAG, "got ip " IPSTR, IP2STR(&event->ip_info.ip));
        char ip[16];
        snprintf(ip, sizeof(ip), IPSTR, IP2STR(&event->ip_info.ip));
        status_lcd_set_wifi(STATUS_WIFI_UP, ip);
        xEventGroupSetBits(s_wifi, WIFI_OK);
    }
}

static bool wifi_start(void) {
    if (CONFIG_XU_WIFI_SSID[0] == 0) {
        ESP_LOGE(TAG, "CONFIG_XU_WIFI_SSID is empty; pass --ssid to scripts/build.sh");
        return false;
    }
    s_wifi = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_config_t wifi = {0};
    strncpy((char *)wifi.sta.ssid, CONFIG_XU_WIFI_SSID, sizeof(wifi.sta.ssid) - 1);
    strncpy((char *)wifi.sta.password, CONFIG_XU_WIFI_PASSWORD, sizeof(wifi.sta.password) - 1);
    wifi.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi));
    ESP_ERROR_CHECK(esp_wifi_start());
    EventBits_t bits = xEventGroupWaitBits(s_wifi, WIFI_OK, pdFALSE, pdTRUE, pdMS_TO_TICKS(60000));
    return (bits & WIFI_OK) != 0;
}

void app_main(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    ESP_LOGI(TAG, "Xu IDF CYD — official BT/Wi-Fi static libs");
    if (!xu_host_init()) {
        ESP_LOGE(TAG, "Xu runtime init failed");
        return;
    }
    if (!status_lcd_start()) {
        ESP_LOGW(TAG, "status screen unavailable; continuing headless");
    }
    if (!xu_host_start()) {
        ESP_LOGE(TAG, "Xu app start failed");
        return;
    }
    if (!wifi_start()) {
        ESP_LOGE(TAG, "Wi-Fi failed");
        status_lcd_set_wifi(STATUS_WIFI_FAILED, NULL);
        return;
    }
    if (!hid_abs_start(CONFIG_XU_HID_NAME)) {
        ESP_LOGE(TAG, "HID start failed");
        return;
    }
    ESP_LOGI(TAG, "ready: MQTT root %s HID %s", CONFIG_XU_MQTT_ROOT, CONFIG_XU_HID_NAME);
}
