# Phase 3: 独立问答多会话管理 — Context

**Gathered:** 2026-09-03
**Status:** Ready for implementation

<domain>
## Phase Boundary

独立问答页面需要像一个轻量的本地聊天工作区：不同主题放在不同会话中，切换会话只恢复该会话的消息和上下文。这个阶段不改变模拟面试 session，也不做云端账户。
</domain>

<decisions>
## Implementation Decisions

### Persistence boundary
- 使用 `DATA_DIR / "qa-conversations"` 保存每个会话一个 JSON 文件。
- `RES_DIR` 只读资源不写用户会话，兼容浏览器和 Electron 的可写数据路径。
- 写入采用临时文件替换，损坏文件在列表时跳过，不阻塞其他会话。

### API contract
- `GET /api/qa/conversations` 返回 metadata 列表，按 `updated_at` 降序。
- `POST /api/qa/conversations` 创建空会话。
- `GET /api/qa/conversations/{id}` 返回完整消息。
- `DELETE /api/qa/conversations/{id}` 删除会话。
- `/api/qa/ask/stream` 增加可选 `conversation_id`；旧请求没有 id 时使用 `history` 并自动创建会话。
- SSE `done` 增加 `conversation_id`，不改变 `d/done/err` 的解析方式。

### Conversation lifecycle
- 创建空会话不会自动加入前端主线程，首次提问才让它成为当前会话。
- 首次用户问题生成标题，最长 42 个字符；标题不调用 LLM。
- 保存 assistant 时记录清洗后的文本和来源，但不记录 timing 作为消息正文。
- 流式错误不创建空 assistant；用户问题保留，便于重试。

### Frontend behavior
- QA 页面左侧显示会话列表，点击切换并读取完整消息。
- “新建会话”只清空当前显示并创建一个新的 id；发送第一问后标题更新。
- 删除当前会话后自动切换到最新剩余会话，无会话时回到空状态。
- 生成期间禁用切换、删除和新建，避免 holder 与会话 id 发生竞态。

### the agent's Discretion
- 列表日期的短格式和消息数量展示。
- JSON 字段的内部版本号和最大文件大小保护。
- 临时文件命名细节。
- 侧边栏在窄屏下改为横向滚动或折叠。

</decisions>

<canonical_refs>
## Canonical References

- `backend/app.py` — 现有 QA SSE 路由和 `DATA_DIR`/Electron 数据目录约定。
- `frontend/app.js` — 现有 `qaMessages`、SSE 解析、流式批量渲染状态。
- `frontend/index.html` — 现有 QA 页面结构。
- `frontend/style.css` — 现有 QA 视觉规范。
- `README.md` — 本地运行和 Electron 打包约束。
- `.planning/phases/03-qa-conversations/03-SPEC.md` — 本阶段锁定需求。

</canonical_refs>

<specifics>
## Specific Ideas

- 会话列表要让用户一眼看出“工具调用兜底”“模型幻觉”“RAG”等主题被分开保存。
- 当前会话标题优先使用第一问，不要让用户手动维护标题。
- 刷新页面后默认打开最近更新的会话，减少找回上下文的成本。
</specifics>

<deferred>
## Deferred Ideas

- 会话重命名、置顶、标签、搜索和导出。
- 会话级模型/风格设置。
- 云同步、账号与跨设备恢复。

</deferred>

---

*Phase: 03-qa-conversations*
*Context gathered: 2026-09-03*
