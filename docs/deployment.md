# 部署与备份

## fp.lovexh.me 一键部署

默认方案使用两个容器：应用 + Caddy。Caddy 为 `fp.lovexh.me` 自动申请和续期 HTTPS 证书，并将 HTTP 跳转到 HTTPS。应用8000端口仅在 Docker 网络内开放，无需另装 Nginx。相关机制见 [Caddy 自动 HTTPS 文档](https://caddyserver.com/docs/automatic-https)。

部署前准备：

- 服务器安装 Docker Engine 和 Docker Compose 插件，`docker compose version` 可以执行。
- 将域名 `fp.lovexh.me` 的 A 记录指向这台服务器的公网 IPv4。如果配置 AAAA 记录，IPv6 也必须正确指向服务器且可访问。
- 在云安全组和服务器防火墙放行 TCP 80、443；UDP 443 可用于 HTTP/3。确保80、443端口没有被其他服务占用。

首次部署，在服务器执行：

```bash
git clone https://github.com/Lvaxy-dup/fp.lovexh.me.git
cd fp.lovexh.me
cp .env.example .env
nano .env
# 填写 OPENAI_API_KEY，以及需要使用的 PADDLEOCR_API_TOKEN，然后保存
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app caddy
```

`.env` 已存在时跳过复制，不要覆盖密钥。Compose 已为生产环境强制启用 Secure Cookie，不需要改本地开发的默认配置。

等待应用健康检查通过与证书签发后，访问 **https://fp.lovexh.me**。验证：

```bash
curl -I http://fp.lovexh.me
curl https://fp.lovexh.me/healthz
```

第一条应跳转 HTTPS，第二条返回 `{"status":"ok"}`。如果证书未成功签发，检查 Caddy 日志、DNS 和外部80/443连通性；首次签发需要服务器可连接证书颁发服务。

数据保存在 `travel-data` 命名卷；证书与 Caddy 状态保存在 `caddy-data`、`caddy-config` 卷。更新或重建容器会复用它们。**保留部署目录名称和 Compose 项目名称**；改名可能创建另一套空数据卷。容器日志按10MB轮转，保留3份。

更新：

```bash
git pull --ff-only
docker compose pull caddy
docker compose up -d --build
```

如服务器已有 Nginx/宝塔占用80、443端口，使用单独的宿主机反代方案：

```bash
docker compose -f compose.yaml -f compose.host-proxy.yaml up -d --build app
```

这条命令只启动应用，监听本机 `127.0.0.1:8000`，不启动 Caddy。在已有的 `fp.lovexh.me` HTTPS 站点中使用 `deploy/nginx.conf.example` 反代片段，证书由已有站点管理。选定此方案后，后续更新也使用同一条命令；不要再直接运行默认的 `docker compose up` 启动 Caddy。

Compose 限制2GB内存、2个CPU和进程数，供初始试用；按实际服务器资源与材料大小调整。系统免费免登录，公网访问者可以使用配置的模型额度，按当前产品决定暂不增加用户额度。

必须保持一个实例、一个 worker。不能通过增加 `--workers` 扩容后台任务；数据目录锁会拒绝第二个实例启动。更新用 `docker compose up -d --build`，不要使用 `docker compose down -v` 删除数据卷。

`TRAVEL_COOKIE_SECURE=true` 只用于 HTTPS。本地直接 HTTP 测试时设为 false。代理保留原始 Host，避免请求来源校验失败。Caddy 和应用都限制请求体大小；单个文件仍最多20MB。

## 自动备份

默认 `TRAVEL_AUTO_BACKUP=true`。后台每小时检查，当天尚无成功备份时生成 `<数据目录>/backups/YYYY-MM-DD.zip`，保留最近7份。备份包含同一写锁保护下的 SQLite 快照、会话恢复映射、个人档案、表单和原件。发现缺失原件会让备份失败并记录日志，避免把不完整备份当成成功。

自动备份位于同一个数据卷，需要定期复制到独立存储。备份和找回文件均可访问个人记录，不要提交 GitHub。

## 手工备份和恢复

以下命令在项目目录、安装好依赖的 Python 环境执行。手工备份前先停应用；若仍有进程使用数据目录，命令会拒绝执行。

```bash
python -m server.maintenance backup --output /secure-backups/travel-20260920.zip
python -m server.maintenance restore /secure-backups/travel-20260920.zip --destination /srv/travel-restored
```

恢复目标必须是不存在的新目录。程序检查压缩包路径、数据库完整性及附件是否齐全，不覆盖原数据。恢复完成后将 `TRAVEL_DATA_DIR` 改为新目录，再启动单实例服务。

Docker 手工备份示例（写入现有数据卷）：

```bash
docker compose stop app
docker compose run --rm app python -m server.maintenance backup --output /data/backups/manual-20260920.zip
docker compose start app
```

Docker 恢复可把可信备份放入数据卷 `backups` 后，停服执行恢复到 `/data/restored-20260920`，再在 Compose 中将应用 `TRAVEL_DATA_DIR` 改为该目录。恢复到新目录后保留旧目录，核对完成再按运维流程处理旧数据。

## 从本地迁移

停服后制作备份，将备份安全传到服务器并恢复。旧 Windows 绝对附件路径会按 `uploads/记录ID/材料ID.扩展名` 在新数据目录下解析，无需逐条修改数据库。迁移整套记录时必须一起保留 `travel.db` 与附件。

本地浏览器与服务器域名的存储不同。迁移前在个人信息设置保存“找回文件”，服务器恢复数据库后，在服务器页面导入该文件认领原记录。若服务器从空数据库开始，旧找回文件不会凭空带回未迁移的记录。

每次更新后至少检查一次：合成材料上传、单表填写、连续修改后刷新、补助人工纠正、打印，以及从备份恢复到新目录。自动化回归不替代真实服务器验收。
