"""PyInstaller 打包入口。Electron 通过 IC_RES_DIR / IC_DATA_DIR / IC_PORT 注入路径与端口。"""
import os

import uvicorn

from backend.app import app

if __name__ == "__main__":
    port = int(os.environ.get("IC_PORT", "47821"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
