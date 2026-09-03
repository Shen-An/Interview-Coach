"""把人写的 Markdown 页面切成可检索条目。

kb/ 下的 .md 就是这个 wiki 的页面：人可读、可手改、git 管历史。这里只做一件事——
按标题层级把页面切成能单独寻址的条目，并把标题路径当成条目的分类留下来。

为什么是解析而不是喂给模型编译：题库是手写沉淀的资产，结构规整（`##` 分层、`###` 分小节、
一条一个 bullet），解析是精确、免费、离线、可重放的；编译要花钱、结果每次都可能漂，
还得留一份产物在磁盘上跟原文对账。情报那条路要编译，因为原文是散文；这条路不用。

切出来的东西不落盘：装载一次几毫秒，页面改了下次装载自然跟着变，也就没有"产物过期"
这种状态需要谁去记得失效。
"""
from __future__ import annotations

import re
from pathlib import Path

# 参与检索的页面。人格卡（判人标准）与评分标准（尺子）不在这里：那是指令不是素材，
# 每场面试整份都要用，检索它们没有意义。
PAGES = ("QUESTION-BANK.md",)

# h2 标题 → 条目类别与考点层次。层次直接来自页面自己的"考点 3 层次"分层，
# 一面偏第 1 层八股、二面偏第 2/3 层设计与落地，检索时按轮次加权（见 retrieval.LAYER_FIT）。
_H2_RULES = (
    (re.compile(r"^第\s*(\d)\s*层"), "questions", None),
    (re.compile(r"场景设计题"), "scenarios", ""),
    (re.compile(r"手撕"), "coding", ""),
    (re.compile(r"工程基本功"), "questions", ""),
    (re.compile(r"行业视野"), "questions", ""),
)
_STYLE_H2 = re.compile(r"各厂风格")

