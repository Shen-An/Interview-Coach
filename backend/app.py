"""interview-coach 后端：FastAPI + 会话管理 + 复盘存档。

启动：uvicorn backend.app:app --port 47821（或 python start.py）
前端静态页由本服务直接托管，浏览器访问 http://127.0.0.1:47821
（打包版由 Electron 动态挑空闲端口注入 IC_PORT，不占固定端口）
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
