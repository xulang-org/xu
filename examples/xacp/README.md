# XACP 最小样例

[PROTOCOL.md](PROTOCOL.md) 是已实现协议的权威英文规格，涵盖分帧、错误与断连、
认证/权限、防重放、超时、分页、Screen、截图、输出与平台限制。
[STDIO-CONTROL-DESIGN.md](STDIO-CONTROL-DESIGN.md) 仅保留历史设计说明。
下文是样例使用指南；完整协议规则以 PROTOCOL.md 为准。

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
此前通过 schema 校验的非 hello 请求返回 `hello_required` 并关闭连接。
hello 响应回显经过路径过滤的 nonce（防重放仍比较原始解码字节），
`permissions: !i <位掩码>` 表示实际权限，`permission_label` 为对应标签。
可选 `permissions: !i 0..31` 与宿主允许集取交集；省略则取允许集全集。
未配置非空 `XU_XACP_TOKEN` 时仅允许 INFO（1），客户端自带 token 不提升权限；
配置后 hello 必须带匹配的 `token`，默认允许集为 15（不含 RAW）；缺失或不匹配返回
`auth_failed` 并关闭连接。显式以 `set_permissions` 写入协商结果。
`PERM_UI_RAW=16`，`PERM_ALL=31`；只有宿主显式设置
`XU_XACP_ALLOW_RAW=1` 时 token hello 才允许 RAW，无 token 永远仅 INFO。
开发宿主可显式使用 `development_permissions()` 授予含 RAW 的全集。
同一 TCP 监听器的连接共享成功 hello 的 nonce，按精确解码字节比较；stdio 也走同一检查。
宿主启动时读取 `XU_XACP_NONCE_CACHE`，默认 1024，仅接受 ASCII 十进制
1..65536，非法值回退默认。缓存为有界环形 FIFO，满时驱逐最旧项，
被驱逐的 nonce 可再次使用，防重放窗口为最近 N 次成功 hello。
`XU_XACP_NONCE_REPLAY=0` 关闭检查，其余值默认开启；认证或 schema 失败的 hello 不记录。

| 认证错误码 | 行为 |
| --- | --- |
| `auth_failed` | hello token 缺失或不匹配；回错误后断连。 |
| `nonce_replay` | hello nonce 已在监听器共享缓存中；回显请求 id，不进入 OPEN，回错误后断连。 |

proc.status 返回 pid/state；proc.output 与全部 UI ops 经过 schema/权限/生命周期
校验，权限不足返回 permission_denied。proc.output 在具备捕获支持的宿主上可直接读取，
不依赖 Screen；UI ops 无注册 Screen 时返回 not_implemented（包括 mutate、record）。
应用可用下述旁路注册 API 接入 Screen；本阶段没有事件推送。

