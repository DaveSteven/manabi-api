# Manabi 服务器部署

默认通过 `ssh manabi` 部署到 `/opt/manabi`，服务域名为 `biblenotes.cc`。脚本不保存 SSH 密码、私钥或账号密码。数据库快照上传限速为 256 KiB/s，以兼容当前网络；代码和资源采用增量同步。要求 SSH 别名以 root 登录，服务器为 Ubuntu 24.04；本机需要 bash、rsync，首次导入还需要运行中的本机 Docker 数据库。

## 域名

在 Cloudflare 添加 `A` 记录：名称 `@`，地址 `160.251.140.88`，代理状态为 **仅 DNS（灰云）**。如果已有同名记录，应先确认没有其他网站使用它；有指向其他主机的 AAAA 记录时也需处理，避免证书校验连接到错误主机。

服务器内部防火墙和云厂商控制台的安全组都需放行 TCP 80、443（来源 0.0.0.0/0），数据库端口不对外暴露。使用 Let's Encrypt 的公开证书，Cloudflare 目前只负责 DNS。以后开启代理时使用 Full (strict)，并补充可信代理 IP 配置后再启用；不要直接信任任意客户端传入的 CF-Connecting-IP。

## 使用

从 `manabi_api` 目录运行：

```sh
# 只读检查；不带参数也默认 check
bash deploy/deploy.sh check

# 首次部署：数据库必须为空。当前服务器已经上传资源，可跳过资源同步。
bash deploy/deploy.sh deploy --seed-local --skip-assets

# 全新 Ubuntu 主机：安装依赖、同步资源、首次导入
bash deploy/deploy.sh deploy --bootstrap --seed-local

# 日常更新代码，不重新导入数据库
bash deploy/deploy.sh deploy --skip-assets

# 同时增量同步音频、图片
bash deploy/deploy.sh deploy
```

可用 `--host`、`--domain` 覆盖默认 SSH 别名和域名。`--seed-local` 会导入本机数据库中的题库、账号和学习记录（包括本机测试记录），并清除导入的登录 token；用户需重新登录。它不会覆盖已有数据库。本机数据库不会被修改。

首次部署若已完成数据导入、随后在 DNS/证书步骤失败，可使用 `bash deploy/deploy.sh tls` 单独重试证书配置；重新部署时**去掉 `--seed-local`**。构建失败时旧容器继续运行；迁移和重启失败时脚本报错，不自动回滚数据库。生产数据以服务器为准，后续不再用本机快照覆盖。

## HTTPS 与运行状态

脚本检查本机 HTTP 验证路径可达后申请证书，证书机构再从公网校验域名和路径，成功后配置 HTTPS 和 HTTP 跳转。证书通过 `manabi-cert-renew.timer` 每日检查两次；首次部署采用无邮件 ACME 账号，可后续用 Certbot 添加联系邮箱。

```sh
ssh manabi 'cd /opt/manabi && docker compose ps'
ssh manabi 'cd /opt/manabi && docker compose logs --tail=100 api'
ssh manabi 'systemctl list-timers manabi-cert-renew.timer'
curl --fail https://biblenotes.cc/api/v1/health
```

App 的“连接设置”填写 `https://biblenotes.cc`，不包含 `/api/v1`。线上禁用游客、注册和游客升级入口，仅允许已有正式账号登录。

## 备份与故障处理

每次更新前，数据库快照保存在 `/opt/manabi/backups/pre-deploy-时间.dump`，旧代码和配置保存在 `code-时间.tar.gz`。首次快照保存在 `initial-时间.dump`。这些备份只在服务器本机；脚本暂未安排定时备份或异地备份。部署暂存目录可能在失败后保留，可检查后清理。

不要直接把旧快照恢复到正在使用的数据库。需要回退时先停止 API、另做当前数据库备份，再将选定快照恢复到新建的空数据库并验证后切换。代码和数据库迁移必须配套；脚本不会自动执行可能丢失新记录的数据库回滚。

配置文件：`compose.yml`、`nginx.conf`、`nginx-http.conf`、`nginx-proxy.conf`；`@DOMAIN@` 在部署时替换。数据库随机密码只在服务器 `.env` 中生成，更新时保留。
