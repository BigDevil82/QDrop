# 自行部署

本指南供公开源码使用。域名、IP、SSH 账号、注册码、token 和签名密钥由部署者自行配置，不提交 Git。两端在设置填写 HTTPS origin，无需为不同服务器重新编译。当前没有远程部署；本机配置验证不代表容器和公网验收通过。

## 1. 准备域名和服务器

准备支持 Docker Engine 与 Compose plugin 的 Linux 服务器，至少预留 2 GiB 持久磁盘。按实际系统参考 [Docker 安装](https://docs.docker.com/engine/install/) 和 [Compose plugin 安装](https://docs.docker.com/compose/install/linux/)，宿主机不需要安装 Python、Redis 或数据库。

DNS 添加 A 记录：主机记录例如 qdrop，指向自己的公网 IPv4；只有实际支持 IPv6 时才添加 AAAA。云安全组与主机防火墙允许 TCP 80/443；443 UDP 可选用于 HTTP/3。API 8000 不开放公网。

```bash
ssh YOUR_USER@YOUR_SERVER
cat /etc/os-release
df -h
docker version
docker compose version
sudo ss -lntp
```

默认配置由 Caddy 绑定 80/443，适用于端口空闲的服务器。已有 Nginx、Caddy、宝塔或其他站点时先设计代理接入，不直接停止或覆盖。DNS、端口及持久卷满足条件时自动申请/续期证书，见 [Caddy 自动 HTTPS 条件](https://caddyserver.com/docs/automatic-https)。

## 2. 获取源码和配置

未发布时上传源码压缩包，解压为 /srv/QDrop。GitHub 发布后替换下面仓库地址。当前用户需有 /srv 写权限，按服务器账户安排执行。

```bash
cd /srv
git clone https://github.com/YOUR_NAME/QDrop.git
cd QDrop
umask 077
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
nano deploy/.env
```

至少替换两项，保持一致（example.com 是占位，不能直接部署）：

```dotenv
PUBLIC_DOMAIN=qdrop.example.com
PUBLIC_BASE_URL=https://qdrop.example.com
```

PUBLIC_DOMAIN 只填主机名；PUBLIC_BASE_URL 填 HTTPS origin，不带路径、账号或查询参数。后者记录公开地址供客户端配置参考，不修改 API 监听，也不负责客户端自动发现。

| 配置 | 用途 |
| --- | --- |
| PUBLIC_DOMAIN | Caddy 站点和证书域名 |
| PUBLIC_BASE_URL | 客户端应填写的公开 HTTPS origin |
| DATA_DIR | 容器内私有数据目录，Compose 固定 /data，与数据卷对应，保持默认 |
| MAX_FILE_BYTES | 服务端文件和 Caddy 请求体上限，默认 50 MiB |
| MAX_TEXT_BYTES | 服务端文本上限，默认 64 KiB |
| STORAGE_QUOTA_BYTES | 总配额，含未提交上传预留，默认 1 GiB |
| DEFAULT_TTL_SECONDS | 普通正文提交后 TTL 上限，默认 24 小时 |
| ACK_GRACE_SECONDS | ACK 后保留期，默认 300 秒 |
| UPLOAD_DEADLINE_SECONDS | 上传截止，默认 1800 秒；敏感文本另受 5 分钟限制 |
| LOG_LEVEL | info/warning/error/critical，不输出正文或凭证 |

客户端仍限制文件 50 MiB、文本 64 KiB；服务端提高参数不会提高客户端上限。MAX_FILE_BYTES 至少覆盖 MAX_TEXT_BYTES 和 16 KiB 元数据，防止代理提前拒绝合法请求。真实 .env、私钥和本地 override 已被 Git 忽略，只有 .env.example 可以公开。数据卷不能作为静态文件站点。

## 3. 构建、启动和检查

在仓库根目录执行，显式指定 env 文件；无 Docker 权限时按服务器账户安排使用 sudo。

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
docker compose --env-file deploy/.env -f deploy/compose.yaml logs --tail=100 api caddy
# 改成自己的域名，不使用 -k 绕过证书校验
curl --fail https://qdrop.example.com/readyz
```

期望 readyz 返回 {"ready":true}。API 单实例、非 root，SQLite WAL 和正文在私有专用卷；Caddy 为唯一公网入口。启动自动执行 Alembic。失败先查 DNS、端口、证书及容器日志，不公开明文 API。

### 已有 Apache 或其他 HTTPS 代理

已有代理占用 80/443 时，使用下面的替代启动命令，只启动 API，不启动本项目的 Caddy：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.external-proxy.example.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml -f deploy/compose.external-proxy.example.yaml up -d --build api
```

API_BIND_PORT 可在私有 .env 调整，默认 18080；API 只绑定 127.0.0.1。Apache 示例见 deploy/apache-vhost.example.conf，要求 2.4.47+ 及 proxy/proxy_http/ssl/headers/reqtimeout 模块。在服务器复制为自己的独立站点，替换域名、证书路径和后端端口；文件上限需与 .env 保持一致。先执行 apache2ctl configtest，通过后 graceful reload，保留其他站点。WebSocket 路由必须支持 Upgrade，依据 [Apache 代理文档](https://httpd.apache.org/docs/2.4/mod/mod_proxy.html)。已有通配符证书可在覆盖目标域名且未过期时复用，沿用证书原有续期机制。

后续 exec、ps、logs、备份和升级也要沿用相同的两份 -f 参数；升级仅启动 api，避免误启动 Caddy 抢占端口。不把实际服务器配置文件提交源码。

## 4. 注册两端并验收

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python -m app.cli enroll
# Windows 填 HTTPS 地址及本次注册码，注册。
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python -m app.cli enroll
# Android 正式包填相同地址和新的注册码，注册。
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python -m app.cli devices
```

每个注册码 10 分钟内有效，单次使用。不要放到 issue、公开日志或截图。手机刷新设备、选择电脑，先测中文文本，再发 PDF，核对摘要与回执，再测离线补收和服务端重启。正式客户端禁止明文 HTTP。

```bash
# 撤销设备
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python -m app.cli revoke DEVICE_ID
```

## 5. 备份和升级

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml exec api python -m app.cli backup /data/backup.sqlite
docker compose --env-file deploy/.env -f deploy/compose.yaml cp api:/data/backup.sqlite ./backup.sqlite
chmod 600 backup.sqlite
```

数据库含设备凭证摘要与元数据，应作为私有数据保护。默认只备份数据库，临时正文可过期。完整恢复需要停 API 后一致备份数据卷，并先在隔离实例验证。不能在运行 SQLite 时只复制主库而遗漏 WAL。

升级前备份，再 git pull --ff-only 和执行 up -d --build。检查迁移、readyz、HTTPS 文件校验与 ACK 后再删除旧备份。回滚需要兼容迁移。不要执行 down -v，它会删除数据和 TLS 卷。

本机 Docker daemon 未运行；容器启动、公网 TLS 和备份恢复尚未执行，见 TEST_RESULTS.md。