_HOT = "🔥"
_PILLAR = re.compile(r"^\*\*(支柱[^*]*)\*\*\s*$")
_CODING_SEP = "·"
_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def _clean(s: str) -> str:
    """压成单行、剥掉 Markdown 强调符。行首绝不留 `#`/`-`：条目会被拼进提示词，
    带着结构符进去会让模型以为那是新的一节。"""
    t = _BOLD.sub(r"\1", str(s or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t.lstrip("#-*>· ").strip()


def _h2_kind(title: str) -> tuple[str, str] | None:
    """h2 标题 → (kind, layer)。认不出来的小节按 questions 收，宁可多收也别静默丢一页。"""
    for pat, kind, layer in _H2_RULES:
        m = pat.search(title)
        if m:
            return kind, (m.group(1) if layer is None else layer)
    return ("questions", "")


def _style_rows(lines: list[str]) -> dict:
    """「各厂风格差异」那张表 → {厂: "风格｜典型压力点"}。

    这一段不进检索池：它是"我该扮成哪种面试官"的指令，跟出题素材是两回事。
    但也没必要把五家全塞进提示词——本场只用得上一行，注入时按压力风格取那一行。"""
    out = {}
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[0] or set(cells[0]) <= set("-: "):
            continue
        firm = _clean(cells[0])
        if firm in ("厂", "风格"):
            continue
        out[firm] = "｜".join(c for c in (_clean(cells[1]), _clean(cells[2])) if c)
    return out


def _coding_entries(lines: list[str]) -> list[tuple[str, str]]:
    """手撕那一节：`**支柱一：…**` 是分组，下面一行用「·」隔开一堆题名。
    返回 [(支柱, 题名)]。没有分隔符的（支柱四那串追问）整行算一条。"""
    out, pillar = [], ""
    for ln in lines:
        m = _PILLAR.match(ln.strip())
        if m:
            pillar = _clean(m.group(1))
            continue
        body = ln.strip().lstrip("-").strip()
        if not body:
            continue
        for part in body.split(_CODING_SEP):
            text = _clean(part)
            if len(text) >= 2:
                out.append((pillar, text))
    return out


def _short(title: str) -> str:
    """标题里括号后面那半截是给人看的注解（"（入场券）""（43 道全景，按四大支柱）"），
    当面包屑用只留前半截。"""
    return _clean(title).split("（")[0].strip()


def parse(name: str, text: str) -> dict:
    """一个页面 → {page, title, note, entries, sections, style_rows, bullets}。

    entries 里每条自带 (page, section, sub) 面包屑：那既是给面试官看的"这题属于哪一类"，
    也是打分时的层次依据。sections 是页面目录——注入时只给挑中的几十条，目录让面试官
    知道库里还有哪些方向，而不是以为只剩这些题。"""
    page = name[:-3] if name.endswith(".md") else name
    title, note = "", []
    h2 = h3 = ""
    blocks: dict[tuple[str, str], list[str]] = {}
    order: list[tuple[str, str]] = []
    style_lines: list[str] = []
    for raw in text.splitlines():
        ln = raw.rstrip()
        s = ln.strip()
        if s.startswith("# ") and not title:
            title = _clean(s)
            continue
        if s.startswith("## "):
            h2, h3 = _clean(s), ""
            continue
        if s.startswith("### "):
            h3 = _clean(s)
            continue
        if not s or s.startswith("---"):
            continue
        if s.startswith(">"):
            if not h2:                     # 只收页头那段出处说明，正文里的引用块不算
                note.append(_clean(s))
            continue
        if not h2:
            continue
        if _STYLE_H2.search(h2):
            style_lines.append(s)
            continue
        key = (h2, h3)
        if key not in blocks:
            blocks[key] = []
            order.append(key)
        blocks[key].append(s)

    entries, sections, bullets = [], [], 0
    for h2, h3 in order:
        kind, layer = _h2_kind(h2)
        sec, sub = _short(h2), _short(h3)
        lines = blocks[(h2, h3)]
        if kind == "coding":
            rows = [(_short(p) or sub, t) for p, t in _coding_entries(lines)]
        else:
            bullets += sum(1 for ln in lines if ln.startswith("- "))
            rows = [(sub, _clean(ln)) for ln in lines if ln.startswith("- ")]
        n = 0
        for pillar, body in rows:
            hot = _HOT in body               # 页面约定：🔥 = 多厂命中的高频题
            body = body.replace(_HOT, "").strip()
            if len(body) < 4:
                continue
            crumb = pillar or sub
            entries.append({
                # 地址 = 页面 + 面包屑 + 序号。跟情报条目的 slug#kind#i 一个路子：
                # 编号在装载时算，页面改了下次装载重新算，不存第二份。
                "id": f"{page}#{sec}" + (f"/{crumb}" if crumb else "") + f"#{n}",
                "page": page, "section": sec, "sub": crumb,
                "kind": kind, "layer": layer, "hot": hot, "text": body,
            })
            n += 1
        if n:
            sections.append({"path": f"{sec}／{sub}" if sub else sec, "kind": kind, "n": n})
    return {
        "page": page, "title": title, "note": "".join(note), "entries": entries,
        "sections": sections, "style_rows": _style_rows(style_lines),
        # 原文有多少条 bullet、切出来多少条，留着对账：静默少切几条比切错更难发现
        "bullets": bullets,
    }


# 压力风格 → 表里行名可能的写法。表里写成"阿里/蚂蚁"，设定里是"阿里蚂蚁"，按子串认。
_STYLE_MATCH = {
    "字节": ("字节",), "美团": ("美团",), "阿里蚂蚁": ("阿里", "蚂蚁"),
    "腾讯": ("腾讯",), "京东": ("京东",),
}


def style_row(pages: list, style: str) -> str:
    """本场压力风格对应的那一行。整张表五家里只有一家用得上，注入那一行就够。"""
    keys = _STYLE_MATCH.get(style, (style,)) if style else ()
    for p in pages:
        for firm, desc in (p.get("style_rows") or {}).items():
            if any(k and k in firm for k in keys):
                return f"{firm}｜{desc}"
    return ""


def stamp(kb_dir) -> tuple:
    """页面指纹（文件名+mtime+大小）。检索缓存拿它当键：改了页面下次装载自动重切，
    不需要谁记得来手动失效。"""
    d = Path(kb_dir)
    out = []
    for name in PAGES:
        try:
            st = (d / name).stat()
        except OSError:
            continue
        out.append((name, st.st_mtime_ns, st.st_size))
    return tuple(out)


def load(kb_dir) -> list[dict]:
    """读 PAGES 并解析。读不到就当这页不存在：少一页该是少几道题，不该是整场面试起不来。"""
    out = []
    for name in PAGES:
        try:
            text = (Path(kb_dir) / name).read_text(encoding="utf-8")
        except OSError:
            continue
        if text.strip():
            out.append(parse(name, text))
    return out
