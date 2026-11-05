#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    XU_OP_STATUS = 1,
    XU_OP_ADVERTISING_START = 2,
    XU_OP_ADVERTISING_STOP = 3,
    XU_OP_DISCONNECT = 4,
    XU_OP_RELEASE_ALL = 5,
    XU_OP_KEYBOARD = 6,
    XU_OP_MOUSE = 7,
    XU_OP_CONSUMER = 8,
};

typedef struct {
    bool valid;
    char id[65];
    int op;
    uint8_t report[8];
    size_t report_len;
} xu_command_t;

/* Bounded ASCII JSON: {"id":"...","op":"...","report":[...]} — same rules as
 * #embedded/bluetooth/control. Rejects relative 4-byte mouse reports. */
xu_command_t xu_control_parse(const char *bytes, size_t len);

#ifdef __cplusplus
}
#endif
