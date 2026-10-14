# Xu 编程语言

Xu 是一门静态类型、原生 AOT 编译、无 GC 的编程语言，通过所有权和借用管理内存。SDK 提供编译器、配套工具、标准库和官方示例，解压即可使用，也可以安装到用户目录。

当前源码版本见 [VERSION](VERSION)。下载版本以 [Releases](https://github.com/xulang-org/xu/releases) 和包内 `VERSION` 为准；包内 `TARGET` 记录平台，`bundle.json` 记录产品来源与二进制 SHA-256。

- [官网与文档](https://xulang.org)
- [Installed SDK 工作流](https://github.com/xulang-org/xu/actions/workflows/sdk.yml)
- [问题反馈](https://github.com/xulang-org/xu/issues)

## 开发版与正式版

Xu 与编译器使用同一个完整版本号：开发调试版为 `0.8.8-dev.1`、`0.8.8-dev.2`；发布候选版为 `0.8.8-rc.1`；验收后的正式版为 `0.8.8`。持续调试递增后缀计数，进入下一个正式版本周期时再递增三段数字。

GitHub 的开发版和候选版标记为 **Pre-release**。默认 `xu update` 获取正式发布；需要调试版时显式执行 `xu update --version 0.8.8-dev.1`。已发布的标签和安装包不覆盖，修复后使用新的开发版序号。这里的“正式发布”仍属于 `0.8.x`，不代表语言已经进入 `1.0` 稳定阶段。

版本维护命令：

```bash
# 从上一正式版本开始新一轮开发，例如 0.8.8 → 0.8.8-dev.1
python3 scripts/module_versions.py --release-bump patch --channel dev
# 同一轮开发：dev.1 → dev.2，或 rc.1 → rc.2
python3 scripts/module_versions.py --next-prerelease
# dev.N → rc.1
python3 scripts/module_versions.py --promote rc
# rc.N → 同号正式版，仅在验收通过并决定发布后执行
python3 scripts/module_versions.py --promote stable
```

这些命令同步 `VERSION`、编译器 `version:` / `xu:`、所有当前模块的 Xu 要求与产品横幅；其他模块自身的 `version:` 保持独立。改动后仍需重建并验证实际二进制与安装包。

## 下载 SDK 与 Setup 安装包

在 [Releases](https://github.com/xulang-org/xu/releases) 下载对应平台的 Setup 安装程序、SDK 归档包和 `SHA256SUMS`。后续所有版本均默认发布单文件离线 Setup 安装包，内嵌完整编译器、工具链与标准库源码，自动配置系统全局环境变量。

| 操作系统 / CPU | 平台 | 推荐 Setup 安装程序 (单文件离线包) | SDK 完整源码归档 |
| --- | --- | --- | --- |
| Windows / x86-64 | `windows-x64` | `xu-v<版本>-windows-x64-setup.exe` (双击运行图形向导) | `xu-v<版本>-windows-x64.zip` |
| Windows / ARM64 | `windows-arm64` | `xu-v<版本>-windows-arm64-setup.exe` | `xu-v<版本>-windows-arm64.zip` |
| macOS / Apple Silicon | `macos-arm64` | `xu-v<版本>-macos-arm64.pkg` (双击安装) 或 `xu-setup-macos-arm64` | `xu-v<版本>-macos-arm64.tar.gz` |
| macOS / Intel | `macos-x64` | `xu-setup-macos-x64` | `xu-v<版本>-macos-x64.tar.gz` |
| Linux / x86-64 | `linux-x64` | `xu-setup-linux-x64` (赋权后直接 `./xu-setup-linux-x64 -y`) | `xu-v<版本>-linux-x64.tar.gz` |
| Linux / ARM64 | `linux-arm64` | `xu-setup-linux-arm64` | `xu-v<版本>-linux-arm64.tar.gz` |
| Linux / LoongArch64 | `linux-loongarch64` | `xu-setup-linux-loongarch64` | `xu-v<版本>-linux-loongarch64.tar.gz` |
| Linux / RISC-V 64 | `linux-riscv64` | `xu-setup-linux-riscv64` | `xu-v<版本>-linux-riscv64.tar.gz` |

Releases 中同时提供带版本号文件（如 `xu-v<版本>-windows-x64-setup.exe`）及标准别名（如 `xu-setup-windows-x64.exe`）。也可以打开 Installed SDK 工作流，选择安装验收已通过的平台，从 Artifacts 下载 `xu-sdk-product-<平台>`。

Actions Artifact 是外层 ZIP，解压后在 `dist/sdk-ci/` 找到 SDK 压缩包、`SHA256SUMS` 与 `RELEASE_MANIFEST.md`，再解压 SDK 压缩包。SDK 顶层目录为 `xu-v<版本>/`；不同平台使用各自的解压目录。

以下解压示例使用已发布的 `0.8.3`，下载其他版本时替换文件名和目录中的版本号。

## 校验与解压

在压缩包与 `SHA256SUMS` 所在目录执行。

macOS：

```bash
shasum -a 256 -c SHA256SUMS
tar -xzf xu-v0.8.3-macos-arm64.tar.gz
cd xu-v0.8.3
```

Linux（x86-64）：

```bash
sha256sum -c SHA256SUMS
tar -xzf xu-v0.8.3-linux-x64.tar.gz
cd xu-v0.8.3
```

Windows（PowerShell，x64）：

```powershell
Get-FileHash .\xu-v0.8.3-windows-x64.zip -Algorithm SHA256
Expand-Archive .\xu-v0.8.3-windows-x64.zip -DestinationPath .
Set-Location .\xu-v0.8.3
```

Windows 的 Hash 应与 `SHA256SUMS` 中同名文件的完整哈希一致。

## SDK 内容

| 路径 | 内容 |
| --- | --- |
| `bin/` | `xu`、`xu-doctor`、`xu-fmt`、`xu-doc`、`xu-map`、`xu-desktop`；Windows 使用 `.exe` 扩展名 |
| `src/` | 标准库与运行时支撑源码 |
| `packages/` | 可选外部包，来自独立的 [packages 仓库](https://github.com/xulang-org/packages) |
| `examples/` | 官方教程与示例，来自独立的 [examples 仓库](https://github.com/xulang-org/examples) |
| `include/` | C 原生接口头文件 `xu_native.h` |
| `xu-setup` / `xu-setup.exe` | 原生安装程序（零依赖、自动注册全局环境变量） |
| `editors/` | 编辑器资源，内容取决于打包输入 |
| `install.sh` / `install.ps1` | 兼容安装脚本 |
| `env.sh` / `env.ps1` | 当前终端环境激活脚本 |
| `uninstall.sh` / `uninstall.ps1` | 卸载脚本 |
| `README.md`、`VERSION`、`TARGET`、`bundle.json` | 安装说明、版本、平台与校验元数据 |

VS Code 扩展独立发布，见 [vscode 仓库](https://github.com/xulang-org/vscode)。

## 解压后直接使用

在 SDK 目录中激活当前终端。

macOS / Linux（Bash）：

```bash
source ./env.sh
xu --version
xu run "$XU_ROOT/examples/01_hello/main.xu"
```

Windows（PowerShell）：

```powershell
. .\env.ps1
xu --version
xu run "$env:XU_ROOT\examples\01_hello\main.xu"
```

激活脚本设置 `PATH`、`XU_ROOT`、`XU_STDLIB_ROOT` 和 `XUPATH`，保留已有包搜索路径；重开终端后再次激活。

## 原生 Setup 安装程序（推荐全局安装）

Xu 提供纯原生安装程序（无需安装 Python、解压工具或调整 PowerShell 脚本策略），单文件离线安装，自动持久化注册操作系统全局环境变量。在 Releases 中可直接下载独立安装包，也可在下载解压后的 SDK 目录中执行 `xu-setup`。

### Windows

下载 `xu-v<版本>-windows-x64-setup.exe` 或 `xu-setup-windows-x64.exe`：
- **图形向导**：直接双击运行，启动零依赖原生自绘界面，一键完成安装。
- **命令行静默安装**：
  ```cmd
  xu-v<版本>-windows-x64-setup.exe -y
  ```

安装程序会自动将 `bin` 路径注册到用户注册表 `HKCU\Environment\Path` 并配置 `XU_ROOT`。重新打开任意终端（CMD / PowerShell / Terminal / VS Code）即可全局直接使用 `xu`。

### macOS

- **官方 PKG 安装包**：下载 `xu-v<版本>-macos-arm64.pkg`，双击启动图形安装向导，自动配置 `/etc/paths.d/xu`，全局立即可用。
- **免提权原生程序**：下载 `xu-setup-macos-arm64`（或在解压的 SDK 目录下执行 `./xu-setup`）：
  ```bash
  chmod +x xu-setup-macos-arm64
  ./xu-setup-macos-arm64 -y
  ```

### Linux

下载对应架构的 `xu-setup-linux-x64`（或 `xu-setup-linux-arm64`），赋予权限后执行：

```bash
chmod +x xu-setup-linux-x64
./xu-setup-linux-x64 -y
```

自动解压并写入用户 Shell 环境配置（`~/.bashrc` / `~/.zshrc`），全局生效。

### 自定义选项

所有平台的原生 Setup 安装程序均支持以下参数：

```bash
# 指定安装目录 (默认 ~/.xu 或 %USERPROFILE%\.xu)
./xu-setup --prefix "$HOME/my-xu" -y

# 强制控制台命令行交互 (Windows 下跳过自绘图形向导)
.\xu-setup.exe --cli

# 查看帮助
./xu-setup --help
```

自动化 CI 脚本中亦可继续使用 `bash ./install.sh` 或 `.\install.ps1`。

原生 FFI 和桌面 UI 打包需要平台 C 工具链、链接器与 UI SDK。执行 `xu doctor` 检查依赖。

## 第一个程序

在项目目录新建 UTF-8 编码的 `main.xu`：

```xu
@main

fn main() int {
    println("Hello, Xu!")
    << 0
}
```

```bash
xu check main.xu
xu run main.xu
xu build main.xu -o hello
```

编译后，macOS / Linux 执行 `./hello`，Windows 执行 `.\hello.exe`。其他常用命令：

```bash
xu fmt main.xu -w
xu test test_main.xu
xu doc . --public
xu map .
xu build --debug-build main.xu
xu --help
```

保留完整 SDK 目录结构，编译器即可从 `bin/` 旁的 `src/` 查找标准库。外部包必须在项目的 `xu.xun` 中声明依赖；packages 使用统一根模块 `github.com/xulang-org/packages`，内部包路径如 `github.com/xulang-org/packages/mysql`。`XUPATH` 不能替代依赖声明。

## 卸载与反馈

默认安装目录的卸载方式：

```bash
bash "$HOME/.xu/uninstall.sh"
```

```powershell
& "$HOME\.xu\uninstall.ps1"
```

自定义目录使用 Unix 的 `XU_INSTALL_DIR` 或 PowerShell 的 `-Prefix` 指定卸载位置。仅解压使用时，关闭已激活的终端后删除解压目录。

Xu 仍处于 `0.x` 阶段。反馈问题时请提供安装包文件名、`xu --version` 输出、操作系统与 CPU 架构、最小复现源码、执行命令及完整错误信息。
