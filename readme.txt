Xu 编程语言 · 首发安装包使用说明
版本：0.8.3
============================================================

Xu 是一门静态类型、原生 AOT 编译、无 GC 的编程语言，通过所有权
和借用管理内存。安装包提供编译器、配套工具、标准库和官方示例，
解压即可使用，也可以安装到用户目录。

本文对应 GitHub Actions 的 Installed SDK 工作流生成的产品 SDK。
包内 VERSION 记录版本，TARGET 记录平台，bundle.json 记录产品
来源（lane: product）和工具二进制的 SHA-256。

官网与文档：https://xulang.org
CI 安装包：https://github.com/xulang-org/xu/actions/workflows/sdk.yml
版本发布页：https://github.com/xulang-org/xu/releases
问题反馈：https://github.com/xulang-org/xu/issues


1. 下载对应平台的安装包
------------------------------------------------------------

打开 GitHub 仓库的 Actions，选择 Installed SDK，再进入对应版本
的运行记录。选择已通过“Package and test the installed SDK”步骤
的平台，在 Artifacts 中下载 xu-sdk-product-<平台>。

当前 CI 生成以下六种安装包：

操作系统 / CPU         平台             SDK 文件名
macOS / Apple Silicon  macos-arm64      xu-v0.8.3-macos-arm64.tar.gz
macOS / Intel          macos-x64        xu-v0.8.3-macos-x64.tar.gz
Linux / ARM64          linux-arm64      xu-v0.8.3-linux-arm64.tar.gz
Linux / x86-64         linux-x64        xu-v0.8.3-linux-x64.tar.gz
Windows / ARM64        windows-arm64    xu-v0.8.3-windows-arm64.zip
Windows / x86-64       windows-x64      xu-v0.8.3-windows-x64.zip

例如，Apple Silicon Mac 下载 xu-sdk-product-macos-arm64，
普通 Intel / AMD Windows 电脑下载 xu-sdk-product-windows-x64。

从 GitHub 网页下载的 Artifact 是外层 ZIP。先解压该 ZIP，再进入
dist/sdk-ci/，可以找到对应的 SDK 压缩包、SHA256SUMS 和
RELEASE_MANIFEST.md。SDK 压缩包需要再解压一次。

CI 会保留失败运行的诊断产物，使用前应确认该平台的安装测试通过。
当前工作流上传 Actions Artifacts；正式发布后，也可从 Releases
下载相同命名的 SDK 文件及校验文件。


2. 校验与解压
------------------------------------------------------------

在 SDK 压缩包与 SHA256SUMS 所在目录操作。

macOS 校验：

    shasum -a 256 -c SHA256SUMS

Linux 校验：

    sha256sum -c SHA256SUMS

Windows 校验（PowerShell，以 x64 为例）：

    Get-FileHash .\xu-v0.8.3-windows-x64.zip -Algorithm SHA256

将输出的 Hash 与 SHA256SUMS 中同名文件的完整哈希比较。

macOS 解压示例（Apple Silicon）：

    tar -xzf xu-v0.8.3-macos-arm64.tar.gz
    cd xu-v0.8.3

Linux 解压示例（x86-64）：

    tar -xzf xu-v0.8.3-linux-x64.tar.gz
    cd xu-v0.8.3

Windows 解压示例（PowerShell，x64）：

    Expand-Archive .\xu-v0.8.3-windows-x64.zip -DestinationPath .
    Set-Location .\xu-v0.8.3

其他架构替换压缩包文件名即可。六种 SDK 的顶层目录均为
xu-v0.8.3/；每种平台解压到各自的目录，使用本机对应的包。


3. 安装包内容
------------------------------------------------------------

    bin/               xu、xu-doctor、xu-fmt、xu-doc、xu-map、xu-desktop
    src/               标准库与运行时支撑源码
    packages/          数据库、存储和消息等外部模块
    examples/          官方教程与可运行示例
    include/           C 原生接口头文件 xu_native.h
    editors/           编辑器资源目录（内容取决于打包输入）
    install.sh         macOS / Linux 安装脚本
    install.ps1        Windows 安装脚本
    env.sh             Bash 当前终端环境激活脚本
    env.ps1            PowerShell 当前终端环境激活脚本
    uninstall.sh       macOS / Linux 卸载脚本
    uninstall.ps1      Windows 卸载脚本
    README.md          包内使用说明
    VERSION            Xu 版本
    TARGET             包的操作系统与 CPU 架构
    bundle.json        包元数据与二进制校验信息

