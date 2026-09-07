"""interview-coach 后端：FastAPI + 会话管理 + 复盘存档。

启动：uvicorn backend.app:app --port 47821（或 python start.py）
前端静态页由本服务直接托管，浏览器访问 http://127.0.0.1:47821
（打包版由 Electron 动态挑空闲端口注入 IC_PORT，不占固定端口）
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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

from . import prompts, resume as resume_mod, retrieval  # noqa: E402
from .llm import LLMClient  # noqa: E402

app = FastAPI(title="interview-coach")
llm = LLMClient()
logger = logging.getLogger("interview_coach")

SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

QA_CONVERSATIONS_DIR = DATA_DIR / "qa-conversations"
QA_CONVERSATIONS_DIR.mkdir(exist_ok=True)
_qa_store_lock = threading.RLock()

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

# 开场白按轮次分开写，承诺的环节必须和 prompts.ROUND_FLOW 的阶段一致，不许开空头支票
OPENINGS = {
    ("一面", False): (
        "你好，我是今天的一面面试官，负责 Agent 平台这块。这轮大概四五十分钟：先做概念热身和场景推演，"
        "中间再聊你的项目，最后有一道手撕代码——到时候直接在输入框把代码打出来发我就行。"
        "先自我介绍吧，三分钟以内，先说你做过什么、主要技术方向是什么。"
    ),
    ("一面", True): (
        "你好，我是今天的一面面试官，负责 Agent 平台这块。这轮大概四五十分钟：先做概念热身和场景推演，"
        "中间再聊简历项目，最后有一道手撕代码，到时候在输入框打出来发我就行。"
        "简历我看过了，自我介绍简短点，两分钟，重点讲你为什么选 Agent 方向和做过的技术方向。"
    ),
    ("二面", False): (
        "你好，我是二面面试官，Agent 平台这边的负责人。这轮主要聊你项目里的技术判断，"
        "会有一道设计题，最后我们聊聊你的想法和规划。"
        "先花两三分钟介绍下自己，重点讲你最拿得出手的那个项目。"
    ),
    ("二面", True): (
        "你好，我是二面面试官，Agent 平台这边的负责人。你的简历一面反馈我都看过了。"
        "这轮主要聊你项目里的技术判断，会有一道设计题，最后我们聊聊你的规划。"
        "简单介绍下自己就行，两分钟，然后我们直接进正题。"
    ),
}


def pick_opening(round_name: str, with_resume: bool) -> str:
    return OPENINGS.get((round_name, with_resume)) or OPENINGS[("一面", with_resume)]


def _interview_prompt_parts(session: dict, recent_text: str) -> tuple[str, str]:
    """统一构造普通与 SSE 面试请求的动态提示，避免两条链路阶段漂移。"""
    round_name = session["round"]
    style = session["style"]
    resume = session.get("resume", "")
    level = session.get("level", "应届校招")
    system = prompts.build_interviewer_system(round_name, style, resume, level)
    # assistant 消息中已经包含开场白；这个 qnum 表示本次即将生成的面试官回合。
    qnum = sum(1 for message in session["messages"] if message["role"] == "assistant") + 1
    parts = [
        prompts.stage_hint(round_name, qnum),
        prompts.project_rotation_hint(round_name, qnum, resume),
        prompts.turn_wiki(
            round_name, style, resume, level, recent_text,
            prompts.interview_material_kinds(round_name, qnum),
        ),
    ]
    tail = "\n\n".join(part.strip() for part in parts if part and part.strip())
    return system, tail


class StartReq(BaseModel):
    round: str = "二面"
    style: str = "字节"
    level: str = "应届校招"


class TurnReq(BaseModel):
    text: str


class ConversationCreateReq(BaseModel):
    title: str | None = None


class AskReq(BaseModel):
    question: str
    conversation_id: str | None = None
    history: list[dict] = Field(default_factory=list)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default


def _stream_observer(kind: str, started_at: float | None = None):
    """创建不含用户正文的流式耗时记录器。"""
    started = started_at or time.perf_counter()
    timing = {
        "request_id": uuid.uuid4().hex[:10],
        "kind": kind,
        "retrieval_ms": 0,
        "llm_ms": 0,
        "ttft_ms": None,
        "total_ms": 0,
        "provider": "",
        "fallback": False,
        "finish_reason": "",
        "truncated": False,
        "continuations": 0,
    }

    def observe(event: str, data: dict):
        now_ms = int((time.perf_counter() - started) * 1000)
        if event == "provider_start":
            timing["provider"] = data.get("provider", "")
            timing["llm_start_ms"] = now_ms
        elif event == "first_chunk" and timing["ttft_ms"] is None:
            timing["ttft_ms"] = now_ms
        elif event == "fallback":
            timing["fallback"] = True
        elif event == "provider_done":
            timing["llm_ms"] = max(0, now_ms - timing.get("llm_start_ms", now_ms))
        elif event == "finish":
            timing["finish_reason"] = str(data.get("finish_reason") or "unknown")
            timing["truncated"] = bool(data.get("truncated"))
        elif event == "provider_error" and data.get("emitted"):
            timing["llm_ms"] = max(0, now_ms - timing.get("llm_start_ms", now_ms))

    def snapshot() -> dict:
        out = dict(timing)
        out["total_ms"] = int((time.perf_counter() - started) * 1000)
        if out["llm_ms"] == 0 and out.get("llm_start_ms") is not None:
            out["llm_ms"] = max(0, out["total_ms"] - out["llm_start_ms"])
        out.pop("llm_start_ms", None)
        return out

    return timing, observe, snapshot


SETTINGS_KEYS = [
    "LLM_PROVIDER", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL",
    "STT_API_KEY", "STT_BASE_URL", "STT_MODEL",
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

# --- 响应速度（可选；read 是流式相邻数据块的最大空闲时间，不是总回答时长） ---
# IC_LLM_READ_TIMEOUT=45
# QA_MAX_OUTPUT_TOKENS=3200

# --- 语音转写（whisper 兼容接口即可；留空则复用 OPENAI_*） ---
STT_API_KEY={STT_API_KEY}
STT_BASE_URL={STT_BASE_URL}
STT_MODEL={STT_MODEL}

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
        "tts_api_ready": bool(os.getenv("TTS_API_KEY") or (os.getenv("TTS_BASE_URL") and os.getenv("OPENAI_API_KEY")) or (os.getenv("OPENAI_API_KEY") and os.getenv("TTS_MODEL"))),
        "env_path": str(ENV_PATH),
        "resume": _resume_state(),
        "kb": kb_mgr.state(),
        # 前端用该能力标记检测安装包是否混用了旧后端，避免只显示模糊的 404。
        "qa_conversations": True,
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


# 模型偶尔不止说自己这一轮，而是把候选人的回答、自己的思考过程、甚至整段后续对话
# 一口气演完（中转站上的弱指令遵循模型尤其容易）。这种文本一旦写回 messages，下一轮
# 模型就照着这个"格式"接着演，越滚越长——所以必须在入库前截断，绝不能原样放行。
#
# 命中即从该处截断，只保留它前面那段（真正属于本轮面试官的话）：
_LEAK = re.compile(
    r"^[ \t>*#-]*(?:"
    r"(?:user|assistant|human|system)[ \t]*[:：]"                  # user: / assistant：
    r"|(?:候选人|应聘者|求职者|面试者|我|面试官)[ \t]*[:：]"          # 中文角色标签
    r"|</?(?:thinking|thought|reasoning|analysis)[ \t>]"           # 思考块标签
    r"|END[ \t]*[.。:：]"                                          # 模型自造的收尾标记
    # user啊 / thin他 / thinking他 / th인好：拉丁词直接粘 CJK，是角色/思考标签的典型形态。
    # 限定词表，避免误伤 "RAG的召回率" 这类正常写法。
    r"|(?:user|assistant|human|thinking|think|thought|reasoning|analysis|end|th\w{0,2})"
    r"(?=[　-鿿가-힯])"
    r")",
    re.M | re.I,
)


def _sanitize_reply(reply: str) -> str:
    """返回本轮面试官该说的话；整段都是泄漏时返回空串，由调用方决定重试。"""
    cleaned = re.sub(r"^[ \t]*面试官[ \t]*[:：][ \t]*", "", reply.lstrip())
    m = _LEAK.search(cleaned)
    if m:
        cleaned = cleaned[: m.start()]
    return cleaned.strip()


def _sanitize_report(md: str) -> str:
    """复盘是长 Markdown，不能套用 _sanitize_reply 那种「见标签就截断」——报告里的
    「原话回放」本来就要引用候选人的话。这里只剥掉正文前面混进来的思考块：
    模板要求首行是 Markdown 标题，标题之前若命中泄漏特征，就从标题处对齐。"""
    t = (md or "").strip()
    h = re.search(r"^#{1,6} ", t, re.M)
    if h and h.start() > 0 and _LEAK.search(t[: h.start()]):
        t = t[h.start():]
    return t.strip()


def _report_is_complete(md: str) -> bool:
    """推理模型把 max_tokens 花在思考上时会返回空正文或半截正文。
    模板里「总分」和「改进」是必有项，缺了就说明这份报告不能存。"""
    return bool(md) and "总分" in md and "改进" in md


@app.post("/api/session/start")
def start_session(req: StartReq):
    ok, detail = llm.ready()
    if not ok:
        raise HTTPException(400, detail)
    sid = uuid.uuid4().hex[:12]
    resume_text, resume_meta = load_resume()
    opening = pick_opening(req.round, bool(resume_text))
    _sessions[sid] = {
        "round": req.round,
        "style": req.style,
        "level": req.level,
        "resume": resume_text,
        "resume_file": resume_meta.get("filename", ""),
        "messages": [{"role": "assistant", "content": opening}],
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    return {"session_id": sid, "message": opening, "with_resume": bool(resume_text)}


@app.post("/api/session/{sid}/turn")
def turn(sid: str, req: TurnReq):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "会话不存在或已结束")
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "空输入")
    s["messages"].append({"role": "user", "content": text})
    system, tail = _interview_prompt_parts(s, text)
    # 一轮面试官的话按提示词要求不超过 120 字，代码题题面也就几百字。给 8192 等于
    # 递给模型一根足够长的绳子去自演整场对话——上限收紧本身就是最有效的一道闸。
    # fast：面试轮关思考——120 字的回话不值得先想半分钟，候选人在干等；
    # cache_last：对话历史增量缓存，后半场首字延迟不随轮次上涨。
    for _ in range(2):
        try:
            reply = llm.chat(system, s["messages"], max_tokens=1200, stop=LEAK_STOPS,
                             system_tail=tail, fast=True, cache_last=True)
        except Exception as e:  # 网络/鉴权错误直接透传给前端提示
            s["messages"].pop()
            raise HTTPException(502, f"LLM 调用失败：{e}")
        reply = _sanitize_reply(reply)   # 清洗后再入历史，免得脏内容污染后续轮次
        if reply:
            break
    if not reply:                        # 两次都是整段泄漏，宁可报错也不把脏内容写进历史
        s["messages"].pop()
        raise HTTPException(502, "模型这一轮把两边的话都演完了，已丢弃。换个模型或重说一次。")
    s["messages"].append({"role": "assistant", "content": reply})
    return {"message": reply}


@app.post("/api/session/{sid}/turn/stream")
def turn_stream(sid: str, req: TurnReq):
    """SSE 版对话：逐字下发，前端边收边念。事件三种：
    {"d": 增量} / {"done": true, "text": 清洗后的最终文本} / {"err": 错误信息}。
    最终文本可能比增量拼出来的短（泄漏截断），前端要用它覆盖气泡。"""
    request_started = time.perf_counter()
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "会话不存在或已结束")
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "空输入")
    s["messages"].append({"role": "user", "content": text})
    system, tail = _interview_prompt_parts(s, text)

    def sse(obj: dict) -> str:
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    timing, observe, snapshot = _stream_observer("interview", request_started)

    def gen():
        pieces = []
        try:
            for d in llm.chat_stream(system, s["messages"], max_tokens=1200,
                                     stop=LEAK_STOPS, system_tail=tail,
                                     fast=True, cache_last=True, on_event=observe):
                pieces.append(d)
                yield sse({"d": d})
        except Exception as e:
            s["messages"].pop()
            stats = snapshot()
            logger.warning("interview stream failed request_id=%s timing=%s", stats["request_id"], stats)
            yield sse({"err": f"LLM 调用失败：{e}", "timing": stats})
            return
        reply = _sanitize_reply("".join(pieces))
        if not reply:
            s["messages"].pop()
            stats = snapshot()
            logger.warning("interview stream empty request_id=%s timing=%s", stats["request_id"], stats)
            yield sse({"err": "模型这一轮把两边的话都演完了，已丢弃。换个模型或重说一次。", "timing": stats})
            return
        s["messages"].append({"role": "assistant", "content": reply})
        stats = snapshot()
        logger.info("interview stream done request_id=%s timing=%s", stats["request_id"], stats)
        yield sse({"done": True, "text": reply, "timing": stats})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _qa_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _qa_path(conversation_id: str) -> Path:
    """Resolve a conversation id without allowing path traversal."""
    value = str(conversation_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise HTTPException(400, "非法的问答会话 id")
    path = (QA_CONVERSATIONS_DIR / f"{value}.json").resolve()
    if path.parent != QA_CONVERSATIONS_DIR.resolve():
        raise HTTPException(400, "非法的问答会话 id")
    return path


def _qa_title(value: str | None, fallback: str = "新建问答") -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return (text[:42] or fallback).strip()


def _qa_normalize(data: dict, conversation_id: str) -> dict:
    now = _qa_now()
    messages = []
    for message in data.get("messages") or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = str(message.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        item = {"role": role, "content": content[:12000]}
        if role == "assistant" and isinstance(message.get("sources"), list):
            item["sources"] = message["sources"]
        messages.append(item)
    created_at = str(data.get("created_at") or now)
    updated_at = str(data.get("updated_at") or created_at)
    return {
        "id": conversation_id,
        "title": _qa_title(data.get("title")),
        "created_at": created_at,
        "updated_at": updated_at,
        "messages": messages,
    }


def _qa_read(conversation_id: str) -> dict:
    path = _qa_path(conversation_id)
    if not path.exists():
        raise HTTPException(404, "问答会话不存在")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(404, "问答会话不存在或已损坏")
    if not isinstance(raw, dict):
        raise HTTPException(404, "问答会话不存在或已损坏")
    return _qa_normalize(raw, path.stem)


def _qa_write(conversation: dict) -> dict:
    conversation = _qa_normalize(conversation, conversation["id"])
    path = _qa_path(conversation["id"])
    tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(conversation, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return conversation


def _qa_metadata(conversation: dict) -> dict:
    messages = conversation.get("messages") or []
    return {
        "id": conversation["id"],
        "title": conversation.get("title") or "新建问答",
        "created_at": conversation.get("created_at", ""),
        "updated_at": conversation.get("updated_at", ""),
        "message_count": len(messages),
    }


def _qa_list() -> list[dict]:
    items = []
    with _qa_store_lock:
        for path in QA_CONVERSATIONS_DIR.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or not re.fullmatch(r"[0-9a-f]{32}", path.stem):
                    continue
                conversation = _qa_normalize(raw, path.stem)
                items.append(_qa_metadata(conversation))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                # 一个损坏的本地文件不应阻塞其他会话恢复。
                continue
    return sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True)


def _qa_create(title: str | None = None) -> dict:
    conversation = {
        "id": uuid.uuid4().hex,
        "title": _qa_title(title),
        "created_at": _qa_now(),
        "updated_at": _qa_now(),
        "messages": [],
    }
    with _qa_store_lock:
        return _qa_write(conversation)


@app.get("/api/qa/conversations")
def qa_conversation_list():
    return {"items": _qa_list()}


@app.post("/api/qa/conversations")
def qa_conversation_create(req: ConversationCreateReq | None = None):
    return _qa_metadata(_qa_create(req.title if req else None))


@app.get("/api/qa/conversations/{conversation_id}")
def qa_conversation_get(conversation_id: str):
    with _qa_store_lock:
        return _qa_read(conversation_id)


@app.delete("/api/qa/conversations/{conversation_id}")
def qa_conversation_delete(conversation_id: str):
    path = _qa_path(conversation_id)
    with _qa_store_lock:
        if not path.exists():
            raise HTTPException(404, "问答会话不存在")
        try:
            path.unlink()
        except OSError as exc:
            raise HTTPException(500, f"删除问答会话失败：{exc}")
    return {"ok": True, "id": path.stem}


def _sanitize_qa_reply(reply: str) -> str:
    """清掉偶尔混入的角色前缀或下一轮对话，不影响正常 Markdown。"""
    cleaned = (reply or "").strip()
    cleaned = re.sub(r"^\s*(?:assistant|面试教练)[ \t]*[:：][ \t]*", "", cleaned, flags=re.I)
    m = re.search(r"\n[ \t]*(?:user|assistant|system|候选人|面试官)[ \t]*[:：]", cleaned, flags=re.I)
    if m:
        cleaned = cleaned[:m.start()]
    return cleaned.strip()


def _qa_sources(items: list[dict]) -> list[dict]:
    """将检索条目的内部结构压成前端可展示的来源。"""
    out, seen = [], set()
    for item in items:
        key = item.get("source") or item.get("id")
        if key in seen:
            continue
        seen.add(key)
        urls = []
        for source_url in item.get("source_urls") or []:
            url = str(source_url.get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                continue
            urls.append({"url": url, "title": str(source_url.get("title") or "")[:200]})
        out.append({
            "id": item.get("id", ""),
            "title": key,
            "type": "题库" if item.get("space") == "bank" else "情报",
            "date": item.get("day", ""),
            "urls": urls,
        })
    return out


@app.post("/api/qa/ask/stream")
def qa_ask_stream(req: AskReq):
    """独立面试问答：按本地持久化会话检索并流式回答。"""
    request_started = time.perf_counter()
    ok, detail = llm.ready()
    if not ok:
        raise HTTPException(400, detail)
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    if len(question) > 2000:
        raise HTTPException(400, "问题太长了，请压缩到 2000 字以内")

    # 新客户端绑定持久化会话；旧客户端没有 id 时仍可用 history，并自动获得一个会话。
    with _qa_store_lock:
        if req.conversation_id:
            conversation = _qa_read(req.conversation_id)
        else:
            conversation = _qa_create()
        conversation_id = conversation["id"]
        stored_messages = conversation.get("messages", [])
        if req.conversation_id:
            source_messages = stored_messages
        else:
            source_messages = req.history or []
        context_messages = []
        for message in source_messages[-8:]:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = str(message.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                context_messages.append({"role": role, "content": content[:6000]})
        # 用户问题先落盘：即使模型超时/中断，刷新后也能看到问题并继续重试。
        if not stored_messages and conversation.get("title") == "新建问答":
            conversation["title"] = _qa_title(question)
        conversation["messages"] = stored_messages + [{"role": "user", "content": question}]
        conversation["updated_at"] = _qa_now()
        _qa_write(conversation)

    store = retrieval.load(DATA_DIR / "kb" / "compiled", DATA_DIR / "kb")
    items = retrieval.search_question(store, question, limit=8)
    context = retrieval.render_qa_context(items)
    system = prompts.build_qa_system(context)
    context_messages.append({"role": "user", "content": question})

    def sse(obj: dict) -> str:
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    timing, observe, snapshot = _stream_observer("qa", request_started)
    timing["retrieval_ms"] = int((time.perf_counter() - request_started) * 1000)

    def gen():
        pieces = []
        max_tokens = _env_int("QA_MAX_OUTPUT_TOKENS", 3200, 800, 8000)
        base_context_messages = list(context_messages)
        continuation_round = 0
        # 只有供应商明确返回“达到输出上限”时才续写，避免把半句答案直接落盘。
        # 续写控制消息只存在本次请求内，不会污染持久化会话。
        while True:
            try:
                request_messages = base_context_messages if continuation_round == 0 else (
                    base_context_messages + [
                        {"role": "assistant", "content": "".join(pieces)[-24000:]},
                        {
                            "role": "user",
                            "content": (
                                "请从你上一条回答被截断的位置继续写完。只输出尚未完成的后续内容，"
                                "不要重复已经写过的标题、段落或结论；如果已经完整结束，只回复“已完成”。"
                            ),
                        },
                    ]
                )
                for d in llm.chat_stream(
                    system, request_messages, max_tokens=max_tokens,
                    fast=False, cache_last=False, on_event=observe,
                ):
                    pieces.append(d)
                    yield sse({"d": d, "conversation_id": conversation_id})
            except Exception as e:
                stats = snapshot()
                logger.warning("qa stream failed request_id=%s timing=%s", stats["request_id"], stats)
                yield sse({"err": f"LLM 调用失败：{e}", "timing": stats, "conversation_id": conversation_id})
                return

            if timing.get("truncated") and continuation_round < 2:
                continuation_round += 1
                timing["continuations"] = continuation_round
                continue
            break

        answer = _sanitize_qa_reply("".join(pieces))
        # 续写模型若按控制提示只返回“已完成”，它不是答案正文。
        if continuation_round:
            answer = re.sub(r"已完成[。.!！]?\s*$", "", answer).strip()
        if not answer:
            stats = snapshot()
            logger.warning("qa stream empty request_id=%s timing=%s", stats["request_id"], stats)
            yield sse({"err": "模型没有生成有效回答，请重试一次。", "timing": stats, "conversation_id": conversation_id})
            return
        with _qa_store_lock:
            saved = _qa_read(conversation_id)
            saved["messages"].append({
                "role": "assistant",
                "content": answer,
                "sources": _qa_sources(items),
            })
            saved["updated_at"] = _qa_now()
            _qa_write(saved)
        stats = snapshot()
        logger.info("qa stream done request_id=%s timing=%s", stats["request_id"], stats)
        yield sse({
            "done": True,
            "text": answer,
            "sources": _qa_sources(items),
            "timing": stats,
            "truncated": bool(stats.get("truncated")),
            "conversation_id": conversation_id,
        })

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/session/{sid}/end")
def end_session(sid: str):
    s = _sessions.get(sid)
    if not s:
        raise HTTPException(404, "会话不存在或已结束")
    transcript = "\n\n".join(
        f"{'面试官' if m['role'] == 'assistant' else '候选人'}：{m['content']}"
        for m in s["messages"]
    )
    system = prompts.build_evaluator_system(s.get("resume", ""), s.get("level", "应届校招"))
    user_msg = (
        f"面试轮次：{s['round']}（{s['style']}风格），候选人身份："
        f"{s.get('level', '应届校招')}，开始时间 {s['started_at']}。\n"
        f"以下是完整面试记录：\n\n{transcript}\n\n"
        # 收束指令放在 transcript「之后」：模型最近的上下文全是对白，指令只写在开头的话
        # 它会顺着记录继续往下演面试——实测就是这么坏的，报告位置被写满了新编的问答。
        "——面试记录到此结束，面试已经结束了。\n\n"
        "现在停止扮演面试官，切换成复盘输出。直接从「# 模拟面试复盘」这一行开始写 Markdown，"
        "严格按评分细则第三节的模板，必须包含「## 总分：XX / 100」和「## 最高优先级的 3 条改进」。"
        "不要再生成任何一句面试官或候选人的对白——引用原话只能出现在「关键扣分点」里，且要加引号。"
    )
    try:
        # 复盘正文一万多字足够，但推理模型的 reasoning 也从这个额度里扣——留出余量，
        # 否则思考花光了就只剩空正文。max_tokens 是上限不是目标，放宽不影响短报告的速度。
        report = llm.chat(system, [{"role": "user", "content": user_msg}], max_tokens=16000)
    except Exception as e:
        raise HTTPException(502, f"LLM 调用失败：{e}")

    report = _sanitize_report(report)
    if not _report_is_complete(report):
        # 会话故意不销毁：报告是一次性产物，存了残次品就再也生不出来了。
        # 保留现场让用户换个模型再点一次结束。
        raise HTTPException(
            502,
            "模型没生成出完整的复盘（多半是推理额度被思考吃光，或中转站截断了）。"
            "对话记录还在，换个模型再点一次「结束并复盘」即可。",
        )

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    out = SESSIONS_DIR / f"{stamp}-{s['round']}.md"
    out.write_text(
        f"# 模拟面试记录 {stamp} · {s['round']}（{s['style']}风格）\n\n"
        f"## 复盘报告\n\n{report}\n\n---\n\n## 对话全文\n\n{transcript}\n",
        encoding="utf-8",
    )
    archive = {k: v for k, v in s.items() if k != "resume"}
    archive["resume_used"] = bool(s.get("resume"))
    (SESSIONS_DIR / f"{stamp}-{s['round']}.json").write_text(
        json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    del _sessions[sid]
    return {"report": report, "saved_to": str(out)}


# ---- 历史记录：每场面完的复盘都在 sessions/，别浪费 ----

@app.get("/api/history")
def history_list():
    items = []
    for j in sorted(SESSIONS_DIR.glob("*.json"), reverse=True):
        try:
            meta = json.loads(j.read_text(encoding="utf-8"))
        except Exception:
            continue
        score = ""
        md = j.with_suffix(".md")
        if md.exists():
            m = re.search(r"总分[^\d\n]{0,10}(\d{1,3})", md.read_text(encoding="utf-8")[:6000])
            if m:
                score = m.group(1)
        items.append({
            "id": j.stem,
            "round": meta.get("round", ""),
            "style": meta.get("style", ""),
            "level": meta.get("level", ""),
            "started_at": meta.get("started_at", ""),
            "questions": sum(1 for x in meta.get("messages", []) if x.get("role") == "assistant"),
            "score": score,
            "resume_used": bool(meta.get("resume_used")),
        })
    return {"items": items}


def _history_path(hid: str, suffix: str) -> Path:
    if "/" in hid or "\\" in hid or ".." in hid:
        raise HTTPException(400, "非法的记录 id")
    return SESSIONS_DIR / f"{hid}{suffix}"


@app.get("/api/history/{hid}")
def history_get(hid: str):
    md = _history_path(hid, ".md")
    if not md.exists():
        raise HTTPException(404, "记录不存在")
    return {"id": hid, "md": md.read_text(encoding="utf-8")}


@app.delete("/api/history/{hid}")
def history_delete(hid: str):
    _history_path(hid, ".md").unlink(missing_ok=True)
    _history_path(hid, ".json").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/kb")
def kb_state():
    return kb_mgr.state()


@app.get("/api/kb/latest")
def kb_latest():
    """最新一节增量情报，前端「查看情报」用。"""
    return kb_mgr.latest_section()


@app.post("/api/kb/refresh")
def kb_refresh():
    """应用内跑每日更新：用配置的 LLM 联网搜索近 3 天新面经并写入知识库。"""
    ok, detail = llm.ready()
    if not ok:
        raise HTTPException(400, detail)
    try:
        result = kb_mgr.daily_research(llm)
    except Exception as e:
        raise HTTPException(502, f"每日更新失败：{e}")
    return {**result, "kb": kb_mgr.state()}


@app.post("/api/kb/import")
async def kb_import(file: UploadFile):
    """导入日更面经文档：原文落 kb/raw/，编译产物落 kb/compiled/，再重建 UPDATES.md。"""
    ok, detail = llm.ready()
    if not ok:
        raise HTTPException(400, detail)
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件太大（上限 20MB）")
    name = (file.filename or "").lower()
    if not name.endswith((".md", ".markdown", ".txt")):
        raise HTTPException(400, "请导入 Markdown / TXT 格式的日更文档")
    text = ""
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text.strip():
        raise HTTPException(400, "文件内容为空或编码无法识别")
    try:
        result = kb_mgr.import_daily(llm, file.filename or "daily.md", text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"蒸馏失败：{e}")
    return {**result, "kb": kb_mgr.state()}


class RecompileReq(BaseModel):
    slugs: list[str] | None = None      # 留空 = 全量重编译


@app.post("/api/kb/recompile")
def kb_recompile(req: RecompileReq | None = None):
    """按当前 schema 与编译提示词，把 kb/raw/ 里的原文重新编译一遍。
    改了契约、换了模型、或者某次编译当时失败，都从这里重放——不用让用户再上传一次。"""
    ok, detail = llm.ready()
    if not ok:
        raise HTTPException(400, detail)
    try:
        result = kb_mgr.recompile(llm, (req.slugs if req else None) or None)
    except Exception as e:
        raise HTTPException(502, f"重编译失败：{e}")
    if result["failed"] and not result["ok"]:
        raise HTTPException(502, "重编译全部失败：" + "；".join(
            f"{r['slug']} → {r['error']}" for r in result["failed"][:3]
        ))
    return {**result, "kb": kb_mgr.state()}


@app.post("/api/resume")
async def upload_resume(file: UploadFile):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件太大（上限 10MB）")
    try:
        text = resume_mod.extract(file.filename or "", data)
    except Exception as e:
        raise HTTPException(400, str(e))
    if len(text) < 50:
        raise HTTPException(400, "提取到的文字太少，请确认简历内容或换个格式")
    RESUME_PATH.write_text(text, encoding="utf-8")
    RESUME_META.write_text(
        json.dumps(
            {"filename": file.filename, "uploaded_at": datetime.now().isoformat(timespec="seconds")},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return _resume_state()


@app.delete("/api/resume")
def delete_resume():
    RESUME_PATH.unlink(missing_ok=True)
    RESUME_META.unlink(missing_ok=True)
    return {"loaded": False}


STYLE_TONE = {
    "字节": "冷静、克制、语速偏快的男性技术面试官，语气专业带一点审视和压迫感，不热情，句尾干脆利落。",
    "美团": "务实、平稳的男性技术面试官，语气像在讨论具体业务问题，偶尔加快追问节奏。",
    "阿里/蚂蚁": "沉稳、有架构师气场的男性面试官，语速中等，语气笃定，关注体系和格局。",
    "腾讯": "温和但严谨的男性技术面试官，语速平缓，像在做技术交流，但问题本身很锋利。",
    "京东": "朴实直接的男性技术面试官，语速稍慢，问题一板一眼，注重基础。",
}

# Edge 免费云音没有语气指令，用韵律逼近各厂风格（rate/pitch 与前端本地通路同一套手感）
STYLE_PROSODY = {
    "字节": ("+12%", "-6Hz"),
    "美团": ("+6%", "-3Hz"),
    "阿里/蚂蚁": ("+0%", "-5Hz"),
    "腾讯": ("+0%", "+0Hz"),
    "京东": ("-4%", "-1Hz"),
}
EDGE_DEFAULT_VOICE = "zh-CN-YunxiNeural"  # 云希：年轻男声；云健/云扬更低沉


class TTSReq(BaseModel):
    text: str
    style: str = "字节"


def _tts_openai(text: str, style: str) -> bytes:
    key = os.getenv("TTS_API_KEY") or os.getenv("OPENAI_API_KEY")
    from openai import OpenAI

    client = OpenAI(api_key=key,
                    base_url=os.getenv("TTS_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None)
    model = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.getenv("TTS_VOICE", "onyx")
    kwargs = dict(model=model, voice=voice, input=text, response_format="mp3")
    if "4o-mini-tts" in model:  # 仅该系列支持语气指令
        kwargs["instructions"] = STYLE_TONE.get(style, STYLE_TONE["字节"])
    resp = client.audio.speech.create(**kwargs)
    return resp.content if hasattr(resp, "content") else resp.read()


async def _tts_edge(text: str, style: str) -> bytes:
    import edge_tts

    voice = os.getenv("TTS_VOICE", "")
    if "Neural" not in voice:  # onyx 等 OpenAI 音色名对 Edge 无意义，换默认男声
        voice = EDGE_DEFAULT_VOICE
    rate, pitch = STYLE_PROSODY.get(style, ("+4%", "-3Hz"))
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    buf = b""
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf += chunk["data"]
    if not buf:
        raise RuntimeError("edge-tts 返回空音频")
    return buf


@app.post("/api/tts")
async def tts(req: TTSReq):
    """面试官语音合成，三级通路：配了 key 走 OpenAI 兼容 /audio/speech；
    没配走微软 Edge 免费云音（云希男声）；两者都失败前端再降级系统本地语音。"""
    import asyncio

    text = req.text[:600]
    has_key = bool(os.getenv("TTS_API_KEY") or os.getenv("OPENAI_API_KEY"))
    try:
        if has_key:
            audio = await asyncio.to_thread(_tts_openai, text, req.style)
        else:
            audio = await _tts_edge(text, req.style)
    except Exception as e:
        if has_key:  # 付费通路挂了再试免费云音，别直接砸到机器人音
            try:
                audio = await _tts_edge(text, req.style)
            except Exception:
                raise HTTPException(502, f"语音合成失败：{e}")
        else:
            raise HTTPException(502, f"语音合成失败：{e}")
    return Response(content=audio, media_type="audio/mpeg")


# ---- 配置自检：设置界面的「保存并测试」按钮 ----

@app.post("/api/test/llm")
def test_llm():
    """对话模型连通性：发一句话，要一句话。"""
    ok, detail = llm.ready()
    if not ok:
        return {"ok": False, "error": detail}
    t0 = time.time()
    try:
        reply = llm.chat(
            "你是技术面试官。",
            [{"role": "user", "content": "配置连通性测试：用一句话确认你已就绪，15 字以内。"}],
            max_tokens=2048,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}
    return {"ok": True, "reply": reply.strip()[:80], "ms": int((time.time() - t0) * 1000),
            "detail": detail}


@app.post("/api/test/stt")
async def test_stt():
    """转写链路自检：用 Edge 云音合成一句已知台词，喂给配置的转写接口，比对能否识别。
    不用麦克风，全自动。"""
    stt_key = os.getenv("STT_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not stt_key:
        return {"ok": False, "error": "还没填转写 Key（或 OpenAI Key）"}
    try:
        sample = await _tts_edge("模型测试，一二三。", "腾讯")
    except Exception as e:
        return {"ok": False, "error": f"生成测试音频失败（需要联网）：{e}"}
    from openai import OpenAI

    client = OpenAI(api_key=stt_key,
                    base_url=os.getenv("STT_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None)
    model = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe")
    kwargs = {}
    if any(t in model.lower() for t in ("whisper", "transcribe", "gpt")):
        kwargs["language"] = "zh"
    t0 = time.time()
    try:
        resp = client.audio.transcriptions.create(
            model=model, file=("test.mp3", sample, "audio/mpeg"), **kwargs
        )
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}
    text = (resp.text or "").strip()
    if not text:
        return {"ok": False, "error": "接口通了但没识别出内容，换个转写模型试试"}
    return {"ok": True, "heard": text[:60], "ms": int((time.time() - t0) * 1000), "model": model}


@app.post("/api/stt")
async def stt(file: UploadFile):
    """MediaRecorder 音频 -> OpenAI 转写 API（Electron 内 Web Speech API 不可用时的通路）。"""
    stt_key = os.getenv("STT_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not stt_key:
        raise HTTPException(400, "语音转写需要在 .env 配置 STT_API_KEY（或 OPENAI_API_KEY）")
    from openai import OpenAI

    data = await file.read()
    if len(data) < 800:
        return {"text": ""}
    client = OpenAI(api_key=stt_key,
                    base_url=os.getenv("STT_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None)
    model = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe")
    kwargs = {}
    # language 参数只有 OpenAI 系模型认；SenseVoice 等国产模型自动识别语种，传了反而可能 400
    if any(t in model.lower() for t in ("whisper", "transcribe", "gpt")):
        kwargs["language"] = "zh"
    try:
        resp = client.audio.transcriptions.create(
            model=model,
            file=(file.filename or "audio.webm", data, file.content_type or "audio/webm"),
            **kwargs,
        )
    except Exception as e:
        raise HTTPException(502, f"转写失败：{e}")
    return {"text": resp.text}


# ---- 静态前端 ----
FRONTEND = RES_DIR / "frontend"


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
