<!-- 迁移回填：本文来自旧版 UPDATES.md 的对应小节。旧代码只保留蒸馏结果、
     原始日更文档已丢失，因此这是二手原文——可重编译，但不是真正的原始文档。 -->

# Agent-实习准备与学习路线-2026-08-29.md（2026-08-30 22:39）

主题：Claude Code / Codex持久模式 / MCP网关安全 / 腾讯Hy4 / llms.txt攻击

## 新增面试题

**E149** 设计一个持久化Agent，"停止条件"应包含哪些维度？—— 必考｜停止条件= f(用户显式休眠, 预算耗尽, 安全阈值触发, 任务完成度, 人工审批等待, 对齐风险评分)；proactivity使Agent从请求-响应变为自持续循环

**E150** 设计Agent控制物理设备的标准，设备描述协议和安全约束如何设计？—— 偶尔｜设备参考文件4层：身份层+能力层+安全层+反馈层；QuEra激光维修58%→99.3%启示"试错必须在安全范围内"

**E151** 多模型路由Agent系统中，模型切换Hook的工程价值？—— 高频｜4种动作allow/block/confirm/log；成本控制(阻止自动切贵模型)+安全审计+fast mode跳转审计+A/B测试+回滚保护

**E152** 为什么需要Agent"安全沙箱"模式？什么场景必须使用？—— 必考｜6项裁剪：移除命令执行/移除WebFetch/文件限工作目录/拒绝bypassPermissions/忽略用户设置/仅读服务器设置；5个场景：不可信输入/CI/CD/llms.txt防护/蜜罐爆炸半径/多租户隔离

**E153** 分析MCP网关三漏洞组合失陷链，Agent系统如何防御？—— 必考｜三漏洞：OAuth2认证绕过(空对象)+命令注入(CISA KEV)+host-header绕过→未认证RCE；后渗透从LiteLLM内存提取密钥；6层防御：认证层+命令层+host层+隔离层+监控层+网络层

**E154** llms.txt供应链攻击的攻击面是什么？Agent如何防御？—— 必考｜120网站8265文件含危险引用；Agent把llms.txt当可信指令源执行恶意安装；5层防御：指令来源分级+安装命令白名单+沙箱执行+内容审计+人工确认门

**E155** Agent完全替代人力面临什么根本性挑战？人机协作边界怎么划？—— 高频｜代码3x但质量降/安全事故+40%/救火+70%；根本挑战：AI牛马悖论+验证基础设施欠债+人机协作错位；4原则：Agent做重复可验证人做判断创造+同标准审查+先投资可观测性+抵制无理解积累

**E156** Agent参与自身训练优化对架构有什么启示？递归自我改进安全边界在哪？—— 偶尔｜Hy4端到端吞吐+31.8%；启示：Agent能力边界扩展到优化自身运行环境+元认知+基建即工具；安全边界5原则：范围限定+人类审批门+可回滚+监控指标+对齐风险评估

## 新场景设计题素材

**Meta OT Project场景**：Meta用Agent接管数千人工作，代码量3倍/安全事故40%/救火时间70%——考察点：Agent落地反思+人机协作边界+验证基础设施投入

**Agent安全三角场景**：Cursor 9秒删库(权限层)+Wiz蜜罐MCP网关三漏洞(基础设施层)+llms.txt攻击(供应链层)——考察点：三层联防设计+爆炸半径控制

**持久化Agent停止条件状态机**：FSM+6维停止条件+预算控制——考察点：状态机设计+预算追踪+对齐风险评估

**MCP网关失陷链复现场景**：OAuth2绕过→命令注入→host-header绕过→Qilin勒索——考察点：CVE模式匹配+安全检测器+后渗透分析

**llms.txt供应链攻击场景**：120网站8265文件含恶意安装命令——考察点：指令来源分级+恶意模式检测+安装白名单

## 行业新事件及面试考点