Windows 的 bin/ 工具使用 .exe 扩展名。
当前 SDK CI 检出 packages 和 examples，将它们打入安装包；
VS Code 扩展独立发布，当前 SDK CI 未检出 vscode 仓库，扩展可从
https://github.com/xulang-org/vscode 获取。


4. 解压后直接使用
------------------------------------------------------------

在解压后的 xu-v0.8.3/ 目录执行环境激活，无需安装。

macOS / Linux（Bash）：

    source ./env.sh
    xu --version
    xu run "$XU_ROOT/examples/01_hello/main.xu"

Windows（PowerShell）：

    . .\env.ps1
    xu --version
    xu run "$env:XU_ROOT\examples\01_hello\main.xu"

激活只影响当前终端；重开终端后再次激活。脚本设置 PATH、XU_ROOT、
XU_STDLIB_ROOT 和 XUPATH，并保留已有的包搜索路径。


5. 安装到用户目录
------------------------------------------------------------

在解压后的 xu-v0.8.3/ 目录执行。

macOS / Linux：

    bash ./install.sh
    source "$HOME/.xu/env.sh"
    xu --version

Windows（PowerShell）：

    .\install.ps1
    . "$HOME\.xu\env.ps1"
    xu --version

默认安装目录为用户目录下的 .xu。Unix 安装程序配置终端启动文件，
Windows 安装程序配置用户环境变量。安装后在当前终端激活环境，
或重开终端。

自定义安装目录并自行管理终端环境：

    macOS / Linux（Bash）：
    bash ./install.sh --prefix "$HOME/xu-sdk" --no-modify-path
    source "$HOME/xu-sdk/env.sh"

    Windows（PowerShell）：
    .\install.ps1 -Prefix "$HOME\xu-sdk" -NoModifyPath
    . "$HOME\xu-sdk\env.ps1"

原生 FFI 和桌面 UI 打包需要平台 C 工具链、链接器和 UI SDK。
安装后可执行 xu doctor 查看对应依赖。


6. 编写第一个程序
------------------------------------------------------------

激活环境后，在自己的项目目录中新建 main.xu（UTF-8）：

    @main

    fn main() int {
        println("Hello, Xu!")
        << 0
    }

执行：

    xu check main.xu
    xu run main.xu
    xu build main.xu -o hello

运行编译结果：macOS / Linux 使用 ./hello，Windows 使用 .\hello.exe。
程序输出 Hello, Xu!。默认可执行文件在 macOS / Linux 上无扩展名，
Windows 上使用 .exe。

其他常用命令：

    xu fmt main.xu -w               格式化并写回
    xu test test_main.xu            执行 fn test_* 测试
    xu doc . --public              生成公开声明文档
    xu map .                       生成源码结构图
    xu build --debug-build main.xu  关闭优化并生成适用目标的调试信息
    xu --help                      查看完整命令说明

标准库从 bin/ 旁的 src/ 查找，保留完整 SDK 目录结构即可使用。
packages 中的外部模块需在项目 xu.xun 的 require: 中声明；
其根模块身份为 github.com/xulang-org/packages，内部包例如
github.com/xulang-org/packages/mysql。XUPATH 不能替代依赖声明。


7. 卸载与反馈
------------------------------------------------------------

默认安装目录的卸载方式：

    macOS / Linux：bash "$HOME/.xu/uninstall.sh"
    Windows：     & "$HOME\.xu\uninstall.ps1"

自定义安装目录使用 XU_INSTALL_DIR（Unix）或 -Prefix（Windows）
指定卸载位置。仅解压使用时，关闭已激活的终端后删除解压目录。

Xu 仍处于 0.x 阶段。反馈问题时请附上安装包文件名、xu --version
输出、操作系统与 CPU 架构、最小复现源码、执行命令及完整错误信息。
