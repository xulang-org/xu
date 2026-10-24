/* Pack entry: embed icon + www + optional WebView2Loader, then Xu _xu_main. */
#define WIN32_LEAN_AND_MEAN
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <windows.h>
#include "xu_ui_mem.h"
#include "xu_pack_assets.h"
#include "xu_ui_text.h"

typedef void (WINAPI *ExitProcessFn)(UINT);

extern const unsigned char xu_pack_icon_png[];
extern const unsigned int xu_pack_icon_png_len;

extern const unsigned char xu_pack_webview2_loader[];
extern const unsigned int xu_pack_webview2_loader_len;

static int write_bytes(const char *path, const void *data, DWORD n) {
  HANDLE h = CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, NULL);
  if (h == INVALID_HANDLE_VALUE) return 0;
  DWORD w = 0;
  BOOL ok = WriteFile(h, data, n, &w, NULL);
  CloseHandle(h);
  return ok && w == n;
}

static int write_loader_to(const char *dir) {
  char path[MAX_PATH];
  WIN32_FILE_ATTRIBUTE_DATA fad;
  if (!dir || !dir[0]) return 0;
  snprintf(path, MAX_PATH, "%s\\WebView2Loader.dll", dir);
  if (GetFileAttributesExA(path, GetFileExInfoStandard, &fad) &&
      fad.nFileSizeHigh == 0 &&
      fad.nFileSizeLow == xu_pack_webview2_loader_len) {
    return 1;
  }
  return write_bytes(path, xu_pack_webview2_loader, xu_pack_webview2_loader_len);
}

static int write_loader_beside_exe(void) {
  char path[MAX_PATH];
  char *slash;
  DWORD n = GetModuleFileNameA(NULL, path, MAX_PATH);
  if (n == 0 || n >= MAX_PATH) return 0;
  slash = strrchr(path, '\\');
  if (!slash) slash = strrchr(path, '/');
  if (!slash) return 0;
  *slash = 0;
  return write_loader_to(path);
}

static char g_log_path[MAX_PATH];
static char g_trace_path[MAX_PATH];
static HANDLE g_log_std = INVALID_HANDLE_VALUE;
static DWORD g_main_tid = 0;
static CRITICAL_SECTION g_log_cs;
static int g_log_cs_ready = 0;

static void log_write_raw(const char *s, DWORD n) {
  DWORD w = 0;
  if (!s || !n) return;
  if (g_log_cs_ready) EnterCriticalSection(&g_log_cs);
  if (g_log_std != INVALID_HANDLE_VALUE) {
    WriteFile(g_log_std, s, n, &w, NULL);
    WriteFile(g_log_std, "\r\n", 2, &w, NULL);
    FlushFileBuffers(g_log_std);
  } else if (g_log_path[0]) {
    HANDLE h = CreateFileA(g_log_path, FILE_APPEND_DATA,
                          FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                          OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) {
      WriteFile(h, s, n, &w, NULL);
      WriteFile(h, "\r\n", 2, &w, NULL);
      CloseHandle(h);
    }
  }
  if (g_log_cs_ready) LeaveCriticalSection(&g_log_cs);
}

