"""评测检索质量：手写的期望 vs 四种注入策略，看挑出来的到底对不对得上简历。

四条对照，同一份期望、同一套打分：
  wiki     现在的做法：题库条目与情报条目在同一个池子里按相关性挑（配额内）
  whole    重构前线上的做法：题库整页塞进提示词 + 情报按相关性挑
  recency  同样的条数预算，情报纯按时间倒序拿——也就是"只给最近的"；题库不给
  chars    更早的做法：情报按天整节给到字数预算用完（预算是三倍）；题库不给

期望里既有情报条目也有题库条目，所以 whole 的命中率天然接近满分——那是把一整页
一万字塞进去换来的。命中率必须和注入字数、命中密度一起看，否则"多给"永远赢。

用法：python evals/run.py [-v]
"""
import collections
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import kb, retrieval  # noqa: E402

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv
STRATS = (("wiki", "统一检索（现在）"), ("whole", "题库整页+情报检索"),
          ("recency", "只给最近的情报"), ("chars", "情报按字数给"))


def _intel_only(sel: dict) -> dict:
    return {k: [it for it in v if it["space"] == "intel"] for k, v in sel.items()}


def baseline_recency(store: dict, round_name: str) -> dict:
    """同样的情报配额，纯按时间倒序填。store["items"] 里情报已经按天倒序。"""
    quotas = retrieval.INTEL_QUOTAS.get(round_name, retrieval.INTEL_QUOTAS["一面"])
    return {kind: [it for it in store["items"]
                   if it["space"] == "intel" and it["kind"] == kind][:n]
            for kind, n in quotas.items()}


def baseline_chars(store: dict, limit: int = kb.INTEL_BODY_CHARS) -> dict:
    """老线上做法：一天一整节地给，直到字数预算用完，装不下的整天丢掉。"""
    out = {key: [] for key, _label, _fmt in kb.CATEGORIES}
    used = 0
    for d in store["days"]:
        today = [it for it in store["items"]
                 if it["space"] == "intel" and it["day"] == d["day"]]
        cost = sum(len(it["line"]) + 3 for it in today)
        if used and used + cost > limit:
            break
        for it in today:
            out[it["kind"]].append(it)
        used += cost
    return out


def baseline_whole(store: dict, sel: dict) -> dict:
    """重构前线上跑的那套：情报按相关性挑，题库那一页整份塞进去。
    整页在提示词里 = 全部 207 条题库条目都算"注入了"，所以题库侧的期望它全中。
    代价在字数那一列，以及它没法按身份/轮次筛——forbid 那几项它照样中。"""
    out = {kind: list(v) for kind, v in _intel_only(sel).items()}
    for it in store["items"]:
        if it["space"] == "bank":
            out.setdefault(it["kind"], []).append(it)
    return out


_BANK_PAGE = len((ROOT / "kb" / "QUESTION-BANK.md").read_text(encoding="utf-8")) + 80


def injected(store: dict, name: str, sel: dict, style: str) -> int:
    """这套策略真正会进提示词的字数。题库块和情报块分开算，加起来才是可比的。"""
    if name == "wiki":
        return len(retrieval.render_bank(store, sel, style)) + len(retrieval.render_block(store, sel))
    if name == "whole":
        return _BANK_PAGE + len(retrieval.render_block(store, sel))
    return len(retrieval.render_block(store, sel))


def _match(item: dict, exp: dict) -> bool:
    for key in ("kind", "space", "layer", "day"):
        want = exp.get(key)
        if want and want != "any" and item.get(key, "") != want:
            return False
    line = item["line"].lower()
    return all(str(s).lower() in line for s in exp.get("all", []))


def _label(exp: dict) -> str:
    head = exp.get("space", "") + ("/" if exp.get("space") else "") + (exp.get("kind") or "any")
    return head + ":" + ("+".join(exp.get("all", [])) or exp.get("day", ""))


