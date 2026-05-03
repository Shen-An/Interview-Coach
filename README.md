# Interview Coach 🎙️

语音模拟面试助手：面试官人格（AI Agent 开发方向），她问你答、你也能反问她，面完自动生成五维评分复盘并存档。

题库与人格来自 `policyflow-ai/mock-interview/`（2026-05~08 共 47 份大厂面经、1250+ 题提炼），已迁移到本项目 `kb/`。

## 技术栈

- **后端**：Python + FastAPI，会话管理 + 复盘存档
- **前端**：Vue 3 + Element Plus（全部本地 vendored，无 node_modules、无构建步骤）
- **语音**：浏览器 Web Speech API —— TTS 朗读题目 + STT 识别回答，**零本地模型、零额外 API 费用**（需 Edge 或 Chrome）
- **LLM**：支持 **Anthropic Claude（Messages API）** 和 **OpenAI（Responses API）**，key 自行填写
