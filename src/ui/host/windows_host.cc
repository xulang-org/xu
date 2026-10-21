// Xu UI Windows shell host (Win32 + GDI+) — shell.* aligned with macOS TMP protocol.

#include <windows.h>
#include "xu_ui_dpi.h"
#include <shellapi.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <shlwapi.h>
#include <gdiplus.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "xu_content_abi.h"
#include "xu_pack_assets.h"
#include "xu_ui_mem.h"
#include "xu_ui_commands.h"
#include "xu_ui_windows.h"
#include "xu_ui_requests.h"
#include "xu_draw_frame.h"
#include "windows_files.inc"

using namespace Gdiplus;

extern "C" {
const XuContentVTable *xu_webview_plugin_vtable(void) __attribute__((weak));
const XuContentVTable *xu_draw_plugin_vtable(void) __attribute__((weak));
}

static char g_tmp[1024];
static unsigned g_root_generation=0;
static bool g_root_closed=false;
static HWND g_hwnd = NULL;
static BOOL g_frameless = FALSE;
static BOOL g_transparent = FALSE;
static BOOL g_floating = FALSE;
static BOOL g_close_guard = FALSE;
static BOOL g_close_pending = FALSE;
static BOOL g_hidden = FALSE;
static BOOL g_titlebar_hidden = FALSE; // hide titlebar: drag top strip only (not whole client)
static BOOL g_fullscreen = FALSE;
static RECT g_fs_restore = {0, 0, 0, 0};
static int g_min_w = 0;
static int g_min_h = 0;
static int g_width = 800;
static int g_height = 560;
static ULONG_PTR g_gdiplus_token = 0;
static Bitmap *g_mask = NULL;
static BOOL g_mask_active = FALSE;
static BOOL g_quitting = FALSE;
static char g_last_title[512];
static char g_last_size[64];
static UINT_PTR g_timer = 0;
static XuContentPlugin *g_content = NULL;
static const XuContentVTable *g_content_vt = NULL;
static XuContentHost g_content_host;

enum {
  WM_XU_TRAY = WM_APP + 42,
  WM_XU_KICK_HOST = WM_APP + 43,
  TRAY_ICON_UID = 1,
  TRAY_MAX_ITEMS = 32,
  MENU_MAX_ITEMS = 32,
  MENU_ID_BASE = 5000,
  MENU_ID_DEVTOOLS = 5999,
  TITLEBAR_DRAG_PX = 28
};
static NOTIFYICONDATAW g_nid;
static BOOL g_tray_added = FALSE;
static HICON g_tray_icon = NULL;
static HICON g_app_icon_big = NULL;
static HICON g_app_icon_sm = NULL;
static BOOL g_app_icon_owned = FALSE; // DestroyIcon only when we created them
static char g_app_icon_sig[520];
static char g_tray_ids[TRAY_MAX_ITEMS][64];
static char g_tray_labels[TRAY_MAX_ITEMS][256];
static int g_tray_n = 0;
static char g_tray_sig[512]; // tip+items fingerprint to avoid rebuild spam
static UINT g_taskbar_created = 0; // RegisterWindowMessageW(L"TaskbarCreated")
static HMENU g_app_menu = NULL;
static char g_menu_ids[MENU_MAX_ITEMS][64];
static int g_menu_n = 0;
static char g_menu_sig[512];
static char g_last_shot_path[1200];
static HICON g_badge_icon = NULL;

static void request_close(void);
static void drain_title_size(void);
static void append_shell_event(const char *payload);
static void read_trim_file(const char *name, char *out, size_t n);
static void read_file_raw(const char *name, char *out, size_t n);
static void write_tmp(const char *name, const char *body);
static void utf8_to_wide(const char *src, wchar_t *dst, int dstn);
static Bitmap *bitmap_from_pack(const char *path_utf8);

static void host_trace(const char *step) {
  const char *p = getenv("XU_PACK_TRACE");
  if (p && p[0]) {
    FILE *f = fopen(p, "a");
    if (f) {
      fprintf(f, "host: %s\n", step);
      fclose(f);
    }
  }
  const char *logp = getenv("XU_UI_LOG");
  if (logp && logp[0]) {
    FILE *f = fopen(logp, "a");
    if (f) {
      fprintf(f, "host: %s\r\n", step);
      fclose(f);
    }
  }
  if (g_tmp[0]) {
    char path[1200];
    snprintf(path, sizeof(path), "%s/xu_host_trace.txt", g_tmp);
    FILE *f = fopen(path, "a");
    if (!f) {
      snprintf(path, sizeof(path), "%s\\xu_host_trace.txt", g_tmp);
      f = fopen(path, "a");
    }
    if (f) {
      fprintf(f, "%s\n", step);
      fclose(f);
    }
  }
  fprintf(stderr, "xu_ui_host: %s\n", step);
  fflush(stderr);
}

static void path_join(char *out, size_t n, const char *name) {
  if (g_tmp[0])
    snprintf(out, n, "%s/%s", g_tmp, name);
  else
    snprintf(out, n, "%s", name);
}

static void write_tmp(const char *name, const char *body) {
  // Always prefer in-process mailbox (pack has no xu_ui_* TEMP dir).
  xu_ui_mem_set(name, body ? body : "");
  if (!g_tmp[0]) return;
  char path[1200];
  path_join(path, sizeof(path), name);
  FILE *f = fopen(path, "wb");
  if (!f) {
    snprintf(path, sizeof(path), "%s\\%s", g_tmp, name);
    f = fopen(path, "wb");
  }
  if (!f) return;
  fputs(body ? body : "", f);
  fclose(f);
}

static void append_shell_event(const char *payload) {
  xu_ui_window_event(1,(payload && strcmp(payload,"ready") && strcmp(payload,"exit"))?g_root_generation:0,payload?payload:"");
  if (!g_tmp[0]) return;
  char path[1200];
  path_join(path, sizeof(path), "xu_ui_shell_event.txt");
  FILE *f = fopen(path, "ab");
  if (!f) {
    snprintf(path, sizeof(path), "%s\\xu_ui_shell_event.txt", g_tmp);
    f = fopen(path, "ab");
  }
  if (!f) return;
  fprintf(f, "%s\n", payload);
  fclose(f);
}

static void read_trim_file(const char *name, char *out, size_t n) {
  out[0] = 0;
  if (xu_ui_mem_get(name, out, (unsigned)n) >= 0) {
    size_t L = strlen(out);
    while (L > 0 && (out[L - 1] == '\n' || out[L - 1] == '\r' || out[L - 1] == ' ')) {
      out[--L] = 0;
    }
    return;
  }
  if (!g_tmp[0]) return;
  char path[1200];
  path_join(path, sizeof(path), name);
  FILE *f = fopen(path, "r");
  if (!f) {
    snprintf(path, sizeof(path), "%s\\%s", g_tmp, name);
    f = fopen(path, "r");
  }
  if (!f) return;
  if (!fgets(out, (int)n, f)) {
    fclose(f);
    return;
  }
  fclose(f);
  size_t L = strlen(out);
  while (L > 0 && (out[L - 1] == '\n' || out[L - 1] == '\r' || out[L - 1] == ' ')) {
    out[--L] = 0;
  }
}

static void read_file_raw(const char *name, char *out, size_t n) {
  out[0] = 0;
  if (xu_ui_mem_get(name, out, (unsigned)n) >= 0) return;
  if (!g_tmp[0]) return;
  char path[1200];
  path_join(path, sizeof(path), name);
  FILE *f = fopen(path, "r");
  if (!f) {
    snprintf(path, sizeof(path), "%s\\%s", g_tmp, name);
    f = fopen(path, "r");
  }
  if (!f) return;
  size_t got = fread(out, 1, n - 1, f);
  fclose(f);
  out[got] = 0;
}

static void utf8_to_wide(const char *src, wchar_t *dst, int dstn) {
  MultiByteToWideChar(CP_UTF8, 0, src, -1, dst, dstn);
}

static void wide_to_utf8(const wchar_t *src, char *dst, int dstn) {
  WideCharToMultiByte(CP_UTF8, 0, src, -1, dst, dstn, NULL, NULL);
}

static void apply_frameless(BOOL on) {
  g_frameless = on;
  if (!g_hwnd) return;
  LONG_PTR style = GetWindowLongPtr(g_hwnd, GWL_STYLE);
  if (on) {
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU);
    style |= WS_POPUP;
  } else {
    style &= ~WS_POPUP;
    style |= WS_OVERLAPPEDWINDOW;
  }
  SetWindowLongPtr(g_hwnd, GWL_STYLE, style);
  SetWindowPos(g_hwnd, NULL, 0, 0, 0, 0,
               SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED);
}

static void apply_transparent(BOOL on) {
  g_transparent = on;
  if (!g_hwnd || g_mask_active) return;
  LONG_PTR ex = GetWindowLongPtr(g_hwnd, GWL_EXSTYLE);
  if (on) {
    SetWindowLongPtr(g_hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED);
    SetLayeredWindowAttributes(g_hwnd, 0, 230, LWA_ALPHA);
  } else {
    SetWindowLongPtr(g_hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED);
  }
}

static void paint_mask_layered(void) {
  if (!g_hwnd || !g_mask) return;
  int mw = (int)g_mask->GetWidth();
  int mh = (int)g_mask->GetHeight();
  if (mw <= 0 || mh <= 0) return;

  RECT rc;
  GetWindowRect(g_hwnd, &rc);
  int ww = rc.right - rc.left;
  int wh = rc.bottom - rc.top;
  if (ww <= 0) ww = g_width;
  if (wh <= 0) wh = g_height;

  HDC screen = GetDC(NULL);
  HDC mem = CreateCompatibleDC(screen);
  BITMAPINFO bmi;
  ZeroMemory(&bmi, sizeof(bmi));
  bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
  bmi.bmiHeader.biWidth = ww;
  bmi.bmiHeader.biHeight = -wh;
  bmi.bmiHeader.biPlanes = 1;
  bmi.bmiHeader.biBitCount = 32;
  bmi.bmiHeader.biCompression = BI_RGB;
  void *bits = NULL;
  HBITMAP dib = CreateDIBSection(mem, &bmi, DIB_RGB_COLORS, &bits, NULL, 0);
  if (!dib) {
    DeleteDC(mem);
    ReleaseDC(NULL, screen);
    return;
  }
  HGDIOBJ old = SelectObject(mem, dib);

  Graphics g(mem);
  g.SetInterpolationMode(InterpolationModeHighQualityBicubic);
  g.Clear(Color(0, 0, 0, 0));
  g.DrawImage(g_mask, 0, 0, ww, wh);

  POINT ptSrc = {0, 0};
  POINT ptPos = {rc.left, rc.top};
  SIZE sizeWnd = {ww, wh};
  BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
  UpdateLayeredWindow(g_hwnd, screen, &ptPos, &sizeWnd, mem, &ptSrc, 0, &blend, ULW_ALPHA);

  SelectObject(mem, old);
  DeleteObject(dib);
  DeleteDC(mem);
  ReleaseDC(NULL, screen);
}

static IStream *g_mask_stream = NULL;

