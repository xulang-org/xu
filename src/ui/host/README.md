# UI host (per OS)

## 原则：异语言 → `.a` → 单主程序（无 cgo）

凡 Swift / C++ 等进 Xu UI 应用，一律先编成 **`libxu_ui_host.a`**，再与 Xu 目标**静态链**成**一个**可执行文件。  
**不做 cgo / dlopen / LoadLibrary / 旁路编第二 host**；产品形态禁止第二 host 主程序。

```text
host(+webview).o  →  ar  →  libxu_ui_host.a  →  link with Xu .o  →  one main
                                                     ↑
                                          xu_ui_host_run 由 .a 提供
```

辅助：[`scripts/ar_xu_host.py`](../../../scripts/ar_xu_host.py)、[`xuobj_to_macho_o.py`](../../../scripts/xuobj_to_macho_o.py) / [`xuobj_to_coff_o.py`](../../../scripts/xuobj_to_coff_o.py) / [`xuobj_to_elf_o.py`](../../../scripts/xuobj_to_elf_o.py)。

## Xu 侧（编译期 `$` 标记）

| File | Tag | Role |
|------|-----|------|
| `../host_open_macos.xu` | `$macos` | 仅同进程 `ui_host_run`；未链 host（stub=127）报错 |
| `../host_open_linux.xu` | `$linux` | 同上 |
| `../host_open_windows.xu` | `$windows` | 同上 |

`App.run()` → `open_native_window` → `ui_host_run`。内容槽经 `register_content_plugin` 写 TMP bootstrap（供静态链插件注册）。

## 原生宿主源

| File | Role |
|------|------|
| `macos_host.swift` | AppKit；`XU_UI_STATIC` 时无独立 `main` |
| `linux_host.cc` / `windows_host.cc` | `xu_ui_host_run`；`XU_UI_STATIC` 时无独立 `main` |
| `xu_content_abi.h` | L/W 内容插件 ABI |

WebView 插件见同目录 `macos_webview.swift` / `linux_webview.cc` / `windows_webview.cc`（`#ui/webview`；始终注册 `xu://`；本地 `www` 或远程 http(s) 均可）。打包后的 `www` / 图标**留在进程内存**（`xu_pack_www_files` / `xu_pack_icon_png`），不释放到临时目录。

## 单文件打包（三端均为静态链）

**用户入口**（产品自举 `xu`，非 Rust bootstrap）：

```bash
xu doctor --desktop --target macos-arm64
xu build App --target macos-arm64 --desktop -o XuApp
# → XuApp.app（须含 xu.xun + main.xu + brand/<icon>.png；可选 www/）
xu build ../xu-examples/examples/16_ui_webview/open --target macos-arm64 --desktop -o XuApp
xu build ../xu-examples/examples/16_ui_webview/shaped --target macos-arm64 --desktop -o XuShaped
# windows/linux --desktop：产品路径明确未实现（不回退 Python）
```

**macOS** 产品路径在 `src/cmd/compile`（`driver_desktop.xu` + `xuobj_macho.xu`）内完成，只调用主机 `swiftc`/`clang`/`ar`/`xcrun`。  
`scripts/xu_desktop_pack.py` / `pack_*.py` / `xu_doctor.py` **仅 CI/调试**，不是产品入口。

用户只拿**一个**主程序。无 `--desktop` 时普通编译的 UI 二进制未链 host（stub=127），会报 `host not linked`。

Windows WebView 额外说明：Edge **WebView2 Runtime**（系统 Evergreen）不能打进 PE；NuGet 的 `WebView2LoaderStatic.lib` 仅 MSVC。MinGW pack 把约 166KB 的 `WebView2Loader.dll` **嵌进 exe**，启动时解到 **exe 同目录**（已存在且大小一致则跳过，不进 TEMP）。`www` 与品牌图标不落盘。
