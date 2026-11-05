#include "xu_host.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "hid_abs.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#include "sdkconfig.h"
#include "status_lcd.h"

/*
 * Host services for the Xu application object (sources in ../xu). Every function here
 * is called from Xu through c_call6(...): int words in, one int word out.
 * Xu owns MQTT framing, command parsing and policy; C owns sockets, BLE HID,
 * the LCD and the RTOS.
 */

static const char *TAG = "xu";

/* Emitted by the Xu compiler (relocatable object). */
extern void xu_rt_init(void *heap);
extern int _rom_cb_xu_main_xu_app_main(int arg);

#define XU_HEAP_BYTES 65536
#define TEXT_SLOTS 4
#define TEXT_CAP 512
#define RX_CAP 1024
#define TX_CAP 4096

static char s_text[TEXT_SLOTS][TEXT_CAP + 1];
static int s_text_len[TEXT_SLOTS];
static uint8_t s_rx[RX_CAP];
static uint8_t s_tx[TX_CAP];
static int s_tx_len;
static int s_sock = -1;

int xu_host_now_ms(void) {
    return (int)((esp_timer_get_time() / 1000) & 0x7FFFFFFF);
}

int xu_host_sleep_ms(int ms) {
    TickType_t ticks = pdMS_TO_TICKS(ms);
    vTaskDelay(ticks > 0 ? ticks : 1);
    return 0;
}

int xu_host_text_clear(int slot) {
    if (slot < 0 || slot >= TEXT_SLOTS) {
        return 0;
    }
    s_text_len[slot] = 0;
    s_text[slot][0] = 0;
    return 1;
}

int xu_host_text_put(int slot, int byte) {
    if (slot < 0 || slot >= TEXT_SLOTS || s_text_len[slot] >= TEXT_CAP) {
        return 0;
    }
    s_text[slot][s_text_len[slot]++] = (char)byte;
    s_text[slot][s_text_len[slot]] = 0;
    return 1;
}

int xu_host_log(int slot) {
    if (slot < 0 || slot >= TEXT_SLOTS) {
        return 0;
    }
    ESP_LOGI(TAG, "%s", s_text[slot]);
    return 1;
}

/* Config strings: 0 MQTT topic root, 1 HID name, 2 Wi-Fi SSID, 3 current IP
 * (snapshotted by xu_host_config_len so the bytes stay consistent). */
static char s_ip_snap[16];

static const char *config_text(int key) {
    switch (key) {
    case 0: return CONFIG_XU_MQTT_ROOT;
    case 1: return CONFIG_XU_HID_NAME;
    case 2: return CONFIG_XU_WIFI_SSID;
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

int xu_host_config_byte(int key, int index) {
    const char *s = config_text(key);
    return index >= 0 && index < (int)strlen(s) ? (uint8_t)s[index] : 0;
}

int xu_host_tcp_close(void) {
    if (s_sock >= 0) {
        close(s_sock);
        s_sock = -1;
    }
    s_tx_len = 0;
    return 1;
}

/* Connect to CONFIG_XU_MQTT_URI (mqtt://host:port) within 5 s; socket stays non-blocking. */
int xu_host_tcp_open(void) {
    xu_host_tcp_close();
    const char *uri = CONFIG_XU_MQTT_URI;
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

/* >0: bytes now readable via xu_host_rx_byte; 0: nothing yet; -1: closed. */
int xu_host_tcp_recv(void) {
    if (s_sock < 0) {
        return -1;
    }
    int n = recv(s_sock, s_rx, sizeof(s_rx), MSG_DONTWAIT);
    if (n > 0) {
        return n;
    }
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
        return 0;
    }
    return -1;
}

int xu_host_rx_byte(int index) {
    return index >= 0 && index < RX_CAP ? s_rx[index] : 0;
}

int xu_host_tx_put(int byte) {
    if (s_tx_len >= TX_CAP) {
        return 0;
    }
    s_tx[s_tx_len++] = (uint8_t)byte;
    return 1;
}

int xu_host_tcp_flush(void) {
    int sent = 0;
    int waits = 0;
    while (s_sock >= 0 && sent < s_tx_len) {
        int n = send(s_sock, s_tx + sent, s_tx_len - sent, 0);
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && waits++ < 300) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (n <= 0) {
            s_tx_len = 0;
            return 0;
        }
        sent += n;
    }
    s_tx_len = 0;
    return s_sock >= 0;
}

/* HID state: 1 connected, 2 encrypted, 3 keyboard, 4 mouse, 5 consumer, 6 advertising, 7 paired. */
int xu_host_hid_state(int what) {
    switch (what) {
    case 1: return hid_abs_connected();
    case 2: return hid_abs_encrypted_ready();
    case 3: return hid_abs_keyboard_subscribed();
    case 4: return hid_abs_mouse_subscribed();
    case 5: return hid_abs_consumer_subscribed();
    case 6: return hid_abs_advertising();
    case 7: return hid_abs_paired();
    default: return 0;
    }
}

/* HID actions: 1 advertise on, 2 advertise off, 3 disconnect, 4 release all. */
int xu_host_hid_action(int what) {
    switch (what) {
    case 1: return hid_abs_set_advertising(true);
    case 2: return hid_abs_set_advertising(false);
    case 3: return hid_abs_disconnect();
    case 4: return hid_abs_release_all();
    default: return 0;
    }
}

int xu_host_hid_mouse(int b0, int b1, int b2, int b3, int b4) {
    const uint8_t report[5] = {(uint8_t)b0, (uint8_t)b1, (uint8_t)b2, (uint8_t)b3, (uint8_t)b4};
    return hid_abs_send_mouse(report);
}

/* Eight bytes packed little-endian, two per word. */
int xu_host_hid_keyboard(int w0, int w1, int w2, int w3) {
    const int w[4] = {w0, w1, w2, w3};
    uint8_t report[8];
    for (int i = 0; i < 4; i++) {
        report[i * 2] = (uint8_t)(w[i] & 0xFF);
        report[i * 2 + 1] = (uint8_t)((w[i] >> 8) & 0xFF);
    }
    return hid_abs_send_keyboard(report);
}

int xu_host_hid_consumer(int mask) {
    return hid_abs_send_consumer((uint8_t)mask);
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

/* LCD: stage pixels five per call, then draw one horizontal span. */
#define SPAN_CAP 64
static uint16_t s_px[SPAN_CAP];

int xu_host_lcd_px(int index, int p0, int p1, int p2, int p3, int p4) {
    const int p[5] = {p0, p1, p2, p3, p4};
    for (int i = 0; i < 5; i++) {
        if (index + i >= 0 && index + i < SPAN_CAP) {
            s_px[index + i] = (uint16_t)p[i];
        }
    }
    return 1;
}

int xu_host_lcd_span(int x, int y, int count) {
    return count > 0 && count <= SPAN_CAP && status_lcd_span(x, y, s_px, count);
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
