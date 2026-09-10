"""知识库管理：原文落盘 → LLM 编译成受 schema 约束的结构化情报 → 渲染成 UPDATES.md。

三层分工，改一层不动另外两层：

  kb/raw/<slug>.md          原文。用户导入的日更文档，或联网检索回来的当日笔记。只存不解释。
  kb/compiled/<slug>.json   编译产物。落盘前必须通过 kb/schema/intel.schema.json，否则不落。
  kb/UPDATES.md             由 compiled/ 渲染拼装出来的视图。面试官提示词读的是它。

为什么要拆成三层：改之前 import 把几十万字原文喂给模型、只留下一段 3500 字散文，原文当场
丢弃。于是编译提示词一改、schema 一加字段，历史情报就永远回不来了，而"结构"只靠提示词里
一句"请按这个格式写"维持——模型偷懒少写一行，读取侧只会静默拿到空字符串。
现在原文是事实来源，编译是可重放的（/api/kb/recompile），UPDATES.md 是随时能重建的派生物，
schema 是重建时的验收标准。三者任一坏掉都能从上一层重新长出来。

读取侧（backend/prompts.py 的目录/正文分层注入）看到的仍然是同一份 Markdown，没有改动。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from . import schema as jschema

UPDATES_NAME = "UPDATES.md"
UPDATES_HEADER = "# 知识库增量情报（由 kb/compiled/ 渲染生成，面试官优先使用）\n"

RAW_DIR = "raw"
COMPILED_DIR = "compiled"
SCHEMA_DIR = "schema"
SCHEMA_NAME = "intel.schema.json"
COMPILE_RETRIES = 2          # 首次 + 2 次带错误清单的重试，仍不合契约就报错，不静默降级

# 注入预算。以前这个数字同时管三件事（存多少、去重回看多少、注入多少），现在只管后两件：
# 存多少归 compiled/ 管，那边不设上限——原文与产物是资产，删了就回不来。
# 之所以敢把 UPDATES.md 全量注入：提示词命中前缀缓存，实测 1.6 万 token 和 20 token 的延迟一样。
MAX_UPDATES_CHARS = 60000   # UPDATES.md 渲染上限（保新弃旧），约 20 天
# 注入提示词的「正文」只取最近这么多字符，更早的只在目录里留一行摘要。
# 不是怕撑爆窗口（跑满也才 ~71k tokens，对 1M 窗口是 7%），是怕稀释：
# 情报 55k 压着人格卡+题库 16k，面试官的注意力会被面经带偏。
INTEL_BODY_CHARS = 20000    # 约 7 天的全文
MAX_IMPORT_CHARS = 300000   # 单次喂给模型的原文上限
MAX_RAW_CHARS = 2000000     # 落盘保留的原文上限（比上面宽：留着给以后更强的模型重编译）

# ---- 联网搜索域名白名单（只写域名，不带 http/https；子域名自动包含）----
# 面经与技术社区
SEARCH_DOMAINS_CN = [
    "zhihu.com",          # 知乎
    "nowcoder.com",       # 牛客网
    "xiaohongshu.com",    # 小红书
    "v2ex.com",           # V2EX
    "juejin.cn",          # 掘金
    "csdn.net",           # CSDN
    "cnblogs.com",        # 博客园
    "segmentfault.com",   # 思否
    "jianshu.com",        # 简书
    "bilibili.com",       # B 站（面经视频/专栏）
    "mp.weixin.qq.com",   # 微信公众号文章
    # 行业动态
    "qbitai.com",         # 量子位
    "jiqizhixin.com",     # 机器之心
    "infoq.cn",           # InfoQ 中文
    "36kr.com",           # 36 氪
]

# 国外平台：暂不启用，保留备用（想开就并进 SEARCH_ALLOWED_DOMAINS）
SEARCH_DOMAINS_INTL = [
    "reddit.com",
    "news.ycombinator.com",
    "stackoverflow.com",
    "medium.com",
    "github.com",
    "arxiv.org",
]

# 实际生效的白名单：只搜中文平台
SEARCH_ALLOWED_DOMAINS = SEARCH_DOMAINS_CN

# ---------------- 编译器：任何原文 → 受 schema 约束的 JSON ----------------
# 导入的日更文档和联网检索回来的笔记走的是同一个编译器，只有采集方式不同。
# 字段骨架由 schema 反推（backend/schema.outline），提示词与契约不可能各说各话。
COMPILE_GUIDE = """你是模拟面试官的知识库编译器。用户给你一份原文（可能是「AI Agent 实习准备」日更文档，
也可能是情报官联网检索回来的当日笔记），你把其中对模拟面试官**当下出题有用的增量内容**抽成 JSON。