例如：`bin/xu xacp control ./bin/xacp-example < examples/xacp/control.xun`。
线上分帧为 XACP/1 长度前缀：`XACP/1\n<正文字节数>\n<恰好 N 字节 XUN 正文>`。
传输层不解释正文内的分隔符或 NUL；正文仍必须是合法 XUN 并通过请求 schema 校验。
响应包含 id、ok 和 data 或 error.code；可选 error.msg 在转义前限 256 字节，
有内容才写，转义后的字段可能更长。能解析出请求 id 就回该 id，帧级失败 id 为 0。
详见 [PROTOCOL.md](PROTOCOL.md#2-xacp1-framing-and-xun-bodies)。
帧错误、schema_error（OPEN 会话中的 proc.output 参数错误除外）、auth_failed、nonce_replay、半帧 EOF（truncated_frame）与超限
（frame_too_large）回错误后关闭该会话并结束连接控制循环，同批后续帧不再处理。
已打开会话的权限、请求编号、生命周期与 not_implemented 错误不断连；
permission_denied 不消耗请求编号，下一次请求沿用该编号。EOF 关闭会话。
会话 `next_id` 从 1 开始，首个 hello 的 id 必须为 1；每个被 `begin_request`
接受的请求消耗一个编号，后续 id 必须严格 +1。id <= 0、重复、回退或跳跃返回
`invalid_request_id`（`request id is not monotonic`），回显原 id、不断连、不消耗编号；
首帧 hello id=2 失败后仍可发送 id=1 的 hello。NEW 状态下非 hello 优先报
`hello_required` 并断连，已有在途请求优先报 `request_in_flight`。
`request_timeout` 的 id 已消耗，下一请求使用 id+1。
TCP 监听继续接收后续连接；stdio 模式则退出。
控制循环开始后默认须在 5000 ms 内完成合法 hello，否则返回 id=0 的
`hello_timeout` 并断连。`XU_XACP_HELLO_TIMEOUT_MS` 仅接受 ASCII 十进制
1..600000，非法值使用默认值。OPEN 后默认连续 60000 ms 无完整请求帧即返回
id=0 的 `session_idle` 并断连；`XU_XACP_IDLE_TIMEOUT_MS` 接受 1000..3600000，
0 禁用，非法值使用默认值。配置在服务启动时读取一次，半帧字节不刷新空闲计时。
等待活动请求结果期间只执行请求超时；结果返回后仍按完整帧到达时刻计算空闲。
stdio 限时读取支持 POSIX 文件/管道；Windows 已实现 `GetFileType` +
`PeekNamedPipe` 和约 1 ms 轮询（磁盘直接就绪，控制台用 `WaitForSingleObject`），
实机运行尚未验证。控制台非按键事件唤醒与完整行读取保证属于非目标。
客户端启动的目标进程若持续无输出/不退出，调用方仍应自行设置进程超时。

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
禁止 socket 的环境可单独验证 stdio 限期与请求/空闲超时顺序：
`python3 scripts/xacp_smoke.py --stdio-timeouts-only`。
分页与 id 规则可单独验证（含 Screen stdio 集成）：
`python3 scripts/xacp_smoke.py --stdio-pagination-id-only`。

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
在持有 Screen 的协程调用 `xacp.register_screen($&control, &screen)`，
然后在非阻塞 UI 事件循环中持续调用 `xacp.poll($&control, $&screen)`。
`xu xacp attach` 运行 main，并转发 stdin/stdout，不注入独占控制参数；
应用仍须调用附着 API。`control` 和 `--xacp-stdio` / `--xacp-tcp` 继续跳过 main。
附着 API 可单独导入使用；`--xacp` 额外提供发现帮助和独占入口。

支持的使用模型是每进程一个附着控制器、一个已注册 Screen。重复注册拒绝；先
`unregister_screen` 再注册可更换 Screen。控制旁路只持有 channel 和复制的
请求正文、权限、注册 generation，不持有 `$&Screen`。UI 协程执行
`dispatch_screen`，把数据序列化进 `ControlReply.data` 后回复。
`ui.tree` 返回真实节点 id/kind/parent、位置、大小、可见/启用/焦点和转义后的 text；
支持 `start: !i`（默认 0，>=0）和 `max_table_rows: !i`（默认
`min(512, limits.max_table_rows)`，范围 1..limits.max_table_rows）。节点按
`include_hidden` 过滤后的现有顺序分页，响应 data 包含 `win`、`generation`、
`start`、`count`、`total`、`truncated: !b`、`next_start: !i`、`nodes`。
下一页用 `start = next_start`；未截断时 `next_start == total`。
`start == total` 返回空页，`start > total` 返回 `adapter_error`；负 start 或
行数上限越界返回 `schema_error`，不会静默钳制。节点总数仍受 512 上限约束；
响应超过帧上限返回 `adapter_error`，客户端应减小 `max_table_rows`。
两页间 `generation` 不同则从 0 重读；它是 Screen 身份 generation，
不是每次文本/布局变更的版本号，相同值也不保证快照一致性。
`ui.act`、`ui.input` 返回 actions。`ui.tree` 和 `ui.screenshot` 默认脱敏：
tree 中 password/secure 控件（`Screen.secret_input` 或 `set_secure` 标记）text 为空且
`redacted: !b true`；普通 text 截断到 256 字节（保留 UTF-8 边界），超出加
`text_truncated: !b true`。响应根和 data 均含 `redacted: !b`；不回窗口标题。
tree text、hello nonce 回显和错误 msg 使用路径 token 过滤，识别出的宿主绝对路径
与 `$HOME` 替换为 `<path>`；proc.output 保留原始字节，不做该过滤。
两种请求均接受 `raw: !b true`，需要 RAW；无 RAW 返回带 id 的
`permission_denied`，不断连、不消耗 id。RAW 关闭序列化层的文本截断和秘密控件
遮盖，但仍做路径过滤；底层 Screen 枚举已清空的 password-editor text 不会恢复，
RAW 也不返回窗口标题。

`ui.screenshot` 导出 RGBA8 PNG（仅 IHDR/IDAT/IEND，无文本或 EXIF），
返回 `width/height/pixel_width/pixel_height`、`mime: image/png`、PNG 字节数 `bytes`。
缺省 `mode: inline_b64`，`data` 为 base64；完整响应超过帧上限返回
`screenshot_too_large`，可降低 `scale` 或使用 `mode: file`。
脱敏截图在独立像素副本中把秘密控件矩形填为不透明 `#808080`，
包括 node 裁剪和缩放；原 Surface 不变并在编码前释放。无原生截图后端时返回 `adapter_error`。

`mode: file` 由 POSIX 原生 UI 宿主写入 `$XDG_RUNTIME_DIR/xacp/<pid>/`，
无该环境变量时为 `${TMPDIR:-/tmp}/xacp-<uid>/<pid>/`。
创建目录为 0700；已有目录须属于当前 uid 且无额外权限，拒绝符号链接。
文件以 `O_CREAT|O_EXCL|O_NOFOLLOW` 和 0600 创建，响应只回相对文件名
`path: "shot-<session_generation>-<request_id>.png"`、`dir_hint: xacp-runtime`；
宿主用 `xacp.screenshot_dir()` 获取绝对目录。客户端传 `path` 为 `schema_error`。
单文件上限 32 MiB，`XU_XACP_SCREENSHOT_MAX_BYTES` 仅可调低；每会话 FIFO 保留 16 个。
会话关闭（EOF、超时、致命错误或传输失败）删除所属文件，并尽力删除空 pid 目录。
UI 超时后到达的回复不能写文件；未链接原生文件桥接或不支持 POSIX 权限时返回 `file_unavailable`。

| 截图错误码 | 行为 |
| --- | --- |
| `permission_denied` | 请求 RAW 但未授权；带 id，不断连，id 不消耗。 |
| `screenshot_too_large` | inline 完整响应超帧或文件超上限；带 id，不断连，id 已消耗。 |
| `file_unavailable` | 目录不安全/不可建、磁盘写失败或 EXCL 冲突；带 id，不断连。 |
| `encode_error` | 像素读回或 PNG 编码失败；带 id，不断连。 |

`surface_record` 仍仅导出尺寸元数据，标记 `redacted=true`，不导出帧像素。
`ui.record` 在匹配的 Screen 上使用内存有界 sink，同步采样后返回一段完整 XAR1。
客户端重复请求形成拉取式分段流，每段序号从 1 开始；每请求仍只有一个 XACP 响应，
没有跨请求录制状态或续传游标。参数为 `win: !i`（正数）、`mode: events|frames`，
可选 `max_bytes: !i`（默认 65536，1..max_frame_bytes）、`max_records: !i`（默认 64，>=1）
及 `duration_ms: !i`（默认 0，范围 0..request_timeout_ms-1）。0 表示立即采样一次，
正数窗口内重复采样，采样间最多等待 10 ms；排队时间计入请求超时。
成功 data 含 `mode`、`records`、`bytes`、`truncated` 和带引号的 XAR1 `payload`。
`frames` 使用截图的尺寸元数据；Screen 未公开输入事件历史/订阅，故 `events` 如实返回
标记 `state=true` 的当前 `window/canvas/generation/open` 状态，不注入输入，不要求 UI_MUTATE。
采样占用 UI-owner 的本次 poll，不推进业务事件循环，也不补录请求间的事件。
无 Screen 为 `not_implemented`，窗口不符为 `stale_window`；`stream_required` 仅保留给
未提供 sink/采样能力的适配器，常规 Screen 路径不再返回。
`proc.output` 接受 `stream`（stdout/stderr）、`since`（>=0）和 `max_bytes`
（1..max_frame_bytes，默认 min(4096, max_frame_bytes/2)，越界为 `schema_error`）。
启用 XACP 的 64 位 POSIX 宿主捕获 Xu 运行时 print/eprint 和 fd-write 路径的
fd 1/2 写入，原样透传；不是对全部外部原生代码或子进程输出的通用拦截。
每流独立环形缓冲由 `XU_XACP_OUTPUT_BUFFER` 设置，默认 65536 字节，合法范围
4096..16777216，非法值回退默认，满时丢弃最旧字节。未接入捕获的宿主仍返回
`not_implemented`。`since` 是单调绝对字节偏移，响应字段为 `stream`、`since`、
`count`、`total`、`base`、`dropped`、`truncated`、`next_since`、`data`。
游标早于 `base` 时从 `base` 返回并报告 `dropped`；等于 `total` 返回空页；超过
`total` 返回 `adapter_error`，会话保持可用。`data` 使用引号转义，非 UTF-8 和
控制字节使用 `\xHH`；分页按原始字节计数，不对齐 UTF-8。转义膨胀超过帧上限
时自动缩页，客户端用 `next_since` 继续轮询。OPEN 会话中的输出参数错误不消耗
id，返回 `schema_error` 后可重试。stdio 控制帧通过 stdout 的专用复制 fd 写出，
不进入缓冲；该 fd 仍指向原 stdout，业务 stdout 不会自动重定向，须避免日志与帧混写。
attach 的输出请求直接由控制协程处理，不需要 Screen 注册或 UI-owner poll。
`ui.record.max_bytes` 含 XAR1 头和尾 LF。实现将有效预算进一步限制为
`(max_frame_bytes-256)/2`，预留信封和转义空间，并校验完整响应大小。
参数越界/未知字段为 `schema_error`；首条记录超预算、sink/截图失败为 `adapter_error`，
并中止 recorder；已有完整记录后字节预算耗尽则返回有效前缀，`truncated=true`。
达到记录数上限也标记 `truncated=true`；采样窗口正常结束不单独标记截断。
响应仍遵守 `XU_XACP_WRITE_TIMEOUT_MS`，超时后保留原传输关闭语义。

未注册时返回 `not_implemented`；注销使已入队请求得到 `stale_window`。
Screen close/dispose（含窗口关闭事件）通过单槽 channel 通知控制侧失效，
正在等待的请求得到 `stale_window`，后续请求返回 `not_implemented`。
UI 不得停止 poll 后遗留一个仍开放的注册：退出循环前应 unregister 或 dispose。
单槽 mailbox、单个顺序 peer 提供背压；注册后停止 poll 会得到 `request_timeout`
（默认 5000 ms，可用 `XU_XACP_REQUEST_TIMEOUT_MS` 配置）。该计时约束等待 UI 回复，
不抢占已执行的 UI 操作，也不为同步文件写出或响应写出提供独立超时。
独占与附着共用帧校验、首帧 hello、nonce/token 和权限协商。

附着 stdio 独占 stdin/stdout，业务日志写 stderr。不要让 UI host 或业务代码同时
读取控制 stdin。样例显式使用 `XU_UI_SIM=1` 和模拟 canvas_ready，在无显示环境中
构造真实 retained Screen；原生应用须使用实际 host 的 canvas_ready 事件。
`ScreenControl.done` 在 stdio EOF/致命会话错误/传输错误时给出服务退出码，
main 自行处理；TCP 顺序监听持续运行至进程退出，单个坏 peer 不关闭监听。

`make xacp-test` 包含旁路 Screen 冒烟；可单独运行
`python3 scripts/xacp_screen_marshal_smoke.py`。脚本检查 stdin 保持打开时 main 已运行、
真实树/动作序列化、转义帧边界、权限、重复注册拒绝、注销/重注册、close/dispose、
排队请求失效，以及旁路 TCP 的 HTTP POST 探针和后续会话恢复。
`python3 scripts/xacp_screenshot_smoke.py` 在 Linux 链接实际 Cairo/Pango 渲染后端，
不创建桌面窗口，覆盖 stdio 和 attach 两种启动方式的 PNG/RAW/脱敏像素、私有文件、
FIFO/断连清理、超限、目录权限/符号链接、UTF-8 截断及路径过滤；需要 C++、GTK4/Pango 开发库。
`python3 scripts/xacp_ui_record_smoke.py` 复用该真实渲染夹具，检查 stdio/attach 的
XAR1 分段、序号/长度、字节与记录预算、坏参数错误码、无 Screen、权限和请求超时，
并验证 sink 失败时的原子写入与 recorder 生命周期；已加入 `make xacp-test`。
