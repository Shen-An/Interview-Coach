# Interview Coach 🎙️

语音模拟面试助手：面试官人格（AI Agent 开发方向），她问你答、你也能反问她，面完自动生成五维评分复盘并存档。

题库与人格来自 `policyflow-ai/mock-interview/`（2026-05~08 共 47 份大厂面经、1250+ 题提炼），已迁移到本项目 `kb/`。

## 技术栈

- **后端**：Python + FastAPI，会话管理 + 复盘存档
- **前端**：Vue 3 + Element Plus（全部本地 vendored，无 node_modules、无构建步骤）
- **语音**：浏览器 Web Speech API —— TTS 朗读题目 + STT 识别回答，**零本地模型、零额外 API 费用**（需 Edge 或 Chrome）
- **LLM**：支持 **Anthropic Claude（Messages API）** 和 **OpenAI（Responses API）**，key 自行填写

## 快速开始

```bash
cd E:\Coding\Code\Python\interview-coach
pip install -r requirements.txt

copy .env.example .env     # 然后编辑 .env 填入你的 API key

python start.py            # 启动后浏览器打开 http://127.0.0.1:47821（可用 IC_PORT 环境变量改）
```

`.env` 关键项：

```ini
LLM_PROVIDER=anthropic          # 或 openai
ANTHROPIC_API_KEY=sk-ant-...    # 二选一填写（中转站 key 也填这里）
ANTHROPIC_BASE_URL=             # Claude 走中转站时填（不带 /v1）
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=                # OpenAI 走第三方网关/中转站时填（带 /v1）
```

中转站兼容说明：OpenAI 通路优先用 Responses API，网关只有 chat/completions 时自动降级（联网搜索的知识库更新除外，它需要官方或支持 /v1/responses 的网关）。

### 独立面试问答

侧边栏的「面试问答」适合随时查漏补缺，不需要先创建一场模拟面试。输入例如“如何解决工具调用失败和兜底？”或“如何降低模型幻觉？”，应用会：

1. 直接检索本地题库与日更情报，避免把整份知识库塞给模型；
2. 通过 SSE 流式展示回答，先给结论，再补充架构、工程落地、常见坑和风险边界；
3. 展示本次使用的题库/情报来源；
4. 保留最近几轮上下文，支持继续追问；
5. 前端按约 32ms 批量刷新流式文本，避免长回答时逐 token 触发布局抖动；后端在完成事件中附带 `ttft_ms`、`total_ms`、提供商和 fallback 状态，便于判断慢在首字还是生成过程。
6. 不创建模拟面试 session，也不会影响正在进行的模拟面试。

回答会明确区分本地资料和通用技术补充；没有命中本地资料时不会伪造题目、公司案例、日期、指标或来源。问答会话文件保存在可写数据目录的 `qa-conversations/` 下（开发模式为项目 `DATA_DIR`，Electron 为用户数据目录），每个会话一个 JSON 文件。问答接口为 `POST /api/qa/ask/stream`，请求体包含 `question`、可选的 `conversation_id` 和兼容用 `history`；会话管理接口为 `GET/POST /api/qa/conversations`、`GET/DELETE /api/qa/conversations/{id}`。流式协议保持向后兼容：`d` 为增量、`done` 为最终文本，`err` 为错误；`done.timing` 是可选性能诊断字段。

知识库「每日更新」的联网搜索限定在中文平台（知乎、牛客网、小红书、V2EX、掘金、CSDN、微信公众号、量子位等），域名白名单在 `backend/kb.py` 的 `SEARCH_ALLOWED_DOMAINS`；国外站点的清单留在同文件的 `SEARCH_DOMAINS_INTL` 里，想开就并进去。

