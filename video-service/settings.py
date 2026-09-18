"""用户设置的持久化。

只保存不带敏感信息的偏好项，例如输出目录、最近用过的目录。
API Key 之类的凭据一律不落盘（前端自己保存在 localStorage，也不回传）。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from config import DATA_DIR, OUTPUT_DIR

log = logging.getLogger("videodub.settings")

SETTINGS_FILE = DATA_DIR / "settings.json"

_LOCK = threading.Lock()

DEFAULTS: dict = {
    "output_dir": str(OUTPUT_DIR),
    "recent_dirs": [],
    "last_voice": "",
    "output_suffix": "_中文配音",
}

# 最近目录最多记多少个
MAX_RECENT = 8


def load() -> dict:
    """读取设置，缺失或损坏时返回默认值。"""
    data = dict(DEFAULTS)
    try:
        if SETTINGS_FILE.exists():
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in DEFAULTS:
                        data[k] = v
    except Exception as exc:  # noqa: BLE001
        log.warning("读取设置失败，使用默认值：%s", exc)

    # 输出目录若已不存在，回退到默认目录，避免前端显示一个失效路径
    out = str(data.get("output_dir") or "").strip()
    if not out or not _is_dir(out):
        data["output_dir"] = str(OUTPUT_DIR)

    recent = data.get("recent_dirs")
    if not isinstance(recent, list):
        recent = []
    data["recent_dirs"] = [str(p) for p in recent if _is_dir(str(p))][:MAX_RECENT]
    return data


def save(patch: dict) -> dict:
    """合并保存设置，返回合并后的完整设置。"""
    with _LOCK:
        current = load()
        for k, v in patch.items():
            if k in DEFAULTS:
                current[k] = v

        if current["output_dir"]:
            remember_dir(current, current["output_dir"])

        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(current, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("保存设置失败：%s", exc)
        return current


def remember_dir(state: dict, path: str) -> None:
    """把用过的目录提到最近列表最前面（去重、限长）。"""
    try:
        p = str(Path(path).resolve())
    except Exception:  # noqa: BLE001
        return
    recent = [d for d in state.get("recent_dirs", []) if d != p]
    recent.insert(0, p)
    state["recent_dirs"] = recent[:MAX_RECENT]


def _is_dir(path: str) -> bool:
    try:
        return Path(path).is_dir()
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ 快捷目录
def common_dirs() -> list[dict]:
    """返回一些用户常用的目录，方便一键选择。"""
    home = Path.home()
    candidates = [
        ("桌面", home / "Desktop"),
        ("下载", home / "Downloads"),
        ("视频", home / "Videos"),
        ("文档", home / "Documents"),
        ("默认输出目录", OUTPUT_DIR),
    ]
    out: list[dict] = []
    for label, p in candidates:
        try:
            if p.is_dir():
                out.append({"label": label, "path": str(p.resolve())})
        except Exception:  # noqa: BLE001
            continue
    return out


def drives() -> list[dict]:
    """列出本机可用盘符（Windows）。"""
    out: list[dict] = []
    if os.name != "nt":
        out.append({"label": "根目录", "path": "/"})
        return out
    import string

    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if Path(root).exists():
                out.append({"label": f"{letter}: 盘", "path": root})
        except Exception:  # noqa: BLE001
            continue
    return out


def dir_free_space(path: str) -> int:
    """目录所在磁盘的剩余空间（字节），取不到返回 -1。"""
    try:
        target = Path(path)
        while not target.exists() and target.parent != target:
            target = target.parent
        usage = __import__("shutil").disk_usage(str(target))
        return int(usage.free)
    except Exception:  # noqa: BLE001
        return -1
