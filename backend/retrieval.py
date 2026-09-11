"""按相关性挑素材：把整个 wiki 的每个条目当成一个检索单位——kb/*.md 的题库条目和
compiled/ 的情报条目进同一个池子、用同一套打分——选出这一场真正该给面试官的那几十条，
而不是把题库整份灌进去、情报按时间倒序补到字数上限。

为什么不上向量库：条目数在千级以内，纯 Python 全量打分是毫秒级，而每一轮本来就要等模型
好几秒。索引的价值是跳过扫描，这里没有值得跳过的扫描量；反过来，后端要打成单文件 exe，
多一个带原生扩展的依赖就多一处打包风险（schema.py 当初手写校验也是为了这个）。
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path

from . import kb, wiki
from .security import safe_http_url

# 每场从情报层注入多少条。一面重八股与手撕、二面重系统设计与判断力——配额照着
# 〈本场流程〉的阶段配比走，挑出来的东西才跟这一轮真正要考的东西对得上。
INTEL_QUOTAS = {
    "一面": {"questions": 22, "scenarios": 4, "events": 6, "coding": 8},
    "二面": {"questions": 16, "scenarios": 8, "events": 8, "coding": 3},
}
# 题库层的配额。题库有 200 多条，一场面试真正问得到的就十几道：整份注入等于每轮都
# 为 190 条用不上的题付钱，还把模型的注意力摊薄。配额比情报小，因为题库是兜底的
# 覆盖面，情报才是这一场的差异化弹药。
BANK_QUOTAS = {
    "一面": {"questions": 14, "scenarios": 2, "coding": 5},
    "二面": {"questions": 10, "scenarios": 5, "coding": 2},
}
# 题库自己的"考点 3 层次"就是最好的轮次信号：一面筛基本功（第 1 层），
# 二面判设计与落地（第 2/3 层）。层次不明的（场景/手撕/兜底）给中间值。
LAYER_FIT = {
    "一面": {"1": 1.0, "2": 0.55, "3": 0.35},
    "二面": {"1": 0.25, "2": 1.0, "3": 0.95},
}
BANK_FRESH = 0.5         # 题库是沉淀，不参与时效竞争：给个中间值，别让它跟当天情报抢"新"
# 每轮至少给这一层留几个题库名额（见 _reserve）：简历字面上最像的永远是第 2 层设计题，
# 一面的「基础连环」和二面的「落地追问」会被相关性挤空。
RESERVE_LAYER = {"一面": ("1", 4), "二面": ("3", 3)}
TURN_K = 3               # 每轮挂在动态尾块上的追加条数（不进大 system，不破前缀缓存）
TURN_MIN_REL = 0.5       # 轮内追加的门槛：至少要有全库最佳命中的一半，够不着就这轮不补
TURN_DF_FRAC = 0.12      # 英文命中要落在"出现在不到 12% 条目里"的词上，才算真命中而不是撞 agent 这种
LINK_DF_MAX = 12         # 建链只认出现在 12 条以内的词：共现一个大众词不算"相关条目"
LINK_MIN = 2             # 要共现两个这样的词才连边，一个可能是切词切出来的巧合
LINK_K = 4               # 每条最多挂几个邻居
LINK_HOPS = 2            # 顺链走一步时，从命中最强的前几条出发
LINK_DISCOUNT = 0.75     # 邻居是"顺着看到的"，排序上让直接命中优先
RESERVE_NEWEST = 2       # 最新一天至少占几条题，否则"每日更新"更新完也可能一条都进不来
HALF_LIFE_DAYS = 21.0    # 时间衰减半衰期：三周前的情报权重减半
DEDUPE_J = 0.45          # 题面词重合超过这个比例算近义重复，只留分高的那条


# 压力风格 → 公司别名。语料里 company 写法很杂（"字节"/"字节豆包(Seed)"/"美团/字节/京东"），
# 所以按别名子串命中，不做精确相等。
STYLE_ALIASES = {
    "字节": ("字节", "豆包", "火山", "Seed", "抖音"),
    "美团": ("美团",),
    "阿里蚂蚁": ("阿里", "蚂蚁", "千问", "通义", "钉钉", "支付宝"),
    "腾讯": ("腾讯", "混元", "微信"),
    "京东": ("京东",),
}
FREQ_WEIGHT = {"必考": 1.0, "高频": 0.65, "常问": 0.65, "偶尔": 0.2, "低频": 0.15}
# 手撕题难度按候选人身份挑：给实习生出困难题、给社招 3 年+ 出简单题，都是浪费一个阶段
DIFF_FIT = {
    "在校实习": {"简单": 1.0, "中等": 0.7, "困难": 0.15},
    "应届校招": {"简单": 0.7, "中等": 1.0, "困难": 0.4},
    "社招1-3年": {"简单": 0.35, "中等": 1.0, "困难": 0.8},
    "社招3年+": {"简单": 0.15, "中等": 0.8, "困难": 1.0},
}

# 打分各项权重。字面重合是主项，其余是修正项——修正项加起来不该盖过主项。
W_LEX, W_TOPIC, W_COMPANY, W_FREQ, W_DIFF, W_FRESH = 3.0, 1.2, 1.0, 0.8, 0.8, 0.7
W_LAYER = 1.0            # 题库条目的考点层次与本轮的匹配度

_ASCII = re.compile(r"[a-z][a-z0-9+.#_-]+")
_CJK = re.compile(r"[一-鿿]+")
_ASCII_STOP = frozenset(
    "the a an of to in for on at and or is are be was were with without how what why "
    "when which that this it its as by from into not no do does can could should would".split()
)
_DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")
# 只在轮内追加的证据判定里用（见 _solid）：口语里的虚词和套话。候选人说的是话不是题面，
# "直接在""基本""我们"这类词两边都有，却什么考点都没命中。会话级排序不用它——那边名额多，
# 虚词命中会被真命中盖过去，评测也证明了不用管；尾块只有三条，才需要这一层。
_ZH_STOP = frozenset(
    "我们 你们 他们 这个 那个 什么 怎么 为什 哪些 哪个 一个 一下 一些 一般 一直 "
    "可以 不能 没有 有的 用的 的是 是不 会不 需要 应该 已经 正在 进行 直接 接在 "
    "就是 但是 如果 因为 所以 然后 而且 或者 之后 之前 时候 目前 现在 基本 主要 "
    "通常 比较 非常 特别 觉得 还行 清楚 不太 没做 方面 情况 相关 东西 事情 地方".split()
)
# 问答查询额外去掉常见疑问/关系词。条目侧仍保留原词袋，避免影响已有的整场选题
# 排序；只在问答的“是否真的命中”判断和排序中使用，防止“量子纠缠和股价有什么关系”
# 之类的新问题被“关系/什么”撞出随机资料。
_QA_STOP = _ZH_STOP | frozenset(
    "如何 为何 关系 有关 有什 么关 怎么办 解决 问题 方案 设计 介绍 以及 和 与 或".split()
)
_QA_STOP_CHARS = frozenset("如何什么怎么为何和与或有的了是吗呢？")
_QA_GENERIC_HEAD = frozenset("agent llm rag tool")
# 每类条目里参与打分的文本字段（结构化字段如 company/frequency 另算，不混进词袋）
_TEXT_FIELDS = {
    "questions": ("q", "answer_hint"),
    "scenarios": ("title", "background", "focus"),
    "events": ("event", "ask"),
    "coding": ("title", "focus"),
}
_LABEL = {key: label for key, label, _fmt in kb.CATEGORIES}

# 中英同义对：简历写"多头注意力"、题库写 "Attention 中的 Q/K/V"，字面上一个字都不重合。
# 评测里就是这么漏掉一条的（见 evals/cases.json 的 transformer-basics）。二十行字典能补上
# 常见的这一类，不必为此上向量检索——真需要泛化到没列进来的说法时再考虑。
SYNONYMS = (
    ("注意力", "attention"), ("分词", "token"), ("词表", "vocab"), ("召回", "recall"),
    ("重排", "rerank"), ("向量", "embedding"), ("嵌入", "embedding"), ("检索", "retrieval"),
    ("提示词", "prompt"), ("上下文", "context"), ("记忆", "memory"), ("智能体", "agent"),
    ("沙箱", "sandbox"), ("熔断", "circuit"), ("退避", "backoff"), ("流式", "stream"),
    ("微调", "finetune"), ("大模型", "llm"), ("工具调用", "tool"), ("会话", "session"),
    # 切分那一组：题库和情报里这个考点一律写成 "Chunk"，可候选人嘴里出来的是
    # "按 500 字切的、重叠给了 50"。没有这几条，纯中文的两个词又凑不出相邻三字，
    # 轮内追加那道 _solid 门槛就把它拦掉了——问的明明是最典型的 RAG 考点。
    ("分块", "chunk"), ("切分", "chunk"), ("重叠", "chunk"),
)


def terms(text: str) -> set[str]:
    """切词：中文按相邻两字切，英文整词保留。
    不装分词库有两个理由——两字一组对"向量/召回/索引/幂等"这类技术词的区分度已经够；
    而词典分词碰上 "cross-encoder"、"HNSW" 这种新词反而会切碎，越切越不准。"""
    t = str(text or "").lower()
    out = {w for w in _ASCII.findall(t) if w not in _ASCII_STOP}
    for run in _CJK.findall(t):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def query_terms(*texts: str) -> set[str]:
    """查询侧切词：比条目侧多一步同义扩展。只扩查询不扩条目，语料变了不用重建任何东西。"""
    raw = " ".join(str(t or "") for t in texts)
    out = terms(raw)
    low = raw.lower()
    for zh, en in SYNONYMS:
        if zh in low:
            out.add(en)
        if en in low:
            out |= terms(zh)
    return out


def _day_of(meta: dict) -> str:
    """条目的情报日期：优先使用导入时从文件名确定的日期，
    历史产物再从原文文件名/来源/小节标题推断，最后退回编译时间。"""
    if day := str(meta.get("source_day") or ""):
        return day
    for v in (meta.get("raw_file"), meta.get("source"), meta.get("section_title")):
        m = _DATE.search(str(v or ""))
        if m:
            return m.group(0)
    return str(meta.get("compiled_at") or "")[:10]


def _age_days(day: str, ref: str) -> float:
    try:
        a, b = (date(*(int(x) for x in d.split("-"))) for d in (day, ref))
    except (ValueError, TypeError):
        return 0.0
    return max(0.0, float((b - a).days))


def _safe_http_url(value: object) -> str:
    return safe_http_url(value)


def _diff_bucket(s) -> str:
    """难度归三档。语料里写法不统一（"中等偏难"/"简单-中等"），归档时往稳的一边靠。"""
    t = str(s or "")
    if "困难" in t or "较难" in t or "hard" in t.lower():
        return "困难"
    if "简单" in t and "中" not in t:
        return "简单"
    return "中等"


def _items_of(artifact: dict) -> list[dict]:
    """一份编译产物 → 若干可单独寻址的条目。渲染成什么样交给 kb 的格式化函数，
    这边只负责打分要用的东西，两边不会各说各话。"""
    meta = artifact.get("meta") or {}
    slug = str(meta.get("slug") or "")
    day = _day_of(meta)
    topics = [kb._flat(t) for t in (artifact.get("topic") or []) if kb._flat(t)]
    topic = " / ".join(topics)
    tt = terms(" ".join(topics))
    out = []
    for kind, _label, fmt in kb.CATEGORIES:
        for i, x in enumerate(artifact.get(kind) or []):
            if not isinstance(x, dict):
                continue
            text = " ".join(str(x.get(f) or "") for f in _TEXT_FIELDS[kind])
            head = terms(x.get(_TEXT_FIELDS[kind][0]))
            out.append({
                # 编号在装载时算出来，不写进 schema：重编译会重新抽条目，
                # 存进产物里的编号第二天就是错的。
                "id": f"{slug}#{kind}#{i}",
                "space": "intel",       # 跟题库条目同池打分，靠这个字段分配额、分渲染块
                "kind": kind,
                "layer": "",            # 情报没有考点层次，那是题库页面自己的分层
                "day": day,
                "line": fmt(x),
                "company": kb._flat(x.get("company")),
                "platform": kb._flat(x.get("platform")),
                "topic": topic,
                "freq": kb._flat(x.get("frequency")),
                "diff": _diff_bucket(x.get("difficulty")),
                "terms": terms(text),
                "head": head or terms(text),   # 去重只比题面：同一个考点隔几天被不同来源
                                               # 抽出来时，答题要点的措辞往往完全不同
                "topic_terms": tt,      # 那天整体讲什么，当条目的标签用，不用改 schema
                "source": str(meta.get("source") or meta.get("section_title") or "日更情报"),
                "source_urls": [
                    {"url": str(src.get("url") or ""), "title": str(src.get("title") or "")}
                    for src in (meta.get("sources") or [])
                    if isinstance(src, dict) and src.get("url")
                ],
            })
    return out


_BANK_HEAD = re.compile(r"^[^？?：:（(]{4,60}[？?]?")


def _bank_items(pages: list[dict]) -> list[dict]:
    """wiki 页面的条目 → 跟情报条目同一个形状，好进同一个池子打分。

    几个字段是从页面结构里读出来的，不是猜的：层次来自 `## 第 N 层`，🔥 来自页面
    自己的高频标记，公司来自条目里写着的"（美团 Keeta）""（阿里必考）"。
    难度不猜——页面没标手撕题难度，硬给一档会让身份过滤把整节题挡在门外。"""
    out = []
    for p in pages:
        for e in p["entries"]:
            text = e["text"]
            m = _BANK_HEAD.match(text)
            crumb = f"{e['section']} {e['sub']}".strip()
            out.append({
                "id": e["id"],
                "space": "bank",
                "kind": e["kind"],
                "layer": e["layer"],
                "day": "",              # 题库不带日期：它是沉淀，不跟当天情报比新
                "line": text,
                "company": "/".join(
                    firm for firm, al in STYLE_ALIASES.items() if any(a in text for a in al)),
                "platform": "",
                "topic": crumb,
                "freq": "高频" if e["hot"] else "",
                "hot": e["hot"],        # 页面的 🔥 标记，渲染时留着：那是"必问"的信号
                "diff": "中等",          # 见 docstring：不猜难度，取中间档不被身份过滤挡掉
                "terms": terms(text),
                "head": terms(m.group(0)) if m else terms(text),
                "topic_terms": terms(crumb),   # 面包屑就是这条的标签，跟情报的当日主题同位
                "page": e["page"], "section": e["section"], "sub": e["sub"],
                "source": e["page"],
                "source_urls": [],
            })
    return out



def _build_df(items: list[dict]) -> dict[str, int]:
    """每个词出现在多少个条目里。idf 由它算出来（"agent"、"怎么"这种到处都有的压下去，
    "hnsw"、"幂等"抬起来，就是 BM25 的 idf）；df 本身也直接用来判断一次命中够不够特别。"""
    df: dict[str, int] = {}
    for it in items:
        for t in it["terms"]:
            df[t] = df.get(t, 0) + 1
    return df


def _build_links(items: list[dict], df: dict) -> None:
    """给每条条目挂上几个邻居，就地写进 item["related"]。

    真 wiki 的链是人手写的；这份题库里没有链，但"同一个考点在别处也被问过"这件事
    完全能从词面算出来，而且算出来的链是跨层的：八股条目链到最新面经，最新面经链回
    八股条目——这正是"一份知识库"该有的样子，而不是两个互不相识的池子。

    只认稀有词（df ≤ LINK_DF_MAX）且要共现两个：一个共现词可能是切词切出来的巧合
    （见 _solid 里那个"索引"），两个才说明真在讲同一件事。用倒排表算，几百条条目
    是几十毫秒的事。"""
    post: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        for t in it["terms"]:
            if df.get(t, 0) <= LINK_DF_MAX:
                post.setdefault(t, []).append(i)
    for i, it in enumerate(items):
        cnt: dict[int, int] = {}
        for t in it["terms"]:
            if df.get(t, 0) > LINK_DF_MAX:
                continue
            for j in post.get(t, ()):
                if j != i:
                    cnt[j] = cnt.get(j, 0) + 1
        best = sorted(((c, items[j]["id"]) for j, c in cnt.items() if c >= LINK_MIN),
                      key=lambda p: (-p[0], p[1]))
        it["related"] = [rid for _c, rid in best[:LINK_K]]


_store_cache: dict = {}


def load(compiled_dir, kb_dir=None) -> dict:
    """装载整个 wiki 的条目仓库。

    两个来源进同一个池子：kb/*.md 的题库页面（装载时按标题层级解析，见 wiki.py）和
    compiled/*.json 的情报产物。共用一份 idf、共用一套打分、互相连边——检索面对的是
    "一个知识库"，而不是"整份注入的题库 + 单独检索的情报"。

    按目录指纹（文件名+mtime+大小，页面也算）缓存：导入、重编译、手改页面都会改文件，
    指纹跟着变，不需要谁记得来手动失效；一次装载几十毫秒，装完整场面试都在内存里查。"""
    d = Path(compiled_dir)
    kdir = Path(kb_dir) if kb_dir else d.parent
    try:
        stamp = tuple(sorted(
            (p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in d.glob("*.json")
        ))
    except OSError:
        stamp = ()
    wstamp = wiki.stamp(kdir)
    version = (stamp, wstamp)
    if _store_cache.get("key") == (str(d), version, str(kdir)):
        return _store_cache["store"]
    arts = []
    for name, _mtime, _size in stamp:
        try:
            doc = json.loads((d / name).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            continue                      # 一份手改坏的 JSON 不该让整场面试起不来
        if isinstance(doc, dict) and isinstance(doc.get("meta"), dict):
            arts.append(doc)
    arts.sort(key=lambda a: _day_of(a["meta"]), reverse=True)
    pages = wiki.load(kdir)
    items = [it for a in arts for it in _items_of(a)] + _bank_items(pages)
    days = [{
        "day": _day_of(a["meta"]),
        "section": kb._flat(a["meta"].get("section_title") or a["meta"].get("source")),
        "topics": [kb._flat(t) for t in (a.get("topic") or []) if kb._flat(t)],
        "counts": kb.counts(a),
    } for a in arts]
    df = _build_df(items)
    n = len(items) or 1
    _build_links(items, df)
    store = {
        "items": items, "days": days, "pages": pages, "total": len(items), "df": df,
        "version": version,
        "intel_total": sum(1 for it in items if it["space"] == "intel"),
        "bank_total": sum(1 for it in items if it["space"] == "bank"),
        "by_id": {it["id"]: it for it in items},
        "idf": {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()},
        # 一次命中要落在出现次数少于这个数的词上，才算命中考点而不是撞上"用的""数据"
        "df_cut": max(3, int(TURN_DF_FRAC * n)),
        # 时间衰减的参照点取语料里最新的一天，不取当天：语料放旧了不该整体贴地，
        # 评测也才能离线复现。
        "newest": days[0]["day"] if days else "",
    }
    _store_cache.update(key=(str(d), version, str(kdir)), store=store)
    return store



def _freq_w(s) -> float:
    t = str(s or "")
    for key, w in FREQ_WEIGHT.items():
        if key in t:                      # 语料里会写成"必考（3 家都问）"，子串匹配才认得
            return w
    return 0.3


def _lex(item: dict, q_terms: set, idf: dict) -> float:
    """查询词与条目的 idf 加权重合，再按条目长度开方归一——长条目天然多词，
    不归一它就永远赢，最后全场都在问背景写得最长的那道场景题。"""
    hit = item["terms"] & q_terms
    if not hit:
        return 0.0
    return sum(idf.get(t, 1.0) for t in hit) / math.sqrt(len(item["terms"]) + 8)


_CATALOG_FIELDS = (
    "id", "space", "kind", "layer", "day", "line", "company", "platform", "topic", "freq",
    "hot", "source", "source_urls", "page", "section", "sub",
)


def public_item(item: dict) -> dict:
    """Return only fields needed by the read-only Wiki browser.

    Retrieval internals (terms, idf neighbours and scoring hints) stay private so
    the browsing API remains stable even when ranking implementation changes.
    """
    out = {key: item.get(key, "") for key in _CATALOG_FIELDS}
    out["source_urls"] = [
        {"url": url, "title": str(src.get("title") or "")}
        for src in (item.get("source_urls") or [])
        if isinstance(src, dict) and (url := _safe_http_url(src.get("url")))
    ]
    out["source_scope"] = "artifact" if out["source_urls"] else ""
    out["frequency"] = out.pop("freq")
    out["title"] = str(item.get("line") or "").strip()
    return out


def catalog(store: dict, *, query: str = "", kind: str = "", layer: str = "",
            company: str = "", space: str = "", days: int = 0, page: int = 1,
            page_size: int = 50, ref_day: str | None = None) -> dict:
    """Filter and paginate the unified Wiki item store for human browsing."""
    query = str(query or "").strip().casefold()
    kind = str(kind or "").strip()
    layer = str(layer or "").strip()
    company = str(company or "").strip().casefold()
    space = str(space or "").strip()
    try:
        days = max(0, int(days or 0))
    except (TypeError, ValueError):
        days = 0
    ref_day = ref_day or date.today().isoformat()

    def matches(item: dict) -> bool:
        if kind and item.get("kind") != kind:
            return False
        if layer and item.get("layer") != layer:
            return False
        if space and item.get("space") != space:
            return False
        if company and company not in " ".join((
                str(item.get("company") or ""), str(item.get("platform") or ""))).casefold():
            return False
        if query:
            haystack = " ".join(str(item.get(key) or "") for key in (
                "line", "source", "company", "platform", "topic", "page", "section", "sub", "day"))
            if query not in haystack.casefold():
                return False
        if days:
            if not item.get("day") or _age_days(str(item.get("day")), ref_day) > days:
                return False
        return True

    selected = [item for item in store.get("items", []) if matches(item)]
    def sort_day(item: dict) -> int:
        try:
            return date.fromisoformat(str(item.get("day") or "")).toordinal()
        except ValueError:
            return -1

    selected.sort(key=lambda item: (
        -sort_day(item),
        0 if item.get("space") == "intel" else 1,
        str(item.get("id") or ""),
    ))
    total = len(selected)
    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(500, max(1, int(page_size or 50)))
    except (TypeError, ValueError):
        page_size = 50
    start = (page - 1) * page_size
    items = [public_item(item) for item in selected[start:start + page_size]]

    all_items = store.get("items", [])
    kind_counts = {key: sum(1 for item in all_items if item.get("kind") == key)
                   for key, _label, _fmt in kb.CATEGORIES}
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "stats": {
            "total": len(all_items),
            "intel": sum(1 for item in all_items if item.get("space") == "intel"),
            "bank": sum(1 for item in all_items if item.get("space") == "bank"),
            "kinds": kind_counts,
        },
        "facets": {
            "kinds": sorted({str(item.get("kind") or "") for item in all_items if item.get("kind")}),
            "layers": sorted({str(item.get("layer") or "") for item in all_items if item.get("layer")}),
            "spaces": sorted({str(item.get("space") or "") for item in all_items if item.get("space")}),
            "companies": sorted({str(value) for item in all_items
                                 for value in (item.get("company"), item.get("platform")) if value}),
            "platforms": sorted({str(item.get("platform") or "") for item in all_items if item.get("platform")}),
        },
    }


def score(item: dict, q_terms: set, store: dict, *, aliases=(), level="应届校招",
          layer_fit=None) -> float:
    """一条条目对这场面试的相关度。字面重合是主项，其余是修正项：目标公司的题、
    必考的题、贴身份的手撕难度、更新的情报、对得上本轮的考点层次，各加一点。"""
    s = W_LEX * _lex(item, q_terms, store["idf"])
    if q_terms and item["topic_terms"]:
        s += W_TOPIC * min(1.0, len(item["topic_terms"] & q_terms) / 12.0)
    if aliases and any(a in item["company"] for a in aliases):
        s += W_COMPANY
    s += W_FREQ * _freq_w(item["freq"])
    if item["kind"] == "coding":
        s += W_DIFF * DIFF_FIT.get(level, DIFF_FIT["应届校招"]).get(item["diff"], 0.5)
    # 有日期的按时间衰减；题库条目没有日期，给个固定中间值——它不该跟当天情报抢"新"，
    # 也不该因为没日期就被当成最旧的那一天压到底。
    s += W_FRESH * (0.5 ** (_age_days(item["day"], store["newest"]) / HALF_LIFE_DAYS)
                    if item["day"] else BANK_FRESH)
    if item["layer"] and layer_fit:
        s += W_LAYER * layer_fit.get(item["layer"], 0.5)
    return s


def search_question(store: dict, question: str, limit: int = 8) -> list[dict]:
    """面试问答的通用检索。

    和 select() 的整场选题不同，这里只根据用户当前问题排序，不使用轮次、
    公司风格或手撕难度配额。题库与日更情报仍然共用同一套词项和去重逻辑。
    没有字面命中时返回空列表，让上层明确告诉模型“没有命中本地资料”，
    而不是把一条无关素材硬塞进上下文。
    """
    raw_terms = terms(question)
    q_terms = {
        term for term in query_terms(question)
        if term not in _QA_STOP
        and term not in _ASCII_STOP
        and not (len(term) == 2 and any(ch in _QA_STOP_CHARS for ch in term))
    }
    # “Agent” 的同义扩展会产生“智能/能体”两个高频中文二元词；英文问题
    # 已经有 agent 这个稳定 token，不要再让这两个泛词把行业新闻排到前面。
    if "agent" in raw_terms and "智能体" not in question:
        q_terms -= terms("智能体")
    if not q_terms or not store.get("items"):
        return []

    ranked = []
    for item in store["items"]:
        direct_hits = item.get("terms", set()) & q_terms
        head_hits = item.get("head", set()) & q_terms
        topical_hits = item.get("topic_terms", set()) & q_terms
        # score() 含有频率和新鲜度的基础分；问答检索不能让“没有命中”
        # 的条目靠这些基础分进入上下文，否则用户问一个新问题时会收到随机旧素材。
        # 正文里偶然出现一个词不算相关命中：例如“价格”可能出现在某条行业
        # 情报里，但不代表它能回答股票问题。标题命中可单独成立，但只有泛化的
        # “Agent/RAG”标题词不够；否则至少要有两个查询词命中正文/主题。
        strong_head_hits = head_hits - _QA_GENERIC_HEAD
        if not (strong_head_hits or len(direct_hits) >= 2 or len(topical_hits) >= 2):
            continue
        direct = len(head_hits)
        topical = len(topical_hits)
        value = score(item, q_terms, store) + direct * 0.35 + topical * 0.2
        ranked.append((value, item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return [item for _value, item in _take(ranked, max(1, min(limit, 12)))]


def render_qa_context(items: list[dict]) -> str:
    """把问答命中的条目渲染成仅供模型参考的上下文。"""
    if not items:
        return "（本次没有命中本地题库或情报库。可以给出通用技术回答，但不要伪造本地来源、公司案例或具体数据。）"
    lines = []
    for item in items:
        source = item.get("source") or ("题库" if item.get("space") == "bank" else "日更情报")
        date_mark = f"｜{item['day']}" if item.get("day") else ""
        lines.append(f"- [{item.get('kind', 'question')}] {item.get('line', '').strip()}（来源：{source}{date_mark}）")
    return "\n".join(lines)


def _too_close(a: set, b: set) -> bool:
    """近义重复判定，比的是题面。同一个考点隔几天会被不同来源重复抽出来
    （"向量索引有哪些类型" 两天里各有一条），不去重就是拿配额喂重复。"""
    if not a or not b:
        return False
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter) >= DEDUPE_J


def _take(ranked: list, n: int, seen=()) -> list:
    """按分数取 n 条，跳过近义重复的。seen 是别处已经选走的：题库那一批要跟情报那一批
    比，同一道八股题两边都收录时才不会占两个名额。"""
    picked: list = []
    for pair in ranked:
        if len(picked) >= n:
            break
        if any(_too_close(pair[1]["head"], p[1]["head"]) for p in list(seen) + picked):
            continue
        picked.append(pair)
    return picked



def _reserve(picked: list, pool: list, ok, k: int) -> list:
    """保证挑出来的里至少有 k 条满足 ok()：不够就拿池子里满足的、分最高的几条，
    替掉已选里分最低的几条。

    相关性该赢，但有两件事不能被相关性挤掉：最新一天的情报（"每日更新"更新完一条都
    进不来，这功能就白做了），和本轮该考的那一层（一面没有第 1 层八股、二面没有第 3 层
    落地题，〈本场流程〉里对应的阶段就没弹药可用）。"""
    if k <= 0:
        return picked
    have = sum(1 for _s, it in picked if ok(it))
    if have >= k:
        return picked
    ids = {it["id"] for _s, it in picked}
    add = [p for p in pool
           if ok(p[1]) and p[1]["id"] not in ids
           and not any(_too_close(p[1]["head"], q[1]["head"]) for q in picked)][: k - have]
    # 只挤掉不满足 ok() 的那几条，从尾巴上一刀切会连已经满足的一起切掉——补一条丢一条，
    # 永远够不到 k。挤不出位置就少补几条，不许把配额撑大。
    drop = {i for i, (_s, it) in reversed(list(enumerate(picked))) if not ok(it)}
    drop = set(sorted(drop, reverse=True)[: len(add)])
    add = add[: len(drop)]
    if not add:
        return picked
    keep = [p for i, p in enumerate(picked) if i not in drop]
    return sorted(keep + add, key=lambda p: (-p[0], p[1]["id"]))



def select(store: dict, *, resume="", round_name="一面", style="", level="应届校招",
           extra="") -> dict:
    """一场面试的选材，返回 {kind: [item, ...]}；题库条目与情报条目混在一起，各自带 space。

    会话级而不是每轮级：大 system 块要字节稳定才吃得到前缀缓存，所以整场只选一次；
    每轮变的那两三条走动态尾块（select_turn）。

    情报先挑、题库后挑：时效性该优先，而且同一道题两边都有时（题库里的高频八股常常
    正是最近面经里的原题），去重要保留带日期和答题要点的那一条。"""
    q = query_terms(resume, extra)
    aliases = STYLE_ALIASES.get(style, ())
    fit = DIFF_FIT.get(level, DIFF_FIT["应届校招"])
    layer_fit = LAYER_FIT.get(round_name, LAYER_FIT["一面"])
    out: dict = {}
    for space, quotas in (("intel", INTEL_QUOTAS), ("bank", BANK_QUOTAS)):
        for kind, n in quotas.get(round_name, quotas["一面"]).items():
            pool = [(score(it, q, store, aliases=aliases, level=level, layer_fit=layer_fit), it)
                    for it in store["items"]
                    if it["kind"] == kind and it["space"] == space
                    # 明显不匹配身份的手撕题直接不进池子：给实习生甩困难题、给社招 3 年+
                    # 出简单题，都是白扔一个阶段，靠加权压不稳（新鲜度一抬就翻上来了）。
                    and (kind != "coding" or fit.get(it["diff"], 0.5) >= 0.2)]
            pool.sort(key=lambda p: (-p[0], p[1]["id"]))   # 同分按 id，保证可复现
            prev = out.get(kind) or []
            picked = _take(pool, n, seen=prev)
            if kind == "questions" and space == "intel" and store["newest"]:
                picked = _reserve(picked, pool,
                                  lambda it: it["day"] == store["newest"], RESERVE_NEWEST)
            if kind == "questions" and space == "bank":
                # 简历写的是 RAG/Agent，字面上最像的永远是第 2 层设计题；一面的
                # 「基础连环」阶段却指着第 1 层要弹药，留几个名额给它。
                want, kn = RESERVE_LAYER.get(round_name, ("", 0))
                picked = _reserve(picked, pool, lambda it: it["layer"] == want, kn)
            out[kind] = prev + picked

    return {kind: [it for _sc, it in pairs] for kind, pairs in out.items()}



def _solid(hits: set, df: dict, cut: int) -> bool:
    """这次命中够不够硬。

    中文按相邻两字切会造出"幽灵词"：语料里"检索引用与输出过滤"会切出一个"索引"，
    跟候选人说的"HNSW 索引"字面上完美对上，可那句话根本不在讲索引——尾块里就这么
    混进过一条 Anthropic 版权和解。df 拦不住它，因为"索引"本身确实是个稀有词。

    所以按命中的形态分别要求：英文整词不会被切碎，一个够特别的英文命中就算硬；
    纯中文命中要两个首尾相接的两字词（等于原文连着三个字都对上），且不能是虚词——
    "直接"+"接在" 也能接成三个字，可"直接在"什么考点都不是。
    只在轮内追加上这么严：大 system 那边有四十个名额、排序能把偶发的幽灵词压下去，
    尾块只有三条，每条都得站得住。"""
    if any(t.isascii() and df.get(t, 1) <= cut for t in hits):
        return True
    zh = {t for t in hits if not t.isascii()} - _ZH_STOP
    return any(a[1] == b[0] for a in zh for b in zh if a != b)


def select_turn(store: dict, *, recent="", used_ids=(), style="", level="应届校招",
                kinds=None, k=TURN_K) -> list:
    """每轮的追加：拿候选人刚说的那段话当查询，从没进 system 的条目里挑几条。

    两道门槛，缺一不可：命中得够硬（见 _solid），而且得有全库最佳命中的一半以上。
    尾块每轮都在花钱，宁可不给也别给噪音。

    直接命中不够 k 条时，顺着条目间的链走一步：命中最强的那条往往已经在 system 里了，
    与其在剩下的条目里矮子里拔将军，不如从它出发看它链到哪些还没注入过的条目——
    那是"翻到一页再顺着链接翻下一页"，不是"把库里第二像的东西端上来"。"""
    q = query_terms(recent)
    if not q or not store["items"]:
        return []
    used = set(used_ids)
    idf, df, cut = store["idf"], store["df"], store["df_cut"]
    # 门槛比的是全库最佳命中，不是未选中里的最佳：否则最相关的几条进了 system 之后，
    # 剩下的一批矮子里拔将军，每轮都能凑出三条来。
    allowed = None if kinds is None else set(kinds)
    best = max((_lex(it, q, idf) for it in store["items"]
                if allowed is None or it["kind"] in allowed), default=0.0)
    if best <= 0:
        return []
    aliases = STYLE_ALIASES.get(style, ())

    def sc(it: dict) -> float:
        return score(it, q, store, aliases=aliases, level=level)

    hits = []                       # 命中够硬的，含已注入过的：它们是走链的起点
    for it in store["items"]:
        if allowed is not None and it["kind"] not in allowed:
            continue
        lex = _lex(it, q, idf)
        if lex < TURN_MIN_REL * best or not _solid(it["terms"] & q, df, cut):
            continue
        hits.append((lex, it))
    if not hits:
        return []
    cands = sorted(((sc(it), it) for _l, it in hits if it["id"] not in used),
                   key=lambda p: (-p[0], p[1]["id"]))
    picked = _take(cands, k)
    if len(picked) < k:
        hits.sort(key=lambda p: (-p[0], p[1]["id"]))
        seen = used | {it["id"] for _s, it in picked}
        hop = []
        for _l, anchor in hits[:LINK_HOPS]:
            for rid in anchor.get("related", ()):
                nb = store["by_id"].get(rid)
                if nb is None or (allowed is not None and nb["kind"] not in allowed) or rid in seen:
                    continue
                seen.add(rid)
                hop.append((LINK_DISCOUNT * sc(nb), nb))
        hop.sort(key=lambda p: (-p[0], p[1]["id"]))
        picked += _take(hop, k - len(picked), seen=picked)
    return [it for _sc, it in picked]


def render_block(store: dict, selected: dict) -> str:
    """情报块：先按天给目录，再给挑出来的条目。

    目录只有七八行，很便宜；换来的是面试官知道库里还有哪些天、哪些主题，
    而不是像按字数截断那样被静默丢掉。"""
    picks = {kind: [it for it in (selected.get(kind) or []) if it["space"] == "intel"]
             for kind, _label, _fmt in kb.CATEGORIES}
    n = sum(len(v) for v in picks.values())
    if not n:
        return ""
    out = ["\n<最新面经情报（时效性最强，出题优先参考）>",
           f"库里现有 {store['intel_total']} 条，按天："]
    for d in store["days"]:
        out.append(f"- {d['section']}：{' / '.join(d['topics']) or '无新增'}")
    out.append("")
    out.append(f"下面 {n} 条是按候选人这份简历和本轮设定从全库挑出来的（不是全部）。"
               "要问上面别的方向就顺着日期和主题问，没细节时只问思路，别编造具体数字。")
    for kind, label, _fmt in kb.CATEGORIES:
        if not picks[kind]:
            continue
        out += ["", f"**{label}**"] + [f"- {it['line']}｜{it['day']}" for it in picks[kind]]
    out.append("</最新面经情报>\n")
    return "\n".join(out)


def render_bank(store: dict, selected: dict, style: str = "") -> str:
    """题库块：页面目录 + 按这场面试挑出来的条目 + 本场压力风格那一行。

    以前这一页一万字每轮整份注入，而一场面试真正问得到的就十几道。现在只给挑中的，
    外加一份目录：面试官知道页面上还有哪些方向，要换方向直接问就是了——题面不必背在
    提示词里。目录这几行的钱花得值，它换掉的是"我看不见的东西等于不存在"。"""
    picks = [it for kind, _label, _fmt in kb.CATEGORIES
             for it in (selected.get(kind) or []) if it["space"] == "bank"]
    pages = store.get("pages") or []
    if not picks or not pages:
        return ""
    out = ["\n<面试官题库（弹药库：选题、改题的素材，不是照读的剧本）>"]
    for p in pages:
        head = p["title"] or p["page"]
        out.append(f"{head}｜{p['note']}" if p["note"] else head)
        out.append(f"目录（整页 {len(p['entries'])} 条，下面注入的只是其中一部分）：")
        out += [f"- {s['path']}（{s['n']}）" for s in p["sections"]]
    row = wiki.style_row(pages, style)
    if row:
        out += ["", f"本场压力风格对应的出题侧重：{row}"]
    out += ["", f"下面 {len(picks)} 条是按这轮考点层次挑出来的素材。按题型使用：项目题才贴他的简历；"
                "概念题独立问机制、原理和边界；场景题必须补充简历之外的背景、量级和约束。"
                "要换目录里别的方向直接问，别为了用这几条硬转。"]
    groups: dict[str, list] = {}
    for it in picks:
        crumb = f"{it['section']}／{it['sub']}" if it["sub"] else it["section"]
        # 🔥 是页面自己标的多厂高频，注入时留着：面试官看一眼就知道哪几条是必问的
        groups.setdefault(crumb, []).append(("🔥 " if it.get("hot") else "") + it["line"])
    for crumb, lines in groups.items():
        out += ["", f"**{crumb}**"] + [f"- {ln}" for ln in lines]
    out.append("</面试官题库>\n")
    return "\n".join(out)


def render_turn(items: list) -> str:
    """每轮尾块里的素材补充（题库条目和情报条目都可能）。
    明说是备选：硬转话题比不给素材更假。"""
    if not items:
        return ""
    body = "\n".join("- " + it["line"] + (f"｜{it['day']}" if it["day"] else "｜题库")
                     for it in items)
    return ("\n【素材补充，候选人不可见】库里跟他刚才这段话相关的条目（备选，顺就用、"
            f"不顺就不用，别为了用它硬转话题）：\n{body}")







