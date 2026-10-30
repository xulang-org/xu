# 标准库现状盘点与分批补全

人工复核日期：2026-10-30。由 `scripts/generate_stdlib_audit.py` 生成；任务源为 [stdlib_gaps.json](stdlib_gaps.json)。

## 口径与结论

扫描全部 **139 个可导入包**（127 个当前 inventory stdlib 分类、12 个扩展）、**571 个源文件 / 8384 个公开声明**。公开声明包含方法及类型，不等于独立能力数。

这是全目录静态盘点与重点 API 复核，不是逐 API 全量语义/安全审计。未登记问题的包仍为 inventory-only，不能据此声称完整。源码中的 subset/unsupported 只是待复核线索；合法的非法输入拒绝也会命中，不自动当作缺陷。

旧测试证据没有源码/编译器指纹，现已拒绝套用到当前源码。新证据绑定编译器文件、包导入闭包、隐式 runtime 与 fixture 合同。PASS 只涵盖该次日志中实际执行的 fixture；包有 smoke 不代表全部导出方法可用。

已实施批次及验证边界：[第一批 UTF-8/证据](STDLIB_BATCH1.md)、[第二批 HTTP/运行时依赖](STDLIB_BATCH2.md)、[第三批 select 唤醒与取消回收](STDLIB_BATCH3.md)、[第四批 Rune 与 Unicode 大小写](STDLIB_BATCH4.md)、[第五批 Unicode 分类与 titlecase](STDLIB_BATCH5.md)、[第六批流式复制与 gzip](STDLIB_BATCH6.md)、[第七批缓冲 I/O 边界](STDLIB_BATCH7.md)、[第八批通用缓冲包装](STDLIB_BATCH8.md)、[资源所有权第一批](RESOURCE_SAFETY_BATCH1.md)、[I/O 进度第二批](IO_PROGRESS_BATCH2.md)。执行批次是交付记录；下表是长期主题分组。

## 已确认与分批安排

已登记 10 项任务；3 项完成本机验证，其余仍有待完成的依赖或验收。

P0：错误完成度声明与取消后资源滞留；P1：基础语义、服务主链及无直接测试的新包；P2：高频扩展；P3：格式长尾。

| 批次 | 主题 | 验收边界 |
|---|---|---|
| 1 | 证据可信度、UTF-8 文本基础 | 产品/对照编译器本机 fixture + 独立 Go oracle；不宣称发布绿 |
| 2 | context、timer、HTTP 超时、进程取消、signal | 先完成最小 runtime adapter；取消/竞态/关闭/回收 |
| 3 | Rune API、流式 I/O、FS、新包测试 | 独立向量与正向/边界/错误 fixture |
| 4 | HTTP/2、poller、数据库、Windows 时区/管道 | 协议互操作、实际流控/取消、原生平台 |
| 5 | X.509/TLS/私钥操作深化 | 支持矩阵、负向标准向量与安全合同 |
| 6 | testing、regexp、序列化、模板及格式长尾 | 类型/复杂度/资源上限合同 |
| 7 | 全量平台与发布收口 | native/compile-only/unsupported 分列，Gen3==Gen4 单独验收 |

旧记录修正：`os/exec` 已有 start/wait 和 Unix stdin/stdout pipe；`filepath` 已有 glob/walk；`net/http2` 已有受限独立包；`unicode.is_space` 已支持 U+0085/U+2028/U+2029。后续项以实际实现深度为准。

### GAP-OS-SIGNAL-01 · P0 · 批次 2 · os/signal.notify / stop / ignore

包：`os/signal`。状态：`pending`。

notify / stop / ignore 均为占位抛错，未接入内核信号处理机制。

依赖：runtime OS signal handler hook。验收：支持注册信号捕获并向 channel 投递。

