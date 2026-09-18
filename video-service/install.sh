#!/usr/bin/env bash
# ============================================================================
# 视频译制服务（MustardSeed）- Ubuntu/Debian 一键环境安装
#
# 用法：  bash install.sh
# 做的事：
#   1. 检查 Python 3.10+
#   2. apt 安装 ffmpeg / fonts-noto-cjk / python3-venv（缺啥装啥）
#   3. 创建 .venv 并 pip 安装 requirements.txt（清华镜像，失败回退官方源）
#   4. 首次运行从 service.example.json 生成 service.json，可选开放局域网访问
# 重新运行本脚本是安全的（已装的项会跳过）。
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

VENV_DIR=".venv"
PY_BIN="${PYTHON:-python3}"
PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

info() { printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[ OK ]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[WARN]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[ERR ]\033[0m %s\n' "$*" >&2; }

echo "============================================"
echo "  Video Dub Service - 环境安装 (Linux)"
echo "============================================"

# ------------------------------------------------------------ 1. Python 检查
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  err "未找到 $PY_BIN。请先安装 Python 3.10+："
  echo "      sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi
if ! "$PY_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  ver="$("$PY_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  err "需要 Python 3.10+，当前为 $ver。"
  echo "      Ubuntu 22.04 自带 3.10、24.04 自带 3.12，可通过 apt 或 deadsnakes PPA 升级。"
  exit 1
fi
ok "Python $("$PY_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

# ------------------------------------------------------------ 2. 系统依赖
# 收集本机缺失的 apt 包；非 Debian 系（无 apt-get）仅提示。
APT_PKGS=()
if ! "$PY_BIN" -c 'import venv, ensurepip' >/dev/null 2>&1; then
  APT_PKGS+=("python3-venv")
fi
command -v ffmpeg >/dev/null 2>&1 || APT_PKGS+=("ffmpeg")
if command -v fc-list >/dev/null 2>&1; then
  # 烧中文字幕必须有 CJK 字体，否则字幕是方块或烧录失败
  if ! fc-list :lang=zh family 2>/dev/null | grep -q .; then
    APT_PKGS+=("fonts-noto-cjk")
  fi
else
  APT_PKGS+=("fontconfig" "fonts-noto-cjk")
fi

if [ "${#APT_PKGS[@]}" -gt 0 ]; then
  if command -v apt-get >/dev/null 2>&1; then
    info "将通过 apt 安装系统依赖：${APT_PKGS[*]}"
    echo "      （需要 sudo 权限，可能提示输入密码）"
    sudo apt-get update
    sudo apt-get install -y "${APT_PKGS[@]}"
  else
    warn "未检测到 apt-get，请手动安装这些包：${APT_PKGS[*]}"
    warn "ffmpeg 与中文字体（Noto CJK）是烧录中文字幕的必需项。"
  fi
else
  ok "系统依赖（ffmpeg / 中文字体）已就绪"
fi

# ------------------------------------------------------------ 3. 虚拟环境
if [ ! -x "$VENV_DIR/bin/python" ]; then
  info "创建虚拟环境 $VENV_DIR ..."
  if ! "$PY_BIN" -m venv "$VENV_DIR"; then
    err "创建虚拟环境失败，请安装：sudo apt install -y python3-venv python3-pip"
    exit 1
  fi
fi
VPY="$VENV_DIR/bin/python"

info "升级 pip ..."
"$VPY" -m pip install --upgrade pip -i "$PIP_MIRROR" \
  || "$VPY" -m pip install --upgrade pip

info "安装 Python 依赖（requirements.txt）..."
if ! "$VPY" -m pip install -r requirements.txt -i "$PIP_MIRROR"; then
  warn "清华镜像安装失败，回退官方 PyPI 重试 ..."
  "$VPY" -m pip install -r requirements.txt
fi
ok "Python 依赖安装完成"

# ------------------------------------------------------------ 4. 配置文件
if [ ! -f service.json ]; then
  if [ -f service.example.json ]; then
    cp service.example.json service.json
    ok "已从模板生成 service.json"
    if [ -t 0 ]; then
      read -r -p "是否允许局域网内其他设备访问（host 改为 0.0.0.0）？[Y/n] " ans || true
      case "${ans:-Y}" in
        [Nn]*) info "保持仅本机访问（127.0.0.1），以后可手动编辑 service.json" ;;
        *)
          "$VPY" - <<'PY'
import json
p = "service.json"
with open(p, encoding="utf-8") as f:
    d = json.load(f)
d["host"] = "0.0.0.0"
with open(p, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
PY
          ok "已设置 host=0.0.0.0（局域网可访问，记得用 ufw 放行端口）"
          ;;
      esac
    else
      info "非交互模式：保持模板默认 host=127.0.0.1。"
      info "需要局域网访问时，把 service.json 里的 host 改成 0.0.0.0 后重启服务。"
    fi
  fi
else
  info "service.json 已存在，保留不动"
fi

# ------------------------------------------------------------ 5. 结果自检
if "$VPY" -c "import config; assert config.ffmpeg_available()" >/dev/null 2>&1; then
  ok "ffmpeg 探测通过"
else
  warn "ffmpeg 仍未被探测到，可稍后运行 $VPY selftest.py 排查。"
fi
if command -v fc-list >/dev/null 2>&1 && fc-list :lang=zh family 2>/dev/null | grep -q .; then
  ok "中文字体已就绪（烧录中文字幕正常）"
else
  warn "未检测到中文字体：sudo apt install -y fonts-noto-cjk"
fi

echo
echo "============================================"
ok "安装完成"
echo "  前台启动：  bash start.sh"
echo "  后台服务：  见 README.md「Ubuntu 部署」（systemd）"
echo "  接口文档：  http://127.0.0.1:8765/docs"
echo "============================================"