static Bitmap *bitmap_from_pack(const char *path_utf8) {
  const unsigned char *p = NULL;
  unsigned n = 0;
  IStream *st = NULL;
  HGLOBAL h = NULL;
  void *locked = NULL;
  Bitmap *nb = NULL;
  if (!xu_pack_file_for_path(path_utf8, &p, &n) || !p || !n) return NULL;
  // Copy into an HGLOBAL-backed stream. GDI+ may keep reading the stream for
  // the Bitmap lifetime — releasing early yields an empty (fully transparent)
  // layered window.
  h = GlobalAlloc(GMEM_MOVEABLE, n);
  if (!h) return NULL;
  locked = GlobalLock(h);
  if (!locked) {
    GlobalFree(h);
    return NULL;
  }
  memcpy(locked, p, n);
  GlobalUnlock(h);
  if (FAILED(CreateStreamOnHGlobal(h, TRUE, &st)) || !st) {
    GlobalFree(h);
    return NULL;
  }
  nb = Bitmap::FromStream(st, FALSE);
  if (!nb || nb->GetLastStatus() != Ok) {
    delete nb;
    st->Release();
    return NULL;
  }
  // Transfer stream ownership to apply_mask via g_mask_stream.
  if (g_mask_stream) {
    g_mask_stream->Release();
    g_mask_stream = NULL;
  }
  g_mask_stream = st;
  return nb;
}

static void apply_mask(const char *path_utf8) {
  if (!path_utf8 || !path_utf8[0]) return;
  wchar_t wpath[1024];
  utf8_to_wide(path_utf8, wpath, 1024);
  Bitmap *nb = NULL;
  // Prefer in-PE pack when XU_UI_PACK=1 (TEMP has no brand/ tree).
  const char *pack = getenv("XU_UI_PACK");
  if (pack && pack[0] == '1') {
    nb = bitmap_from_pack(path_utf8);
  }
  if (!nb) {
    nb = Bitmap::FromFile(wpath, FALSE);
    if (!nb || nb->GetLastStatus() != Ok) {
      delete nb;
      nb = bitmap_from_pack(path_utf8);
    } else if (g_mask_stream) {
      g_mask_stream->Release();
      g_mask_stream = NULL;
    }
  }
  if (!nb) {
    append_shell_event("mask_failed");
    host_trace("mask_failed");
    fprintf(stderr, "xu_ui_host: mask_failed path=%s\n", path_utf8);
    fflush(stderr);
    return;
  }
  if (g_mask_stream) {
    g_mask_stream->Release();
    g_mask_stream = NULL;
  }
  delete g_mask;
  g_mask = nb;
  g_mask_active = TRUE;
  if (!g_frameless) apply_frameless(TRUE);
  // SetLayeredWindowAttributes and UpdateLayeredWindow are mutually exclusive.
  // Clear layered bit first so UpdateLayeredWindow can take over (otherwise the
  // shaped window stays fully invisible).
  LONG_PTR ex = GetWindowLongPtr(g_hwnd, GWL_EXSTYLE);
  SetWindowLongPtr(g_hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED);
  SetWindowLongPtr(g_hwnd, GWL_EXSTYLE, (ex & ~WS_EX_LAYERED) | WS_EX_LAYERED);
  {
    char msg[128];
    snprintf(msg, sizeof(msg), "mask ok %ux%u", (unsigned)g_mask->GetWidth(),
             (unsigned)g_mask->GetHeight());
    host_trace(msg);
  }
  paint_mask_layered();
}

static void clear_mask(void) {
  delete g_mask;
  g_mask = NULL;
  g_mask_active = FALSE;
  if (g_mask_stream) {
    g_mask_stream->Release();
    g_mask_stream = NULL;
  }
  if (g_hwnd) {
    LONG_PTR ex = GetWindowLongPtr(g_hwnd, GWL_EXSTYLE);
    if (g_transparent) {
      SetWindowLongPtr(g_hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED);
      SetLayeredWindowAttributes(g_hwnd, 0, 230, LWA_ALPHA);
    } else {
      SetWindowLongPtr(g_hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED);
    }
    InvalidateRect(g_hwnd, NULL, TRUE);
  }
}

static void tray_remove(void) {
  if (g_tray_added) {
    Shell_NotifyIconW(NIM_DELETE, &g_nid);
    g_tray_added = FALSE;
  }
  if (g_tray_icon) {
    DestroyIcon(g_tray_icon);
    g_tray_icon = NULL;
  }
  g_tray_n = 0;
  g_tray_sig[0] = 0;
  for (int i = 0; i < TRAY_MAX_ITEMS; i++) {
    g_tray_ids[i][0] = 0;
    g_tray_labels[i][0] = 0;
  }
}

/* Build HICON via CreateIconIndirect. GDI+ Bitmap::GetHICON from ARGB PNG often
 * yields a tray-invisible icon on Win10/11 (Explorer treats the mask poorly). */
static HICON hicon_from_argb_bits(int dw, int dh, const BYTE *bgra, int stride) {
  if (!bgra || dw < 1 || dh < 1) return NULL;
  BITMAPINFO bi;
  ZeroMemory(&bi, sizeof(bi));
  bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
  bi.bmiHeader.biWidth = dw;
  bi.bmiHeader.biHeight = -dh; // top-down
  bi.bmiHeader.biPlanes = 1;
  bi.bmiHeader.biBitCount = 32;
  bi.bmiHeader.biCompression = BI_RGB;
  void *color_bits = NULL;
  HDC screen = GetDC(NULL);
  HBITMAP color = CreateDIBSection(screen, &bi, DIB_RGB_COLORS, &color_bits, NULL, 0);
  if (!color || !color_bits) {
    if (color) DeleteObject(color);
    ReleaseDC(NULL, screen);
    return NULL;
  }
  for (int y = 0; y < dh; y++) {
    memcpy((BYTE *)color_bits + (size_t)y * dw * 4, bgra + (size_t)y * stride, (size_t)dw * 4);
  }

  // Monochrome AND mask: 1 = transparent. Row stride DWORD-aligned.
  int mask_stride = ((dw + 31) / 32) * 4;
  size_t mask_bytes = (size_t)mask_stride * (size_t)dh;
  BYTE *mask_bits = (BYTE *)calloc(1, mask_bytes);
  if (!mask_bits) {
    DeleteObject(color);
    ReleaseDC(NULL, screen);
    return NULL;
  }
  for (int y = 0; y < dh; y++) {
    const BYTE *row = bgra + (size_t)y * stride;
    BYTE *mout = mask_bits + (size_t)y * mask_stride;
    for (int x = 0; x < dw; x++) {
      BYTE a = row[x * 4 + 3];
      if (a < 16) mout[x / 8] |= (BYTE)(0x80 >> (x % 8));
    }
  }
  HBITMAP mask = CreateBitmap(dw, dh, 1, 1, mask_bits);
  free(mask_bits);
  if (!mask) {
    DeleteObject(color);
    ReleaseDC(NULL, screen);
    return NULL;
  }

  ICONINFO ii;
  ZeroMemory(&ii, sizeof(ii));
  ii.fIcon = TRUE;
  ii.hbmMask = mask;
  ii.hbmColor = color;
  HICON icon = CreateIconIndirect(&ii);
  DeleteObject(mask);
  DeleteObject(color);
  ReleaseDC(NULL, screen);
  return icon;
}

static HICON hicon_from_bitmap_sized(Bitmap *bm, int dw, int dh) {
  if (!bm || bm->GetLastStatus() != Ok || dw < 1 || dh < 1) return NULL;
  Bitmap *scaled = new Bitmap(dw, dh, PixelFormat32bppARGB);
  if (!scaled || scaled->GetLastStatus() != Ok) {
    delete scaled;
    return NULL;
  }
  {
    Graphics g(scaled);
    g.SetInterpolationMode(InterpolationModeHighQualityBicubic);
    g.SetPixelOffsetMode(PixelOffsetModeHighQuality);
    g.SetCompositingMode(CompositingModeSourceCopy);
    g.Clear(Color(0, 0, 0, 0));
    g.DrawImage(bm, Rect(0, 0, dw, dh));
  }
  BitmapData bd;
  ZeroMemory(&bd, sizeof(bd));
  Rect lock(0, 0, dw, dh);
  if (scaled->LockBits(&lock, ImageLockModeRead, PixelFormat32bppARGB, &bd) != Ok) {
    delete scaled;
    return NULL;
  }
  HICON icon = hicon_from_argb_bits(dw, dh, (const BYTE *)bd.Scan0, bd.Stride);
  scaled->UnlockBits(&bd);
  delete scaled;
  return icon;
}

/* Scale ARGB bitmap to SM_CXSMICON and convert to HICON (does not touch g_mask_stream). */
static HICON hicon_from_bitmap(Bitmap *bm) {
  const int tw = GetSystemMetrics(SM_CXSMICON);
  const int th = GetSystemMetrics(SM_CYSMICON);
  return hicon_from_bitmap_sized(bm, tw > 0 ? tw : 16, th > 0 ? th : 16);
}

/* Classic .ico (BMP or PNG entries) → HICON via CreateIconFromResourceEx. */
static HICON hicon_from_ico_bytes_sized(const unsigned char *p, unsigned n, int cx, int cy) {
  if (!p || n < 22 || cx < 1 || cy < 1) return NULL;
  WORD type = *(const WORD *)(p + 2);
  WORD count = *(const WORD *)(p + 4);
  if (type != 1 || count == 0) return NULL;
  if (6u + (unsigned)count * 16u > n) return NULL;

  int best = -1;
  int best_score = 0x7fffffff;
  for (WORD i = 0; i < count; i++) {
    const unsigned char *e = p + 6 + (unsigned)i * 16;
    int w = e[0] ? (int)e[0] : 256;
    int h = e[1] ? (int)e[1] : 256;
    DWORD bytes = *(const DWORD *)(e + 8);
    DWORD off = *(const DWORD *)(e + 12);
    if (off >= n || bytes == 0 || off + bytes > n) continue;
    int score = abs(w - cx) + abs(h - cy);
    if (score < best_score) {
      best_score = score;
      best = (int)i;
    }
  }
  if (best < 0) return NULL;
  const unsigned char *e = p + 6 + (unsigned)best * 16;
  DWORD bytes = *(const DWORD *)(e + 8);
  DWORD off = *(const DWORD *)(e + 12);
  return CreateIconFromResourceEx((PBYTE)(p + off), bytes, TRUE, 0x00030000, cx, cy,
                                  LR_DEFAULTCOLOR);
}

static HICON hicon_from_ico_bytes(const unsigned char *p, unsigned n) {
  const int tw = GetSystemMetrics(SM_CXSMICON);
  const int th = GetSystemMetrics(SM_CYSMICON);
  return hicon_from_ico_bytes_sized(p, n, tw > 0 ? tw : 16, th > 0 ? th : 16);
}

/* In-PE pack PNG → HICON. Own stream lifetime; never use bitmap_from_pack (mask). */
static HICON hicon_from_png_bytes_sized(const unsigned char *p, unsigned n, int cx, int cy) {
  if (!p || !n) return NULL;
  HGLOBAL h = GlobalAlloc(GMEM_MOVEABLE, n);
  if (!h) return NULL;
  void *locked = GlobalLock(h);
  if (!locked) {
    GlobalFree(h);
    return NULL;
  }
  memcpy(locked, p, n);
  GlobalUnlock(h);
  IStream *st = NULL;
  if (FAILED(CreateStreamOnHGlobal(h, TRUE, &st)) || !st) {
    GlobalFree(h);
    return NULL;
  }
  Bitmap *bm = Bitmap::FromStream(st, FALSE);
  HICON icon = NULL;
  if (bm && bm->GetLastStatus() == Ok) icon = hicon_from_bitmap_sized(bm, cx, cy);
  delete bm;
  st->Release();
  return icon;
}

static HICON hicon_from_png_bytes(const unsigned char *p, unsigned n) {
  const int tw = GetSystemMetrics(SM_CXSMICON);
  const int th = GetSystemMetrics(SM_CYSMICON);
  return hicon_from_png_bytes_sized(p, n, tw > 0 ? tw : 16, th > 0 ? th : 16);
}

