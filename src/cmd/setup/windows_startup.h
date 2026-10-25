/* Installer-only Win32 startup. Runs before the Xu entry, without a shell. */
#include <shellapi.h>
#include <wchar.h>
#include <stdlib.h>

static BOOL xu_setup_is_elevated(void) {
    HANDLE token = NULL;
    TOKEN_ELEVATION elevation = {0};
    DWORD size = 0;
    BOOL elevated = OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token) &&
        GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &size) &&
        elevation.TokenIsElevated;
    if (token) CloseHandle(token);
    return elevated;
}

/* Encode one argument with the same quoting rules as CommandLineToArgvW. */
static BOOL xu_setup_quote(wchar_t *out, size_t *used, const wchar_t *arg) {
    size_t slashes = 0;
    if (*used + 2 >= 32767) return FALSE;
    out[(*used)++] = L'"';
    for (const wchar_t *p = arg; ; ++p) {
        if (*p == L'\\') { ++slashes; continue; }
        size_t count = (*p == L'"' || !*p) ? slashes * 2 : slashes;
        if (*used + count + 4 >= 32767) return FALSE;
        while (count--) out[(*used)++] = L'\\';
        slashes = 0;
        if (!*p) break;
        if (*p == L'"') out[(*used)++] = L'\\';
        out[(*used)++] = *p;
    }
    out[(*used)++] = L'"';
    out[(*used)++] = L' ';
    out[*used] = 0;
    return TRUE;
}

/* -1 continues into Xu. Other results are the launcher exit status. */
static int xu_setup_startup(void) {
    int count = 0;
    wchar_t **args = CommandLineToArgvW(GetCommandLineW(), &count);
    if (!args) return 1;
    BOOL all_users = FALSE, launch_only = FALSE, help = FALSE;
    for (int i = 1; i < count; ++i) {
        /* Values are data, including a prefix literally named '--all-users'. */
        if ((!wcscmp(args[i], L"--prefix") || !wcscmp(args[i], L"-p") ||
             !wcscmp(args[i], L"--version")) && i + 1 < count) { ++i; continue; }
        if (!wcscmp(args[i], L"--all-users")) all_users = TRUE;
        if (!wcscmp(args[i], L"--current-user")) all_users = FALSE;
        if (!wcscmp(args[i], L"--elevate-ui")) launch_only = TRUE;
        if (!wcscmp(args[i], L"--help") || !wcscmp(args[i], L"-h") || !wcscmp(args[i], L"/?")) help = TRUE;
    }
    BOOL elevated = xu_setup_is_elevated();
    SetEnvironmentVariableW(L"XU_SETUP_ELEVATED", elevated ? L"1" : L"0");
    if (!all_users || elevated || help) { LocalFree(args); return -1; }
    wchar_t *exe = (wchar_t *)calloc(32768, sizeof(wchar_t));
    wchar_t *params = (wchar_t *)calloc(32768, sizeof(wchar_t));
    size_t used = 0;
    DWORD length = exe ? GetModuleFileNameW(NULL, exe, 32768) : 0;
    BOOL valid = params && length && length < 32768;
    for (int i = 1; valid && i < count; ++i) valid = xu_setup_quote(params, &used, args[i]);
    LocalFree(args);
    if (!valid) { free(exe); free(params); return 1; }
    SHELLEXECUTEINFOW launch = {0};
    launch.cbSize = sizeof(launch);
    launch.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI;
    launch.lpVerb = L"runas";
    launch.lpFile = exe;
    launch.lpParameters = params;
    launch.nShow = SW_SHOWNORMAL;
    BOOL started = ShellExecuteExW(&launch);
    DWORD code = started ? 0 : GetLastError();
    free(exe); free(params);
    if (started && !launch_only) {
        if (!launch.hProcess || WaitForSingleObject(launch.hProcess, INFINITE) != WAIT_OBJECT_0 ||
            !GetExitCodeProcess(launch.hProcess, &code)) code = 1;
    }
    if (launch.hProcess) CloseHandle(launch.hProcess);
    return (int)code;
}

static void xu_setup_notify_environment(void) {
    SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, (LPARAM)L"Environment",
                        SMTO_ABORTIFHUNG, 5000, NULL);
}
