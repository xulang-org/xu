# Xu Mail

本地邮件服务：SMTP 收信、网页写信、POP3 取信、关键词垃圾过滤、联系人分组。

管理界面在 [`www/`](www/)（`index.html` / `app.css` / `app.js`）。Xu 只托管这些静态文件并提供 `/api/*` JSON 接口，页面不要写进 `.xu`。

数据文件落在本目录 `data/`（可用环境变量改路径）。用户写的是 `develop/xu_mail`，仓库开发者树是 `developer/`，所以放在这里。

## 编译

在仓库根：

```bash
XU=./developer/bin/xu.macos.arm64 # 产品 hosted seed，按本机平台替换
./scripts/run_product_compiler.sh "$XU" build developer/xu_mail -o /tmp/xu_mail.xin
/tmp/xu_mail.xin
```

如需排查 primer，只能显式走 oracle/recovery（不属于产品或自举证据）：

```bash
cargo build --manifest-path bootstrap/Cargo.toml -p xu
XU_BOOT=./bootstrap/target/debug/xu
"$XU_BOOT" developer/xu_mail -o /tmp/xu_mail_oracle.xin
```

请在仓库根目录启动，这样默认能读到 `developer/xu_mail/www`。Web 进程会再拉起 SMTP / POP3 子进程；也可以单独跑 `/tmp/xu_mail.xin smtp`、`/tmp/xu_mail.xin pop3`。

## 端口

| 服务 | 默认 | 环境变量 |
|------|------|----------|
| Web 管理界面 | `http://127.0.0.1:8088` | `XU_MAIL_HTTP` |
| SMTP 投递 | `127.0.0.1:2525` | `XU_MAIL_SMTP` |
| POP3 取信 | `127.0.0.1:1110` | `XU_MAIL_POP3` |
| 数据目录 | `developer/xu_mail/data` | `XU_MAIL_DATA` 或启动参数 |
| 管理页静态文件 | `developer/xu_mail/www` | `XU_MAIL_WWW` |

本机投递域名是 **`xu.local`**。网页左上角可切换用户（`ada` / `bob` / 任意本地部分）。

## 收发

打开 `http://127.0.0.1:8088`，点「写邮件」。只投递 `*@xu/local`。

命令行（不启动服务）：

```bash
/tmp/xu_mail send ada@xu.local bob@xu.local "hello" "body text"
```

SMTP（）：

```python
import smtplib
from email.mime.text import MIMEText
msg = MIMEText("hello from smtp", "plain", "utf-8")
msg["From"] = "bob@xu.local"
msg["To"] = "ada@xu.local"
msg["Subject"] = "smtp ping"
s = smtplib.SMTP("127.0.0.1", 2525)
s.sendmail(msg["From"], [msg["To"]], msg.as_string())
s.quit()
```

POP3：USER 填 `ada`（不必带域名），PASS 任意非空。只拉该用户收件箱。

## 垃圾过滤

规则在网页「过滤规则」。默认带一批中英文关键词。另外会看：

- 主题几乎全大写
- 正文链接过多
- 发件人是否在通讯录（「其它」以外的分组会减分）

分数 ≥ 28 进垃圾箱。可在邮件页「标为垃圾 / 不是垃圾」。

## 联系人分组

「分组」里建组，「联系人」里把邮箱归组。侧栏点组名，收件箱只显示该组发件人的来信。
