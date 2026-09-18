#!/usr/bin/env bash
# ============================================================================
# 打包 Linux（Ubuntu）源码部署包 -> ../video-service-linux.tar.gz
#
# 用法（Linux 或 Windows 的 Git Bash 均可）：
#   bash pack.sh                  # 不含模型（首启自动从镜像下载）
#   INCLUDE_MODELS=1 bash pack.sh # 连 models/ 一起打包（包更大，部署免下载）
#
# 部署机拿到后：tar xzf video-service-linux.tar.gz && cd video-service
#               bash install.sh && bash start.sh
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

INCLUDE_MODELS="${INCLUDE_MODELS:-0}"

SRC_NAME="$(basename "$PWD")"          # 通常是 video-service
PARENT="$(dirname "$PWD")"
OUT="$PARENT/video-service-linux.tar.gz"

info() { printf '[INFO] %s\n' "$*"; }

echo "============================================"
echo "  构建 Linux 部署包 (tar.gz)"
echo "============================================"

EXCLUDES=(
  --exclude="$SRC_NAME/venv"
  --exclude="$SRC_NAME/.venv"
  --exclude="$SRC_NAME/data"
  --exclude="$SRC_NAME/python"        # Windows 便携 Python，Linux 不可用
  --exclude="$SRC_NAME/ffmpeg"        # Windows ffmpeg，Linux 用 apt 装
  --exclude="$SRC_NAME/.git"
  --exclude="$SRC_NAME/service.json"  # 机器相关配置，部署时从模板生成
  --exclude="$SRC_NAME/video-service-linux.tar.gz"
  --exclude="*/__pycache__"
  --exclude="*.pyc"
  --exclude="*.pyo"
  --exclude="*.log"
  --exclude="*.tmp"
)
if [ "$INCLUDE_MODELS" != "1" ]; then
  EXCLUDES+=(--exclude="$SRC_NAME/models")
  EXCLUDES+=(--exclude="$SRC_NAME/models_retry")
  info "不包含模型（INCLUDE_MODELS=1 bash pack.sh 可连模型一起打包）"
else
  info "包含 models/ 模型目录"
fi

if [ ! -d web ]; then
  info "web/ 不存在（未放入前端构建产物）：部署后仅提供 API。"
  info "如需同源托管页面，把 frontend/dist 的内容拷到 web/ 后重新打包。"
fi

info "打包中 ..."
rm -f "$OUT"
tar -czf "$OUT" "${EXCLUDES[@]}" -C "$PARENT" "$SRC_NAME"

SIZE="$(du -h "$OUT" | cut -f1)"
echo
echo "完成: $OUT  ($SIZE)"
echo
echo "部署：scp 到 Ubuntu 后  tar xzf video-service-linux.tar.gz"
echo "      cd $SRC_NAME && bash install.sh && bash start.sh"