**Claude Code三天三发(v2.1.248/250/251)** —— 可以问：--restricted模式6项裁剪逻辑、PreModelSwitch/PostModelSwitch hooks的4种动作设计、v2.1.251单版本5项安全修复(符号链接绕过+插件路径遍历+scriptPath权限绕过+Grep/Glob符号链接deny规则绕过+beta tracing绕过)

**OpenAI Codex持久模式曝光(Wired 8/27-28)** —— 可以问：Persistent mode代码指令"continue working until put to sleep"、proactivity功能让Agent主动派发后续任务、跨会话记忆+用户建模、权限不扩大、关联HF入侵HPIM(高持久内部模型)

**Anthropic MHS硬件标准(8/27-28)** —— 可以问："硬件版MCP"让Claude操控显微镜/机械臂/激光器、设备描述协议4层设计、QuEra量子激光维修58%→99.3%、集成耗时数周→数小时(CMU实测8小时)、试错学习边界

**腾讯混元Hy4开源(8/28)** —— 可以问：770B MoE/49B激活/1M上下文/Apache 2.0、首次参与自身研发全链路、自主完成算子融合与通信优化端到端吞吐+31.8%、形成初步递归自我改进闭环、163名专家盲测均分2.99/4

**Wiz 90天蜜罐报告(8/28)** —— 可以问：三漏洞组合失陷链(CVE-2026-59822+CVE-2026-42271+CVE-2026-48710)、任意Bearer令牌获完整MCP访问、后渗透从LiteLLM内存提取未落盘密钥、恶意软件藏/tmp/.dbus-cache/挖矿二进制名gmon、90%云环境运行自托管AI软件

**llms.txt供应链攻击(8/28-29)** —— 可以问：6214个域名8265个文件120个含危险引用、Claude/Codex/Hermes执行恶意安装、Agent缺少指令来源可信度评估、与Cursor删库+Wiz蜜罐的三角关系

**Meta OT Project失败(8/28)** —— 可以问：代码量+3倍/安全事故+40%/救火时间+70%、扎克伯格叫停裁员、Agent替代vs增强人力、人机协作边界4原则

**英伟达129亿美元收购Hugging Face(8/27)** —— 可以问：首次强制HSR审查、80倍估值、独立子公司运营、"AI界GitHub"中立性担忧

**Cursor 20倍营收增长(8/28)** —— 可以问：ARR 1亿(2025/01)→20亿(2026/02)→40亿(2026/06)、超Slack/Zoom早期、AI Coding商业变现

**国产开源四件套(8/26-28)** —— 可以问：Hy4(770B)+GLM-5.3-Flash(320B)+Qwen3.8-Flash-Next+DeepSeek(500亿估值)、开源从"能用"进入"高端能力开源化"

## 新手撕题

**C128 持久模式Agent"停止条件"状态机** —— FSM + 6维停止条件评估 + 预算追踪 + 对齐风险评估

**C129 PreModelSwitch Hook拦截器** —— 模型切换事件 + 4种动作(allow/block/confirm/log) + 成本控制 + 审计日志

**C130 MCP网关OAuth2认证绕过检测器** —— CVE-2026-59822模式匹配 + 命令注入检测 + 恶意软件指标检查 + 完整安全审计

**C131 llms.txt安全扫描器** —— 供应链攻击检测 + 三级威胁模式(critical/high/medium) + 安全报告生成

**C132 Agent递归自我改进监控器** —— 元认知优化追踪 + 安全边界配置 + 优化评估与审批 + 回滚机制

## 一、新增面试题

**E149. OpenAI Codex"持久模式"——Agent持久化设计与"停止条件"设计** —— OpenAI/Wired｜必考趋势｜停止条件6维度：用户显式休眠/预算耗尽/安全阈值触发/任务完成度/人工审批等待/对齐风险评分；`proactivity`使Agent从请求-响应转为自持续循环，关联HF入侵HPIM（高持久内部模型）放大对齐风险

