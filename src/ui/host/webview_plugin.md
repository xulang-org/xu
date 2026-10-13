# WebView host plugins (per OS)

Content plugin for `#ui/webview`. Registered by `webview.attach` as `ui.ContentPlugin`
with separate sources per OS — `#ui` shell does not hardcode WebKit/WebView2.

| File | Role |
|------|------|
| `macos_webview.swift` | WKWebView plugin (`XuWebViewPluginBootstrap`) |
| `linux_webview.cc` | WebKitGTK 6 plugin (`xu_webview_plugin_vtable`) |
| `windows_webview.cc` | WebView2 plugin (`xu_webview_plugin_vtable`) |
| `webview2_min.h` | Minimal WebView2 COM + dynamic `WebView2Loader.dll` |

Shared ABI: `src/ui/host/xu_content_abi.h` (L/W). macOS uses Swift `XuContentPlugin`.

## Capability (vs macOS)

| Feature | macOS | Linux | Windows |
|---------|-------|-------|---------|
| load html / url | ✅ | ✅ | ✅ |
| eval / eval result | ✅ | ✅ | ✅ |
| reload / back / forward / stop | ✅ | ✅ | ✅ |
| zoom / mute / bgcolor / inject CSS | ✅ | ✅ | ✅ |
| find / UA / context_menu | ✅ | ✅ | ✅ |
| loading / loaded / progress / external_nav | ✅ | ✅ | ✅ |
| file drop | ✅ | ✅ | ✅ |
| print / cookies / cache | ✅ | 部分 | best-effort |
| DevTools | ✅ | inspector | best-effort |

## Build deps

- **Linux**: `libgtk-4-dev` + `libwebkitgtk-6.0-dev`（`pkg-config webkitgtk-6.0`）
- **Windows**: mingw/cl；运行时 Evergreen WebView2 Runtime + `WebView2Loader.dll`（exe 旁或 PATH）
- Shell-only（无 `attach`）：不链插件，弱符号为空

构建：经 `scripts/pack_*_ui_oneexe.py` 静态链入 `libxu_ui_host.a`（含本插件）。无外部 host 旁路。