static void bind_xu_stdio_to_log(void) {
  if (!g_log_path[0]) return;
  if (!g_log_cs_ready) {
    InitializeCriticalSection(&g_log_cs);
    g_log_cs_ready = 1;
  }
  g_log_std = CreateFileA(g_log_path, GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                         OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
  if (g_log_std == INVALID_HANDLE_VALUE) return;
  SetFilePointer(g_log_std, 0, NULL, FILE_END);
  SetStdHandle(STD_OUTPUT_HANDLE, g_log_std);
  SetStdHandle(STD_ERROR_HANDLE, g_log_std);
}

static void log_line(const char *s) {
  if (!s) return;
  log_write_raw(s, (DWORD)strlen(s));
  fprintf(stderr, "%s\n", s);
  fflush(stderr);
}

static void init_log_path(void) {
  char exe[MAX_PATH];
  char *slash;
  char *dot;
  DWORD n = GetModuleFileNameA(NULL, exe, MAX_PATH);
  g_log_path[0] = 0;
  g_trace_path[0] = 0;
  if (n == 0 || n >= MAX_PATH) {
    GetTempPathA(MAX_PATH, g_log_path);
    strcat(g_log_path, "xu_ui.log");
    snprintf(g_trace_path, MAX_PATH, "%s.trace.txt", g_log_path);
    DeleteFileA(g_log_path);
    DeleteFileA(g_trace_path);
    SetEnvironmentVariableA("XU_PACK_TRACE", g_trace_path);
    SetEnvironmentVariableA("XU_UI_LOG", g_log_path);
    return;
  }
  slash = strrchr(exe, '\\');
  if (!slash) slash = strrchr(exe, '/');
  snprintf(g_log_path, MAX_PATH, "%s", exe);
  dot = strrchr(g_log_path, '.');
  if (dot && _stricmp(dot, ".exe") == 0) strcpy(dot, ".log");
  else strcat(g_log_path, ".log");
  snprintf(g_trace_path, MAX_PATH, "%s", exe);
  dot = strrchr(g_trace_path, '.');
  if (dot && _stricmp(dot, ".exe") == 0) strcpy(dot, ".trace.txt");
  else strcat(g_trace_path, ".trace.txt");
  DeleteFileA(g_log_path);
  DeleteFileA(g_trace_path);
  SetEnvironmentVariableA("XU_PACK_TRACE", g_trace_path);
  SetEnvironmentVariableA("XU_UI_LOG", g_log_path);
}

static void log_ptr_module(const char *prefix, void *ptr) {
  HMODULE mod = NULL;
  char line[512];
  if (!ptr) return;
  if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)ptr, &mod)) {
    char path[MAX_PATH];
    DWORD n = GetModuleFileNameA(mod, path, MAX_PATH);
    if (n > 0) {
      char *fn = strrchr(path, '\\');
      if (!fn) fn = strrchr(path, '/');
      if (fn) fn++; else fn = path;
      snprintf(line, sizeof(line), "%s%p (%s+0x%llx base=%p)", prefix, ptr, fn,
               (unsigned long long)((uintptr_t)ptr - (uintptr_t)mod), (void *)mod);
      log_line(line);
      return;
    }
  }
  snprintf(line, sizeof(line), "%s%p", prefix, ptr);
  log_line(line);
}

void xu_trace(const char *msg) {
  log_line(msg);
}

