#include "xu_host.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "hid_abs.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "status_lcd.h"

/*
 * Host services for the Xu application object (sources in ../xu). Every function here
 * is called from Xu through c_call6(...): int words in, one int word out. A
 * borrowed Xu string arrives as its byte pointer and a []int as a pointer to
 * 8-byte little-endian elements; both are valid only during the call.
 * Xu owns MQTT framing, command parsing and policy; C owns sockets, BLE HID,
 * the LCD and the RTOS.
 */

static const char *TAG = "xu";

/* Emitted by the Xu compiler (relocatable object). */
extern void xu_rt_init(void *heap);
extern int _rom_cb_xu_main_xu_app_main(int arg);

#define XU_HEAP_BYTES 65536
#define RX_CAP 1024

static uint8_t s_rx[RX_CAP];
static int s_rx_len;
static int s_sock = -1;

int xu_host_now_ms(void) {
    return (int)((esp_timer_get_time() / 1000) & 0x7FFFFFFF);
}

int xu_host_sleep_ms(int ms) {
    TickType_t ticks = pdMS_TO_TICKS(ms);
    vTaskDelay(ticks > 0 ? ticks : 1);
    return 0;
}

int xu_host_log(const char *text, int len) {
    ESP_LOGI(TAG, "%.*s", len, text);
    return 1;
}

/* Config strings: 0 MQTT topic root, 1 HID name, 2 Wi-Fi SSID, 3 current IP
 * (snapshotted by xu_host_config_len so the bytes stay consistent). */
static char s_ip_snap[16];
static char s_rt_mqtt_uri[96] = CONFIG_XU_MQTT_URI;
static char s_rt_mqtt_root[64] = CONFIG_XU_MQTT_ROOT;
static char s_rt_hid_name[32] = CONFIG_XU_HID_NAME;
static char s_rt_wifi_ssid[64] = CONFIG_XU_WIFI_SSID;

void xu_host_set_runtime_config(const char *mqtt_uri, const char *mqtt_root,
                                const char *hid_name, const char *wifi_ssid) {
    if (mqtt_uri && mqtt_uri[0]) {
        strncpy(s_rt_mqtt_uri, mqtt_uri, sizeof(s_rt_mqtt_uri) - 1);
    }
    if (mqtt_root && mqtt_root[0]) {
        strncpy(s_rt_mqtt_root, mqtt_root, sizeof(s_rt_mqtt_root) - 1);
    }
    if (hid_name && hid_name[0]) {
        strncpy(s_rt_hid_name, hid_name, sizeof(s_rt_hid_name) - 1);
    }
    if (wifi_ssid && wifi_ssid[0]) {
        strncpy(s_rt_wifi_ssid, wifi_ssid, sizeof(s_rt_wifi_ssid) - 1);
    }
}

static const char *config_text(int key) {
    switch (key) {
    case 0: return s_rt_mqtt_root;
    case 1: return s_rt_hid_name;
    case 2: return s_rt_wifi_ssid;
    case 3: return s_ip_snap;
    default: return "";
    }
}

int xu_host_config_len(int key) {
    if (key == 3) {
        status_lcd_wifi(s_ip_snap, sizeof(s_ip_snap));
    }
    return (int)strlen(config_text(key));
}

/* Copies up to cap bytes of config string key into dst; returns bytes copied. */
int xu_host_config_copy(int key, char *dst, int cap) {
    const char *s = config_text(key);
    int n = (int)strlen(s);
    n = n < cap ? n : cap;
    memcpy(dst, s, n);
    return n;
}

int xu_host_tcp_close(void) {
    if (s_sock >= 0) {
        close(s_sock);
        s_sock = -1;
    }
    s_rx_len = 0;
    return 1;
}

