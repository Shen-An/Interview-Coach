"""知识库管理：播种到可写目录、导入日更文件并用配置的 LLM 蒸馏为增量情报。"""
from __future__ import annotations

import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

UPDATES_NAME = "UPDATES.md"
UPDATES_HEADER = "# 知识库增量情报（导入面经日更文件蒸馏生成，面试官优先使用）\n"
# 这一个数字同时管三件事，不许再各管各的：文件保留多少、去重时回看多少、注入提示词多少。
# 三者相等 =「存下来的」永远等于「用得上的」。之前是 80000/12000/30000，导致 4 天前的内容
# 会被当新的重复收录，10 天前的躺在文件里却永远进不了提示词。
# 之所以敢全量注入：提示词命中缓存，实测 1.6 万 token 和 20 token 的延迟一样。
MAX_UPDATES_CHARS = 60000   # UPDATES.md 总量上限（保新弃旧），约 20 天
# 注入提示词的「正文」只取最近这么多字符，更早的只在目录里留一行摘要。
# 不是怕撑爆窗口（跑满也才 ~71k tokens，对 1M 窗口是 7%），是怕稀释：
# 情报 55k 压着人格卡+题库 16k，面试官的注意力会被面经带偏。
INTEL_BODY_CHARS = 20000    # 约 7 天的全文
MAX_IMPORT_CHARS = 300000   # 单次导入原文上限
