# Manabi API

面向 iOS App 的 JLPT 专项练习服务。FastAPI + PostgreSQL，独立于旧服务运行。当前题库覆盖 N2、N3。

## 已实现

- 61 套试卷的 6,279 条题目出现记录完整导入，不再以来源题目 ID 覆盖试卷归属。
- 题型目录、材料分组、富文本清理、字幕时间段、图片与音频资源。
- 数据来源快照、内容修订、导入质量报告及待核对隔离。
- 正式账号登录、注销与等级设置；游客创建已关闭，旧游客凭证不再接受。
- 专项组题、幂等创建和提交、服务端判题、练习恢复、完成与放弃。
- 按试卷年月和专项选择题型，按原卷顺序练习，独立保存每位用户的完成进度。
- 错题复习、学习统计、分页历史和音频 Range 请求。
- Alembic 迁移、Docker 配置、OpenAPI 和 PostgreSQL 并发测试。

## 服务器部署

使用 `bash deploy/deploy.sh` 做只读检查；通过 `ssh manabi` 部署到 `biblenotes.cc` 的首次导入、更新和 HTTPS 配置见 [部署说明](deploy/README.md)。

## 本机地址

- API 根地址：`http://127.0.0.1:8001`
- Swagger：`http://127.0.0.1:8001/docs`
- OpenAPI：`http://127.0.0.1:8001/openapi.json`
- PostgreSQL：`127.0.0.1:5433`，数据库和用户均为 `manabi`，密码保存在忽略提交的 `.env`。

端口仅绑定本机。iOS 模拟器可使用上述地址；真机联调需要另外配置可访问的服务地址和开发网络设置。

## 首次安装与导入

以下命令在 `manabi_api` 目录执行，需要 Python 3.12 和 Docker。

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
python3 -c 'from pathlib import Path; import secrets; p=Path(".env"); p.exists() or p.write_text("POSTGRES_PASSWORD="+secrets.token_hex(24)+"\n"); p.chmod(0o600)'
docker compose up -d --wait db
.venv/bin/python -m scripts.export_legacy
.venv/bin/python -m scripts.local migrate
.venv/bin/python -m scripts.local import
docker compose up -d --build api
```

`scripts.export_legacy` 只读取旧服务的四张 JLPT 内容表，不读取用户、会话或作答数据。默认旧容器名 `japanese_study_db`，可通过 `--container` 指定。

默认源数据位于 `../mojitest_spider/data`。导入使用 normalized 文件；原始 JSON 保持不变。新数据库保存完整来源记录与摘要。旧数据库快照只用于比较版本，差异不会直接覆盖任一来源。

已完成本机配置时，运行 `docker compose up -d` 即可。更新代码使用 `docker compose up -d --build api`；数据库升级先运行 `scripts.local migrate`。服务启动不会自动改表或重新导入。

## 重新导入

```sh
.venv/bin/python -m scripts.local import
```

每次导入在单个事务中写入，并生成 `data/import-report.json`。出现记录 ID 稳定，内容变更生成新修订，已有练习使用快照。源数据删除的记录标为 retired，不删除历史引用。

之前对比过旧数据库时，重导入必须继续提供快照，避免绕过版本检查。默认使用 `data/legacy-jlpt-snapshot.json`，有意更新比较基线前应另存旧文件。

## 测试

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.local test -q
.venv/bin/python -m scripts.local verify
```

依次为 SQLite 内存测试、PostgreSQL 临时 schema 测试、运行中真实题库的接口验证。PostgreSQL 测试包含并发重试并自动清理临时 schema；真实验证遍历所有已发布等级和题型，清理本次创建的测试账号数据。并发保证以 PostgreSQL 为准。

## 文档

- `docs/api.md`：iOS 对接流程与约定。
- `docs/data-model.md`：模型和清洗规则。
- `docs/data-quality.md`：真实导入结果与限制。
- `docs/openapi.json`：客户端类型生成用的接口定义。
- `docs/verification.json`：运行中服务的真实数据验证结果。

## 当前范围

本版不包含支付、整卷计时考试、后台内容编辑器、账号找回或离线同步协议。账号 token 有效期 30 天，失效后需要重新登录。单进程登录限流已启用，多实例部署需共享限流，并配置 HTTPS、备份与监控。

## 内部账号管理

管理员可在接口文档登录并授权后，调用 `POST /api/v1/admin/users` 创建普通内部账号。线上公开注册仍关闭；具体操作见 [API 文档](docs/api.md#管理员创建内部账号)。初始管理员需通过服务器的 `python -m scripts.set_admin USERNAME` 安全设置，既有学习记录保留。
