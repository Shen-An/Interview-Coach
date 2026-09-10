# Roadmap: Interview Coach 响应速度优化

## Phase 1: LLM 链路与耗时可观测性

**Goal:** 找到并降低模拟面试和独立问答的完整回答耗时，同时建立可重复的性能基线和有界 fallback。

**Requirements:** RESP-01, RESP-02, RESP-03, RESP-04, RESP-05, RESP-06, RESP-10, RESP-11, RESP-12

**Deliverables:**
- 请求阶段计时和调试信息
- 模拟面试 / 独立问答分别配置的上下文、输出和推理策略
- 首字超时、流中断、重试和备用提供商的边界处理
- fake LLM 与本地 smoke benchmark

## Phase 2: 流式渲染与语音交互体验

**Goal:** 在不牺牲流式反馈的前提下，降低前端频繁更新造成的卡顿，并让 TTS 与文本生成和下一轮输入解耦。

**Requirements:** RESP-07, RESP-08, RESP-09, RESP-10, RESP-11, RESP-12

**Deliverables:**
- 增量文本的帧级更新 / 滚动节流
- 生成、播放和失败状态提示
- TTS 取消、降级和并行预取行为验证
- 浏览器与 Electron 两种模式的回归检查

## Phase 3: Wiki 安全与规模化（已完成）

**Goal:** 在不改变检索排名的前提下，让 Wiki 浏览、来源、写入和本地 API 能安全支持超过 500 条的持续增长。

**Requirements:** WIKI-01–WIKI-12

**Deliverables:**
- 明确允许列表的 Markdown 清洗和仅 HTTP(S) 的来源边界
- loopback 同源 API 防护与不泄露密钥的设置流程
- 服务端筛选、每页 50 条分页、竞态保护和完整目录状态
- topic/platform/space 浏览字段与 artifact 级来源语义
- `RLock` 写事务、原子文件替换和内容指纹缓存失效
- Python、Node、浏览器、移动端、检索和 Electron 随机端口验证

**Result:** 2026-09-10 完成。25 个 Python 测试、6 个 Node 测试通过；395 条目录；检索保持 108/110（98.2%）。

## Completion Criteria

- 真实或 fake LLM 测试可以输出首字耗时、完整回答耗时、fallback 次数和错误原因。
- 模拟面试完整回答等待时间相对基线有明确改善，且答案长度、关键内容和 SSE 协议回归通过。
- 独立问答仍能返回完整技术解释、上下文追问和来源。
- 前端连续流式输出不出现明显滚动抖动或输入锁死。
- `python -m compileall -q backend`、`node --check frontend/app.js`、`git diff --check` 和既有 smoke test 通过。

---
*Roadmap created: 2026-09-03*
