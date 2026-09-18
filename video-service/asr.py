"""语音识别 + 翻译。

两条轨道，界面上可切换：
  1) 本地 faster-whisper  —— 免费、离线、隐私安全
  2) 云端 OpenAI 兼容 API —— 速度快、无需下载模型
两者输出统一的 Segment 结构。
"""
from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from config import (
    DATA_DIR,
    MODEL_DIR,
    PAUSE_USE,
    ZH_BUDGET_SLACK,
    ZH_CHARS_PER_SEC,
    ZH_MIN_KEEP,
    ZH_TRIM_THRESHOLD,
)

log = logging.getLogger("videodub.asr")

ProgressFn = Callable[[float, str], None]


@dataclass
class Segment:
    """一句字幕。start/end 为秒。"""
    start: float
    end: float
    text: str
    translated: str = ""

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Segment":
        return Segment(
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
            text=str(d.get("text", "")),
            translated=str(d.get("translated", "")),
        )


# ============================================================== 本地 Whisper
_model_cache: dict[str, object] = {}


def _load_whisper(model_id: str, progress: ProgressFn | None = None):
    """加载并缓存 faster-whisper 模型。"""
    if model_id in _model_cache:
        return _model_cache[model_id]

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "未安装 faster-whisper，请先运行 install.bat 安装依赖"
        ) from exc

    if progress:
        progress(0.0, f"正在加载 Whisper 模型 {model_id}（首次使用需要下载）…")

    # 优先用 CPU int8；有 CUDA 时自动尝试 GPU
    try:
        model = WhisperModel(
            model_id,
            device="cpu",
            compute_type="int8",
            download_root=str(MODEL_DIR),
            # 默认只用 4 线程，按 CPU 核数给满（上限 8，多了反而争内存带宽）
            cpu_threads=min(8, max(4, os.cpu_count() or 4)),
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"加载 Whisper 模型失败：{exc}") from exc

    _model_cache[model_id] = model
    return model


def transcribe_local(
    audio_path: str | Path,
    *,
    model_id: str = "small",
    language: str | None = None,
    progress: ProgressFn | None = None,
) -> tuple[list[Segment], str]:
    """本地 faster-whisper 识别，返回 (原始语言片段, 检测到的语言)。

    使用 task="transcribe" 保留**原始语言文本**，中文译文交给翻译层处理。

    为什么不直接用 Whisper 的 task="translate"：
    Whisper 的翻译任务**只能翻成英文**（官方设计如此，不支持指定目标语言）。
    如果用它来「翻成中文」，得到的其实还是英文，而且原始文本会被丢掉，
    双语字幕也就做不出来了。所以这里保留原文，翻译统一走 translate_segments。

    打开 word_timestamps 后，用词级时间戳把碎片重组成**完整句子**，
    这样每句的起止时间是准确的，翻译和 TTS 都以整句为单位，中文更自然。
    """
    model = _load_whisper(model_id, progress)

    if progress:
        progress(0.05, "正在识别语音…")

    segments, info = model.transcribe(
        str(audio_path),
        language=language,              # None = 自动检测
        task="transcribe",              # 保留原语言，翻译交给下游
        beam_size=5,
        vad_filter=True,                # 过滤静音，明显减少空转
        vad_parameters={"min_silence_duration_ms": 400},
        condition_on_previous_text=False,
        word_timestamps=True,           # 词级时间戳，用于重建句子边界
    )

    detected = (getattr(info, "language", "") or "").strip()
    total = getattr(info, "duration", 0.0) or 0.0

    # 先把词级时间戳收集出来（生成器只能遍历一次）
    words: list[dict] = []
    fallback: list[Segment] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        fallback.append(Segment(start=float(seg.start), end=float(seg.end), text=text))
        for w in (getattr(seg, "words", None) or []):
            token = getattr(w, "word", "") or ""
            if token.strip():
                words.append({
                    "start": float(getattr(w, "start", 0.0) or 0.0),
                    "end": float(getattr(w, "end", 0.0) or 0.0),
                    "text": token,
                })
        if progress and total > 0:
            pct = min(float(seg.end) / total, 1.0)
            progress(0.05 + pct * 0.85, f"识别中 {pct * 100:.0f}%")

    if progress:
        progress(0.92, "正在整理句子…")

    out = sentences_from_words(words) if words else []
    if not out:
        # 词级时间戳不可用时退回段级结果
        out = merge_into_sentences(fallback) or fallback

    if progress:
        progress(1.0, f"识别完成，共 {len(out)} 句")

    return out, detected


# ============================================================== 云端 ASR
def transcribe_cloud(
    audio_path: str | Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    language: str | None = None,
    progress: ProgressFn | None = None,
) -> tuple[list[Segment], str]:
    """调用 OpenAI 兼容的 /audio/transcriptions 接口。

    支持 whisper-1 / gpt-4o-transcribe 等兼容实现。
    返回 (原始语言片段, 检测到的语言)，不在这里做翻译。
    """
    if not api_key:
        raise RuntimeError("使用云端识别需要填写 API Key")

    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/audio/transcriptions"):
        endpoint = f"{endpoint}/audio/transcriptions"

    if progress:
        progress(0.1, "正在上传音频到云端识别…")

    audio_path = Path(audio_path)
    boundary = "----VideoDubBoundary7MA4YWxkTrZu0gW"
    fields: dict[str, str] = {
        "model": model,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "segment",
    }
    if language:
        fields["language"] = language

    body = _build_multipart(fields, "file", audio_path, boundary)

    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"云端识别失败 HTTP {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接云端识别服务：{exc.reason}") from exc

    if progress:
        progress(0.9, "云端识别完成，正在整理结果…")

    segs_raw = payload.get("segments") or []
    segments: list[Segment] = []
    if segs_raw:
        for s in segs_raw:
            text = (s.get("text") or "").strip()
            if not text:
                continue
            segments.append(Segment(
                start=float(s.get("start", 0.0)),
                end=float(s.get("end", 0.0)),
                text=text,
            ))
    else:
        # 部分实现只返回整段文本，没有时间戳
        whole = (payload.get("text") or "").strip()
        if whole:
            segments = _fake_timeline(whole, audio_duration_of(audio_path))

    if not segments:
        raise RuntimeError("云端识别没有返回有效内容")

    det_lang = (payload.get("language") or language or "").strip()

    if progress:
        progress(1.0, f"识别完成，共 {len(segments)} 句")
    return segments, det_lang


def audio_duration_of(path: str | Path) -> float:
    try:
        from media_utils import probe
        return probe(path).duration
    except Exception:  # noqa: BLE001
        return 0.0


def _fake_timeline(text: str, duration: float) -> list[Segment]:
    """没有时间戳时，按标点均分时间轴，保证流程能继续。"""
    pieces = [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+", text) if p.strip()]
    if not pieces:
        pieces = [text]
    duration = duration or len(pieces) * 3.0
    each = duration / len(pieces)
    return [
        Segment(start=i * each, end=(i + 1) * each, text=p)
        for i, p in enumerate(pieces)
    ]


def _build_multipart(
    fields: dict[str, str], file_field: str, file_path: Path, boundary: str
) -> bytes:
    lines: list[bytes] = []
    for key, value in fields.items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{key}"'.encode())
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))

    lines.append(f"--{boundary}".encode())
    lines.append(
        f'Content-Disposition: form-data; name="{file_field}"; '
        f'filename="{file_path.name}"'.encode()
    )
    lines.append(b"Content-Type: audio/wav")
    lines.append(b"")
    lines.append(file_path.read_bytes())
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    return b"\r\n".join(lines)


