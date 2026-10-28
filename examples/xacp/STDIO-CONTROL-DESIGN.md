# XACP stdio 控制通道设计（方案 B）

日期：2026-10-27  
工作目录：`/workspace/xu-dev`  
基线分支：`cursor/xacp-usability-smoke`（基于 `origin/dev`）  
范围：先打通 **stdio** 控制通道；**TCP 本阶段不做**（端口仍为编译期元数据）。

## 目标

让 `--xacp` 构建的 Xu 程序能通过 **stdin/stdout 帧** 与宿主（`xu-xacp`）完成真实控制会话，而不再停留在 `help_only` 发现。

成功标准：

1. 宿主与目标之间能收发 `--- !xacp` … `===` 帧。
2. `xacp.hello` 握手成功后会话进入 OPEN，并调用 `enable_development()`（开发态全权限，便于打通）。
3. 已知操作可调度：`proc.status`、`proc.output`、`ui.tree`、`ui.screenshot`、`ui.input`、`ui.act`、`ui.record`（含 mutate）。
4. 无 UI / 未注册适配器时返回协议级错误（如 `not_implemented` / `permission_denied`），进程不挂死、不崩。
5. `--xacp-help` 发现文档标明 `stdio` 传输与已接线 ops（不再只报 `help_only`）。
6. 冒烟覆盖 hello、proc.status、至少一个 UI 读、一个 UI mutate；接入 `xacp-test` / `scripts/xacp_smoke.py`。
7. 无控制 stdin 时行为与现网一致（业务 main / `--xacp-help`）。
8. 不 push；不 force；TCP listen 本阶段明确不做。

## 非目标

- TCP listen / connect（后续阶段）。
- 生产级授权策略（本阶段固定 development 全开）。
- 跨平台 Windows record / 实机 macOS·Windows 验证（保持现有限制说明）。
- 编译器版本号提升与正式发布（合入前另走 release 流程）。

## 现状锚点

- `src/xacp/mod.xu`：传输无关安全核心（帧解析、会话、权限、`dispatch`）；默认仅 `xacp.hello`，其余无 adapter 时 `not_implemented`。
- `src/xacp/ui.xu`：`ScreenAdapter` 与 UI ops 桥接，需宿主/应用接入传输。
- Runtime 今日只生成 `--xacp-help` preflight；无控制循环。
- `xu-xacp`：inspect / run / debug / record；不注入控制载荷。

## 架构

```
xu-xacp control/run  --  pipes  --►  target (--xacp)
   写请求帧到 child stdin          读 stdin 帧
   读响应帧自 child stdout         写响应帧到 stdout
                                   业务 stdout 与控制帧需隔离策略（见下）
```

### 传输

- 帧格式不变：正文为 XUN，外层 `--- !xacp` / `===`，大小受 `MAX_FRAME_BYTES` 约束。
- 一请求一响应（本阶段不做多路复用与推送事件流；`ui.record` 若需流式，先以有界单响应或明确错误落地）。
- **stdio 多路复用**：控制帧与业务 stdout 不能混写。采用其一（实现时选更贴合现有 runtime 的方案，并在报告中写明）：
  - **推荐**：控制模式下业务程序的常规 `println` 仍走原 stdout，但控制会话期间宿主只解析完整帧；或
  - **更干净**：控制通道占用一对专用 fd / 或约定控制在 stdin + 专用 stderr-fd；若过重则退回「控制会话独占 stdio，业务输出经 `proc.output`」。
- 无控制宿主（普通终端直接跑二进制）：不进入控制循环，保持现有 argv / `--xacp-help` 行为。

### 如何判定「有控制 stdin」

- 由 `xu-xacp` 启动子进程并接管管道，和/或目标通过环境变量 / argv 约定进入控制模式（例如 `XU_XACP_STDIO=1` 或启动后首帧超时探测）。优先显式标志，避免把交互式 TTY 误判为控制通道。

### 会话与授权

1. `open_session()` → `STATE_NEW`
2. 收到并校验 `xacp.hello` → `enable_development()` → `finish_request` 使 `STATE_OPEN`
3. 后续已知 ops 走 `validate_request` → `authorized` → adapter
4. `close` / 连接结束 → `close_session()`

### 操作接线

| Op | 期望 |
|----|------|
| `xacp.hello` | 生命周期；开 development 权限 |
| `proc.status` | 返回最小进程信息（pid、state 等已有/可提供字段） |
| `proc.output` | 有界输出读取；不可用则协议错误 |
| `ui.tree` / `ui.screenshot` / `ui.record` | 经 ScreenAdapter；无 UI → not_implemented |
| `ui.input` / `ui.act` | mutate；无 UI → not_implemented |

### 发现文档

`--xacp-help` 输出更新：

- `capabilities`：不再仅 `help_only`，标明 `stdio`（及已支持 ops 列表）
- `transport: stdio (v1)` 表示已接线，而非仅方向描述
- 端口字段仍可存在，但注明 **TCP 未启用**

### `xu-xacp` 宿主

- 新增或扩展子命令（名称实现自定，文档写清），例如：`xu-xacp control <target> -- …` 或 `xu xacp control`
- 职责：spawn 目标、设置控制标志、stdin 写请求、stdout 读响应、可选脚本化单次 hello+op 冒烟
- 不授予超越 development 约定的额外权限模型；不在本阶段做 TCP connect

## 测试

- 扩展 `examples/xacp/`：可被 control 的最小程序（有/无 UI 两条路径可接受）
- `scripts/xacp_smoke.py` / `make xacp-test`：stdio hello、proc.status、UI 读、UI mutate（无 UI 时期望稳定错误码）
- 回归：现有 inspect/run/debug/record、`--` 边界、1 MiB record 上限

## 实现约束

- 在 box 上用 Codex（`CODEX_HOME=/home/box/.codex` / cupfuls）；不用 Mac。
- 继续 `/workspace/xu-dev`；可留在 `cursor/xacp-usability-smoke` 或建 `cursor/xacp-stdio-control`。
- 可用 `XU_SEED=/home/box/.xu/bin/xu` 与已有 `bin/xu`；`make` 在 `/home/box/.local/bin/make`。
- 不 push、不 force；报告写到 `/tmp/xu-codex-box/xacp-stdio-report.md`。

## 后续（非本阶段）

- TCP listen（`--xacp-port` 真正生效）
- 生产授权（默认拒绝 + 宿主显式授权）
- 推送/事件流与正式 UI 录制容器
