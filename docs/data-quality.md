# 首次 JLPT 导入质量报告

数据集：N2/N3，共 61 套试卷、6,279 条出现记录、6,269 个不同来源题目 ID。

可练：6,202 条；待核对：77 条。保存了 2,430 份不同材料内容，2,014 个媒体资源引用。

| 等级 | 状态 | 出现记录数 |
|---|---|---:|
| N2 | ready | 3257 |
| N2 | review | 77 |
| N3 | ready | 2945 |

## 问题统计

| 问题代码 | 次数 |
|---|---:|
| type_conflict | 48 |
| legacy_version_difference | 39 |
| missing_explanation | 443 |
| invalid_subtitle_segments | 10 |
| type_alias | 44 |
| reused_source_id | 10 |
| group_contains_review_item | 1 |

问题次数可能重叠，不能直接相加作为待核对题数。48 条语义题型冲突、39 条旧数据库版本差异等经整组隔离后，共 77 条暂不发布。

44 条 type_alias 是 N3 的来源 13/14 语境选词编码别名，经过显式映射可使用。10 个重复来源 ID 的全部出现记录均保留，没有覆盖等级或试卷归属。

443 条缺少解析的记录保留可判题能力，API 提供 explanation_available。10 条记录存在无效字幕时间段，已保留有效片段并记录警告，原文可追溯。没有发现缺失本地媒体或不合法正确选项的记录。

这些是结构和一致性检查结果，不代表对全部日语内容、答案及音频做了人工校验。未猜测或自动重写有争议的答案和解析。

## 复核材料

- 逐项报告：`../data/import-report.json`，包括 occurrence ID、问题类别、差异字段。
- 旧库只读快照：`../data/legacy-jlpt-snapshot.json`，不含用户与作答记录。
- 每条原始 normalized 记录保存在数据库 occurrences.source.record。
- 输入文件摘要见本报告下方，完整导入运行保存在 import_runs 和 quality_issues 中。

## 输入摘要

```json
{
  "normalized/N2/exams_with_assets.json": "8cb7380850c5adf5beacf196362e4a485e028c8140cacf3c56910a7b6aeb6939",
  "normalized/N2/questions_with_assets.json": "b70b1f09933a0a65b5f1f81d3096dc96ac76d53c41a50544fba38229e22c7e2e",
  "normalized/N3/exams_with_assets.json": "f7727ef53cd790f336ecfe6f9e16de17a8c317703d447b767e0d7262632d5518",
  "normalized/N3/questions_with_assets.json": "fd26bd463b72adc1886c0060765fe2aa95268033ac4b5f5636e02f070c9d5cfa"
}
```
