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

