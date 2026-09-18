"""中文配音合成 + 智能时间轴对齐。

═══════════════════════════════════════════════════════════════════════
设计要点（这一版重写过，原因见文件末尾的「踩过的坑」）
═══════════════════════════════════════════════════════════════════════

1. 全程只拼接**同一种格式**的音频。
   配音是 MP3、静音是 WAV 时，ffmpeg 的 concat 协议会把 WAV 段整体丢掉
   （实测 42 秒的音轨只剩 32 秒，静音段 9.86 秒被吞得一点不剩）。
   所以每条配音合成后立刻转成 WAV，再和 WAV 静音段一起拼。

2. **原始时间槽 ≠ 实际播放时间**。
   每句配音在最终音轨里的真实区间记为 actual_start / actual_end，
   字幕由它生成 —— 字幕和声音因此是同一份数据，不可能对不上。

3. 时间不够时先「借停顿」再「压语速」。
   原句说完到下一句开始之间通常有 0.5~2 秒空白，先吃掉它（PAUSE_USE），
   不够了才考虑变速，且变速上限收到 1.35 倍，保证听感。

4. 落后了会往回追。
   某句实在放不下导致后续整体延后时，允许后面的句子在停顿里适当提前开始
   （每句最多 MAX_CATCHUP 秒），把累积误差拉回来。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from config import (
    FILL_GAPS,
    FILL_RATIO,
    MAX_CATCHUP,
    MAX_SPEED,
    MIN_GAP,
    MIN_SPEED,
    PAUSE_USE,
    SUB_LEAD,
    SUB_MAX_CHARS,
    SUB_TAIL,
    TTS_SAMPLE_RATE,
    VOICE_META,
)
from asr import Segment

log = logging.getLogger("videodub.tts")

ProgressFn = Callable[[float, str], None]


@dataclass
class DubbedLine:
    """一句合成结果。"""
    index: int
    segment: Segment
    audio: Path | None
    speech_duration: float      # 配音本身的时长（已含变速，实测值）
    speed: float                # 实际使用的语速
    slot_start: float           # 原始时间槽起点（画面里这句话本来的位置）
    slot_end: float             # 原始时间槽终点
    actual_start: float = 0.0   # ★ 在最终音轨中的真实开始时间
    actual_end: float = 0.0     # ★ 真实结束时间
    overflowed: bool = False    # 是否超时溢出

    @property
    def text(self) -> str:
        return (self.segment.translated or self.segment.text).strip()

    @property
    def drift(self) -> float:
        """实际播放位置相对原始时间槽的偏移，正数表示落后。"""
        return self.actual_start - self.slot_start


# ------------------------------------------------------------------ edge-tts
async def _synth_async(
    text: str,
    voice: str,
    out_path: Path,
    rate: str,
    volume: str,
    pitch: str,
) -> None:
    """调用 edge-tts 合成单句。"""
    import edge_tts

    communicate = edge_tts.Communicate(
        text, voice, rate=rate, volume=volume, pitch=pitch
    )
    await communicate.save(str(out_path))


def synthesize(
    text: str,
    voice: str,
    out_path: Path,
    *,
    rate_percent: int = 0,
    volume_percent: int = 0,
    pitch_hz: int = 0,
    retries: int = 3,
) -> Path:
    """合成一句话，返回音频文件路径。

    rate_percent: 语速增减百分比，如 +20 表示快 20%

    注意：这个函数在两种环境下都会被调用——
      * 后台任务线程里（没有事件循环）→ 用 asyncio.run 最直接
      * FastAPI 的 async 接口里（已在事件循环中）→ asyncio.run 会直接报
        "asyncio.run() cannot be called from a running event loop"
    所以这里先探测是否已有运行中的事件循环，有则改用独立线程跑。
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rate = f"{rate_percent:+d}%"
    volume = f"{volume_percent:+d}%"
    pitch = f"{pitch_hz:+d}Hz"

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            _run_synth(text, voice, out_path, rate, volume, pitch)
            if out_path.exists() and out_path.stat().st_size > 0:
                return out_path
            last_error = RuntimeError("合成结果为空")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log.warning("edge-tts 第 %d 次失败：%s", attempt + 1, exc)
            if attempt < retries - 1:
                import time
                time.sleep(1.0 + attempt)

    raise RuntimeError(f"语音合成失败：{last_error}")


