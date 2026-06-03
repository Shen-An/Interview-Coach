"""interview-coach 后端：FastAPI + 会话管理 + 复盘存档。

启动：uvicorn backend.app:app --port 47821（或 python start.py）
前端静态页由本服务直接托管，浏览器访问 http://127.0.0.1:47821
（打包版由 Electron 动态挑空闲端口注入 IC_PORT，不占固定端口）
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
# 打包运行时由 Electron 注入：IC_RES_DIR=只读资源(kb/frontend)，IC_DATA_DIR=可写数据(.env/sessions)
RES_DIR = Path(os.environ.get("IC_RES_DIR", ROOT))
DATA_DIR = Path(os.environ.get("IC_DATA_DIR", ROOT))
DATA_DIR.mkdir(parents=True, exist_ok=True)

ENV_PATH = DATA_DIR / ".env"
if not ENV_PATH.exists():  # 首次运行：生成配置模板
    example = RES_DIR / ".env.example"
    ENV_PATH.write_text(
        example.read_text(encoding="utf-8") if example.exists() else "LLM_PROVIDER=anthropic\nANTHROPIC_API_KEY=\n",
        encoding="utf-8",
    )
# override=True：.env 是唯一事实来源。机器/终端里残留的 ANTHROPIC_*/OPENAI_* 变量
# （常见于装过各类 AI CLI 的开发机，BASE_URL 往往指向一个已经换了端口的本地代理）
# 会被 SDK 悄悄捡走，症状是"配置明明对，请求却挂死在一个不存在的地址上"。
load_dotenv(ENV_PATH, override=True)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)  # 不归我们管的 SDK 认证变量，防止串到别人的网关
from .kb import KBManager  # noqa: E402

kb_mgr = KBManager(RES_DIR / "kb", DATA_DIR / "kb")
kb_mgr.seed()
os.environ["IC_KB_DIR"] = str(DATA_DIR / "kb")

from . import prompts, resume as resume_mod  # noqa: E402
from .llm import LLMClient  # noqa: E402

app = FastAPI(title="interview-coach")
llm = LLMClient()

SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

RESUME_PATH = DATA_DIR / "resume.txt"
RESUME_META = DATA_DIR / "resume.meta.json"


def load_resume() -> tuple[str, dict]:
    """返回 (简历全文, 元信息)；未上传时为空。"""
    if not RESUME_PATH.exists():
        return "", {}
    text = RESUME_PATH.read_text(encoding="utf-8")
    meta = {}
    if RESUME_META.exists():
        try:
            meta = json.loads(RESUME_META.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    return text, meta

# 内存会话表：{sid: {round, style, messages: [...], started_at}}
_sessions: dict[str, dict] = {}

OPENING = (
    "你好，我是今天的面试官，负责 Agent 平台这块。今天这轮 {round}，前面聊项目，后面有代码题。"
    "先自我介绍吧，三分钟以内，重点两件事：你的背景，以及为什么选 Agent 方向。"
    "介绍完直接告诉我，你最想让我深挖的项目是哪个。"
)

OPENING_RESUME = (
    "你好，我是今天的面试官，负责 Agent 平台这块。今天这轮 {round}，前面聊项目，后面有代码题。"
    "你的简历我看过了。先花两分钟自我介绍——重点讲你为什么选 Agent 方向，"
    "简历上的东西不用复述一遍，我等下会挨个问。"
)


class StartReq(BaseModel):
    round: str = "二面"
    style: str = "字节"
    level: str = "应届校招"


class TurnReq(BaseModel):
    text: str


class RewriteReq(BaseModel):
    text: str
    session_id: str = ""


SETTINGS_KEYS = [
    "LLM_PROVIDER", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL",
    "STT_API_KEY", "STT_BASE_URL", "STT_MODEL", "STT_REWRITE",
    "TTS_API_KEY", "TTS_BASE_URL", "TTS_MODEL", "TTS_VOICE",
]

ENV_TEMPLATE = """# ===== interview-coach 配置（可在应用「设置」里修改） =====
LLM_PROVIDER={LLM_PROVIDER}

# --- Anthropic (Claude Messages API；中转站填 ANTHROPIC_BASE_URL，不带 /v1) ---
ANTHROPIC_API_KEY={ANTHROPIC_API_KEY}
ANTHROPIC_MODEL={ANTHROPIC_MODEL}
ANTHROPIC_BASE_URL={ANTHROPIC_BASE_URL}