# ============================================================== 翻译
PUNCT_SPLIT = re.compile(r"(?<=[.!?;:])\s+")

# MyMemory 免密钥翻译接口：全球公益翻译记忆库，匿名可用，无需注册。
# 实测在教育网/国内网络下可直连（Google 翻译接口不可达）。
MYMEMORY_ENDPOINT = "https://api.mymemory.translated.net/get"

# 各目标语言的接口代码
_LANG_CODE = {
    "zh": "zh-CN", "zh-cn": "zh-CN", "zh-tw": "zh-TW",
    "en": "en", "ja": "ja", "ko": "ko", "fr": "fr", "de": "de", "es": "es",
}

_ZH_LANGS = {"zh", "zh-cn", "zh-tw", "zh-hk", "zh-hans", "zh-hant", "cmn", "yue"}

# 译文缓存，避免同一句话重复请求（长视频里重复台词很常见）
_FREE_CACHE: dict[tuple[str, str, str], str] = {}
_FREE_CACHE_LOCK = __import__("threading").Lock()

# 免费翻译引擎的限流与熔断。
# MyMemory 匿名接口对请求频率和当日总量都有限制，超了会返回 429
# 或额度告警文本（前端表现即"请求次数过多"）。对策：
#   1) 多句合并请求：12 句拼成一次请求，请求数降一个数量级
#   2) 全局节流：相邻两次请求至少间隔 FREE_MIN_INTERVAL 秒（串行放行）
#   3) 429/5xx 退避重试 1s → 2s（约 3 秒内放弃，绝不卡死任务），
#      仍被限流则冷却 _MM_LIMIT_COOLDOWN 秒，期间直接走备用引擎
#   4) 当日额度耗尽 → 冷却 30 分钟
#   5) Google 网页翻译接口兜底；连不上（国内网络常见）也熔断 10 分钟
#   6) 腾讯交互翻译兜底（国内可达、免密钥、原生批量）：MyMemory
#      额度耗尽 + Google 被墙时依然能出中文
#   7) 磁盘缓存 data/translate_cache.json：同一句话永远只请求一次
FREE_MIN_INTERVAL = 0.3          # 相邻请求最小间隔（秒）
_MM_LIMIT_COOLDOWN = 15          # 被限流后的短冷却（秒）
_MM_QUOTA_COOLDOWN = 30 * 60     # 当日额度耗尽后的冷却（秒）
_GOOGLE_DOWN_COOLDOWN = 10 * 60  # Google 不可达后的冷却（秒）
_QQ_DOWN_COOLDOWN = 10 * 60      # 腾讯不可达后的冷却（秒）

MM_BATCH_ITEMS = 12     # MyMemory 单次请求最多合并的句数
MM_BATCH_CHARS = 380    # MyMemory 单次请求合并文本的字符上限（服务端 q 限 500）
QQ_BATCH_ITEMS = 20     # 腾讯单次请求最多句数（原生 text_list 批量）
QQ_BATCH_CHARS = 1500   # 腾讯单次请求总字符上限

GOOGLE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
QQ_ENDPOINT = "https://transmart.qq.com/api/imt"

_MM_PAUSE_UNTIL = 0.0       # MyMemory 冷却截止时间（monotonic）
_GOOGLE_DOWN_UNTIL = 0.0    # Google 不可达熔断截止时间（monotonic）
_QQ_DOWN_UNTIL = 0.0        # 腾讯不可达熔断截止时间（monotonic）
_FREE_LAST_REQUEST = 0.0    # MyMemory 节流
_QQ_LAST_REQUEST = 0.0      # 腾讯节流
_FREE_STATE_LOCK = threading.Lock()

# 磁盘缓存：key 为 (源语言, 目标语言, 原文)，持久化为两层 JSON
_CACHE_PATH = DATA_DIR / "translate_cache.json"
_CACHE_LOCK = threading.Lock()
_CACHE_LOADED = False
_CACHE_MAX_ENTRIES = 20000


def _is_chinese_lang(lang: str) -> bool:
    return (lang or "").strip().lower() in _ZH_LANGS


def _has_chinese(text: str) -> bool:
    if not text:
        return False
    return len(re.findall(r"[\u4e00-\u9fff]", text)) / max(len(text), 1) > 0.25


def translate_segments(
    segments: list[Segment],
    *,
    target: str = "zh",
    source_lang: str = "",
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    provider: str = "auto",
    progress: ProgressFn | None = None,
) -> list[Segment]:
    """把 segment.text 翻译成 target 语言，写入 translated。

    provider:
      - "auto"     自动选择：配了 LLM 就用 LLM，否则用免费引擎
      - "free"     强制使用免密钥免费引擎（MyMemory）
      - "llm"      强制使用 OpenAI 兼容 LLM 接口（需 base_url + api_key + model）
      - "none"     不翻译，原文直通

    设计目标：**不配任何密钥也能产出中文字幕**，同时保留接入高质量
    LLM 翻译的能力（质量明显更好，适合正式发布）。
    """
    if not segments:
        return segments

    # 源语言已经是目标语言 → 无需翻译
    if _is_chinese_lang(source_lang) and target == "zh":
        for seg in segments:
            if not seg.translated:
                seg.translated = seg.text
        return segments

    # 用户明确关掉翻译
    if provider == "none":
        for seg in segments:
            if not seg.translated:
                seg.translated = seg.text
        return segments

    has_llm = bool(base_url and api_key and model)

    if provider == "llm" and not has_llm:
        raise RuntimeError(
            "已选择 LLM 翻译，但未填写 base_url / API Key / 模型名"
        )

    use_llm = has_llm if provider == "auto" else (provider == "llm")

    if use_llm:
        return _translate_with_llm(
            segments, target=target, base_url=base_url,
            api_key=api_key, model=model, progress=progress,
        )

    return _translate_free(
        segments, target=target, source_lang=source_lang, progress=progress
    )


def _translate_with_llm(
    segments: list[Segment],
    *,
    target: str,
    base_url: str,
    api_key: str,
    model: str,
    progress: ProgressFn | None = None,
) -> list[Segment]:
    if progress:
        progress(0.1, "正在用 LLM 翻译为中文…")

    batch_size = 20
    total = len(segments)
    for i in range(0, total, batch_size):
        chunk = segments[i:i + batch_size]
        payload_texts = [s.text for s in chunk]
        # 每句的时间预算 → 中文字数上限。
        # 中文口播约 4.6 字/秒，按原句时长反推能说多少个字，
        # 让 LLM 往这个长度内翻，从源头减少"配音说不完要狂压语速"的情况。
        budgets = [
            max(6, int(round(s.duration * ZH_CHARS_PER_SEC)))
            for s in chunk
        ]
        translated = _llm_translate(
            payload_texts, base_url, api_key, model, target, budgets
        )
        for seg, zh in zip(chunk, translated):
            seg.translated = zh or seg.text
        if progress:
            done = min(i + batch_size, total)
            progress(done / total, f"翻译中 {done}/{total}")

    return segments


