# Xu 服务器连接配置模板

将本文件复制为仓库根目录的 `server.md` 后再填写；`server.md` 已被 `.gitignore` 忽略，禁止提交。

```text
SERVER_HOST=<hostname-or-ip>
SERVER_SSH_PORT=<ssh-port>
SERVER_USER=<deployment-user>
SERVER_APP_ROOT=/srv/xu-server
SERVER_SERVICE=xu-server.service
SERVER_TARGET=linux-x64
SERVER_HEALTH_URL=http://127.0.0.1:18080/health
# Optional; prefer SSH agent when possible. Paths are relative to this file.
SERVER_IDENTITY_FILE=/home/deploy/.ssh/id_ed25519
# Optional but recommended for pinned host-key verification. If omitted, the
# user's normal ~/.ssh/known_hosts is used with StrictHostKeyChecking=yes.
SERVER_KNOWN_HOSTS_FILE=/home/deploy/.ssh/known_hosts
# Optional migration fallback; do not commit a password or token.
# SERVER_PASSWORD_FILE=/absolute/path/to/secret
```

该文件只定义人工核对字段，不是 shell 脚本；`scripts/deploy_xu_remote.sh` 会按白名单解析字段，不会执行任意行。不要在此文件或 `server.md` 中保存明文密码、私钥、token、数据库 URL 或证书私钥。优先使用 SSH key/agent、操作系统密钥链或 CI secret。远程适配器默认严格校验 host key；首次连接应先通过受信渠道写入 `known_hosts`，只有明确的一次性引导场景才设置 `XU_SERVER_ACCEPT_NEW_HOST=1`。远程部署前必须确认目标服务、监听端口、回滚版本和变更审批；`scripts/deploy_xu_server.sh` 仍只在本地构建、检查和运行，远端动作必须显式调用 `deploy_xu_remote.sh`。
