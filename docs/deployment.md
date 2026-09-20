# 部署与备份

## 部署

1. 克隆仓库，复制 `.env.example` 为 `.env` 并填写模型及 OCR 密钥。已有配置不要覆盖。
2. `docker compose up -d --build`。Compose 将应用绑定到服务器本机8000端口，数据写入命名卷 `travel-data`，不会随镜像替换丢失。
3. 在服务器现有的 HTTPS 站点中加入 `deploy/nginx.conf.example` 的反向代理配置，并配置实际域名及证书。应用不直接监听公网。
4. 检查 `curl http://127.0.0.1:8000/healthz` 返回 `{"status":"ok"}`，再通过 HTTPS 域名验证上传、填写、保存、刷新和打印。
5. `docker compose logs --tail=100 app` 查看启动与备份日志。容器日志按10MB轮转，保留3份。

Compose 限制2GB内存、2个CPU和进程数，供初始试用；按实际服务器资源与材料大小调整。系统免费免登录，公网访问者可以使用配置的模型额度，按当前产品决定暂不增加用户额度。

必须保持一个实例、一个 worker。不能通过增加 `--workers` 扩容后台任务；数据目录锁会拒绝第二个实例启动。更新用 `docker compose up -d --build`，不要使用 `docker compose down -v` 删除数据卷。

`TRAVEL_COOKIE_SECURE=true` 只用于 HTTPS。本地直接 HTTP 测试时设为 false。Nginx 将 Host 原样传入，避免请求来源校验失败。

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