def _translate_free(
    segments: list[Segment],
    *,
    target: str,
    source_lang: str = "",
    progress: ProgressFn | None = None,
) -> list[Segment]:
    """免密钥翻译（MyMemory 批量优先，逐句降级，Google 兜底）。

    多句合并成一次请求把请求数降一个数量级；磁盘缓存让同一句话
    永远只请求一次（重跑同一视频 0 请求）；串行限速 + 退避冷却
    避免触发免费接口的频率限制；个别句子失败时保留原文，
    不让整条流水线中断。
    """
    src = (source_lang or "en").strip().lower()
    if src in ("", "auto"):
        src = "en"

    # 需要翻译的句子（已是中文的跳过）
    todo = [s for s in segments if s.text.strip() and not _has_chinese(s.text)]

    # 先把「无需翻译」的填上
    for s in segments:
        if not s.translated and (not s.text.strip() or _has_chinese(s.text)):
            s.translated = s.text

    if not todo:
        if progress:
            progress(1.0, "内容已是中文，无需翻译")
        return segments

    uniq = list(dict.fromkeys(s.text.strip() for s in todo))
    results: dict[str, str] = {}
    total = len(uniq)

    # ---- 1) 磁盘 + 内存缓存命中：同一句话永远只请求一次
    pending: list[str] = []
    for t in uniq:
        zh = _cache_get(src, target, t)
        if zh:
            results[t] = zh
        else:
            pending.append(t)
    cached = total - len(pending)
    done = cached

    if progress:
        hit = f"，缓存命中 {cached} 句" if cached else ""
        progress(0.05, f"正在免费翻译（共 {total} 句{hit}）…")
    if not pending:
        # 全部命中缓存：直接写回译文，0 请求
        for s in todo:
            s.translated = results.get(s.text.strip()) or s.text
        _report_free_done(progress, total, cached)
        return segments

    # ---- 2) MyMemory 批量：多句（≤12 句）合并成一次请求
    #      超长句服务端必拒（q 限 500 字符），直接进逐句通道走 Google
    remaining = [t for t in pending if len(t) > MM_BATCH_CHARS]
    batchable = [t for t in pending if len(t) <= MM_BATCH_CHARS]
    if batchable:
        for batch in _pack_lines(batchable, MM_BATCH_ITEMS, MM_BATCH_CHARS):
            if _mm_paused():
                # 前面批次触发限流冷却，剩余批次不再硬撞，直接走逐句通道
                remaining.extend(batch)
                continue
            ok, failed_texts = _mymemory_batch_request(batch, src, target)
            for t, zh in ok.items():
                results[t] = zh
                _cache_put(src, target, t, zh)
            remaining.extend(failed_texts)
            done += len(batch)
            if progress:
                progress(0.05 + (done / total) * 0.9, f"翻译中 {min(done, total)}/{total}")

    # ---- 3) 腾讯批量兜底：MyMemory 额度耗尽/被限流时保住中文输出
    #         （原生 text_list 批量，国内可达、无需密钥）
    if remaining:
        qq_pool = [t for t in remaining if len(t) <= QQ_BATCH_CHARS]
        remaining = [t for t in remaining if len(t) > QQ_BATCH_CHARS]
        for batch in _pack_lines(qq_pool, QQ_BATCH_ITEMS, QQ_BATCH_CHARS):
            ok = _qq_translate_batch(batch, src, target)
            for t, zh in ok.items():
                results[t] = zh
                _cache_put(src, target, t, zh)
            remaining.extend(t for t in batch if t not in ok)
            done += len(batch)
            if progress:
                progress(0.05 + (done / total) * 0.9, f"翻译中 {min(done, total)}/{total}")

    # ---- 4) 逐句降级：批量拆分失败/超长的句子（内部 MyMemory → 腾讯 → Google）
    for t in remaining:
        zh = _free_translate_one(t, src, target)
        if zh:
            results[t] = zh
        done += 1
        if progress:
            progress(0.05 + (min(done, total) / total) * 0.9, f"翻译中 {min(done, total)}/{total}")

    _flush_cache()

    # 翻译失败不保底：任何句子没翻出来就让任务失败，
    # 避免用户拿到中英混杂/纯英文的成片却没察觉。
    failed = total - len(results)
    if failed:
        raise RuntimeError(
            f"免费翻译接口未能翻译 {failed}/{total} 句（限流或当日额度耗尽），任务已终止。"
            "已翻译成功的句子已存入缓存，稍后重试不会重复请求；"
            "也可在高级设置中配置 LLM 翻译接口以获得稳定通道。"
        )

    for s in todo:
        s.translated = results[s.text.strip()]

    _report_free_done(progress, total, cached)
    return segments


def _report_free_done(progress: ProgressFn | None, total: int, cached: int) -> None:
    if not progress:
        return
    msg = f"翻译完成，共 {total} 句"
    if cached:
        msg += f"（缓存命中 {cached}）"
    progress(1.0, msg)


def _free_translate_one(text: str, source_lang: str, target: str) -> str:
    """逐句翻译：MyMemory → 腾讯 → Google，三级兜底。"""
    key = (source_lang, target, text)
    cached = _cache_get(*key)
    if cached:
        return cached

    src_code = _LANG_CODE.get(source_lang, source_lang or "en")
    dst_code = _LANG_CODE.get(target, target)

    out = ""
    if not _mm_paused():
        out = _mymemory_request(text, src_code, dst_code)

    if not out:
        out = _qq_translate_batch([text], src_code, dst_code).get(text, "")

    if not out:
        out = _google_translate_one(text, src_code, dst_code)

    if out:
        _cache_put(*key, out)
    return out


def _throttle_free_request() -> None:
    """免费引擎请求节流：保证相邻两次请求至少间隔 FREE_MIN_INTERVAL 秒。"""
    global _FREE_LAST_REQUEST
    with _FREE_STATE_LOCK:
        wait = _FREE_LAST_REQUEST + FREE_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _FREE_LAST_REQUEST = time.monotonic()


def _mm_paused() -> bool:
    with _FREE_STATE_LOCK:
        return time.monotonic() < _MM_PAUSE_UNTIL


def _mm_pause(seconds: float, reason: str) -> None:
    """MyMemory 冷却：期间所有句子直接走备用引擎，不再硬撞。"""
    global _MM_PAUSE_UNTIL
    with _FREE_STATE_LOCK:
        until = time.monotonic() + seconds
        if until > _MM_PAUSE_UNTIL:
            _MM_PAUSE_UNTIL = until
    log.warning("MyMemory 冷却 %.0f 秒：%s", seconds, reason)


# ------------------------------------------------------------ 磁盘缓存
def _ensure_cache_loaded() -> None:
    """首次使用时把磁盘缓存加载进内存。"""
    global _CACHE_LOADED
    if _CACHE_LOADED:
        return
    with _CACHE_LOCK:
        if _CACHE_LOADED:
            return
        _CACHE_LOADED = True
        try:
            if _CACHE_PATH.exists():
                data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
                with _FREE_CACHE_LOCK:
                    for pair, items in (data or {}).items():
                        try:
                            src, dst = str(pair).split(">", 1)
                        except ValueError:
                            continue
                        if isinstance(items, dict):
                            for text, zh in items.items():
                                _FREE_CACHE[(src, dst, text)] = str(zh)
                log.info("翻译缓存已加载：%d 条", len(_FREE_CACHE))
        except Exception as exc:  # noqa: BLE001
            log.warning("翻译缓存读取失败（忽略）：%s", exc)


def _cache_get(src: str, dst: str, text: str) -> str:
    _ensure_cache_loaded()
    with _FREE_CACHE_LOCK:
        return _FREE_CACHE.get((src, dst, text), "")


def _cache_put(src: str, dst: str, text: str, zh: str) -> None:
    _ensure_cache_loaded()
    with _FREE_CACHE_LOCK:
        if (src, dst, text) not in _FREE_CACHE and len(_FREE_CACHE) >= _CACHE_MAX_ENTRIES:
            return
        _FREE_CACHE[(src, dst, text)] = zh


