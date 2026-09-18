"""统一启动入口：python run.py

host / port 等全部从 service.json（或环境变量）读取，
部署到其他电脑时无需改任何代码或脚本，双击 start.bat 等价于运行本文件。
"""
from __future__ import annotations

import uvicorn

import config

if __name__ == "__main__":
    print(f"[video-service] listening on http://{config.HOST}:{config.PORT}")
    print(f"[video-service] ffmpeg: {config.FFMPEG}")
    print(f"[video-service] models: {config.MODEL_DIR}")
    uvicorn.run("app:app", host=config.HOST, port=config.PORT, log_level="info")