static HICON hicon_from_file_path_sized(const char *path_utf8, int cx, int cy) {
  if (!path_utf8 || !path_utf8[0]) return NULL;
  wchar_t wpath[1024];
  utf8_to_wide(path_utf8, wpath, 1024);
  size_t len = strlen(path_utf8);
  if (len >= 4) {
    const char *ext = path_utf8 + len - 4;
    if (_stricmp(ext, ".ico") == 0) {
      HICON icon = (HICON)LoadImageW(NULL, wpath, IMAGE_ICON, cx, cy, LR_LOADFROMFILE);
      if (icon) return icon;
    }
  }
  Bitmap *bm = Bitmap::FromFile(wpath, FALSE);
  if (!bm || bm->GetLastStatus() != Ok) {
    delete bm;
    return NULL;
  }
  HICON icon = hicon_from_bitmap_sized(bm, cx, cy);
  delete bm;
  return icon;
}

static HICON hicon_from_file_path(const char *path_utf8) {
  const int tw = GetSystemMetrics(SM_CXSMICON);
  const int th = GetSystemMetrics(SM_CYSMICON);
  return hicon_from_file_path_sized(path_utf8, tw > 0 ? tw : 16, th > 0 ? th : 16);
}

/* Load big/small HICONs for window + taskbar (align mac applyAppIcon). */
static HICON load_app_icon_one(const char *icon_path_file, int cx, int cy) {
  if (icon_path_file && icon_path_file[0]) {
    HICON icon = hicon_from_file_path_sized(icon_path_file, cx, cy);
    if (icon) return icon;
  }
  {
    const unsigned char *p = NULL;
    unsigned n = 0;
    if (xu_pack_get_icon_ico(&p, &n) && p && n) {
      HICON icon = hicon_from_ico_bytes_sized(p, n, cx, cy);
      if (icon) return icon;
    }
  }
  {
    const unsigned char *p = NULL;
    unsigned n = 0;
    if (xu_pack_icon(&p, &n) && p && n) {
      HICON icon = hicon_from_png_bytes_sized(p, n, cx, cy);
      if (icon) return icon;
    }
  }
  if (g_tmp[0]) {
    char path[1200];
    snprintf(path, sizeof(path), "%s\\brand\\xu_app_logo.ico", g_tmp);
    HICON icon = hicon_from_file_path_sized(path, cx, cy);
    if (icon) return icon;
    snprintf(path, sizeof(path), "%s\\brand\\xu_app_icon.ico", g_tmp);
    icon = hicon_from_file_path_sized(path, cx, cy);
    if (icon) return icon;
    snprintf(path, sizeof(path), "%s\\brand\\xu_app_logo.png", g_tmp);
    icon = hicon_from_file_path_sized(path, cx, cy);
    if (icon) return icon;
    snprintf(path, sizeof(path), "%s\\brand\\xu_app_icon.png", g_tmp);
    icon = hicon_from_file_path_sized(path, cx, cy);
    if (icon) return icon;
  }
  return NULL;
}

#ifndef IDI_XUAPP
#define IDI_XUAPP 101
#endif

static void apply_app_icon(void) {
  if (!g_hwnd) return;
  char path_file[1024];
  read_trim_file("xu_ui_app_icon.txt", path_file, sizeof(path_file));
  char sig[520];
  snprintf(sig, sizeof(sig), "%s", path_file);
  if (g_app_icon_big && strcmp(sig, g_app_icon_sig) == 0) return;

  int cx_big = GetSystemMetrics(SM_CXICON);
  int cy_big = GetSystemMetrics(SM_CYICON);
  int cx_sm = GetSystemMetrics(SM_CXSMICON);
  int cy_sm = GetSystemMetrics(SM_CYSMICON);
  if (cx_big < 1) cx_big = 32;
  if (cy_big < 1) cy_big = 32;
  if (cx_sm < 1) cx_sm = 16;
  if (cy_sm < 1) cy_sm = 16;

  HICON big = load_app_icon_one(path_file, cx_big, cy_big);
  HICON sm = load_app_icon_one(path_file, cx_sm, cy_sm);

  // PE resource fallback (windres IDI_XUAPP). LoadImage without LR_SHARED → we own.
  if (!big || !sm) {
    HINSTANCE hi = GetModuleHandleW(NULL);
    if (!big) {
      big = (HICON)LoadImageW(hi, MAKEINTRESOURCEW(IDI_XUAPP), IMAGE_ICON, cx_big, cy_big, 0);
    }
    if (!sm) {
      sm = (HICON)LoadImageW(hi, MAKEINTRESOURCEW(IDI_XUAPP), IMAGE_ICON, cx_sm, cy_sm, 0);
    }
  }
  if (!big && !sm) {
    host_trace("app icon: none loaded");
    return;
  }
  if (!sm) sm = big;
  if (!big) big = sm;

  if (g_app_icon_owned) {
    if (g_app_icon_big && g_app_icon_big != g_app_icon_sm) DestroyIcon(g_app_icon_big);
    if (g_app_icon_sm) DestroyIcon(g_app_icon_sm);
  }
  g_app_icon_big = big;
  g_app_icon_sm = sm;
  g_app_icon_owned = TRUE;

  SendMessageW(g_hwnd, WM_SETICON, ICON_BIG, (LPARAM)big);
  SendMessageW(g_hwnd, WM_SETICON, ICON_SMALL, (LPARAM)sm);
  SetClassLongPtrW(g_hwnd, GCLP_HICON, (LONG_PTR)big);
  SetClassLongPtrW(g_hwnd, GCLP_HICONSM, (LONG_PTR)sm);
  snprintf(g_app_icon_sig, sizeof(g_app_icon_sig), "%s", sig);
  // Tray may have installed earlier with a fallback glyph — refresh to match.
  g_tray_sig[0] = 0;
  host_trace("app icon: applied");
}

static HICON tray_load_icon(const char *icon_path_file) {
  const int tw = GetSystemMetrics(SM_CXSMICON);
  const int th = GetSystemMetrics(SM_CYSMICON);
  int cx = tw > 0 ? tw : 16;
  int cy = th > 0 ? th : 16;

  // Prefer the same PE ICON resource that already works for the window/taskbar.
  // CreateIconFromResourceEx on the in-memory PNG-in-ICO blob often yields a
  // tray HICON that NIM_ADD accepts but Explorer draws as the wrong/blank glyph.
  {
    HINSTANCE hi = GetModuleHandleW(NULL);
    HICON pe = (HICON)LoadImageW(hi, MAKEINTRESOURCEW(IDI_XUAPP), IMAGE_ICON, cx, cy, 0);
    if (pe) {
      host_trace("tray icon: from PE IDI_XUAPP");
      return pe;
    }
  }

  // Reuse the small app icon we already applied (CopyIcon → we own the handle).
  if (g_app_icon_sm) {
    HICON copied = CopyIcon(g_app_icon_sm);
    if (copied) {
      host_trace("tray icon: CopyIcon(app small)");
      return copied;
    }
  }

  // Explicit tray path, then app icon path, then pack blobs.
  char app_path[1024];
  app_path[0] = 0;
  read_trim_file("xu_ui_app_icon.txt", app_path, sizeof(app_path));
  if (icon_path_file && icon_path_file[0]) {
    HICON icon = load_app_icon_one(icon_path_file, cx, cy);
    if (icon) {
      host_trace("tray icon: from tray path / pack");
      return icon;
    }
  }
  if (app_path[0]) {
    HICON icon = load_app_icon_one(app_path, cx, cy);
    if (icon) {
      host_trace("tray icon: from app icon path / pack");
      return icon;
    }
  }
  {
    HICON icon = load_app_icon_one("", cx, cy);
    if (icon) {
      host_trace("tray icon: from pack fallback");
      return icon;
    }
  }
  host_trace("tray icon: all custom sources failed");
  return NULL;
}

static void post_menu_invoke(const char *id) {
  if (!id || !id[0]) return;
  char pending[32];
  read_trim_file("xu_ui_ipc_req.txt", pending, sizeof(pending));
  if (!pending[0]) {
    char body[640];
    snprintf(body, sizeof(body), "name: menu\npayload: %s\n", id);
    write_tmp("xu_ui_ipc_req.txt", body);
  }
  char ev[320];
  snprintf(ev, sizeof(ev), "menu_clicked\t%s", id);
  append_shell_event(ev);
}

static void menu_on_command(const char *id) {
  if (!id || !id[0]) return;
  if (strcmp(id, "quit") == 0) {
    post_menu_invoke(id);
    request_close();
    return;
  }
  if (strcmp(id, "about") == 0) {
    MessageBoxW(g_hwnd, L"Xu WebView UI", L"About Xu", MB_OK | MB_ICONINFORMATION);
  }
  post_menu_invoke(id);
}

static SIZE outer_size_for_client(int width,int height,DWORD style,DWORD ex,BOOL has_menu,HWND window=NULL) {
  return xu_ui_outer_for_client(window,width,height,style,ex,has_menu);
}

static void resize_to_client(int width, int height, UINT flags = 0) {
  if (!g_hwnd) return;
  SIZE size = outer_size_for_client(width, height,
      (DWORD)GetWindowLongPtr(g_hwnd, GWL_STYLE),
      (DWORD)GetWindowLongPtr(g_hwnd, GWL_EXSTYLE), GetMenu(g_hwnd) != NULL,g_hwnd);
  SetWindowPos(g_hwnd, NULL, 0, 0, size.cx, size.cy,
               SWP_NOMOVE | SWP_NOZORDER | flags);
}

static void menu_install_or_update(void) {
  if (!g_hwnd) return;
  char visible[16];
  read_trim_file("xu_ui_menu_visible.txt", visible, sizeof(visible));
  if (visible[0] == '0') {
    if (g_app_menu) {
      SetMenu(g_hwnd, NULL);
      DestroyMenu(g_app_menu);
      g_app_menu = NULL;
      g_menu_n = 0;
      g_menu_sig[0] = 0;
      DrawMenuBar(g_hwnd);
      resize_to_client(g_width, g_height);
    }
    return;
  }
  char items[4096];
  read_file_raw("xu_ui_menu.txt", items, sizeof(items));
  char sig[512];
  snprintf(sig, sizeof(sig), "%s", items);
  if (g_app_menu && strcmp(sig, g_menu_sig) == 0) return;

  if (g_app_menu) {
    SetMenu(g_hwnd, NULL);
    DestroyMenu(g_app_menu);
    g_app_menu = NULL;
  }
  g_menu_n = 0;
  g_menu_sig[0] = 0;

  HMENU menubar = CreateMenu();
  HMENU app = CreatePopupMenu();
  if (!menubar || !app) {
    if (menubar) DestroyMenu(menubar);
    if (app) DestroyMenu(app);
    return;
  }

  if (!items[0]) {
    AppendMenuW(app, MF_STRING, MENU_ID_BASE + 0, L"About");
    snprintf(g_menu_ids[0], sizeof(g_menu_ids[0]), "about");
    AppendMenuW(app, MF_SEPARATOR, 0, NULL);
    AppendMenuW(app, MF_STRING, MENU_ID_BASE + 1, L"Quit");
    snprintf(g_menu_ids[1], sizeof(g_menu_ids[1]), "quit");
    g_menu_n = 2;
  } else {
    char *p = items;
    while (*p && g_menu_n < MENU_MAX_ITEMS) {
      char *line = p;
      while (*p && *p != '\n' && *p != '\r') p++;
      char save = *p;
      if (*p) {
        *p = 0;
        p++;
        if (save == '\r' && *p == '\n') p++;
      }
      while (*line == ' ') line++;
      if (!line[0]) continue;
      char *tab = strchr(line, '\t');
      const char *label = (tab && tab[1]) ? tab + 1 : line;
      if (tab) *tab = 0;
      snprintf(g_menu_ids[g_menu_n], sizeof(g_menu_ids[0]), "%s", line);
      wchar_t wlabel[256];
      utf8_to_wide(label, wlabel, 256);
      AppendMenuW(app, MF_STRING, (UINT)(MENU_ID_BASE + g_menu_n), wlabel);
      g_menu_n++;
    }
  }

  AppendMenuW(menubar, MF_POPUP, (UINT_PTR)app, L"Xu");
  HMENU view = CreatePopupMenu();
  if (view) {
    AppendMenuW(view, MF_STRING, MENU_ID_DEVTOOLS, L"Developer Tools");
    AppendMenuW(menubar, MF_POPUP, (UINT_PTR)view, L"View");
  }
  SetMenu(g_hwnd, menubar);
  DrawMenuBar(g_hwnd);
  resize_to_client(g_width, g_height);
  g_app_menu = menubar;
  snprintf(g_menu_sig, sizeof(g_menu_sig), "%s", sig);
}

