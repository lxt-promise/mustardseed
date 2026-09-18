#!/usr/bin/env bash
# ============================================================================
# 视频译制服务（MustardSeed）- Linux 前台启动脚本
#
# 用法：  bash start.sh
# 首次运行会自动从 service.example.json 生成 service.json。
# 要给局域网其他设备使用：编辑 service.json，把 host 改成 0.0.0.0。
# 后台常驻请用 deploy/videodub.service（systemd），见 README。
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

# ---- 首次运行：从模板生成配置 ----
if [ ! -f service.json ]; then
  if [ -f service.example.json ]; then
    cp service.example.json service.json
    echo "[INFO] 已从模板生成 service.json（默认仅本机 127.0.0.1 访问）"
    echo "       局域网访问请把 host 改成 0.0.0.0 后重新启动。"
  fi
fi

# ---- 选择 Python：优先 .venv ----
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  PY="python3"
else
  echo "[ERROR] 找不到已安装依赖的 Python 环境，请先运行：bash install.sh" >&2
  exit 1
fi

if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "[ERROR] 缺少 fastapi / uvicorn，请先运行：bash install.sh" >&2
  exit 1
fi

PORT="$("$PY" -c 'import config; print(config.PORT)' 2>/dev/null || echo 8765)"
HOST="$("$PY" -c 'import config; print(config.HOST)' 2>/dev/null || echo 127.0.0.1)"

echo "============================================"
echo "  Video Dub Service (MustardSeed)"
echo "============================================"
if [ "$HOST" = "0.0.0.0" ] && command -v hostname >/dev/null 2>&1; then
  for ip in $(hostname -I 2>/dev/null); do
    echo "  局域网访问: http://$ip:$PORT"
  done
fi
echo "  本机访问:   http://127.0.0.1:$PORT/docs"
echo "  保持本窗口打开，Ctrl+C 停止服务"
echo "--------------------------------------------"

exec "$PY" run.py
