#define INPUT_FUNCTIONS(X) \
 X(SDL_StartTextInput) X(SDL_StopTextInput) X(SDL_TextInputActive) X(SDL_SetTextInputArea) \
 X(SDL_SetWindowRelativeMouseMode) X(SDL_GetWindowRelativeMouseMode) X(SDL_SetWindowMouseGrab) X(SDL_GetWindowMouseGrab)
INPUT_FUNCTIONS(DECLARE)
static bool input_loaded;
static bool load_input(void) {
    if (input_loaded) return true;
#ifdef _WIN32
#define INPUT_FIND(name) GetProcAddress(sdl_library,#name)
#else
#define INPUT_FIND(name) dlsym(sdl_library,#name)
#endif
#define INPUT_LOAD(name) p_##name=(__typeof__(name) *)INPUT_FIND(name); \
 if (!p_##name) { fail("SDL runtime is missing " #name); return false; }
    INPUT_FUNCTIONS(INPUT_LOAD)
    input_loaded=true; return true;
}
xu_int API(window_event_peek)(xu_int id,const xu_i64_span_mut *output) {
    WindowRecord *w=window_record(id); if (!w) return -1;
    if (!output || output->len!=EVENT_WORDS || !output->data) return fail("event requires 21 output words");
    memset(output->data,0,EVENT_WORDS*sizeof(xu_int));
    if (!w->input.count) return 0;
    memcpy(output->data,w->input.events[w->input.head].words,EVENT_WORDS*sizeof(xu_int)); return 1;
}
xu_int API(window_event_read)(xu_int id,const xu_u8_span_mut *text) {
    WindowRecord *w=window_record(id); if (!w) return -1;
    WindowInput *input=&w->input;
    if (!input->count) return fail("window event queue is empty");
    WindowEvent *event=&input->events[input->head]; xu_int length=event->words[18];
    if (!text || text->len!=length || (length && !text->data)) return fail("event text requires exact output size");
    if (length) memcpy(text->data,event->text,(size_t)length);
    if (event->words[0]==W_RESET) input->desynchronized=false;
    input->text_bytes-=(size_t)length; free(event->text); memset(event,0,sizeof(*event));
    input->head=(input->head+1)%EVENT_CAPACITY; --input->count; return 0;
}
xu_int API(window_input_reset)(xu_int id) {
    WindowRecord *w=window_record(id); if (!w) return -1;
    reset_window_input(&w->input,id,RESET_INVALID); return 0;
}
xu_int API(window_event_count)(xu_int id) {
    WindowRecord *w=window_record(id); if (!w) return -1;
    return (xu_int)w->input.count;
}
xu_int API(window_key_down)(xu_int id,xu_int key) {
    WindowRecord *w=window_record(id); if (!w) return -1;
    if (key<0 || key>=EVENT_KEY_COUNT) return fail("physical key is outside the portable key range");
    return w->input.keys[key] ? 1 : 0;
}
xu_int API(window_pointer)(xu_int id,const xu_i64_span_mut *output) {
    WindowRecord *w=window_record(id); if (!w) return -1;
    if (!output || output->len!=4 || !output->data) return fail("pointer state requires four output words");
    xu_int values[]={coordinate_bits(w->input.x),coordinate_bits(w->input.y),w->input.buttons,w->input.modifiers};
    memcpy(output->data,values,sizeof(values)); return 0;
}
xu_int API(window_text)(xu_int id,xu_int action) {
    WindowRecord *w=window_record(id); if (!w || !load_input()) return -1;
    if (action==2) return p_SDL_TextInputActive(w->native) ? 1 : 0;
    if (action==1) return p_SDL_StartTextInput(w->native) ? 0 : sdl_fail();
    if (action==0) return p_SDL_StopTextInput(w->native) ? 0 : sdl_fail();
    return fail("invalid window text input operation");
}
xu_int API(window_text_area)(xu_int id,const xu_i64_span *area) {
    WindowRecord *w=window_record(id); if (!w || !load_input()) return -1;
    if (!area || (area->len!=0 && area->len!=5) || (area->len && !area->data)) return fail("invalid text input area");
    if (!area->len) return p_SDL_SetTextInputArea(w->native,NULL,0) ? 0 : sdl_fail();
    const xu_int *v=area->data;
    for (int i=0;i<5;++i) if (v[i]<INT_MIN || v[i]>INT_MAX) return fail("text input area exceeds int32 range");
    if (v[2]<=0 || v[3]<=0 || v[4]<0 || v[4]>v[2] || v[0]>INT_MAX-v[2] || v[1]>INT_MAX-v[3])
        return fail("invalid text input area extent or cursor");
    SDL_Rect rect={(int)v[0],(int)v[1],(int)v[2],(int)v[3]};
    return p_SDL_SetTextInputArea(w->native,&rect,(int)v[4]) ? 0 : sdl_fail();
}
xu_int API(window_pointer_mode)(xu_int id,xu_int kind,xu_int enabled) {
    WindowRecord *w=window_record(id); if (!w || !load_input()) return -1;
    if (kind<0 || kind>1 || enabled<0 || enabled>2) return fail("invalid pointer mode");
    if (enabled==2) return (kind ? p_SDL_GetWindowMouseGrab(w->native) : p_SDL_GetWindowRelativeMouseMode(w->native)) ? 1 : 0;
    bool ok=kind ? p_SDL_SetWindowMouseGrab(w->native,enabled!=0) : p_SDL_SetWindowRelativeMouseMode(w->native,enabled!=0);
    return ok ? 0 : sdl_fail();
}