static void apply_appearance(const char *mode) {
  if (!g_hwnd || !mode) return;
  BOOL dark = (_stricmp(mode, "dark") == 0);
  // DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win10 1903+)
  BOOL val = dark ? TRUE : FALSE;
  HMODULE dwm = LoadLibraryA("dwmapi.dll");
  if (dwm) {
    typedef HRESULT(WINAPI *DwmSetWindowAttributeFn)(HWND, DWORD, LPCVOID, DWORD);
    auto fn = (DwmSetWindowAttributeFn)GetProcAddress(dwm, "DwmSetWindowAttribute");
    if (fn) {
      fn(g_hwnd, 20, &val, sizeof(val));
    }
    FreeLibrary(dwm);
  }
}

static void add_round_rect(GraphicsPath *path, REAL x, REAL y, REAL w, REAL h, REAL rad) {
  if (w < 1 || h < 1) return;
  if (rad > w / 2) rad = w / 2;
  if (rad > h / 2) rad = h / 2;
  REAL d = rad * 2;
  path->AddArc(x, y, d, d, 180, 90);
  path->AddArc(x + w - d, y, d, d, 270, 90);
  path->AddArc(x + w - d, y + h - d, d, d, 0, 90);
  path->AddArc(x, y + h - d, d, d, 90, 90);
  path->CloseFigure();
}

/* macOS Dock badge: systemRed pill, white type, white hairline. Overlay IS the badge. */
static HICON hicon_macos_badge(const wchar_t *wtext) {
  int sm = GetSystemMetrics(SM_CXSMICON);
  if (sm < 16) sm = 16;
  const int sz = sm * 2;
  Bitmap bmp(sz, sz, PixelFormat32bppARGB);
  if (bmp.GetLastStatus() != Ok) return NULL;
  Graphics g(&bmp);
  g.SetSmoothingMode(SmoothingModeAntiAlias);
  g.SetInterpolationMode(InterpolationModeHighQualityBicubic);
  g.SetPixelOffsetMode(PixelOffsetModeHighQuality);
  g.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);
  g.Clear(Color(0, 0, 0, 0));

  FontFamily family(L"Segoe UI");
  const FontFamily *ff = (family.GetLastStatus() == Ok) ? &family : FontFamily::GenericSansSerif();
  REAL fontPx = (REAL)(sz * 42 / 100);
  if (fontPx < 11) fontPx = 11;
  Font font(ff, fontPx, FontStyleBold, UnitPixel);
  StringFormat fmt;
  fmt.SetAlignment(StringAlignmentCenter);
  fmt.SetLineAlignment(StringAlignmentCenter);
  fmt.SetFormatFlags(StringFormatFlagsNoWrap | StringFormatFlagsNoClip);

  RectF measured;
  g.MeasureString(wtext, -1, &font, PointF(0, 0), &fmt, &measured);
  REAL padX = (REAL)sz * 0.07f;
  if (padX < 5) padX = 5;
  REAL padY = (REAL)sz * 0.035f;
  if (padY < 2) padY = 2;
  REAL bh = measured.Height + padY * 2;
  REAL bw = measured.Width + padX * 2;
  if (bw < bh) bw = bh;
  REAL x = ((REAL)sz - bw) / 2;
  REAL y = ((REAL)sz - bh) / 2;
  if (x < 1) {
    x = 1;
    bw = (REAL)sz - 2;
  }
  if (y < 1) {
    y = 1;
    bh = (REAL)sz - 2;
  }

  GraphicsPath pill;
  add_round_rect(&pill, x, y, bw, bh, bh / 2);
  SolidBrush fill(Color(255, 255, 59, 48)); // macOS systemRed
  REAL strokeW = (REAL)sz * 0.02f;
  if (strokeW < 1.2f) strokeW = 1.2f;
  Pen stroke(Color(255, 255, 255, 255), strokeW);
  g.FillPath(&fill, &pill);
  g.DrawPath(&stroke, &pill);
  SolidBrush white(Color(255, 255, 255, 255));
  g.DrawString(wtext, -1, &font, RectF(x, y, bw, bh), &fmt, &white);
  return hicon_from_bitmap_sized(&bmp, sz, sz);
}

static void set_taskbar_badge(const char *text) {
  ITaskbarList3 *tbl = NULL;
  if (FAILED(CoCreateInstance(CLSID_TaskbarList, NULL, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&tbl))) ||
      !tbl) {
    return;
  }
  tbl->HrInit();
  if (g_badge_icon) {
    DestroyIcon(g_badge_icon);
    g_badge_icon = NULL;
  }
  if (!text || !text[0]) {
    tbl->SetOverlayIcon(g_hwnd, NULL, L"");
    tbl->Release();
    return;
  }
  wchar_t wch[32];
  utf8_to_wide(text, wch, 32);
  g_badge_icon = hicon_macos_badge(wch);
  wchar_t wtip[64];
  utf8_to_wide(text, wtip, 64);
  if (g_badge_icon) tbl->SetOverlayIcon(g_hwnd, g_badge_icon, wtip);
  tbl->Release();
}

static void enter_fullscreen(void) {
  if (g_fullscreen || !g_hwnd) return;
  GetWindowRect(g_hwnd, &g_fs_restore);
  LONG_PTR style = GetWindowLongPtr(g_hwnd, GWL_STYLE);
  style &= ~(WS_CAPTION | WS_THICKFRAME | WS_BORDER | WS_SYSMENU);
  style |= WS_POPUP;
  SetWindowLongPtr(g_hwnd, GWL_STYLE, style);
  int sw = GetSystemMetrics(SM_CXSCREEN);
  int sh = GetSystemMetrics(SM_CYSCREEN);
  SetWindowPos(g_hwnd, HWND_TOP, 0, 0, sw, sh, SWP_FRAMECHANGED | SWP_SHOWWINDOW);
  g_fullscreen = TRUE;
}

static void exit_fullscreen(void) {
  if (!g_fullscreen || !g_hwnd) return;
  LONG_PTR style = GetWindowLongPtr(g_hwnd, GWL_STYLE);
  style &= ~WS_POPUP;
  if (!g_frameless && !g_titlebar_hidden) style |= WS_OVERLAPPEDWINDOW;
  else style |= WS_POPUP;
  SetWindowLongPtr(g_hwnd, GWL_STYLE, style);
  int w = g_fs_restore.right - g_fs_restore.left;
  int h = g_fs_restore.bottom - g_fs_restore.top;
  if (w < 40) w = g_width;
  if (h < 40) h = g_height;
  SetWindowPos(g_hwnd, NULL, g_fs_restore.left, g_fs_restore.top, w, h,
               SWP_FRAMECHANGED | SWP_NOZORDER);
  g_fullscreen = FALSE;
}

static void show_desktop_notify(void) {
  char title[256], body[1024];
  read_trim_file("xu_ui_notify_title.txt", title, sizeof(title));
  read_file_raw("xu_ui_notify_body.txt", body, sizeof(body));
  if (!title[0]) snprintf(title, sizeof(title), "Xu");
  FlashWindow(g_hwnd, TRUE);
  if (g_tray_added) {
    NOTIFYICONDATAW nid;
    ZeroMemory(&nid, sizeof(nid));
    nid.cbSize = (DWORD)sizeof(NOTIFYICONDATAW);
    nid.hWnd = g_hwnd;
    nid.uID = TRAY_ICON_UID;
    nid.uFlags = NIF_INFO;
    wchar_t wt[64], wb[256];
    utf8_to_wide(title, wt, 64);
    utf8_to_wide(body[0] ? body : " ", wb, 256);
    wcsncpy(nid.szInfoTitle, wt, 63);
    wcsncpy(nid.szInfo, wb, 255);
    nid.szInfoTitle[63] = 0;
    nid.szInfo[255] = 0;
    nid.dwInfoFlags = NIIF_INFO;
    Shell_NotifyIconW(NIM_MODIFY, &nid);
  }
  append_shell_event("notify\tok");
}

static void post_tray_invoke(const char *id) {
  if (!id || !id[0]) return;
  char pending[32];
  read_trim_file("xu_ui_ipc_req.txt", pending, sizeof(pending));
  if (!pending[0]) {
    char body[640];
    snprintf(body, sizeof(body), "name: tray\npayload: %s\n", id);
    write_tmp("xu_ui_ipc_req.txt", body);
  }
  char ev[320];
  snprintf(ev, sizeof(ev), "tray_menu_clicked\t%s", id);
  append_shell_event(ev);
}

static void tray_on_command(const char *id) {
  if (!id || !id[0]) return;
  if (strcmp(id, "quit") == 0) {
    post_tray_invoke(id);
    request_close();
    return;
  }
  if (strcmp(id, "show") == 0) {
    g_hidden = FALSE;
    ShowWindow(g_hwnd, SW_SHOW);
    SetForegroundWindow(g_hwnd);
  } else if (strcmp(id, "hide") == 0) {
    g_hidden = TRUE;
    ShowWindow(g_hwnd, SW_HIDE);
  }
  post_tray_invoke(id);
}

static void tray_popup_menu(void) {
  if (!g_hwnd || g_tray_n <= 0) return;
  HMENU menu = CreatePopupMenu();
  if (!menu) return;
  // Labels cached at install — no re-read of xu_ui_tray.txt from TEMP.
  for (int idx = 0; idx < g_tray_n; idx++) {
    const char *label = g_tray_labels[idx][0] ? g_tray_labels[idx] : g_tray_ids[idx];
    wchar_t wlabel[256];
    utf8_to_wide(label, wlabel, 256);
    AppendMenuW(menu, MF_STRING, (UINT)(idx + 1), wlabel);
  }
  POINT pt;
  GetCursorPos(&pt);
  SetForegroundWindow(g_hwnd);
  int cmd = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_BOTTOMALIGN,
                           pt.x, pt.y, 0, g_hwnd, NULL);
  DestroyMenu(menu);
  PostMessageW(g_hwnd, WM_NULL, 0, 0);
  if (cmd >= 1 && cmd <= g_tray_n) tray_on_command(g_tray_ids[cmd - 1]);
}

