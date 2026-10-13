# Xu 本机仓库布局

`xu` 管理编译器、标准库、运行时和产品测试。`bootstrap` 独立管理冻结的 Rust Gen0 primer 与 oracle。`vscode` 独立管理 VS Code 语法高亮扩展。`packages` 独立管理外部模块；`examples`、`bench`、`xulang-org` 分别管理示例、基准和站点。

七个仓库放在同一父目录，各自使用自己的 Git 仓库。可通过 `XU_PACKAGES_ROOT`、`XU_EXAMPLES_ROOT`、`XU_BENCH_ROOT`、`XU_SITE_ROOT`、`XU_BOOTSTRAP_ROOT`、`XU_VSCODE_ROOT` 覆盖位置；伙伴仓库使用 `XU_ROOT` 定位编译器。旧的 `xu-packages`、`xu-examples`、`xu-bench`、`xu-site` 目录名继续作为查找后备。

产品构建不调用 Rust bootstrap；冻结边界检查仍需要 bootstrap checkout。核心 `make xu` 不依赖 packages、examples、bench 、xulang-org 或 vscode。`make packages-test` 显式执行 packages 的产品回归，扩展安装和打包仅复制模块目录，不复制伙伴仓库的 Git 元数据、本机文档或测试目录。没有 packages 时仍可安装核心工具链；需要扩展时通过项目 `require:` 声明。

packages 采用单一根模块 `github.com/xulang-org/packages`，版本从 `0.1.0` 开始；mysql 等内部包的导入路径为 `github.com/xulang-org/packages/mysql`，不再维护独立清单。其他仓库的模块保留独立 `version:`。产品编译器版本与 Xu 根 `VERSION` 一致，当前属于 `0.8.x`；packages 根模块版本独立于 Xu 发布总版本。

bootstrap 默认位于 `../bootstrap`，历史 `../xu-bootstrap` 和嵌套源码归档作为查找后备。`make bootstrap` / `bootstrap-release` / `bootstrap-e2e` 使用独立仓库的 Cargo workspace。`BOUNDARY.json` 内的 `bootstrap/` 是跨仓库逻辑路径；冻结门禁分别检查两个仓库的路径边界与 bootstrap 的 Git 索引。

vscode 默认位于 `../vscode`，历史 `../xu-vscode` 和 `editors/vscode` 源码归档作为后备。扩展版本独立于 Xu，仓库根执行 `npm ci` / `npm run package`。发行包仍使用 `editors/vscode/` 布局，只选择当前版本的 VSIX 和公开元数据，不复制 Git、依赖和本机配置；扩展缺席时核心构建、安装与版本检查照常运行。