def _flush_cache() -> None:
    """把内存缓存落盘（原子写），重跑同一视频即可 0 请求。"""
    with _FREE_CACHE_LOCK:
        snapshot = dict(_FREE_CACHE)
    if not snapshot:
        return
    data: dict[str, dict[str, str]] = {}
    for (src, dst, text), zh in snapshot.items():
        data.setdefault(f"{src}>{dst}", {})[text] = zh
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_name(_CACHE_PATH.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CACHE_PATH)
    except OSError as exc:
        log.warning("翻译缓存写入失败（忽略）：%s", exc)


# ------------------------------------------------------------ 批量请求
def _pack_lines(
    texts: list[str], max_items: int, max_chars: int
) -> list[list[str]]:
    """把句子打包成多批：每批 ≤ max_items 句、拼接总长 ≤ max_chars。"""
    batches: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for t in texts:
        w = len(t) + 4  # 4 ≈ "12. " 编号与换行的开销
        if cur and (len(cur) >= max_items or size + w > max_chars):
            batches.append(cur)
            cur, size = [], 0
        cur.append(t)
        size += w
    if cur:
        batches.append(cur)
    return batches


_NUMBERED_LINE = re.compile(r"^\s*(\d{1,3})[.、)]\s*(.*?)\s*$")
_LINE_NUMBER_PREFIX = re.compile(r"^\s*\d{1,3}[.、)]\s*")


def _split_batch_translation(
    raw: str, texts: list[str]
) -> tuple[dict[str, str], list[str]]:
    """把批量返回的文本按句拆回去。返回 (成功映射, 失败列表)。"""
    by_num: dict[int, str] = {}
    rows: list[str] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        rows.append(ln)
        m = _NUMBERED_LINE.match(ln)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(texts) and m.group(2):
                by_num[idx] = m.group(2)

    # ① 编号完整匹配 → 最可靠
    if len(by_num) == len(texts):
        return {t: by_num[i] for i, t in enumerate(texts)}, []
    # ② 行数一致 → 按顺序对应（剥掉可能残留的编号前缀）
    if len(rows) == len(texts) and all(rows):
        return dict(zip(texts, [_LINE_NUMBER_PREFIX.sub("", r) for r in rows])), []
    return {}, list(texts)


def _mymemory_batch_request(
    texts: list[str], src_code: str, dst_code: str
) -> tuple[dict[str, str], list[str]]:
    """一次请求翻译多句（编号拼接）。返回 (成功映射, 失败列表)。

    429/5xx 退避 1s → 2s（约 3 秒内放弃，不卡任务）；仍被限流则
    冷却 15 秒；当日额度耗尽则冷却 30 分钟，冷却期间走备用引擎。
    """
    joined = "\n".join(
        f"{i + 1}. {t.replace(chr(10), ' ')}" for i, t in enumerate(texts)
    )
    params = urllib.parse.urlencode({
        "q": joined,
        "langpair": f"{src_code}|{dst_code}",
    })
    url = f"{MYMEMORY_ENDPOINT}?{params}"

    payload: dict | None = None
    limited = False
    for attempt in range(3):
        _throttle_free_request()
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "VideoDub/1.0 (+local app)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503):
                if attempt < 2:
                    wait = 2.0 ** attempt  # 1s → 2s
                    log.warning(
                        "MyMemory 限流（HTTP %d），%.0f 秒后重试", exc.code, wait
                    )
                    time.sleep(wait)
                    continue
                limited = True
                log.warning("MyMemory 批量请求被限流：HTTP %d", exc.code)
            else:
                log.warning("MyMemory 批量请求失败：HTTP %d", exc.code)
            break
        except Exception as exc:  # noqa: BLE001
            if attempt < 2:
                wait = 2.0 ** attempt
                log.warning(
                    "MyMemory 批量请求异常（第 %d/3 次）：%s，%.0f 秒后重试",
                    attempt + 1, exc, wait,
                )
                time.sleep(wait)
                continue
            log.warning("MyMemory 批量请求失败：%s", exc)
            break

    if payload is not None:
        raw = ""
        try:
            raw = str((payload.get("responseData") or {}).get("translatedText") or "")
        except AttributeError:
            pass
        if "ALL AVAILABLE FREE TRANSLATIONS" in raw.upper():
            _mm_pause(_MM_QUOTA_COOLDOWN, "当日免费额度已用尽，改用备用引擎")
            return {}, list(texts)
        if payload.get("responseStatus") == 429:
            limited = True
        else:
            ok, failed = _split_batch_translation(raw, texts)
            if ok:
                return ok, failed
            log.warning(
                "MyMemory 批量译文无法按句拆分，%d 句降级为逐句翻译", len(texts)
            )
            return {}, list(texts)

    if limited:
        _mm_pause(_MM_LIMIT_COOLDOWN, "连续被限流（HTTP 429）")
    return {}, list(texts)


def _qq_lang(code: str) -> str:
    """腾讯 TransMart 的语言代码："zh-CN" → "zh"。"""
    return (code or "en").split("-", 1)[0].lower()


def _qq_translate_batch(
    texts: list[str], src_code: str, dst_code: str
) -> dict[str, str]:
    """腾讯交互翻译兜底（国内可达、免密钥、原生 text_list 批量）。

    成功返回 {原文: 译文}；失败/不可达返回 {}（触发下一通道）。
    典型场景：MyMemory 当日额度耗尽 + Google 被墙，靠它保住中文输出。
    """
    global _QQ_DOWN_UNTIL, _QQ_LAST_REQUEST
    sl, tl = _qq_lang(src_code), _qq_lang(dst_code)
    if sl == tl or not texts:
        return {}
    with _FREE_STATE_LOCK:
        if time.monotonic() < _QQ_DOWN_UNTIL:
            return {}

    body = json.dumps({
        "header": {
            "fn": "auto_translation",
            "session": "",
            "client_key": "browser-chromium-Win32-133.0.6943.127-x64-videodub",
        },
        "source": {"lang": sl, "text_list": list(texts)},
        "target": {"lang": tl},
    }, ensure_ascii=False).encode("utf-8")
    try:
        with _FREE_STATE_LOCK:
            wait = _QQ_LAST_REQUEST + FREE_MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _QQ_LAST_REQUEST = time.monotonic()
        req = urllib.request.Request(
            QQ_ENDPOINT, data=body, method="POST",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                ),
                "Content-Type": "application/json",
                "Origin": "https://transmart.qq.com",
                "Referer": "https://transmart.qq.com/zh-CN/browser",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        trans = payload.get("auto_translation")
        if isinstance(trans, list) and len(trans) == len(texts):
            return {
                t: str(x).strip() for t, x in zip(texts, trans)
                if x and str(x).strip()
            }
        log.warning("腾讯翻译返回异常结构（%d 句失败）", len(texts))
        return {}
    except Exception as exc:  # noqa: BLE001
        # 连不上/接口变更 → 熔断一段时间，避免每批都白等超时
        with _FREE_STATE_LOCK:
            _QQ_DOWN_UNTIL = time.monotonic() + _QQ_DOWN_COOLDOWN
        log.warning(
            "腾讯翻译不可用，%d 分钟内不再尝试：%s",
            _QQ_DOWN_COOLDOWN // 60, exc,
        )
        return {}


