# Phase 1: LLM 链路与耗时可观测性 - Context

**Gathered:** 2026-09-03
**Status:** Ready for research and planning

<domain>
## Phase Boundary

为模拟面试和独立面试问答建立响应耗时基线，并优化 LLM 请求、上下文、输出上限、推理参数和 fallback 边界，以缩短完整回答等待时间。前端渲染节流和 TTS 解耦属于 Phase 2，但 Phase 1 必须保留现有 SSE 协议并为它们提供可观测数据。
</domain>

<decisions>
## Implementation Decisions

### Scope priority
- **D-01:** 同时覆盖模拟面试和独立问答，共用基础链路优化，但模拟面试优先。
- **D-02:** 复盘报告不纳入短答参数调整，继续保持独立的长文本质量策略。

### Quality and speed tradeoff
- **D-03:** 不默认更换模型、不直接关闭所有推理；优先优化现有模型的请求链路、上下文大小、输出上限和失败边界。
- **D-04:** 可以在不改变用户可见回答质量的前提下使用场景化参数：模拟面试短答与独立问答技术解释允许不同配置。

### Success emphasis
- **D-05:** 主要目标是缩短从发送问题到完整回答结束的时间。
- **D-06:** 首字 / 首段尽早显示仍然是必须保留的辅助体验，但不能以明显截短答案或损失关键内容为代价。

### Agent discretion
- 具体超时阈值、上下文裁剪长度、输出上限和调试日志字段由研究与基准结果决定。
- 如果某个 provider 不支持参数，应采用已有兼容降级模式，而不是让请求失败。
- 只有在 fake LLM、smoke test 和人工回答质量对比都通过后，才接受参数变化。
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product and requirements
- `E:\Coding\Code\Python\interview-coach\.planning\PROJECT.md` — 项目目标、约束与已锁定决策
- `E:\Coding\Code\Python\interview-coach\.planning\REQUIREMENTS.md` — RESP-01 至 RESP-12 的范围和验收要求
- `E:\Coding\Code\Python\interview-coach\.planning\ROADMAP.md` — Phase 1 / Phase 2 边界

### Existing implementation
- `E:\Coding\Code\Python\interview-coach\backend\app.py` — 模拟面试和独立问答 SSE 路由、计时插入点
- `E:\Coding\Code\Python\interview-coach\backend\llm.py` — provider、stream、fast、cache、timeout 和 fallback
- `E:\Coding\Code\Python\interview-coach\backend\retrieval.py` — 本地知识库加载缓存和问题检索
- `E:\Coding\Code\Python\interview-coach\frontend\app.js` — SSE 读取、增量追加、滚动、TTS 分句和预取
- `E:\Coding\Code\Python\interview-coach\README.md` — 用户操作、配置和现有能力说明

No external specs — requirements are captured in this context and the referenced source files.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app.py` 的 `turn_stream` 和 `qa_ask_stream` 已提供统一 SSE 事件结构，可插入阶段计时而不改变当前协议。
- `backend/llm.py` 的 `chat_stream` 已实现“首个增量前允许轮换、吐字后不换 provider”的安全边界，可在此增加首字计时和错误分类。
- `backend/retrieval.py` 的 `_store_cache` 已避免每轮重复构建知识库，继续复用即可。
- `frontend/app.js` 的 `queueSentences` / `enqueueSpeak` 已实现首句 TTS 和云端预取，Phase 2 应在其上做解耦而不是重写。

### Established Patterns
- SSE 使用 `data: JSON\n\n`，事件包括 `d`、`done`、`err`。
- 模拟面试使用 `fast=True`、约 1200 输出上限和多轮缓存；独立问答使用更长输出、完整上下文回答。
- Electron 无法依赖浏览器 Web Speech，因此已有云端 STT/TTS 与本地语音降级逻辑。
- 前端无构建步骤，修改后使用 Node 语法检查和浏览器 smoke test。

### Integration Points
- Phase 1 主要修改 `backend/app.py` 和 `backend/llm.py`，必要时增加测试或调试接口。
- Phase 2 修改 `frontend/app.js`、`frontend/style.css`，不得破坏 `frontend/index.html` 现有路由和 SSE 绑定。
- 需要覆盖浏览器启动和 Electron 打包后静态资源 / 后端进程的兼容性。
</code_context>

<specifics>
## Specific Ideas

- 用户选择 `1C，2A，3B`：两条问答链路都优化但模拟面试优先；不更换模型，优先链路参数；以完整回答耗时为主目标。
</specifics>

<deferred>
## Deferred Ideas

- 模型供应商或模型档位的产品化切换 — 后续独立阶段
- 向量数据库和远程检索服务 — 当前基准显示不是主要瓶颈
- 全面 UI 重设计 — 不属于响应速度阶段
</deferred>

---

*Phase: 1-LLM 链路与耗时可观测性*
*Context gathered: 2026-09-03*