static LONG WINAPI xu_veh(EXCEPTION_POINTERS *ep) {
  char msg[768];
  unsigned long code = 0;
  void *addr = NULL;
  void *rip = NULL;
  void *rsp = NULL;
  void *rbp = NULL;
  ULONG_PTR fault_op = 0;
  ULONG_PTR fault_addr = 0;
  DWORD tid = GetCurrentThreadId();

  if (ep && ep->ExceptionRecord) {
    code = (unsigned long)ep->ExceptionRecord->ExceptionCode;
    addr = ep->ExceptionRecord->ExceptionAddress;
    if (ep->ExceptionRecord->NumberParameters >= 2) {
      fault_op = ep->ExceptionRecord->ExceptionInformation[0];
      fault_addr = ep->ExceptionRecord->ExceptionInformation[1];
    }
  }
  if (code == 0x40010006UL || code == 0x4001000AUL)
    return EXCEPTION_CONTINUE_SEARCH;
  if (ep && ep->ContextRecord) {
#if defined(__aarch64__) || defined(_M_ARM64)
    rip = (void *)(uintptr_t)ep->ContextRecord->Pc;
    rsp = (void *)(uintptr_t)ep->ContextRecord->Sp;
    rbp = (void *)(uintptr_t)ep->ContextRecord->Fp;
#else
    rip = (void *)(uintptr_t)ep->ContextRecord->Rip;
    rsp = (void *)(uintptr_t)ep->ContextRecord->Rsp;
    rbp = (void *)(uintptr_t)ep->ContextRecord->Rbp;
    {
      char regs[512];
      snprintf(regs, sizeof(regs),
        "rax=%016llx rbx=%016llx rcx=%016llx rdx=%016llx\n"
        "rsi=%016llx rdi=%016llx rbp=%016llx rsp=%016llx\n"
        "r8 =%016llx r9 =%016llx r10=%016llx r11=%016llx\n"
        "r12=%016llx r13=%016llx r14=%016llx r15=%016llx",
        (unsigned long long)ep->ContextRecord->Rax,
        (unsigned long long)ep->ContextRecord->Rbx,
        (unsigned long long)ep->ContextRecord->Rcx,
        (unsigned long long)ep->ContextRecord->Rdx,
        (unsigned long long)ep->ContextRecord->Rsi,
        (unsigned long long)ep->ContextRecord->Rdi,
        (unsigned long long)ep->ContextRecord->Rbp,
        (unsigned long long)ep->ContextRecord->Rsp,
        (unsigned long long)ep->ContextRecord->R8,
        (unsigned long long)ep->ContextRecord->R9,
        (unsigned long long)ep->ContextRecord->R10,
        (unsigned long long)ep->ContextRecord->R11,
        (unsigned long long)ep->ContextRecord->R12,
        (unsigned long long)ep->ContextRecord->R13,
        (unsigned long long)ep->ContextRecord->R14,
        (unsigned long long)ep->ContextRecord->R15);
      log_line(regs);
    }
#endif
  }
  snprintf(msg, sizeof(msg),
           "VEH exception 0x%08lX (op=%llu addr=%p) at %p rip=%p rsp=%p tid=%lu (main=%lu)",
           code, (unsigned long long)fault_op, (void *)fault_addr, addr, rip, rsp,
           (unsigned long)tid, (unsigned long)g_main_tid);
  log_line(msg);

  log_ptr_module("  rip in module: ", rip);

  /* Walk RBP frame pointer chain */
  if (rbp) {
    void **frame = (void **)rbp;
    for (int f = 0; f < 16 && frame; f++) {
      char prefix[64];
      void *next;
      void *ret;
      if (IsBadReadPtr(frame, sizeof(void *) * 2)) {
        log_line("  frame: invalid rbp pointer");
        break;
      }
      next = frame[0];
      ret = frame[1];
      snprintf(prefix, sizeof(prefix), "  frame #%d rbp=%p ret=", f, (void *)frame);
      log_ptr_module(prefix, ret);
      if ((uintptr_t)next <= (uintptr_t)frame || (uintptr_t)next - (uintptr_t)frame > 0x1000000)
        break;
      frame = (void **)next;
    }
  }

  /* Scan stack words for pointers into loaded modules */
  if (rsp) {
    void **sp = (void **)rsp;
    char stack_msg[512];
    snprintf(stack_msg, sizeof(stack_msg),
             "stack: %p %p %p %p %p %p %p %p",
             sp[0], sp[1], sp[2], sp[3], sp[4], sp[5], sp[6], sp[7]);
    log_line(stack_msg);
    for (int i = 0; i < 64; i++) {
      char prefix[64];
      HMODULE smod = NULL;
      if (IsBadReadPtr(&sp[i], sizeof(void *))) break;
      if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)sp[i], &smod)) {
        snprintf(prefix, sizeof(prefix), "  stack[%02d]=%p -> ", i, sp[i]);
        log_ptr_module(prefix, sp[i]);
      }
    }
  }

  return EXCEPTION_CONTINUE_SEARCH;
}

static LONG WINAPI xu_unhandled(EXCEPTION_POINTERS *ep) {
  char msg[384];
  unsigned long code = 0;
  void *addr = NULL;
  if (ep && ep->ExceptionRecord) {
    code = (unsigned long)ep->ExceptionRecord->ExceptionCode;
    addr = ep->ExceptionRecord->ExceptionAddress;
  }
  snprintf(msg, sizeof(msg),
           "Xu crashed (exception 0x%08lX at %p).\r\nSee .log / .trace.txt next to exe.",
           code, addr);
  log_line(msg);
  {
    char dbg[8];
    if (GetEnvironmentVariableA("XU_UI_DEBUG", dbg, sizeof(dbg)) > 0 && dbg[0] == '1')
      MessageBoxA(NULL, msg, "Xu", MB_OK | MB_ICONERROR);
  }
  return EXCEPTION_EXECUTE_HANDLER;
}

