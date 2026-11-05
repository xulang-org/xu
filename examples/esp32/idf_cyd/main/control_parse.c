#include "control_parse.h"

#include <ctype.h>
#include <string.h>

static size_t skip_ws(const char *s, size_t n, size_t i) {
    while (i < n && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) {
        i++;
    }
    return i;
}

static int string_end(const char *s, size_t n, size_t at) {
    if (at >= n || s[at] != '"') {
        return -1;
    }
    for (size_t i = at + 1; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '"') {
            return (int)i;
        }
        if (c < 32 || c > 126 || c == '\\') {
            return -1;
        }
    }
    return -1;
}

static bool id_valid(const char *id, size_t len) {
    if (len < 1 || len > 64) {
        return false;
    }
    for (size_t i = 0; i < len; i++) {
        char c = id[i];
        if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
              c == '-' || c == '.' || c == '_')) {
            return false;
        }
    }
    return true;
}

static int operation(const char *name, size_t len) {
    if (len == 6 && memcmp(name, "status", 6) == 0) {
        return XU_OP_STATUS;
    }
    if (len == 17 && memcmp(name, "advertising.start", 17) == 0) {
        return XU_OP_ADVERTISING_START;
    }
    if (len == 16 && memcmp(name, "advertising.stop", 16) == 0) {
        return XU_OP_ADVERTISING_STOP;
    }
    if (len == 10 && memcmp(name, "disconnect", 10) == 0) {
        return XU_OP_DISCONNECT;
    }
    if (len == 11 && memcmp(name, "release.all", 11) == 0) {
        return XU_OP_RELEASE_ALL;
    }
    if (len == 12 && memcmp(name, "hid.keyboard", 12) == 0) {
        return XU_OP_KEYBOARD;
    }
    if (len == 9 && memcmp(name, "hid.mouse", 9) == 0) {
        return XU_OP_MOUSE;
    }
    if (len == 12 && memcmp(name, "hid.consumer", 12) == 0) {
        return XU_OP_CONSUMER;
    }
    return 0;
}

static bool report_valid(const xu_command_t *cmd) {
    int op = cmd->op;
    size_t n = cmd->report_len;
    const uint8_t *r = cmd->report;
    if (op == XU_OP_STATUS || op == XU_OP_ADVERTISING_START || op == XU_OP_ADVERTISING_STOP ||
        op == XU_OP_DISCONNECT || op == XU_OP_RELEASE_ALL) {
        return n == 0;
    }
    if (op == XU_OP_KEYBOARD) {
        if (n != 8 || r[1] != 0) {
            return false;
        }
        for (size_t i = 2; i < 8; i++) {
            if (r[i] > 115) {
                return false;
            }
        }
        return true;
    }
    if (op == XU_OP_MOUSE) {
        if (n != 5 || r[0] > 7) {
            return false;
        }
        unsigned x = (unsigned)r[1] | ((unsigned)r[2] << 8);
        unsigned y = (unsigned)r[3] | ((unsigned)r[4] << 8);
        return x <= 32767 && y <= 32767;
    }
    if (op == XU_OP_CONSUMER) {
        return n == 1 && r[0] <= 31;
    }
    return false;
}

static xu_command_t empty_cmd(void) {
    xu_command_t out;
    memset(&out, 0, sizeof(out));
    return out;
}

xu_command_t xu_control_parse(const char *bytes, size_t len) {
    xu_command_t out = empty_cmd();
    if (bytes == NULL || len == 0 || len > 512) {
        return out;
    }
    size_t at = skip_ws(bytes, len, 0);
    if (at >= len || bytes[at] != '{') {
        return out;
    }
    at = skip_ws(bytes, len, at + 1);
    int seen = 0;
    while (at < len && bytes[at] != '}') {
        int last = string_end(bytes, len, at);
        if (last < 0) {
            return empty_cmd();
        }
        const char *name = bytes + at + 1;
        size_t name_len = (size_t)last - at - 1;
        at = skip_ws(bytes, len, (size_t)last + 1);
        if (at >= len || bytes[at] != ':') {
            return empty_cmd();
        }
        at = skip_ws(bytes, len, at + 1);
        if ((name_len == 2 && memcmp(name, "id", 2) == 0) ||
            (name_len == 2 && memcmp(name, "op", 2) == 0)) {
            int bit = name[0] == 'i' ? 1 : 2;
            if ((seen & bit) != 0) {
                return empty_cmd();
            }
            int end = string_end(bytes, len, at);
            if (end < 0) {
                return empty_cmd();
            }
            const char *value = bytes + at + 1;
            size_t value_len = (size_t)end - at - 1;
            if (bit == 1) {
                if (!id_valid(value, value_len)) {
                    return empty_cmd();
                }
                memcpy(out.id, value, value_len);
                out.id[value_len] = 0;
            } else {
                out.op = operation(value, value_len);
            }
            seen |= bit;
            at = skip_ws(bytes, len, (size_t)end + 1);
        } else if (name_len == 6 && memcmp(name, "report", 6) == 0) {
            if ((seen & 4) != 0 || at >= len || bytes[at] != '[') {
                return empty_cmd();
            }
            seen |= 4;
            at = skip_ws(bytes, len, at + 1);
            while (at < len && bytes[at] != ']') {
                if (out.report_len >= 8 || bytes[at] < '0' || bytes[at] > '9') {
                    return empty_cmd();
                }
                unsigned value = 0;
                int digits = 0;
                bool zero = false;
                while (at < len && bytes[at] >= '0' && bytes[at] <= '9') {
                    if (digits == 0 && bytes[at] == '0') {
                        zero = true;
                    }
                    if (digits > 0 && zero) {
                        return empty_cmd();
                    }
                    value = value * 10u + (unsigned)(bytes[at] - '0');
                    if (value > 255) {
                        return empty_cmd();
                    }
                    digits++;
                    at++;
                }
                out.report[out.report_len++] = (uint8_t)value;
                at = skip_ws(bytes, len, at);
                if (at < len && bytes[at] == ',') {
                    at = skip_ws(bytes, len, at + 1);
                    if (at >= len || bytes[at] == ']') {
                        return empty_cmd();
                    }
                } else {
                    break;
                }
            }
            if (at >= len || bytes[at] != ']') {
                return empty_cmd();
            }
            at = skip_ws(bytes, len, at + 1);
        } else {
            return empty_cmd();
        }
        if (at < len && bytes[at] == ',') {
            at = skip_ws(bytes, len, at + 1);
            if (at >= len || bytes[at] == '}') {
                return empty_cmd();
            }
        } else {
            break;
        }
    }
    if (at >= len || bytes[at] != '}' || skip_ws(bytes, len, at + 1) != len ||
        (seen & 3) != 3 || out.op == 0 || !report_valid(&out)) {
        return empty_cmd();
    }
    out.valid = true;
    return out;
}
