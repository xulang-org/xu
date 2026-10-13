# 17_database_postgres

用 `database/sql` 调用 PostgreSQL。驱动由独立模块 `packages/postgres` 提供，通过 `#postgres` 导入；标准库只提供通用 SQL API 和驱动接口。

本目录的 `xu.xun` 已声明本地依赖：

```xun
require:
  postgres: file:../../../packages
```

示例覆盖：

- `sql.open(postgres.driver(), dsn)` 与 `ping`
- 建表及参数化 `exec`（PostgreSQL 占位符为 `$1`、`$2`、`$3`）
- `prepare`、事务 `begin` / `commit`
- `query` + `rows.next()` / `rows.take()`
- `query_row` 与关闭连接

## 启动本地 PostgreSQL

```bash
docker run --rm --name xu-postgres \
 -e POSTGRES_PASSWORD=postgres \
 -e POSTGRES_DB=xu_demo \
 -p 5432:5432 \
 postgres:15-alpine
```

等容器就绪后，在另一个终端编译并运行：

```bash
XU=./bin/xu
export XU_POSTGRES_DSN='postgres://postgres:postgres@127.0.0.1:5432/xu_demo?sslmode=disable'
$XU build developer/examples/17_database_postgres/main.xu -o /tmp/xu_17_postgres
chmod +x /tmp/xu_17_postgres && /tmp/xu_17_postgres
```

未设置 `XU_POSTGRES_DSN` 时，程序使用上面的本地 DSN。也支持 libpq 风格：

```text
host=127.0.0.1 port=5432 user=postgres password=postgres dbname=xu_demo sslmode=disable
```

当前版本支持 trust、明文、MD5、SCRAM-SHA-256 认证及 PostgreSQL 扩展查询协议；参数不会插值进 SQL。当前 `database/sql` 单次调用最多传 3 个参数。首版尚未启用 TLS，只应在本机或受保护网络中显式使用 `sslmode=disable`。