只抽这四类，对应四个数组；某一类原文里确实没有，就给空数组 []，不要编：
1. questions —— 新增面试题（题目 + 公司来源 + 频率 + 一句话答案要点）
2. scenarios —— 新场景设计题素材（面试官能拿来搭台子的业务场景：背景 + 量级数字 + 考察点）
3. events —— 行业新事件及其面试考点（事件一句话 + 面试官可以怎么问）
4. coding —— 新手撕题（题名 + 考察点，不要贴完整代码）

判断增量的标准：
- 忽略学习路线、资源清单、历史累积统计、风险提示这类与出题无关的部分
- 忽略原文里明显是往期已收录的内容（标了"保留""历史归档"的部分）
- 宁缺毋滥。只留面试官真能拿去问的，含糊到没法追问的条目直接丢
- 频率拿不准就填"偶尔"；公司来源原文没写就留空字符串，不要猜一个大厂填进去
- topic 填 3-5 个最有出题价值的关键词（公司名、技术点），会被渲染成情报目录里的那行摘要

输出硬性要求：
- **只输出一个 JSON 对象**，不要 ```json 代码块、不要任何解释文字
- 严格按下面的字段骨架，字段名一字不差，不要多加字段（多余字段会被判不合法并退回重做）
- 字符串里不要换行、不要 Markdown 标记（#、-、*），一条就是一句话
- 不要输出 meta 字段，那一节由程序填写

<字段骨架>
{outline}
</字段骨架>"""

# ---------------- 采集器：联网检索当日情报，产出的是「原文笔记」而不是最终产物 ----------------
# 故意不让它直接吐 JSON：带搜索工具的调用又慢又贵，它的产出理应落盘成 raw 原文，
# 之后的结构化交给便宜可重放的编译器。这样"重编译"对检索来的情报同样有效。
RESEARCH_SYSTEM = """你是模拟面试官的每日情报官。用 web_search 工具搜索**近 3 天**中文互联网上新出现的 AI Agent 开发方向面经与行业动态，产出一份给知识库编译用的检索笔记。

搜索范围已被限制在中文平台（知乎、牛客网、小红书、V2EX、掘金、CSDN、博客园、思否、简书、B站、微信公众号，以及量子位/机器之心/InfoQ中文/36氪），搜不到结果时换关键词，不要试图去英文站。

搜索策略（执行 4-8 次搜索）：
- "Agent 面经 牛客" / "AI Agent 面试 一面 二面"（加上当前月份）
- "大模型应用开发 面经"（知乎/掘金/CSDN）
- "AI Agent 面试" 小红书 / V2EX（求职、offer 讨论帖里常有一手面经）
- 大厂关键词轮换：字节/美团/阿里/腾讯/蚂蚁/京东/百度 + "Agent 面经"
- "AI Agent" 行业重大发布（近3天）

笔记格式（紧凑 Markdown，总量不超过 3000 字，分成这四节，没有的节写"无"）：
1. **新增面试题**：一行一题「题目 —— 公司｜频率（必考/高频/偶尔）｜答案要点一句话｜来源平台」
2. **新场景设计题素材**：可搭台子的业务场景（背景 + 量级数字 + 考察点）
3. **行业新事件及面试考点**：事件一句话 + 可以怎么问
4. **新手撕题**：题名 + 考察点

硬性要求：
- 用户会提供已收录情报的清单，**只输出未收录的新内容**，重复的丢弃
- 每条注明来源平台；搜索结果的发布时间不确定时标注"（时间待核）"
- 确实没有新内容就只输出一行：「今日无新增面经，行业无重大变化。」
- 不要开场白、不要总结、不要建议，正文直接开始"""


def site_stats(sources: list[dict]) -> list[dict]:
    """把引用到的网页按站点归并计数，多的排前面：[{"host": "zhihu.com", "count": 5}]。"""
    hosts = []
    for src in sources or []:
        host = urlparse(src.get("url", "")).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            continue
        # 子域名归并到白名单里的主站，zhuanlan.zhihu.com 和 zhihu.com 算一家
        hosts.append(next(
            (d for d in SEARCH_ALLOWED_DOMAINS if host == d or host.endswith("." + d)),
            host,
        ))
    return [{"host": h, "count": n} for h, n in Counter(hosts).most_common()]


# ---------------- JSON 提取：模型总有那么几次要包代码块或者带一句解释 ----------------
def extract_json(text: str) -> dict:
    """从模型回复里抠出第一个完整的 JSON 对象。按引号/转义状态数括号，
    不用正则——正文里带 { } 的字符串会把贪婪正则骗到天上去。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[A-Za-z]*\s*", "", s)
        s = re.sub(r"```\s*$", "", s).strip()
    start = s.find("{")
    if start < 0:
        raise ValueError("模型输出里找不到 JSON 对象")
    depth, in_str, esc, end = 0, False, False, -1
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        raise ValueError("JSON 对象没有闭合（多半是被 max_tokens 截断了）")
    try:
        doc = json.loads(s[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{e}") from e
    if not isinstance(doc, dict):
        raise ValueError("顶层不是 JSON 对象")
    return doc


# ---------------- 渲染：编译产物 → UPDATES.md 的一节 ----------------
# 这里的输出格式就是读取侧（prompts._intel_catalog / _intel_body）的契约，改动要一起改：
#   ## <小节标题>            ← 按 ^##  切节
#   （空行）
#   主题：关键词 / 关键词      ← 必须是正文第一个非空行，目录靠它取摘要
_RANGE_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)(?=\s*(?:倍|ms|s|秒|毫秒|万|亿|%|次|个|条|人|GB|MB|元|[)\]\uFF09\u3011,\uFF0C;\uFF1B]))"
)


