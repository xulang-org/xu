# Xu 开发者目录

<p align="center"><img src="../brand/xu_classic.svg" alt="Xu" width="88" height="88"></p>

面向日常写代码的**语言特色**、**使用帮助**与**可运行示例**。语法定稿以 [`docs/LANGUAGE.md`](../docs/LANGUAGE.md) 为准；本目录是薄教程，不替代规范。

参与本仓库开发前，所有开发者和 agent 必须阅读 [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md)：修改模块内容必须同步递增模块根 `xu.xun` 的 `version:`，并通过版本检查后交付。

涉及 Xu 产品修改时，还必须同步递增根 `VERSION`、更新当前发行相关版本、重建交付产物并通过发布身份检查。只更新模块版本或源码版本，不代表实际 Xu 二进制版本已同步；重建待完成必须在交付中注明。

发布 Xu 时，所有当前模块 `xu.xun` 的 `xu:` 必须统一对齐根 `VERSION`。用 `make xu BUMP=patch`（或 `minor` / `major`）先同步再构建；只补齐现有发布版本用 `make release-version-sync`，检查用 `make release-version-check`。

## 语言特色（先看这个）

Xu = **静态 AOT 一键编译部署** + **无 GC 的所有权安全** + **极简语法**。 
一眼能认出的记号：`<<` 返回、`>>`/`or` 错误、`#errors` 导入、默认不可变、`struct@` / `名字#` 泛型分流。

完整说明：[`FEATURES.md`](FEATURES.md)。

## 预编译编译器

各平台产品 `xu` 已放在 [`bin/`](bin/)，命名 `xu.<os>.<arch>`：

| 文件 | 对应 `--target` |
|------|-----------------|
| [`bin/xu.macos.arm64`](bin/xu.macos.arm64) | `macos-arm64` |
| [`bin/xu.macos.x64`](bin/xu.macos.x64) | `macos-x64` |
| [`bin/xu.linux.arm64`](bin/xu.linux.arm64) | `linux-arm64` |
| [`bin/xu.linux.x64`](bin/xu.linux.x64) | `linux-x64` |
| [`bin/xu.linux.loongarch64`](bin/xu.linux.loongarch64) | `linux-loongarch64` |
| [`bin/xu.linux.riscv64`](bin/xu.linux.riscv64) | `linux-riscv64` |
| [`bin/xu.windows.x64.exe`](bin/xu.windows.x64.exe) | `windows-x64` |
| [`bin/xu.windows.arm64.exe`](bin/xu.windows.arm64.exe) | `windows-arm64` |

说明与重打包：[`bin/README.md`](bin/README.md)。重打包命令：`./scripts/pack_developer_xu.sh`（需先有可用的 `./bin/xu`）。

本机（Apple Silicon）可直接：

```bash
XU=./bin/xu
```

`./bin/xu` 是与当前 `src/` 配套的产品编译器；`developer/bin/xu.*` 是历史快照，仅在对应版本的源码上使用。也可用仓库根 `make xu` 得到 `./bin/platform/<os>-<arch>/xu`（各托管目标）。

## 独立仓库

- [`xu-examples`](../../xu-examples)：教程与示例。
- [`xu-bench`](../../xu-bench)：完整基准与横测。
- [`xu-site`](../../xu-site)：官方网站。

`XU_EXAMPLES_ROOT`、`XU_BENCH_ROOT`、`XU_SITE_ROOT` 可指定其他目录。

## 怎么跑示例

在仓库根选一个平台二进制（下例用 macOS arm64），再编示例：

```bash
XU=./bin/xu
$XU build ../xu-examples/examples/01_hello/main.xu
./main.xin
# 或：$XU build … -o /tmp/xu_hello && /tmp/xu_hello.xin
```

默认产物 mac/linux 为 `.xin`（已可执行）；Windows 为 `.exe`。PowerShell 请用 `--output`。

只做检查：

```bash
$XU check ../xu-examples/examples/01_hello/main.xu
```

每个示例子目录的 `README.md` 里有该示例的完整编译命令。

## 内容索引

| 文档 / 示例 | 内容 |
|-------------|------|
| [`FEATURES.md`](FEATURES.md) | **语言特色**（定位、记号、内存、工程形态） |
| [`USAGE.md`](USAGE.md) | 语言使用帮助（按主题） |
| [`bin/`](bin/) | 各平台预编译 `xu.<os>.<arch>` |
| [`examples/01_hello`](../../xu-examples/examples/01_hello) | 最小程序 |
| [`examples/02_bindings`](../../xu-examples/examples/02_bindings) | 绑定、`mut`、`const` |
| [`examples/03_control_flow`](../../xu-examples/examples/03_control_flow) | if / for / while / match / `<-` `->` |
| [`examples/04_functions_methods`](../../xu-examples/examples/04_functions_methods) | 函数、struct、方法 |
| [`examples/05_errors`](../../xu-examples/examples/05_errors) | `>>` + `or` 错误处理 |
| [`examples/06_ownership_borrow`](../../xu-examples/examples/06_ownership_borrow) | 所有权与借用 |
| [`examples/07_arrays_strings`](../../xu-examples/examples/07_arrays_strings) | 数组、字符串、插值 |
| [`examples/08_enum_match`](../../xu-examples/examples/08_enum_match) | enum 与 match |
| [`examples/09_generics_temp`](../../xu-examples/examples/09_generics_temp) | 泛型、`struct@`、`temp` |
| [`examples/10_concurrency`](../../xu-examples/examples/10_concurrency) | `xu` 协程与 `chan` |
| [`examples/16_ui_webview/xu_design_system`](../../xu-examples/examples/16_ui_webview/xu_design_system) | 设计系统静态 HTTP 服务（见 [`server-deployment.md`](../docs/server-deployment.md)） |
| [`examples/19_native_c`](../../xu-examples/examples/19_native_c) | C/XUNATIVE 多目标静态模块 POC |

## 相关文档

| 路径 | 职责 |
|------|------|
| [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md) | 开发强制规则、模块版本递增与交付检查（所有开发者和 agent 必须遵守） |
| [`docs/LANGUAGE.md`](../docs/LANGUAGE.md) | 语言面完整规划与定稿 |
| [`architecture.md`](../architecture.md) | 设计愿景与鸟瞰 |
| [`docs/BOOTSTRAP.md`](../docs/BOOTSTRAP.md) | 自举与编译器工程 |
| [`Makefile`](../Makefile) | `make xu` / `make fixtures` 等 |
| [`docs/server-deployment.md`](../docs/server-deployment.md) | 本地/Linux HTTP 服务构建、健康检查与部署模板 |
