<p align="center">
  <a href="https://xulang.org"><img src="brand/xu_classic.svg" alt="Xu Logo" width="100" height="100"></a>
</p>

<h1 align="center">Xu 编程语言</h1>

<p align="center">
  <b>兼具 Go 的直观并发与 C/Rust 的无 GC 极致性能</b><br>
  <sub>专为高性能低延迟系统、微服务底层与现代轻量级应用打造的编译期内存安全语言</sub>
</p>

<p align="center">
  <a href="README.md">English</a> | <b>简体中文</b>
</p>

<p align="center">
  <a href="https://github.com/xulang-org/xu/releases"><img src="https://img.shields.io/github/v/release/xulang-org/xu?label=Release&color=0284c7" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-emerald.svg" alt="License"></a>
  <a href="https://xulang.org"><img src="https://img.shields.io/badge/Docs-xulang.org-rose" alt="Docs"></a>
  <a href="https://xulang.org/benchmarks"><img src="https://img.shields.io/badge/Benchmarks-47%20Tasks-amber" alt="Benchmarks"></a>
  <a href="https://github.com/xulang-org/xu/actions/workflows/sdk.yml"><img src="https://github.com/xulang-org/xu/actions/workflows/sdk.yml/badge.svg" alt="SDK CI"></a>
</p>

<p align="center">
  <a href="https://xulang.org">🌐 <b>在线 Playground（免安装试玩）</b></a> &nbsp;•&nbsp;
  <a href="https://xulang.org/benchmarks">⚡ <b>47 项跨语言横测看板</b></a> &nbsp;•&nbsp;
  <a href="#-零阻力快速上手-quick-start">🚀 <b>30 秒上手</b></a> &nbsp;•&nbsp;
  <a href="RELEASES.zh-CN.md">📋 <b>版本说明</b></a> &nbsp;•&nbsp;
  <a href="https://github.com/xulang-org/xu/releases">📦 <b>下载安装包</b></a>
</p>

---

