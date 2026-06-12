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
    opening = OPENING_RESUME.format(round=req.round) if resume_text else OPENING.format(round=req.round)
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
    system = prompts.build_interviewer_system(s["round"], s["style"], s.get("resume", ""), s.get("level", "应届校招"))
    # 一轮面试官的话按提示词要求不超过 120 字，代码题题面也就几百字。给 8192 等于
    # 递给模型一根足够长的绳子去自演整场对话——上限收紧本身就是最有效的一道闸。
    for _ in range(2):
        try:
            reply = llm.chat(system, s["messages"], max_tokens=1200, stop=LEAK_STOPS)
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
    """导入日更面经文档，用当前配置的 LLM 蒸馏为增量情报。"""
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

