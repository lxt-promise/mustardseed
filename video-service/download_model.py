"""下载 faster-whisper 模型（干净、可断点续传、校验完整性）。

针对国内网络环境做了这些事：
  1. 走 hf-mirror.com 镜像
  2. 禁用 Xet 传输后端（镜像站不支持，会 401）
  3. 禁用符号链接（Windows 普通账号无权限，会产生 0 字节空文件）
  4. 清除代理变量（clash/v2ray 常把请求打成 502）
  5. 下载后校验 model.bin 大小，不通过就报错而不是静默成功
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
MODELS.mkdir(parents=True, exist_ok=True)

# ---- 网络环境：必须在导入 huggingface_hub 之前设置 ----
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["HF_ENDPOINT"] = os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com"
os.environ["HF_HOME"] = str(MODELS)
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "120"

REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
}

# 各模型 model.bin 的期望大小（字节），用于校验是否下完整
EXPECTED_MB = {
    "tiny": 72, "base": 139, "small": 462, "medium": 1459, "large-v3": 2947,
}


def download(model_id: str, max_retries: int = 3) -> bool:
    repo = REPOS.get(model_id)
    if not repo:
        print(f"  未知模型：{model_id}（可选：{', '.join(REPOS)}）")
        return False

    print(f"  下载 {model_id}")
    print(f"    仓库：{repo}")
    print(f"    镜像：{os.environ['HF_ENDPOINT']}")
    print(f"    大小：约 {EXPECTED_MB.get(model_id, '?')} MB")

    from huggingface_hub import snapshot_download

    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                print(f"    第 {attempt} 次尝试…")
            path = snapshot_download(
                repo,
                cache_dir=str(MODELS),
                max_workers=1,          # 单线程更稳，避免被镜像限速中断
                resume_download=True,
            )
            if _verify(path, model_id):
                return True
            print("    文件不完整，重试…")
        except Exception as exc:  # noqa: BLE001
            print(f"    失败：{type(exc).__name__}: {str(exc)[:200]}")

    print(f"  ✗ {model_id} 下载失败")
    return False


def _verify(snapshot_path: str, model_id: str) -> bool:
    """校验模型是否真实可用。"""
    p = Path(snapshot_path)

    # 某些版本返回的路径可能不是最终快照目录
    if not (p / "model.bin").exists():
        cands = list(p.glob("model.bin")) or list(p.glob("**/model.bin"))
        if cands:
            p = cands[0].parent
        else:
            print(f"    ✗ 找不到 model.bin（目录：{p}）")
            return False

    model_bin = p / "model.bin"
    size = model_bin.stat().st_size
    size_mb = size / 1024 / 1024
    expect = EXPECTED_MB.get(model_id, 0)

    if size < 1024:
        print(f"    ✗ model.bin 仅 {size} 字节")
        return False

    if expect and size_mb < expect * 0.7:
        print(f"    ✗ model.bin 只有 {size_mb:.0f} MB，"
              f"少于预期的 {expect} MB，可能没下完")
        return False

    print(f"    ✓ 下载完成并校验通过")
    print(f"      model.bin = {size_mb:.1f} MB")
    print(f"      路径：{p}")
    return True


def main() -> int:
    targets = sys.argv[1:] or ["small"]
    print("=" * 58)
    print("  Whisper 模型下载")
    print("=" * 58)
    print()

    if not targets or targets == ["all"]:
        targets = list(REPOS)

    ok = True
    for m in targets:
        if not download(m):
            ok = False
        print()

    print("=" * 58)
    print("  " + ("全部完成 ✓" if ok else "部分失败 ✗"))
    print("=" * 58)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
