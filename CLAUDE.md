# 仓库开发指令

开始修改前，必须阅读并遵守仓库根 [`AGENTS.md`](AGENTS.md) 和统一开发规范 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。

每次修改模块内容，必须同步递增模块根 `xu.xun` 的 `version:`，并通过 `python3 scripts/module_versions.py --check`；未同步版本不得将修改标记为完成。模块版本与 `xu:` 语言版本独立。

涉及 Xu 产品修改时，还必须按 `docs/DEVELOPMENT.md` 同步递增根 `VERSION`、更新发行相关版本、重建交付产物并通过 `python3 scripts/check_release_identity.py --require-cli`。同一批改动仅递增一次；只改模块版本或源码版本、旧二进制尚未重建时，不得声称 Xu 发布版本同步完成。

发布时，所有当前模块的 `xu.xun` 中 `xu:` 必须统一对齐根 `VERSION`，包括未修改的模块。发布入口为 `make xu BUMP=patch|minor|major`；只补齐现有版本用 `make release-version-sync`，验证用 `make release-version-check`。模块 `version:` 保持独立。旧二进制尚未重建时，明确记录产品重建待完成。
