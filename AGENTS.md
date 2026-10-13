# 仓库开发指令

所有在本仓库工作的 agent，开始修改前必须阅读并遵守 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。该文档是开发规则的统一来源，不因模型、工具、会话或执行者变化而省略。

## Git 提交（强制）

- 本仓库仅在本机研发。`docs/` 全目录只在本机保留，禁止提交，也不为其他机器或 CI 迁移这些文件。
- 提交只包含本次任务的源码、必要资源、正式测试、依赖清单和仓库规则。计划、进度、笔记、审计报告、日志、截图、基准运行结果、临时脚本、缓存、构建产物和本机配置不得提交；`PROGRESS.md` 与 `xu-site/xu-api-extract.md` 同样只在本机保留。
- 使用 `git add -- <明确路径>` 或 `git add -p` 逐项暂存。禁止未经逐项审查使用 `git add .`、`git add -A`、`git commit -a`，禁止用 `git add -f` 或 `--no-verify` 绕过规则。
- 提交前运行 `python3 scripts/check_git_hygiene.py --staged`，查看 `git diff --cached --stat` 和 `git diff --cached`，并执行适用的测试和版本检查。提交信息采用 `<type>(<scope>): <说明>`，一条提交只表达一个完整目的。
- 发现已有跟踪的过程文件时，用 `git rm --cached` 移除跟踪并补充忽略规则，保留本地文件；不得清空其他任务的改动，不得为制造干净状态而删除本机研发材料。未获用户指示，不提交或推送。

## 模块版本（强制）

- 修改模块内容（源码、资源、依赖或模块内文档）时，必须同步递增模块根 `xu.xun` 的 `version:`；同一批改动递增一次。
- `version: !ver x.y.z` 是模块版本，`xu:` 是所用 Xu 的版本；除编译器外两者独立；发布时同步 `xu:`，模块修改时递增 `version:`。常规修改递增 patch；兼容功能递增 minor；不兼容修改递增 major。
- 新模块从 `version: !ver 0.1.0` 开始；内部包归属最近的模块根，不为每个内部包新增清单。共享标准库改动需按影响同步更新使用它的模块版本。
- 完成修改后运行 `python3 scripts/module_versions.py --bump`，再运行 `python3 scripts/module_versions.py --check`。脚本默认与 `HEAD` 比较，重复运行不会对同一批改动重复递增；跨提交检查用 `--base <revision>`。
- 不修改测试夹具、历史审计快照或 `dist/` 构建副本的版本；发布总版本仍由 `VERSION` 和 `scripts/bump_version.sh` 管理。
- 未同步模块版本或版本检查失败，不得声称模块修改已完成。交付时说明受影响模块的旧版本、新版本和检查结果。

## Xu 发布总版本（强制）

- **用户版本决策（2026-10-12）：Xu 继续使用 `0.8.x`，本批路径迁移版本为 `0.8.1`；未经新的明确版本决定，不升到 `0.9`。`src/cmd/compile/xu.xun` 的 `version:` 与 `xu:` 必须都等于根 `VERSION`，编译器不再独立递增版本。`--sync-release` / 发布递增自动同步，模块检查和发布身份检查强制验证。其他模块继续独立管理。**

- **Xu 在正式稳定版发布决定前保持 `0.x`。普通修复、标准库补齐和兼容新增不能据此升到 `1.0.0` 或更高；破坏性调整在 `0.x` 阶段递增 minor 并记录迁移。跨入 `1.x` 须由用户明确决定正式发布，不能由 agent 自行推断。**

- 涉及 Xu 产品源码、前端、标准库、运行时、产品工具或构建、打包、发布行为的修改时，还必须同步递增根 `VERSION`；不能只更新模块 `version:`。具体同步范围见 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。
- 同一批产品改动只递增一次。执行 `./scripts/bump_version.sh patch` 前确认本批是否已经递增；该脚本每次调用都会加版本，不可重复运行，也不可再用 `make xu BUMP=patch` 重复递增。
- 发布时必须将所有当前模块 `xu.xun` 的 `xu:` 统一对齐根 `VERSION`，包括未修改的模块；除编译器外，模块 `version:` 保持独立。`make xu BUMP=patch|minor|major` 自动先同步再构建；单独同步现有发布版本用 `make release-version-sync`，只读检查用 `make release-version-check`。普通 `make xu` 不自动递增发布版本，dry-run 和 help 不修改版本。
- 同步源码横幅、打包元数据和当前发行说明后，重建本次交付的产品产物，并通过 `python3 scripts/check_release_identity.py --require-cli`。旧二进制版本未同步时，必须记录产品重建待完成，不得声称发布版本同步完成。
- 交付时报告 Xu 旧版本、新版本、实际二进制版本和检查结果；编译器模块版本与 Xu 发布版本一致，其余模块版本仍独立。
