"""LLM 提供商适配层：支持 Anthropic Messages API 与 OpenAI Responses API。

配置通过 .env 读取，用户自行填写 key：
  LLM_PROVIDER=anthropic | openai
  ANTHROPIC_API_KEY / ANTHROPIC_MODEL / ANTHROPIC_BASE_URL（中转站时填写，不带 /v1）
  OPENAI_API_KEY / OPENAI_MODEL / OPENAI_BASE_URL（兼容第三方网关时填写，带 /v1）

中转站兼容：OpenAI 通路优先走 Responses API，网关不支持时自动降级 chat/completions。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable


_NO_SEARCH_MARK = "没有发起过一次搜索"


class SearchUnavailable(RuntimeError):
    """这条通路没有真正联网搜索：中转站常见的做法是静默丢弃 tools 参数，
    请求照常 200 返回，模型那头却看不到工具，只会凭记忆编或者直接拒答。"""


@dataclass
class ResearchResult:
    """联网检索的结果：蒸馏正文 + 这次实际引用到的网页。"""
    text: str
    sources: list[dict]          # [{"url": ..., "title": ...}]


def _source_collector() -> tuple[list[dict], Callable[..., None]]:
    """返回 (结果列表, add(url, title))，按 url 去重。"""
    out: list[dict] = []
    seen: set[str] = set()

    def add(url, title=""):
        url = (url or "").strip()
        if url and url not in seen:
            seen.add(url)
            out.append({"url": url, "title": (title or "").strip()})

    return out, add


def _harvest_anthropic_sources(blocks, add) -> bool:
    """捞搜索结果，返回「这一轮模型有没有真的发起搜索」。
    块的形状随 SDK/网关有出入，一律软处理。"""
    searched = False
    for b in blocks or []:
        btype = getattr(b, "type", "")
        if btype == "web_search_tool_result":
            searched = True
            content = getattr(b, "content", None)
            if isinstance(content, list):      # 出错时 content 是单个错误对象，不是列表
                for r in content:
                    add(getattr(r, "url", ""), getattr(r, "title", ""))
        elif btype == "server_tool_use" and getattr(b, "name", "") == "web_search":
            searched = True                    # 发起了搜索但结果块被网关删了，也算搜过
        elif btype == "text":
            for c in getattr(b, "citations", None) or []:
                add(getattr(c, "url", ""), getattr(c, "title", ""))
    return searched


def _harvest_openai_sources(resp, add) -> bool:
    """捞 url_citation 标注，返回 output 里有没有出现搜索调用。"""
    searched = False
    for item in getattr(resp, "output", None) or []:
        if "search" in getattr(item, "type", ""):
            searched = True
        for c in getattr(item, "content", None) or []:
            for a in getattr(c, "annotations", None) or []:
                add(getattr(a, "url", ""), getattr(a, "title", ""))
    return searched


@dataclass
class LLMConfig:
    provider: str
    model: str

    @staticmethod
    def load() -> "LLMConfig":
        provider = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
        if provider == "anthropic":
            model = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
        else:
            model = os.getenv("OPENAI_MODEL", "gpt-5")
        return LLMConfig(provider=provider, model=model)


class LLMClient:
    """messages: [{"role": "user"|"assistant", "content": str}, ...]"""

    def __init__(self) -> None:
        self.cfg = LLMConfig.load()
        self._anthropic = None
        self._openai = None
        self._force_chat_completions = False  # 网关不支持 Responses API 时置位

    # ---- provider clients (lazy) ----
    # SDK 默认 timeout=600s 且重试 2 次：中转站死掉/半开时一次调用能挂半小时，前端就是无尽转圈。
    # 收紧成有界值——流式下 read 是「相邻数据块之间」的间隔上限，长回答不受影响；
    # 挂了能在分钟级报错，交给 _rotate 换下一家。
    @staticmethod
    def _http_limits() -> dict:
        try:
            import httpx2 as hx  # 新版 anthropic/openai SDK 依赖 httpx2
        except ImportError:
            import httpx as hx
        return {
            "timeout": hx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
            "max_retries": 1,
        }

    def _get_anthropic(self):
        if self._anthropic is None:
            import anthropic
            base_url = (os.getenv("ANTHROPIC_BASE_URL") or "").strip().rstrip("/")
            # SDK 自己会拼 /v1/messages，中转站给的地址若带了 /v1 就剥掉，避免出现 /v1/v1
            if base_url.endswith("/v1"):
                base_url = base_url[:-3].rstrip("/")
            self._anthropic = anthropic.Anthropic(base_url=base_url or None, **self._http_limits())
        return self._anthropic

    def _get_openai(self):
        if self._openai is None:
            from openai import OpenAI
            base_url = os.getenv("OPENAI_BASE_URL") or None
            self._openai = OpenAI(base_url=base_url, **self._http_limits())
        return self._openai

    # ---- 双提供商调度：首选 = 设置里选的那家，另一家配了 key 就是备用 ----
    @staticmethod
    def _key_of(provider: str) -> str:
        return os.getenv("ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY", "")

    @staticmethod
    def model_of(provider: str) -> str:
        if provider == "anthropic":
            return os.getenv("ANTHROPIC_MODEL", "claude-opus-5")
        return os.getenv("OPENAI_MODEL", "gpt-5")

    def chain(self) -> list[str]:
        """按优先级返回配了 key 的提供商列表。"""
        prefs = [self.cfg.provider] + [p for p in ("anthropic", "openai") if p != self.cfg.provider]
        return [p for p in prefs if self._key_of(p)]

    def ready(self) -> tuple[bool, str]:
        ch = self.chain()
        if not ch:
            return False, "两家的 API Key 都还没填，请在设置里配置任意一家"
        detail = f"{ch[0]} / {self.model_of(ch[0])}"
        if len(ch) > 1:
            detail += f"（备用：{ch[1]} / {self.model_of(ch[1])}）"
        return True, detail

    def _rotate(self, fn_map: dict, *args) -> str:
        """依次尝试可用提供商，一家报错自动换下一家；全挂了把每家的错都抛出来。"""
        errs = []
        for p in self.chain() or [self.cfg.provider]:
            try:
                return fn_map[p](self.model_of(p), *args)
            except Exception as e:
                errs.append(f"{p}/{self.model_of(p)}：{e}")
        raise RuntimeError("　→ 已自动切换备用，仍失败 → 　".join(errs) if len(errs) > 1 else errs[0])

    # ---- unified chat ----
    def chat(
        self, system: str, messages: list[dict], max_tokens: int = 8192,
        stop: list[str] | None = None, fast: bool = False, system_tail: str = "",
        cache_last: bool = False,
    ) -> str:
        """stop：停止序列，用来在 API 端就掐住"模型开始自演下一轮"的开头。
        Anthropic 与 chat/completions 支持；Responses API 没有这个参数，会被忽略。

        fast：对话轮和机械任务用。推理模型默认自适应思考，一句 120 字的面试官回话
        也能先想 30 秒——候选人那头就是干等；显式压低思考能降到几秒。
        网关不认这个参数时自动退回普通调用。

        system_tail：每轮都变的小尾巴（面试进度提示这类）。单独一个块拼在 system 之后、
        缓存断点之外——大头的 system 保持字节不变才能吃到前缀缓存。

        cache_last：多轮对话专用。system 的断点只护住提示词，对话历史每轮都全价重算，
        40 分钟面到后半场 TTFT 线性变慢；在最后一条消息也挂断点，历史就成了增量缓存。
        一次性调用（复盘/纠错）别开，白付 25% 的缓存写入费。"""
        return self._rotate(
            {"anthropic": self._chat_anthropic, "openai": self._chat_openai},
            system, messages, max_tokens, stop, fast, system_tail, cache_last,
        )

    @staticmethod
    def _cache_tail(messages: list[dict]) -> list[dict]:
        """最后一条消息挂缓存断点。每轮断点后移，服务端按最长前缀命中上一轮的缓存，
        实际只算新增的一问一答。"""
        last = messages[-1]
        return messages[:-1] + [{
            "role": last["role"],
            "content": [{
                "type": "text",
                "text": last["content"],
                "cache_control": {"type": "ephemeral"},
            }],
        }]

    def _chat_anthropic(
        self, model: str, system: str, messages: list[dict], max_tokens: int,
        stop: list[str] | None = None, fast: bool = False, system_tail: str = "",
        cache_last: bool = False,
    ) -> str:
        client = self._get_anthropic()
        # 走流式：复盘报告要生成几千字，非流式请求在中转站/CDN 上常被 100s 空闲超时掐断（524），
        # SDK 还会把它当 5xx 重试两次，于是表现为"卡很久最后报 52x"。流式全程有数据在走，不会被判超时。
        # Opus 5：省略 thinking 参数即自适应思考；system 挂 cache_control 复用前缀缓存
        sys_blocks = [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }]
        if system_tail:  # 动态尾块放缓存断点之后，不搅坏前缀缓存
            sys_blocks.append({"type": "text", "text": system_tail})

        # 中转站可能不认 thinking / 消息级 cache_control：逐个摘掉重试，最差退成裸调用
        thinking_off = fast
        cache = cache_last and len(messages) > 1
        while True:
            try:
                with client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=sys_blocks,
                    messages=self._cache_tail(messages) if cache else messages,
                    **({"stop_sequences": list(stop)} if stop else {}),
                    **({"thinking": {"type": "disabled"}} if thinking_off else {}),
                ) as stream:
                    resp = stream.get_final_message()
                break
            except Exception as e:
                s = str(e).lower()
                if thinking_off and "thinking" in s:
                    thinking_off = False      # 不认就照常跑，只是慢
                    continue
                if cache and "cache" in s:
                    cache = False
                    continue
                raise
        if resp.stop_reason == "refusal":
            return "（面试官暂时无法回应这个话题，换个问题继续。）"
        return "".join(b.text for b in resp.content if b.type == "text")

    # ---- streaming chat：SSE 逐字吐给前端，边收边念 ----
    def chat_stream(self, system: str, messages: list[dict], max_tokens: int = 8192,
                    stop: list[str] | None = None, system_tail: str = "",
                    fast: bool = False, cache_last: bool = False):
        """生成器：逐段 yield 文本增量。轮换只在「还没吐出任何字」时发生——
        吐了半句再换家，候选人会听到两个面试官接力说话。
        fast / cache_last 语义同 chat()：面试轮必开——首字延迟的大头是模型
        开口前的自适应思考，其次是越滚越长的未缓存历史。"""
        errs = []
        for p in self.chain() or [self.cfg.provider]:
            fn = self._stream_anthropic if p == "anthropic" else self._stream_openai
            emitted = False
            try:
                for piece in fn(self.model_of(p), system, messages, max_tokens,
                                stop, system_tail, fast, cache_last):
                    emitted = True
                    yield piece
                return
            except Exception as e:
                if emitted:
                    raise
                errs.append(f"{p}/{self.model_of(p)}：{e}")
        raise RuntimeError(
            "　→ 已自动切换备用，仍失败 → 　".join(errs) if len(errs) > 1
            else (errs[0] if errs else "没有可用的提供商")
        )

    def _stream_anthropic(self, model: str, system: str, messages: list[dict], max_tokens: int,
                          stop: list[str] | None = None, system_tail: str = ""):
        client = self._get_anthropic()
        sys_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if system_tail:
            sys_blocks.append({"type": "text", "text": system_tail})
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=sys_blocks,
            messages=messages,
            **({"stop_sequences": list(stop)} if stop else {}),
        ) as stream:
            for t in stream.text_stream:
                if t:
                    yield t
            final = stream.get_final_message()
        if final.stop_reason == "refusal" and not any(
            b.type == "text" and b.text for b in final.content
        ):
            yield "（面试官暂时无法回应这个话题，换个问题继续。）"

    def _stream_openai(self, model: str, system: str, messages: list[dict], max_tokens: int,
                       stop: list[str] | None = None, system_tail: str = ""):
        if self._force_chat_completions:
            yield from self._stream_chat_completions(model, system, messages, max_tokens, stop, system_tail)
            return
        client = self._get_openai()
        instructions = f"{system}\n\n{system_tail}" if system_tail else system
        emitted = False
        try:
            with client.responses.stream(
                model=model,
                instructions=instructions,
                input=[{"role": m["role"], "content": m["content"]} for m in messages],
                max_output_tokens=max_tokens,
            ) as stream:
                for event in stream:
                    # 只放行正文增量——reasoning 等其它事件流不进候选人耳朵
                    if getattr(event, "type", "") == "response.output_text.delta":
                        d = getattr(event, "delta", "") or ""
                        if d:
                            emitted = True
                            yield d
        except Exception as e:
            if emitted or not self._responses_unsupported(e):
                raise
            self._force_chat_completions = True
            yield from self._stream_chat_completions(model, system, messages, max_tokens, stop, system_tail)

    def _stream_chat_completions(self, model: str, system: str, messages: list[dict], max_tokens: int,
                                 stop: list[str] | None = None, system_tail: str = ""):
        client = self._get_openai()
        if system_tail:
            system = f"{system}\n\n{system_tail}"
        msgs = [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]
        extra = {"stop": list(stop)[:4]} if stop else {}

        def gen(**kw):
            for chunk in client.chat.completions.create(model=model, messages=msgs, stream=True, **extra, **kw):
                if chunk.choices:
                    piece = chunk.choices[0].delta.content
                    if piece:
                        yield piece

        try:
            yield from gen(max_completion_tokens=max_tokens)
        except Exception as e:
            # 参数不兼容在首个 chunk 之前就会报，此时还没吐字，重试安全
            if "max_completion_tokens" not in str(e):
                raise
            yield from gen(max_tokens=max_tokens)

    # ---- research：带原生 web search 工具的调用（每日知识库更新用） ----
    def research(
        self, system: str, prompt: str, max_tokens: int = 8192,
        allowed_domains: list[str] | None = None,
    ) -> ResearchResult:
        """allowed_domains：搜索域名白名单（只写域名，不带 http/https），None = 不限。"""
        try:
            return self._rotate(
                {"anthropic": self._research_anthropic, "openai": self._research_openai},
                system, prompt, max_tokens, allowed_domains,
            )
        except Exception as e:
            if _NO_SEARCH_MARK not in str(e):
                raise
            raise SearchUnavailable(
                f"配置的通路都没能真正联网搜索。\n\n原因：{e}\n\n"
                "多数中转站不实现服务端搜索工具，会把 tools 参数静默丢弃——"
                f"请求照常成功，模型却看不到工具，于是只能拒答或编造。\n"
                "换成官方直连（把设置里的 BASE_URL 清空、填官方 key），"
                f"或换一个明确支持 web_search 的中转站即可恢复。\n"
                "在那之前，「导入日更文件」这条路不受影响——蒸馏用的是普通对话，不需要搜索工具。"
            ) from e

    @staticmethod
    def _domain_filter_unsupported(e: Exception) -> bool:
        """网关/旧模型不认域名白名单参数时的典型报错。"""
        s = str(e).lower()
        return "allowed_domains" in s or "filters" in s

    def _research_anthropic(
        self, model: str, system: str, prompt: str, max_tokens: int,
        allowed_domains: list[str] | None = None,
    ) -> ResearchResult:
        client = self._get_anthropic()

        def tool(tool_type: str, domains: list[str] | None):
            t = {"type": tool_type, "name": "web_search", "max_uses": 8}
            if domains:
                t["allowed_domains"] = list(domains)
            return [t]

        def run(tool_defs):
            messages = [{"role": "user", "content": prompt}]
            sources, add = _source_collector()
            searched = False
            while True:
                resp = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    tools=tool_defs,
                    messages=messages,
                    timeout=600.0,  # 非流式 + 服务端搜索，合法耗时可达几分钟，单独放宽
                )
                # 续跑前先收，否则前几轮的来源丢了
                searched |= _harvest_anthropic_sources(resp.content, add)
                if resp.stop_reason == "pause_turn":  # 服务端搜索循环到限，续跑
                    messages = [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": resp.content},
                    ]
                    continue
                if not searched:
                    raise SearchUnavailable(
                        f"{model} 这条通路全程{_NO_SEARCH_MARK}"
                        "（中转站多半把工具参数丢了），产出只能是编造或拒答，已丢弃"
                    )
                text = "".join(b.text for b in resp.content if b.type == "text")
                return ResearchResult(text, sources)

        try:
            return run(tool("web_search_20260209", allowed_domains))
        except SearchUnavailable:
            raise                       # 工具被吞了，换工具版本没意义，交给上层轮换提供商
        except Exception as e:
            if "web_search" in str(e):  # 旧模型不支持新版搜索工具，降级 basic
                try:
                    return run(tool("web_search_20250305", allowed_domains))
                except SearchUnavailable:
                    raise
                except Exception as e2:
                    if allowed_domains and self._domain_filter_unsupported(e2):
                        return run(tool("web_search_20250305", None))
                    raise
            if allowed_domains and self._domain_filter_unsupported(e):
                return run(tool("web_search_20260209", None))
            raise

    def _research_openai(
        self, model: str, system: str, prompt: str, max_tokens: int,
        allowed_domains: list[str] | None = None,
    ) -> ResearchResult:
        client = self._get_openai()

        def run(tool_type: str, domains: list[str] | None):
            t = {"type": tool_type}
            if domains:
                t["filters"] = {"allowed_domains": list(domains)}
            resp = client.responses.create(
                model=model,
                instructions=system,
                input=prompt,
                tools=[t],
                max_output_tokens=max_tokens,
                timeout=600.0,  # 非流式 + 服务端搜索，合法耗时可达几分钟，单独放宽
            )
            sources, add = _source_collector()
            if not _harvest_openai_sources(resp, add):
                raise SearchUnavailable(
                    f"{model} 这条通路全程{_NO_SEARCH_MARK}"
                    "（网关多半把工具参数丢了），产出只能是编造或拒答，已丢弃"
                )
            return ResearchResult(resp.output_text, sources)

        try:
            return run("web_search", allowed_domains)
        except SearchUnavailable:
            raise
        except Exception as e:
            if self._responses_unsupported(e):
                raise RuntimeError(
                    "当前网关不支持 OpenAI Responses API，联网搜索用不了。"
                    "知识库自动更新需要官方 OpenAI 或支持 /v1/responses 的中转站；面试对话不受影响。"
                ) from e
            if "web_search" in str(e):
                try:
                    return run("web_search_preview", allowed_domains)
                except SearchUnavailable:
                    raise
                except Exception as e2:
                    if allowed_domains and self._domain_filter_unsupported(e2):
                        return run("web_search_preview", None)
                    raise
            if allowed_domains and self._domain_filter_unsupported(e):
                return run("web_search", None)
            raise

    @staticmethod
    def _responses_unsupported(e: Exception) -> bool:
        """中转站没有 /v1/responses 时的典型报错：404 / not found / unknown path。"""
        s = str(e).lower()
        return (
            getattr(e, "status_code", None) == 404
            or "404" in s or "not found" in s or "unknown request url" in s
            or ("unsupported" in s and "responses" in s)
        )

    def _chat_completions_fallback(
        self, model: str, system: str, messages: list[dict], max_tokens: int,
        stop: list[str] | None = None, fast: bool = False, system_tail: str = "",
    ) -> str:
        client = self._get_openai()
        if system_tail:  # OpenAI 侧没有显式缓存断点，尾巴拼在 system 末尾即可（前缀缓存仍命中大头）
            system = f"{system}\n\n{system_tail}"
        msgs = [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]
        def collect(**kw):
            parts = []
            for chunk in client.chat.completions.create(
                model=model, messages=msgs, stream=True, **kw
            ):
                if not chunk.choices:
                    continue
                piece = chunk.choices[0].delta.content
                if piece:
                    parts.append(piece)
            return "".join(parts)

        extra = {"stop": list(stop)[:4]} if stop else {}   # OpenAI 侧最多 4 条
        if fast:
            extra["reasoning_effort"] = "low"
        try:
            return collect(max_completion_tokens=max_tokens, **extra)
        except Exception as e:
            # 旧后端的网关只认 max_tokens
            if "max_completion_tokens" not in str(e):
                raise
            return collect(max_tokens=max_tokens, **extra)

    @staticmethod
    def _responses_text(resp) -> str:
        """只取 message 项里的 output_text。有的中转站是拿 chat/completions 假装
        Responses API，会把模型的思考过程（reasoning）也当成正文塞进来——面试场景下
        那等于把面试官的心理活动念给候选人听。按 item 类型过一道筛。"""
        parts = []
        for item in getattr(resp, "output", None) or []:
            if getattr(item, "type", "") != "message":
                continue
            for c in getattr(item, "content", None) or []:
                if getattr(c, "type", "") == "output_text":
                    parts.append(getattr(c, "text", "") or "")
        text = "".join(parts).strip()
        return text or (getattr(resp, "output_text", "") or "")

    def _chat_openai(
        self, model: str, system: str, messages: list[dict], max_tokens: int,
        stop: list[str] | None = None, fast: bool = False, system_tail: str = "",
    ) -> str:
        if self._force_chat_completions:
            return self._chat_completions_fallback(model, system, messages, max_tokens, stop, fast, system_tail)
        client = self._get_openai()
        instructions = f"{system}\n\n{system_tail}" if system_tail else system
        try:
            # 同 Anthropic 通路：长输出走流式，避开中转站/CDN 的空闲超时
            with client.responses.stream(
                model=model,
                instructions=instructions,
                input=[{"role": m["role"], "content": m["content"]} for m in messages],
                max_output_tokens=max_tokens,
                **({"reasoning": {"effort": "low"}} if fast else {}),
            ) as stream:
                resp = stream.get_final_response()
        except Exception as e:
            if not self._responses_unsupported(e):
                raise
            self._force_chat_completions = True  # 这个网关没有 Responses API，之后直接走降级
            return self._chat_completions_fallback(model, system, messages, max_tokens, stop, fast, system_tail)
        return self._responses_text(resp)
