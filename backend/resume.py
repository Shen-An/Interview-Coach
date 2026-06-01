"""简历解析：PDF / DOCX / TXT / MD -> 纯文本。"""
from __future__ import annotations

import io
import re

MAX_CHARS = 20000  # 超长简历截断，避免撑爆上下文


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n（简历过长，已截断）"
    return text

