#include "status_lcd.h"

#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_st7789.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "status_lcd";

/* ESP32-2432S028 (CYD) panel wiring and the status_demo landscape MADCTL. */
#define LCD_HOST SPI2_HOST
#define LCD_SCLK 14
#define LCD_MOSI 13
#define LCD_CS 15
#define LCD_DC 2
#define LCD_BL 21
#define LCD_PCLK_HZ (40 * 1000 * 1000)
#define LCD_MADCTL_LANDSCAPE 0x70
#define BAND_H 16
#define UI_BG 0x0842

static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_buf;
static SemaphoreHandle_t s_flush_done;
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static status_wifi_t s_wifi = STATUS_WIFI_CONNECTING;
static char s_ip[16];

static bool on_flush_done(esp_lcd_panel_io_handle_t io, esp_lcd_panel_io_event_data_t *edata, void *ctx) {
    (void)io;
    (void)edata;
    (void)ctx;
    BaseType_t woken = pdFALSE;
    xSemaphoreGiveFromISR(s_flush_done, &woken);
    return woken == pdTRUE;
}

static bool flush(int x, int y, int w, int h) {
    if (esp_lcd_panel_draw_bitmap(s_panel, x, y, x + w, y + h, s_buf) != ESP_OK) {
        return false;
    }
    xSemaphoreTake(s_flush_done, portMAX_DELAY);
    return true;
}

static bool in_bounds(int x, int y, int w, int h) {
    return s_panel && w > 0 && h > 0 && x >= 0 && y >= 0 && x + w <= STATUS_LCD_W && y + h <= STATUS_LCD_H;
}

bool status_lcd_fill(int x, int y, int w, int h, uint16_t color) {
    if (!in_bounds(x, y, w, h)) {
        return false;
    }
    uint16_t wire = __builtin_bswap16(color);
    while (h > 0) {
        int rows = h < BAND_H ? h : BAND_H;
        for (int i = 0; i < w * rows; i++) {
            s_buf[i] = wire;
        }
        if (!flush(x, y, w, rows)) {
            return false;
        }
        y += rows;
        h -= rows;
    }
    return true;
}

bool status_lcd_span(int x, int y, const uint16_t *pixels, int count) {
    if (!in_bounds(x, y, count, 1)) {
        return false;
    }
    for (int i = 0; i < count; i++) {
        s_buf[i] = __builtin_bswap16(pixels[i]);
    }
    return flush(x, y, count, 1);
}

bool status_lcd_start(void) {
    gpio_config_t bl = {.pin_bit_mask = 1ULL << LCD_BL, .mode = GPIO_MODE_OUTPUT};
    gpio_config(&bl);
    gpio_set_level(LCD_BL, 0);

    spi_bus_config_t bus = {
        .sclk_io_num = LCD_SCLK,
        .mosi_io_num = LCD_MOSI,
        .miso_io_num = -1,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = STATUS_LCD_W * BAND_H * sizeof(uint16_t),
    };
    if (spi_bus_initialize(LCD_HOST, &bus, SPI_DMA_CH_AUTO) != ESP_OK) {
        ESP_LOGE(TAG, "SPI bus init failed");
        return false;
    }
    s_flush_done = xSemaphoreCreateBinary();
    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_io_spi_config_t io_cfg = {
        .dc_gpio_num = LCD_DC,
        .cs_gpio_num = LCD_CS,
        .pclk_hz = LCD_PCLK_HZ,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 4,
        .on_color_trans_done = on_flush_done,
    };
    if (esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST, &io_cfg, &io) != ESP_OK) {
        ESP_LOGE(TAG, "panel IO init failed");
        return false;
    }
    esp_lcd_panel_dev_config_t panel_cfg = {
        .reset_gpio_num = -1,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };
    if (esp_lcd_new_panel_st7789(io, &panel_cfg, &s_panel) != ESP_OK) {
        ESP_LOGE(TAG, "panel init failed");
        return false;
    }
    esp_lcd_panel_reset(s_panel);
    esp_lcd_panel_init(s_panel);
    esp_lcd_panel_io_tx_param(io, 0x36, (uint8_t[]){LCD_MADCTL_LANDSCAPE}, 1);
    esp_lcd_panel_invert_color(s_panel, false);
    esp_lcd_panel_disp_on_off(s_panel, true);

    s_buf = heap_caps_malloc(STATUS_LCD_W * BAND_H * sizeof(uint16_t), MALLOC_CAP_DMA);
    if (!s_buf) {
        ESP_LOGE(TAG, "line buffer alloc failed");
        s_panel = NULL;
        return false;
    }
    status_lcd_fill(0, 0, STATUS_LCD_W, STATUS_LCD_H, UI_BG);
    gpio_set_level(LCD_BL, 1);
    ESP_LOGI(TAG, "panel on; Xu draws the dashboard");
    return true;
}

void status_lcd_set_wifi(status_wifi_t state, const char *ip) {
    portENTER_CRITICAL(&s_lock);
    s_wifi = state;
    strncpy(s_ip, ip ? ip : "", sizeof(s_ip) - 1);
    portEXIT_CRITICAL(&s_lock);
}

status_wifi_t status_lcd_wifi(char *ip, size_t cap) {
    portENTER_CRITICAL(&s_lock);
    status_wifi_t state = s_wifi;
    if (ip && cap > 0) {
        strncpy(ip, s_ip, cap - 1);
        ip[cap - 1] = 0;
    }
    portEXIT_CRITICAL(&s_lock);
    return state;
}