def grade(sel: dict, case: dict) -> tuple:
    """返回 (命中数, 总数, 没命中的期望标签, 命中来自哪一层的计数)。
    forbid 里的条目没出现才算对——整页注入就是在这里丢分的：它没法不给。"""
    items = [it for v in sel.values() for it in v]
    good, miss, split = 0, [], collections.Counter()
    for exp in case.get("expect", []):
        hit = next((it for it in items if _match(it, exp)), None)
        if hit is not None:
            good += 1
            split[hit["space"]] += 1
        else:
            miss.append(_label(exp))
    for exp in case.get("forbid", []):
        if any(_match(it, exp) for it in items):
            miss.append("!" + _label(exp))
        else:
            good += 1
    return good, len(case.get("expect", [])) + len(case.get("forbid", [])), miss, split


def layer_cover(sel: dict, round_name: str) -> tuple:
    """本轮该考的那一层，题库里到底给了几条（RESERVE_LAYER 的兜底有没有生效）。
    一面的〈基础连环〉指着第 1 层要弹药，二面的〈系统设计〉指着第 3 层要。"""
    want, need = retrieval.RESERVE_LAYER.get(round_name, ("", 0))
    n = sum(1 for v in sel.values() for it in v
            if it["space"] == "bank" and it["layer"] == want)
    return want, n, need


def _hops(store: dict, recent: str, picked: list) -> int:
    """挑出来的里有几条不是直接命中的——那几条是顺着条目间的链走过来的。
    用的是 select_turn 自己那两道门槛（够硬 + 到全库最佳的一半），所以口径一致。"""
    q = retrieval.query_terms(recent)
    if not q:
        return 0
    idf, df, cut = store["idf"], store["df"], store["df_cut"]
    best = max((retrieval._lex(it, q, idf) for it in store["items"]), default=0.0)
    return sum(1 for it in picked
               if retrieval._lex(it, q, idf) < retrieval.TURN_MIN_REL * best
               or not retrieval._solid(it["terms"] & q, df, cut))


def run_turns(store: dict, cases: list, sels: dict) -> tuple:
    """轮内追加的评测：候选人说一句话，看尾块那三条对不对。
    这条路径没有对照组——重构前根本没有轮内检索，整场就一份静态提示词。"""
    good = total = hops = picks = 0
    print(f"\n{'轮内追加（候选人说一句 → 尾块给什么）':<44}{'条数':>5}{'其中走链':>9}  期望")
    print("-" * 92)
    for c in cases:
        used = {it["id"] for v in sels[c["id"]].values() for it in v}
        for t in c.get("turns", []):
            got = retrieval.select_turn(store, recent=t["say"], used_ids=used,
                                        style=c["style"], level=c["level"])
            lines = [it["line"].lower() for it in got]
            miss = [w for w in t.get("want", []) if not any(w.lower() in ln for ln in lines)]
            total += len(t.get("want", []))
            good += len(t.get("want", [])) - len(miss)
            if "n" in t:
                total += 1
                good += int(len(got) == t["n"])
                if len(got) != t["n"]:
                    miss.append(f"!条数={len(got)}≠{t['n']}")
            h = _hops(store, t["say"], got)
            hops += h
            picks += len(got)
            print(f"  {t['say'][:38]:<42}{len(got):>5}{h:>9}  "
                  + ("、".join(miss) if miss else "全中"))
            if VERBOSE:
                for it in got:
                    print(f"      [{it['space']}] {it['line'][:74]}")
    return good, total, hops, picks