**语音 key 怎么弄**（转写/合成都是 OpenAI 兼容接口，四选一即可）：
- 硅基流动 siliconflow.cn（国内直连，注册送额度）：转写 `FunAudioLLM/SenseVoiceSmall`（免费），合成 `FunAudioLLM/CosyVoice2-0.5B` + 音色 `...:benjamin`（付费）
- OpenAI 官方或任意中转站：转写 `whisper-1` / `gpt-4o-mini-transcribe`，合成 `gpt-4o-mini-tts` + `onyx`
- **合成可以白嫖**：TTS 全留空 = 微软 Edge 免费云端男声（云希神经网络音，按厂风格调韵律），断网才退回系统本地音
- 转写在 exe 版必须配一个；浏览器版走免费 Web Speech API 可不配

### 知识库怎么长出来的（原文 → 编译 → 渲染）

情报走三层，事实来源永远是原文，后两层随时能重建：

| 层 | 位置 | 是什么 |
| --- | --- | --- |
| 原文 | `kb/raw/<slug>.md` | 你导入的日更文档，或每日更新检索回来的笔记（附实际引用到的链接）。只存不解释 |
| 编译产物 | `kb/compiled/<slug>.json` | LLM 把原文抽成结构化情报：面试题 / 场景素材 / 行业事件 / 手撕题。**通不过 schema 就不落盘** |
| 渲染视图 | `kb/UPDATES.md` | 由 `compiled/` 拼装出来的 Markdown，情报库页面给人看的就是它（面试官读的是从 `compiled/` 检索出来的条目，见下一节；只有拿不到编译产物时才退回读这份） |

- 结构契约是 `kb/schema/intel.schema.json`（JSON Schema）。编译提示词里的字段骨架由这份 schema 反推生成，两边不可能各说各话；校验器在 `backend/schema.py`，零依赖，不给打包链添 Rust 扩展。
- 模型输出不合契约时，把具体错误清单喂回去重试两次，仍不合法就报错并保留原文——不再出现"格式错了但读取侧静默拿到空内容"。
- 改了 schema、换了模型、或某次编译当时失败：`POST /api/kb/recompile` 拿 `raw/` 重放一遍，不用重新上传。同名文件重复导入直接覆盖同一个 slug。
- `UPDATES.md` 有 60000 字符的渲染预算（约 20 天），超出的旧节不写进去，但 `raw/` 与 `compiled/` 不删——预算调大或删几份旧产物就又回来了。
- 三层都进仓库、也随安装包一起发。装到新机器上首次启动时播种到可写数据目录（只补缺失的，不覆盖你本机改过的），所以新机器开箱就有历史情报，而且因为原文跟着走，在本机也能重编译。

### 面试官怎么用知识库（wiki 检索）

`kb/` 就是这个项目的 wiki：页面是人写的 Markdown，git 管历史，改完下次开面就生效。面试官不是把整个 wiki 塞进提示词，而是按**这一场**（简历 + 轮次 + 压力风格 + 身份）检索出几十条最相关的条目。

| 步 | 做什么 | 在哪 |
| --- | --- | --- |
| 切条目 | 按标题层级把页面切成能单独寻址的条目，标题路径当分类留下（`QUESTION-BANK#第 2 层：设计与决策能力/工具调用设计#5`） | `backend/wiki.py`，装载时解析，不落盘 |
| 进同一个池子 | 题库条目和情报条目合成一个池，共用一套 idf、一套打分。检索时不分家，命中谁算谁 | `backend/retrieval.py` |
| 打分 | CJK 双字 + ASCII 整词切词 → BM25 式 idf → 长度归一的重合度，再叠上时效衰减（半衰期 21 天，基准是语料里最新那天）、🔥 高频加权、轮次×考点层次的适配度 | 同上 |
| 挑 | 每类按配额取，情报优先、题库补位；题面 Jaccard 去重；保底两条：最新一天的情报 ≥2 条，本轮该考那一层 ≥3~4 条 | 同上 |
| 条目间的链 | 装载时按稀有词建倒排，共享 ≥2 个稀有词就连一条边（每条最多 4 个邻居）。轮内追加时从直接命中往外走一跳，能捞到不共词但相关的条目 | 同上 |