def normalize_rendered_text(value) -> str:
    """Conservatively tidy text emitted into Markdown views.

    This intentionally runs on rendered strings only. It never changes raw notes or
    the structured compiled JSON, and it avoids broad punctuation rewrites that could
    alter code, URLs, model names, or factual content.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = _RANGE_RE.sub(r"\1~\2", text)
    text = re.sub(r"([\uFF08\u3010])\s+", r"\1", text)
    text = re.sub(r"\s+([\uFF09\u3011])", r"\1", text)
    text = re.sub(r"\s+([\uFF0C\u3002\uFF1B\uFF1A\uFF01\uFF1F\u3001])", r"\1", text)
    return text


def _flat(s) -> str:
    """压成单行并剥掉行首的 Markdown 结构符。正文里绝不能出现行首的 `## `，
    否则会被读取侧当成新的一节切开——把换行全压成空格就永远不会在行首。"""
    t = normalize_rendered_text(s)
    return t.lstrip("#-*>· ").strip()


def _fmt_question(x: dict) -> str:
    tail = "｜".join(p for p in (
        _flat(x.get("company")) or "来源未标",
        _flat(x.get("frequency")),
        _flat(x.get("answer_hint")),
    ) if p)
    plat = _flat(x.get("platform"))
    return f"{_flat(x.get('q'))} —— {tail}" + (f"｜见于 {plat}" if plat else "")


def _fmt_scenario(x: dict) -> str:
    bits = []
    for key, label in (("background", "背景"), ("scale", "量级"), ("focus", "考察")):
        value = _flat(x.get(key))
        if value:
            bits.append(f"{label}：{value}")
    title = _flat(x.get("title")) or "未命名场景"
    return f"{title}（{'；'.join(bits)}）" if bits else title


def _fmt_event(x: dict) -> str:
    event = _flat(x.get("event")) or "未命名事件"
    ask = _flat(x.get("ask"))
    return f"{event} —— 可以这么问：{ask}" if ask else event


def _fmt_coding(x: dict) -> str:
    diff = _flat(x.get("difficulty"))
    head = f"{_flat(x.get('title'))}（{diff}）" if diff else (_flat(x.get("title")) or "未命名手撕题")
    focus = _flat(x.get("focus"))
    return f"{head} —— 考察：{focus}" if focus else head


CATEGORIES = (
    ("questions", "新增面试题", _fmt_question),
    ("scenarios", "新场景设计题素材", _fmt_scenario),
    ("events", "行业新事件及面试考点", _fmt_event),
    ("coding", "新手撕题", _fmt_coding),
)


def counts(artifact: dict) -> dict:
    return {key: len(artifact.get(key) or []) for key, _label, _fmt in CATEGORIES}


def render_body(artifact: dict) -> str:
    """一节的正文（不含 `## 标题` 那行）。第一行必须是「主题：」。"""
    topics = [_flat(t) for t in (artifact.get("topic") or [])]
    line = " / ".join(t for t in topics if t) or "无新增"
    out = [f"主题：{line}", ""]
    for key, label, fmt in CATEGORIES:
        items = [x for x in (artifact.get(key) or []) if isinstance(x, dict)]
        if not items:
            continue
        out.append(f"**{label}**")
        out += [f"- {fmt(x)}" for x in items]
        out.append("")
    if (artifact.get("meta") or {}).get("no_news"):
        out += ["今日无新增面经，行业无重大变化。", ""]
    return "\n".join(out).rstrip() + "\n"


def render_section(artifact: dict) -> str:
    meta = artifact.get("meta") or {}
    title = _flat(meta.get("section_title") or meta.get("source") or "增量情报")
    return f"## {title}\n\n{render_body(artifact)}"


def _slug(name: str, prefix: str) -> str:
    """文件名 → 稳定的 slug。同一个来源重复导入落到同一个 slug，天然覆盖旧的，
    不用再靠"标题里含 来自 xxx"这种字符串匹配去删旧节。"""
    stem = Path(str(name or "")).stem or "daily"
    stem = re.sub(r"[^0-9A-Za-z一-鿿._-]+", "-", stem).strip("-._")[:60]
    return f"{prefix}__{stem or 'daily'}"


def _sources_appendix(sources: list[dict]) -> str:
    """把检索到的链接附在 raw 笔记末尾，让原文自身可溯源、可复查。"""
    if not sources:
        return ""
    lines = ["", "<!-- 以下由程序追加：本次检索实际引用到的网页 -->", "## 检索来源"]
    for s in sources:
        title = _flat(s.get("title")) or "（无标题）"
        lines.append(f"- {title} — {(s.get('url') or '').strip()}")
    return "\n".join(lines) + "\n"


class KBManager:
    def __init__(self, res_kb: Path, data_kb: Path):
        self.res_kb = res_kb
        self.data_kb = data_kb
        self._schema: dict | None = None
        self._compile_sys: str = ""
        self._write_lock = threading.RLock()

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    # ---------------- 目录与播种 ----------------
    @property
    def raw_dir(self) -> Path:
        return self.data_kb / RAW_DIR

    @property
    def compiled_dir(self) -> Path:
        return self.data_kb / COMPILED_DIR

    @property
    def schema_path(self) -> Path:
        return self.data_kb / SCHEMA_DIR / SCHEMA_NAME

    def seed(self) -> None:
        """把安装包里的只读 kb 播种到可写目录。人格卡/题库只补缺失的，不覆盖用户改过的；
        schema 是代码而不是用户数据，每次启动都用安装包里的版本盖掉，免得升级后契约还是旧的。

        安装包里带着的情报语料（raw 原文 + compiled 产物）同样只补缺失的：新机器装上就有历史
        情报可用，而且因为原文一起带过来了，换 schema 或换模型之后还能在本机重编译。"""
        for d in (self.data_kb, self.raw_dir, self.compiled_dir, self.data_kb / SCHEMA_DIR):
            d.mkdir(parents=True, exist_ok=True)
        if not self.res_kb.exists() or self.res_kb.resolve() == self.data_kb.resolve():
            return
        for f in self.res_kb.glob("*.md"):
            target = self.data_kb / f.name
            if not target.exists():
                shutil.copy2(f, target)
        for sub in (RAW_DIR, COMPILED_DIR):
            src = self.res_kb / sub
            if not src.is_dir():
                continue
            for f in src.iterdir():
                target = self.data_kb / sub / f.name
                if f.is_file() and not target.exists():
                    shutil.copy2(f, target)
        packaged = self.res_kb / SCHEMA_DIR / SCHEMA_NAME
        if packaged.exists():
            shutil.copy2(packaged, self.schema_path)

    def schema(self) -> dict:
        if self._schema is None:
            if not self.schema_path.exists():
                raise FileNotFoundError(
                    f"结构契约缺失：{self.schema_path}。"
                    f"从源码 kb/{SCHEMA_DIR}/{SCHEMA_NAME} 复制一份，或重装应用。"
                )
            self._schema = jschema.load(self.schema_path)
        return self._schema

    def compile_system(self) -> str:
        """编译器的 system 提示词：字段骨架从 schema 反推，所以契约改了提示词自动跟着改。
        缓存住是为了字节稳定——每轮都重新拼一遍字典序不保证一致，前缀缓存就白瞎了。"""
        if not self._compile_sys:
            outline = jschema.outline(self.schema(), skip=("meta",))
            self._compile_sys = COMPILE_GUIDE.format(outline=outline)
        return self._compile_sys

    # ---------------- 产物读写 ----------------
    def _compiled_path(self, slug: str) -> Path:
        return self.compiled_dir / f"{slug}.json"

    def _read_compiled(self, slug: str) -> dict | None:
        p = self._compiled_path(slug)
        if not p.exists():
            return None
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return doc if isinstance(doc, dict) else None

    def _write_compiled(self, slug: str, artifact: dict) -> Path:
        p = self._compiled_path(slug)
        self._atomic_write_text(
            p, json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
        )
        return p

    def all_compiled(self) -> list[dict]:
        """全部编译产物，按编译时间倒序（新的在前）。坏文件跳过——
        一份手改坏的 JSON 不该让整个提示词组装失败。"""
        arts = []
        for f in self.compiled_dir.glob("*.json"):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(doc, dict) and isinstance(doc.get("meta"), dict):
                arts.append(doc)
        arts.sort(key=lambda a: str(a["meta"].get("compiled_at") or ""), reverse=True)
        return arts

    def _legacy_sections(self, owned: set[str]) -> list[str]:
        """重构之前由旧代码直接写进 UPDATES.md、没有对应 compiled 产物的老节。
        原样留着（已经没有原文可重编译了），随渲染预算自然老化淘汰。

        只认标题以日期开头的节：旧版蒸馏产物的正文里带着「## 新增面试题」这类内部小标题，
        按 ^## 一切就会被误当成独立的节。它们不是节，是上一节的身体，不能作为"老节"再生一遍。"""
        p = self.data_kb / UPDATES_NAME
        if not p.exists():
            return []
        out = []
        for part in re.split(r"^## ", p.read_text(encoding="utf-8"), flags=re.M)[1:]:
            title = part.partition("\n")[0].strip()
            if title and title not in owned and re.match(r"\d{4}-\d{2}-\d{2}", title):
                out.append("## " + part.rstrip() + "\n")
        return out

    def assemble(self) -> int:
        """从 compiled/ 重建 UPDATES.md。新的在前，超出渲染预算的旧节不写进去
        （产物本身留着，换个更大的预算或删几份旧产物就又回来了）。返回文件字符数。"""
        rendered = [render_section(a) for a in self.all_compiled()]
        owned = {s.partition("\n")[0][3:].strip() for s in rendered}
        merged = UPDATES_HEADER
        for sec in rendered + self._legacy_sections(owned):
            if len(merged) + len(sec) + 1 > MAX_UPDATES_CHARS:
                break
            merged += "\n" + sec
        self._atomic_write_text(self.data_kb / UPDATES_NAME, merged)
        return len(merged)

    # ---------------- 编译（带校验与重试） ----------------
    def _compile(self, llm, raw_text: str, meta: dict) -> dict:
        """原文 → 校验通过的产物。不合契约就把错误清单喂回去重做，重试用尽则抛错。
        绝不返回半成品：以前"格式不对"的下场是读取侧静默拿到空摘要，坏得无声无息。"""
        sysmsg = self.compile_system()
        msgs = [{"role": "user", "content":
                 f"来源：{meta.get('source')}（{meta.get('kind')}）\n\n"
                 f"<原文>\n{raw_text[:MAX_IMPORT_CHARS]}\n</原文>"}]
        errs = ["模型没有返回任何内容"]
        for attempt in range(COMPILE_RETRIES + 1):
            reply = llm.chat(sysmsg, msgs, max_tokens=8192, fast=True)
            try:
                doc = extract_json(reply)
            except ValueError as e:
                errs = [str(e)]
            else:
                doc.pop("meta", None)          # meta 归程序填，模型顺手写的一律丢掉
                artifact = {"meta": meta, **doc}
                errs = jschema.validate(artifact, self.schema())
                if not errs:
                    return artifact
            if attempt < COMPILE_RETRIES:
                msgs = msgs + [
                    {"role": "assistant", "content": reply[-4000:]},
                    {"role": "user", "content":
                     "上一次输出没通过结构校验：\n- " + "\n- ".join(errs[:12])
                     + "\n\n照字段骨架改好，只输出修正后的完整 JSON，不要解释。"},
                ]
        raise ValueError(
            f"编译产物连续 {COMPILE_RETRIES + 1} 次不符合 {SCHEMA_NAME}："
            + "；".join(errs[:6])
            + f"。原文已存在 {RAW_DIR}/{meta.get('raw_file', '')}，"
            "换个模型或改完提示词点「重编译」可以重放，不用重新上传。"
        )

    @staticmethod
    def _model_tag(llm) -> str:
        cfg = getattr(llm, "cfg", None)
        return f"{getattr(cfg, 'provider', '?')}/{getattr(cfg, 'model', '?')}"[:120]

    def _result(self, artifact: dict, extra: dict | None = None) -> dict:
        """写入后的统一返回体。前端认的是 section / summary / distilled_chars 这三个键，
        新增的键只是加料，老字段一个都不动。"""
        meta = artifact.get("meta") or {}
        body = render_body(artifact)
        return {
            "section": meta.get("section_title", ""),
            "summary": body,
            "distilled_chars": len(body),
            "chars": len(body),
            "items": counts(artifact),
            "slug": meta.get("slug", ""),
            "raw_file": meta.get("raw_file", ""),
            "compiled_file": f"{meta.get('slug', '')}.json",
            "updates_chars": self.assemble(),
            **(extra or {}),
        }

    # ---------------- 入口一：导入日更文档 ----------------
    def import_daily(self, llm, filename: str, text: str) -> dict:
        """原文落盘 → 编译 → 校验 → 重建 UPDATES.md。同一个文件名重复导入覆盖旧产物。"""
        with self._write_lock:
            return self._import_daily(llm, filename, text)

    def _import_daily(self, llm, filename: str, text: str) -> dict:
        slug = _slug(filename, "import")
        raw_name = f"{slug}.md"
        text = (text or "")[:MAX_RAW_CHARS]
        self._atomic_write_text(self.raw_dir / raw_name, text)

        now = datetime.now()
        meta = {
            "kind": "import",
            "source": filename or "daily.md",
            "slug": slug,
            "raw_file": raw_name,
            "raw_chars": len(text),
            "compiled_at": now.isoformat(timespec="seconds"),
            "section_title": f"{now.strftime('%Y-%m-%d %H:%M')} · 来自 {filename}",
            "model": self._model_tag(llm),
        }
        artifact = self._compile(llm, text, meta)
        if not any(counts(artifact).values()):
            raise ValueError(
                "这份文档里没有可用的增量内容（四类全空），没有写入知识库。"
                f"原文已存在 {RAW_DIR}/{raw_name}，需要的话可以改完提示词再重编译。"
            )
        self._write_compiled(slug, artifact)
        return self._result(artifact)

    # ---------------- 入口二：联网检索当日情报 ----------------
    def daily_research(self, llm) -> dict:
        """采集（带搜索工具，贵）→ 笔记落盘 → 编译（便宜可重放）→ 校验 → 重建 UPDATES.md。"""
        with self._write_lock:
            return self._daily_research(llm)

    def _daily_research(self, llm) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        slug = f"research__{today}"
        raw_name = f"{slug}.md"
        existing = self.latest_intel()      # 全量回看，跟注入窗口一致，才不会重复收录
        prompt = (
            f"今天是 {today}。以下是知识库已收录的情报（用于去重，别再输出这些）：\n\n"
            f"<已收录>\n{existing or '（暂无）'}\n</已收录>\n\n"
            "现在开始搜索并输出新增情报笔记。"
        )
        res = llm.research(
            RESEARCH_SYSTEM, prompt, max_tokens=8192,
            allowed_domains=SEARCH_ALLOWED_DOMAINS,
        )
        notes = (res.text or "").strip()
        if not notes:
            raise ValueError("情报搜集返回为空，请稍后重试")

        self._atomic_write_text(
            self.raw_dir / raw_name, notes + _sources_appendix(res.sources or [])
        )

        no_news = "今日无新增" in notes and len(notes) < 200
        meta = {
            "kind": "research",
            "source": "每日自动更新",
            "slug": slug,
            "raw_file": raw_name,
            "raw_chars": len(notes),
            "compiled_at": datetime.now().isoformat(timespec="seconds"),
            "section_title": f"{today} · 每日自动更新",
            "model": self._model_tag(llm),
            "sources": [
                {"url": (s.get("url") or "")[:600], "title": (s.get("title") or "")[:300]}
                for s in (res.sources or [])[:40]
            ],
        }
        if no_news:
            # 空手而归也照样落一份合契约的产物：面试官读到"今日无新增"胜过读到昨天的当新的，
            # 前端的 kbStale 也才能看出今天已经跑过了。这一步不必再花一次编译调用。
            artifact = {
                "meta": {**meta, "no_news": True},
                "topic": ["无新增"], "questions": [], "scenarios": [], "events": [], "coding": [],
            }
            errs = jschema.validate(artifact, self.schema())
            if errs:
                raise ValueError("「无新增」产物都不合契约，schema 或代码有问题：" + "；".join(errs[:5]))
        else:
            artifact = self._compile(llm, notes, meta)

        self._write_compiled(slug, artifact)
        return self._result(artifact, {
            "no_news": no_news,
            "sites": site_stats(res.sources),     # 命中的站点及次数
            "sources": (res.sources or [])[:40],  # 具体链接，供展开查看
        })

    # ---------------- 入口三：重编译（raw/ 是事实来源，这条路才是留原文的意义） ----------------
    def _meta_for(self, raw_path: Path, text: str, prev: dict | None, llm) -> dict:
        """重编译时的 meta：能从旧产物继承的一律继承（尤其是 compiled_at，它是 UPDATES.md
        的排序键，重编译不该把三个月前的情报顶到最前面），只有模型和重编译时间是新的。"""
        slug = raw_path.stem
        kind = "research" if slug.startswith("research__") else "import"
        tag = slug.split("__", 1)[-1]
        pm = (prev or {}).get("meta") if isinstance(prev, dict) else None
        pm = pm if isinstance(pm, dict) else {}
        mtime = datetime.fromtimestamp(raw_path.stat().st_mtime)
        source = pm.get("source") or ("每日自动更新" if kind == "research" else f"{tag}.md")
        meta = {
            "kind": kind,
            "source": source,
            "slug": slug,
            "raw_file": raw_path.name,
            "raw_chars": len(text),
            "compiled_at": pm.get("compiled_at") or mtime.isoformat(timespec="seconds"),
            "recompiled_at": datetime.now().isoformat(timespec="seconds"),
            "section_title": pm.get("section_title") or (
                f"{tag} · 每日自动更新" if kind == "research"
                else f"{mtime.strftime('%Y-%m-%d %H:%M')} · 来自 {source}"
            ),
            "model": self._model_tag(llm),
        }
        if pm.get("sources"):
            meta["sources"] = pm["sources"]    # 网页内容没法重放，来源清单从旧产物继承
        return meta

    def _no_news_artifact(self, meta: dict) -> dict:
        return {
            "meta": {**meta, "no_news": True},
            "topic": ["无新增"], "questions": [], "scenarios": [], "events": [], "coding": [],
        }

    def recompile(self, llm, slugs: list[str] | None = None) -> dict:
        """把 raw/ 里的原文按当前 schema 与编译提示词重跑一遍，逐份替换 compiled/，最后重建
        UPDATES.md。单份失败不影响其它份——失败清单照实返回，原文还在，随时能再来一次。"""
        with self._write_lock:
            return self._recompile(llm, slugs)

    def _recompile(self, llm, slugs: list[str] | None = None) -> dict:
        targets = sorted(self.raw_dir.glob("*.md"))
        if slugs:
            want = set(slugs)
            targets = [p for p in targets if p.stem in want]
        if not targets:
            raise ValueError(
                f"{RAW_DIR}/ 里没有可重编译的原文。先导入一份日更文档，或跑一次每日更新。"
            )
        ok, failed = [], []
        for p in targets:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                prev = self._read_compiled(p.stem)
                meta = self._meta_for(p, text, prev, llm)
                stale_empty = bool(((prev or {}).get("meta") or {}).get("no_news"))
                if stale_empty or ("今日无新增" in text and len(text) < 400):
                    artifact = self._no_news_artifact(meta)
                else:
                    artifact = self._compile(llm, text, meta)
                self._write_compiled(p.stem, artifact)
                ok.append({"slug": p.stem, "section": meta["section_title"],
                           "items": counts(artifact)})
            except Exception as e:                       # noqa: BLE001 逐份隔离，一份坏不拖累全局
                failed.append({"slug": p.stem, "error": str(e)[:400]})
        chars = self.assemble()
        lines = [f"共 {len(targets)} 份原文：成功 **{len(ok)}**，失败 **{len(failed)}**，"
                 f"UPDATES.md 重建为 {chars} 字符。", ""]
        for r in ok:
            it = r["items"]
            lines.append(f"- ✅ {r['section']} —— 题 {it['questions']}／场景 {it['scenarios']}"
                         f"／事件 {it['events']}／手撕 {it['coding']}")
        for r in failed:
            lines.append(f"- ❌ {r['slug']}：{r['error']}")
        return {
            "total": len(targets), "ok": ok, "failed": failed,
            "updates_chars": chars,
            "section": f"重编译 {len(ok)}/{len(targets)} 份",
            "summary": "\n".join(lines),
        }

    # ---------------- 状态与读取（读取侧接口一字未改） ----------------
    def state(self) -> dict:
        files = []
        for f in sorted(self.data_kb.glob("*.md")):
            files.append({
                "name": f.name,
                "chars": len(f.read_text(encoding="utf-8", errors="ignore")),
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
            })
        updates = self.data_kb / UPDATES_NAME
        latest = ""
        if updates.exists():
            m = re.search(r"^## (.+)$", updates.read_text(encoding="utf-8"), re.M)
            latest = m.group(1) if m else ""
        arts = self.all_compiled()
        total: Counter = Counter()
        for a in arts:
            total.update(counts(a))
        return {
            "files": files,
            "latest_update": latest,
            "dir": str(self.data_kb),
            # 新增：三层流水线的现状。前端不认这些键也不影响原有渲染。
            "pipeline": {
                "raw": len(list(self.raw_dir.glob("*.md"))),
                "compiled": len(arts),
                "schema": SCHEMA_NAME if self.schema_path.exists() else "",
                "items": {key: total.get(key, 0) for key, _l, _f in CATEGORIES},
                "sections": [{
                    "slug": (a["meta"].get("slug") or ""),
                    "section": (a["meta"].get("section_title") or ""),
                    "kind": (a["meta"].get("kind") or ""),
                    "compiled_at": (a["meta"].get("compiled_at") or ""),
                    "items": counts(a),
                } for a in arts[:40]],
            },
        }

    def latest_section(self) -> dict:
        """最新一节增量情报（标题 + 正文），供「查看情报」随时翻出来。"""
        updates = self.data_kb / UPDATES_NAME
        if not updates.exists():
            return {"section": "", "summary": ""}
        parts = re.split(r"^## ", updates.read_text(encoding="utf-8"), flags=re.M)
        if len(parts) < 2:
            return {"section": "", "summary": ""}
        title, _, content = parts[1].partition("\n")   # parts[1] 就是最新一节
        return {"section": title.strip(), "summary": content.strip()}

    def latest_intel(self, cap: int = MAX_UPDATES_CHARS) -> str:
        """给面试官提示词用：最新在前的增量情报，截断到 cap。"""
        updates = self.data_kb / UPDATES_NAME
        if not updates.exists():
            return ""
        return updates.read_text(encoding="utf-8")[:cap]