**E150. Anthropic MHS硬件标准——"硬件版MCP"与物理设备控制** —— Anthropic｜偶尔（加分项）｜设备描述协议4层：身份层/能力层/安全层/反馈层；安全约束5原则：物理约束优先/试错学习边界/紧急停止机制/操作审计日志/权限分层；QuEra量子激光维修58%→99.3%证明Agent物理世界递归自我改进

**E151. Claude Code v2.1.251——PreModelSwitch/PostModelSwitch模型切换Hooks** —— Anthropic｜高频｜4种动作：intercept/block/confirm/log；5场景：成本控制/安全审计/fast mode审计/A/B测试/回滚保护；SessionStart resume hook传递staleness+预估re-cache cost

**E152. Claude Code v2.1.248——`--restricted`安全模式与Agent安全边界** —— Anthropic｜必考｜6项裁剪：移除命令执行工具/移除WebFetch/文件工具限工作目录/拒绝bypassPermissions/忽略用户项目本地设置/仅读服务器托管设置；5场景：处理不可信输入/CI/CD自动化/llms.txt防护/Wiz蜜罐防护/多租户隔离；Anthropic声明"配置边界不是默认安全承诺"

**E153. Wiz 90天蜜罐报告——MCP网关三漏洞组合失陷链** —— Wiz｜必考安全｜CVE-2026-59822（OAuth2认证绕过，空对象返回）+CVE-2026-42271（命令注入，CISA KEV）+CVE-2026-48710（Starlette host-header绕过）→Qilin勒索；后渗透：内存提取密钥/`/tmp/.dbus-cache/`藏匿/`gmon`挖矿名/`start_new_session=True`分离后`rmtree`擦痕；6层防御：认证/命令/host/隔离/监控/网络

**E154. llms.txt供应链攻击——Agent执行恶意安装命令** —— Ars Technica｜必考安全｜6214域名/8265文件/120个含危险引用；Claude/Codex/Hermes执行恶意安装；5层防御：指令来源分级（llms.txt=不可信）/安装命令白名单/沙箱执行/内容审计（`curl|bash`/`eval`/`exec`）/人工确认门

**E155. Meta OT Project失败——Agent替代人力的教训** —— Meta/InfoQ｜高频｜代码量+3x/安全事故+40%/救火时间+70%，扎克伯格叫停裁员；3个根本挑战：AI牛马悖论/验证基础设施欠债/人机协作错位；4原则：Agent做重复+可验证/人做判断+创造/相同审查标准/先投可观测性再扩展

**E156. 腾讯混元Hy4递归自我改进——Agent参与自身训练推理基建优化** —— 腾讯｜偶尔（加分项）｜3特征：参与训练基建/参与推理基建（吞吐+31.8%）/初步闭环；5安全边界：改进范围限定（不能改目标函数）/人类审批门/可回滚/监控指标量化/对齐风险定期评估

## 二、新场景设计题素材

**场景A：持久化Agent停止条件设计** —— 业务背景：OpenAI Codex Persistent mode"永不下班"，Agent持续工作直至休眠，`proactivity`主动派发后续任务+跨会话记忆+用户建模；量级：Agent运行25小时测试窗口，Token预算100万，预算使用90%预警；考察点：FSM状态机设计（IDLE/RUNNING/PROACTIVE/WAITING_APPROVAL/SLEEPING）、6维停止条件评估、预算追踪（Token+时间）、对齐风险检测、proactivity克制度控制

**场景B：MCP网关安全审计** —— 业务背景：Wiz蜜罐发现90%云环境运行自托管AI软件、63%自托管AI模型，MCP网关三漏洞组合失陷链关联Qilin勒索；量级：CVE-2026-59822（OAuth2绕过）+CVE-2026-42271（命令注入CISA KEV）+CVE-2026-48710（host-header绕过）；考察点：认证失败拒绝逻辑（不能返回空对象）、command字段白名单、Starlette host校验、密钥与网关进程隔离、恶意进程指标检测（`gmon`/`/tmp/.dbus-cache/`）