- **为什么题库是解析而不是 LLM 编译**：题库结构规整（`##` 分层、一条一个 bullet），解析精确、免费、离线、可重放，也不留第二份产物要跟原文对账。情报那条路必须编译，因为原文是散文。
- **人格卡整份注入，不检索**：那是"我该怎么判人"的指令，不是出题素材，每场都要用全份。评分细则只给复盘用。
- **轮内追加**：候选人说完一句，再检索三条挂到提示词尾巴上（只给没进 system 的）。尾块之外的大块**逐字节稳定**，跨轮吃得到前缀缓存。答得空泛时会一条都不给——宁可不给，也不塞不相关的条目。
- **零检索依赖**：没有 faiss / chromadb / langchain、没有本地 embedding 模型。语料才几百条，纯词法检索够用，也不给单文件 exe 打包添麻烦。
- **两层各自退**：读不到页面就少几道题、没有编译产物就情报退回按时间注入，另一层照常检索，不会整场起不来。

### 检索评测

```bash
python evals/run.py        # 加 -v 看每条选中的条目
```

`evals/cases.json` 是 20 份手写简历 + 110 项期望（"这条简历这一轮，该挑出带 Rerank+TopK 的题库条目"、"主管面不该出现第 1 层八股"）。同一套期望、同一套打分，跑四条对照：统一检索 / 题库整页+情报检索（重构前线上的做法）/ 只给最近的情报 / 情报按字数给。当前结果：

| 策略 | 命中 | 平均注入 | 命中密度 |
| --- | --- | --- | --- |
| **统一检索（现在）** | **108/110（98.2%）** | **9704 字** | **0.56 项/千字** |
| 题库整页 + 情报检索 | 104/110（94.5%） | 18039 字 | 0.29 项/千字 |
| 只给最近的情报 | 39/110（35.5%） | 7149 字 | 0.27 项/千字 |
| 情报按字数给 | 52/110（47.3%） | 18989 字 | 0.14 项/千字 |

命中率必须和注入字数一起看：整页注入天然接近满分，那是拿一万字换来的，而且它没法**不给**——主管面里第 1 层八股照样在提示词里。命中来源题库 33 项 / 情报 67 项，说明题库那层是真的在被检索。

## 使用流程

1. **上传简历**（可选但强烈建议，PDF / DOCX / TXT / MD）——上传后面试官会照着你的简历逐条深挖
2. 选轮次（一面/二面）和压力风格（字节/美团/阿里蚂蚁/腾讯/京东）
3. 面试官开场提问并**朗读**；点 🎤 **按下说话**回答，停止后自动发送（也可打字）
4. 双向对话：随时可以反问澄清、或进入反问环节
5. 点**结束面试并复盘** → 五维评分卡 + 扣分点原话回放 + 改进项（传了简历还会多出「简历兑现度」和「简历需要改的地方」两节）
6. 记录与复盘自动存档到 `sessions/YYYY-MM-DD-HHMM-<轮次>.md`

## 简历模式做了什么

传了简历后，面试官的行为会变成：

- **只问简历里真实存在的东西**，项目名、技术栈、指标数字全部取自简历，不虚构经历
- **拿简历原文当抓手追问**：写"提升 30%"就问基线和测法；写"高并发"就问 QPS 峰值；写"自研"就问为什么不用现成的、你负责哪块
- **专打简历的空白与可疑处**：时间线断档、"参与/负责相关工作"这类含糊表述、技术栈罗列但项目里没体现、指标没有基线
- **题库题目改写成贴合你简历的版本**再问，而不是泛泛考概念
- 复盘时额外给出**简历兑现度**（写了但答不出细节的会被点名）和**简历改写建议**（给出改写后的句子）

简历存在 `%APPDATA%/interview-coach/resume.txt`，上传一次长期复用，随时可在首页「换一份 / 移除」。

