# Manabi iOS API 对接

API 前缀 `/api/v1`，本机根地址 `http://127.0.0.1:8001`。完整字段类型见 `openapi.json` 或在线 `/docs`。

## 账号

1. 使用内部账号调用 `POST /auth/login`，提交 `username`、`password`，获取 token。
2. token 保存在 Keychain，请求带 `Authorization: Bearer <token>`。
3. `POST /auth/logout` 撤销当前 token；`GET /me` 获取身份，`PATCH /me` 设置 `level`。
4. App 不提供注册入口；服务端 `/auth/register` 仍保留。游客创建入口已移除，旧游客 token 返回 401。

用户名忽略大小写，允许英文字母、数字、下划线、点和短横线，长度 3～64；密码长度 8～128。token 有效期 30 天，失效后须重新登录。

## 首页

- `GET /catalog/levels`：可用等级、可练题目出现次数、试卷数。
- `GET /catalog/types?level=N2`：题型 id、category、中日名称、可练题数和材料组数。
- `GET /exams?level=N2&limit=50&offset=0`：试卷来源列表。

分类值为 vocabulary、grammar、reading、listening。使用语义化题型 ID，例如 `kanji_reading`、`sentence_order`、`listening_response`，不依赖来源数字编码。

## 创建练习

`POST /practices`：

```json
{
  "level": "N2",
  "type_id": "kanji_reading",
  "count": 10,
  "mode": "normal",
  "request_key": "ios-generated-unique-request-key"
}
```

count 为目标题数，范围 1～50。为保留完整材料组，实际 total 可能大于目标；题目不足时可能小于目标，UI 应使用响应 total。组间随机、组内按原顺序，不拆组。同一修订不会在一次练习中跨组重复出现。

request_key 使用 UUID 等唯一值，网络重试复用原值。同用户同 key 返回同一练习；同 key 不同参数返回 409。开始新练习需要新 key。

响应 items 中：

- item.id：本次练习的项目 ID，用于作答。
- question.id：不可变题目修订 ID。
- question.occurrence_id：题目在试卷中的出现记录 ID。
- question.group_id：材料组 ID，同组可复用材料区域。
- question.prompt：题干富文本。
- question.material：文章及图片、音频 URL。
- question.options：选项，提交其 ID。
- question.source：试卷、等级、大题说明和位置。
- feedback：未提交时为 null，已提交时包含判题与解析。

听力和文章语法题可能没有题干，应结合大题说明和材料展示，不应判定为加载失败。

## 作答和恢复

`POST /practices/{practice_id}/items/{item_id}/answer`：

```json
{
  "option_id": "选项 UUID",
  "elapsed_ms": 12500
}
```

响应 feedback 包含正确选项、是否答对、解析、译文、字幕，答题前不返回这些解答内容。explanation_available=false 时显示“暂无解析”。字幕段字段为 start_ms、end_ms、text。

第一次提交后不可修改。重复提交同一选项返回原结果，不重复计分、计时或增加错题次数；提交其他选项返回 409。elapsed_ms 是该题有效作答时间。

- `GET /practices/{id}` 恢复完整练习，next_item_id 定位下一道未答题。
- `GET /practices?status=active` 查询未完成练习，支持分页。
- 全部题目答完自动变为 completed，无需提交整组。
- 退出页面时保留练习；仅在明确放弃时调用 `POST /practices/{id}/abandon`。

练习保存内容快照，重新导入不会改变已创建练习的题目和解析。

## 错题和统计

- `GET /wrong-questions?level=N2&type_id=kanji_reading` 返回未掌握错题，支持 limit、offset。
- resolved=true 可查看之后已答对的错题。
- 创建练习使用 mode=wrong，抽取含未掌握错题的完整材料组，组内可能包含之前答对的题。
- 答错累加次数，之后答对标记 resolved，再次答错重新进入未掌握列表。
- available=false 表示更新后暂不能抽取该题，历史仍保留。
- `GET /me/stats` 按等级、题型汇总作答次数、正确次数、正确率和耗时，包含未完成及放弃练习中已提交的答案。

## 内容、媒体和错误

富文本统一为 `{"text":"纯文本","html":"清理后的 HTML"}`。HTML 保留段落、下划线、加粗、ruby 注音、表格等，移除来源样式和可执行属性。日文全角空格不全局压缩。

媒体 URL 是相对 API 根地址的路径，例如 `/api/v1/assets/<id>`，不要重复拼接 /api/v1。音频支持 Range，便于 AVPlayer 定位。

时间为带 Z 的 UTC ISO 8601 字符串。耗时、字幕以毫秒计；item 和 option 的 position 从 0 开始，source position 从 1 开始。

错误格式为 `{"detail": ...}`：401 身份失效；404 资源不存在、不可访问或无可练题；409 请求冲突或状态不允许；422 参数无效；429 请求过多，遵守 Retry-After。不要依赖英文错误文本作逻辑判断。

## 精听

`GET /practices/{practice_id}/items/{item_id}/listening`：需登录且练习属于当前用户，返回 `audio_url` 和 `segments`（`start_ms`、`end_ms`、`text`）。这是用户主动进入精听时获取的原文，不需要先提交答案，也不会改变答题状态；不返回正确选项或解析。无音频返回 404，无有效时间标记返回空数组。旧练习使用自己的内容快照。

## 按试卷练习

以下接口均需登录；路径前缀为 `/api/v1`。

- `GET /exam-practice/exams?level=N2&category=listening`：按年月倒序列出该专项的可练试卷，以及当前用户的 total、answered、correct、status。category 可选 vocabulary、grammar、reading、listening。
- `GET /exam-practice/exams/{exam_id}/types?category=listening`：按题型顺序返回题型名称、题数、已答/答对数、状态和 practice_id。状态为 not_started、active 或 completed（明确放弃的历史会话可能为 abandoned）。
- `POST /exam-practice/exams/{exam_id}/types/{type_id}/practice`：首次进入创建 mode=exam 的练习，包含该卷该题型全部可练题，按原卷顺序排列；重复进入返回同一个练习并恢复 next_item_id，已完成则可回顾。无需请求体或客户端 request_key。

提交答案、查看解析和精听复用已有练习接口。每个用户的试卷进度独立保存；随机专项练习不改变此模块的进度。总学习统计仍计入所有模式的作答。进度以已提交答案为准，退出或重启后保留。创建后使用内容快照，不随题库更新改变已开始的题目。

## 管理员创建内部账号

公开注册保持关闭。管理员在 `/docs` 中使用：

1. 展开 `POST /api/v1/auth/login`，点击 **Try it out**，填写管理员用户名、密码后执行。
2. 复制返回的 `access_token`（不含引号）。点击页面右上角 **Authorize**，粘贴 token 后授权，无需加 `Bearer ` 前缀。
3. 展开 **Admin → POST /api/v1/admin/users**，填写 `username`、`password` 和 `level`（N2 或 N3，默认 N3），执行后返回 201 即创建成功。

用户名为 3–64 位英文字母、数字、下划线、点或短横线，不区分大小写；密码为 8–128 位。返回信息不含密码或新用户登录 token。创建的账号均为普通账号，不能通过请求增加管理员权限。未登录返回 401，普通账号返回 403，用户名重复返回 409。新账号可直接在 App 登录。

管理员资格由服务器维护，不能通过公开注册或修改个人资料取得。服务器管理员可运行 `python -m scripts.set_admin USERNAME`，按隐藏提示输入新密码；该操作保留练习记录，同时撤销该账号旧 token。密码不得放入源码、文档或命令行参数。
