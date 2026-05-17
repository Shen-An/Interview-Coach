# 面试官题库 v2（全量版）

> 覆盖 2026-05 ~ 2026-08 共 47 份面经文档、1250+ 题、1696 条去重问句、E17–E135 题号库、43 道手撕题。
> 按「考点 3 层次」（E84 框架）组织。标 🔥 为多厂命中高频题。

---

## 第 1 层：概念与架构认知（入场券）

### Agent 基础
- 🔥 Agent 和 LLM / 普通 API 调用 / Chatbot 的本质区别？ChatBot 加上插件算 Agent 吗？网页版对话助手算 Agent 吗？RAG+Chat 算 Agent 吗？
- 🔥 Agent 和 Workflow 的区别？什么时候用 Workflow 就够了？如何判断一个场景用 Agent 还是 Workflow？
- Tools / Workflow / Agent 三层次区别（阿里必考）
- Agent = Model + Harness 这个等式怎么理解？Harness 六层组件各解决什么问题？
- Agent 的工作模式有哪些？四种模式怎么选？
- Agentic Loop 是什么？画出流程图。上下文治理怎么做？
- 🔥 ReAct 与 CoT 的区别？ReAct / Plan-and-Execute / Reflexion 三者区别和适用场景？
- ToT 和 CoT 的本质区别？什么时候 CoT 反而降低性能？BFS/DFS 搜索策略怎么选？
- 反思（Reflection）和 ReAct 循环有什么区别？反思结果会不会污染上下文？失败如何兜底？
