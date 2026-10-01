"""
手动导入 outputs 目录下的 mp4 到视频库（jobs.json）。
用法： python import_outputs.py <你的uid>
      不传 uid 则提示输入
"""
import json
import sys
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
OUTPUT_DIR = DATA_DIR / "outputs"
JOBS_DB = DATA_DIR / "jobs.json"


def main():
    uid = sys.argv[1] if len(sys.argv) > 1 else input("请输入你的 uid（浏览器 localStorage vd_uid）: ").strip()
    if not uid:
        print("uid 不能为空")
        return

    if not OUTPUT_DIR.is_dir():
        print(f"outputs 目录不存在: {OUTPUT_DIR}")
        return

    mp4s = sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp4s:
        print("outputs 目录下没有 mp4 文件")
        return

    # 读取现有 jobs.json
    existing = {"jobs": []}
    if JOBS_DB.exists():
        try:
            existing = json.loads(JOBS_DB.read_text(encoding="utf-8"))
        except Exception:
            existing = {"jobs": []}

    existing_ids = {j["id"] for j in existing.get("jobs", [])}
    existing_sources = {Path(j.get("source", "")).name for j in existing.get("jobs", [])}

    added = 0
    for f in mp4s:
        # 跳过已有同名
        if f.name in existing_sources:
            print(f"  跳过（已存在）: {f.name}")
            continue

        mtime = f.stat().st_mtime
        # 原始文件名去掉 hash 前缀和 _中文配音 后缀，尽量还原
        title = f.name
        # 例: 75277706c92eb42f696643e8491d8d85_中文配音.mp4 → 中文配音
        parts = f.stem.split("_", 1)
        display_name = parts[1] if len(parts) == 2 else f.stem

        job = {
            "id": str(uuid.uuid4())[:8],
            "filename": f"{display_name}.mp4",
            "source": str(f),
            "options": {},
            "user": uid,
            "status": "done",
            "stage": "done",
            "stage_label": "已导入",
            "progress": 1.0,
            "message": "",
            "error": "",
            "created_at": mtime,
            "finished_at": mtime,
            "media": {"duration": 0, "size": f.stat().st_size},
            "segments": [],
            "plan": {},
            "outputs": [{"kind": "video", "path": f.name, "filename": f.name}],
            "logs": [],
            "stage_timings": {},
            "total_seconds": 0,
            "published": True,
            "published_at": mtime,
        }
        existing.setdefault("jobs", []).append(job)
        added += 1
        print(f"  导入: {f.name} → {display_name}")

    if added == 0:
        print("没有新文件需要导入")
        return

    # 原子写入
    tmp = JOBS_DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
    tmp.replace(JOBS_DB)
    print(f"\n完成: 导入 {added} 个视频到视频库，所有者: {uid}")
    print("重启 video-service 后生效")


if __name__ == "__main__":
    main()