def _mymemory_request(text: str, src_code: str, dst_code: str) -> str:
    """请求 MyMemory 翻译一句。失败/被限流返回空串（触发备用引擎）。"""
    params = urllib.parse.urlencode({
        "q": text,
        "langpair": f"{src_code}|{dst_code}",
    })
    url = f"{MYMEMORY_ENDPOINT}?{params}"

    for attempt in range(3):
        _throttle_free_request()
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "VideoDub/1.0 (+local app)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < 2:
                wait = 2.0 ** attempt  # 1s → 2s（3 秒内放弃）
                log.warning("MyMemory 限流（HTTP %d），%.0f 秒后重试", exc.code, wait)
                time.sleep(wait)
                continue
            if exc.code in (429, 503):
                _mm_pause(_MM_LIMIT_COOLDOWN, "连续被限流（HTTP 429）")
            else:
                log.warning("MyMemory 请求失败：HTTP %d", exc.code)
            return ""
        except Exception as exc:  # noqa: BLE001
            if attempt < 2:
                wait = 2.0 ** attempt
                log.warning(
                    "MyMemory 请求异常（第 %d/3 次）：%s，%.0f 秒后重试",
                    attempt + 1, exc, wait,
                )
                time.sleep(wait)
                continue
            log.warning("MyMemory 请求失败：%s", exc)
            return ""

        out = _extract_mymemory(payload, text)
        if out:
            return out

        # 没取到译文：区分「当日额度耗尽」与普通失败
        raw = ""
        try:
            raw = str((payload.get("responseData") or {}).get("translatedText") or "")
        except AttributeError:
            pass
        if "ALL AVAILABLE FREE TRANSLATIONS" in raw.upper():
            _mm_pause(_MM_QUOTA_COOLDOWN, "当日免费额度已用尽，改用备用引擎")
            return ""
        if payload.get("responseStatus") == 429 and attempt < 2:
            time.sleep(2.0 ** attempt)
            continue
        if payload.get("responseStatus") == 429:
            _mm_pause(_MM_LIMIT_COOLDOWN, "连续被限流")
            return ""
        return ""

    return ""


