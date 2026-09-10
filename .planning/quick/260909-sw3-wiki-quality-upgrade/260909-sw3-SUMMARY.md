---
status: complete
completed: 2026-09-09
---

# Wiki 质量升级总结

## 已完成

### P0
- 修正前端“总字数 / 全部随开场提示词喂给面试官”的错误口径，改为明确说明按简历、轮次和风格检索，不整库注入。
- 抽出 `frontend/kb-ui-utils.js`，用浏览器本地日历日期判断更新状态，修复北京时间凌晨跨 UTC 日误判。

### P1
- 新增 `GET /api/kb/items`，复用统一检索条目池，支持关键词、kind、layer、company、space、days 和分页。
- 返回公开的题面、空间、类型、层次、日期、来源、频率、公司、原文 URL 等字段，隐藏检索内部字段。
- 情报库前端新增 raw/compiled/schema/分类统计，条目浏览、关键词搜索、类型/层次/公司/时间筛选和来源链接。

### P2
- 新增保守的 `normalize_rendered_text()`，仅通过 `_flat()` 作用于渲染文本。
- 修复缺失数字范围分隔符、清理展示标点空格，并避免空背景/空考察字段产生噪音。
- 明确保证 raw 原文和 compiled JSON 不被 normalize 回写。

## 修改文件

- `E:\Coding\Code\Python\interview-coach\backend\app.py`
- `E:\Coding\Code\Python\interview-coach\backend\kb.py`
- `E:\Coding\Code\Python\interview-coach\backend\retrieval.py`
- `E:\Coding\Code\Python\interview-coach\frontend\index.html`
- `E:\Coding\Code\Python\interview-coach\frontend\app.js`
- `E:\Coding\Code\Python\interview-coach\frontend\style.css`
- `E:\Coding\Code\Python\interview-coach\frontend\kb-ui-utils.js`
- `E:\Coding\Code\Python\interview-coach\README.md`
- `E:\Coding\Code\Python\interview-coach\tests\test_kb_catalog.py`
- `E:\Coding\Code\Python\interview-coach\tests\test_kb_render.py`
- `E:\Coding\Code\Python\interview-coach\tests\test_kb_ui_utils.js`

## 验证

- `python -m pytest -q`: 11 passed
- `node --test tests/test_kb_ui_utils.js`: 3 passed
- `node --check frontend/app.js`: passed
- `node --check frontend/kb-ui-utils.js`: passed
- `python -m py_compile backend/kb.py backend/retrieval.py backend/app.py`: passed
- `git diff --check`: passed
- 真实 API smoke：`GET /api/kb/items?page_size=3&kind=questions` 返回 200，返回 3 条，题目总数 245；全库目录 395 条。

## Git 提交

- `9ea8f81 feat: upgrade wiki browsing and rendering`

## 后续安全与规模化加固（2026-09-10，未提交）

在 `9ea8f81` 的浏览能力上继续完成：

- 所有 Markdown 统一经过 DOMPurify 3.4.15 明确允许列表处理，移除脚本、事件属性、图片、SVG、iframe、style 和危险链接。
- 本地 API 增加 loopback Host、同源 Origin、Fetch Metadata 和自定义请求头边界；设置接口不再返回 API key 原文，空值保留旧 key，清除必须显式选择。
- 目录改为服务端筛选和分页（默认 50 条），增加 space/topic/platform、请求竞态保护，以及 loading/error/retry/empty/ready 状态。
- 来源 URL 只公开带主机的 HTTP(S) 链接，并以“本批资料来源”明确其 artifact 级范围。
- Wiki 写事务通过 `RLock` 串行化，raw、compiled、`UPDATES.md` 和 `.env` 使用同目录临时文件加 `os.replace()` 原子替换；编译失败仍保留 raw。
- 检索 store 暴露内容指纹，选材缓存随实际文件内容变化失效；导入和检索资料统一视为不可信证据而非提示词指令。

## 最终验证（2026-09-10）

- `python -m pytest -q`: 25 passed
- `node --test tests/test_kb_ui_utils.js`: 6 passed
- Python compileall、JavaScript syntax、`git diff --check`: passed（仅 Git 的 CRLF 提示）
- 统一目录：395 条；服务端分页第 1 页 50 条，第 8 页 45 条；501 条测试数据稳定分为 11 页
- `python evals/run.py`: 108/110（98.2%），平均注入 9732 字，密度 0.55 项/千字；未调整排名权重
- 浏览器验证：筛选、分页、竞态、错误重试、合法空结果、严格 Markdown 清洗、artifact 来源链接和显式清除 key 流程通过
- 375×812 移动视口：document/main/stat strip 无横向溢出，分页仅在自身容器内滚动
- Electron 随机端口 59611 smoke：sanitizer 静态资源 200；无 marker 的 settings 403、有 marker 200 且 secrets 全空；目录第 8 页 45/395

当前加固改动保持未提交；未触碰 PPT 脚本、截图、检查 JSON 或渲染目录。

## 质量备注

Luna 子智能体曾尝试并行分析 P0/P1/P2，但运行时连续返回 429，未产生可用结果；本次未依赖其未完成输出，主流程完成了同等的检查、实现与验证。
