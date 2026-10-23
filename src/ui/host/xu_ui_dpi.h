// Windows DPI APIs are resolved dynamically to retain the older-OS fallback.
#pragma once
#include <windows.h>
#ifndef WM_DPICHANGED
#define WM_DPICHANGED 0x02e0
#endif
#ifndef WM_DPICHANGED_AFTERPARENT
#define WM_DPICHANGED_AFTERPARENT 0x02e3
#endif

static inline void xu_ui_enable_dpi_awareness(void) {
  HMODULE user32 = GetModuleHandleW(L"user32.dll");
  typedef BOOL (WINAPI *SetContext)(HANDLE);
  SetContext context = (SetContext)GetProcAddress(user32, "SetProcessDpiAwarenessContext");
  if (context && context((HANDLE)(INT_PTR)-4)) return; // per-monitor aware v2
  HMODULE shcore = LoadLibraryW(L"shcore.dll");
  if (shcore) {
    typedef HRESULT (WINAPI *SetAwareness)(int);
    SetAwareness awareness = (SetAwareness)GetProcAddress(shcore, "SetProcessDpiAwareness");
    HRESULT result = awareness ? awareness(2) : E_NOTIMPL;
    FreeLibrary(shcore);
    if (SUCCEEDED(result) || result == E_ACCESSDENIED) return; // already configured
  }
  SetProcessDPIAware();
}

static inline double xu_ui_window_scale(HWND window) {
  typedef UINT (WINAPI *GetWindowDpi)(HWND);
  GetWindowDpi get = (GetWindowDpi)GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow");
  UINT dpi = get && window ? get(window) : 0;
  if (!dpi) {
    HDC dc = GetDC(window);
    if (dc) { dpi = (UINT)GetDeviceCaps(dc, LOGPIXELSX); ReleaseDC(window, dc); }
  }
  return dpi ? (double)dpi / 96.0 : 1.0;
}

// Modeless native prompts use the ordinary host loop for Tab, Enter and Escape.
static inline bool xu_ui_dialog_message(MSG *message) {
  HWND root = message->hwnd ? GetAncestor(message->hwnd, GA_ROOT) : NULL;
  wchar_t name[16];
  return root && GetClassNameW(root, name, 16) && lstrcmpW(name, L"#32770") == 0 && IsDialogMessageW(root, message);
}

// Window options are logical client pixels on every platform. Use the actual
// HWND after creation/moving; a secondary window may have a different DPI.
static inline SIZE xu_ui_outer_for_client(HWND window,int width,int height,DWORD style,DWORD ex,BOOL menu) {
  double scale=xu_ui_window_scale(window);
  // Native DPI values are trusted, but keep legacy oversized calls representable.
  double physical_width=(double)width*scale,physical_height=(double)height*scale;
  if(physical_width<0)physical_width=0;if(physical_height<0)physical_height=0;
  if(physical_width>1073741823.0)physical_width=1073741823.0;
  if(physical_height>1073741823.0)physical_height=1073741823.0;
  RECT frame={0,0,(LONG)(physical_width+0.5),(LONG)(physical_height+0.5)};
  typedef BOOL (WINAPI *AdjustForDpi)(LPRECT,DWORD,BOOL,DWORD,UINT);
  auto adjust=(AdjustForDpi)GetProcAddress(GetModuleHandleW(L"user32.dll"),"AdjustWindowRectExForDpi");
  UINT dpi=(UINT)(scale*96.0+0.5);
  if(!adjust || !adjust(&frame,style,menu,ex,dpi))AdjustWindowRectEx(&frame,style,menu,ex);
  SIZE size={frame.right-frame.left,frame.bottom-frame.top};return size;
}