# --- OpenAI (Responses API，兼容网关填 OPENAI_BASE_URL) ---
OPENAI_API_KEY={OPENAI_API_KEY}
OPENAI_MODEL={OPENAI_MODEL}
OPENAI_BASE_URL={OPENAI_BASE_URL}

# --- 语音转写（whisper 兼容接口即可；留空则复用 OPENAI_*） ---
STT_API_KEY={STT_API_KEY}
STT_BASE_URL={STT_BASE_URL}
STT_MODEL={STT_MODEL}
# 语音输入后用对话模型顺一遍转写（修同音错字/术语，不润色）：on / off
STT_REWRITE={STT_REWRITE}

# --- 面试官语音合成（OpenAI 兼容 /audio/speech；留空则用 Windows 本地语音） ---
TTS_API_KEY={TTS_API_KEY}
TTS_BASE_URL={TTS_BASE_URL}
TTS_MODEL={TTS_MODEL}
TTS_VOICE={TTS_VOICE}
"""


class SettingsReq(BaseModel):
    values: dict[str, str] = {}


@app.get("/api/settings")
def get_settings():
    return {k: os.getenv(k, "") for k in SETTINGS_KEYS}


@app.post("/api/settings")
def save_settings(req: SettingsReq):
    global llm
    vals = {k: (req.values.get(k) or "").strip() for k in SETTINGS_KEYS}
    if vals["LLM_PROVIDER"] not in ("anthropic", "openai"):
        vals["LLM_PROVIDER"] = "anthropic"
    vals["ANTHROPIC_MODEL"] = vals["ANTHROPIC_MODEL"] or "claude-opus-5"
    vals["OPENAI_MODEL"] = vals["OPENAI_MODEL"] or "gpt-5"
    vals["STT_MODEL"] = vals["STT_MODEL"] or "gpt-4o-mini-transcribe"
    vals["STT_REWRITE"] = "off" if vals["STT_REWRITE"] == "off" else "on"
    vals["TTS_MODEL"] = vals["TTS_MODEL"] or "gpt-4o-mini-tts"
    vals["TTS_VOICE"] = vals["TTS_VOICE"] or "onyx"
    ENV_PATH.write_text(ENV_TEMPLATE.format(**vals), encoding="utf-8")
    for k, v in vals.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    llm = LLMClient()  # 热重建客户端，立即生效
    ok, detail = llm.ready()
    return {"ready": ok, "detail": detail,
            "stt_rewrite": _rewrite_on(),
            "stt_api_ready": bool(os.getenv("STT_API_KEY") or os.getenv("OPENAI_API_KEY"))}


@app.get("/api/config")
def get_config():
    ok, detail = llm.ready()
    chain = llm.chain()
    primary = chain[0] if chain else llm.cfg.provider
    return {
        "ready": ok,
        "detail": detail,
        "provider": primary,
        "model": llm.model_of(primary) if chain else "",
        "fallback": f"{chain[1]} / {llm.model_of(chain[1])}" if len(chain) > 1 else "",
        "stt_api_ready": bool(os.getenv("STT_API_KEY") or os.getenv("OPENAI_API_KEY")),
        "stt_rewrite": _rewrite_on(),
        "tts_api_ready": bool(os.getenv("TTS_API_KEY") or (os.getenv("TTS_BASE_URL") and os.getenv("OPENAI_API_KEY")) or (os.getenv("OPENAI_API_KEY") and os.getenv("TTS_MODEL"))),
        "env_path": str(ENV_PATH),
        "resume": _resume_state(),
        "kb": kb_mgr.state(),
    }


def _resume_state() -> dict:
    text, meta = load_resume()
    if not text:
        return {"loaded": False}
    return {
        "loaded": True,
        "filename": meta.get("filename", "简历"),
        "chars": len(text),
        "uploaded_at": meta.get("uploaded_at", ""),
        "preview": resume_mod.summarize_for_ui(text),
    }


# 模型开口演下一轮时最常见的开头，交给 API 端当停止符——比事后截断省钱也更稳。
# Anthropic 的 stop_sequences / chat-completions 的 stop 支持它；Responses API 没有
# 这个参数，那条通路只能靠 max_tokens 和下面的 _LEAK 兜。
LEAK_STOPS = ['\nuser', '\n候选人：', '\nthinking', '\nassistant']

