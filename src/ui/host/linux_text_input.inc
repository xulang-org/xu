// Each focus lifetime owns a distinct GTK client. Disconnect before reset:
// delayed callbacks from an old IME must never edit a newly focused document.
struct DrawTextInput {
  XuContentPlugin *owner;
  const uint64_t id;
  GtkIMContext *context = NULL;
  bool focused = false;
  explicit DrawTextInput(XuContentPlugin *p, uint64_t session) : owner(p), id(session) {}
  ~DrawTextInput() { detach(); }
  void detach() {
    owner = NULL; focused = false;
    if (!context) return;
    GtkIMContext *old = context; context = NULL;
    g_signal_handlers_disconnect_by_data(old, this);
    gtk_im_context_focus_out(old);
    gtk_im_context_reset(old);
    gtk_im_context_set_client_widget(old, NULL);
    g_object_unref(old);
  }
  static std::shared_ptr<DrawTextInput> retain(GtkIMContext *context, gpointer data) {
    auto *client = (DrawTextInput *)data;
    auto *p = client->owner;
    // focused covers the synchronous focus-enter handshake too: an IME may
    // request surrounding text before GtkWidget.has-focus changes to true.
    if (!p || p->text_input.get() != client || client->context != context || !client->focused ||
        !p->area || !xu_ui_text_input_active(client->id)) return {};
    return p->text_input;
  }
  bool snapshot(XuTextInputSnapshot *out) const {
    return owner && xu_text_input_read(id, owner->host.canvas_id, owner->canvas_generation, false, out);
  }
  void failed() {
    if (owner) xu_ui_text_input_stop(id, owner->host.canvas_id, owner->canvas_generation, XUTI_NATIVE_UNAVAILABLE);
  }
  void refresh() {
    if (!context || !owner) return;
    XuTextInputSnapshot state;
    if (!snapshot(&state)) return;
    double geometry[8]={};
    if(xu_ui_text_input_query(id,owner->host.canvas_id,owner->canvas_generation,state.revision,3,0,0,0,0,geometry))
      memcpy(state.caret,geometry+4,sizeof(state.caret));
    if(!owner || !context || !focused) return;
    // GTK's client coordinates are logical pixels; GTK applies monitor scaling.
    auto position = [](double value) {
      return isfinite(value) ? (int)std::max(-1073741824.0, std::min(1073741824.0, floor(value))) : 0;
    };
    GdkRectangle caret = {position(state.caret[0] - owner->cam_x), position(state.caret[1] - owner->cam_y),
                         std::max(1, (int)ceil(state.caret[2])), std::max(1, (int)ceil(state.caret[3]))};
    auto *native = GTK_IM_CONTEXT(g_object_ref(context));
    gtk_im_context_set_cursor_location(native, &caret);
    g_object_unref(native);
  }
  static void commit(GtkIMContext *context, const char *text, gpointer data) {
    auto client = retain(context, data); if (!client) return;
    size_t length = text ? strnlen(text, 16385) : 16385;
    if (length > 16384 || !xu_ui_text_input_commit(client->id, text, (unsigned)length, UINT_MAX, UINT_MAX)) client->failed();
  }
  static void preedit_start(GtkIMContext *context, gpointer data) {
    auto client = retain(context, data); if (!client) return;
    if (!xu_ui_text_input_compose(client->id, "", 0, 0, 0, UINT_MAX, UINT_MAX)) client->failed();
  }
  static void preedit_changed(GtkIMContext *context, gpointer data) {
    auto client = retain(context, data); if (!client) return;
    char *text = NULL; PangoAttrList *attributes = NULL; int cursor = 0;
    g_object_ref(context);
    gtk_im_context_get_preedit_string(context, &text, &attributes, &cursor);
    size_t length = text ? strnlen(text, 16385) : 16385;
    bool valid = length <= 16384 && cursor >= 0 && g_utf8_validate(text, (gssize)length, NULL);
    if (valid) valid = cursor <= g_utf8_strlen(text, (gssize)length);
    bool current = (bool)retain(context, data);
    if (valid && current) {
      unsigned byte = (unsigned)(g_utf8_offset_to_pointer(text, cursor) - text);
      valid = xu_ui_text_input_compose(client->id, text, (unsigned)length, byte, byte, UINT_MAX, UINT_MAX) != 0;
    }
    if (attributes) pango_attr_list_unref(attributes);
    g_free(text);
    g_object_unref(context);
    if (!valid && current) client->failed();
  }
  static void preedit_end(GtkIMContext *context, gpointer data) {
    auto client = retain(context, data); if (!client) return;
    // commit already clears the overlay; the following end signal is a no-op.
    if (!xu_ui_text_input_cancel(client->id)) client->failed();
  }
  static gboolean surrounding(GtkIMContext *context, gpointer data) {
    auto client = retain(context, data); if (!client) return FALSE;
    XuTextInputSnapshot state; if (!client->snapshot(&state) || state.password()) return FALSE;
    g_object_ref(context);
#if GTK_CHECK_VERSION(4, 2, 0)
    gtk_im_context_set_surrounding_with_selection(context, state.source.c_str(), (int)state.source.size(),
                                                 (int)state.focus, (int)state.anchor);
#else
    gtk_im_context_set_surrounding(context, state.source.c_str(), (int)state.source.size(), (int)state.focus);
#endif
    g_object_unref(context);
    return TRUE;
  }
  static gboolean delete_surrounding(GtkIMContext *context, int offset, int count, gpointer data) {
    auto client = retain(context, data); if (!client || count < 0) return FALSE;
    XuTextInputSnapshot state; if (!client->snapshot(&state)) return FALSE;
    const char *text = state.source.c_str();
    int64_t cursor = g_utf8_pointer_to_offset(text, text + state.focus);
    int64_t first = cursor + (int64_t)offset, last = first + (int64_t)count;
    if (first < 0 || last > g_utf8_strlen(text, (gssize)state.source.size())) return FALSE;
    unsigned start = (unsigned)(g_utf8_offset_to_pointer(text, (glong)first) - text);
    unsigned end = (unsigned)(g_utf8_offset_to_pointer(text, (glong)last) - text);
    bool accepted = xu_ui_text_input_delete_surrounding_at(client->id, state.revision, start, end) != 0;
    if (!accepted) client->failed();
    return accepted ? TRUE : FALSE;
  }
  void install() {
    context = gtk_im_multicontext_new();
    XuTextInputSnapshot state;
    if (snapshot(&state) && state.password())
      g_object_set(context, "input-purpose", GTK_INPUT_PURPOSE_PASSWORD,
                   "input-hints", GTK_INPUT_HINT_NO_SPELLCHECK, NULL);
    gtk_im_context_set_client_widget(context, owner->area);
    gtk_im_context_set_use_preedit(context, TRUE);
    g_signal_connect(context, "commit", G_CALLBACK(commit), this);
    g_signal_connect(context, "preedit-start", G_CALLBACK(preedit_start), this);
    g_signal_connect(context, "preedit-changed", G_CALLBACK(preedit_changed), this);
    g_signal_connect(context, "preedit-end", G_CALLBACK(preedit_end), this);
    g_signal_connect(context, "retrieve-surrounding", G_CALLBACK(surrounding), this);
    g_signal_connect(context, "delete-surrounding", G_CALLBACK(delete_surrounding), this);
    focused = true;
    auto *native = GTK_IM_CONTEXT(g_object_ref(context));
    refresh(); if (context == native && owner) gtk_im_context_focus_in(native);
    g_object_unref(native);
  }
};

