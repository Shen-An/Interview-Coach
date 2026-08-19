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

知识库「每日更新」的联网搜索限定在中文平台（知乎、牛客网、小红书、V2EX、掘金、CSDN、微信公众号、量子位等），域名白名单在 `backend/kb.py` 的 `SEARCH_ALLOWED_DOMAINS`；国外站点的清单留在同文件的 `SEARCH_DOMAINS_INTL` 里，想开就并进去。

**语音 key 怎么弄**（转写/合成都是 OpenAI 兼容接口，四选一即可）：
- 硅基流动 siliconflow.cn（国内直连，注册送额度）：转写 `FunAudioLLM/SenseVoiceSmall`（免费），合成 `FunAudioLLM/CosyVoice2-0.5B` + 音色 `...:benjamin`（付费）
- OpenAI 官方或任意中转站：转写 `whisper-1` / `gpt-4o-mini-transcribe`，合成 `gpt-4o-mini-tts` + `onyx`
- **合成可以白嫖**：TTS 全留空 = 微软 Edge 免费云端男声（云希神经网络音，按厂风格调韵律），断网才退回系统本地音
- 转写在 exe 版必须配一个；浏览器版走免费 Web Speech API 可不配

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
├── backend/          FastAPI（app.py 路由 / llm.py 双提供商适配 / prompts.py 提示词 / resume.py 简历解析）
├── frontend/         Vue3 SPA（侧边导航：工作台/面试/情报库/记录）+ Web Speech API（vendor/ 内含 vue / element-plus / marked）
├── kb/               面试官人格卡 / 题库 / 评分细则（知识库，可自行编辑增补）
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
