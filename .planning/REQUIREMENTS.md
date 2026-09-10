# Requirements: 面试响应速度优化

## Scope

本阶段优化现有模拟面试和独立面试问答的响应链路，重点是缩短完整回答耗时，同时保留流式首字反馈、回答质量、上下文和语音体验。

## Functional Requirements

### Response pipeline

- **RESP-01**: 系统必须记录一次请求的请求开始、检索完成、LLM 请求开始、首个增量、流结束和最终完成时间，至少在开发/调试模式可见。
- **RESP-02**: 模拟面试必须继续使用 SSE 增量响应，用户不需要等待完整回答生成后才看到内容。
- **RESP-03**: 模拟面试回答必须采用独立于复盘报告的短答策略，包括合理的输出上限、上下文裁剪和推理参数；不得因为短答优化而改变复盘策略。
- **RESP-04**: 独立问答必须保留更完整的技术解释能力，同时减少不必要的上下文和输出开销。
- **RESP-05**: 备用提供商和重试策略必须有界；主通路在连接失败、首字超时、流中断和明确服务端错误时应有不同处理，不得无限等待。
- **RESP-06**: 任何已经向前端输出增量的请求不得无缝切换到另一个提供商继续生成，避免用户听到或看到两个模型接力。

### Frontend and voice

- **RESP-07**: 前端必须对流式增量进行节流或帧级批处理，避免每个 token 都触发滚动、布局和 Markdown 全量解析。
- **RESP-08**: 面试官的 TTS 必须能够在首句到达后尽早播放，但不能阻塞文本流和候选人下一轮输入。
- **RESP-09**: 用户必须能区分“请求已发送”“模型生成中”“语音播放中”“请求失败”等状态；长等待时不能只有无限 loading。

### Verification and compatibility

- **RESP-10**: 必须提供至少一套可重复的 fake LLM / smoke benchmark，用于比较优化前后的首字耗时、完整耗时、输出长度和错误场景。
- **RESP-11**: 现有 SSE 协议 `data: {"d": ...}`、`data: {"done": true, ...}`、`data: {"err": ...}` 保持兼容。
- **RESP-12**: 现有模拟面试、独立问答、复盘、情报库、简历、STT、TTS 和 Electron 打包入口不得被破坏。

## Non-Functional Requirements

- 优化必须优先减少完整回答等待，而不是单纯把内容截短到不可用。
- 本地检索缓存继续有效，不能因为增加计时而每轮重新加载知识库。
- 性能日志不得包含 API key、简历敏感内容或完整用户回答，除非用户明确开启调试导出。
- 对无模型配置、模型失败、空回答、流意外结束等现有错误行为保持友好提示。

## Out of Scope

- 更换基础模型、训练模型或引入新的付费供应商。
- 重构整个检索架构、加入向量数据库或远程缓存服务。
- 重新设计整个页面和导航系统。
- 把复盘报告改造成流式短答。

## Wiki Security and Scale Requirements

### Trust boundaries

- **WIKI-01**: QA、最新情报、复盘和历史中的 Markdown 必须经过同一个明确允许列表的 sanitizer，危险标签、事件属性和 URL 不得进入 DOM。
- **WIKI-02**: 公开来源只能是具有主机名的 HTTP(S) URL，并明确标示为 artifact 级“本批资料来源”，不得伪造成逐条引用。
- **WIKI-03**: 本地 FastAPI 只接受 loopback Host，拒绝 cross-site Fetch Metadata；存在 Origin 时必须同源，敏感读取和状态修改必须带应用 marker。
- **WIKI-04**: 设置 API 不得返回 API key 原文；空 secret 输入保留旧值，只有 `clear_secrets` 显式声明才清除。
- **WIKI-05**: 导入、联网研究和检索得到的 Wiki 内容只作为不可信证据，不得覆盖角色、泄露提示词或伪造来源。

### Catalog and metadata

- **WIKI-06**: 目录筛选和分页必须由服务端权威执行，支持超过 500 条数据；前端默认每页 50 条。
- **WIKI-07**: 目录必须区分 loading、可重试 error、合法 empty 和 ready，并阻止旧请求覆盖新查询结果。
- **WIKI-08**: 目录搜索、筛选和 facet 必须覆盖 space、topic、company 和 platform，并保留稳定可访问的控件及来源链接名称。
- **WIKI-09**: 375px 移动视口不得产生页面级横向溢出；Markdown 表格、代码、长链接和分页可在局部容器滚动或换行。

### Persistence and cache

- **WIKI-10**: Wiki 写工作流必须用实例级 `RLock` 串行化，raw、compiled、`UPDATES.md` 和 `.env` 必须同目录临时写入后原子替换。
- **WIKI-11**: raw 获取成功后必须保留；编译或 schema 校验失败不得产生半成品，也不得破坏既有目标文件。
- **WIKI-12**: 选材缓存必须包含 compiled/Wiki 内容指纹；内容变化时即使 newest/total 不变也必须失效，同时保持现有检索评分不变。

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RESP-01–RESP-06 | Phase 1 | Pending |
| RESP-07–RESP-09 | Phase 2 | Pending |
| RESP-10–RESP-12 | Phase 1–2 | Pending |
| WIKI-01–WIKI-05 | Phase 3 | Complete |
| WIKI-06–WIKI-09 | Phase 3 | Complete |
| WIKI-10–WIKI-12 | Phase 3 | Complete |

---
*Requirements defined: 2026-09-03*
