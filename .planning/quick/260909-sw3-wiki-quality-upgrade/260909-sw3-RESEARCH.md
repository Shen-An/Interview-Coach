---
status: complete
---

# 研究摘要

## 现状

- `backend/retrieval.py::load()` 已把 `kb/compiled/*.json` 与 Markdown 题库装载为统一 `store["items"]`，条目已经包含 `space/kind/layer/day/line/company/freq/source/source_urls` 等字段。
- `backend/kb.py::KBManager.state()` 已提供 raw、compiled、schema 计数以及按产物的 sections/counts，但前端只显示顶层 `.md` 文件与最新情报。
- `backend/app.py` 已有 `/api/kb`、`/api/kb/latest`、刷新、导入、重编译接口，新增条目接口可直接调用 retrieval.load。
- 前端无构建步骤，`frontend/index.html` 直接加载 `app.js`，适合增加小型纯函数模块并用 Node 原生测试。

## 方案判断

- API 返回展示所需字段的 JSON 副本，不返回 `terms/head/topic_terms/related` 等内部检索细节，避免泄露实现并降低响应体。
- API 在后端做分页与过滤，前端仍保留本地过滤函数用于交互/测试；默认按日期、空间、种类排序。
- 日期使用 `new Date(year, month - 1, day)`，不使用 `toISOString()`，避免北京时间凌晨跨 UTC 日造成误判。
- normalize 仅在 `render_body()` 的 `_flat()` 输出路径生效；JSON 编译产物仍保存模型原始结构，raw 文件完全不动。
