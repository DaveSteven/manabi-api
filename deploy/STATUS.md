# 部署记录

日期：2026-09-11（Asia/Tokyo）

- SSH：`ssh manabi`
- 服务根地址：`https://biblenotes.cc`
- API 文档：`https://biblenotes.cc/docs`
- 服务器目录：`/opt/manabi`
- 数据库和 API 仅内部/回环访问，Nginx 对外提供 HTTPS。
- DNS 直接指向服务器；Cloudflare 仅用于 DNS。
- 已完成首次数据导入，后续更新不要再传 `--seed-local`。
- 三个内部账号已验证公网登录；账号密码未写入部署脚本。
- 36 个等级/题型组合通过 HTTPS 验证，音频 Range 请求通过。
- 2,014 个题库资源文件的存在及字节数验证通过。
- 游客、注册和升级入口在线上禁用，未登录不能访问用户学习记录。
- 证书自动续期：`manabi-cert-renew.timer`；续期演练及 Nginx 重载钩子已验证成功。

日常更新（在 `manabi_api` 目录）：

```sh
bash deploy/deploy.sh deploy --skip-assets
```

资源有变化时去掉 `--skip-assets`。证书配置可独立运行 `bash deploy/deploy.sh tls`。App 的连接设置填写上述服务根地址。

更新前快照在服务器 `/opt/manabi/backups`；尚未配置定时数据库备份或异地备份。
