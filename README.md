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

### 试卷资源清单（媒体缓存准备）

`GET /api/v1/exam-practice/exams/{exam_id}/resources` 需要登录。
省略筛选返回整卷；可选 `category`（vocabulary/grammar/reading/listening）和
`type_id`（题型 ID），同时提供时取交集，题型与分类不匹配返回 422。
仅收录已发布试卷中 ready 题目的音频、配图；没有资源返回空列表。
读取清单不会创建练习或修改进度。

返回 `exam_id`、`items`、`resource_count`、`total_bytes`。每项包含
`id`、`kind`、`url`、`mime_type`、`byte_size`、`sha256`。
按资源 ID 去重，排序固定；`total_bytes` 为去重后总字节数，App 应再扣除
本地已有且哈希相同的文件。不同资源 ID 即使文件内容相同仍分别计数。
`sha256` 同时用作内容版本和下载校验；下载地址为相对路径，附带 `?v=<sha256>`。
版本过期的下载返回 409，客户端应刷新清单；原有不带版本的媒体地址保持兼容。
清单不包含答案、字幕或用户进度，不代表支持完整离线练习。

上线/本地准备顺序：

1. 执行 `python -m alembic upgrade head`。
2. 在资源所在环境执行 `python -m scripts.hash_assets`（可用 `--assets-dir PATH`）。
3. 启用新接口并检查资源清单。历史资源哈希尚未补齐时，相关清单返回 503，不能误标为下载完成。

本地 Docker 数据库可使用 `python -m scripts.local migrate` 和
`python -m scripts.local hash-assets`。哈希脚本可重复运行，所有元数据统一提交，
无效文件导致本次事务回滚。后续导入会计算哈希，每个资源只计算一次。
禁止直接替换线上文件而不更新元数据；替换时需通过导入或维护窗口重新运行哈希脚本。
下载完成后客户端仍须校验 SHA-256，以识别传输损坏或更新期间的文件变化。