static void tray_install_or_update_inner(void) {
  if (!g_hwnd) return;
  char tip[256], items[4096], icon_path[1024];
  read_trim_file("xu_ui_tray_tip.txt", tip, sizeof(tip));
  read_file_raw("xu_ui_tray.txt", items, sizeof(items));
  read_trim_file("xu_ui_tray_icon.txt", icon_path, sizeof(icon_path));
  if (!items[0]) return;
  char sig[512];
  snprintf(sig, sizeof(sig), "%s|%s|%s", tip, icon_path, items);
  if (g_tray_added && strcmp(sig, g_tray_sig) == 0) return;

  g_tray_n = 0;
  char *p = items;
  while (*p && g_tray_n < TRAY_MAX_ITEMS) {
    char *line = p;
    while (*p && *p != '\n' && *p != '\r') p++;
    char save = *p;
    if (*p) {
      *p = 0;
      p++;
      if (save == '\r' && *p == '\n') p++;
    }
    while (*line == ' ') line++;
    if (!line[0]) continue;
    char *tab = strchr(line, '\t');
    const char *label = (tab && tab[1]) ? tab + 1 : line;
    if (tab) *tab = 0;
    snprintf(g_tray_ids[g_tray_n], sizeof(g_tray_ids[0]), "%s", line);
    snprintf(g_tray_labels[g_tray_n], sizeof(g_tray_labels[0]), "%s", label);
    g_tray_n++;
  }
  if (g_tray_n == 0) return;

  // LR_SHARED system icon — always visible fallback if custom load fails.
  HICON icon = (HICON)LoadImageW(NULL, (LPCWSTR)IDI_APPLICATION, IMAGE_ICON,
                                 GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON),
                                 LR_SHARED);
  if (!icon) icon = LoadIconW(NULL, (LPCWSTR)IDI_APPLICATION);
  HICON custom = tray_load_icon(icon_path);
  if (custom) icon = custom;
  else host_trace("tray icon: system default (custom load failed)");

  ZeroMemory(&g_nid, sizeof(g_nid));
  // Full sizeof matches Win10/11 Explorer; V2_SIZE + NIF_SHOWTIP + VERSION_4
  // previously returned TRUE from NIM_ADD but often left the icon invisible.
  g_nid.cbSize = (DWORD)sizeof(NOTIFYICONDATAW);
  g_nid.hWnd = g_hwnd;
  g_nid.uID = TRAY_ICON_UID;
  g_nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
  g_nid.uCallbackMessage = WM_XU_TRAY;
  g_nid.hIcon = icon;
  wchar_t wtip[128];
  utf8_to_wide(tip[0] ? tip : "Xu", wtip, 128);
  wcsncpy(g_nid.szTip, wtip, 127);
  g_nid.szTip[127] = 0;

  {
    char diag[768];
    snprintf(diag, sizeof(diag),
             "tray install tip=[%s] icon=[%s] items=%d smicon=%d custom=%d cbSize=%lu",
             tip[0] ? tip : "Xu", icon_path[0] ? icon_path : "(fallback)", g_tray_n,
             GetSystemMetrics(SM_CXSMICON), custom ? 1 : 0,
             (unsigned long)g_nid.cbSize);
    host_trace(diag);
  }

  if (g_tray_added) {
    if (g_tray_icon && g_tray_icon != icon && g_tray_icon != custom)
      DestroyIcon(g_tray_icon);
    g_tray_icon = custom ? custom : NULL; // don't destroy shared IDI_APPLICATION
    if (!Shell_NotifyIconW(NIM_MODIFY, &g_nid)) {
      char err[80];
      snprintf(err, sizeof(err), "tray modify failed gle=%lu", (unsigned long)GetLastError());
      host_trace(err);
    } else {
      host_trace(custom ? "tray modify ok (custom icon)" : "tray modify ok (system icon)");
    }
  } else {
    if (g_tray_icon) DestroyIcon(g_tray_icon);
    g_tray_icon = custom ? custom : NULL;
    if (Shell_NotifyIconW(NIM_ADD, &g_nid)) {
      g_tray_added = TRUE;
#ifdef NIM_SETVERSION
      // NOTIFYICON_VERSION (3): classic lParam = WM_*BUTTON* — matches WndProc.
      // VERSION_4 changes callback layout; keep V3 for reliable popup menus.
      g_nid.uVersion = NOTIFYICON_VERSION;
      if (!Shell_NotifyIconW(NIM_SETVERSION, &g_nid)) {
        char err[80];
        snprintf(err, sizeof(err), "tray setversion failed gle=%lu",
                 (unsigned long)GetLastError());
        host_trace(err);
      } else {
        host_trace("tray setversion ok (NOTIFYICON_VERSION)");
      }
#endif
      host_trace(custom ? "tray ok (custom icon)" : "tray ok (system icon)");
    } else {
      char err[64];
      snprintf(err, sizeof(err), "tray add failed gle=%lu", (unsigned long)GetLastError());
      host_trace(err);
      if (custom) {
        DestroyIcon(custom);
        g_tray_icon = NULL;
      }
    }
  }
  snprintf(g_tray_sig, sizeof(g_tray_sig), "%s", sig);
}

static void tray_install_or_update(void) {
  tray_install_or_update_inner();
}

static void do_quit(void) {
  if(g_quitting)return;
  if(!g_root_closed){
    g_root_closed=true;
    desktop_files_close_owner(1,g_root_generation);
    if(g_content && g_content_vt && g_content_vt->destroy)g_content_vt->destroy(g_content);
    g_content=NULL;xu_ui_window_closed(1,g_root_generation);append_shell_event("closed");
    if(g_hwnd)ShowWindow(g_hwnd,SW_HIDE);
  }
  if(xu_ui_window_count() || !desktop_files_idle())return;
  g_quitting=TRUE;xu_ui_windows_shutdown();xu_ui_emit_close();
  if(g_hwnd && g_timer){KillTimer(g_hwnd,g_timer);g_timer=0;}
  tray_remove();xu_ui_host_set_kick(NULL);
  if(g_hwnd){HWND window=g_hwnd;g_hwnd=NULL;DestroyWindow(window);}
  append_shell_event("exit");PostQuitMessage(0);
}

static void request_close(void) {
  if (g_close_guard) {
    if (g_close_pending) return;
    g_close_pending = TRUE;
    append_shell_event("close_requested");
    // Align with macOS: show confirm dialog immediately (Quit / Cancel).
    int r = MessageBoxW(g_hwnd, L"Close guard is on. Quit the application?", L"Quit Xu?",
                        MB_OKCANCEL | MB_ICONWARNING | MB_DEFBUTTON2);
    if (r == IDOK) {
      g_close_guard = FALSE;
      g_close_pending = FALSE;
      write_tmp("xu_ui_close_guard.txt", "0");
      do_quit();
    } else {
      g_close_pending = FALSE;
      append_shell_event("close_rejected");
    }
    return;
  }
  do_quit();
}

/* Frameless / masked windows have no title-bar × — Esc or right-click Close. */
static void show_frameless_context_menu(HWND hwnd, int screen_x, int screen_y) {
  HMENU m = CreatePopupMenu();
  if (!m) return;
  AppendMenuW(m, MF_STRING, 1, L"Close");
  int cmd = TrackPopupMenu(m, TPM_RETURNCMD | TPM_RIGHTBUTTON, screen_x, screen_y, 0,
                           hwnd, NULL);
  DestroyMenu(m);
  if (cmd == 1) request_close();
}

static void write_bounds(void) {
  RECT rc;
  GetWindowRect(g_hwnd, &rc);
  char line[128];
  snprintf(line, sizeof(line), "%ld %ld %ld %ld",
           (long)rc.left, (long)rc.top,
           (long)(rc.right - rc.left), (long)(rc.bottom - rc.top));
  write_tmp("xu_ui_bounds.txt", line);
}

static void write_state(void) {
  char line[256];
  BOOL zoomed = IsZoomed(g_hwnd);
  snprintf(line, sizeof(line),
           "visible=%d zoomed=%d fullscreen=%d floating=%d close_guard=%d",
           g_hidden ? 0 : 1, zoomed ? 1 : 0, g_fullscreen ? 1 : 0, g_floating ? 1 : 0,
           g_close_guard ? 1 : 0);
  write_tmp("xu_ui_state.txt", line);
}

static int shot_png_path(char *out, size_t n) {
  char tmp[MAX_PATH];
  if (g_tmp[0]) {
    snprintf(out, n, "%s\\xu_ui_shot.png", g_tmp);
    return 1;
  }
  if (!GetTempPathA(MAX_PATH, tmp)) return 0;
  snprintf(out, n, "%sXuShot_%lu.png", tmp, (unsigned long)GetCurrentProcessId());
  return 1;
}

static BOOL save_hwnd_png(const char *path_utf8) {
  RECT rc;
  GetClientRect(g_hwnd, &rc);
  int w = rc.right - rc.left;
  int h = rc.bottom - rc.top;
  if (w < 1) w = 1;
  if (h < 1) h = 1;
  HDC hdc = GetDC(g_hwnd);
  HDC mem = CreateCompatibleDC(hdc);
  HBITMAP bmp = CreateCompatibleBitmap(hdc, w, h);
  HGDIOBJ old = SelectObject(mem, bmp);
  BitBlt(mem, 0, 0, w, h, hdc, 0, 0, SRCCOPY);
  SelectObject(mem, old);
  BOOL ok = FALSE;
  Bitmap *gb = Bitmap::FromHBITMAP(bmp, NULL);
  if (gb) {
    wchar_t wpath[1200];
    utf8_to_wide(path_utf8, wpath, 1200);
    CLSID clsid;
    UINT num = 0, size = 0;
    GetImageEncodersSize(&num, &size);
    if (size) {
      ImageCodecInfo *info = (ImageCodecInfo *)malloc(size);
      GetImageEncoders(num, size, info);
      for (UINT i = 0; i < num; i++) {
        if (wcscmp(info[i].MimeType, L"image/png") == 0) {
          clsid = info[i].Clsid;
          ok = (gb->Save(wpath, &clsid, NULL) == Ok);
          break;
        }
      }
      free(info);
    }
    delete gb;
  }
  DeleteObject(bmp);
  DeleteDC(mem);
  ReleaseDC(g_hwnd, hdc);
  return ok;
}

static void take_screenshot(void) {
  char path[1200];
  if (!shot_png_path(path, sizeof(path))) {
    append_shell_event("screenshot\t");
    return;
  }
  if (!save_hwnd_png(path)) {
    append_shell_event("screenshot\t");
    return;
  }
  snprintf(g_last_shot_path, sizeof(g_last_shot_path), "%s", path);
  write_tmp("xu_ui_shot_path.txt", path);
  // Also mirror PNG bytes into mailbox so pack `:xu:/xu_ui_shot.png` magic-check works.
  {
    FILE *f = fopen(path, "rb");
    if (f) {
      fseek(f, 0, SEEK_END);
      long sz = ftell(f);
      fseek(f, 0, SEEK_SET);
      if (sz > 0 && sz < 32 * 1024 * 1024) {
        char *buf = (char *)malloc((size_t)sz);
        if (buf && fread(buf, 1, (size_t)sz, f) == (size_t)sz) {
          xu_ui_mem_set_n("xu_ui_shot.png", buf, (unsigned)sz);
        }
        free(buf);
      }
      fclose(f);
    }
  }
  append_shell_event("screenshot\tok");
}

