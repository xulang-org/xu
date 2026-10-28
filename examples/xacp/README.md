# XACP 最小样例

在仓库根目录执行：

```sh
make xu-xacp
bin/xu build --xacp examples/xacp/main.xu -o bin/xacp-example
bin/xacp-example --xacp-help
bin/xu-xacp inspect ./bin/xacp-example
bin/xu xacp debug ./bin/xacp-example -- 'hello world'
bin/xu xacp run ./bin/xacp-example -- --xacp-help
bin/xu xacp record ./bin/xacp-example -- hello > /tmp/xacp-output.txt
make xacp-test
```

`--xacp` 是构建选项；单独导入 `#xacp` 不会生成启动发现入口。
`--xacp-port PORT`（或 `--xacp-port=PORT`）会同时启用 XACP，端口范围为
0..65535。端口 0 禁用 TCP；非零端口由显式 `--xacp-tcp` 入口在 `127.0.0.1` 监听。
另一个终端运行 `xu xacp connect PORT`，通过 stdin/stdout 逐帧请求/响应。
TCP 与 `--xacp-stdio` 均独占控制、不运行业务 main；`--` 前首个控制标志优先。
每条连接独立会话，连接顺序处理；结束服务可终止进程。普通启动不监听。
生成器目前只允许 hosted native 可执行程序，拒绝 lib/shared/test、嵌入式和
`--desktop` 打包模式。

发现信息保留 `stdio` 能力，并标明 TCP 是否启用及绑定地址：`inspect` 执行目标的 `--xacp-help` 并输出结果；
`debug` 先发现再启动，不提供断点调试；`run` 直接启动；`record` 在 Unix 上录制
最多 1 MiB stdout，stderr 仍继承终端，Windows 暂不支持。录制输出不是 XACP
UI 事件/帧文件。目标必须是受信任的本地可执行程序；inspect 同样会执行它。

用户参数必须写在工具的 `--` 后；工具会给目标额外插入 `--`，目标的
`os.args()` 会保留该标记。生成的启动扫描遇到标记即停止，所以业务参数
`--xacp-help` 不会触发发现。路径建议使用 `./bin/...` 或绝对路径。
inspect 和 control 不接受额外业务参数，子进程失败会返回非零状态。

`src/xacp/mod.xu` 提供有界帧/XUN 校验、权限、会话生命周期等安全核心；
`src/xacp/ui.xu` 提供 UI 适配及录制 API。`--xacp` 构建自动接入 `src/xacp/stdio.xu`。
`xu xacp control <program>` 继承调用方的 stdin/stdout 管道，启动目标的
`--xacp-stdio` 独占模式，不运行业务 main；普通运行不读取控制 stdin。
首个请求必须为合法 hello（`ver: !ver 1.0.0`、非空 `nonce`，最多 65536 字节）；
此前的非 hello 请求返回 `hello_required` 并关闭连接。hello 响应回显 nonce，
`permissions: !i <位掩码>` 表示实际权限，`permission_label` 为对应标签。
可选 `permissions: !i 0..15` 与宿主允许集取交集；省略则取允许集全集。
未配置非空 `XU_XACP_TOKEN` 时仅允许 INFO（1），客户端自带 token 不提升权限；
配置后 hello 必须带匹配的 `token`，允许集为 ALL（15）；缺失或不匹配返回
`auth_failed` 并关闭连接。显式以 `set_permissions` 写入协商结果。
proc.status 返回 pid/state；proc.output 与全部 UI ops 经过 schema/权限/生命周期
校验，权限不足返回 permission_denied；通过校验而无注册适配器时返回 not_implemented（包括 mutate、record）。
应用可用下述旁路注册 API 接入 Screen；本阶段没有事件推送。

例如：`bin/xu xacp control ./bin/xacp-example < examples/xacp/control.xun`。
线上分帧为 XACP/1 长度前缀：`XACP/1\n<正文字节数>\n<恰好 N 字节 XUN 正文>`，正文可含任意字节（含 `===`）；旧的 `--- !xacp`/`===` 外壳已移除，会被当作 frame_error。
响应包含 id、ok 和 data 或 error.code（可选 error.msg，≤256 字节，有才写）；能解析出请求 id 就回该 id，帧级失败 id 为 0。详见 `docs/superpowers/specs/2026-10-28-xacp-length-prefix-framing-design.md`。
帧错误、schema_error、auth_failed、半帧 EOF（truncated_frame）与超限
（frame_too_large）回错误后关闭该会话并结束连接控制循环，同批后续帧不再处理。
已打开会话的权限、请求编号、生命周期与 not_implemented 错误不断连；
permission_denied 不消耗请求编号，下一次请求沿用该编号。EOF 关闭会话。
TCP 监听继续接收后续连接；stdio 模式则退出。
持续无输出/不退出的目标尚无超时或终止机制，调用方应自行设置进程超时。

