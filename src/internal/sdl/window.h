/* Window lifecycle is independent of GPU ownership. A display binding may
 * register one synchronous release hook; no callback enters Xu or keeps a
 * borrowed pointer. All registry and event filtering work is main-thread-only. */
#define WINDOW_FUNCTIONS(X) \
 X(SDL_CreateWindow) X(SDL_DestroyWindow) X(SDL_GetWindowID) X(SDL_GetWindowFlags) \
 X(SDL_GetWindowSize) X(SDL_GetWindowSizeInPixels) X(SDL_SetWindowSize) X(SDL_ShowWindow) X(SDL_HideWindow) \
 X(SDL_MinimizeWindow) X(SDL_RestoreWindow) X(SDL_PumpEvents) X(SDL_FilterEvents) X(SDL_GetWindowFromEvent)
WINDOW_FUNCTIONS(DECLARE)
static bool window_loaded;
static bool load_window(void) {
    if (!load_sdl()) return false;
    if (window_loaded) return true;
#ifdef _WIN32
#define WINDOW_FIND(name) GetProcAddress(sdl_library, #name)
#else
#define WINDOW_FIND(name) dlsym(sdl_library, #name)
#endif
#define WINDOW_LOAD(name) p_##name = (__typeof__(name) *)WINDOW_FIND(name); \
 if (!p_##name) { fail("SDL runtime is missing " #name); return false; }
    WINDOW_FUNCTIONS(WINDOW_LOAD)
    window_loaded = true;
    return true;
}
#include "events.h"

typedef struct WindowRecord {
    xu_int id;
    SDL_WindowID event_id;
    SDL_Window *native;
    bool closed, close_requested;
    WindowInput input;
    void *binding;
    bool (*release_binding)(void *);
    struct WindowRecord *next;
} WindowRecord;
static WindowRecord *windows;
static WindowRecord *window_record(xu_int id) {
    if (!on_main()) return NULL;
    for (WindowRecord *w=windows; w; w=w->next) if (w->id==id && !w->closed) return w;
    fail("closed or invalid window"); return NULL;
}
static bool filter_window_events(void *userdata, SDL_Event *event) {
    (void)userdata;
    if (event->type==SDL_EVENT_QUIT) {
        for (WindowRecord *w=windows; w; w=w->next) {
            if (!w->close_requested && !w->closed) collect_window_event(&w->input,w->id,event);
            w->close_requested=true;
        }
        return true; /* Leave global quit for external SDL consumers, once per owner. */
    }
    if (event->type>=SDL_EVENT_USER) return true;
    SDL_Window *target=p_SDL_GetWindowFromEvent(event);
    for (WindowRecord *w=windows; w; w=w->next) {
        bool window_event=event->type>=SDL_EVENT_WINDOW_FIRST && event->type<=SDL_EVENT_WINDOW_LAST;
        if ((window_event && w->event_id==event->window.windowID) || (target && target==w->native)) {
            if (!w->closed) {
                if (event->type==SDL_EVENT_WINDOW_CLOSE_REQUESTED) w->close_requested=true;
                collect_window_event(&w->input,w->id,event);
            }
            return false;
        }
    }
    return true;
}

xu_int API(window_open)(const xu_u8_span *title, xu_int width, xu_int height, xu_int options) {
    if (!title || title->len<1 || title->len>4096 || !title->data || memchr(title->data,0,(size_t)title->len) ||
        width<1 || width>INT_MAX || height<1 || height>INT_MAX || options<0 || options>7)
        return fail("invalid window title, dimensions or options");
    if (!load_window()) return -1;
    WindowRecord *w=calloc(1,sizeof(*w)); char *name=calloc((size_t)title->len+1,1);
    if (!w || !name) { free(w); free(name); return fail("window allocation failed"); }
    w->id=identifier(); if (w->id<0) { free(w); free(name); return -1; }
    memcpy(name,title->data,(size_t)title->len);
    if (!p_SDL_InitSubSystem(0x20u)) { free(w); free(name); return sdl_fail(); }
    SDL_WindowFlags flags=0;
    if (options&1) flags|=SDL_WINDOW_RESIZABLE;
    if (options&2) flags|=SDL_WINDOW_HIGH_PIXEL_DENSITY;
    if (options&4) flags|=SDL_WINDOW_HIDDEN;
    w->native=p_SDL_CreateWindow(name,(int)width,(int)height,flags); free(name);
    if (!w->native) { sdl_fail(); p_SDL_QuitSubSystem(0x20u); free(w); return -1; }
    w->event_id=p_SDL_GetWindowID(w->native);
    if (!w->event_id) { sdl_fail(); p_SDL_DestroyWindow(w->native); p_SDL_QuitSubSystem(0x20u); free(w); return -1; }
    w->next=windows; windows=w; return w->id;
}
xu_int API(window_close)(xu_int id) {
    if (!on_main()) return -1;
    WindowRecord **link=&windows; while (*link && (*link)->id!=id) link=&(*link)->next;
    if (!*link || (*link)->closed) return 0;
    WindowRecord *w=*link; w->closed=true;
    bool ok=!w->release_binding || w->release_binding(w->binding);
    p_SDL_FilterEvents(filter_window_events,NULL);
    p_SDL_DestroyWindow(w->native); w->native=NULL;
    p_SDL_FilterEvents(filter_window_events,NULL);
    clear_window_events(&w->input);
    *link=w->next; free(w); p_SDL_QuitSubSystem(0x20u);
    return ok ? 0 : -1;
}
xu_int API(window_pump)(void) {
    if (!on_main()) return -1;
    if (!windows) return 0;
    if (!load_window()) return -1;
    p_SDL_PumpEvents(); p_SDL_FilterEvents(filter_window_events,NULL); return 0;
}
xu_int API(window_state)(xu_int id, const xu_i64_span_mut *output) {
    WindowRecord *w=window_record(id); if (!w) return -1;
    if (!output || output->len!=8 || !output->data) return fail("window state requires eight output words");
    int width,height,pixel_width,pixel_height;
    if (!p_SDL_GetWindowSize(w->native,&width,&height) || !p_SDL_GetWindowSizeInPixels(w->native,&pixel_width,&pixel_height)) return sdl_fail();
    SDL_WindowFlags flags=p_SDL_GetWindowFlags(w->native);
    xu_int values[]={width,height,pixel_width,pixel_height,w->close_requested,
        !!(flags&SDL_WINDOW_MINIMIZED),!(flags&SDL_WINDOW_HIDDEN),!!(flags&SDL_WINDOW_INPUT_FOCUS)};
    memcpy(output->data,values,sizeof(values)); return 0;
}
xu_int API(window_resize)(xu_int id, xu_int width, xu_int height) {
    WindowRecord *w=window_record(id); if (!w) return -1;
    if (width<1 || width>INT_MAX || height<1 || height>INT_MAX) return fail("invalid window dimensions");
    return p_SDL_SetWindowSize(w->native,(int)width,(int)height) ? 0 : sdl_fail();
}
xu_int API(window_visibility)(xu_int id, xu_int action) {
    WindowRecord *w=window_record(id); if (!w) return -1;
    bool ok;
    if (action==0) ok=p_SDL_HideWindow(w->native);
    else if (action==1) ok=p_SDL_ShowWindow(w->native);
    else if (action==2) ok=p_SDL_MinimizeWindow(w->native);
    else if (action==3) ok=p_SDL_RestoreWindow(w->native);
    else return fail("invalid window visibility operation");
    return ok ? 0 : sdl_fail();
}
xu_int API(window_count)(void) {
    if (!on_main()) return -1;
    xu_int count=0; for (WindowRecord *w=windows; w; w=w->next) if (!w->closed) ++count;
    return count;
}
