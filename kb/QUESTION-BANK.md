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

### 模型底层
- 🔥 Transformer 核心结构，Q/K/V 为什么要分三个向量？Attention 怎么算？为什么除以 √d_k？
- 同一个 Token 在不同位置的向量一样吗？GQA 比 MHA 省多少 KV-Cache？
- Token 怎么切分（BPE）？为什么不直接用字符或单词？中英文/代码消耗为什么不同？
- 上下文窗口由什么决定？是不是越大越好？Lost in the Middle 怎么产生、怎么解？
- 支持更长上下文需要怎样的训练？为什么不直接把窗口做大？
- KV Cache 的作用？为什么 Agent 场景更敏感？PagedAttention / Continuous Batching / vLLM vs SGLang？
- 幻觉是怎么产生的？有哪些缓解方法？
- 大模型的"涌现能力"是什么？CoT 什么条件下才涌现？

### 训练方法
- 🔥 SFT / PPO / DPO / GRPO 分别什么特点？
- PPO 为什么既有 reward model 又有 critic model？
- DPO 为什么不需要在线采样？数据格式？损失函数怎么写？
- GRPO 训练出现全 0 全 1 怎么办？GSPO/DAPO 与 GRPO 区别？
- 为什么有了 SFT 还要 RLHF？RLHF 三阶段的 loss 各怎么定义？
- Agent 训练三阶段 CPT→SFT→RL：🔥 为什么 SFT 时要 mask observation tokens？（字节经典追问）
- LoRA / QLoRA 核心思想？LoRA 超越"减参数"的 4 个优点？矩阵初始化方式？
- Function Call 能力用 GRPO 提升，奖励函数怎么设计？过程奖励怎么加？

### 协议与生态四件套
- 🔥 Function Call 是什么？底层怎么实现？四步流程？Parallel Function Call？
- 🔥 MCP 是什么协议？解决什么问题？和 Function Calling 的本质区别（"三大绝症"）？能共存吗？
- MCP 三种原语 Resources/Tools/Prompts？Resource 和 Tool 什么时候用哪个？
- MCP stdio vs Streamable HTTP？JSON-RPC 怎么工作？notifications 机制？
- 🔥 MCP 2026-07-28 为什么要无状态化？旧 session 协议有什么问题？迁移要改什么？
- Mcp-Method/Mcp-Name HTTP 头解决了什么问题？
- MCP Token 税是什么？你用 MCP 遇到过什么问题、怎么解决？
- 🔥 A2A 和 MCP 的区别？为什么 MCP 解决不了 A2A 的问题？Agent Card 是什么？A2A 三种通信模式、任务状态机？
- MCP / A2A / AG-UI 三协议怎么分类？
- 🔥 Skill、MCP、Tools、Function Calling 四者关系？（2026 标准四件套题）
- 🔥 Skills vs Tool 的 5 个本质区别（8 月最高频）；Skill 是知识库还是融合在 Agent 里？什么阶段 fetch？
- Skills 和 System Prompt / Prompt / Few-shot 的区别？为什么说"Skill 不是更长的 Prompt"？
- 🔥 Rules 和 Skills 的本质区别？为什么 Skill 不能写进 Rules？Instructions+Rules+MCP+Skills 四件套怎么区分？
- 渐进式披露（Progressive Disclosure）是什么？和 RAG 是什么关系？怎么实现？
- SSE vs WebSocket 底层区别？为什么 Agent 用 SSE？
- RPC vs HTTP 本质区别？Agent 通信到底走哪个？

---
