/* Bounded callback-mode SDL event inbox shared by App.c and tests.
 * SDL's callback host owns the raw queue; only the owner thread pops events
 * into Xu's pure-Xu SDL decoder. */
#include <SDL3/SDL.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    XU_CB_EVENT_CAPACITY = 256,
    XU_CB_TEXT_LIMIT = 65536,
    XU_CB_TEXT_BUDGET = 262144,
    XU_CB_RESET_QUEUE = 1,
    XU_CB_RESET_SUSPEND = 6
};

typedef struct {
    SDL_Event event;
    char *text;
} CallbackEvent;

static CallbackEvent callback_events[XU_CB_EVENT_CAPACITY];
static CallbackEvent pump_events[XU_CB_EVENT_CAPACITY];
static unsigned callback_count, pump_count, pump_index;
static size_t callback_text_bytes;
static bool callback_overflow, callback_suspended, callback_accepting, callback_quit, callback_mode;
static SDL_WindowID callback_closes[XU_CB_EVENT_CAPACITY];
static unsigned callback_close_count;
static pthread_mutex_t callback_mutex = PTHREAD_MUTEX_INITIALIZER;

static void clear_pump_events(void) {
    while (pump_index < pump_count) {
        free(pump_events[pump_index].text);
        memset(&pump_events[pump_index], 0, sizeof(pump_events[pump_index]));
        ++pump_index;
    }
    pump_count = 0;
    pump_index = 0;
}

void xu_sdl_callback_begin(void) {
    pthread_mutex_lock(&callback_mutex);
    callback_accepting = true;
    callback_mode = true;
    pthread_mutex_unlock(&callback_mutex);
}

void xu_sdl_callback_suspend(void) {
    pthread_mutex_lock(&callback_mutex);
    if (callback_accepting) callback_suspended = true;
    pthread_mutex_unlock(&callback_mutex);
}

void xu_sdl_callback_event(const SDL_Event *event) {
    if (!event) return;
    pthread_mutex_lock(&callback_mutex);
    if (!callback_accepting) {
        pthread_mutex_unlock(&callback_mutex);
        return;
    }
    if (event->type == SDL_EVENT_QUIT) callback_quit = true;
    if (event->type == SDL_EVENT_WINDOW_CLOSE_REQUESTED) {
        bool seen = false;
        for (unsigned i = 0; i < callback_close_count; ++i)
            if (callback_closes[i] == event->window.windowID) seen = true;
        if (!seen) {
            if (callback_close_count < XU_CB_EVENT_CAPACITY)
                callback_closes[callback_close_count++] = event->window.windowID;
            else
                callback_quit = true;
        }
    }
    if (callback_overflow) {
        pthread_mutex_unlock(&callback_mutex);
        return;
    }
    const char *text = NULL;
    if (event->type == SDL_EVENT_TEXT_INPUT) text = event->text.text;
    if (event->type == SDL_EVENT_TEXT_EDITING) text = event->edit.text;
    size_t bytes = text ? strnlen(text, XU_CB_TEXT_LIMIT + 1) : 0;
    char *copy = bytes <= XU_CB_TEXT_LIMIT && text ? (char *)malloc(bytes + 1) : NULL;
    if (callback_count == XU_CB_EVENT_CAPACITY || bytes > XU_CB_TEXT_LIMIT ||
        bytes > XU_CB_TEXT_BUDGET - callback_text_bytes || (text && !copy)) {
        free(copy);
        callback_overflow = true;
    } else {
        CallbackEvent *slot = &callback_events[callback_count++];
        slot->event = *event;
        slot->text = copy;
        if (text) {
            memcpy(copy, text, bytes + 1);
            if (event->type == SDL_EVENT_TEXT_INPUT) slot->event.text.text = copy;
            else slot->event.edit.text = copy;
        }
        callback_text_bytes += bytes;
    }
    pthread_mutex_unlock(&callback_mutex);
}

__attribute__((used, visibility("default")))
int xu_phone_callback_mode(void) {
    return callback_mode ? 1 : 0;
}

__attribute__((used, visibility("default")))
int xu_phone_callback_take(int *discard_reason, int *has_quit, int *close_count,
                           unsigned int *closes_out, int closes_cap) {
    clear_pump_events();
    if (discard_reason) *discard_reason = 0;
    if (has_quit) *has_quit = 0;
    if (close_count) *close_count = 0;
    pthread_mutex_lock(&callback_mutex);
    bool discard = callback_overflow || callback_suspended;
    int work = 0;
    if (discard) {
        if (discard_reason)
            *discard_reason = callback_suspended ? XU_CB_RESET_SUSPEND : XU_CB_RESET_QUEUE;
        bool quit = callback_quit;
        unsigned copy_count = callback_close_count;
        if (closes_cap < 0 || copy_count > (unsigned)closes_cap) {
            copy_count = closes_cap > 0 ? (unsigned)closes_cap : 0u;
            quit = true;
        }
        if (has_quit) *has_quit = quit ? 1 : 0;
        if (close_count) *close_count = (int)copy_count;
        if (closes_out && copy_count > 0) {
            for (unsigned i = 0; i < copy_count; ++i) closes_out[i] = callback_closes[i];
        }
        for (unsigned i = 0; i < callback_count; ++i) {
            free(callback_events[i].text);
            memset(&callback_events[i], 0, sizeof(callback_events[i]));
        }
        work = 1;
    } else if (callback_count > 0) {
        memcpy(pump_events, callback_events, callback_count * sizeof(CallbackEvent));
        memset(callback_events, 0, callback_count * sizeof(CallbackEvent));
        pump_count = callback_count;
        pump_index = 0;
        work = 1;
    }
    callback_count = 0;
    callback_text_bytes = 0;
    callback_overflow = false;
    callback_suspended = false;
    callback_quit = false;
    callback_close_count = 0;
    pthread_mutex_unlock(&callback_mutex);
    return work;
}

__attribute__((used, visibility("default")))
int xu_phone_callback_pop(void *out_event_bytes, char *text_buf, int text_cap) {
    if (pump_index >= pump_count) {
        clear_pump_events();
        return 0;
    }
    CallbackEvent *slot = &pump_events[pump_index++];
    SDL_Event ev = slot->event;
    if (slot->text) {
        size_t len = strlen(slot->text);
        if (!text_buf || text_cap <= 0 || len >= (size_t)text_cap) {
            free(slot->text);
            memset(slot, 0, sizeof(*slot));
            return -1;
        }
        memcpy(text_buf, slot->text, len + 1);
        if (ev.type == SDL_EVENT_TEXT_INPUT) ev.text.text = text_buf;
        else if (ev.type == SDL_EVENT_TEXT_EDITING) ev.edit.text = text_buf;
        free(slot->text);
    }
    if (out_event_bytes) memcpy(out_event_bytes, &ev, sizeof(ev));
    memset(slot, 0, sizeof(*slot));
    if (pump_index >= pump_count) {
        pump_count = 0;
        pump_index = 0;
    }
    return 1;
}

void xu_sdl_callback_end(void) {
    pthread_mutex_lock(&callback_mutex);
    callback_accepting = false;
    pthread_mutex_unlock(&callback_mutex);
    int r = 0, q = 0, cc = 0;
    xu_phone_callback_take(&r, &q, &cc, NULL, 0);
    clear_pump_events();
    callback_mode = false;
}

#ifdef __cplusplus
}
#endif
