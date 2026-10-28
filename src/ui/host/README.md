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

## 桌面打包（三端均静态链接 Xu host）

**用户入口**（产品自举 `xu`，非 Rust bootstrap）：

以下命令在 `xu` 仓库根目录执行；示例仓库按同级 `../examples` 检出。其他布局请将示例路径替换为实际路径或绝对路径。

```bash
xu doctor --desktop --webview --target macos-arm64
xu build App --target macos-arm64 --desktop -o XuApp
# → XuApp.app（App 目录含 main.xu；项目配置用 xu.xun，图标用 brand/<icon>.png；可选 www/）
xu build ../examples/examples/16_ui_webview/open --target macos-arm64 --desktop -o XuApp
xu build ../examples/examples/16_ui_webview/shaped --target macos-arm64 --desktop -o XuShaped

# 在具备对应工具链的宿主上分别执行：
xu doctor --desktop --webview --target windows-x64
xu build ../examples/examples/16_ui_webview/open --target windows-x64 --desktop -o XuApp.exe
xu doctor --desktop --webview --target linux-x64
xu build ../examples/examples/16_ui_webview/open --target linux-x64 --desktop -o XuApp
```

产品入口为 `xu build --desktop`，转交伴生工具 `xu-desktop pack`；分派与实现位于 [`src/cmd/desktop/`](../../cmd/desktop/main.xu) 的 `main.xu`、`pack_macos.xu`、`pack_windows.xu`、`pack_linux.xu`。从源码使用时，以已验证的 hosted Xu seed（`bin/xu`，或通过 `XU_SEED=/path/to/xu` 指定）运行 `make xu-desktop xu-doctor`，将仓库的 `bin/` 加入 `PATH` 后执行上面的命令。打包还需要可定位的 Xu checkout（含 `src/ui/host`；可用 `XU_ROOT` 指定）。

| 目标 | 宿主工具要求 | 输出与运行依赖 |
|------|--------------|----------------|
| `macos-arm64` / `macos-x64` | macOS；Xcode 开发工具目录，`swiftc`、`clang`/`clang++`、`ar`、`xcrun`，图标处理用 `sips` / `iconutil` | `.app`；系统 AppKit，WebView 使用系统 WebKit |
| `windows-arm64` / `windows-x64` | 对应架构的 MinGW 工具链（`gcc`、`g++`、`ar`、`windres`），`sh` 与 Unix 工具、`xxd`；Windows 宿主需 Git Bash / MSYS2 等环境 | `.exe`；WebView 另需系统 WebView2 Runtime，loader 规则见下 |
| `linux-arm64` / `linux-x64` | Linux；与目标匹配的 `g++` / `c++` 工具链、`ar`、`xxd`、`pkg-config`、GTK ≥ 4.10 开发包；WebView 另需 `webkitgtk-6.0` 开发包 | ELF 可执行文件；目标系统需相应 GTK / WebKitGTK 共享库 |

三平台均已有产品打包入口。上表按当前实现与 [`xu doctor`](../../cmd/doctor/main.xu) 整理，不表示所有宿主、架构组合均已实机验证；先检查工具，再在目标系统验证产物。`--target` 不能替代原生 UI SDK 或交叉链接工具链。静态链接的是 Xu host，系统 UI 框架和 WebView 运行时仍是运行依赖。

`scripts/xu_desktop_pack.py` / `pack_*.py` / `xu_doctor.py` **仅 CI/调试**，不是产品入口。

用户只拿**一个**主程序。无 `--desktop` 时普通编译的 UI 二进制未链 host（stub=127），会报 `host not linked`。

Windows WebView 额外说明：Edge **WebView2 Runtime**（系统 Evergreen）不能打进 PE；NuGet 的 `WebView2LoaderStatic.lib` 仅 MSVC。MinGW pack 可从 `dist/windows-x64-ui/_build/` 选择架构匹配的 `WebView2Loader.dll`（或带架构后缀的文件）**嵌进 exe**，启动时解到 **exe 同目录**（已存在且大小一致则跳过，不进 TEMP）。`www` 与品牌图标不落盘。

Windows ARM64 从配套开发源码使用时，需要同时重建 `xu`、`xu-desktop` 和 `xu-doctor`，保持编译器、内存 mailbox 与原生宿主匹配。`xu doctor --desktop --webview --target windows-arm64` 会检查对应 MinGW 工具、`sh` 和 `xxd`；Windows 系统的 NTFS `convert.exe` 不作为 ImageMagick 使用，缺少 `magick` 时仅跳过可选 ICO 生成。

原生 Canvas 通过离屏缓冲一次提交完整帧。控件内输入代理与 Canvas 之间的焦点转移会保留弹层；真正离开 Canvas 或丢失鼠标捕获仍取消输入。设置 `XU_UI_TRACE_INPUT=1` 可记录按下、松开、取消、命中 ID 和动作结果，便于区分未命中与被取消；该诊断不记录输入文字。

公开的 Windows 回归入口为 `scripts/test_windows_workers.py`、`scripts/test_windows_controls.py` 和 `scripts/test_windows_desktop.py`（传入 `--compiler`）；`scripts/test_windows_focus.py` 使用 `--cxx` 指定本机 C++ 编译器，在模拟窗口树上验证焦点分类，不创建或操作系统窗口。桌面 shell 回归需要 Git Bash / MSYS2 的 `sh` 在 `PATH` 中。

## 内嵌 WebView 组件

`Screen.webview()` 将系统 WebView 作为 Draw 窗口的子控件。`ui.native_view()` 提供同一能力的底层句柄，`webview.bind_native()` 绑定文档与异步查询 API。macOS 使用剪裁 NSView，Windows 使用子 HWND，Linux 使用 GtkOverlay 与保留完整文档尺寸的裁剪容器。

每个子视图拥有独立 Canvas ID、generation、页面配置和请求作用域；所有事件仍由 App 的单一事件通道分发。组件关闭或父窗口销毁后，旧句柄和回调不能影响其他实例。`InvokeRequest.target()` 返回发起请求的具体组件。

HTML 从组件自己的 `xu://app/` 文档入口加载，重载保留正确来源与 IPC 路由。页面配置带修订号；空闲轮询不会反复复制大段 HTML。单份 HTML 上限为 1 MiB。文档与请求生命周期独立，默认系统 WebView 配置仍共享 Cookie 与网站存储。

原生子表面位于 Canvas 上方。Screen 在重叠的弹出菜单、Tooltip、Toast 或 Modal 显示期间暂时隐藏网页，关闭后恢复页面状态。Canvas 旋转、全局透明度、离屏 Surface 与截图不自动包含网页；Screen.snapshot 对可见原生 WebView 明确报错。网页内部 Tab 继续使用 DOM 焦点顺序，Ctrl+Tab / Ctrl+Shift+Tab 返回 Screen 的焦点链。打包须链接 WebView 插件。

原生文字布局与绘制帧中的文字引用按稳定 ID 动态登记，不按 1024 个对象分配固定槽位。释放应用句柄不会撤销绘制帧或输入会话保留的布局；关闭画布会撤销匹配 generation 的应用句柄。保留原有文本长度、坐标与字节预算检查（全局布局 32 MiB、单布局 4 MiB），这些是资源预算，不是控件数量配额。未完成的 ID 预约按期限惰性清理，分配失败返回明确错误。