static void screenshot_to_clipboard(void) {
  RECT rc;
  GetClientRect(g_hwnd, &rc);
  int w = rc.right - rc.left;
  int h = rc.bottom - rc.top;
  if (w < 1) w = 1;
  if (h < 1) h = 1;
  HDC hdc = GetDC(g_hwnd);
  HDC mem = CreateCompatibleDC(hdc);
  HBITMAP bmp = CreateCompatibleBitmap(hdc, w, h);
  HGDIOBJ old = SelectObject(mem, bmp);
  BitBlt(mem, 0, 0, w, h, hdc, 0, 0, SRCCOPY);
  SelectObject(mem, old);
  if (OpenClipboard(g_hwnd)) {
    EmptyClipboard();
    SetClipboardData(CF_BITMAP, bmp); // ownership transferred on success
    CloseClipboard();
    bmp = NULL;
    append_shell_event("screenshot\tclipboard");
  } else {
    append_shell_event("screenshot\t");
  }
  if (bmp) DeleteObject(bmp);
  DeleteDC(mem);
  ReleaseDC(g_hwnd, hdc);
}

static void pick_path(BOOL folder) {
  IFileOpenDialog *dlg = NULL;
  if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, NULL, CLSCTX_INPROC_SERVER,
                              IID_PPV_ARGS(&dlg)))) {
    write_tmp("xu_ui_pick.txt", "");
    append_shell_event(folder ? "folder_picked\t" : "file_picked\t");
    return;
  }
  DWORD opts = 0;
  dlg->GetOptions(&opts);
  if (folder) opts |= FOS_PICKFOLDERS;
  dlg->SetOptions(opts);
  if (SUCCEEDED(dlg->Show(g_hwnd))) {
    IShellItem *item = NULL;
    if (SUCCEEDED(dlg->GetResult(&item))) {
      PWSTR path = NULL;
      if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &path))) {
        char utf8[2048];
        wide_to_utf8(path, utf8, sizeof(utf8));
        write_tmp("xu_ui_pick.txt", utf8);
        char ev[2200];
        snprintf(ev, sizeof(ev), "%s\t%s", folder ? "folder_picked" : "file_picked", utf8);
        append_shell_event(ev);
        CoTaskMemFree(path);
      }
      item->Release();
    }
  } else {
    write_tmp("xu_ui_pick.txt", "");
    append_shell_event(folder ? "folder_picked\t" : "file_picked\t");
  }
  dlg->Release();
}

static void save_file(void) {
  IFileSaveDialog *dlg = NULL;
  if (FAILED(CoCreateInstance(CLSID_FileSaveDialog, NULL, CLSCTX_INPROC_SERVER,
                              IID_PPV_ARGS(&dlg)))) {
    write_tmp("xu_ui_save.txt", "");
    append_shell_event("file_saved\t");
    return;
  }
  char name[256];
  read_trim_file("xu_ui_save_name.txt", name, sizeof(name));
  if (name[0]) {
    wchar_t wname[256];
    utf8_to_wide(name, wname, 256);
    dlg->SetFileName(wname);
  }
  if (SUCCEEDED(dlg->Show(g_hwnd))) {
    IShellItem *item = NULL;
    if (SUCCEEDED(dlg->GetResult(&item))) {
      PWSTR path = NULL;
      if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &path))) {
        char utf8[2048];
        wide_to_utf8(path, utf8, sizeof(utf8));
        write_tmp("xu_ui_save.txt", utf8);
        char ev[2200];
        snprintf(ev, sizeof(ev), "file_saved\t%s", utf8);
        append_shell_event(ev);
        CoTaskMemFree(path);
      }
      item->Release();
    }
  } else {
    write_tmp("xu_ui_save.txt", "");
    append_shell_event("file_saved\t");
  }
  dlg->Release();
}

static void show_alert(BOOL confirm) {
  char title[256], msg[4096];
  read_trim_file("xu_ui_alert_title.txt", title, sizeof(title));
  read_file_raw("xu_ui_alert_msg.txt", msg, sizeof(msg));
  wchar_t wt[256], wm[4096];
  utf8_to_wide(title[0] ? title : "Xu", wt, 256);
  utf8_to_wide(msg, wm, 4096);
  UINT type = confirm ? (MB_OKCANCEL | MB_ICONWARNING) : (MB_OK | MB_ICONINFORMATION);
  int r = MessageBoxW(g_hwnd, wm, wt, type);
  if (confirm) {
    const char *ok = (r == IDOK) ? "1" : "0";
    write_tmp("xu_ui_alert_result.txt", ok);
    char ev[32];
    snprintf(ev, sizeof(ev), "confirm\t%s", ok);
    append_shell_event(ev);
  } else {
    write_tmp("xu_ui_alert_result.txt", "ok");
    append_shell_event("alert\tok");
  }
}

static void clipboard_set(void) {
  char body[8192];
  read_file_raw("xu_ui_clipboard_set.txt", body, sizeof(body));
  wchar_t *w = (wchar_t *)malloc((strlen(body) + 1) * sizeof(wchar_t) * 2);
  if (!w) return;
  utf8_to_wide(body, w, (int)(strlen(body) + 1) * 2);
  size_t bytes = (wcslen(w) + 1) * sizeof(wchar_t);
  HGLOBAL h = GlobalAlloc(GMEM_MOVEABLE, bytes);
  if (!h) {
    free(w);
    return;
  }
  void *p = GlobalLock(h);
  memcpy(p, w, bytes);
  GlobalUnlock(h);
  free(w);
  if (OpenClipboard(g_hwnd)) {
    EmptyClipboard();
    SetClipboardData(CF_UNICODETEXT, h);
    CloseClipboard();
  } else {
    GlobalFree(h);
  }
}

static void clipboard_get(void) {
  if (!OpenClipboard(g_hwnd)) {
    write_tmp("xu_ui_clipboard.txt", "");
    return;
  }
  HANDLE h = GetClipboardData(CF_UNICODETEXT);
  if (!h) {
    CloseClipboard();
    write_tmp("xu_ui_clipboard.txt", "");
    return;
  }
  wchar_t *w = (wchar_t *)GlobalLock(h);
  char utf8[8192];
  wide_to_utf8(w ? w : L"", utf8, sizeof(utf8));
  GlobalUnlock(h);
  CloseClipboard();
  write_tmp("xu_ui_clipboard.txt", utf8);
}

static void drain_title_size(void) {
  char title[512], size_raw[64];
  read_trim_file("xu_ui_title.txt", title, sizeof(title));
  if (title[0] && strcmp(title, g_last_title) != 0) {
    snprintf(g_last_title, sizeof(g_last_title), "%s", title);
    wchar_t wt[512];
    utf8_to_wide(title, wt, 512);
    SetWindowTextW(g_hwnd, wt);
  }
  read_trim_file("xu_ui_size.txt", size_raw, sizeof(size_raw));
  if (size_raw[0] && strcmp(size_raw, g_last_size) != 0) {
    int w = 0, h = 0;
    if (sscanf(size_raw, "%d %d", &w, &h) == 2 && w > 0 && h > 0) {
      snprintf(g_last_size, sizeof(g_last_size), "%s", size_raw);
      g_width = w;
      g_height = h;
      resize_to_client(w, h);
      if (g_mask_active) paint_mask_layered();
    }
  }
}

static void handle_shell_cmd(const char *s) {
  if(g_root_closed)return;
  if(!strcmp(s,"close")){request_close();return;}
  if(!strncmp(s,"title\t",6)){write_tmp("xu_ui_title.txt",s+6);drain_title_size();return;}
  if(!strncmp(s,"size\t",5)){int width=0,height=0;char tail=0;if(sscanf(s+5,"%d\t%d%c",&width,&height,&tail)==2 && width>=40 && height>=40 && width<=16384 && height<=16384){char size[40];snprintf(size,sizeof(size),"%d %d",width,height);write_tmp("xu_ui_size.txt",size);drain_title_size();}return;}

  if (strcmp(s, "show") == 0) {
    g_hidden = FALSE;
    ShowWindow(g_hwnd, SW_SHOW);
    SetForegroundWindow(g_hwnd);
    return;
  }
  if (strcmp(s, "hide") == 0) {
    g_hidden = TRUE;
    ShowWindow(g_hwnd, SW_HIDE);
    return;
  }
  if (strcmp(s, "minimize") == 0) {
    ShowWindow(g_hwnd, SW_MINIMIZE);
    return;
  }
  if (strcmp(s, "maximize") == 0) {
    ShowWindow(g_hwnd, SW_MAXIMIZE);
    return;
  }
  if (strcmp(s, "unmaximize") == 0) {
    ShowWindow(g_hwnd, SW_RESTORE);
    return;
  }
  if (strcmp(s, "quit") == 0) {
    do_quit();
    return;
  }
  if (strcmp(s, "bounce") == 0) {
    FlashWindow(g_hwnd, TRUE);
    return;
  }
  if (strcmp(s, "center") == 0) {
    RECT rc;
    GetWindowRect(g_hwnd, &rc);
    int ww = rc.right - rc.left;
    int wh = rc.bottom - rc.top;
    int sw = GetSystemMetrics(SM_CXSCREEN);
    int sh = GetSystemMetrics(SM_CYSCREEN);
    SetWindowPos(g_hwnd, NULL, (sw - ww) / 2, (sh - wh) / 2, 0, 0,
                 SWP_NOSIZE | SWP_NOZORDER);
    return;
  }
  if (strcmp(s, "fullscreen") == 0) {
    enter_fullscreen();
    return;
  }
  if (strcmp(s, "fullscreen_exit") == 0) {
    exit_fullscreen();
    return;
  }
  if (strcmp(s, "float") == 0) {
    g_floating = TRUE;
    SetWindowPos(g_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE);
    return;
  }
  if (strcmp(s, "unfloat") == 0) {
    g_floating = FALSE;
    SetWindowPos(g_hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE);
    return;
  }
  if (strcmp(s, "pick_file") == 0) {
    pick_path(FALSE);
    return;
  }
  if (strcmp(s, "pick_folder") == 0) {
    pick_path(TRUE);
    return;
  }
  if (strcmp(s, "save_file") == 0) {
    save_file();
    return;
  }
  if (strcmp(s, "screenshot") == 0) {
    take_screenshot();
    return;
  }
  if (strcmp(s, "screenshot_clipboard") == 0) {
    screenshot_to_clipboard();
    return;
  }
  if (strcmp(s, "alert") == 0) {
    show_alert(FALSE);
    return;
  }
  if (strcmp(s, "confirm") == 0) {
    show_alert(TRUE);
    return;
  }
  if (strcmp(s, "notify") == 0) {
    show_desktop_notify();
    return;
  }
  if (strcmp(s, "accept_close") == 0) {
    g_close_guard = FALSE;
    g_close_pending = FALSE;
    do_quit();
    return;
  }
  if (strcmp(s, "reject_close") == 0) {
    g_close_pending = FALSE;
    append_shell_event("close_rejected");
    return;
  }
  if (strcmp(s, "get_bounds") == 0) {
    write_bounds();
    return;
  }
  if (strcmp(s, "get_state") == 0) {
    write_state();
    return;
  }
  if (strcmp(s, "clipboard_set") == 0) {
    clipboard_set();
    return;
  }
  if (strcmp(s, "clipboard_get") == 0) {
    clipboard_get();
    return;
  }
  if (strcmp(s, "open_external") == 0) {
    char url[2048];
    read_trim_file("xu_ui_open_url.txt", url, sizeof(url));
    if (url[0]) {
      wchar_t wurl[2048];
      utf8_to_wide(url, wurl, 2048);
      ShellExecuteW(NULL, L"open", wurl, NULL, NULL, SW_SHOWNORMAL);
    }
    return;
  }
  if (strcmp(s, "open_path") == 0 || strcmp(s, "reveal_path") == 0) {
    char p[2048];
    read_trim_file("xu_ui_path.txt", p, sizeof(p));
    if (!p[0]) {
      // Legacy filenames (pre-align).
      read_trim_file(strcmp(s, "open_path") == 0 ? "xu_ui_open_path.txt" : "xu_ui_reveal_path.txt",
                     p, sizeof(p));
    }
    if (p[0]) {
      wchar_t wp[2048];
      utf8_to_wide(p, wp, 2048);
      if (strcmp(s, "reveal_path") == 0) {
        wchar_t params[2200];
        _snwprintf(params, 2200, L"/select,\"%s\"", wp);
        ShellExecuteW(NULL, L"open", L"explorer.exe", params, NULL, SW_SHOWNORMAL);
      } else {
        ShellExecuteW(NULL, L"open", wp, NULL, NULL, SW_SHOWNORMAL);
      }
    }
    return;
  }
  if (strncmp(s, "frameless\t", 10) == 0) {
    apply_frameless(s[10] != '0');
    return;
  }
  if (strncmp(s, "transparent\t", 12) == 0) {
    apply_transparent(s[12] != '0');
    return;
  }
  if (strncmp(s, "opacity\t", 8) == 0) {
    double o = atof(s + 8);
    if (o < 0.15) o = 0.15;
    if (o > 1.0) o = 1.0;
    if (!g_mask_active) {
      LONG_PTR ex = GetWindowLongPtr(g_hwnd, GWL_EXSTYLE);
      SetWindowLongPtr(g_hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED);
      SetLayeredWindowAttributes(g_hwnd, 0, (BYTE)(o * 255.0), LWA_ALPHA);
    }
    return;
  }
  if (strncmp(s, "mask\t", 5) == 0) {
    apply_mask(s + 5);
    return;
  }
  if (strcmp(s, "mask_clear") == 0) {
    clear_mask();
    return;
  }
  if (strncmp(s, "titlebar\t", 9) == 0) {
    // Align mac: hide title chrome but keep WebView clickable — only top strip drags.
    g_titlebar_hidden = (s[9] == '0');
    if (g_titlebar_hidden) {
      LONG_PTR style = GetWindowLongPtr(g_hwnd, GWL_STYLE);
      style &= ~(WS_CAPTION | WS_SYSMENU);
      style |= WS_POPUP | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX;
      SetWindowLongPtr(g_hwnd, GWL_STYLE, style);
    } else if (!g_frameless && !g_mask_active) {
      LONG_PTR style = GetWindowLongPtr(g_hwnd, GWL_STYLE);
      style &= ~WS_POPUP;
      style |= WS_OVERLAPPEDWINDOW;
      SetWindowLongPtr(g_hwnd, GWL_STYLE, style);
    }
    SetWindowPos(g_hwnd, NULL, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED);
    return;
  }
  if (strncmp(s, "close_guard\t", 12) == 0) {
    g_close_guard = s[12] != '0';
    return;
  }
  if (strncmp(s, "shadow\t", 7) == 0) {
    // Best-effort: DWM cloaking not required; no-op success for API parity.
    return;
  }
  if (strncmp(s, "appearance\t", 11) == 0) {
    apply_appearance(s + 11);
    return;
  }
  if (strncmp(s, "all_spaces\t", 11) == 0) return; // macOS-only
  if (strncmp(s, "dock_badge\t", 11) == 0) {
    set_taskbar_badge(s + 11);
    return;
  }
  if (strcmp(s, "dock_badge_clear") == 0) {
    set_taskbar_badge("");
    return;
  }
  if (strncmp(s, "minsize\t", 8) == 0) {
    int w = 0, h = 0;
    if (sscanf(s + 8, "%d\t%d", &w, &h) == 2) {
      g_min_w = w > 0 ? w : 0;
      g_min_h = h > 0 ? h : 0;
    }
    return;
  }
  if (strncmp(s, "resizable\t", 10) == 0) {
    LONG_PTR style = GetWindowLongPtr(g_hwnd, GWL_STYLE);
    if (s[10] != '0') style |= WS_THICKFRAME | WS_MAXIMIZEBOX;
    else style &= ~(WS_THICKFRAME | WS_MAXIMIZEBOX);
    SetWindowLongPtr(g_hwnd, GWL_STYLE, style);
    resize_to_client(g_width, g_height, SWP_FRAMECHANGED);
    return;
  }
  if (strncmp(s, "position\t", 9) == 0) {
    int x = 0, y = 0;
    if (sscanf(s + 9, "%d\t%d", &x, &y) == 2) {
      SetWindowPos(g_hwnd, NULL, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER);
    }
    return;
  }
}

