# 参与 Xu 开发

本仓库遵守 [XU GitHub 仓库管理规范](https://github.com/xulang-org/xulang-org/blob/main/.github/REPOSITORY_RULES.md)。分支、版本、PR、文档与发布要求以统一规范为基线；本文件补充编译器的实际入口。

XU 源码还须遵守 [XU 代码规范](.github/XU_CODING_STANDARDS.md)；涉及配套语言或跨语言接口时，按各语言工具链及其中的边界契约验证。

Agent 任务、人工编写的 agent prompt 及自动化任务模板须遵守 [Agent 提示规则](.github/AGENT_PROMPT_RULES.md)，细则以 [XUN 正文](.github/AGENT_PROMPT_RULES.xun) 为准。

日常产品开发从 `dev` 建立任务分支，通过 PR 合回 `dev`；正式验收后才进入 `main`。开发版本保留 `-dev.N`，候选版保留 `-rc.N`。独立的仓库规则和贡献文档可走规范中的维护 PR。后台门禁是否启用另按 [配置清单](https://github.com/xulang-org/xulang-org/blob/main/.github/GITHUB_SETTINGS.md) 验收，不能从文档存在推定保护生效。

## 修改与验证

从仓库根运行。修改前确认受影响的模块、当前 `VERSION`、模块 `version:` 以及本批是否已经递增。产品改动同步产品版本；模块内容变化同步模块版本；纯治理文件不递增产品版本。

```sh
python3 scripts/module_versions.py --check
make release-version-check
```

跨提交或检查整个 PR 时，将版本检查与本批改动之前的基准比较：

```sh
python3 scripts/module_versions.py --check --base <base-revision>
```

涉及编译器、标准库或产品工具时，使用已验证的 Xu 产品种子重建，并运行本次变化适用的自举、功能、安装或平台验收：

```sh
make xu
python3 scripts/check_release_identity.py --require-cli
```

普通 `make xu` 不递增版本；版本准备和产物重建是不同步骤，不重复执行递增入口。实际可用的构建与检查目标见 `make help`。不能用历史 Rust 引导实现代替产品编译器证据。

远端验证使用仓库公开源码契约、自举与 SDK 安装验收；完整研发回归遵守本机约定。不要为修复 CI 上传本机 `docs/`、`tests/`、agent 配置或过程记录。公开的 GitHub Pages 落地页只允许跟踪 `docs/index.html`、`docs/.nojekyll` 和 `docs/assets/` 里的两份品牌图；其余 `docs/` 仍是本机材料。仅修改规则和模板时，检查文档、链接、表单及模板一致性，不要求无关的产品重建。

## 提交 PR

PR 写明问题与行为变化、最小复现或验收条件、兼容性、产品及模块版本变化、实际执行的检查、已知限制和回滚方法。关联跨仓库依赖时列出完整提交及合并顺序。未执行、失败或受环境阻塞的检查必须如实标注。

提交前逐项审查明确的暂存路径，并运行：

```sh
git diff --cached --stat
git diff --cached
python3 scripts/check_git_hygiene.py --staged
```

提交或推送不等同于发布授权；创建可触发发行的标签前，须先完成统一规范的发布检查。
