// A transparent input proxy has a distinct HWND and HIMC for each focus
// lifetime. Queued character/IME messages cannot target the next document.
struct DrawTextInput {
  XuContentPlugin *owner;
  const uint64_t id;
  HWND hwnd = NULL;
  HIMC context = NULL, previous = NULL;
  bool retired = false, result_handled = false;
  wchar_t high_surrogate = 0;
  unsigned high_repeat = 0;
  explicit DrawTextInput(XuContentPlugin *p, uint64_t session) : owner(p), id(session) {}
  ~DrawTextInput() { detach(); }
  void detach(bool destroying = false) {
    retired = true; owner = NULL; high_surrogate = 0;
    HWND old = hwnd; hwnd = NULL;
    if (old) SetWindowLongPtrW(old, GWLP_USERDATA, 0);
    if (context) {
      if (previous) {
        DWORD conversion = 0, sentence = 0;
        if (ImmGetConversionStatus(context, &conversion, &sentence)) ImmSetConversionStatus(previous, conversion, sentence);
        ImmSetOpenStatus(previous, ImmGetOpenStatus(context));
      }
      ImmNotifyIME(context, NI_COMPOSITIONSTR, CPS_CANCEL, 0);
      if (old) ImmAssociateContext(old, previous);
      ImmDestroyContext(context); context = NULL;
    }
    if (old && !destroying && IsWindow(old)) DestroyWindow(old);
  }
  static std::shared_ptr<DrawTextInput> retain(HWND hwnd) {
    auto *client = (DrawTextInput *)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
    if (!client || client->retired || client->hwnd != hwnd || !client->owner || GetFocus() != hwnd) return {};
    auto *p = client->owner;
    if (p->closing || p->text_input.get() != client || !xu_ui_text_input_active(client->id)) return {};
    return p->text_input;
  }
  bool snapshot(XuTextInputSnapshot *state) const {
    return owner && xu_text_input_read(id, owner->host.canvas_id, owner->canvas_generation, false, state);
  }
  bool live() const {
    return !retired && owner && owner->text_input.get() == this && hwnd && GetFocus() == hwnd;
  }
  void failed() {
    if (owner) xu_ui_text_input_stop(id, owner->host.canvas_id, owner->canvas_generation, XUTI_NATIVE_UNAVAILABLE);
  }
  static bool utf8(const wchar_t *text, unsigned length, std::string *out) {
    if (!out || length > 16384 || (length && !text)) return false;
    if (!length) { out->clear(); return true; }
    int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, (int)length, NULL, 0, NULL, NULL);
    if (bytes <= 0 || bytes > 16384) return false;
    out->resize((unsigned)bytes);
    return WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text, (int)length, &(*out)[0], bytes, NULL, NULL) == bytes &&
           out->find('\0') == std::string::npos;
  }
  bool read_string(DWORD kind, std::wstring *text) const {
    LONG bytes = ImmGetCompositionStringW(context, kind, NULL, 0);
    if (bytes < 0 || bytes > 32768 || (bytes & 1)) return false;
    text->resize((unsigned)bytes / 2);
    if (!bytes) return true;
    return ImmGetCompositionStringW(context, kind, &(*text)[0], (DWORD)bytes) == bytes;
  }
  void refresh() {
    if (!context || !hwnd || !owner) return;
    XuTextInputSnapshot state; if (!snapshot(&state)) return;
    double geometry[8]={};
    if(xu_ui_text_input_query(id,owner->host.canvas_id,owner->canvas_generation,state.revision,3,0,0,0,0,geometry))
      memcpy(state.caret,geometry+4,sizeof(state.caret));
    if(!owner || !context || !hwnd) return;
    double scale = owner->device_scale;
    auto pixel = [](double value) -> LONG {
      return isfinite(value) ? (LONG)std::max(-1073741824.0, std::min(1073741824.0, floor(value))) : 0;
    };
    // The proxy's origin follows the logical caret in canvas backing pixels.
    LONG x = pixel(state.caret[0] * scale - owner->cam_x), y = pixel(state.caret[1] * scale - owner->cam_y);
    LONG width = std::max(1L, pixel(ceil(state.caret[2] * scale))), height = std::max(1L, pixel(ceil(state.caret[3] * scale)));
    SetWindowPos(hwnd, NULL, x, y, width, height, SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOREDRAW);
    COMPOSITIONFORM composition = {}; composition.dwStyle = CFS_POINT;
    ImmSetCompositionWindow(context, &composition);
    CANDIDATEFORM candidate = {}; candidate.dwStyle = CFS_EXCLUDE;
    candidate.ptCurrentPos.y = height; candidate.rcArea.right = width; candidate.rcArea.bottom = height;
    ImmSetCandidateWindow(context, &candidate);
  }
  bool commit(const std::string &text, unsigned repeat = 1) {
    if (!live() || !repeat || repeat > 16384 || text.size() * repeat > 16384) return false;
    std::string repeated; repeated.reserve(text.size() * repeat);
    for (unsigned i = 0; i < repeat; ++i) repeated += text;
    return xu_ui_text_input_commit(id, repeated.data(), (unsigned)repeated.size(), UINT_MAX, UINT_MAX) != 0;
  }
  bool character(WPARAM value, unsigned repeat, bool scalar = false) {
    if (scalar) {
      if (!value || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff) || high_surrogate) return false;
      wchar_t chars[2]; unsigned count = 1;
      if (value <= 0xffff) chars[0] = (wchar_t)value;
      else { value -= 0x10000; chars[0] = (wchar_t)(0xd800 + (value >> 10)); chars[1] = (wchar_t)(0xdc00 + (value & 1023)); count = 2; }
      std::string text; return utf8(chars, count, &text) && commit(text, repeat);
    }
    if (!value || value > 0xffff) return false;
    if (value >= 0xd800 && value <= 0xdbff) {
      if (high_surrogate || !repeat || repeat > 8192) return false;
      high_surrogate = (wchar_t)value; high_repeat = repeat; return true;
    }
    wchar_t chars[2] = {(wchar_t)value, 0}; unsigned count = 1;
    if (value >= 0xdc00 && value <= 0xdfff) {
      if (!high_surrogate || repeat != high_repeat) return false;
      chars[0] = high_surrogate; chars[1] = (wchar_t)value; count = 2; high_surrogate = 0;
    } else if (high_surrogate) return false;
    std::string text; return utf8(chars, count, &text) && commit(text, repeat);
  }
  bool composition(LPARAM flags) {
    if (!live()) return false;
    if (!flags) return xu_ui_text_input_cancel(id) != 0;
    if (flags & GCS_RESULTSTR) {
      std::wstring wide; std::string value;
      if (!read_string(GCS_RESULTSTR, &wide) || !utf8(wide.data(), (unsigned)wide.size(), &value) || !commit(value)) return false;
      result_handled = true;
    }
    if (flags & (GCS_COMPSTR | GCS_CURSORPOS | GCS_COMPATTR | GCS_COMPCLAUSE)) {
      std::wstring wide; std::string value, prefix;
      if (!read_string(GCS_COMPSTR, &wide)) return false;
      LONG cursor = wide.empty() ? 0 : ImmGetCompositionStringW(context, GCS_CURSORPOS, NULL, 0);
      if (cursor == IMM_ERROR_NODATA && !(flags & GCS_CURSORPOS)) cursor = (LONG)wide.size();
      if (cursor < 0 || (unsigned)cursor > wide.size() ||
          !utf8(wide.data(), (unsigned)wide.size(), &value) || !utf8(wide.data(), (unsigned)cursor, &prefix)) return false;
      return live() && xu_ui_text_input_compose(id, value.data(), (unsigned)value.size(), (unsigned)prefix.size(), (unsigned)prefix.size(), UINT_MAX, UINT_MAX) != 0;
    }
    return true;
  }
  static LRESULT CALLBACK procedure(HWND hwnd, UINT message, WPARAM wp, LPARAM lp) {
    if (message == WM_NCCREATE) {
      auto *client = (DrawTextInput *)((CREATESTRUCTW *)lp)->lpCreateParams;
      client->hwnd = hwnd; SetWindowLongPtrW(hwnd, GWLP_USERDATA, (LONG_PTR)client);
    }
    if (message == WM_NCHITTEST) return HTTRANSPARENT;
    if (message == WM_ERASEBKGND) return 1;
    if (message == WM_PAINT) { PAINTSTRUCT ps; BeginPaint(hwnd, &ps); EndPaint(hwnd, &ps); return 0; }
    // Focus loss is delivered after GetFocus already names another window.
    // Retire synchronously; a blur/refocus between polls must get a fresh HWND.
    if (message == WM_KILLFOCUS || message == WM_NCDESTROY) {
      auto *raw = (DrawTextInput *)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
      if (raw && raw->owner && raw->owner->text_input.get() == raw) {
        auto client = raw->owner->text_input;
        auto *p = client->owner; p->text_input.reset();
        client->detach(message == WM_NCDESTROY);
        xu_ui_text_input_cancel(client->id);
        // Moving between our native text proxy and its canvas is an internal
        // focus handoff, not a cancellation of the Screen or its open overlays.
        if (message == WM_NCDESTROY || !draw_focus_within_canvas(p, (HWND)wp)) cancel_input(p);
        if (message == WM_NCDESTROY) {
          xu_ui_text_input_stop(client->id, p->host.canvas_id, p->canvas_generation, XUTI_NATIVE_UNAVAILABLE);
          p->text_input_id = 0;
        }
        return message == WM_NCDESTROY ? DefWindowProcW(hwnd, message, wp, lp) : 0;
      }
    }
    auto client = retain(hwnd);
    if (!client) return DefWindowProcW(hwnd, message, wp, lp);
    auto *p = client->owner;
    if (message == WM_GETDLGCODE) return DLGC_WANTALLKEYS | DLGC_WANTCHARS;
    if (message == WM_IME_SETCONTEXT)
      return DefWindowProcW(hwnd, message, wp, lp & ~ISC_SHOWUICOMPOSITIONWINDOW);
    if (message == WM_KEYDOWN || message == WM_SYSKEYDOWN || message == WM_KEYUP || message == WM_SYSKEYUP) {
      bool down = message == WM_KEYDOWN || message == WM_SYSKEYDOWN;
      if (p->input_enabled) xu_ui_input_emit(&p->host, down ? XUI_KEY_DOWN : XUI_KEY_UP, 0, 0, 0, 0, 0, p->buttons,
        input_modifiers(), input_key(wp), (unsigned)(((lp >> 16) & 255) | (((lp >> 24) & 1) << 8)), down && ((lp >> 30) & 1));
      if (down && wp != VK_PROCESSKEY) client->result_handled = false;
      if (down) {
        XuTextInputSnapshot state;
        if (!client->snapshot(&state)) return 0;
        bool accepted = true, handled = false;
        unsigned modifiers = input_modifiers();
        if (wp == VK_ESCAPE) {
          accepted = xu_ui_text_input_cancel(client->id) != 0;
          ImmNotifyIME(client->context, NI_COMPOSITIONSTR, CPS_CANCEL, 0); handled = true;
        } else if (!state.composing() && !(modifiers & (4u | 8u))) {
          if (wp == 'A' && (modifiers & 2)) { accepted = xu_ui_text_input_select_all(client->id) != 0; handled = true; }
          else if (!(modifiers & 2) && (wp == VK_LEFT || wp == VK_RIGHT)) {
            accepted = xu_ui_text_input_move(client->id, wp == VK_LEFT, (modifiers & 1) != 0) != 0; handled = true;
          } else if (!(modifiers & 2) && wp == VK_DELETE) {
            accepted = xu_ui_text_input_erase_count(client->id, 0, std::min(16384u, std::max(1u, (unsigned)(lp & 0xffff)))) != 0; handled = true;
          }
        }
        if (!accepted) client->failed();
        if (handled) return 0;
      }
    }
    if (message == WM_CHAR || message == WM_IME_CHAR || message == WM_UNICHAR) {
      if (message == WM_UNICHAR && wp == UNICODE_NOCHAR) return TRUE;
      // Handling RESULTSTR and IME_CHAR here prevents DefWindowProc from
      // synthesizing a second WM_CHAR. Ordinary WM_CHAR is never guessed away.
      if (message == WM_IME_CHAR && client->result_handled) return 0;
      XuTextInputSnapshot state; if (!client->snapshot(&state)) return 0;
      bool accepted = true;
      unsigned repeat = std::max(1u, (unsigned)(lp & 0xffff));
      if (wp == '\b' && !state.composing()) accepted = xu_ui_text_input_erase_count(client->id, 1, std::min(16384u, repeat)) != 0;
      else if ((wp == '\r' || wp == '\n') && (state.flags & 1) && !state.composing()) accepted = client->commit("\n", repeat);
      else if (wp >= 32 && wp != 127) accepted = client->character(wp, repeat, message == WM_UNICHAR);
      if (!accepted) client->failed();
      return 0;
    }
    if (message == WM_IME_STARTCOMPOSITION) {
      client->result_handled = false;
      if (!xu_ui_text_input_compose(client->id, "", 0, 0, 0, UINT_MAX, UINT_MAX)) client->failed();
      client->refresh(); return 0;
    }
    if (message == WM_IME_COMPOSITION) {
      if (!client->composition(lp)) client->failed();
      return 0;
    }
    if (message == WM_IME_ENDCOMPOSITION) {
      if (!xu_ui_text_input_cancel(client->id)) client->failed();
      return 0;
    }
    if (message == WM_IME_REQUEST) return 0; // Reconversion requires layout/editor binding.
    return DefWindowProcW(hwnd, message, wp, lp);
  }
  bool install() {
    static bool registered = false;
    const wchar_t *name = L"XuTextInputProxy";
    if (!registered) {
      WNDCLASSW type = {}; type.lpfnWndProc = procedure; type.hInstance = GetModuleHandleW(NULL); type.lpszClassName = name;
      if (!RegisterClassW(&type) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) return false;
      registered = true;
    }
    context = ImmCreateContext(); if (!context) return false;
    hwnd = CreateWindowExW(WS_EX_TRANSPARENT, name, L"", WS_CHILD | WS_VISIBLE, 0, 0, 1, 1,
                          owner->hwnd, NULL, GetModuleHandleW(NULL), this);
    if (!hwnd) return false;
    previous = ImmAssociateContext(hwnd, context);
    HIMC associated = ImmGetContext(hwnd);
    bool valid = associated == context;
    if (associated) ImmReleaseContext(hwnd, associated);
    if (!valid) return false;
    if (previous) {
      DWORD conversion = 0, sentence = 0;
      if (ImmGetConversionStatus(previous, &conversion, &sentence)) ImmSetConversionStatus(context, conversion, sentence);
      ImmSetOpenStatus(context, ImmGetOpenStatus(previous));
    }
    refresh(); return true;
  }
};

