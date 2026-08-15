import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("IC_PORT", "47821"))
    print(f"interview-coach: http://127.0.0.1:{port}  (Edge/Chrome 打开，语音功能需要这两种浏览器)")
    uvicorn.run("backend.app:app", host="127.0.0.1", port=port)
