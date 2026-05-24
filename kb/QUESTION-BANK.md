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

## 第 2 层：设计与决策能力（拉开分差）

### 记忆与上下文
- 🔥 Agent Memory 怎么设计？工作/短期/长期/实体记忆分别怎么存、怎么落地？
- 🔥 记忆的滚动更新、摘要压缩、结构化压缩怎么做？多重上下文压缩机制？（蚂蚁网商）
- 🔥 会话很长 Prompt 越来越大怎么处理？除截断外的压缩方法？压缩过度导致效果下降怎么发现？
- 记忆为什么用向量库存储而不是每轮拼进 prompt？记忆和 RAG 知识库共不共用？
- 记忆检索怎么平衡相关性+时近性？注入多少记忆合适？用户反复说同一件事，重复存储还是语义合并？
- 长期记忆怎么避免"记忆污染"？Memory 冷启动问题？
- Context Engineering vs Prompt Engineering vs Harness Engineering 三者关系？
- 上下文腐化（Context Rot）/ 上下文漂移是什么？根因？怎么识别和解决？
- Auto-Compact 在压什么、留什么、丢什么？RAG 能不能替代 Auto-Compact？
- Claude Code 底层记忆原理？CLAUDE.md 为什么作为用户消息注入而不是 System Prompt？
- 为什么 Claude Code 不用 RAG 检索代码而用 grep？什么时候该用 RAG 什么时候该用 Grep？
- To-Do List 机制为什么能让模型更聚焦？怎么落地？

### 工具调用设计
- 🔥 Tool schema 怎么设计？描述为什么要写 What+When+How+Limit？annotations（destructiveHint/readOnlyHint）怎么用？
- 🔥 工具太多时怎么管理？百级工具路由怎么设计？工具选择错误怎么优化？
- 多工具并行调用怎么实现？依赖关系（DAG）怎么处理？
- 工具描述怎么优化才能提升调用准确率？
- 两个工具对同一问题返回格式不统一怎么处理？MCP 工具返回格式不统一怎么办？
- 🔥 大模型输出格式不稳定，工程上怎么约束？约束解码 / JSON Mode / Grammar-based 解码区别？
- Tool 直接暴露给模型还是服务端分发？
- 采用 SFT 或 RL 怎么解决工具调用不准确？
- 什么是工具调用幻觉？类型及解法？

### RAG 设计
- 🔥 RAG 完整链路：从用户提问到答案返回？每个环节为什么这么做？
- 🔥 Chunk 策略怎么设计？大小、重叠率怎么定？不同文档类型（PDF/表格/条款/代码）怎么切？
- 法律文档"第三条第二款"和"第三条之二"会不会切散？
- 小 chunk 检索准但上下文碎，矛盾怎么解决？
- 🔥 检索优化：向量/关键词/混合检索怎么配合？BM25 和向量分数不在一个量纲怎么融合？
- 🔥 Rerank 方案有哪些？为什么初筛后还要 Rerank？TopK 截断值怎么定、验证过吗？
- Query 改写 / HyDE / multi-query 是一回事吗？改写缺信息时怎么让用户补充？
- 🔥 Agentic RAG vs 传统 RAG 核心区别？成本和稳定性怎么控制？
- GraphRAG vs LightRAG vs 传统 RAG？什么场景升级？实体提取不准怎么办？
- RAG 四大新范式（Graph-RAG / Agentic RAG / Memory-Augmented / Retrieval-free）？
- 向量库 vs 传统数据库怎么分工？索引类型 Flat/IVF_PQ/HNSW/DiskANN 选型？IVF_PQ 参数怎么选？
- 余弦相似度 vs 欧氏距离优缺点？工程上怎么存储计算？稠密/稀疏向量混合融合？
- 文档更新后怎么避免全量重建？增量索引怎么设计、有什么坑？embedding 模型升级了怎么办？
- 多模态数据（图片/表格/代码块）怎么处理？
- Prompt 明确要求不返回某商品但模型仍返回且多次出现——原因和解法？
- 为什么先调 Tool 查商品再走 RAG 检索？（小红书原题）
- 多轮对话中省略/指代怎么补全成可检索的问题？

### 架构选型
- 🔥 单 Agent 还是多 Agent？判据？多 Agent 的代价？什么情况不该用 Multi-Agent？
- 🔥 多 Agent 为什么需要中心化编排？Supervisor / Swarm / Hierarchical 三种架构怎么选？
- Multi-Agent 三层架构（Router→Manager→Sub-Agent）？主子 Agent 通信链路？
- 为什么拆多个 Agent？一个 Agent 多挂几个 Tool 不行吗？子 Agent 能不能共享所有工具？
- 子 Agent 为什么能减少上下文污染？子 Agent 上下文和父 Agent 什么关系？
- 🔥 框架自研还是 LangChain/LangGraph？LangGraph 的 State/Node/Edge？为什么不选 AutoGen/CrewAI？
- 框架能力不满足时怎么扩展？选错框架的替换成本？
- OpenClaw 为什么火爆？技术/架构上做对了什么？核心边界和局限？
- OpenClaw vs Nanobot vs NanoClaw？OpenClaw/Hermes/Claude Code 三框架区别？
- Mem0 vs Zep vs Letta 三大记忆框架怎么选？
- LangSmith / LangFuse / Phoenix 观测工具怎么选？
- 为什么 Anthropic 说"不要过早引入 Multi-Agent"？
- 意图识别：四层意图识别是哪四层？为什么不能直接让大模型判断意图？并行化意图识别怎么实现、为什么有必要？
- Agent 处理模糊指令：直接检索 vs 先反问确认？怎么判断 query 模糊还是清晰？

---

## 第 3 层：落地与工程化（SP/SSP 分水岭）