def main() -> int:
    store = retrieval.load(ROOT / "kb" / "compiled", ROOT / "kb")
    cases = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))["cases"]
    if not store["items"]:
        print("kb/ 里既没有编译产物也没有题库页面，评测无从跑起")
        return 2
    exp_n = sum(len(c.get("expect", [])) + len(c.get("forbid", [])) for c in cases)
    turn_n = sum(len(t.get("want", [])) + ("n" in t)
                 for c in cases for t in c.get("turns", []))
    print(f"语料：{store['total']} 条 = 情报 {store['intel_total']}（{len(store['days'])} 天，"
          f"最新 {store['newest']}）+ 题库 {store['bank_total']}")
    print(f"用例：{len(cases)} 条，场次期望 {exp_n} 项，轮内期望 {turn_n} 项\n")
    print(f"{'用例':<22}{'统一':>8}{'整页':>8}{'按时间':>8}{'按字数':>8}"
          f"{'层次':>8}   注入字数(统一/整页/时间/字数)")
    print("-" * 96)

    tot = {k: [0, 0] for k, _ in STRATS}
    chars = {k: 0 for k, _ in STRATS}
    split = collections.Counter()
    misses, sels, layer_bad = [], {}, []
    for c in cases:
        wiki_sel = retrieval.select(store, resume=c["resume"], round_name=c["round"],
                                    style=c["style"], level=c["level"])
        sels[c["id"]] = wiki_sel
        strat = {"wiki": wiki_sel, "whole": baseline_whole(store, wiki_sel),
                 "recency": baseline_recency(store, c["round"]),
                 "chars": baseline_chars(store)}
        cells, n_ch = [], []
        for name, _lbl in STRATS:
            good, total, miss, sp = grade(strat[name], c)
            tot[name][0] += good
            tot[name][1] += total
            ch = injected(store, name, strat[name], c["style"])
            chars[name] += ch
            n_ch.append(ch)
            cells.append(f"{good}/{total}")
            if name == "wiki":
                split += sp
                if miss:
                    misses.append((c["id"], miss))
        want, got, need = layer_cover(wiki_sel, c["round"])
        if got < need:
            layer_bad.append((c["id"], want, got, need))
        print(f"{c['id']:<22}" + "".join(f"{x:>8}" for x in cells)
              + f"{'L' + want + ':' + str(got) + '/' + str(need):>8}   "
              + "/".join(f"{x:>5}" for x in n_ch))

    print("-" * 96)
    for name, cn in STRATS:
        good, total = tot[name]
        avg = chars[name] // len(cases)
        print(f"{cn:<20} 命中率 {good / total:6.1%}  ({good}/{total})"
              f"   平均注入 {avg:>5} 字   命中密度 {1000 * good / max(1, chars[name]):5.2f} 项/千字")
    print(f"\n统一检索的命中来源：题库 {split['bank']} 项 / 情报 {split['intel']} 项"
          f"（跨两层同一个池子、同一套打分）")
    if layer_bad:
        print("本轮该考那一层的弹药不够：" + "、".join(
            f"{cid} L{w} {g}<{n}" for cid, w, g, n in layer_bad))
    else:
        print("本轮该考那一层的弹药：每个用例都够（一面第 1 层 ≥"
              f"{retrieval.RESERVE_LAYER['一面'][1]}，二面第 3 层 ≥"
              f"{retrieval.RESERVE_LAYER['二面'][1]}）")
    if misses:
        print("\n统一检索没命中的期望（照实列出，不是全部都该修）：")
        for cid, miss in misses:
            print(f"  {cid}: {'、'.join(miss)}")

    tgood, ttotal, hops, picks = run_turns(store, cases, sels)
    print("-" * 92)
    print(f"轮内追加 命中 {tgood}/{ttotal}"
          + (f" ({tgood / ttotal:.1%})" if ttotal else "")
          + f"；共给出 {picks} 条，其中 {hops} 条是顺着条目间的链走出来的")

    base = max(tot["recency"][0], tot["chars"][0])
    ok = (tot["wiki"][0] > base                          # 得赢过"只给最近的"
          and not layer_bad                              # 每轮该考的那层都有弹药
          and chars["wiki"] < chars["whole"]              # 比整页注入省字
          and tot["wiki"][0] >= tot["whole"][0] - 2)      # 且命中不比整页差太多
    print("\n结论：" + ("统一检索赢过按时间/按字数，且比整页注入省字、层次不缺弹药，通过"
                        if ok else "没达到合入线，照实记着"))
    if VERBOSE:
        print(f"  详细：wiki={tot['wiki']} whole={tot['whole']} "
              f"recency={tot['recency']} chars={tot['chars']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