def _google_translate_one(text: str, src_code: str, dst_code: str) -> str:
    """Google 网页翻译接口兜底（免密钥）。连不上会熔断一段时间。"""
    global _GOOGLE_DOWN_UNTIL
    with _FREE_STATE_LOCK:
        if time.monotonic() < _GOOGLE_DOWN_UNTIL:
            return ""

    params = urllib.parse.urlencode({
        "client": "gtx", "sl": src_code, "tl": dst_code, "dt": "t", "q": text,
    })
    try:
        req = urllib.request.Request(
            f"{GOOGLE_ENDPOINT}?{params}",
            headers={"User-Agent": "VideoDub/1.0 (+local app)"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        parts = payload[0] or []
        return "".join(p[0] for p in parts if p and p[0]).strip()
    except Exception as exc:  # noqa: BLE001
        # 典型场景：国内网络访问不了 Google。熔断一段时间，
        # 避免后面每句话都白等一次超时拖慢整体进度。
        with _FREE_STATE_LOCK:
            _GOOGLE_DOWN_UNTIL = time.monotonic() + _GOOGLE_DOWN_COOLDOWN
        log.warning(
            "Google 兜底翻译不可用，%d 分钟内不再尝试：%s",
            _GOOGLE_DOWN_COOLDOWN // 60, exc,
        )
        return ""


def _extract_mymemory(payload: dict, original: str) -> str:
    """从 MyMemory 响应里取出译文。"""
    try:
        data = payload.get("responseData") or {}
        text = (data.get("translatedText") or "").strip()
    except AttributeError:
        return ""
    if not text:
        return ""
    text = html.unescape(text)

    # 接口在查不到时会原样返回、或返回错误提示，这些都要丢弃
    if text.strip().lower() == original.strip().lower():
        return ""
    if "MYMEMORY WARNING" in text.upper() or "QUERY LENGTH LIMIT" in text.upper():
        log.warning("免费翻译额度/长度限制：%s", text[:120])
        return ""
    if "PLEASE SELECT TWO DISTINCT LANGUAGES" in text.upper():
        return ""
    return text



def _llm_translate(
    texts: list[str],
    base_url: str,
    api_key: str,
    model: str,
    target: str,
    budgets: list[int] | None = None,
) -> list[str]:
    """批量翻译，返回与输入等长的数组。

    budgets: 每条译文的**建议字数上限**，由原句时长推算。
    告诉模型"这句话在画面里只有 3.6 秒，最多说 17 个字"，
    它就会给出更短更口语的译文，配音不用大幅变速。
    """
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"

    lang_name = {"zh": "简体中文", "en": "英文"}.get(target, target)

    if budgets and len(budgets) == len(texts):
        numbered = "\n".join(
            f"{idx + 1}. [≤{b}字] {t}"
            for idx, (t, b) in enumerate(zip(texts, budgets))
        )
        length_rule = (
            f"每条方括号里的数字是该句**最多能说多少个字**（按画面时长推算，"
            f"中文口播约 {ZH_CHARS_PER_SEC} 字/秒）。"
            f"请务必控制在字数上限内，宁可精简也不要超；"
            f"超时会导致配音说不完。数字只是上限，不必刻意凑满。"
        )
    else:
        numbered = "\n".join(f"{idx + 1}. {t}" for idx, t in enumerate(texts))
        length_rule = "每句尽量简短，控制在 25 字以内。"

    system = (
        "你是专业的视频字幕翻译。把用户给出的每条字幕翻译成"
        f"{lang_name}，要求：口语自然、简洁、符合字幕阅读习惯，"
        "不要添加解释，不要合并或拆分条目。"
    )
    user = (
        "请逐条翻译下面的字幕，严格保持条数不变，"
        f"按 `序号. 译文` 的格式输出，不要输出别的内容。\n{length_rule}\n\n"
        + numbered
    )

    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    # 429（请求太频繁）与 5xx（服务端临时故障）退避重试，
    # 避免一整批 20 句因为一次限流全部丢弃。
    payload = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if (exc.code == 429 or exc.code >= 500) and attempt < 2:
                wait = 3.0 * (attempt + 1)  # 3s → 6s
                log.warning(
                    "LLM 翻译被限流（HTTP %d），%.0f 秒后重试", exc.code, wait
                )
                time.sleep(wait)
                continue
            raise RuntimeError(f"翻译接口失败 HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接翻译服务：{exc.reason}") from exc
    if payload is None:
        raise RuntimeError("翻译接口无响应")

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("翻译接口返回格式异常") from exc

    return _parse_numbered(content, len(texts), texts)


def _parse_numbered(content: str, expected: int, fallback: list[str]) -> list[str]:
    """解析 `1. 译文` 格式，长度不符时按行兜底。"""
    result: dict[int, str] = {}
    for line in content.splitlines():
        m = re.match(r"^\s*(\d+)[.、)]\s*(.+?)\s*$", line)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < expected:
                result[idx] = m.group(2).strip()

    if len(result) == expected:
        return [result[i] for i in range(expected)]

    # 兜底：按非空行顺序填充，缺的用原文
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    out: list[str] = []
    for i in range(expected):
        if i in result:
            out.append(result[i])
        elif i < len(lines):
            out.append(re.sub(r"^\s*\d+[.、)]\s*", "", lines[i]).strip() or fallback[i])
        else:
            out.append(fallback[i])
    return out


# ============================================================== 译文后处理
# 免费翻译引擎（MyMemory）返回的中文字幕有几个通病，直接影响观感和配音：
#   1. 用英文标点（",." "?"）——中文 TTS 读到英文句点时不会降调，
#      整句听起来像没说完；字幕上也不规范。
#   2. 中文字符之间夹着多余空格。
#   3. 句末没有任何标点，TTS 语调发平。
#   4. 译文比原句能容纳的字数长——中文信息密度高，同一句话翻过来常常更啰嗦。
#      后果是配音必须疯狂加速，加速到上限还说不完就会盖住下一句。
# 下面两步分别解决前三点（polish_zh）和第四点（fit_to_budget）。

# 可安全删除的口语连接词/填充语。按"删了也不影响主要信息"的标准挑选，
# 且只在句子明显超长时才删，顺序上先删最啰嗦的。
_FILLERS = (
    "换句话说", "也就是说", "总的来看", "总的来说", "需要注意的是", "值得一提的是",
    "基本上来说", "一般来说", "具体来说",
    "事实上", "实际上", "基本上", "可以说", "应该说", "大家都知道",
    "我觉得", "我认为", "我们会发现", "你会发现", "我们可以看到",
    "那么", "然后", "其实", "就是说", "的话", "所以", "而且",
    "这个", "那个", "一个", "进行", "做出",
)

# 句子结束标点
_END_PUNCT = "。！？…；.!?;"

# 需要去掉的句首标点（精简后可能残留）
_LEAD_PUNCT = "，、；：,;:"


def _visible_len(text: str) -> int:
    """配音时长相关的字数：不计空白。"""
    return len(re.sub(r"\s+", "", text or ""))


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    n = len(re.findall(r"[\u4e00-\u9fff]", text))
    return n / max(len(text), 1)


def polish_zh(text: str) -> str:
    """把机器译文整理成适合上字幕 + 朗读的中文。

    只做标点与空白的规范化，不动语义，风险极低。
    """
    t = (text or "").strip()
    if not t:
        return t

    # 中文占比很低说明很可能没翻译成功，不要按中文规则改
    if _cjk_ratio(t) < 0.20:
        return t

    # 1. 保护数字里的小数点/千分位，避免 3.5 被改成 3。5
    slots: dict[str, str] = {}

    def _hold(m: re.Match) -> str:
        key = f"\x00{len(slots)}\x00"
        slots[key] = m.group(0)
        return key

    t = re.sub(r"\d[.,]\d", _hold, t)

    # 2. 英文标点 → 中文标点（只在中英混排安全的范围内替换）
    t = t.replace(",", "，").replace(";", "；").replace(":", "：")
    t = t.replace("?", "？").replace("!", "！")

    # 句点只在「前面是中文」时才转成句号，避免伤到 Mr. Smith / U.S.A
    t = re.sub(r"(?<=[\u4e00-\u9fff])\.(?=[\s\u4e00-\u9fff]|$)", "。", t)
    t = re.sub(r"\.(?=\s*$)", "。", t) if _cjk_ratio(t) > 0.3 else t

    # 3. 省略号规范化
    t = re.sub(r"\.{2,}", "……", t)
    t = re.sub(r"。{2,}", "……", t)
    t = re.sub(r"…{2,}", "……", t)

    # 4. 引号中文化（按出现顺序成对替换）
    if '"' in t or "'" in t:
        buf: list[str] = []
        opened = True
        for ch in t:
            if ch == '"':
                buf.append("“" if opened else "”")
                opened = not opened
            elif ch == "'":
                buf.append("‘" if opened else "’")
                opened = not opened
            else:
                buf.append(ch)
        t = "".join(buf)

    # 5. 中文字符之间的多余空格去掉（英文单词周围的空格保留）
    t = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", t)
    t = re.sub(r"\s+([，。！？；：、])", r"\1", t)
    t = re.sub(r"([，。！？；：、])\s+", r"\1", t)

    # 6. 还原被保护的数字
    for k, v in slots.items():
        t = t.replace(k, v)

    # 7. 去掉句首残留的停顿标点
    t = re.sub(r"^[\s，、；：]+", "", t)
    # 8. 重复标点合并
    t = re.sub(r"([，、；：])\1+", r"\1", t)

    return t.strip()


def _ensure_sentence_end(text: str) -> str:
    """句末补标点。

    TTS 遇到没有句末标点的文本时不会收尾降调，听起来像话说了一半，
    所以这里统一补一个句号（疑问/感叹语气已经从原标点看出来了）。
    """
    t = (text or "").strip().rstrip("，、；：,;:")
    if not t:
        return t
    if t[-1] in _END_PUNCT or t[-1] in "”’）)]}":
        return t
    return t + "。"


def _cut_at_punct(text: str, budget: int) -> tuple[str, bool]:
    """尝试在标点处把句子收短；找不到合适的断点就**原样返回**。

    为什么绝不硬截：
    实测 "But loving the process is key." 被翻成 "但热爱这个过程是关键。"
    （1.7 秒只放得下 8 个字），硬截到第 8 个字就成了 "但热爱这个过程是。" ——
    半句话比超长难看得多，观众宁可听快一点，也不要听半句。
    所以这里只在能停在标点上、且剩下的内容还够读时才收短。
    """
    if _visible_len(text) <= budget:
        return text, False

    # 先取到预算长度，只在这个窗口里找断点
    out: list[str] = []
    n = 0
    for ch in text:
        if n >= budget:
            break
        out.append(ch)
        if not ch.isspace():
            n += 1
    window = "".join(out)

    cut = -1
    for p in "，、；：。！？":
        pos = window.rfind(p)
        if pos > cut:
            cut = pos
    if cut < 0:
        return text, False          # 窗口里没有标点 → 不截

    # 断点太靠前说明收完就剩个零头，不划算
    if (cut + 1) < budget * 0.4:
        return text, False

    s = window[:cut + 1].rstrip(_LEAD_PUNCT)
    if _visible_len(s) < ZH_MIN_KEEP:
        return text, False

    return s, True


def fit_to_budget(text: str, budget: int) -> tuple[str, bool]:
    """把一句译文压缩到 budget 个字以内，返回 (新文本, 是否被改过)。

    两级降级：
      1. 删口语连接词（信息损失最小）
      2. 截断到预算字数，尽量停在标点处（保字数 = 保信息量）

    为什么不做"砍掉末尾分句"：
    中文一句话里逗号很少，砍掉最后一个分句往往等于砍掉大半句内容，
    得不偿失。截断虽然可能留下半个词，但保留的信息量明显更多。
    """
    t = (text or "").strip()
    if budget <= 0 or _visible_len(t) <= budget:
        return t, False

    # 1. 删填充词——只在「句首 / 分句首」删。
    #    这些词在这个位置纯粹是口语垫字，删掉不影响信息；
    #    反过来，句中的同类词往往是实义（"对我来说"里的"来说"），不能删，
    #    否则会留下 "基本上" 被删掉后剩下的 "来说，" 这种残句。
    for w in _FILLERS:
        if _visible_len(t) <= budget:
            break
        cand = re.sub(
            rf"(^|(?<=[，、；：。！？]))\s*{re.escape(w)}", "", t, count=1
        )
        # 别把话说没了
        if cand != t and _visible_len(cand) >= ZH_MIN_KEEP:
            t = cand

    t = re.sub(r"[，、]{2,}", "，", t)
    t = re.sub(r"[，、]{2,}", "，", t)
    t = re.sub(r"^[，、；：\s]+", "", t)
    if _visible_len(t) <= budget:
        return _ensure_sentence_end(t), True

    # 2. 收短——只在能停在标点上时才做
    t, cut = _cut_at_punct(t, budget)

    return _ensure_sentence_end(t), True


def polish_segments(
    segments: list[Segment],
    *,
    apply_budget: bool = True,
    cps: float = ZH_CHARS_PER_SEC,
    slack: float = ZH_BUDGET_SLACK,
    threshold: float = ZH_TRIM_THRESHOLD,
) -> dict:
    """对已经翻好的中文逐句做润色 + 时长预算适配。

    返回统计信息，供日志和前端展示。

    为什么放在翻译之后、配音之前：
    译文长短直接决定配音能不能在原时间槽里说完。与其等配音阶段
    把语速压到失真还说不完，不如在这里先把口语垫字去掉。

    预算怎么算：
    用「本句时长 + 后面停顿的一部分」，和配音阶段 dubbing.align_segments
    里的 available 口径保持一致（PAUSE_USE 借停顿），
    否则会把很多其实放得下的句子误判成超长。
    """
    stats = {"polished": 0, "trimmed": 0, "chars_saved": 0, "over_budget": 0}
    n = len(segments)

    for i, s in enumerate(segments):
        zh = (s.translated or s.text or "").strip()
        if not zh or not _has_chinese(zh):
            continue

        new = polish_zh(zh)
        if new != zh:
            stats["polished"] += 1

        if apply_budget and s.duration > 0:
            # 下一句开始前的空白，配音阶段会借用其中的 PAUSE_USE
            pause = 0.0
            if i + 1 < n:
                pause = max(segments[i + 1].start - s.end, 0.0)
            available = s.duration + pause * PAUSE_USE
            budget = max(ZH_MIN_KEEP, int(available * cps * slack))

            # 阈值定得比较松：轻度偏长靠配音那 10%~15% 的语速就吸收了，
            # 只有明显塞不下才动文字。宁可让配音稍微快点，
            # 也不要为了对齐把话说半截。
            if _visible_len(new) > budget * threshold:
                trimmed, changed = fit_to_budget(new, budget)
                if changed:
                    stats["chars_saved"] += (
                        _visible_len(new) - _visible_len(trimmed)
                    )
                    stats["trimmed"] += 1
                    new = trimmed
            if _visible_len(new) > budget:
                stats["over_budget"] += 1

        s.translated = _ensure_sentence_end(new)

    return stats


# ============================================================== 断句重建
def _join_words(parts: list[str]) -> str:
    """把词级 token 拼回文本。

    Whisper 的英文 token 常带前导空格（" You"、" want"），中文 token 不带。
    这里按需补空格，避免出现 "Youwanttochange" 这种情况。
    """
    out = ""
    for p in parts:
        if not out:
            out = p
            continue
        if p[:1].isspace() or out[-1:].isspace():
            out += p
        elif out[-1:].isascii() and out[-1:].isalnum() \
                and p[:1].isascii() and p[:1].isalnum():
            out += " " + p
        else:
            out += p
    return re.sub(r"\s+", " ", out).strip()


def sentences_from_words(
    words: list[dict],
    *,
    max_duration: float = 10.0,
    max_chars: int = 80,
) -> list[Segment]:
    """用**词级时间戳**重建完整句子。

    比按段合并更准确：Whisper 的一个段里可能包含好几个完整句子，
    只在段边界切分会把多个句子粘成一大坨（曾出现单句 21 秒的情况）。
    词级时间戳能精确定位每个句号的位置，切出来的句子时间范围才准。

    max_duration / max_chars 是安全上限：遇到说话人不停顿的长句时强制断开，
    避免一句配音过长、字幕溢出。
    """
    if not words:
        return []

    out: list[Segment] = []
    cur: list[dict] = []

    for w in words:
        cur.append(w)
        text = _join_words([x["text"] for x in cur])
        span = cur[-1]["end"] - cur[0]["start"]

        if _SENT_END.search(w["text"].strip()) \
                or span >= max_duration or len(text) >= max_chars:
            if text:
                out.append(Segment(
                    start=round(cur[0]["start"], 3),
                    end=round(cur[-1]["end"], 3),
                    text=text,
                ))
            cur = []

    if cur:
        text = _join_words([x["text"] for x in cur])
        if text:
            out.append(Segment(
                start=round(cur[0]["start"], 3),
                end=round(cur[-1]["end"], 3),
                text=text,
            ))

    return out


# 句末标点（含中英文）
_SENT_END = re.compile(r"""[.!?。！？…；;]["'”’)\]]*\s*$""")
# 有些 Whisper 分片会以连词/介词结尾，说明句子没说完
_DANGLING = re.compile(
    r"(?i)\b(and|or|but|so|the|a|an|to|of|in|on|at|for|with|that|which|"
    r"is|are|was|were|be|been|their|his|her|its|our|your|my|this|these|"
    r"those|as|if|when|while|because|than|from|by|into|about)\s*$"
)


def merge_into_sentences(
    segments: list[Segment],
    *,
    max_duration: float = 10.0,
    max_chars: int = 120,
) -> list[Segment]:
    """把 Whisper 按时间切的碎片合并成较完整的句子（**段级兜底方案**）。

    优先用 sentences_from_words（词级时间戳，边界更准）；
    云端 ASR 通常不返回词级时间戳，此时用这个段级方案兜底。

    时间轴取整组的第一句开始 / 最后一句结束，画面同步不受影响。
    """
    if not segments:
        return segments

    groups: list[list[Segment]] = []
    cur: list[Segment] = []

    for seg in segments:
        cur.append(seg)
        raw = seg.text.strip()
        span = cur[-1].end - cur[0].start
        chars = sum(len(s.text) for s in cur)

        ends = bool(_SENT_END.search(raw))
        dangling = bool(_DANGLING.search(raw))

        # 句子完整结束 → 收口；或超过上限 → 强制收口，避免一句话过长
        if (ends and not dangling) or span >= max_duration or chars >= max_chars:
            groups.append(cur)
            cur = []

    if cur:
        groups.append(cur)

    out: list[Segment] = []
    for g in groups:
        text = " ".join(s.text.strip() for s in g if s.text.strip()).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        out.append(Segment(
            start=g[0].start,
            end=g[-1].end,
            text=text,
            translated="",       # 合并后原文变了，旧译文作废
        ))
    return out


def segments_for_display(
    segments: list[Segment],
    *,
    max_chars: int = 34,
) -> list[Segment]:
    """把长句切成适合上屏的短字幕（只影响字幕文件，不影响配音）。

    为什么需要：
    配音按「完整句子」合成才有正确语调，但一句中文可能有 40~80 字，
    直接当字幕会把画面占满。所以字幕单独按标点切成 ≤max_chars 的小段，
    时间按文字长度**按比例分配**，仍然贴合原时间轴。
    """
    out: list[Segment] = []
    for seg in segments:
        text = (seg.translated or seg.text or "").strip()
        if not text:
            continue

        if len(text) <= max_chars:
            out.append(Segment(seg.start, seg.end, seg.text, seg.translated))
            continue

        chunks = _split_by_punct(text, max_chars)
        if len(chunks) <= 1:
            out.append(Segment(seg.start, seg.end, seg.text, seg.translated))
            continue

        span = max(seg.end - seg.start, 0.01)
        total_chars = sum(len(c) for c in chunks) or 1

        # 英文原文按同样比例分配，双语字幕才配套
        en_words = (seg.text or "").split()
        total_words = len(en_words)
        word_cursor = 0

        cursor = seg.start
        for i, chunk in enumerate(chunks):
            share = len(chunk) / total_chars
            piece = span * share
            end = seg.end if i == len(chunks) - 1 else cursor + piece

            if i == len(chunks) - 1:
                en_part = " ".join(en_words[word_cursor:])
            else:
                n = max(1, round(total_words * share))
                en_part = " ".join(en_words[word_cursor:word_cursor + n])
                word_cursor += n

            out.append(Segment(
                start=round(cursor, 3),
                end=round(max(end, cursor + 0.2), 3),
                text=en_part,
                translated=chunk,
            ))
            cursor = end

    return out


def split_caption(text: str, max_chars: int = 34) -> list[str]:
    """把一句过长字幕按标点切成适合上屏的短片段（供 dubbing 模块调用）。"""
    return _split_by_punct(text, max_chars)


def _split_by_punct(text: str, max_chars: int) -> list[str]:
    """按标点把长文本切成不超过 max_chars 的片段。"""
    # 先在句末标点处切
    pieces = [p for p in re.split(r"(?<=[。！？；!?;])", text) if p.strip()]
    if not pieces:
        pieces = [text]

    out: list[str] = []
    buf = ""
    for piece in pieces:
        # 单个片段本身就超长 → 再按逗号切
        if len(piece) > max_chars:
            if buf:
                out.append(buf)
                buf = ""
            sub = [p for p in re.split(r"(?<=[，,、：:])", piece) if p.strip()]
            if not sub:
                sub = [piece]
            for s in sub:
                if len(s) > max_chars:
                    if buf:
                        out.append(buf)
                        buf = ""
                    for i in range(0, len(s), max_chars):
                        out.append(s[i:i + max_chars])
                elif len(buf) + len(s) <= max_chars:
                    buf += s
                else:
                    out.append(buf)
                    buf = s
            continue

        if len(buf) + len(piece) <= max_chars:
            buf += piece
        else:
            if buf:
                out.append(buf)
            buf = piece

    if buf:
        out.append(buf)
    return [x for x in out if x.strip()]


# ============================================================== 统一入口
def transcribe_with_meta(
    audio_path: str | Path,
    *,
    engine: str = "local",
    model_id: str = "small",
    language: str | None = None,
    cloud: dict | None = None,
    progress: ProgressFn | None = None,
) -> tuple[list[Segment], str]:
    """识别语音，返回 (原始语言片段, 检测到的语言)。

    只做识别，**不做翻译** —— 翻译与断句合并由调用方决定顺序，
    这样「先合并断句再翻译」才有可能实现（见 merge_into_sentences）。
    """
    if engine == "cloud":
        cfg = cloud or {}
        return transcribe_cloud(
            audio_path,
            base_url=cfg.get("base_url", ""),
            api_key=cfg.get("api_key", ""),
            model=cfg.get("model", "whisper-1"),
            language=language,
            progress=progress,
        )
    return transcribe_local(
        audio_path,
        model_id=model_id,
        language=language,
        progress=progress,
    )


def transcribe(
    audio_path: str | Path,
    *,
    engine: str = "local",
    model_id: str = "small",
    language: str | None = None,
    translate_to_zh: bool = True,
    translate_provider: str = "auto",
    merge_sentences: bool = True,
    cloud: dict | None = None,
    progress: ProgressFn | None = None,
) -> list[Segment]:
    """完整识别流程（含断句合并 + 翻译），供简单调用场景使用。

    engine: 'local' | 'cloud'
    translate_provider: 'auto' | 'free' | 'llm' | 'none'
    """
    cfg = cloud or {}

    if translate_provider == "auto":
        has_llm = bool(
            cfg.get("translate_base_url") and cfg.get("translate_api_key")
            and cfg.get("translate_model")
        )
        translate_provider = "llm" if has_llm else "free"

    segs, detected = transcribe_with_meta(
        audio_path, engine=engine, model_id=model_id,
        language=language, cloud=cfg, progress=progress,
    )

    if merge_sentences:
        merged = merge_into_sentences(segs)
        if merged:
            segs = merged

    if not translate_to_zh or translate_provider == "none":
        for s in segs:
            if not s.translated:
                s.translated = s.text
        return segs

    return translate_segments(
        segs,
        target="zh",
        source_lang=detected or language or "",
        provider=translate_provider,
        base_url=cfg.get("translate_base_url", ""),
        api_key=cfg.get("translate_api_key", ""),
        model=cfg.get("translate_model", ""),
        progress=progress,
    )


def segments_to_srt(segments: Iterable[Segment], use_translation: bool = True) -> str:
    """生成 srt 字幕文本。"""
    lines: list[str] = []
    idx = 1
    for seg in segments:
        text = seg.translated if (use_translation and seg.translated) else seg.text
        text = (text or "").strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}")
        # 过长的一行按标点折成两行，字幕更好读
        lines.append("\n".join(_wrap_text(text, 22)))
        lines.append("")
        idx += 1
    return "\n".join(lines)


def segments_to_vtt(segments: Iterable[Segment], use_translation: bool = True) -> str:
    out = ["WEBVTT", ""]
    for seg in segments:
        text = seg.translated if (use_translation and seg.translated) else seg.text
        text = (text or "").strip()
        if not text:
            continue
        out.append(f"{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}")
        out.append(text)
        out.append("")
    return "\n".join(out)


def segments_to_plaintext(segments: Iterable[Segment]) -> str:
    return "\n".join(
        (s.translated or s.text).strip() for s in segments
        if (s.translated or s.text).strip()
    )


def _wrap_text(text: str, max_len: int, max_lines: int = 2) -> list[str]:
    """把字幕文本折成多行，优先在标点处断开。

    之前的实现只切一刀，遇到长文本会留下一条超长行（字幕会溢出画面）。
    这里改成贪心逐行折行，最多 max_lines 行；实在放不下才让末行略长。
    """
    text = text.strip()
    if len(text) <= max_len:
        return [text]

    lines: list[str] = []
    rest = text
    puncts = ("，", "。", "；", "：", "！", "？", ",", ".", ";", ":", "!", "?", "、")

    while rest and len(lines) < max_lines - 1:
        if len(rest) <= max_len:
            break
        # 在 max_len 附近找最靠后的标点
        cut = -1
        for p in puncts:
            pos = rest.rfind(p, 0, max_len + 1)
            if pos > cut:
                cut = pos
        if cut < max_len * 0.4:
            # 没找到合适标点 → 退而找空格
            sp = rest.rfind(" ", 0, max_len + 1)
            cut = sp if sp > max_len * 0.4 else max_len - 1
        lines.append(rest[:cut + 1].strip())
        rest = rest[cut + 1:].lstrip()

    if rest:
        lines.append(rest)

    return [ln for ln in lines if ln] or [text]


def fmt_ts(seconds: float) -> str:
    """把秒格式化成 srt 时间戳 00:00:00,000。"""
    seconds = max(seconds, 0.0)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# 兼容旧引用
_fmt_ts = fmt_ts


# ============================================================== 模型管理
def is_model_downloaded(model_id: str) -> bool:
    """检查模型是否已在本地缓存**且真实可用**。

    注意不能只看目录是否存在：HF 缓存会用符号链接指向 blobs/，
    Windows 上若无权限建链接，snapshots 下会留下 0 字节空文件，
    目录看着存在但模型其实不可用。所以这里校验 model.bin 的大小。
    """
    root = Path(MODEL_DIR)
    if not root.exists():
        return False

    for repo in root.glob(f"models--*faster-whisper-{model_id}"):
        snaps = repo / "snapshots"
        if not snaps.exists():
            continue
        for snap in snaps.iterdir():
            mb = snap / "model.bin"
            try:
                if mb.exists() and mb.stat().st_size > 1024:
                    return True
            except OSError:
                continue
    return False


def model_status() -> list[dict]:
    """返回各模型的可用状态，供前端展示。"""
    from config import WHISPER_MODELS
    out = []
    for m in WHISPER_MODELS:
        mid = m["id"]
        downloaded = is_model_downloaded(mid)
        out.append({
            **m,
            "downloaded": downloaded,
            "status": "ready" if downloaded else "not_downloaded",
        })
    return out


def clear_model_cache() -> None:
    _model_cache.clear()