> **最新正式版本**：[Xu v0.10.7](https://github.com/xulang-org/xu/releases/tag/v0.10.7) — 详细更新记录、变更与迁移指南请查阅 [版本说明 (Release Notes)](RELEASES.zh-CN.md)。

## ⚡ 一眼看懂 Xu（Show, Don't Tell）

不用繁杂的配置，也不用死记晦涩的生命周期标注。一段 15 行代码感受 Xu 的现代语法风格：

```xu
@main
#errors

// 符号化流控制：<< 代替 return，>> 抛错；告别 Result/unwrap 嵌套
fn fetch_metric(task string) int {
    if task.len == 0 { >> errors.new("empty task name") }
    << task.len * 42
}

fn worker(task string, ch chan int) {
    val := fetch_metric(task) or (err) { << } // or 强制安全捕获，无 if err != nil 铺屏
    ch <- val                                 // 管道安全传递计算结果
}

fn main() int {
    ch := chan int{cap: 2}
    xu worker("latency", ch) // xu 原生关键字启动轻量级协程
    xu worker("memory", ch)
    println(<-ch + <-ch)     // 管道汇聚输出
    << 0                     // 确定性退出，无 GC 停顿，全静态 AOT 编译
}
```

> **直观爽点**：
> 1. **符号化流控制**：`<<` 返回、`>>` 抛错、`<<<` 退出，彻底告别沉冗的关键字。
> 2. **轻量错误捕获**：调用处通过 `or (err) { ... }` 强制就地处理或传播，杜绝到处充斥的 `if err != nil` 样板代码与 `unwrap()` 崩溃风险。
> 3. **原生极简并发**：`xu worker()` 启动协程配合 `chan` 管道通信，心智像 Go 一样平易近人。
> 4. **编译期全静态安全**：基于所有权与借用推导，**无垃圾回收器（Zero-GC）**，没有 GC 停顿，内存极度精炼。

---

## 🎯 痛点与“Why Xu?”

作为开发者，我们在系统级与高并发开发中常遇到两难抉择：

### 1. 现有方案的真实痛点

- **痛点一：垃圾回收（GC）的延迟抖动与内存膨胀**
  - *现状*：Go、Java 虽然开发效率高，但 GC 的毫秒级停顿（STW）与不可预测的内存回收尖刺，在高并发低延迟网关、交易系统或嵌入式场景中往往是致命隐患。
  - *Xu 解法*：**零 GC 运行时**。全静态 AOT 编译，采用编译期所有权模型追踪生命周期，作用域结束即确定性释放，无停顿、无抖动、内存极低。
- **痛点二：内存安全与“显式生命周期标注地狱”的冲突**
  - *现状*：C/C++ 手动管理内存极易发生野指针、内存越界与 UAF；Rust 虽具备内存安全，但显式生命周期参数（`'a`, `'b`）与复杂的类型体操让心智负担极大、编译漫长。
  - *Xu 解法*：**隐式所有权推导与借用检查**。无需在业务代码中书写复杂的生命周期标记，切片天然值隔离，在保障内存安全的同时兼顾直观与极简。
- **痛点三：样板代码铺屏与沉重的错误包装**
  - *现状*：Go 代码中三分之一以上是 `if err != nil`；Rust 的 `Result<T, E>` / `map_err` / 泛型封装增加了不少阅读成本。
  - *Xu 解法*：**符号流 `>>` 配合 `or (err) { ... }`**，语言层面提供最轻量、直观且具备强制安全约束的错误流。
- **痛点四：工具链碎片化与安装繁重**
  - *现状*：构建系统需要 CMake / Make / 各种包管理器来回折腾；Windows 与交叉编译环境配置繁复。
  - *Xu 解法*：**单一二进制闭环**。内置编译器、测试运行器、格式化器与自绘原生 Setup 安装向导，零第三方依赖。

### 2. 横向硬核对比

| 核心维度 | C / C++ | Go | Rust | **Xu** |
| :--- | :--- | :--- | :--- | :--- |
| **内存管理机制** | 手动 malloc/free<br>*(易引发内存泄漏与野指针)* | 运行时垃圾回收 (GC)<br>*(存在 STW 停顿与内存膨胀)* | 编译期所有权模型<br>*(需显式生命周期标注)* | **编译期所有权<br>(零 GC / 自动确定性回收)** |
| **运行时开销** | 极低（零开销抽象） | 较重（GC 引擎 + 调度器协程栈） | 极低（零开销抽象） | **极低（零运行时 GC / 纯原生机器码）** |
| **开发心智负担** | 易产生内存越界与并发 UB | 语法平实，但 `nil` 隐患多 | 陡峭（生命周期 `'a` / 借用抗争） | **极低（无生命周期标记 / 直观符号流）** |
| **并发编程模型** | 原生线程 / 第三方库 | CSP 协程 (`go`) + 管道 (`chan`) | 线程 / Async 运行时 (引入函数染色) | **原生轻量协程 (`xu`) + 强类型管道 (`chan`)** |
| **错误处理语法** | 错误码 / 异常 *(破坏控制流)* | `if err != nil` *(样板代码冗余)* | `Result<T, E>` + `?` 运算符 | **符号流：`>>` 抛错 + `or` 强制就地安全处理** |
| **控制流表达** | `return` / `break` / `continue` | `return` / `break` / `continue` | `return` / 隐式尾表达式 | **统一符号流：`<<` 返回 / `>>` 抛错 / `<-` 跳出** |
| **工具链集成度** | 分散 (CMake/Make/Conan 拼装) | 一体化开箱即用 | 一体化 (Cargo) | **单二进制闭环 (编译/测试/格式化/文档一体化)** |
| **跨平台安装** | 需配置繁杂编译器工具链 | 安装包 / 手动配置环境变量 | 依赖 rustup / 跨平台网络脚本 | **单文件原生自绘向导 / 一键全局免配置** |

---

## 🚀 零阻力快速上手 (Quick Start)

### 选项 1：浏览器免安装秒玩

无需在本地配置任何环境，直接访问 **[xulang.org 在线演练场](https://xulang.org)**。底层由 Xu 源码直接 AOT 编译为纯客户端 WebAssembly 沙箱，即开即用。

### 选项 2：一行命令极速安装（推荐）

Xu 提供包含编译器、工具链与标准库的**单文件原生安装包**，自动持久化配置系统环境变量：

- **macOS / Linux**（终端一行命令）：
  ```bash
  # 自动检测平台下载并一键安装配置
  curl -fsSL https://xulang.org/install.sh | bash
  ```
  *或者直接在 [Releases](https://github.com/xulang-org/xu/releases) 下载独立程序执行：*
  ```bash
  chmod +x xu-setup-linux-x64 && ./xu-setup-linux-x64 -y
  ```

- **Windows**（命令行或双击自绘图形向导）：
  - **图形界面**：在 [Releases](https://github.com/xulang-org/xu/releases) 下载 `xu-setup-windows-x64.exe`，直接双击运行零依赖自绘向导，一键完成安装；
  - **PowerShell 一行命令**：
    ```powershell
    irm https://xulang.org/install.ps1 | iex
    ```

> 打开新终端，输入 `xu --version`，即可在全局任意目录调用。

### 选项 3：30 秒运行 Hello World

```bash
# 1. 创建源文件
cat << 'EOF' > main.xu
@main

fn main() int {
    println("Hello, World! Welcome to Xu.")
    << 0
}
EOF

# 2. 极速即时运行
xu run main.xu

# 3. 静态 AOT 构建优化独立机器码二进制
xu build main.xu -o myapp
./myapp
```

### 常用开发命令速查

#### 项目与依赖

| 命令 | 说明 |
| :--- | :--- |
| `xu init [module]` | 在当前目录创建 `xu.xun`，缺少 `main.xu` 时同时生成入口示例 |
| `xu get <module>@<version>` | 添加或升级精确版本依赖，安装到 `vendor/` 并更新 `xu.lock` |
| `xu install [dir]` | 安装指定项目 `xu.xun` 中已有的依赖 |
| `xu build . --frozen -o myapp` | 使用现有锁文件和本地依赖执行冻结、离线构建 |
| `xu env [var...]` | 查看工具链、标准库、依赖缓存与目标平台的有效配置 |

在含有 `xu.xun` 的项目中，执行 `xu get github.com/xulang-org/packages@v0.1.1`
即可添加官方扩展模块。依赖需要显式版本；`--offline` 使用本地缓存或 vendor，
`--frozen` 拒绝依赖变化。

#### 构建、运行与验证

| 命令 | 说明 |
| :--- | :--- |
| `xu run <file.xu> -- <args...>` | 编译并启动本机程序，`--` 后的参数传给程序 |
| `xu build <file.xu> -o <bin>` | AOT 编译为原生可执行文件；项目目录也可作为输入 |
| `xu debug <file.xu> -b file.xu:行号 --run` | 带 DWARF 构建并进入 LLDB/GDB 交互会话；可用 `-e` 预置调试器命令 |
| `xu check <file.xu>` | 仅执行解析、类型与所有权/借用检查，不生成机器码 |
| `xu parse <file.xu>` | 解析源码，输出文件、函数与声明统计 |
| `xu test <file.xu> -v` | 执行 `fn test_*` 测试并显示详细结果；可用 `-run <REGEXP>` 过滤 |
| `xu test <file.xu> -bench <REGEXP>` | 执行匹配的 `fn bench_*` 基准函数 |
| `xu build <file.xu> --target linux-x64 -o app` | 指定目标平台交叉编译，例如 Linux x64 |
| `xu build <file.xu> --target wasm32 -o app.wasm` | 生成 WebAssembly 模块 |
| `xu build <file.xu> --xacp --xacp-port 4321 -o app` | 嵌入 XACP 启动发现元数据 |
| `./app --xacp-help` | 输出生成程序的机器可读 XACP 摘要 |
| `xu xacp inspect app` | 检查启用 XACP 程序的发现信息与安全摘要 |
| `xu xacp run app -- args...` | 使用明确的 AI/用户参数边界运行程序 |
| `xu xacp record app -- > output.log` | 将有界 stdout 流式输出，由用户自行保存 |
| `xu build <AppDir> --desktop` | 打包桌面应用；需要对应宿主 UI SDK 与工具链 |
| `xu build <file.xu> --debug -o app` | 生成 DWARF 行号信息；`--debug-build` 同时关闭优化 |
| `xu build <file.xu> --timings -o app` | 查看编译阶段耗时、优化统计、后端模式命中及寄存器分配模式 |

`#xacp` 是传输无关的标准库层，用于宿主注册一个真实的
`ui/widgets.Screen`。adapter 提供有界的 `ui.tree`、由原生资源承载的
`ui.screenshot`、经过校验的 `ui.input`/`ui.act`，以及流式录制。调用这些
API 时必须携带拥有对应权限位的 session；`start_recorder` 会保持请求直到
`finish_recorder` 或 `abort_recorder`。屏幕句柄、canvas generation、节点数、
帧字节数、文本长度和录制预算都会在进入 widget 前检查。源码开发宿主可以
在 hello 握手前调用 `enable_development` 获得 `PERM_ALL`，但这不会关闭
schema、生命周期、原生资源释放或内存上限。截图返回拥有所有权的
`draw.Surface`，宿主交给自己的资源层后必须显式 dispose。

0.9.4 还提供 `XU_VERIFY=1` 逐 pass MIR 验证、`XU_DUMP_MIR=<函数名>`
与 `XU_PATTERNS_OFF=all` 模式对拍诊断。完整选项见[命令行参考](https://xulang.org/zh/docs/cli/)。

#### 开发工具与工具链管理

| 命令 | 说明 |
| :--- | :--- |
| `xu fmt <file.xu> -w` | 原地格式化源码；省略 `-w` 时输出到终端 |
| `xu doc <dir> --public` | 提取公开声明，生成 Markdown API 文档；`--serve` 启动本地文档服务 |
| `xu map <dir> -o flow.md` | 生成 Mermaid 源码流程图；`--graph` 输出结构化图数据 |
| `xu doctor` | 检查宿主工具链；`--desktop --webview` 检查桌面与 WebView 依赖 |
| `xu native <command> [options]` | 编译、归档 C 模块，打包、检视或提取 `.xulib` 平台切片 |
| `xu lsp` | 启动标准输入/输出上的 LSP 服务，供 VS Code、Cursor、Neovim 等编辑器调用 |
| `xu setup -y` | 静默安装并配置工具链环境 |
| `xu up --check` | 仅检查官方发布版本；`xu up` 与 `xu update` 为同义命令 |
| `xu update --version 0.9.4` | 安装指定版本的官方工具链 |
| `xu update --version 0.9.4 --archive release.tar.gz --prefix DIR` | 从本地 SDK 归档安装，无需联网 |
| `xu --version` | 显示实际编译器版本及宿主目标 |
| `xu help <command>` | 查看子命令帮助，也可使用 `<command> --help` |

自更新由独立工具 `xu-update`（`src/cmd/update`）执行，HTTPS、gzip、tar、ZIP 和文件操作使用 Xu 标准库。可通过 `make xu-update` 构建，发布 SDK 默认包含此工具。`xu-setup` 共用 `internal/sdk` 下载与解包代码。下载时实时显示已下载量；服务器提供总大小时同时显示百分比，安装向导也会更新进度条。 安装向导使用 `ui/layout` 与 `ui/widgets` 的标准组件，自动识别安装位置，支持键盘操作和失败重试。默认沿用 PATH 中现有 SDK，首次安装使用 `~/.xu`。Windows 可选择当前用户或所有用户，系统安装会请求管理员授权；命令行仍支持 `--prefix DIR`。

---

## 🗺️ 项目路线图 (Roadmap)

以下以 **0.10.7 正式 SDK** 为基线，区分已交付能力与后续工作。各目标的运行边界见[限制与现状](https://xulang.org/zh/docs/status/)。

- [x] **纯 Xu 自举与原生 AOT**：以已发布 Xu SDK 为种子，验证自举固定点；直接生成原生机器码与 WebAssembly
- [x] **编译期所有权与借用推导**：确定性资源回收；0.9.4 补齐嵌套表达式与循环回边的借用检查
- [x] **原生协程与管道并发**：`xu` 关键字轻量调度 + 强类型 `chan` 信道机制；100/100 轮多任务并发 select 门禁收口
- [x] **国密算法完整性与工程收口**：SM2/SM3/SM4/SM9 算法全量通过；SM9 双线性对栈帧压降 71.5% 且零编译告警
- [x] **极简符号流控制**：`<<` 返回、`>>` 抛错与 `or (err) { ... }` 强制就地处理
- [x] **多平台代码生成**：Windows / macOS / Linux、ARM64 / x64 / LoongArch64 / RISC-V / ARM32、WASM 及裸机目标
- [x] **SDK 安装与自更新**：Windows 安装向导、macOS PKG、跨平台单文件 Setup 与 `xu up/update`
- [x] **可复现模块依赖**：`init/get/install`、MVS、锁文件/vendor、代理、离线/冻结构建与固定公钥校验客户端
- [x] **LSP 与编辑器集成**：`xu-lsp`、VS Code/Cursor 扩展；诊断、补全、定义、悬停、大纲、引用、重命名与格式化
- [x] **泛型与 SSA 优化基础**：泛型单态化、移除 4 类型参数限制、标量 SSA 提升、ARM64 SSA 循环内核与循环旋转
- [x] **编译器诊断与验证**：逐 pass MIR 验证、MIR 导出、模式命中统计与具名模式开关
- [x] **主流基础设施生态包**：独立 packages 模块提供 MySQL、Postgres、Redis、ClickHouse、Kafka、SQLite 等 29 个扩展包
- [x] **可追溯的跨语言横测**：47 项负载、六个 ARM64/x86-64 平台，保留实际编译器版本、来源与输出校验
- [x] **集成交互式源代码调试器**：`xu debug` 支持 DWARF 源码断点、调用栈与 LLDB/GDB 强类型局部变量检视及自动化批处理模式
- [x] **优化器进一步扩展**：结构体 Record SSA 标量提升准入证明闭环、TVM 风格 Tile 切块规划、低比特 LUT-GEMM 与算子流水线融合
- [ ] **完整目标机运行验收**：原生 SDK 安装门禁覆盖 macOS ARM64/x64、Linux ARM64/x64 与 Windows x64/ARM64；继续补齐各目标的库、网络、并发和桌面运行检查。LoongArch64 与 RISC-V SDK 通过交叉编译交付。
- [ ] **公共包基础设施**：固定公钥校验、MVS 与代理/vendor 客户端已实现；公共代理/校验服务及独立见证仍需单独部署与可用性验收。

---

## 🌟 加入社区与支持我们

Xu 是一门开放透明、面向未来的现代系统编程语言。如果你也认同“**无 GC 的极致性能 + 直观极简的心智体验**”，欢迎加入我们！

- ⭐ **Star 支持**：如果 Xu 给你带来了启发，请在 [GitHub 仓库](https://github.com/xulang-org/xu) 右上角点一颗 **Star**，这是对我们最大的激励！
- 💬 **反馈与讨论**：有任何特性建议或发现 Bug？欢迎提交 [GitHub Issues](https://github.com/xulang-org/xu/issues) 与核心开发团队直接交流。
- 📊 **横测大看板**：了解更多关于 CPU 吞吐与内存占用的严苛对比，详见 [xulang.org/benchmarks](https://xulang.org/benchmarks)。
- 📚 **完整文档**：查阅详尽的语法手册与进阶示例，请访问 [xulang.org 官方网站](https://xulang.org)。

---

## 开源协议

Xu 编程语言基于 [MIT 许可证](LICENSE) 开源。