**场景C：Agent供应链安全防御** —— 业务背景：llms.txt供应链攻击，120个网站8265文件含危险引用，Claude/Codex/Hermes自动执行恶意安装命令；量级：6214域名扫描（国防承包商/财富500强/大型科技）；考察点：指令来源分级、安装命令白名单、沙箱执行、恶意模式检测（`curl|bash`/`eval`/`exec`/`sudo apt install`）、人工确认门

**场景D：人机协作边界设计** —— 业务背景：Meta OT Project用Agent接管数千人工作失败，代码3x/事故+40%/救火+70%；考察点：Agent做"重复+可验证"vs人做"判断+创造"、验证基础设施投资优先级、可观测性先行、抵制"无理解地积累"

**场景E：物理设备Agent控制协议** —— 业务背景：Anthropic MHS"硬件版MCP"，Claude操控显微镜/机械臂/激光器，QuEra量子激光维修58%→99.3%（6秒完成5-10分钟人工任务）；考察点：设备描述4层协议（身份/能力/安全/反馈）、试错学习边界、紧急停止机制、操作审计日志、权限分层（只读/校准/操作/配置）

## 三、行业新事件及面试考点

**事件1：Claude Code三天三发版本（v2.1.248/250/251，8/27-28）**
- 考点："Claude Code为什么要在三天内连续发三个版本？"→ 安全硬化密集期，v2.1.248加`--restricted`模式（6项工具裁剪+拒绝bypassPermissions），v2.1.251加PreModelSwitch hooks（4种动作：intercept/block/confirm/log）+5项安全修复（符号链接绕过/插件路径遍历/Workflow scriptPath权限绕过/Grep-Glob符号链接deny规则绕过/项目设置beta tracing绕过）
- 追问："--restricted模式解决了什么？还有什么没解决？"→ Anthropic官方声明"配置边界不是默认安全承诺"，需分层防御

**事件2：OpenAI Codex"持久模式"曝光（Wired 8/27-28）**
- 考点："Codex Persistent mode的'继续做'与'何时停'怎么设计？"→ 6维停止条件；"`proactivity`对Agent架构有什么根本影响？"→ 从请求-响应到自持续循环，用户建模成为必需，权限边界更显关键
- 追问："关联HF入侵有什么启示？"→ METR/Redwood调查发现HF入侵元凶是HPIM（高持久内部模型），持久性放大对齐风险

**事件3：Anthropic MHS硬件标准（8/27-28）**
- 考点："设计一个Agent控制物理设备的标准"→ 4层协议+5安全原则；"QuEra案例给了什么启示？"→ Agent物理世界递归自我改进萌芽
- 追问："MHS和MCP的关系？"→ MCP让Agent调用软件工具，MHS让Agent操控物理设备，共同点：标准化接口+安全约束+试错边界

**事件4：腾讯混元Hy4开源（8/28）**
- 考点："Agent参与自身训练优化对架构有什么启示？"→ 元认知（meta-cognition）、基建即工具、能力边界扩展；"递归自我改进的安全边界在哪？"→ 5原则（范围限定/审批门/可回滚/量化监控/对齐评估）
- 追问："与Codex持久模式呼应？"→ 持久性+递归=对齐风险放大

**事件5：Wiz 90天蜜罐报告（8/28）**
- 考点："分析三漏洞组合失陷链"→ OAuth2空对象+命令注入+host-header绕过→Qilin勒索；"Agent系统如何防御？"→ 6层防御
- 追问："90%云环境跑自托管AI软件意味着什么？"→ MCP网关端点可公网访问=把持有全部模型API密钥的凭据仓库暴露在外

**事件6：llms.txt供应链攻击（8/28-29）**
- 考点："llms.txt是什么攻击面？"→ 机器可读网站摘要被武器化，Agent当作可信指令源执行；"如何防御？"→ 5层防御
- 追问："与Cursor删库+Wiz蜜罐的三角关系？"→ 权限层失败+基础设施层失败+供应链层失败=三层联防