TCP 示例（先运行监听，再在另一终端连接）：

```sh
bin/xu build --xacp-port 4321 examples/xacp/main.xu -o bin/xacp-example
bin/xacp-example --xacp-tcp
# 另一终端：
bin/xu xacp connect 4321 < examples/xacp/control.xun
```

客户端逐帧等待响应，输入帧必须是完整的 XACP/1 长度前缀帧；输入 EOF 后断开连接。

`make xacp-test` 同时覆盖会话安全与 HTTP POST 跨协议探针。探针也可独立执行：
`python3 scripts/xacp_cross_protocol_probe.py`（自动构建本机 TCP 样例，检查默认 INFO 与配置 token 两种策略）。

旁路附着与 Screen（并存方案）：

```sh
bin/xu build --xacp examples/xacp/attach/main.xu -o bin/xacp-screen
XU_UI_SIM=1 XU_XACP_TOKEN=local-control-token \
  bin/xu xacp attach ./bin/xacp-screen
# stdin 先发送携带相同 token 的 hello，再发送 ui.tree；stdout 只写 XACP 帧。
# TCP 示例：显式库 API 使用自己的端口，不依赖 --xacp-port 构建默认值。
XU_UI_SIM=1 XU_XACP_TOKEN=local-control-token XACP_EXAMPLE_TCP=4321 ./bin/xacp-screen
```

本阶段采用显式库附着，不设置自动 startup 环境钩子。应用调用
`xacp.attach_stdio()` 或 `xacp.attach_tcp(port)` 获取 `ScreenControl`，
在持有 Screen 的协程调用 `xacp.register_screen(mut &control, &screen)`，
然后在非阻塞 UI 事件循环中持续调用 `xacp.poll(mut &control, mut &screen)`。
`xu xacp attach` 运行 main，并转发 stdin/stdout，不注入独占控制参数；
应用仍须调用附着 API。`control` 和 `--xacp-stdio` / `--xacp-tcp` 继续跳过 main。
附着 API 可单独导入使用；`--xacp` 额外提供发现帮助和独占入口。

每进程支持一个附着控制器、一个已注册 Screen。重复注册拒绝；先
`unregister_screen` 再注册可更换 Screen。控制旁路只持有 channel 和复制的
请求正文、权限、注册 generation，不持有 `&mut Screen`。UI 协程执行
`dispatch_screen`，把数据序列化进 `ControlReply.data` 后回复。
`ui.tree` 返回真实节点 id/kind/parent、位置、大小、可见/启用/焦点和转义后的 text；
`ui.act`、`ui.input` 返回 actions。`ui.screenshot` 成功时返回真实 Surface 的尺寸
元数据并释放 Surface，本阶段不导出像素；无原生截图支持时返回 `adapter_error`。
`ui.record` 仍需独立流式接收器，注册后返回 `stream_required`。

未注册时返回 `not_implemented`；注销使已入队请求得到 `stale_window`。
Screen close/dispose（含窗口关闭事件）通过单槽 channel 通知控制侧失效，
正在等待的请求得到 `stale_window`，后续请求返回 `not_implemented`。
UI 不得停止 poll 后遗留一个仍开放的注册：退出循环前应 unregister 或 dispose。
单槽 mailbox、单个顺序 peer 提供背压；本阶段没有请求超时，注册后停止 poll
而不清理会阻塞该 peer。独占与附着共用帧校验、首帧 hello、nonce/token 和权限协商。

附着 stdio 独占 stdin/stdout，业务日志写 stderr。不要让 UI host 或业务代码同时
读取控制 stdin。样例显式使用 `XU_UI_SIM=1` 和模拟 canvas_ready，在无显示环境中
构造真实 retained Screen；原生应用须使用实际 host 的 canvas_ready 事件。
`ScreenControl.done` 在 stdio EOF/致命会话错误/传输错误时给出服务退出码，
main 自行处理；TCP 顺序监听持续运行至进程退出，单个坏 peer 不关闭监听。

`make xacp-test` 包含旁路 Screen 冒烟；可单独运行
`python3 scripts/xacp_screen_marshal_smoke.py`。脚本检查 stdin 保持打开时 main 已运行、
真实树/动作序列化、转义帧边界、权限、重复注册拒绝、注销/重注册、close/dispose、
排队请求失效，以及旁路 TCP 的 HTTP POST 探针和后续会话恢复。