static void draw_text_input_detach(XuContentPlugin *p) {
  if (p->text_input) p->text_input->detach();
  p->text_input.reset(); p->text_input_id = 0;
}
static void draw_text_input_blur(XuContentPlugin *p) {
  auto client = p->text_input;
  if (!client) return;
  client->detach(); p->text_input.reset();
  xu_ui_text_input_cancel(client->id);
}
static void draw_text_input_focus(XuContentPlugin *p, bool entering = false) {
  // The focus controller emits enter before GtkWidget.has-focus is updated.
  // Install synchronously so the first key need not wait for the host poll.
  if (!p->area || (!entering && !gtk_widget_has_focus(p->area)) || p->text_input || !p->text_input_id ||
      !xu_ui_text_input_active(p->text_input_id)) return;
  auto client = std::make_shared<DrawTextInput>(p, p->text_input_id);
  p->text_input = client;
  client->install();
}
static int draw_text_input_command(XuContentPlugin *p, uint64_t id) {
  XuTextInputSnapshot state;
  if (!xu_text_input_read(id, p->host.canvas_id, p->canvas_generation, true, &state)) return 0;
  if (!p->area) {
    xu_ui_text_input_stop(id, p->host.canvas_id, p->canvas_generation, XUTI_NATIVE_UNAVAILABLE); return 1;
  }
  bool starting = p->text_input_id != id;
  if (starting) { draw_text_input_detach(p); p->text_input_id = id; }
  if (!xu_ui_text_input_activate(id, p->host.canvas_id, p->canvas_generation)) {
    draw_text_input_detach(p); return 1;
  }
  // Caret/worker acknowledgements must not steal focus from a dialog or field.
  if (starting) gtk_widget_grab_focus(p->area);
  draw_text_input_focus(p);
  auto client = p->text_input; if (client) client->refresh();
  return 1;
}
static void draw_text_input_poll(XuContentPlugin *p) {
  if (p->text_input_id && !xu_ui_text_input_active(p->text_input_id)) draw_text_input_detach(p);
  if (p->text_input && (!p->area || !gtk_widget_has_focus(p->area))) draw_text_input_blur(p);
  draw_text_input_focus(p);
  auto client = p->text_input; if (client) client->refresh();
}
static bool draw_text_input_key(XuContentPlugin *p, GtkEventControllerKey *controller,
                                guint key, GdkModifierType state, bool pressed) {
  auto client = p->text_input;
  if (!client || !DrawTextInput::retain(client->context, client.get())) return false;
  GdkEvent *event = controller ? gtk_event_controller_get_current_event(GTK_EVENT_CONTROLLER(controller)) : NULL;
  if (event) {
    auto *native = GTK_IM_CONTEXT(g_object_ref(client->context));
    bool consumed = gtk_im_context_filter_keypress(native, event);
    g_object_unref(native);
    if (consumed) return true;
  }
  if (!pressed || !client->owner || !client->focused || !xu_ui_text_input_active(client->id)) return false;
  // Text itself comes only from the IM context. These are logical edit commands;
  // visual bidi/vertical navigation belongs to the layout-aware widget layer.
  bool shift = (state & GDK_SHIFT_MASK) != 0;
  if (state & (GDK_ALT_MASK | GDK_META_MASK | GDK_SUPER_MASK)) return false;
  bool accepted = true;
  if (state & GDK_CONTROL_MASK) {
    if (gdk_keyval_to_lower(key) != GDK_KEY_a) return false;
    if (!xu_ui_text_input_cancel(client->id)) accepted = false;
    if (accepted) accepted = xu_ui_text_input_select_all(client->id) != 0;
  } else if (key == GDK_KEY_Escape) accepted = xu_ui_text_input_cancel(client->id) != 0;
  else {
    XuTextInputSnapshot current;
    if (!client->snapshot(&current) || current.composing()) return false;
    if (key == GDK_KEY_BackSpace || key == GDK_KEY_Delete)
      accepted = xu_ui_text_input_erase(client->id, key == GDK_KEY_BackSpace) != 0;
    else if (key == GDK_KEY_Left || key == GDK_KEY_Right)
      accepted = xu_ui_text_input_move(client->id, key == GDK_KEY_Left, shift) != 0;
    else if ((key == GDK_KEY_Return || key == GDK_KEY_KP_Enter) && (current.flags & 1))
      accepted = xu_ui_text_input_commit(client->id, "\n", 1, UINT_MAX, UINT_MAX) != 0;
    else return false;
  }
  if (!accepted) client->failed();
  return true;
}
