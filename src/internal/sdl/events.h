/* Bounded per-window copies. No SDL event/text pointer survives filtering.
 * Public wire words mirror window/events; coordinates carry IEEE binary64. */
enum { EVENT_WORDS=21, EVENT_CAPACITY=256, EVENT_TEXT_LIMIT=65536, EVENT_TEXT_BUDGET=262144, EVENT_KEY_COUNT=232 };
enum { W_NONE, W_CLOSE, W_FOCUS_GAINED, W_FOCUS_LOST, W_RESIZED, W_PIXEL_SIZE, W_KEY_DOWN, W_KEY_UP,
    W_POINTER_MOVE, W_POINTER_DOWN, W_POINTER_UP, W_WHEEL, W_TEXT, W_EDIT, W_RESET };
enum { RESET_QUEUE=1, RESET_TEXT, RESET_INVALID, RESET_ALLOC };
typedef struct { xu_int words[EVENT_WORDS]; char *text; } WindowEvent;
typedef struct {
    WindowEvent events[EVENT_CAPACITY];
    unsigned head, count;
    size_t text_bytes;
    bool keys[EVENT_KEY_COUNT], desynchronized;
    xu_int buttons, modifiers;
    double x,y;
} WindowInput;
static xu_int coordinate_bits(double value) { xu_int bits; memcpy(&bits,&value,8); return bits; }
static void clear_input_state(WindowInput *input) {
    memset(input->keys,0,sizeof(input->keys)); input->buttons=0; input->modifiers=0; input->x=0; input->y=0;
}
static void clear_window_events(WindowInput *input) {
    while (input->count) {
        WindowEvent *event=&input->events[input->head]; free(event->text); memset(event,0,sizeof(*event));
        input->head=(input->head+1)%EVENT_CAPACITY; --input->count;
    }
    input->text_bytes=0; input->head=0;
}
static void reset_window_input(WindowInput *input,xu_int id,int reason) {
    clear_window_events(input); clear_input_state(input);
    input->desynchronized=true; input->count=1;
    input->events[0].words[0]=W_RESET; input->events[0].words[1]=id; input->events[0].words[20]=reason;
}
static xu_int portable_modifiers(unsigned value) {
    const unsigned native[]={0x1,0x2,0x40,0x80,0x100,0x200,0x400,0x800,0x1000,0x2000,0x4000,0x8000,0x4};
    xu_int result=0; for (unsigned i=0;i<13;++i) if (value&native[i]) result|=1ll<<i;
    return result;
}
static xu_int physical_key(int native) { return native>=4 && native<EVENT_KEY_COUNT ? native : 0; }
static xu_int logical_key(Uint32 native,xu_int physical) {
    xu_int named=0;
    if (native&0x40000000u) named=physical_key((int)(native&~0x40000000u));
    else if (native==0x20000001u) named=43; /* Logical back-tab. */
    else if (native==0x20000004u) named=227;
    else if (native==0x20000005u) named=231;
    else if (native && (native<32 || native==127)) named=physical;
    else if (native<=0x10ffffu && !(native>=0xd800 && native<=0xdfff)) return native;
    return named ? 0x110000+named : 0;
}
static bool queue_window_event(WindowInput *input,xu_int id,WindowEvent *value,const char *text) {
    if (input->desynchronized) return false;
    if (input->count==EVENT_CAPACITY) { reset_window_input(input,id,RESET_QUEUE); return false; }
    size_t length=0;
    if (text) {
        while (length<=EVENT_TEXT_LIMIT && text[length]) ++length;
        if (length>EVENT_TEXT_LIMIT || length>EVENT_TEXT_BUDGET-input->text_bytes) {
            reset_window_input(input,id,RESET_TEXT); return false;
        }
        if (length) {
            value->text=malloc(length);
            if (!value->text) { reset_window_input(input,id,RESET_ALLOC); return false; }
            memcpy(value->text,text,length);
        }
    }
    value->words[18]=(xu_int)length;
    input->events[(input->head+input->count)%EVENT_CAPACITY]=*value;
    input->text_bytes+=length; ++input->count; return true;
}
static void collect_window_event(WindowInput *input,xu_int id,const SDL_Event *source) {
    if (input->desynchronized) return;
    WindowEvent value={0}; xu_int *v=value.words; const char *text=NULL;
    v[1]=id;
    if (source->common.timestamp>LLONG_MAX) { reset_window_input(input,id,RESET_INVALID); return; }
    v[2]=(xu_int)source->common.timestamp;
    switch (source->type) {
    case SDL_EVENT_QUIT:
    case SDL_EVENT_WINDOW_CLOSE_REQUESTED: v[0]=W_CLOSE; clear_input_state(input); break;
    case SDL_EVENT_WINDOW_FOCUS_GAINED: v[0]=W_FOCUS_GAINED; break;
    case SDL_EVENT_WINDOW_FOCUS_LOST: v[0]=W_FOCUS_LOST; clear_input_state(input); break;
    case SDL_EVENT_WINDOW_RESIZED:
    case SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED:
        v[0]=source->type==SDL_EVENT_WINDOW_RESIZED ? W_RESIZED : W_PIXEL_SIZE;
        v[14]=source->window.data1; v[15]=source->window.data2; break;
    case SDL_EVENT_KEY_DOWN:
    case SDL_EVENT_KEY_UP:
        v[0]=source->type==SDL_EVENT_KEY_DOWN ? W_KEY_DOWN : W_KEY_UP; v[3]=source->key.which;
        v[4]=physical_key(source->key.scancode); v[5]=logical_key(source->key.key,v[4]);
        v[6]=portable_modifiers(source->key.mod); v[7]=source->key.repeat;
        /* After reset/focus loss, a repeat cannot recreate a held action. */
        if (v[7] && (!v[4] || !input->keys[v[4]])) return;
        if (v[4]) input->keys[v[4]]=v[0]==W_KEY_DOWN;
        input->modifiers=v[6]; break;
    case SDL_EVENT_MOUSE_MOTION:
        v[0]=W_POINTER_MOVE; v[3]=source->motion.which;
        v[10]=coordinate_bits(source->motion.x); v[11]=coordinate_bits(source->motion.y);
        v[12]=coordinate_bits(source->motion.xrel); v[13]=coordinate_bits(source->motion.yrel);
        v[19]=source->motion.state;
        input->x=source->motion.x; input->y=source->motion.y; input->buttons=v[19]; break;
    case SDL_EVENT_MOUSE_BUTTON_DOWN:
    case SDL_EVENT_MOUSE_BUTTON_UP:
        if (source->button.button<1 || source->button.button>32) { reset_window_input(input,id,RESET_INVALID); return; }
        v[0]=source->type==SDL_EVENT_MOUSE_BUTTON_DOWN ? W_POINTER_DOWN : W_POINTER_UP;
        v[3]=source->button.which; v[8]=source->button.button; v[9]=source->button.clicks;
        v[10]=coordinate_bits(source->button.x); v[11]=coordinate_bits(source->button.y);
        if (v[0]==W_POINTER_DOWN) input->buttons|=1ll<<(v[8]-1);
        else input->buttons&=~(1ll<<(v[8]-1));
        v[19]=input->buttons; input->x=source->button.x; input->y=source->button.y; break;
    case SDL_EVENT_MOUSE_WHEEL: {
        if (source->wheel.direction<0 || source->wheel.direction>1) { reset_window_input(input,id,RESET_INVALID); return; }
        double sign=source->wheel.direction ? -1.0 : 1.0;
        v[0]=W_WHEEL; v[3]=source->wheel.which;
        v[10]=coordinate_bits(source->wheel.mouse_x); v[11]=coordinate_bits(source->wheel.mouse_y);
        v[12]=coordinate_bits(sign*source->wheel.x); v[13]=coordinate_bits(sign*source->wheel.y);
        input->x=source->wheel.mouse_x; input->y=source->wheel.mouse_y; break;
    }
    case SDL_EVENT_TEXT_INPUT: v[0]=W_TEXT; text=source->text.text; break;
    case SDL_EVENT_TEXT_EDITING:
        v[0]=W_EDIT; text=source->edit.text; v[16]=source->edit.start; v[17]=source->edit.length;
        if (v[16]<-1 || v[17]<-1) { reset_window_input(input,id,RESET_INVALID); return; }
        break;
    default: return;
    }
    if (v[0]>=W_POINTER_MOVE && v[0]<=W_WHEEL) {
        for (int i=10;i<=13;++i) { double number; memcpy(&number,&v[i],8);
            if (!isfinite(number)) { reset_window_input(input,id,RESET_INVALID); return; } }
        v[6]=input->modifiers;
    }
    if ((v[0]==W_TEXT || v[0]==W_EDIT) && !text) { reset_window_input(input,id,RESET_INVALID); return; }
    queue_window_event(input,id,&value,text);
}
