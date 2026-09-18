"""FastAPI 服务：视频配音工作台的 HTTP 接口。"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import threading
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

import asr
import config
import dubbing
import jobs as jobs_mod
import media_utils as mu
import publisher
import settings as settings_mod
from config import OUTPUT_DIR, UPLOAD_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("videodub.app")

app = FastAPI(title="视频翻译配音服务（芥末种子）", version="1.1.0")
MANAGER = jobs_mod.MANAGER

# CORS 来源在 service.json 的 cors_origins 配置（默认放开）。
# allow_private_network 让 https 页面（GitHub Pages）能访问 http://127.0.0.1，
# 响应 Chrome 私有网络访问（PNA）预检要求。
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)


@app.get("/")
async def index():
    """根路径：托管了前端（web/）时返回页面，否则返回在线信息。"""
    index_file = config.WEB_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return {"service": "videodub", "version": app.version, "docs": "/docs"}


# ================================================================ 能力探测
@app.get("/api/health")
async def health() -> dict:
    ff = mu.ffmpeg_version()
    ff_ok = config.ffmpeg_available()
    whisper_ok = True
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        whisper_ok = False

    edge_ok = True
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        edge_ok = False

    return {
        "ok": ff_ok and edge_ok,
        "ffmpeg": {"available": ff_ok, "version": ff, "path": config.FFMPEG},
        "faster_whisper": {"available": whisper_ok},
        "edge_tts": {"available": edge_ok},
        "version": app.version,
    }


@app.get("/api/options")
async def options() -> dict:
    """返回前端需要的全部可选项。"""
    voices = dubbing.list_voices()
    locales: dict[str, list[dict]] = {}
    for v in voices:
        locales.setdefault(v["locale"], []).append(v)

    locale_groups = [
        {
            "locale": loc,
            "label": config.LOCALE_NAMES.get(loc, loc),
            "voices": vs,
        }
        for loc, vs in locales.items()
    ]
    # 普通话排最前
    locale_groups.sort(key=lambda g: 0 if g["locale"] == "zh-CN" else 1)

    return {
        "voices": voices,
        "locale_groups": locale_groups,
        "default_voice": config.DEFAULT_VOICE,
        "whisper_models": asr.model_status(),
        "default_whisper_model": config.DEFAULT_WHISPER_MODEL,
        "languages": [
            {"id": "", "label": "自动检测"},
            {"id": "en", "label": "英文"},
            {"id": "zh", "label": "中文"},
            {"id": "ja", "label": "日文"},
            {"id": "ko", "label": "韩文"},
            {"id": "fr", "label": "法文"},
            {"id": "de", "label": "德文"},
            {"id": "es", "label": "西班牙文"},
            {"id": "ru", "label": "俄文"},
        ],
        "limits": {"max_upload_mb": config.MAX_UPLOAD_MB},
        "output": {
            "default_dir": str(OUTPUT_DIR),
            "dir": settings_mod.load()["output_dir"],
            "suffix": settings_mod.load()["output_suffix"],
        },
    }


# ================================================================ 输出目录
@app.get("/api/settings")
async def get_settings() -> dict:
    """读取持久化的用户偏好（输出目录等）。"""
    st = settings_mod.load()
    return {
        "settings": {k: v for k, v in st.items() if k != "recent_dirs" or True},
        "common_dirs": settings_mod.common_dirs(),
        "drives": settings_mod.drives(),
        "disk": {
            "output_free": settings_mod.dir_free_space(st["output_dir"]),
            "output_free_text": _human_size(
                max(settings_mod.dir_free_space(st["output_dir"]), 0)
            ),
        },
    }


@app.post("/api/settings")
async def save_settings(request: Request) -> dict:
    """保存用户偏好。"""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(400, "格式不正确")

    patch: dict = {}
    if "output_dir" in payload:
        path = str(payload["output_dir"] or "").strip()
        if path:
            info = _resolve_output_dir(path, create=False)
            if not info["writable"] and not info["exists"]:
                raise HTTPException(400, f"无法使用该目录：{info['reason']}")
            patch["output_dir"] = info["path"]
    if "output_suffix" in payload:
        suffix = str(payload["output_suffix"] or "").strip()
        # 去掉会导致非法文件名的字符
        suffix = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", suffix)[:40]
        patch["output_suffix"] = suffix or "_中文配音"
    if "last_voice" in payload:
        patch["last_voice"] = str(payload["last_voice"] or "")[:80]

    st = settings_mod.save(patch)
    return {"ok": True, "settings": st}


@app.get("/api/browse")
async def browse_dir(path: str = "", show_hidden: bool = False) -> dict:
    """浏览服务器本机目录，供前端选择输出位置。

    这是纯本地应用，所以允许浏览整个文件系统；但会过滤掉无权限的目录。
    """
    if path in ("", "root", "此电脑"):
        return {
            "path": "",
            "parent": "",
            "is_root": True,
            "drives": settings_mod.drives(),
            "dirs": [],
        }

    target = Path(path)
    if not target.exists():
        raise HTTPException(404, f"目录不存在：{path}")
    if not target.is_dir():
        target = target.parent

    dirs: list[dict] = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            name = child.name
            if not show_hidden and (name.startswith(".") or name.startswith("$")):
                continue
            dirs.append({
                "name": name,
                "path": str(child),
                "writable": _writable(child),
            })
    except PermissionError:
        raise HTTPException(403, "没有权限访问该目录") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"无法读取目录：{exc}") from exc

    parent = str(target.parent) if target.parent != target else ""
    return {
        "path": str(target),
        "parent": parent,
        "is_root": False,
        "writable": _writable(target),
        "free": settings_mod.dir_free_space(str(target)),
        "free_text": _human_size(
            max(settings_mod.dir_free_space(str(target)), 0)
        ),
        "dirs": dirs[:500],
    }


@app.post("/api/mkdir")
async def make_dir(request: Request) -> dict:
    """在指定父目录下新建子文件夹。"""
    payload = await request.json()
    parent = str(payload.get("parent") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not parent or not name:
        raise HTTPException(400, "缺少目录名")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    if not name:
        raise HTTPException(400, "目录名不合法")

    target = Path(parent) / name
    try:
        target.mkdir(parents=False, exist_ok=False)
    except FileExistsError:
        raise HTTPException(400, "该文件夹已存在") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"创建失败：{exc}") from exc

    return {"ok": True, "path": str(target)}


@app.post("/api/open-folder")
async def open_folder(request: Request) -> dict:
    """在系统的文件管理器里打开目录。"""
    payload = {}
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}

    raw = str(payload.get("path") or "").strip()
    target = Path(raw) if raw else None
    if target and target.is_file():        # 传文件则选中它
        _reveal_file(target)
        return {"ok": True}
    if not target or not target.is_dir():
        raise HTTPException(400, "目录不存在")

    try:
        if os.name == "nt":
            os.startfile(str(target))      # noqa: S606
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(target)])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"打开失败：{exc}") from exc
    return {"ok": True}


def _reveal_file(path: Path) -> None:
    """在文件管理器中定位并选中某个文件。"""
    try:
        if os.name == "nt":
            import subprocess
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception as exc:  # noqa: BLE001
        log.warning("定位文件失败：%s", exc)


def _writable(path: Path) -> bool:
    """探测目录是否可写。

    用 os.access 做权限判断而不是「建个临时文件再删」：
    后者会在目录里留下垃圾文件，删除失败还会误判成只读。
    """
    try:
        if not path.is_dir():
            return False
        return os.access(str(path), os.W_OK)
    except Exception:  # noqa: BLE001
        return False


def _resolve_output_dir(raw: str, create: bool = True) -> dict:
    """校验输出目录，必要时创建。

    返回 {path, exists, writable, created, reason}
    """
    try:
        p = Path(raw).expanduser()
        if create:
            p.mkdir(parents=True, exist_ok=True)
        exists = p.is_dir()
        if not exists:
            return {
                "path": str(p), "exists": False, "writable": False,
                "created": False, "reason": "目录不存在且无法创建",
            }
        if not _writable(p):
            return {
                "path": str(p), "exists": True, "writable": False,
                "created": False, "reason": "目录不可写入（权限不足）",
            }
        return {
            "path": str(p), "exists": True, "writable": True,
            "created": create, "reason": "",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "path": str(raw), "exists": False, "writable": False,
            "created": False, "reason": str(exc),
        }


# ================================================================ 上传
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(400, "没有选择文件")

    suffix = Path(file.filename).suffix.lower()
    allowed = {
        ".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".webm", ".m4v",
        ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".rmvb", ".vob",
    }
    if suffix and suffix not in allowed:
        raise HTTPException(400, f"不支持的视频格式：{suffix}")

    safe_name = f"{jobs_mod._safe_stem(file.filename)}{suffix or '.mp4'}"
    dest = UPLOAD_DIR / f"{jobs_mod._safe_stem(file.filename)}_{_short_id()}{suffix or '.mp4'}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    with dest.open("wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024 * 4)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                fh.close()
                mu.safe_unlink(dest)
                raise HTTPException(413, f"文件超过 {config.MAX_UPLOAD_MB} MB 上限")
            fh.write(chunk)

    if size == 0:
        mu.safe_unlink(dest)
        raise HTTPException(400, "文件内容为空")

    # 探测媒体信息，用于前端提示
    try:
        info = mu.probe(dest)
        meta = {
            "duration": round(info.duration, 2),
            "resolution": info.resolution,
            "has_video": info.has_video,
            "has_audio": info.has_audio,
            "subtitle_streams": len(info.subtitle_streams),
            "subtitle_names": [
                s.get("title") or s.get("language") or f"流{s.get('index')}"
                for s in info.subtitle_streams
            ],
        }
    except Exception as exc:  # noqa: BLE001
        mu.safe_unlink(dest)
        raise HTTPException(400, f"无法读取视频，文件可能损坏：{exc}") from exc

    if not meta["has_video"]:
        mu.safe_unlink(dest)
        raise HTTPException(400, "这个文件不含视频轨道")

    return {
        "filename": file.filename,
        "stored_name": dest.name,
        "path": str(dest),
        "size": size,
        "size_text": _human_size(size),
        "meta": meta,
    }


@app.post("/api/upload-subtitle")
async def upload_subtitle(file: UploadFile = File(...)) -> dict:
    """可选：上传外挂字幕。"""
    if not file.filename:
        raise HTTPException(400, "没有选择文件")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".srt", ".vtt", ".ass", ".ssa"}:
        raise HTTPException(400, "字幕只支持 srt / vtt / ass")

    dest = UPLOAD_DIR / f"subtitle_{_short_id()}{suffix}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    try:
        segs = MANAGER._from_srt(dest)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        mu.safe_unlink(dest)
        raise HTTPException(400, f"字幕解析失败：{exc}") from exc

    if not segs:
        mu.safe_unlink(dest)
        raise HTTPException(400, "字幕里没有解析到有效内容")

    return {
        "filename": file.filename,
        "path": str(dest),
        "count": len(segs),
        "preview": [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text}
            for s in segs[:5]
        ],
    }


# ================================================================ 任务
@app.post("/api/jobs")
async def create_job(request: Request) -> dict:
    payload = await request.json()

    video_path = Path(payload.get("video_path") or "")
    if not video_path.exists():
        raise HTTPException(400, "视频文件不存在，请重新上传")

    options = _normalize_options(payload)

    job = MANAGER.create(payload.get("filename") or video_path.name, video_path, options)
    MANAGER.start(job)
    return {"id": job.id, "status": job.status}


@app.get("/api/jobs")
async def list_jobs() -> dict:
    return {
        "jobs": [j.to_dict(with_segments=False) for j in MANAGER.list()[:50]],
        "stages": [{"key": k, "label": v} for k, v in jobs_mod.STAGES],
        "disk": jobs_mod.disk_usage(),
    }


@app.get("/api/jobs/{jid}")
async def get_job(jid: str) -> dict:
    job = MANAGER.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job.to_dict()


@app.post("/api/jobs/{jid}/cancel")
async def cancel_job(jid: str) -> dict:
    if not MANAGER.cancel(jid):
        raise HTTPException(400, "任务无法取消（可能已结束）")
    return {"ok": True}


@app.delete("/api/jobs/{jid}")
async def delete_job(jid: str) -> dict:
    if not MANAGER.remove(jid):
        raise HTTPException(400, "任务正在运行，无法删除")
    return {"ok": True}


@app.post("/api/translate-preview")
async def translate_preview(request: Request) -> dict:
    """试听：把一段文本用指定音色合成为 mp3，直接返回音频流。"""
    payload = await request.json()
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "请输入要试听的文本")
    if len(text) > 400:
        text = text[:400]

    voice = payload.get("voice") or config.DEFAULT_VOICE
    if voice not in config.VOICE_META:
        raise HTTPException(400, "不支持的音色")

    tmp = config.TMP_DIR / f"preview_{_short_id()}.mp3"
    try:
        # 用异步版本，避免在 FastAPI 的事件循环里嵌套 asyncio.run
        await dubbing.synthesize_async(
            text, voice, tmp,
            rate_percent=int(payload.get("rate", 0)),
            volume_percent=int(payload.get("volume", 0)),
            pitch_hz=int(payload.get("pitch", 0)),
        )
        data = tmp.read_bytes()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"试听合成失败：{exc}") from exc
    finally:
        mu.safe_unlink(tmp)

    return Response(content=data, media_type="audio/mpeg")


@app.get("/api/voices")
async def voices() -> dict:
    return {"voices": dubbing.list_voices()}


# ================================================================ 模型管理
@app.get("/api/models")
async def models() -> dict:
    """各 Whisper 模型的本地可用状态。"""
    return {"models": asr.model_status()}


@app.post("/api/models/download")
async def download_model(request: Request) -> dict:
    """在后台下载指定 Whisper 模型，进度通过 /api/models/progress 查询。"""
    payload = await request.json()
    model_id = payload.get("model") or config.DEFAULT_WHISPER_MODEL

    valid = {m["id"] for m in config.WHISPER_MODELS}
    if model_id not in valid:
        raise HTTPException(400, f"不支持的模型：{model_id}")

    if asr.is_model_downloaded(model_id):
        return {"ok": True, "message": "该模型已在本地", "already": True}

    with _DOWNLOAD_LOCK:
        if _DOWNLOAD_STATE.get("running"):
            return {
                "ok": False,
                "message": f"正在下载 {_DOWNLOAD_STATE.get('model')}，请稍候",
                "running": True,
            }
        _DOWNLOAD_STATE.update({
            "running": True, "model": model_id, "progress": 0.0,
            "message": "准备下载…", "error": "", "done": False,
        })

    threading.Thread(
        target=_download_worker, args=(model_id,), daemon=True
    ).start()

    return {"ok": True, "model": model_id, "message": "已开始下载"}


@app.get("/api/models/progress")
async def model_progress() -> dict:
    with _DOWNLOAD_LOCK:
        return dict(_DOWNLOAD_STATE)


_DOWNLOAD_LOCK = threading.Lock()
_DOWNLOAD_STATE: dict = {
    "running": False, "model": "", "progress": 0.0,
    "message": "", "error": "", "done": False,
}


def _download_worker(model_id: str) -> None:
    """后台下载模型（复用 download_model.py 的环境设置）。"""
    import download_model as dm

    def note(pct: float, msg: str) -> None:
        with _DOWNLOAD_LOCK:
            _DOWNLOAD_STATE["progress"] = pct
            _DOWNLOAD_STATE["message"] = msg

    try:
        note(0.05, f"正在下载 {model_id} 模型…")
        ok = dm.download(model_id, max_retries=2)
        with _DOWNLOAD_LOCK:
            if ok:
                _DOWNLOAD_STATE.update({
                    "running": False, "done": True, "progress": 1.0,
                    "message": f"{model_id} 下载完成",
                })
            else:
                _DOWNLOAD_STATE.update({
                    "running": False, "done": False, "error": "下载失败",
                    "message": "下载失败，请检查网络或改用云端识别",
                })
    except Exception as exc:  # noqa: BLE001
        log.exception("模型下载失败")
        with _DOWNLOAD_LOCK:
            _DOWNLOAD_STATE.update({
                "running": False, "done": False,
                "error": str(exc), "message": f"下载失败：{exc}",
            })


# ================================================================ 文件下载
@app.get("/api/download/{jid}/{kind}")
async def download(jid: str, kind: str):
    job = MANAGER.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")

    if kind == "source":
        path = job.source
    else:
        # kind 支持索引或文件名
        target = None
        for i, o in enumerate(job.outputs):
            if kind == str(i) or kind == o["name"]:
                target = Path(o["path"])
                break
        if target is None:
            raise HTTPException(404, "找不到该产物")
        path = target

    if not path.exists():
        raise HTTPException(404, "文件已被清理")

    return FileResponse(
        path,
        filename=path.name,
        media_type=_media_type(path),
        headers={"Content-Disposition": _content_disposition(path.name)},
    )


@app.get("/api/preview/{jid}")
async def preview_video(jid: str, which: int = 0):
    """在线预览产物（用于 <video> 播放）。"""
    job = MANAGER.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")
    videos = [o for o in job.outputs if o["kind"] == "video"]
    if not videos:
        raise HTTPException(404, "还没有生成视频")
    which = max(0, min(which, len(videos) - 1))
    path = Path(videos[which]["path"])
    if not path.exists():
        raise HTTPException(404, "文件已被清理")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/preview-source/{jid}")
async def preview_source(jid: str):
    """在线预览原始视频（浏览器不支持的格式会自动转码）。"""
    job = MANAGER.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")

    info = mu.probe(job.source)
    playable = info.format_name and any(
        k in info.format_name for k in ("mp4", "webm", "mov")
    ) and info.video_codec in ("h264", "vp8", "vp9", "av1")

    if playable:
        return FileResponse(job.source, media_type="video/mp4")

    # 转一份预览版，缓存起来
    cache = config.TMP_DIR / f"preview_{job.id}.mp4"
    if not cache.exists():
        try:
            mu.normalize_for_web(job.source, cache)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"预览转码失败：{exc}") from exc
    return FileResponse(cache, media_type="video/mp4")


@app.get("/api/thumbnail/{jid}")
async def thumbnail(jid: str, at: float = 1.0):
    job = MANAGER.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")
    cache = config.TMP_DIR / f"thumb_{job.id}_{at:.0f}.jpg"
    if not cache.exists():
        try:
            mu.make_thumbnail(job.source, cache, at=at)
        except Exception:  # noqa: BLE001
            raise HTTPException(404, "无法生成缩略图") from None
    return FileResponse(cache, media_type="image/jpeg")


@app.get("/api/audio/{jid}")
async def preview_audio(jid: str):
    """预览生成的配音音轨。"""
    path = config.WORK_DIR / jid / "dub_full.wav"
    if not path.exists():
        raise HTTPException(404, "配音音轨尚未生成")
    return FileResponse(path, media_type="audio/wav")


# ================================================================ 作品库发布
@app.get("/api/publish/config")
async def publish_config() -> dict:
    """作品库发布的公开配置（不返回 token）。"""
    return publisher.publish_info()


@app.post("/api/publish/{jid}")
async def publish_work(jid: str, request: Request) -> dict:
    """把任务成片发布到 GitHub 作品库（上传可能耗时，放线程里跑）。"""
    job = MANAGER.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")

    payload = {}
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    title = str(payload.get("title") or "")[:80]
    note = str(payload.get("note") or "")[:200]
    try:
        index = int(payload.get("index", 0))
    except (TypeError, ValueError):
        index = 0

    try:
        work = await asyncio.to_thread(
            publisher.publish_video, job, index, title, note
        )
    except publisher.PublishError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True, "work": work}


@app.delete("/api/publish/works/{wid}")
async def unpublish_work(wid: str) -> dict:
    """从作品库下架（删资产 + 更新清单）。"""
    try:
        return {"ok": True, **await asyncio.to_thread(publisher.unpublish, wid)}
    except publisher.PublishError as exc:
        raise HTTPException(400, str(exc)) from None


# ================================================================ 文稿编辑
@app.post("/api/segments/{jid}")
async def update_segments(jid: str, request: Request) -> dict:
    """保存用户手工修改的字幕文本（在重新合成前调用）。"""
    job = MANAGER.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")
    payload = await request.json()
    segs = payload.get("segments")
    if not isinstance(segs, list):
        raise HTTPException(400, "格式不正确")

    cleaned = []
    for s in segs:
        try:
            cleaned.append({
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "text": str(s.get("text", "")),
                "translated": str(s.get("translated", "")),
            })
        except (TypeError, ValueError):
            continue
    job.options["edited_segments"] = cleaned
    job.segments = cleaned
    return {"ok": True, "count": len(cleaned)}


@app.post("/api/redo/{jid}")
async def redo_job(jid: str, request: Request) -> dict:
    """用当前选项重跑一遍（复用已上传的视频）。"""
    job = MANAGER.get(jid)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job.status == "running":
        raise HTTPException(400, "任务正在运行中")

    payload = {}
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}

    merged = dict(job.options)
    merged.update(_normalize_options({**job.options, **payload}))
    # payload 显式带 edited_segments 才覆盖（改稿重跑）；
    # 否则丢掉旧任务里可能残留的，避免旧稿反复生效
    if "edited_segments" not in payload:
        merged.pop("edited_segments", None)

    new_job = MANAGER.create(job.filename, job.source, merged)
    MANAGER.start(new_job)
    return {"id": new_job.id, "status": new_job.status}


# ================================================================ 工具
_OPTION_KEYS = {
    "engine", "whisper_model", "source_language", "translate_to_zh",
    "cloud_base_url", "cloud_api_key", "cloud_asr_model",
    "translate_base_url", "translate_api_key", "translate_model",
    "translate_provider", "merge_sentences",
    "voice", "rate", "volume", "pitch", "auto_fit",
    "burn_subtitle", "soft_subtitle", "bilingual", "keep_original_audio",
    "original_volume", "use_embedded_subtitle", "subtitle_file",
    "subtitles_already_zh", "ocr_hard_subtitle",
    "bgm_mode", "bgm_volume", "bgm_ducking",
    "output_suffix", "output_dir", "edited_segments",
}


def _normalize_options(payload: dict) -> dict:
    """只保留白名单字段，并对数值做范围限制。"""
    out: dict = {}
    for k in _OPTION_KEYS:
        if k in payload:
            out[k] = payload[k]

    out["engine"] = "cloud" if out.get("engine") == "cloud" else "local"

    model = out.get("whisper_model", config.DEFAULT_WHISPER_MODEL)
    valid_models = {m["id"] for m in config.WHISPER_MODELS}
    out["whisper_model"] = model if model in valid_models else config.DEFAULT_WHISPER_MODEL

    voice = out.get("voice", config.DEFAULT_VOICE)
    out["voice"] = voice if voice in config.VOICE_META else config.DEFAULT_VOICE

    out["rate"] = _clamp(out.get("rate", 0), -50, 100)
    out["volume"] = _clamp(out.get("volume", 0), -100, 100)
    out["pitch"] = _clamp(out.get("pitch", 0), -50, 50)
    out["original_volume"] = _clamp_f(out.get("original_volume", 0.08), 0.0, 1.0)

    # 背景音模式：off/original/instrumental（旧客户端只传 keep_original_audio）
    bgm_mode = str(out.get("bgm_mode", "") or "").strip()
    if bgm_mode not in ("off", "original", "instrumental"):
        bgm_mode = "original" if out.get("keep_original_audio") else "off"
    out["bgm_mode"] = bgm_mode
    if out.get("bgm_volume") is not None:
        out["bgm_volume"] = _clamp_f(out.get("bgm_volume"), 0.0, 1.0)
    out["bgm_ducking"] = bool(out.get("bgm_ducking", True))

    for flag in (
        "translate_to_zh", "auto_fit", "burn_subtitle", "soft_subtitle",
        "bilingual", "keep_original_audio", "use_embedded_subtitle",
    ):
        out[flag] = bool(out.get(flag, _FLAG_DEFAULTS[flag]))

    out.setdefault("output_suffix", "_中文配音")

    # 输出目录：留空则用默认目录；不可用时回退默认目录（管线里还会再兜一次）
    raw_dir = str(out.get("output_dir") or "").strip()
    if raw_dir:
        info = _resolve_output_dir(raw_dir, create=True)
        if info["writable"]:
            out["output_dir"] = info["path"]
        else:
            log.warning("输出目录不可用，回退默认目录：%s（%s）",
                        raw_dir, info["reason"])
            out["output_dir"] = str(OUTPUT_DIR)
            out["output_dir_fallback"] = info["reason"]
    else:
        out["output_dir"] = str(OUTPUT_DIR)

    # 记住用户选过的目录，下次自动带上
    if out["output_dir"] != str(OUTPUT_DIR):
        try:
            settings_mod.save({"output_dir": out["output_dir"]})
        except Exception:  # noqa: BLE001
            pass

    return out


_FLAG_DEFAULTS = {
    "translate_to_zh": True,
    "auto_fit": True,
    "burn_subtitle": True,
    "soft_subtitle": False,
    "bilingual": False,
    "keep_original_audio": False,
    "use_embedded_subtitle": False,
}


def _clamp(value, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return 0


def _clamp_f(value, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return lo


def _short_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def _media_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".mov": "video/quicktime",
        ".webm": "video/webm", ".srt": "application/x-subrip",
        ".vtt": "text/vtt", ".txt": "text/plain; charset=utf-8",
        ".wav": "audio/wav", ".mp3": "audio/mpeg",
    }.get(ext, "application/octet-stream")


def _content_disposition(name: str) -> str:
    """正确处理中文文件名下载。"""
    quoted = urllib.parse.quote(name)
    return f"attachment; filename=\"{quoted}\"; filename*=UTF-8''{quoted}"


# ---------------------------------------------------------------- 前端静态托管
# 把构建好的前端（frontend/dist 的内容）放进 config.WEB_DIR（默认 ./web），
# 服务即同源提供页面，浏览器直接访问 http://<host>:<port>/。
# 必须在所有 API 路由之后挂载，未匹配 /api 的请求才落到静态文件。
if (config.WEB_DIR / "index.html").is_file():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(config.WEB_DIR), html=True), name="web")
    log.info("已托管前端目录：%s", config.WEB_DIR)


@app.on_event("startup")
async def _startup() -> None:
    jobs_mod.cleanup_uploads()
    log.info("ffmpeg: %s", mu.ffmpeg_version())
    log.info("服务已启动：http://%s:%s", config.HOST, config.PORT)


def main() -> None:
    import uvicorn
    uvicorn.run(
        "app:app",
        host=config.HOST,
        port=config.PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