def _run_synth(
    text: str, voice: str, out_path: Path, rate: str, volume: str, pitch: str
) -> None:
    """在合适的上下文中执行协程。

    如果当前线程已有运行中的事件循环（FastAPI async 接口的情形），
    asyncio.run 会抛错。此时在新线程里用 asyncio.run 执行，
    这样既能正常工作，又不需要把整个调用链改成 async。
    """
    coro = _synth_async(text, voice, out_path, rate, volume, pitch)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的循环 → 直接跑
        asyncio.run(coro)
        return

    # 已在事件循环中 → 换线程执行
    error: list[BaseException] = []

    def _worker() -> None:
        try:
            asyncio.run(_synth_async(text, voice, out_path, rate, volume, pitch))
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()

    if error:
        raise error[0]


async def synthesize_async(
    text: str,
    voice: str,
    out_path: Path,
    *,
    rate_percent: int = 0,
    volume_percent: int = 0,
    pitch_hz: int = 0,
) -> Path:
    """真正的异步版本，供 async 接口直接 await 使用。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    await _synth_async(
        text, voice, out_path,
        f"{rate_percent:+d}%", f"{volume_percent:+d}%", f"{pitch_hz:+d}Hz",
    )
    if not (out_path.exists() and out_path.stat().st_size > 0):
        raise RuntimeError("合成结果为空")
    return out_path


def list_voices() -> list[dict]:
    """返回可选中文音色，按 locale / 性别分组。"""
    out: list[dict] = []
    for short_name, meta in VOICE_META.items():
        out.append({
            "id": short_name,
            "label": meta["label"],
            "gender": meta["gender"],
            "gender_cn": "女声" if meta["gender"] == "Female" else "男声",
            "style": meta["style"],
            "locale": meta["locale"],
            "desc": meta["desc"],
        })
    return out


# ------------------------------------------------------------------ 音频工具
def _audio_len(path: Path, fallback: float = 0.0) -> float:
    """读取音频时长。"""
    try:
        from media_utils import probe
        d = probe(path).duration
        return d if d > 0 else fallback
    except Exception:  # noqa: BLE001
        return fallback


def _to_wav(src: Path, dst: Path) -> Path:
    """统一转成 24kHz 单声道 PCM WAV。

    这一步是必须的：拼接前所有片段必须同格式，否则 concat 协议
    会静默丢弃格式不一致的片段（详见文件头说明）。
    """
    from media_utils import run_ffmpeg

    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(src),
        "-ar", str(TTS_SAMPLE_RATE), "-ac", "1",
        "-acodec", "pcm_s16le",
        str(dst),
    ])
    return dst


def _apply_tempo(src: Path, dst: Path, speed: float) -> None:
    """用 ffmpeg atempo 滤镜变速（保持音高），输入输出均为 WAV。

    atempo 单次限制在 0.5~2.0，超出范围需要串联多级。
    """
    from media_utils import run_ffmpeg

    remaining = speed
    filters: list[str] = []
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")

    run_ffmpeg([
        "-i", str(src),
        "-filter:a", ",".join(filters),
        "-ar", str(TTS_SAMPLE_RATE),
        "-ac", "1",
        "-acodec", "pcm_s16le",
        str(dst),
    ])


# ------------------------------------------------------------------ 时间轴对齐
def align_segments(
    segments: list[Segment],
    voice: str,
    work_dir: Path,
    *,
    base_rate: int = 0,
    volume: int = 0,
    pitch: int = 0,
    auto_fit: bool = True,
    total_duration: float = 0.0,
    progress: ProgressFn | None = None,
) -> tuple[list[DubbedLine], list[Path]]:
    """逐句合成并做智能时间轴对齐。

    返回 (对齐结果列表, 按时间顺序排列的音频片段列表)。
    所有片段均为 WAV，可直接用 concat 协议拼接。
    """
    work_dir = Path(work_dir)
    wav_dir = work_dir / "wav"
    work_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)

    # 只处理有文本的句
    active = [
        i for i, seg in enumerate(segments)
        if (seg.translated or seg.text).strip()
    ]
    total = len(active) or 1

    # ---------- 1. 合成 + 归一化 + 精确测量（并发，edge-tts 是网络服务，
    #              串行逐句会花几分钟；6 路并发约快 5 倍且不易触发限流）
    natural: dict[int, float] = {}
    paths: dict[int, Path] = {}
    _lock = threading.Lock()

    def _synth_one(i: int) -> None:
        text = (segments[i].translated or segments[i].text).strip()
        mp3 = work_dir / f"line_{i:05d}_raw.mp3"
        try:
            synthesize(
                text, voice, mp3,
                rate_percent=base_rate,
                volume_percent=volume,
                pitch_hz=pitch,
            )
            wav = wav_dir / f"line_{i:05d}.wav"
            _to_wav(mp3, wav)
            length = _audio_len(wav, 0.0)
            with _lock:
                natural[i] = length
                paths[i] = wav
        except Exception as exc:  # noqa: BLE001
            log.warning("第 %d 句合成失败，跳过配音：%s", i, exc)

    workers = min(6, max(1, len(active)))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_synth_one, i) for i in active]
        for fut in as_completed(futures):
            fut.result()
            done += 1
            # 进度回调里可能抛取消异常（_check_cancel），此时线程池
            # 会等在途任务收尾（几秒内）再向上传播
            if progress:
                progress(done / total * 0.65, f"配音 {done}/{total}")

    voiced = [i for i in active if i in paths]
    if not voiced:
        return [], []

    # ---------- 2. 规划：放置位置 + 语速
    plan: dict[int, tuple[float, float]] = {}   # index -> (放置时间, 语速)
    cursor = 0.0
    prev_orig_end = 0.0

    for k, i in enumerate(voiced):
        seg = segments[i]
        orig_start = max(seg.start, 0.0)
        orig_end = max(seg.end, orig_start + 0.2)

        # 下一句的原始起点（最后一句用视频总长兜底）
        nxt_orig = (
            segments[voiced[k + 1]].start
            if k + 1 < len(voiced)
            else (total_duration or orig_end)
        )
        nat = natural[i]

        # 最早可放置时间：上一段实际结束后留出间隔
        earliest = cursor + MIN_GAP if k > 0 else 0.0
        place = max(orig_start, earliest)

        # 回追：如果已经落后，且这一句前面还有停顿可挤，就适度提前
        if k > 0:
            drift = cursor - prev_orig_end
            room = place - earliest
            if drift > 0.05 and room > 0:
                place -= min(drift, room, MAX_CATCHUP)

        # 可用长度：原语音时长 + 后面停顿的一部分（这是不再狂压语速的关键）
        pause = max(nxt_orig - orig_end, 0.0)
        usable_end = orig_end + pause * PAUSE_USE
        usable_end = min(usable_end, nxt_orig - MIN_GAP)
        available = max(usable_end - place, 0.5)

        speed = _decide_speed(nat, available, auto_fit)
        used = nat / speed if speed > 0 else nat

        plan[i] = (place, speed)
        cursor = place + used
        prev_orig_end = orig_end

    # ---------- 3. 变速（输出仍是 WAV）
    for i, (place, speed) in list(plan.items()):
        if abs(speed - 1.0) <= 0.01:
            continue
        src = paths[i]
        dst = wav_dir / f"line_{i:05d}_fit.wav"
        try:
            _apply_tempo(src, dst, speed)
            paths[i] = dst
        except Exception as exc:  # noqa: BLE001
            log.warning("第 %d 句变速失败，改用原速：%s", i, exc)
            plan[i] = (place, 1.0)

    # ---------- 4. 用实测时长做最终放置，并生成静音段
    lines: list[DubbedLine] = []
    parts: list[Path] = []
    cursor = 0.0
    sil_dir = work_dir / "silence"
    sil_dir.mkdir(parents=True, exist_ok=True)
    sil_n = 0

    def _gap(seconds: float) -> None:
        """生成一段静音并接上，同时推进游标。"""
        nonlocal sil_n, cursor
        if seconds <= 0.01:
            return
        p = sil_dir / f"sil_{sil_n:05d}.wav"
        sil_n += 1
        _make_silence(seconds, p)
        parts.append(p)
        cursor += _audio_len(p, seconds)

    for k, i in enumerate(voiced):
        place, speed = plan[i]
        dur = _audio_len(paths[i], natural.get(i, 0.0))

        start = place if k == 0 else max(place, cursor + MIN_GAP)
        if total_duration > 0:
            start = min(start, max(total_duration - 0.05, 0.0))

        if start - cursor > 0.01:
            _gap(start - cursor)

        parts.append(paths[i])
        end = start + dur
        cursor = end

        seg = segments[i]
        lines.append(DubbedLine(
            index=i,
            segment=seg,
            audio=paths[i],
            speech_duration=dur,
            speed=speed,
            slot_start=seg.start,
            slot_end=seg.end,
            actual_start=start,
            actual_end=end,
            overflowed=end > seg.end + 0.15,
        ))

    # 末尾补齐，保证音轨不短于视频
    if total_duration > 0 and cursor < total_duration - 0.01:
        _gap(total_duration - cursor)

    # 未成功合成的句子也保留占位，前端统计才准确
    done = {ln.index for ln in lines}
    for i, seg in enumerate(segments):
        if i in done or not (seg.translated or seg.text).strip():
            continue
        lines.append(DubbedLine(
            index=i, segment=seg, audio=None, speech_duration=0.0, speed=1.0,
            slot_start=seg.start, slot_end=seg.end,
            actual_start=seg.start, actual_end=seg.end,
        ))
    lines.sort(key=lambda x: x.index)

    # 重新判定"溢出"：借停顿是有意为之，不算溢出；
    # 只有真正和下一句叠在一起、或超出视频末尾才算。
    ordered = [ln for ln in lines if ln.audio is not None]
    for k, ln in enumerate(ordered):
        overlaps_next = (
            k + 1 < len(ordered)
            and ln.actual_end > ordered[k + 1].actual_start - 0.02
        )
        over_end = total_duration > 0 and ln.actual_end > total_duration + 0.05
        ln.overflowed = overlaps_next or over_end

    return lines, parts


def _make_silence(seconds: float, dst: Path) -> Path:
    from media_utils import silence
    return silence(max(seconds, 0.01), dst, TTS_SAMPLE_RATE)


def _decide_speed(natural_len: float, available: float, auto_fit: bool) -> float:
    """决定语速。

    优先级：不变速 > 借停顿 > 加速 > 减速填充。
    加速上限收到 MAX_SPEED（1.35），超过太多宁可让它占用后面对白前的一点空隙，
    也不把人声压成机器人。
    """
    if not auto_fit or available <= 0 or natural_len <= 0:
        return 1.0

    if natural_len <= available:
        # 塞得下。若短得太多，略微放慢填满，避免长时间空白
        if FILL_GAPS and natural_len < available * 0.75:
            return max(natural_len / (available * FILL_RATIO), MIN_SPEED)
        return 1.0

    # 塞不下 → 加速，但不超过上限
    return min(max(natural_len / available, MIN_SPEED), MAX_SPEED)


# ------------------------------------------------------------------ 字幕生成
def build_subtitle_segments(
    lines: list[DubbedLine],
    *,
    max_chars: int = SUB_MAX_CHARS,
    lead: float = SUB_LEAD,
    tail: float = SUB_TAIL,
) -> list[Segment]:
    """用**配音的真实播放区间**生成字幕。

    为什么不用原始时间轴：
    配音经过变速/借停顿后，实际播放位置已经和原时间轴不完全一致。
    字幕若还按原时间轴排，就会出现"声音先到、字幕后到"的错位。
    这里直接用 actual_start/actual_end，字幕和声音出自同一份数据，
    理论上不可能对不上。

    长句仍按标点切成短字幕，时间按字数比例在该区间内分配。
    """
    from asr import split_caption

    out: list[Segment] = []
    prev_end = -1.0

    for ln in lines:
        if ln.audio is None:
            continue
        zh = (ln.segment.translated or ln.segment.text or "").strip()
        en = (ln.segment.text or "").strip()
        if not zh:
            continue

        start = max(ln.actual_start - lead, 0.0)
        end = ln.actual_end + tail
        if start < prev_end:
            start = prev_end

        if len(zh) <= max_chars:
            out.append(Segment(start=round(start, 3), end=round(end, 3),
                               text=en, translated=zh))
            prev_end = end
            continue

        chunks = split_caption(zh, max_chars)
        if len(chunks) <= 1:
            out.append(Segment(start=round(start, 3), end=round(end, 3),
                               text=en, translated=zh))
            prev_end = end
            continue

        span = max(end - start, 0.01)
        total_chars = sum(len(c) for c in chunks) or 1
        en_words = en.split()
        total_words = len(en_words)
        word_cursor = 0
        cursor = start

        for j, chunk in enumerate(chunks):
            share = len(chunk) / total_chars
            piece = span * share
            seg_end = end if j == len(chunks) - 1 else cursor + piece

            if j == len(chunks) - 1:
                en_part = " ".join(en_words[word_cursor:])
            else:
                n = max(1, round(total_words * share))
                en_part = " ".join(en_words[word_cursor:word_cursor + n])
                word_cursor += n

            out.append(Segment(
                start=round(cursor, 3),
                end=round(max(seg_end, cursor + 0.2), 3),
                text=en_part,
                translated=chunk,
            ))
            cursor = seg_end

        prev_end = end

    return out


# ------------------------------------------------------------------ 配音方案
def build_dub_plan(
    lines: list[DubbedLine],
    total_duration: float,
) -> dict:
    """生成配音计划的统计信息，供前端展示。"""
    voiced = [ln for ln in lines if ln.audio is not None]
    overflowed = [ln for ln in voiced if ln.overflowed]
    sped = [ln for ln in voiced if abs(ln.speed - 1.0) > 0.01]
    drifts = [ln.drift for ln in voiced]

    speech_total = sum(ln.speech_duration for ln in voiced)
    return {
        "total_lines": len(lines),
        "voiced_lines": len(voiced),
        "failed_lines": len(lines) - len(voiced),
        "overflowed_lines": len(overflowed),
        "speed_adjusted_lines": len(sped),
        "avg_speed": round(
            sum(ln.speed for ln in voiced) / len(voiced), 3
        ) if voiced else 1.0,
        "max_speed": round(max((ln.speed for ln in voiced), default=1.0), 3),
        "speech_seconds": round(speech_total, 2),
        "video_seconds": round(total_duration, 2),
        "coverage": round(
            speech_total / total_duration, 4
        ) if total_duration > 0 else 0.0,
        # 同步质量：配音实际播放位置相对原时间轴的偏移
        "max_drift": round(max((abs(d) for d in drifts), default=0.0), 2),
        "final_drift": round(drifts[-1], 2) if drifts else 0.0,
    }


def suggest_rate(lines: list[DubbedLine], total_duration: float) -> int:
    """根据溢出情况建议一个全局语速微调值（百分比）。"""
    voiced = [ln for ln in lines if ln.audio is not None]
    if not voiced or total_duration <= 0:
        return 0
    speech = sum(ln.speech_duration for ln in voiced)
    ratio = speech / total_duration
    if ratio <= 0.95:
        return 0
    # 中文语音与英文原声的语速差，给一个温和的加速建议
    suggestion = min(int((ratio - 1.0) * 100 * 0.8), 25)
    return max(suggestion, 0)


# ══════════════════════════════════════════════════════════════════════
# 踩过的坑（2026-09，真实 bug，改代码前请先读）
#
# 1. concat 协议会吞掉格式不一致的片段
#    配音 MP3 + 静音 WAV 混在一起交给 `-f concat`，ffmpeg 只保留了 MP3，
#    所有静音段被整段丢弃。42 秒的音轨出来只有 32 秒，
#    少了的 9.864 秒精确等于静音段之和。
#    表现：声音一路抢跑，越到后面字幕离声音越远。
#    修法：拼接前把所有片段统一转成 WAV（_to_wav），静音也用 WAV。
#
# 2. 不要用 ffprobe 读 MP3 的时长
#    edge-tts 返回的 MP3 没有 Xing 头，ffprobe 会打印
#    "Estimating duration from bitrate, this may be inaccurate"，
#    估算值可能偏差 10% 以上，导致后续所有时间计算失准。
#    修法：先转 WAV 再测量。
#
# 3. 字幕必须跟着配音走，不能跟着原时间轴走
#    配音变速、借停顿之后，实际播放位置和原始时间槽必然不同。
#    修法：DubbedLine 增加 actual_start/actual_end，字幕由它生成。
# ══════════════════════════════════════════════════════════════════════
