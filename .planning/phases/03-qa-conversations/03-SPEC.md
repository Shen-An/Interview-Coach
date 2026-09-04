# Phase 3: 独立问答多会话管理 — Specification

**Created:** 2026-09-03
**Ambiguity score:** 0.08 (auto-selected from the user's explicit requirement)
**Requirements:** 7 locked

## Goal

把独立面试问答从单条前端临时历史升级为可持久化的多会话工作区：用户可以创建、切换、删除多个互不串上下文的问答会话，刷新浏览器或重启 Electron 后仍能恢复。

## Background

当前 `/api/qa/ask/stream` 每次接收前端传来的 `history`，前端只在内存中维护一个 `qaMessages` 数组。用户无法区分不同主题的问答，也无法在刷新后恢复历史；继续追问始终落在同一条临时线程里。

## Requirements

1. **会话持久化**: 独立问答必须将会话元数据和消息保存到用户数据目录，而不是资源目录或仅浏览器内存。
   - Current: `qaMessages` 只存在前端内存。
   - Target: 每个会话拥有稳定 id、标题、创建时间、更新时间和消息列表；服务重启后可读取。
   - Acceptance: 通过 API 创建并写入会话后，重新加载列表仍能找到同一 id 和消息。

2. **会话隔离**: 模型上下文必须只使用当前会话的消息，不得把其他会话的内容混入。
   - Current: 全局只有一个历史数组。
   - Target: `conversation_id` 绑定一次问答；后端从该会话加载最近上下文，旧 `history` 参数仅作为无 id 调用的兼容回退。
   - Acceptance: 在会话 A 和 B 中分别提问，B 的请求上下文不包含 A 的问题或回答。

3. **会话管理 API**: 提供列表、创建、读取和删除能力；保留原有 SSE ask 接口兼容。
   - Current: 只有问答流接口。
   - Target: `GET/POST /api/qa/conversations`、`GET/DELETE /api/qa/conversations/{id}`，ask 请求可选 `conversation_id`，done 事件返回该 id。
   - Acceptance: CRUD smoke test 全部返回预期状态，旧的只传 `question/history` 请求仍可工作。

4. **界面会话切换**: QA 页面必须显示会话列表、当前会话、创建新会话和删除会话入口。
   - Current: 页面只有单一问答记录。
   - Target: 左侧会话列表按最近更新时间排序，点击后加载对应消息；新建会话清空当前线程但不删除其他会话。
   - Acceptance: 浏览器操作 A→新建→B→切回 A 后，A/B 的消息分别恢复且显示正确。

5. **标题与空状态**: 新会话可以无消息存在；首次提问后自动生成可读标题，空会话不会出现在脏数据列表中。
   - Current: 没有会话标题和空会话概念。
   - Target: 默认标题为“新建问答”，首次用户问题截断生成标题；列表显示更新时间和消息数。
   - Acceptance: 首次提问后列表标题更新；创建后未提问的会话可删除且不会污染主列表。

6. **流式保存边界**: 流式回答过程中不能写入半截 assistant 消息；成功完成才保存回答，失败时保留用户问题并显示错误。
   - Current: 前端流结束后才有内存消息，没有服务端持久化边界。
   - Target: 用户问题先落盘，assistant 仅在 `done` 前完成清洗后落盘；错误不生成空回答。
   - Acceptance: fake LLM 中断后重新读取会话只看到用户问题；成功流重新读取能看到完整回答和来源。

7. **单用户本地兼容**: 方案必须兼容浏览器与 Electron，不引入账号系统、远程数据库或新运行时依赖。
   - Current: 本地单用户 FastAPI + Electron。
   - Target: 数据写入 `IC_DATA_DIR` 下的独立 QA 会话目录，Electron 资源保持只读。
   - Acceptance: Python 编译、Electron 资源路径检查和现有面试/复盘入口均通过。

## Boundaries

**In scope:**
- 本地 JSON 会话存储与 CRUD API。
- QA SSE 请求按会话读取和保存上下文。
- QA 页面会话列表、切换、新建、删除、空状态和加载状态。
- 旧 QA 请求格式兼容。

**Out of scope:**
- 多用户登录、云同步和跨设备同步 — 当前产品是本地单用户工具。
- 会话搜索、标签、置顶、归档和导出 — 先解决隔离与恢复。
- 模拟面试 session 与复盘记录的迁移 — 两者继续使用现有生命周期。
- 改变 LLM 模型、SSE 增量协议或知识库检索算法 — 本阶段只接入会话边界。

## Constraints

- 不把用户回答、简历或 API key 写入日志。
- 会话文件必须位于可写 `DATA_DIR`，不能写入打包后的 `RES_DIR`。
- 前端仍使用现有无构建 Vue 3 SPA，SSE 仍使用 `d/done/err` 事件；允许在事件 payload 中增加 `conversation_id`。
- 单次模型请求最多发送当前会话最近 8 条有效消息，避免历史无限增长。

## Acceptance Criteria

- [ ] 会话 CRUD API 可创建、列出、读取、删除会话。
- [ ] 两个会话的 ask 请求不会互相污染上下文。
- [ ] QA 页面可新建、切换、删除会话，刷新后仍恢复列表与消息。
- [ ] 首次提问自动生成标题，列表按 `updated_at` 降序。
- [ ] 成功回答保存完整 assistant 消息及来源；失败不保存空 assistant 消息。
- [ ] 旧 `/api/qa/ask/stream` 请求格式继续可用。
- [ ] `compileall`、`node --check`、`git diff --check` 与 fake SSE/CRUD smoke test 通过。

## Ambiguity Report

| Dimension           | Score | Min  | Status | Notes |
|---------------------|-------|------|--------|-------|
| Goal Clarity        | 0.95  | 0.75 | ✓     | 用户明确要求按不同会话组织 QA |
| Boundary Clarity    | 0.95  | 0.70 | ✓     | 本地单用户，不做云同步和账号 |
| Constraint Clarity  | 0.90  | 0.65 | ✓     | 复用 FastAPI/Electron/JSON/SSE |
| Acceptance Criteria | 0.90  | 0.70 | ✓     | CRUD、隔离、刷新恢复和失败边界可验证 |
| **Ambiguity**       | **0.05** | ≤0.20 | **✓** | 自动选择最小且可恢复的本地持久化方案 |

## Interview Log

| Round | Perspective | Question summary | Decision locked |
|-------|-------------|------------------|-----------------|
| 1 | Researcher | 当前 QA 是否已有后端 session？ | 没有；现在只有前端内存 history |
| 2 | Simplifier | 最小解决方案是什么？ | 本地 JSON 多会话 + 列表/切换/新建/删除 |
| 3 | Boundary Keeper | 是否引入登录、云同步或数据库？ | 不引入，保持本地单用户和现有依赖 |
| 4 | Failure Analyst | 流中断如何保存？ | 先保存用户问题，成功后才保存 assistant，避免半截回答 |
| 5 | Seed Closer | 如何兼容旧调用？ | `history` 保留，`conversation_id` 可选；无 id 自动创建 |

---

*Phase: 03-qa-conversations*
*Spec created: 2026-09-03*
