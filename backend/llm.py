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