## 目录结构

```
interview-coach/
├── backend/          FastAPI（app.py 路由 / llm.py 双提供商适配 / prompts.py 提示词 / resume.py 简历解析
│                     kb.py 情报三层流水线 / schema.py 零依赖 JSON Schema 校验
│                     wiki.py 页面切条目 / retrieval.py 题库+情报同池检索）
├── frontend/         Vue3 SPA（侧边导航：工作台/面试问答/模拟面试/情报库/记录）+ Web Speech API（vendor/ 内含 vue / element-plus / marked）
├── kb/               这个项目的 wiki。人格卡 / 题库 / 评分细则是人写的页面（可自行编辑增补），以及增量情报三层：
│   ├── raw/          原文（导入的日更文档 / 检索笔记），事实来源
│   ├── compiled/     LLM 编译产物 JSON，过 schema 才落盘
│   ├── schema/       intel.schema.json —— 结构契约，跟着代码走
│   └── UPDATES.md    由 compiled/ 渲染出来的视图，人看这份、检索不到编译产物时也读它
├── evals/            检索评测（cases.json 手写期望 / run.py 四策略对照）
├── assets/           应用图标（icon.ico / icon-1024.png）
├── sessions/         每场面试的记录与复盘
├── .env.example      LLM 配置模板
└── start.py          一键启动
```

## 常见问题

- **麦克风没反应**：确认用 Edge/Chrome，且允许了 `127.0.0.1` 的麦克风权限
- **朗读没声音**：Windows 设置里确认装有中文语音包（Edge 自带 Xiaoxiao 等）
- **换题库**：直接编辑 `kb/QUESTION-BANK.md`，重启即生效

## 打包为 exe（Electron 版）

已内置完整打包链，产物在 `dist-electron/`：

- **InterviewCoach Setup x.y.z.exe** —— NSIS 安装包（最新版在 GitHub Releases 下载），双击安装，桌面快捷方式「Interview Coach」
- 所有配置在应用内「设置」里填，保存即生效；`.env`、面试记录、知识库、后端日志可从「设置」弹窗底部或托盘右键菜单直达
- 响应速度可通过 `.env` 调整：`IC_LLM_READ_TIMEOUT` 默认 45 秒（流式相邻数据块空闲上限），`QA_MAX_OUTPUT_TOKENS` 默认 3200；不会限制持续输出的完整回答
- 关闭窗口 = 收进系统托盘（右键托盘图标「退出」才真正退出）；右上角 ☀/🌙 切换日间/夜间主题
- 后端端口每次启动动态分配，不会再和其它程序抢端口；异常时看 `%APPDATA%\interview-coach\backend.log`

### exe 版语音说明

Electron 里浏览器内置语音识别不可用（缺 Google 服务密钥），因此 exe 版：
- **识别（你说话）**：MediaRecorder 录音 → OpenAI 转写 API（需在 .env 配 `OPENAI_API_KEY`，模型默认 `gpt-4o-mini-transcribe`，可用 `OPENAI_BASE_URL` 走兼容网关）
- **朗读（她说话）**：Windows 本地语音，正常可用
- 浏览器版（`python start.py`）不受影响，识别仍走免费 Web Speech API

### 重新构建

```bash
# 1) 干净 venv 打后端（避免 Anaconda 环境污染）
python -m venv build-venv
build-venv\Scripts\pip install -r requirements.txt pyinstaller
build-venv\Scripts\pyinstaller --onefile --name interview-coach-backend ^
  --distpath dist-backend --workpath build-pyi --specpath build-pyi ^
  --add-binary "E:/Coding/Anaconda/Library/bin/ffi-8.dll;." ^
  --add-binary "E:/Coding/Anaconda/Library/bin/ffi.dll;." run_backend.py

# 2) Electron 安装包（国内走镜像）
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
npm install --registry=https://registry.npmmirror.com
npm run dist
```