/* Connect to s_rt_mqtt_uri (mqtt://host:port) within 5 s; socket stays non-blocking. */
int xu_host_tcp_open(void) {
    xu_host_tcp_close();
    const char *uri = s_rt_mqtt_uri;
    const char *host = strstr(uri, "://");
    host = host ? host + 3 : uri;
    char name[64];
    const char *colon = strchr(host, ':');
    size_t n = colon ? (size_t)(colon - host) : strlen(host);
    if (n == 0 || n >= sizeof(name)) {
        return 0;
    }
    memcpy(name, host, n);
    name[n] = 0;
    const char *port = colon ? colon + 1 : "1883";

    struct addrinfo hints = {.ai_family = AF_INET, .ai_socktype = SOCK_STREAM};
    struct addrinfo *res = NULL;
    int gai = getaddrinfo(name, port, &hints, &res);
    if (gai != 0 || !res) {
        ESP_LOGW(TAG, "resolve %s:%s failed (%d)", name, port, gai);
        return 0;
    }
    int fd = socket(res->ai_family, res->ai_socktype, 0);
    if (fd < 0) {
        freeaddrinfo(res);
        return 0;
    }
    fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK);
    int rc = connect(fd, res->ai_addr, res->ai_addrlen);
    freeaddrinfo(res);
    if (rc != 0 && errno != EINPROGRESS) {
        ESP_LOGW(TAG, "connect %s:%s failed (errno %d)", name, port, errno);
        close(fd);
        return 0;
    }
    if (rc != 0) {
        fd_set wfds;
        FD_ZERO(&wfds);
        FD_SET(fd, &wfds);
        struct timeval tv = {.tv_sec = 5};
        int err = 0;
        socklen_t len = sizeof(err);
        int ready = select(fd + 1, NULL, &wfds, NULL, &tv);
        if (ready != 1 || getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) != 0 || err != 0) {
            ESP_LOGW(TAG, "connect %s:%s failed (select %d, error %d)", name, port, ready, err);
            close(fd);
            return 0;
        }
    }
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    s_sock = fd;
    return 1;
}

/* >0: bytes now readable via xu_host_rx_copy; 0: nothing yet; -1: closed. */
int xu_host_tcp_recv(void) {
    if (s_sock < 0) {
        return -1;
    }
    int n = recv(s_sock, s_rx, sizeof(s_rx), MSG_DONTWAIT);
    if (n > 0) {
        s_rx_len = n;
        return n;
    }
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
        return 0;
    }
    return -1;
}

/* Copies up to cap bytes of the last xu_host_tcp_recv into dst. */
int xu_host_rx_copy(uint8_t *dst, int cap) {
    int n = s_rx_len < cap ? s_rx_len : cap;
    memcpy(dst, s_rx, n);
    return n;
}

/* Sends all len bytes, waiting up to 3 s for socket space. */
int xu_host_tcp_send(const uint8_t *data, int len) {
    int sent = 0;
    int waits = 0;
    while (s_sock >= 0 && sent < len) {
        int n = send(s_sock, data + sent, len - sent, 0);
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && waits++ < 300) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (n <= 0) {
            return 0;
        }
        sent += n;
    }
    return s_sock >= 0;
}

/* HID state: 1 connected, 2 encrypted, 3 keyboard, 4 mouse, 5 consumer, 6 advertising, 7 paired,
 * 8 connected_count, 9 peer_connected(slot), 10 peer_ready(slot). */
int xu_host_hid_state(int what, int slot) {
    switch (what) {
    case 1: return hid_abs_connected();
    case 2: return hid_abs_encrypted_ready();
    case 3: return hid_abs_keyboard_subscribed();
    case 4: return hid_abs_mouse_subscribed();
    case 5: return hid_abs_consumer_subscribed();
    case 6: return hid_abs_advertising();
    case 7: return hid_abs_paired();
    case 8: return hid_abs_connected_count();
    case 9: return hid_abs_peer_connected(slot);
    case 10: return hid_abs_peer_ready(slot);
    default: return 0;
    }
}

/* Peer string: kind 0 = BDA, kind 1 = phone name read via GATT 0x2A00. */
int xu_host_peer_len(int slot, int kind) {
    const char *s = (kind == 0) ? hid_abs_peer_bda(slot) : hid_abs_peer_name(slot);
    return (int)strlen(s);
}

int xu_host_peer_copy(int slot, int kind, char *dst, int cap) {
    const char *s = (kind == 0) ? hid_abs_peer_bda(slot) : hid_abs_peer_name(slot);
    int n = (int)strlen(s);
    n = n < cap ? n : cap;
    memcpy(dst, s, n);
    return n;
}

/* HID actions: 1 advertise on, 2 advertise off, 3 disconnect(target), 4 release all(target). */
int xu_host_hid_action(int what, int target) {
    switch (what) {
    case 1: return hid_abs_set_advertising(true);
    case 2: return hid_abs_set_advertising(false);
    case 3: return hid_abs_disconnect_to(target);
    case 4: return hid_abs_release_all_to(target);
    default: return 0;
    }
}

