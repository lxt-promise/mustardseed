"""把配音成品发布到 GitHub 作品库。

链路（全程在用户本机执行，Token 不出本机）：
1. 视频 / 封面上传到仓库的一个固定 Release（tag 默认 ``works``）的资产，
   资产直链形如 ``https://github.com/{owner}/{repo}/releases/download/works/w_xxx.mp4``，
   支持浏览器 <video> 流式播放（Range 请求），也支持直接下载；
2. 作品清单 ``works.json`` 通过 Contents API 提交进仓库
   （默认 ``frontend/public/works/works.json``），随 GitHub Pages 一起发布；
3. 访客打开网站「作品库」页读取同一份 works.json，即可在线播放 / 下载，
   不需要启动本地服务。

仅依赖标准库 urllib，便携 Python 可直接运行。
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import media_utils as mu
from config import (
    GITHUB_BRANCH,
    GITHUB_REPO,
    GITHUB_TOKEN,
    PAGES_BASE_URL,
    TMP_DIR,
    WORKS_MANIFEST_PATH,
    WORKS_RELEASE_TAG,
)

API_BASE = "https://api.github.com"
UPLOAD_BASE = "https://uploads.github.com"
_MANIFEST_VERSION = 1


class PublishError(RuntimeError):
    """发布失败（配置缺失或 GitHub API 报错）。"""


# ================================================================ 对外信息


def is_configured() -> bool:
    return bool(GITHUB_TOKEN) and _repo_parts() is not None


def publish_info() -> dict:
    """给前端的公开配置（绝不返回 token）。"""
    return {
        "configured": is_configured(),
        "repo": GITHUB_REPO,
        "release_tag": WORKS_RELEASE_TAG,
        "pages_url": pages_url(),
    }


def pages_url() -> str:
    """作品库页面的完整网址。"""
    base = PAGES_BASE_URL
    if not base:
        parts = _repo_parts()
        if parts:
            owner, repo = parts
            base = f"https://{owner}.github.io/{repo}"
    return f"{base}/works" if base else ""


# ================================================================ 发布主流程


def publish_video(job, index: int = 0, title: str = "", note: str = "") -> dict:
    """发布一个任务成片，返回该作品在清单中的条目。

    - 取 job.outputs 中第 index 个 kind=="video" 的产物；
    - 幂等：作品 id 由 job.id 与 index 决定，重复发布会覆盖同名资产与清单条目。
    """
    _require_config()
    video = _pick_video(job, index)

    wid = f"w_{job.id[:8]}_{index}"
    title = (title or "").strip() or Path(job.filename).stem
    note = (note or "").strip()

    # 1. 视频信息 + 生成封面 ------------------------------------------------
    info = mu.probe(video)
    duration = round(info.duration, 1) if info.duration > 0 else 0.0
    size = video.stat().st_size
    poster = TMP_DIR / f"{wid}_poster.jpg"
    at = 1.0
    if duration > 2:
        at = min(duration * 0.2, duration - 0.5)
    try:
        mu.make_thumbnail(video, poster, at=at)
    except Exception as exc:  # noqa: BLE001 - 封面失败不阻断发布
        print(f"[publish] 封面生成失败，继续无封面发布：{exc}")
        poster = None

    # 2. 确保 Release 存在并上传资产 ----------------------------------------
    release = _ensure_release()
    video_name = f"{wid}.mp4"
    poster_name = f"{wid}.jpg"
    _replace_asset(release["id"], video_name, video, "video/mp4")
    if poster is not None:
        _replace_asset(release["id"], poster_name, poster, "image/jpeg")

    # 3. 更新 works.json ----------------------------------------------------
    now = int(time.time())
    work = {
        "id": wid,
        "title": title[:80],
        "note": note[:200],
        "video": _download_url(video_name),
        "poster": _download_url(poster_name) if poster is not None else "",
        "duration": duration,
        "size": size,
        "published_at": now,
    }
    manifest = _read_manifest()
    works = manifest.get("works") if isinstance(manifest.get("works"), list) else []
    existing = next((w for w in works if isinstance(w, dict) and w.get("id") == wid), None)
    if existing:
        # 重发保留首次发布时间
        work["published_at"] = int(existing.get("published_at") or now)
        works = [work if isinstance(w, dict) and w.get("id") == wid else w for w in works]
    else:
        works.insert(0, work)
    _write_manifest(works, f"发布作品：{title[:60]}")

    repo_private = _repo_is_private()
    return {**work, "pages_url": pages_url(), "repo_private": repo_private}


def unpublish(work_id: str) -> dict:
    """下架作品：删除 Release 资产并从清单移除。"""
    _require_config()
    wid = work_id.strip()
    if not wid.replace("_", "").replace("-", "").isalnum():
        raise PublishError("作品 id 不合法")

    # Release 可能已被手动删除；清单更新无论如何都要执行
    try:
        release = _get_release()
        if release:
            for name in (f"{wid}.mp4", f"{wid}.jpg"):
                asset = _find_asset(release, name)
                if asset:
                    _api("DELETE", f"/repos/{GITHUB_REPO}/releases/assets/{asset['id']}")
    except PublishError:
        raise
    except Exception:
        pass

    manifest = _read_manifest()
    works = [w for w in (manifest.get("works") or [])
             if not (isinstance(w, dict) and w.get("id") == wid)]
    _write_manifest(works, f"下架作品：{wid}")
    return {"id": wid, "remaining": len(works)}


# ================================================================ GitHub API


def _api(method: str, path: str, *, body=None, timeout: int = 60,
         base: str = API_BASE) -> dict:
    url = path if path.startswith("https://") else f"{base}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mustardseed-video-service",
    }
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:600]
        try:
            parsed = json.loads(detail)
            detail = parsed.get("message") or detail
        except (ValueError, AttributeError):
            pass
        if exc.code == 401:
            raise PublishError("GitHub Token 无效或已过期（401），请检查 service.json 的 github_token")
        if exc.code == 403:
            raise PublishError(
                f"GitHub 拒绝访问（403）：{detail}。"
                "经典 Token 需勾选 repo 权限；细粒度 Token 需授予 Contents 读写。"
            )
        if exc.code == 404:
            raise PublishError(f"GitHub 资源不存在（404）：{detail or '仓库 / Release / 文件路径有误'}")
        raise PublishError(f"GitHub API {exc.code}：{detail}") from None
    except urllib.error.URLError as exc:
        raise PublishError(f"连不上 GitHub（{exc.reason}），请检查网络 / 代理后重试") from None


def _get_release() -> dict | None:
    try:
        return _api("GET", f"/repos/{GITHUB_REPO}/releases/tags/{urllib.parse.quote(WORKS_RELEASE_TAG)}")
    except PublishError as exc:
        if "404" in str(exc):
            return None
        raise


def _ensure_release() -> dict:
    release = _get_release()
    if release:
        return release
    return _api("POST", f"/repos/{GITHUB_REPO}/releases", body={
        "tag_name": WORKS_RELEASE_TAG,
        "target_commitish": GITHUB_BRANCH,
        "name": "作品库 · 配音成品",
        "body": "视频译制模块一键发布的成片资产，作品清单见仓库 works.json。",
        "draft": False,
        "prerelease": False,
    })


def _find_asset(release: dict, name: str) -> dict | None:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return asset
    return None


def _replace_asset(release_id: int, name: str, local: Path, content_type: str) -> None:
    """上传资产；同名旧资产先删除（重发覆盖）。大文件整块读取（成片一般几十 MB）。"""
    release = _api("GET", f"/repos/{GITHUB_REPO}/releases/{release_id}")
    old = _find_asset(release, name)
    if old:
        _api("DELETE", f"/repos/{GITHUB_REPO}/releases/assets/{old['id']}")

    query = urllib.parse.urlencode({"name": name})
    url = f"{UPLOAD_BASE}/repos/{GITHUB_REPO}/releases/{release_id}/assets?{query}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mustardseed-video-service",
        "Content-Type": content_type,
    }
    req = urllib.request.Request(
        url, data=local.read_bytes(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=1800):
            pass
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:600]
        try:
            detail = json.loads(detail).get("message", detail)
        except (ValueError, AttributeError):
            pass
        if exc.code == 401:
            raise PublishError("GitHub Token 无效或已过期（401），请检查 service.json 的 github_token")
        raise PublishError(
            f"资产「{name}」上传失败（{exc.code}）：{detail}。"
            "单个 Release 资产上限 2GB；也可能是网络中断，重试即可。"
        ) from None
    except urllib.error.URLError as exc:
        raise PublishError(f"上传「{name}」时连不上 GitHub（{exc.reason}）") from None


def _read_manifest() -> dict:
    """读取仓库中的 works.json；不存在则返回空清单。"""
    path_q = urllib.parse.quote(WORKS_MANIFEST_PATH, safe="/")
    url = f"{API_BASE}/repos/{GITHUB_REPO}/contents/{path_q}?ref={urllib.parse.quote(GITHUB_BRANCH)}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mustardseed-video-service",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"version": _MANIFEST_VERSION, "works": []}
        detail = exc.read().decode("utf-8", "ignore")[:300]
        raise PublishError(f"读取 works.json 失败（{exc.code}）：{detail}") from None
    except urllib.error.URLError as exc:
        raise PublishError(f"连不上 GitHub（{exc.reason}）") from None
    try:
        content = base64.b64decode(payload["content"]).decode("utf-8")
        data = json.loads(content)
        data["_sha"] = payload.get("sha")
        return data
    except (KeyError, ValueError) as exc:
        raise PublishError(f"works.json 内容无法解析：{exc}") from None


def _write_manifest(works: list, message: str) -> None:
    manifest = _read_manifest()
    sha = manifest.get("_sha")
    payload = {
        "message": f"[作品库] {message}",
        "branch": GITHUB_BRANCH,
        "content": base64.b64encode(
            json.dumps(
                {"version": _MANIFEST_VERSION,
                 "updated_at": int(time.time()),
                 "works": works},
                ensure_ascii=False, indent=2,
            ).encode("utf-8")
        ).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    path_q = urllib.parse.quote(WORKS_MANIFEST_PATH, safe="/")
    _api("PUT", f"/repos/{GITHUB_REPO}/contents/{path_q}", body=payload)


def _repo_is_private() -> bool:
    try:
        info = _api("GET", f"/repos/{GITHUB_REPO}")
        return bool(info.get("private"))
    except PublishError:
        return False


# ================================================================ 辅助


def _repo_parts() -> tuple[str, str] | None:
    parts = GITHUB_REPO.strip("/").split("/")
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return None


def _require_config() -> None:
    if not GITHUB_TOKEN:
        raise PublishError("未配置 github_token：请在 video-service/service.json 填入 GitHub Token 后重启服务")
    if _repo_parts() is None:
        raise PublishError('未配置 github_repo：形如 "lxt-promise/mustardseed"，填好后重启服务')


def _pick_video(job, index: int) -> Path:
    videos = [o for o in job.outputs if o.get("kind") == "video" and o.get("path")]
    if not videos:
        raise PublishError("该任务还没有视频成片，先完成译制再发布")
    if index < 0 or index >= len(videos):
        index = 0
    path = Path(videos[index]["path"])
    if not path.exists():
        raise PublishError(f"成片文件已不在本地：{path.name}")
    return path


def _download_url(asset_name: str) -> str:
    return (f"https://github.com/{GITHUB_REPO}/releases/download/"
            f"{urllib.parse.quote(WORKS_RELEASE_TAG)}/{urllib.parse.quote(asset_name)}")