static const char *strip_prefix(const char *raw) {
  if (strncmp(raw, "shell.", 6) == 0) return raw + 6;
  if (strncmp(raw, "content.", 8) == 0) return raw + 8;
  if (strncmp(raw, "wv.", 3) == 0) return raw + 3;
  return raw;
}

static void maybe_install_content_plugin(void);
#include "windows_clipboard.inc"
#include "windows_windows.inc"

static void drain_cmds(void) {
  xu_ui_request_poll();
  desktop_files_poll();
  if(!g_root_closed)drain_title_size();
  extra_poll();
  if(g_root_closed && !xu_ui_window_count()){do_quit();if(g_quitting)return;}
  apply_app_icon();
  tray_install_or_update();
  menu_install_or_update();
  if (g_content && g_content_vt && g_content_vt->on_poll) {
    g_content_vt->on_poll(g_content);
  }
  std::string commands = xu_ui_take_commands(g_tmp);
  char *buf = commands.data();
  if (!buf[0]) return;
  char *p = buf;
  while (*p) {
    char *line = p;
    while (*p && *p != '\n') p++;
    if (*p == '\n') {
      *p = 0;
      p++;
    }
    while (*line == ' ') line++;
    if (*line) {
      if(!strcmp(line,"shell.quit_app")){for(auto &window:g_extra_windows)extra_close(window,true);xu_ui_windows_shutdown();do_quit();return;}
      if(extra_dispatch(line))continue;
      unsigned identity[2];const char *unscoped=line;xu_ui_scoped_command(line,identity,&unscoped);
      const char *cmd = strip_prefix(unscoped);
      int to_content = (strncmp(unscoped, "wv.", 3) == 0 || strncmp(unscoped, "content.", 8) == 0);
      if (to_content) {
        if (!desktop_files(cmd,1,g_root_generation,g_hwnd) && !desktop_clipboard(cmd,1,g_root_generation) && g_content && g_content_vt && g_content_vt->handle_cmd) {
          g_content_vt->handle_cmd(g_content, cmd);
        }
        xu_ui_draw_discard_marker(cmd);
        xu_ui_request_discard_marker(cmd);
      } else {
        handle_shell_cmd(cmd);
      }
    }
  }
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
  if (g_taskbar_created && msg == g_taskbar_created) {
    // Explorer restarted — NIM_ADD state is gone; force reinstall.
    host_trace("TaskbarCreated: reinstall tray");
    g_tray_added = FALSE;
    g_tray_sig[0] = 0;
    tray_install_or_update();
    return 0;
  }
  switch (msg) {
  case WM_XU_TRAY:
    if (lParam == WM_RBUTTONUP || lParam == WM_LBUTTONUP || lParam == WM_CONTEXTMENU ||
        lParam == (LPARAM)(WM_USER + 0) /* NIN_SELECT */ ||
        lParam == (LPARAM)(WM_USER + 1) /* NIN_KEYSELECT */) {
      tray_popup_menu();
      return 0;
    }
    break;
  case WM_XU_KICK_HOST:
    drain_cmds();
    return 0;
  case WM_TIMER:
    if (wParam == 1) drain_cmds();
    return 0;
  case WM_PAINT: {
    PAINTSTRUCT ps;
    BeginPaint(hwnd, &ps);
    if (!g_mask_active) {
      HBRUSH br = CreateSolidBrush(RGB(235, 235, 240));
      FillRect(ps.hdc, &ps.rcPaint, br);
      DeleteObject(br);
    }
    EndPaint(hwnd, &ps);
    return 0;
  }
  case WM_SIZE:
    if(!g_root_closed && g_root_generation){RECT client={};GetClientRect(hwnd,&client);double scale=xu_ui_window_scale(hwnd);char event[80];snprintf(event,sizeof(event),"resized\t%d\t%d",(int)((client.right-client.left)/scale),(int)((client.bottom-client.top)/scale));append_shell_event(event);}
    if (g_mask_active) paint_mask_layered();
    if (g_content && g_content_vt && g_content_vt->sync_frame) {
      g_content_vt->sync_frame(g_content);
    }
    return 0;
  case WM_DPICHANGED: {
    const RECT *suggested = (const RECT *)lParam;
    if (suggested) SetWindowPos(hwnd, NULL, suggested->left, suggested->top,
        suggested->right - suggested->left, suggested->bottom - suggested->top,
        SWP_NOZORDER | SWP_NOACTIVATE);
    if (g_content && g_content_vt && g_content_vt->sync_frame) g_content_vt->sync_frame(g_content);
    return 0;
  }
  case WM_GETMINMAXINFO: {
    if (g_min_w > 0 || g_min_h > 0) {
      MINMAXINFO *mmi = (MINMAXINFO *)lParam;
      if (g_min_w > 0) mmi->ptMinTrackSize.x = g_min_w;
      if (g_min_h > 0) mmi->ptMinTrackSize.y = g_min_h;
      return 0;
    }
    break;
  }
  case WM_COMMAND: {
    UINT id = LOWORD(wParam);
    if (id == MENU_ID_DEVTOOLS) {
      if (g_content && g_content_vt && g_content_vt->handle_cmd) {
        g_content_vt->handle_cmd(g_content, "devtools");
      }
      return 0;
    }
    if (id >= MENU_ID_BASE && id < MENU_ID_BASE + (UINT)g_menu_n) {
      menu_on_command(g_menu_ids[id - MENU_ID_BASE]);
      return 0;
    }
    break;
  }
  case WM_NCHITTEST:
    if (g_frameless || g_mask_active || g_titlebar_hidden) {
      LRESULT hit = DefWindowProcW(hwnd, msg, wParam, lParam);
      if (hit == HTCLIENT) {
        POINT pt;
        pt.x = (short)LOWORD(lParam);
        pt.y = (short)HIWORD(lParam);
        ScreenToClient(hwnd, &pt);
        if (pt.y >= 0 && pt.y < TITLEBAR_DRAG_PX) return HTCAPTION;
        return HTCLIENT;
      }
      return hit;
    }
    break;
  case WM_NCRBUTTONUP:
  case WM_RBUTTONUP:
    if (g_frameless || g_mask_active) {
      POINT pt;
      if (msg == WM_RBUTTONUP) {
        pt.x = (short)LOWORD(lParam);
        pt.y = (short)HIWORD(lParam);
        ClientToScreen(hwnd, &pt);
      } else {
        pt.x = (short)LOWORD(lParam);
        pt.y = (short)HIWORD(lParam);
      }
      show_frameless_context_menu(hwnd, pt.x, pt.y);
      return 0;
    }
    break;
  case WM_KEYDOWN:
  case WM_SYSKEYDOWN:
    if (wParam == VK_ESCAPE) {
      request_close();
      return 0;
    }
    break;
  case WM_CLOSE:
    request_close();
    return 0;
  case WM_DESTROY:
    if (!g_quitting) do_quit();
    return 0;
  }
  return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static void host_write_tmp(const char *name, const char *body) { write_tmp(name, body); }
static void host_append_event(const char *payload) { append_shell_event(payload); }
static void host_read_trim(const char *name, char *out, unsigned n) {
  read_trim_file(name, out, (size_t)n);
}
static void host_read_raw(const char *name, char *out, unsigned n) {
  read_file_raw(name, out, (size_t)n);
}

static const XuContentVTable *resolve_content_vtable(void) {
  unsigned meta[6];if(xu_ui_window_info(1,0,meta,NULL,0))return content_kind_vtable(meta[4]);
  char kind[16];read_trim_file("xu_ui_content_kind.txt",kind,sizeof(kind));
  if(kind[0])return content_kind_vtable((unsigned)atoi(kind));
  char boot[256];
  read_trim_file("xu_ui_plugin_bootstrap.txt", boot, sizeof(boot));
  if (strcmp(boot, "XuWebViewPluginBootstrap") == 0) {
    if (xu_webview_plugin_vtable) return xu_webview_plugin_vtable();
    return NULL;
  }
  if (strcmp(boot, "XuDrawPluginBootstrap") == 0) {
    if (xu_draw_plugin_vtable) return xu_draw_plugin_vtable();
    return NULL;
  }
  return NULL;
}

static void maybe_install_content_plugin(void) {
  g_content_vt = resolve_content_vtable();
  if (!g_content_vt || !g_content_vt->create || !g_content_vt->install) return;
  ZeroMemory(&g_content_host, sizeof(g_content_host));
  g_content_host.tmp = g_tmp;
  g_content_host.window_id = 1;
  g_content_host.canvas_id = 1;
  unsigned meta[6];if(xu_ui_window_info(1,0,meta,NULL,0))g_content_host.canvas_generation=meta[1];
  g_content_host.native_window = (void *)g_hwnd;
  g_content_host.content_parent = (void *)g_hwnd;
  g_content_host.append_shell_event = host_append_event;
  g_content_host.write_tmp = host_write_tmp;
  g_content_host.read_trim = host_read_trim;
  g_content_host.read_raw = host_read_raw;
  g_content = g_content_vt->create(&g_content_host);
  if (g_content) g_content_vt->install(g_content);
}

// Real body. Keep separate so xu_ui_host_run can realign RSP first (Win64 + SSE).
static int xu_ui_host_run_impl(const char *tmp_dir) {
  xu_ui_emit_start();
  xu_ui_enable_dpi_awareness();
  host_trace("enter");
  HRESULT co = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
  host_trace(SUCCEEDED(co) || co == S_FALSE || co == RPC_E_CHANGED_MODE ? "coinit ok" : "coinit fail");
  GdiplusStartupInput gdiplusStartupInput;
  Status gst = GdiplusStartup(&g_gdiplus_token, &gdiplusStartupInput, NULL);
  host_trace(gst == Ok ? "gdiplus ok" : "gdiplus fail");

  const char *tmp = tmp_dir;
  if (!tmp || !tmp[0]) tmp = getenv("XU_UI_TMP");
  // Pack/oneexe: no xu_ui_* workdir — mailbox is xu_ui_mem (g_tmp empty).
  if (tmp && tmp[0] && strcmp(tmp, ":xu:") != 0 && strcmp(tmp, ":mem:") != 0) {
    snprintf(g_tmp, sizeof(g_tmp), "%s", tmp);
  } else {
    g_tmp[0] = 0;
  }
  host_trace(g_tmp[0] ? "tmp set (disk)" : "tmp=:xu: (in-process mem, no xu_ui dir)");
  g_last_title[0] = 0;
  g_last_size[0] = 0;
  g_hwnd = NULL;
  g_quitting = FALSE;
  g_close_pending = FALSE;

  char title[512];
  char size_raw[64];
  read_trim_file("xu_ui_title.txt", title, sizeof(title));
  read_trim_file("xu_ui_size.txt", size_raw, sizeof(size_raw));
  if (!title[0]) snprintf(title, sizeof(title), "Xu");
  sscanf(size_raw, "%d %d", &g_width, &g_height);
  if (g_width < 40) g_width = 40;
  if (g_height < 40) g_height = 40;
  snprintf(g_last_title, sizeof(g_last_title), "%s", title);
  snprintf(g_last_size, sizeof(g_last_size), "%s", size_raw);
  host_trace("title/size read");

  char chrome[32];
  read_trim_file("xu_ui_frameless.txt", chrome, sizeof(chrome));
  BOOL launch_frameless = chrome[0] == '1';
  read_trim_file("xu_ui_transparent.txt", chrome, sizeof(chrome));
  BOOL launch_transparent = chrome[0] == '1';
  read_trim_file("xu_ui_close_guard.txt", chrome, sizeof(chrome));
  if (chrome[0] == '1') g_close_guard = TRUE;

  HINSTANCE hi = GetModuleHandleW(NULL);
  // BSS is always 16-byte aligned — avoid stack movaps for WNDCLASSEXW.
  static WNDCLASSEXW s_wc;
  {
    unsigned char *p = (unsigned char *)&s_wc;
    for (size_t i = 0; i < sizeof(s_wc); i++) p[i] = 0;
  }
  s_wc.cbSize = sizeof(s_wc);
  s_wc.lpfnWndProc = WndProc;
  s_wc.hInstance = hi;
  s_wc.lpszClassName = L"XuUiHost";
  s_wc.hCursor = LoadCursor(NULL, IDC_ARROW);
  s_wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
  // PE resource icon (windres IDI_XUAPP) — Explorer + default window chrome.
  s_wc.hIcon = (HICON)LoadImageW(hi, MAKEINTRESOURCEW(IDI_XUAPP), IMAGE_ICON,
                                 GetSystemMetrics(SM_CXICON), GetSystemMetrics(SM_CYICON), 0);
  s_wc.hIconSm = (HICON)LoadImageW(hi, MAKEINTRESOURCEW(IDI_XUAPP), IMAGE_ICON,
                                   GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON), 0);
  if (!g_taskbar_created) {
    g_taskbar_created = RegisterWindowMessageW(L"TaskbarCreated");
  }
  host_trace("RegisterClassW...");
  RegisterClassExW(&s_wc);
  host_trace(s_wc.hIcon ? "RegisterClassExW done (PE icon)" : "RegisterClassExW done (no PE icon)");

  char mask_path[1024];
  read_trim_file("xu_ui_mask_path.txt", mask_path, sizeof(mask_path));
  BOOL has_mask = mask_path[0] != 0;

  DWORD style = launch_frameless ? WS_POPUP : WS_OVERLAPPEDWINDOW;
  DWORD ex = WS_EX_APPWINDOW;
  // Only use SetLayeredWindowAttributes path when there is no PNG mask.
  // Masked windows must use UpdateLayeredWindow exclusively.
  if (launch_transparent && !has_mask) ex |= WS_EX_LAYERED;

  int sw = GetSystemMetrics(SM_CXSCREEN);
  int sh = GetSystemMetrics(SM_CYSCREEN);
  SIZE outer = outer_size_for_client(g_width, g_height, style, ex, FALSE);
  int px = (sw > outer.cx) ? (sw - outer.cx) / 2 : 0;
  int py = (sh > outer.cy) ? (sh - outer.cy) / 2 : 0;

  wchar_t wtitle[512];
  utf8_to_wide(title, wtitle, 512);
  host_trace("CreateWindowExW...");
  g_hwnd = CreateWindowExW(ex, L"XuUiHost", wtitle, style,
                           px, py, outer.cx, outer.cy,
                           NULL, NULL, hi, NULL);
  if (!g_hwnd) {
    append_shell_event("create_window_failed");
    host_trace("CreateWindowEx FAILED");
    fprintf(stderr, "xu_ui_host: CreateWindowEx failed err=%lu\n",
            (unsigned long)GetLastError());
    fflush(stderr);
    GdiplusShutdown(g_gdiplus_token);
    CoUninitialize();
    return 1;
  }
  resize_to_client(g_width,g_height,SWP_NOACTIVATE);
  host_trace("hwnd ok");
  apply_app_icon();
  fprintf(stderr,
          "xu_ui_host: hwnd ok frameless=%d transparent=%d has_mask=%d "
          "size=%dx%d tmp=%s\n",
          (int)launch_frameless, (int)launch_transparent, (int)has_mask,
          g_width, g_height, g_tmp);
  fflush(stderr);
  g_frameless = launch_frameless;
  if (launch_transparent && !has_mask) apply_transparent(TRUE);
  if (has_mask) {
    host_trace("apply_mask...");
    apply_mask(mask_path);
    host_trace(g_mask_active ? "mask ok" : "mask fail");
  }

  host_trace("content plugin...");
  unsigned identity[6];if(xu_ui_window_info(1,0,identity,NULL,0)){g_root_generation=identity[1];xu_ui_window_claim(1,identity[1]);}
  maybe_install_content_plugin();
  if(identity[1])xu_ui_window_ready(1,identity[1]);
  host_trace("ShowWindow...");

  ShowWindow(g_hwnd, SW_SHOW);
  UpdateWindow(g_hwnd);
  if (g_mask_active) paint_mask_layered();
  SetForegroundWindow(g_hwnd);
  BringWindowToTop(g_hwnd);
  /* Tray installed on first WM_TIMER — keep ShowWindow path crash-free. */
  xu_ui_host_set_kick([]() {
    if (g_hwnd) PostMessageW(g_hwnd, WM_XU_KICK_HOST, 0, 0);
  });
  append_shell_event("window_ready");
  append_shell_event("ready");
  host_trace("ready; msgloop");
  fprintf(stderr, "xu_ui_host: ready mask_active=%d\n", (int)g_mask_active);
  fflush(stderr);
  {
    if (g_tmp[0]) {
      char boot[1100];
      snprintf(boot, sizeof(boot), "%s/xu_host_ready.txt", g_tmp);
      FILE *f = fopen(boot, "w");
      if (!f) {
        snprintf(boot, sizeof(boot), "%s\\xu_host_ready.txt", g_tmp);
        f = fopen(boot, "w");
      }
      if (f) {
        fputs("ready\n", f);
        fclose(f);
      }
    }
    xu_ui_mem_set("xu_host_ready.txt", "ready\n");
  }
  g_timer = SetTimer(g_hwnd, 1, 200, NULL);

  MSG msg;
  while (GetMessageW(&msg, NULL, 0, 0)) {
    if (xu_ui_dialog_message(&msg)) continue;
    TranslateMessage(&msg);
    DispatchMessageW(&msg);
  }

  delete g_mask;
  g_mask = NULL;
  g_mask_active = FALSE;
  GdiplusShutdown(g_gdiplus_token);
  CoUninitialize();
  host_trace("exit 0");
  return 0;
}

