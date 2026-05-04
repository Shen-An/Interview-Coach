"""从 kb/ 加载人格卡、题库、评分细则，按候选人身份与简历拼装提示词。"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import kb

KB_DIR = Path(os.environ.get("IC_KB_DIR", Path(__file__).resolve().parent.parent / "kb"))

