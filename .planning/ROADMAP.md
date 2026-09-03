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

## Completion Criteria

- 真实或 fake LLM 测试可以输出首字耗时、完整回答耗时、fallback 次数和错误原因。
- 模拟面试完整回答等待时间相对基线有明确改善，且答案长度、关键内容和 SSE 协议回归通过。
- 独立问答仍能返回完整技术解释、上下文追问和来源。
- 前端连续流式输出不出现明显滚动抖动或输入锁死。
- `python -m compileall -q backend`、`node --check frontend/app.js`、`git diff --check` 和既有 smoke test 通过。

---
*Roadmap created: 2026-09-03*