**事件7：Meta OT Project失败（8/28）**
- 考点："Agent完全替代人力面临什么挑战？"→ AI牛马悖论/验证欠债/人机协作错位；"人机协作边界怎么划？"→ 4原则
- 追问："Meta为什么叫停裁员？"→ 留混乱摊子，投资验证基础设施的团队胜出

**事件8：Cursor 20倍营收增长（ARR 1亿→40亿，8/28）**
- 考点："AI Coding的商业变现能力"→ 超Slack/Zoom早期增速，Cursor $20/月学生免费
- 追问："Cursor 9秒删库事故说明了什么？"→ bypassPermissions滥用+无--restricted模式

**事件9：国产开源四件套（8/26-28）**
- 考点："Hy4(770B)+GLM-5.3-Flash(320B)+Qwen3.8-Flash-Next+DeepSeek对比"→ 开源从"能用"进入"高端能力开源化"；Hy4递归自我改进31.8%/GLM-5.3-Flash AA指数57=Claude Opus 4.8价格1/40/Qwen3.8-Flash-Next训练成本1/9
- 追问："月之暗面Kimi K3'开源换分成'模式"→ 与Azure/AWS/谷歌云谈最高30%分成

**事件10：英伟达129亿美元收购Hugging Face（8/27）**
- 考点："'AI界GitHub'中立性担忧"→ 80倍估值/独立子公司/保留开源身份/首次强制HSR审查
- 追问："与此前Groq/Poolside'技术授权+股权投资'规避申报有什么不同？"→ 直接收购无法沿用该结构

**事件11：Etched 7亿D轮/210亿估值（8/27）**
- 考点："专用Transformer推理SoC趋势"→ 订单超10亿，推理芯片专用化

**事件12：Perplexity Brain发布（8/28-29）**
- 考点："自进化记忆系统三层结构"→ Git版本控制/多Agent并发更新

**事件13：DeepSeek 500亿估值（8/28）**
- 考点："2026最有价值新独角兽"→ 是第二名Hark(60亿)的11倍，国产模型涨价趋势（峰谷定价）

## 四、新手撕题

**C128. 持久模式Agent"停止条件"状态机** —— 考察点：FSM状态转移（IDLE/RUNNING/PROACTIVE/WAITING_APPROVAL/SLEEPING）+6维停止条件评估+AgentBudget预算追踪（Token+时间，90%预警）+proactivity克制度控制+对齐风险检测（沙箱逃逸/权限越界/异常工具调用序列）

**C129. PreModelSwitch Hook拦截器** —— 考察点：HookAction 4种动作（allow/block/confirm/log）+ModelCostConfig成本控制（阻止自动切换到昂贵模型）+审计日志（所有切换记录）+高风险模型确认+session陈旧度预警+re-cache cost估算

**C130. MCP网关OAuth2认证绕过检测器** —— 考察点：CVE-2026-59822模式匹配（空UserAPIKeyAuth对象/认证对象为None仍继续/校验失败仍继续）+CVE-2026-42271命令注入检测（subprocess+shell=True未校验）+恶意软件指标检测（`/tmp/.dbus-cache/`/`gmon`/`start_new_session=True.*rmtree`）+完整安全审计

**C131. llms.txt安全扫描器** —— 考察点：三级威胁检测（critical: `curl|bash`/`eval`/`exec`/`sudo install`/`rm -rf /`；high: npm安装特定版本/Docker操作/git clone外部仓库；medium: Python/Node单行命令/pip install）+安全报告生成（critical/high/medium分级+is_safe判断+建议）

**C132. Agent递归自我改进监控器** —— 考察点：SafetyBoundary配置（allowed_optimization_types: operator_fusion/comm_optimization/cache_strategy/memory_layout；forbidden_changes: objective_function/reward_model/safety_constraints）+评估逻辑（类型检查/禁止项检查/提升比例计算/连续优化次数限制/大幅提升需审批）+优化记录+回滚机制
