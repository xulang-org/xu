#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define STATUS_LCD_W 320
#define STATUS_LCD_H 240

typedef enum {
    STATUS_WIFI_CONNECTING,
    STATUS_WIFI_UP,
    STATUS_WIFI_FAILED,
} status_wifi_t;

/* CYD ILI9341 landscape panel. The dashboard itself is drawn by Xu
 * (status_demo ui.xu over #embedded/display) through these primitives. */
bool status_lcd_start(void);
bool status_lcd_fill(int x, int y, int w, int h, uint16_t rgb565);
/* Spans are coalesced into rectangles; call status_lcd_flush to show them. */
bool status_lcd_span(int x, int y, const uint16_t *rgb565, int count);
bool status_lcd_flush(void);

void status_lcd_set_wifi(status_wifi_t state, const char *ip);
status_wifi_t status_lcd_wifi(char *ip, size_t cap);

#ifdef __cplusplus
}
#endif
