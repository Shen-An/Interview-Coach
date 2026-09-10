---
status: passed
verified: 2026-09-09
---

# 验证报告

## Goal-backward checks

| 目标 | 结果 | 证据 |
|---|---|---|
| 页面不再宣称整库注入 | PASS | `frontend/index.html` 统计卡和目录说明明确按相关性选取 |
| 本地日期跨午夜正确 | PASS | `tests/test_kb_ui_utils.js` 覆盖 `2026-09-08T23:30:00Z` 在东八区为 `2026-09-09` |
| Wiki 可浏览和筛选 | PASS | `GET /api/kb/items` 服务端执行关键词、kind、layer、company/platform、space、days 筛选和分页；25 个 Python、6 个 Node 测试覆盖 |
| 条目可溯源 | PASS | 仅公开带主机的 HTTP(S) URL，前端标为“本批资料来源”并使用标题或主机名作为链接名 |
| 清洗不污染事实层 | PASS | normalize 只从渲染 `_flat()` 调用；Markdown 统一通过 DOMPurify 明确允许列表；raw/compiled 不被清洗回写 |
| 写入失败不破坏旧数据 | PASS | `RLock` 串行化写事务；同目录临时文件 + `os.replace()`；测试覆盖 raw 保留、并发串行和替换失败保留旧目标 |
| 本地 API 和设置密钥有边界 | PASS | loopback/Origin/Fetch Metadata/marker 测试通过；设置响应不含密钥原文，空值保留，清除需显式选择 |
| 既有检索不回归 | PASS | `python -m pytest -q` 25 passed；Node 6 passed；`python evals/run.py` 保持 98.2%（108/110） |

## 规模与运行时验证

- 实际统一目录 395 条，默认每页 50 条，第 8 页 45 条；501 条测试数据稳定返回 11 页，不依赖前端 500 条快照。
- 浏览器验证 loading/error/retry/empty/ready、筛选分页、旧请求不覆盖新请求、严格恶意 Markdown 清洗和来源链接语义。
- 375×812 移动视口无 document/main 横向溢出；Markdown 表格、代码和分页在局部容器滚动。
- Electron 使用隔离用户目录在随机端口 59611 启动；settings marker、空密钥响应、DOMPurify 静态资源和第 8 页目录均通过。
- Python compileall、JavaScript syntax 和 `git diff --check` 通过；后者仅输出 Git 的 CRLF 转换提示。