源码依据：[src/os/signal/mod.xu](../../src/os/signal/mod.xu#L21)。

### GAP-SYNC-RWMUTEX-01 · P0 · 批次 2 · sync.RWMutex.read_lock / read_unlock

包：`sync`。状态：`host-verified`。

已升级：原 RWMutex 读锁串行阻塞，现重构为基于 token channel 的真·并行读锁（无锁竞争读取，写者独占排空）。

依赖：none。验收：多协程并行持有读锁且不相互阻塞，仅与写锁互斥。

源码依据：[src/sync/mod.xu](../../src/sync/mod.xu#L146)。

### GAP-SYNC-COND-01 · P1 · 批次 2 · sync.Cond.broadcast

包：`sync`。状态：`pending`。

Cond 基于有界 channel (容量 64) 实现，超过 64 个等待协程时 broadcast 无法全量唤醒。

依赖：none。验收：全量无上限唤醒所有等待者。

源码依据：[src/sync/mod.xu](../../src/sync/mod.xu#L9)。

### GAP-TIME-ZONEINFO-01 · P0 · 批次 4 · time.load_zoneinfo

包：`time`。状态：`host-verified`。

已修复：为 Windows 及缺少 /usr/share/zoneinfo 的目标内置轻量级标准 IANA 时区（Asia/Shanghai、Tokyo、New_York 等）与夏令时回退，避免直接抛错。

依赖：none。验收：Windows 平台支持加载标准时区与 UTC。

源码依据：[src/time/zoneinfo.xu](../../src/time/zoneinfo.xu#L509)。

### GAP-NET-HTTP-KEEPALIVE-01 · P1 · 批次 4 · net/http.Client

包：`net/http`。状态：`pending`。

连接池仅对明文 HTTP 生效（HTTPS 不复用连接），单 Client 仅缓存 1 个空闲连接，不支持 101 Switching Protocols 升级。

依赖：none。验收：支持 HTTPS 连接复用、连接池管理及 101 升级支持。

源码依据：[src/net/http/mod.xu](../../src/net/http/mod.xu#L11)。

### GAP-NET-IPRAW-01 · P1 · 批次 4 · net.dial_ip / listen_ip

包：`net`。状态：`pending`。

dial_ip / listen_ip 在所有目标平台上直接抛错 raw IP sockets are not available。

依赖：OS raw socket permission。验收：受控平台支持 raw IP socket 收发。

源码依据：[src/net/ipraw.xu](../../src/net/ipraw.xu#L16)。

### GAP-NET-POLLER-01 · P1 · 批次 4 · net/poller.Poller.wait

包：`net/poller`。状态：`pending`。

Poller.wait 遍历所有已注册流并逐个调用 socket_wait，高并发连接下为 O(N) 轮询而非 O(1) 批量事件驱动。

依赖：OS epoll / kqueue / IOCP batch readiness ABI。验收：提供 O(1) 批量就绪事件等待机制。

源码依据：[src/net/poller/mod.xu](../../src/net/poller/mod.xu#L75)。

### GAP-OS-EXEC-PIPE-01 · P1 · 批次 4 · os/exec.Cmd.stdout_pipe / stdin_pipe

包：`os/exec`。状态：`pending`。

管道方法仅支持 Unix，Windows 目标直接报错且不支持子进程运行期双向流式交互。

依赖：Windows anonymous pipe runtime wrapper。验收：Windows 平台支持管道重定向与流式交互。

源码依据：[src/os/exec/mod.xu](../../src/os/exec/mod.xu#L12)。

### GAP-CRYPTO-CIPHER-01 · P2 · 批次 5 · crypto/cipher

包：`crypto/cipher`。状态：`pending`。

CBC/CTR/GCM 硬编码绑定在 aes.Cipher，未抽象通用分组密码接口，缺少 CFB、OFB、XTS 模式。

依赖：none。验收：抽象通用 Cipher / Block 接口或扩充多模式支持。

源码依据：[src/crypto/cipher/mod.xu](../../src/crypto/cipher/mod.xu#L8)。

### GAP-ENCODING-JSON-01 · P1 · 批次 6 · encoding/json.Doc / parse

包：`encoding/json`。状态：`host-verified`。

已扩容：将 MAX_BYTES 缓冲区硬编码上限从 1 MiB 提升至 64 MiB，并新增 parse_max 允许调用方指定文档容量上限。

依赖：none。验收：解除 1 MiB 硬编码限制或支持动态内存扩容。

源码依据：[src/encoding/json/mod.xu](../../src/encoding/json/mod.xu#L26)。

## 全包覆盖表

无直接 import fixture 的包共 139 个：`archive/tar`、`archive/zip`、`bufio`、`bufio/file`、`bytes`、`cmp`、`compress/bzip2`、`compress/flate`、`compress/gzip`、`compress/lzw`、`compress/zlib`、`container/heap`、`container/list`、`container/ring`、`context`、`crypto/aes`、`crypto/cipher`、`crypto/des`、`crypto/ecdsa`、`crypto/ed25519`、`crypto/gmtls`、`crypto/hmac`、`crypto/jwt`、`crypto/md5`、`crypto/password`、`crypto/rand`、`crypto/rc4`、`crypto/rsa`、`crypto/rsa/oaep`、`crypto/sha1`、`crypto/sha256`、`crypto/sha3`、`crypto/sha512`、`crypto/sm2`、`crypto/sm3`、`crypto/sm4`、`crypto/sm9`、`crypto/subtle`、`crypto/tls`、`crypto/x509`、`crypto/x509/pkix`、`crypto/zuc`、`database/sql`、`database/sql/driver`、`encoding/ascii85`、`encoding/asn1`、`encoding/base32`、`encoding/base64`、`encoding/binary`、`encoding/csv`、`encoding/hex`、`encoding/json`、`encoding/pem`、`encoding/xml`、`encoding/xun`、`errors`、`flag`、`fmt`、`hash/adler32`、`hash/crc32`、`hash/crc64`、`hash/fnv`、`hash/maphash`、`html`、`html/query`、`html/template`、`id`、`image`、`image/color`、`image/draw`、`image/gif`、`image/jpeg`、`image/png`、`index/suffixarray`、`internal/dependency`、`internal/modulepath`、`internal/modulezip`、`internal/sdk`、`internal/semver`、`internal/sumdb`、`internal/toolpath`、`io`、`io/fs`、`log`、`log/slog`、`maps`、`math`、`math/big`、`math/bits`、`math/rand`、`mime`、`mime/multipart`、`mime/quotedprintable`、`net`、`net/apns`、`net/http`、`net/http/cookiejar`、`net/http/httptest`、`net/http2`、`net/mail`、`net/netip`、`net/poller`、`net/pool`、`net/smtp`、`net/stream`、`net/textproto`、`net/url`、`os`、`os/exec`、`os/signal`、`os/user`、`path`、`path/filepath`、`rate`、`regexp`、`slices`、`sort`、`strconv`、`strings`、`sync`、`testing`、`testing/fstest`、`testing/iotest`、`text/scanner`、`text/tabwriter`、`text/template`、`tile`、`time`、`timer`、`ui`、`ui/draw`、`ui/internal/codec`、`ui/layout`、`ui/webview`、`ui/widgets`、`unicode`、`unicode/utf16`、`unicode/utf8`、`xacp`。

fixture 只按显式 `#import` 关联；0 不等于没有间接测试。平台状态来自有指纹的日志；`not-measured` 表示证据不足，不能推断代码不支持。完整符号、fixture 和哈希见 [stdlib_matrix.json](stdlib_matrix.json)。

| 包 | 公开声明 | 直接 fixture | 限制线索行数 | 当前日志语义 | macOS ARM64 | 其余 7 目标已测数 |
|---|---:|---:|---:|---|---|---:|
| [src/archive/tar/mod.xu](../../src/archive/tar/mod.xu) | 25 | 0 | 4 | not-measured | not-measured | 0 |
| [src/archive/zip/mod.xu](../../src/archive/zip/mod.xu) | 15 | 0 | 2 | not-measured | not-measured | 0 |
| [src/bufio/mod.xu](../../src/bufio/mod.xu) | 102 | 0 | 0 | not-measured | not-measured | 0 |
| [src/bufio/file/mod.xu](../../src/bufio/file/mod.xu) | 10 | 0 | 0 | not-measured | not-measured | 0 |
| [src/bytes/mod.xu](../../src/bytes/mod.xu) | 86 | 0 | 1 | not-measured | not-measured | 0 |
| [src/cmp/mod.xu](../../src/cmp/mod.xu) | 9 | 0 | 0 | not-measured | not-measured | 0 |
| [src/compress/bzip2/mod.xu](../../src/compress/bzip2/mod.xu) | 4 | 0 | 1 | not-measured | not-measured | 0 |
| [src/compress/flate/mod.xu](../../src/compress/flate/mod.xu) | 3 | 0 | 0 | not-measured | not-measured | 0 |
| [src/compress/gzip/mod.xu](../../src/compress/gzip/mod.xu) | 23 | 0 | 1 | not-measured | not-measured | 0 |
| [src/compress/lzw/mod.xu](../../src/compress/lzw/mod.xu) | 4 | 0 | 0 | not-measured | not-measured | 0 |
| [src/compress/zlib/mod.xu](../../src/compress/zlib/mod.xu) | 10 | 0 | 1 | not-measured | not-measured | 0 |
| [src/container/heap/mod.xu](../../src/container/heap/mod.xu) | 14 | 0 | 0 | not-measured | not-measured | 0 |
| [src/container/list/mod.xu](../../src/container/list/mod.xu) | 18 | 0 | 0 | not-measured | not-measured | 0 |
| [src/container/ring/mod.xu](../../src/container/ring/mod.xu) | 14 | 0 | 0 | not-measured | not-measured | 0 |
| [src/context/mod.xu](../../src/context/mod.xu) | 13 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/aes/mod.xu](../../src/crypto/aes/mod.xu) | 8 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/cipher/mod.xu](../../src/crypto/cipher/mod.xu) | 10 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/des/mod.xu](../../src/crypto/des/mod.xu) | 10 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/ecdsa/mod.xu](../../src/crypto/ecdsa/mod.xu) | 28 | 0 | 4 | not-measured | not-measured | 0 |
| [src/crypto/ed25519/mod.xu](../../src/crypto/ed25519/mod.xu) | 10 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/gmtls/mod.xu](../../src/crypto/gmtls/mod.xu) | 12 | 0 | 1 | not-measured | not-measured | 0 |
| [src/crypto/hmac/mod.xu](../../src/crypto/hmac/mod.xu) | 13 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/jwt/mod.xu](../../src/crypto/jwt/mod.xu) | 9 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/md5/mod.xu](../../src/crypto/md5/mod.xu) | 8 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/password/mod.xu](../../src/crypto/password/mod.xu) | 6 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/rand/mod.xu](../../src/crypto/rand/mod.xu) | 1 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/rc4/mod.xu](../../src/crypto/rc4/mod.xu) | 3 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/rsa/mod.xu](../../src/crypto/rsa/mod.xu) | 16 | 0 | 2 | not-measured | not-measured | 0 |
| [src/crypto/rsa/oaep/mod.xu](../../src/crypto/rsa/oaep/mod.xu) | 4 | 0 | 5 | not-measured | not-measured | 0 |
| [src/crypto/sha1/mod.xu](../../src/crypto/sha1/mod.xu) | 8 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/sha256/mod.xu](../../src/crypto/sha256/mod.xu) | 10 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/sha3/mod.xu](../../src/crypto/sha3/mod.xu) | 9 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/sha512/mod.xu](../../src/crypto/sha512/mod.xu) | 11 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/sm2/mod.xu](../../src/crypto/sm2/mod.xu) | 47 | 0 | 6 | not-measured | not-measured | 0 |
| [src/crypto/sm3/mod.xu](../../src/crypto/sm3/mod.xu) | 11 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/sm4/mod.xu](../../src/crypto/sm4/mod.xu) | 18 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/sm9/mod.xu](../../src/crypto/sm9/mod.xu) | 26 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/subtle/mod.xu](../../src/crypto/subtle/mod.xu) | 5 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/tls/mod.xu](../../src/crypto/tls/mod.xu) | 33 | 0 | 14 | not-measured | not-measured | 0 |
| [src/crypto/x509/mod.xu](../../src/crypto/x509/mod.xu) | 56 | 0 | 21 | not-measured | not-measured | 0 |
| [src/crypto/x509/pkix/mod.xu](../../src/crypto/x509/pkix/mod.xu) | 2 | 0 | 0 | not-measured | not-measured | 0 |
| [src/crypto/zuc/mod.xu](../../src/crypto/zuc/mod.xu) | 7 | 0 | 0 | not-measured | not-measured | 0 |
| [src/database/sql/mod.xu](../../src/database/sql/mod.xu) | 111 | 0 | 1 | not-measured | not-measured | 0 |
| [src/database/sql/driver/mod.xu](../../src/database/sql/driver/mod.xu) | 13 | 0 | 2 | not-measured | not-measured | 0 |
| [src/encoding/ascii85/mod.xu](../../src/encoding/ascii85/mod.xu) | 3 | 0 | 0 | not-measured | not-measured | 0 |
| [src/encoding/asn1/mod.xu](../../src/encoding/asn1/mod.xu) | 37 | 0 | 1 | not-measured | not-measured | 0 |
| [src/encoding/base32/mod.xu](../../src/encoding/base32/mod.xu) | 14 | 0 | 0 | not-measured | not-measured | 0 |
| [src/encoding/base64/mod.xu](../../src/encoding/base64/mod.xu) | 10 | 0 | 0 | not-measured | not-measured | 0 |
| [src/encoding/binary/mod.xu](../../src/encoding/binary/mod.xu) | 24 | 0 | 0 | not-measured | not-measured | 0 |
| [src/encoding/csv/mod.xu](../../src/encoding/csv/mod.xu) | 18 | 0 | 1 | not-measured | not-measured | 0 |
| [src/encoding/hex/mod.xu](../../src/encoding/hex/mod.xu) | 7 | 0 | 0 | not-measured | not-measured | 0 |
| [src/encoding/json/mod.xu](../../src/encoding/json/mod.xu) | 37 | 0 | 0 | not-measured | not-measured | 0 |
| [src/encoding/pem/mod.xu](../../src/encoding/pem/mod.xu) | 4 | 0 | 1 | not-measured | not-measured | 0 |
| [src/encoding/xml/mod.xu](../../src/encoding/xml/mod.xu) | 13 | 0 | 1 | not-measured | not-measured | 0 |
| [src/encoding/xun/mod.xu](../../src/encoding/xun/mod.xu) | 45 | 0 | 0 | not-measured | not-measured | 0 |
| [src/errors/mod.xu](../../src/errors/mod.xu) | 13 | 0 | 0 | not-measured | not-measured | 0 |
| [src/flag/mod.xu](../../src/flag/mod.xu) | 35 | 0 | 0 | not-measured | not-measured | 0 |
| [src/fmt/mod.xu](../../src/fmt/mod.xu) | 15 | 0 | 1 | not-measured | not-measured | 0 |
| [src/hash/adler32/mod.xu](../../src/hash/adler32/mod.xu) | 8 | 0 | 0 | not-measured | not-measured | 0 |
| [src/hash/crc32/mod.xu](../../src/hash/crc32/mod.xu) | 16 | 0 | 0 | not-measured | not-measured | 0 |
| [src/hash/crc64/mod.xu](../../src/hash/crc64/mod.xu) | 15 | 0 | 0 | not-measured | not-measured | 0 |
| [src/hash/fnv/mod.xu](../../src/hash/fnv/mod.xu) | 13 | 0 | 0 | not-measured | not-measured | 0 |
| [src/hash/maphash/mod.xu](../../src/hash/maphash/mod.xu) | 9 | 0 | 0 | not-measured | not-measured | 0 |
| [src/html/mod.xu](../../src/html/mod.xu) | 20 | 0 | 1 | not-measured | not-measured | 0 |
| [src/html/query/mod.xu](../../src/html/query/mod.xu) | 9 | 0 | 1 | not-measured | not-measured | 0 |
| [src/html/template/mod.xu](../../src/html/template/mod.xu) | 9 | 0 | 0 | not-measured | not-measured | 0 |
| [src/id/mod.xu](../../src/id/mod.xu) | 7 | 0 | 0 | not-measured | not-measured | 0 |
| [src/image/mod.xu](../../src/image/mod.xu) | 54 | 0 | 0 | not-measured | not-measured | 0 |
| [src/image/color/mod.xu](../../src/image/color/mod.xu) | 20 | 0 | 0 | not-measured | not-measured | 0 |
| [src/image/draw/mod.xu](../../src/image/draw/mod.xu) | 3 | 0 | 0 | not-measured | not-measured | 0 |
| [src/image/gif/mod.xu](../../src/image/gif/mod.xu) | 4 | 0 | 0 | not-measured | not-measured | 0 |
| [src/image/jpeg/mod.xu](../../src/image/jpeg/mod.xu) | 2 | 0 | 1 | not-measured | not-measured | 0 |
| [src/image/png/mod.xu](../../src/image/png/mod.xu) | 3 | 0 | 0 | not-measured | not-measured | 0 |
| [src/index/suffixarray/mod.xu](../../src/index/suffixarray/mod.xu) | 6 | 0 | 0 | not-measured | not-measured | 0 |
| [src/internal/dependency/mod.xu](../../src/internal/dependency/mod.xu) | 2 | 0 | 0 | not-measured | not-measured | 0 |
| [src/internal/modulepath/mod.xu](../../src/internal/modulepath/mod.xu) | 7 | 0 | 0 | not-measured | not-measured | 0 |
| [src/internal/modulezip/mod.xu](../../src/internal/modulezip/mod.xu) | 1 | 0 | 1 | not-measured | not-measured | 0 |
| [src/internal/sdk/mod.xu](../../src/internal/sdk/mod.xu) | 14 | 0 | 1 | not-measured | not-measured | 0 |
| [src/internal/semver/mod.xu](../../src/internal/semver/mod.xu) | 3 | 0 | 0 | not-measured | not-measured | 0 |
| [src/internal/sumdb/mod.xu](../../src/internal/sumdb/mod.xu) | 14 | 0 | 0 | not-measured | not-measured | 0 |
| [src/internal/toolpath/mod.xu](../../src/internal/toolpath/mod.xu) | 3 | 0 | 0 | not-measured | not-measured | 0 |
| [src/io/mod.xu](../../src/io/mod.xu) | 88 | 0 | 0 | not-measured | not-measured | 0 |
| [src/io/fs/mod.xu](../../src/io/fs/mod.xu) | 6 | 0 | 0 | not-measured | not-measured | 0 |
| [src/log/mod.xu](../../src/log/mod.xu) | 42 | 0 | 0 | not-measured | not-measured | 0 |
| [src/log/slog/mod.xu](../../src/log/slog/mod.xu) | 16 | 0 | 2 | not-measured | not-measured | 0 |
| [src/maps/mod.xu](../../src/maps/mod.xu) | 28 | 0 | 0 | not-measured | not-measured | 0 |
| [src/math/mod.xu](../../src/math/mod.xu) | 162 | 0 | 0 | not-measured | not-measured | 0 |
| [src/math/big/mod.xu](../../src/math/big/mod.xu) | 69 | 0 | 2 | not-measured | not-measured | 0 |
| [src/math/bits/mod.xu](../../src/math/bits/mod.xu) | 33 | 0 | 0 | not-measured | not-measured | 0 |
| [src/math/rand/mod.xu](../../src/math/rand/mod.xu) | 9 | 0 | 0 | not-measured | not-measured | 0 |
| [src/mime/mod.xu](../../src/mime/mod.xu) | 24 | 0 | 0 | not-measured | not-measured | 0 |
| [src/mime/multipart/mod.xu](../../src/mime/multipart/mod.xu) | 17 | 0 | 1 | not-measured | not-measured | 0 |
| [src/mime/quotedprintable/mod.xu](../../src/mime/quotedprintable/mod.xu) | 2 | 0 | 0 | not-measured | not-measured | 0 |
| [src/net/mod.xu](../../src/net/mod.xu) | 396 | 0 | 11 | not-measured | not-measured | 0 |
| [src/net/apns/mod.xu](../../src/net/apns/mod.xu) | 7 | 0 | 0 | not-measured | not-measured | 0 |
| [src/net/http/mod.xu](../../src/net/http/mod.xu) | 98 | 0 | 9 | not-measured | not-measured | 0 |
| [src/net/http/cookiejar/mod.xu](../../src/net/http/cookiejar/mod.xu) | 7 | 0 | 0 | not-measured | not-measured | 0 |
| [src/net/http/httptest/mod.xu](../../src/net/http/httptest/mod.xu) | 12 | 0 | 1 | not-measured | not-measured | 0 |
| [src/net/http2/mod.xu](../../src/net/http2/mod.xu) | 18 | 0 | 1 | not-measured | not-measured | 0 |
| [src/net/mail/mod.xu](../../src/net/mail/mod.xu) | 4 | 0 | 1 | not-measured | not-measured | 0 |
| [src/net/netip/mod.xu](../../src/net/netip/mod.xu) | 25 | 0 | 1 | not-measured | not-measured | 0 |
| [src/net/poller/mod.xu](../../src/net/poller/mod.xu) | 14 | 0 | 0 | not-measured | not-measured | 0 |
| [src/net/pool/mod.xu](../../src/net/pool/mod.xu) | 7 | 0 | 0 | not-measured | not-measured | 0 |
| [src/net/smtp/mod.xu](../../src/net/smtp/mod.xu) | 10 | 0 | 2 | not-measured | not-measured | 0 |
| [src/net/stream/mod.xu](../../src/net/stream/mod.xu) | 12 | 0 | 0 | not-measured | not-measured | 0 |
| [src/net/textproto/mod.xu](../../src/net/textproto/mod.xu) | 15 | 0 | 0 | not-measured | not-measured | 0 |
| [src/net/url/mod.xu](../../src/net/url/mod.xu) | 31 | 0 | 2 | not-measured | not-measured | 0 |
| [src/os/mod.xu](../../src/os/mod.xu) | 135 | 0 | 1 | not-measured | not-measured | 0 |
| [src/os/exec/mod.xu](../../src/os/exec/mod.xu) | 13 | 0 | 3 | not-measured | not-measured | 0 |
| [src/os/signal/mod.xu](../../src/os/signal/mod.xu) | 11 | 0 | 3 | not-measured | not-measured | 0 |
| [src/os/user/mod.xu](../../src/os/user/mod.xu) | 4 | 0 | 1 | not-measured | not-measured | 0 |
| [src/path/mod.xu](../../src/path/mod.xu) | 29 | 0 | 0 | not-measured | not-measured | 0 |
| [src/path/filepath/mod.xu](../../src/path/filepath/mod.xu) | 18 | 0 | 2 | not-measured | not-measured | 0 |
| [src/rate/mod.xu](../../src/rate/mod.xu) | 6 | 0 | 0 | not-measured | not-measured | 0 |
| [src/regexp/mod.xu](../../src/regexp/mod.xu) | 20 | 0 | 2 | not-measured | not-measured | 0 |
| [src/slices/mod.xu](../../src/slices/mod.xu) | 63 | 0 | 0 | not-measured | not-measured | 0 |
| [src/sort/mod.xu](../../src/sort/mod.xu) | 18 | 0 | 1 | not-measured | not-measured | 0 |
| [src/strconv/mod.xu](../../src/strconv/mod.xu) | 27 | 0 | 2 | not-measured | not-measured | 0 |
| [src/strings/mod.xu](../../src/strings/mod.xu) | 92 | 0 | 0 | not-measured | not-measured | 0 |
| [src/sync/mod.xu](../../src/sync/mod.xu) | 29 | 0 | 2 | not-measured | not-measured | 0 |
| [src/testing/mod.xu](../../src/testing/mod.xu) | 46 | 0 | 0 | not-measured | not-measured | 0 |
| [src/testing/fstest/mod.xu](../../src/testing/fstest/mod.xu) | 9 | 0 | 0 | not-measured | not-measured | 0 |
| [src/testing/iotest/mod.xu](../../src/testing/iotest/mod.xu) | 9 | 0 | 0 | not-measured | not-measured | 0 |
| [src/text/scanner/mod.xu](../../src/text/scanner/mod.xu) | 17 | 0 | 0 | not-measured | not-measured | 0 |
| [src/text/tabwriter/mod.xu](../../src/text/tabwriter/mod.xu) | 7 | 0 | 1 | not-measured | not-measured | 0 |
| [src/text/template/mod.xu](../../src/text/template/mod.xu) | 12 | 0 | 1 | not-measured | not-measured | 0 |
| [src/tile/mod.xu](../../src/tile/mod.xu) | 54 | 0 | 0 | not-measured | not-measured | 0 |
| [src/time/mod.xu](../../src/time/mod.xu) | 102 | 0 | 0 | not-measured | not-measured | 0 |
| [src/timer/mod.xu](../../src/timer/mod.xu) | 8 | 0 | 0 | not-measured | not-measured | 0 |
| [src/ui/mod.xu](../../src/ui/mod.xu) | 2655 | 0 | 10 | not-measured | not-measured | 0 |
| [src/ui/draw/mod.xu](../../src/ui/draw/mod.xu) | 206 | 0 | 0 | not-measured | not-measured | 0 |
| [src/ui/internal/codec/mod.xu](../../src/ui/internal/codec/mod.xu) | 5 | 0 | 0 | not-measured | not-measured | 0 |
| [src/ui/layout/mod.xu](../../src/ui/layout/mod.xu) | 69 | 0 | 0 | not-measured | not-measured | 0 |
| [src/ui/webview/mod.xu](../../src/ui/webview/mod.xu) | 61 | 0 | 4 | not-measured | not-measured | 0 |
| [src/ui/widgets/mod.xu](../../src/ui/widgets/mod.xu) | 1988 | 0 | 15 | not-measured | not-measured | 0 |
| [src/unicode/mod.xu](../../src/unicode/mod.xu) | 35 | 0 | 0 | not-measured | not-measured | 0 |
| [src/unicode/utf16/mod.xu](../../src/unicode/utf16/mod.xu) | 6 | 0 | 0 | not-measured | not-measured | 0 |
| [src/unicode/utf8/mod.xu](../../src/unicode/utf8/mod.xu) | 12 | 0 | 0 | not-measured | not-measured | 0 |
| [src/xacp/mod.xu](../../src/xacp/mod.xu) | 94 | 0 | 1 | not-measured | not-measured | 0 |

## 重放

```sh
python3 scripts/generate_stdlib_matrix.py
python3 scripts/generate_stdlib_audit.py
python3 scripts/generate_stdlib_matrix.py --check
python3 scripts/generate_stdlib_audit.py --check
```

记录新证据前必须先生成当前矩阵并实际运行 fixture。证据 recorder 会拒绝源哈希/fixture 列表过时的矩阵。历史未绑定证据保留为 rejected，不能补填当前哈希来冒充重新运行。