static ExitProcessFn g_real_ExitProcess = NULL;

static void WINAPI hooked_ExitProcess(UINT code) {
  char msg[320];
  if (g_real_ExitProcess) g_real_ExitProcess(code);
  (void)code;
  (void)msg;
}

static void hook_exit_process(void) {
  HMODULE base = GetModuleHandleA(NULL);
  IMAGE_DOS_HEADER *dos;
  IMAGE_NT_HEADERS *nt;
  IMAGE_IMPORT_DESCRIPTOR *imp;
  if (!base) return;
  dos = (IMAGE_DOS_HEADER *)base;
  if (dos->e_magic != IMAGE_DOS_SIGNATURE) return;
  nt = (IMAGE_NT_HEADERS *)((char *)base + dos->e_lfanew);
  if (nt->Signature != IMAGE_NT_SIGNATURE) return;
  if (!nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress) return;
  imp = (IMAGE_IMPORT_DESCRIPTOR *)((char *)base +
        nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress);
  for (; imp->Name; imp++) {
    char *dll = (char *)base + imp->Name;
    IMAGE_THUNK_DATA *thunk;
    IMAGE_THUNK_DATA *orig;
    if (!dll) continue;
    if (_stricmp(dll, "KERNEL32.dll") != 0 && _stricmp(dll, "kernel32.dll") != 0) continue;
    if (!imp->OriginalFirstThunk || !imp->FirstThunk) continue;
    thunk = (IMAGE_THUNK_DATA *)((char *)base + imp->FirstThunk);
    orig = (IMAGE_THUNK_DATA *)((char *)base + imp->OriginalFirstThunk);
    for (; thunk->u1.Function; thunk++, orig++) {
      IMAGE_IMPORT_BY_NAME *nm;
      DWORD old = 0;
      if (orig->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
      nm = (IMAGE_IMPORT_BY_NAME *)((char *)base + (DWORD)orig->u1.AddressOfData);
      if (!nm || strcmp(nm->Name, "ExitProcess") != 0) continue;
      g_real_ExitProcess = (ExitProcessFn)(uintptr_t)thunk->u1.Function;
      if (!VirtualProtect(&thunk->u1.Function, sizeof(void *), PAGE_READWRITE, &old))
        return;
      thunk->u1.Function = (ULONGLONG)(uintptr_t)hooked_ExitProcess;
      VirtualProtect(&thunk->u1.Function, sizeof(void *), old, &old);
      log_line("hooked ExitProcess");
      return;
    }
  }
}

static void maybe_alloc_console(void) {
  char buf[8];
  int want = 0;
  DWORD n = GetEnvironmentVariableA("XU_UI_CONSOLE", buf, sizeof(buf));
  if (n > 0 && buf[0] == '1') want = 1;
  {
    const char *cl = GetCommandLineA();
    if (cl && strstr(cl, "--console")) want = 1;
  }
  if (!want) return;
  FreeConsole();
  if (!AllocConsole()) {
    log_line("AllocConsole failed");
    return;
  }
  SetConsoleTitleA("Xu UI debug console");
  freopen("CONOUT$", "w", stdout);
  freopen("CONOUT$", "w", stderr);
  freopen("CONIN$", "r", stdin);
  if (g_log_std != INVALID_HANDLE_VALUE) {
    SetStdHandle(STD_OUTPUT_HANDLE, g_log_std);
    SetStdHandle(STD_ERROR_HANDLE, g_log_std);
  }
}

static int xu_pack_setup(void) {
  xu_ui_set_asset_reader(xu_pack_asset_ptr);
  xu_draw_text_init();
  char exe_dir[MAX_PATH];
  char *slash;
  DWORD n;
  SetEnvironmentVariableA("XU_UI_TMP", "");
  SetEnvironmentVariableA("XU_UI_PACK", "1");
  SetEnvironmentVariableA("XU_UI_WWW", ":mem:");
  if (xu_pack_webview2_loader_len > 0) {
    if (!write_loader_beside_exe()) return 0;
    log_line("WebView2Loader beside exe");
  }
  n = GetModuleFileNameA(NULL, exe_dir, MAX_PATH);
  if (n > 0 && n < MAX_PATH) {
    slash = strrchr(exe_dir, '\\');
    if (!slash) slash = strrchr(exe_dir, '/');
    if (slash) {
      *slash = 0;
      SetCurrentDirectoryA(exe_dir);
    }
  }
  log_line("cwd pack (no xu_ui TEMP dir)");
  log_line("www=:mem: icon=:pack: bridge=:pack: mailbox=:xu:");
  return 1;
}

int WINAPI WinMain(HINSTANCE a, HINSTANCE b, LPSTR c, int d) {
  (void)a; (void)b; (void)c; (void)d;
  g_main_tid = GetCurrentThreadId();
  init_log_path();
  bind_xu_stdio_to_log();
  AddVectoredExceptionHandler(1, xu_veh);
  SetUnhandledExceptionFilter(xu_unhandled);
  log_line("WinMain begin");
  maybe_alloc_console();
  if (!xu_pack_setup()) {
    log_line("pack setup failed");
    if (xu_pack_webview2_loader_len > 0)
      MessageBoxA(NULL, "pack setup failed (WebView2Loader beside exe)", "Xu", MB_OK | MB_ICONERROR);
    return 1;
  }
  hook_exit_process();
  {
    extern void xu_force_cxx_string_syms(void);
    extern void _rt_collect_args(void);
    extern void _rt_xu_mark(void);
    extern void _rt_collect_env(void);
    extern void _rt_win_sysinfo(void);
    extern int _xu_main(void);
    char *cmdline;
    int rc;
    log_line("before xu_force_cxx_string_syms");
    xu_force_cxx_string_syms();
    log_line("after xu_force_cxx_string_syms");
    cmdline = GetCommandLineA();
    log_line("GetCommandLineA ok");
#if defined(__aarch64__) || defined(_M_ARM64)
    __asm__ __volatile__(
      "mov x0, %[cl]\n\t"
      "bl _rt_collect_args\n\t"
      :
      : [cl] "r" (cmdline)
      : "x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "x30", "memory");
#else
    __asm__ __volatile__(
      "mov %[cl], %%rdi\n\t"
      "call _rt_collect_args\n\t"
      :
      : [cl] "r" (cmdline)
      : "rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11",
        "xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "memory");
#endif
    log_line("after _rt_collect_args");
    _rt_xu_mark();
    log_line("after _rt_xu_mark");
    _rt_collect_env();
    log_line("after _rt_collect_env");
    _rt_win_sysinfo();
    log_line("after _rt_win_sysinfo");
    log_line("calling _xu_main");
#if defined(__aarch64__) || defined(_M_ARM64)
    __asm__ __volatile__(
      "bl _xu_main\n\t"
      "mov %w[rc], w0\n\t"
      : [rc] "=r" (rc)
      :
      : "x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "x30", "memory");
#else
    __asm__ __volatile__(
      "push %%rbp\n\t"
      "mov %%rsp, %%rbp\n\t"
      "and $~15, %%rsp\n\t"
      "sub $32, %%rsp\n\t"
      "call _xu_main\n\t"
      "mov %%rbp, %%rsp\n\t"
      "pop %%rbp\n\t"
      "mov %%eax, %[rc]\n\t"
      : [rc] "=r" (rc)
      :
      : "rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11",
        "xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "memory");
#endif
    {
      char m[64];
      snprintf(m, sizeof(m), "_xu_main returned %d", rc);
      log_line(m);
    }
    if (g_real_ExitProcess) g_real_ExitProcess((UINT)rc);
    else ExitProcess((UINT)rc);
  }
  return 0;
}
