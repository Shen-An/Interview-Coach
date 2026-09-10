"""Shared validation for URLs exposed by local API responses."""
from __future__ import annotations

from urllib.parse import urlparse


def safe_http_url(value: object) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
        return url if parsed.scheme in ("http", "https") and parsed.hostname else ""
    except ValueError:
        return ""