/* Clear the stored network settings and reboot into BLE provisioning mode.
 * The restart is delayed so the MQTT result for this command still leaves. */
static void wifi_reset_reboot(void *arg) {
    (void)arg;
    ESP_LOGW(TAG, "wifi.reset: rebooting into BLE provisioning mode");
    esp_restart();
}

int xu_host_wifi_reset(void) {
    nvs_handle_t h;
    if (nvs_open("xu_cfg", NVS_READWRITE, &h) == ESP_OK) {
        nvs_erase_key(h, "ssid");
        nvs_erase_key(h, "pass");
        nvs_erase_key(h, "mqtt_uri");
        nvs_erase_key(h, "mqtt_root");
        nvs_commit(h);
        nvs_close(h);
    }
    esp_timer_handle_t timer = NULL;
    esp_timer_create_args_t args = {
        .callback = wifi_reset_reboot,
        .name = "xu_wifi_reset",
    };
    if (esp_timer_create(&args, &timer) == ESP_OK) {
        esp_timer_start_once(timer, 700 * 1000);
    } else {
        esp_restart();
    }
    return 1;
}

int xu_host_hid_mouse(int b0, int b1, int b2, int b3, int b4, int target) {
    const uint8_t report[5] = {(uint8_t)b0, (uint8_t)b1, (uint8_t)b2, (uint8_t)b3, (uint8_t)b4};
    return hid_abs_send_mouse_to(target, report);
}

/* Eight bytes packed little-endian, two per word. */
int xu_host_hid_keyboard(int w0, int w1, int w2, int w3, int target) {
    const int w[4] = {w0, w1, w2, w3};
    uint8_t report[8];
    for (int i = 0; i < 4; i++) {
        report[i * 2] = (uint8_t)(w[i] & 0xFF);
        report[i * 2 + 1] = (uint8_t)((w[i] >> 8) & 0xFF);
    }
    return hid_abs_send_keyboard_to(target, report);
}

int xu_host_hid_consumer(int mask, int target) {
    return hid_abs_send_consumer_to(target, (uint8_t)mask);
}

int xu_host_hid_screen_size(int w, int h, int target) {
    return hid_abs_set_screen_size(target, w, h) ? 1 : 0;
}

/* Wi-Fi: 0 connecting, 1 up, 2 failed. */
int xu_host_wifi_state(void) {
    return (int)status_lcd_wifi(NULL, 0);
}

/* RSSI in dBm (negative), or 0 when not associated. */
int xu_host_wifi_rssi(void) {
    wifi_ap_record_t ap;
    return esp_wifi_sta_get_ap_info(&ap) == ESP_OK ? ap.rssi : 0;
}

/* LCD: draw pixels[offset .. offset+count) of a Xu []int as one row. */
#define SPAN_CAP 64

int xu_host_lcd_write(int x, int y, const int32_t *pixels, int offset, int count) {
    uint16_t row[SPAN_CAP];
    if (count <= 0 || count > SPAN_CAP || offset < 0) {
        return 0;
    }
    for (int i = 0; i < count; i++) {
        row[i] = (uint16_t)pixels[(offset + i) * 2];
    }
    return status_lcd_span(x, y, row, count);
}

int xu_host_lcd_flush(void) {
    return status_lcd_flush();
}

int xu_host_lcd_fill(int x, int y, int w, int h, int color) {
    return status_lcd_fill(x, y, w, h, (uint16_t)color);
}

static void xu_task(void *arg) {
    (void)arg;
    int rc = _rom_cb_xu_main_xu_app_main(0);
    ESP_LOGE(TAG, "Xu app returned %d", rc);
    vTaskDelete(NULL);
}

bool xu_host_init(void) {
    void *heap = heap_caps_aligned_alloc(8, XU_HEAP_BYTES, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!heap) {
        ESP_LOGE(TAG, "no %d-byte block for the Xu heap (largest %u)", XU_HEAP_BYTES,
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        return false;
    }
    xu_rt_init(heap);
    return true;
}

bool xu_host_start(void) {
    return xTaskCreate(xu_task, "xu_app", 16384, NULL, 5, NULL) == pdPASS;
}