// In-process entry (statically linked via libxu_ui_host.a). tmp_dir may be NULL → env/TEMP.
// Realign RSP before entering C++ that may use movaps (Xu callers can leave RSP%16==0).
#if defined(XU_UI_STATIC)
extern "C" int xu_ui_host_run(const char *tmp_dir) {
#else
extern "C" __declspec(dllexport) int xu_ui_host_run(const char *tmp_dir) {
#endif
#if defined(__x86_64__)
  int ret;
  const void *arg = tmp_dir;
  int (*impl)(const char *) = xu_ui_host_run_impl;
  __asm__ __volatile__(
      "pushq %%rbp\n\t"
      "movq %%rsp, %%rbp\n\t"
      "andq $-16, %%rsp\n\t"
      "subq $32, %%rsp\n\t"
      "movq %[arg], %%rcx\n\t"
      "call *%[impl]\n\t"
      "movl %%eax, %[ret]\n\t"
      "leave\n\t"
      : [ret] "=r"(ret)
      : [arg] "r"(arg), [impl] "r"(impl)
      : "rax", "rcx", "rdx", "r8", "r9", "r10", "r11", "cc", "memory");
  return ret;
#else
  return xu_ui_host_run_impl(tmp_dir);
#endif
}

#ifndef XU_UI_STATIC
int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
  return xu_ui_host_run(NULL);
}
#endif
