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