static void draw_text_input_detach(XuContentPlugin *p) {
  auto client = p->text_input; p->text_input.reset(); p->text_input_id = 0;
  if (client) client->detach();
}
static void draw_text_input_blur(XuContentPlugin *p) {
  auto client = p->text_input; if (!client) return;
  p->text_input.reset(); client->detach(); xu_ui_text_input_cancel(client->id);
}
static void draw_text_input_focus(XuContentPlugin *p) {
  if (p->text_input || !p->hwnd || p->closing || !p->text_input_id || !xu_ui_text_input_active(p->text_input_id)) return;
  auto client = std::make_shared<DrawTextInput>(p, p->text_input_id); p->text_input = client;
  if (!client->install()) { client->failed(); draw_text_input_detach(p); return; }
  if (!client->retired && p->text_input == client) SetFocus(client->hwnd);
}
static void draw_text_input_grab_focus(XuContentPlugin *p) {
  if (p->text_input_id) {
    draw_text_input_focus(p);
    if (p->text_input) SetFocus(p->text_input->hwnd);
  } else if (p->hwnd) SetFocus(p->hwnd);
}
static int draw_text_input_command(XuContentPlugin *p, uint64_t id) {
  XuTextInputSnapshot state;
  if (!xu_text_input_read(id, p->host.canvas_id, p->canvas_generation, true, &state)) return 0;
  if (!p->hwnd || p->closing) { xu_ui_text_input_stop(id, p->host.canvas_id, p->canvas_generation, XUTI_NATIVE_UNAVAILABLE); return 1; }
  bool starting = p->text_input_id != id;
  if (starting) { draw_text_input_detach(p); p->text_input_id = id; }
  if (!xu_ui_text_input_activate(id, p->host.canvas_id, p->canvas_generation)) { draw_text_input_detach(p); return 1; }
  if (starting) draw_text_input_grab_focus(p);
  auto client = p->text_input; if (client) client->refresh();
  return 1;
}
static void draw_text_input_poll(XuContentPlugin *p) {
  if (p->text_input_id && !xu_ui_text_input_active(p->text_input_id)) draw_text_input_detach(p);
  if (p->text_input && GetFocus() != p->text_input->hwnd) draw_text_input_blur(p);
  if (GetFocus() == p->hwnd) draw_text_input_focus(p);
  auto client = p->text_input; if (client) client->refresh();
}
