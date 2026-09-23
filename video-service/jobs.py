"""任务编排：把「识别 → 翻译 → 配音 → 对齐 → 合成」串成一条流水线。

任务状态存放在内存里，并实时推给前端（轮询 /jobs/{id}）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asr
import config
import dubbing
import ocr_subtitle
import media_utils as mu
from config import DATA_DIR, OUTPUT_DIR, UPLOAD_DIR, WORK_DIR

log = logging.getLogger("videodub.jobs")

# --------------------------------------------------------------- 持久化
# 任务状态落盘，服务重启后按用户恢复历史。running 状态重启后视为 failed。
JOBS_DB = DATA_DIR / "jobs.json"


STAGES = [
    ("probe",    "分析视频"),
    ("extract",  "分离音频"),
    ("transcribe", "识别语音"),
    ("translate", "翻译字幕"),
    ("dub",      "合成配音"),
    ("mix",      "合成视频"),
]


@dataclass
class Job:
    id: str
    filename: str
    source: Path
    options: dict
    user: str = "default"          # 归属用户（前端匿名 uid），用于任务隔离
    status: str = "pending"        # pending|running|done|failed|cancelled
    stage: str = "probe"
    stage_label: str = "等待开始"
    progress: float = 0.0
    message: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    # 结果
    media: dict = field(default_factory=dict)
    segments: list[dict] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    outputs: list[dict] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)

    # 耗时统计：各阶段秒数 + 总计
    stage_timings: dict = field(default_factory=dict)
    total_seconds: float = 0.0
    _stage_started_at: float = 0.0

    # 取消标记
    cancelled: bool = False

    # 已发布到视频库（所有人可见）
    published: bool = False
    published_at: float = 0.0

    def to_dict(self, with_segments: bool = True) -> dict:
        d = {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "stage": self.stage,
            "stage_label": self.stage_label,
            "progress": round(self.progress, 4),
            "message": self.message,
            "error": self.error,
            "media": self.media,
            "plan": self.plan,
            "outputs": self.outputs,
            "logs": self.logs[-40:],
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "stage_timings": {k: round(v, 1) for k, v in self.stage_timings.items()},
            "total_seconds": round(self.total_seconds, 1),
            "published": self.published,
            "published_at": self.published_at,
            "options": {k: v for k, v in self.options.items()
                        if k not in ("cloud_api_key",)},
        }
        if with_segments:
            d["segments"] = self.segments
        return d

    def stage_index(self) -> int:
        for i, (key, _) in enumerate(STAGES):
            if key == self.stage:
                return i
        return len(STAGES)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._load()

    # -------------------------------------------------------- 持久化
    def _load(self) -> None:
        """启动时从 jobs.json 恢复历史任务；文件缺失/损坏时忽略。"""
        if not JOBS_DB.exists():
            return
        try:
            raw = json.loads(JOBS_DB.read_text(encoding="utf-8"))
            count = 0
            for d in raw.get("jobs", []):
                # 运行中被中断的任务标记为失败
                if d.get("status") == "running":
                    d["status"] = "failed"
                    d["stage_label"] = "服务重启中断"
                    d["error"] = d.get("error") or "服务重启中断"
                    d["message"] = "服务重启中断"
                try:
                    job = Job(
                        id=d["id"], filename=d["filename"],
                        source=Path(d["source"]), options=d.get("options", {}),
                        user=d.get("user", "default"),
                    )
                    job.status = d.get("status", "failed")
                    job.stage = d.get("stage", "probe")
                    job.stage_label = d.get("stage_label", "")
                    job.progress = d.get("progress", 0.0)
                    job.message = d.get("message", "")
                    job.error = d.get("error", "")
                    job.created_at = d.get("created_at", 0.0)
                    job.finished_at = d.get("finished_at", 0.0)
                    job.media = d.get("media", {})
                    job.segments = d.get("segments", [])
                    job.plan = d.get("plan", {})
                    job.outputs = d.get("outputs", [])
                    job.logs = d.get("logs", [])
                    job.stage_timings = d.get("stage_timings", {})
                    job.total_seconds = d.get("total_seconds", 0.0)
                    job.published = d.get("published", False)
                    job.published_at = d.get("published_at", 0.0)
                    self._jobs[job.id] = job
                    count += 1
                except (KeyError, ValueError) as exc:  # noqa: BLE001
                    log.warning("跳过损坏的任务记录：%s (%s)", d.get("id"), exc)
            log.info("已从 jobs.json 恢复 %d 个任务", count)
        except Exception as exc:  # noqa: BLE001
            log.warning("读取 jobs.json 失败，忽略历史：%s", exc)

    def _save(self) -> None:
        """把所有任务写盘（自带锁）。失败仅记日志，不影响主流程。"""
        with self._lock:
            try:
                JOBS_DB.parent.mkdir(parents=True, exist_ok=True)
                jobs = [j.to_dict(with_segments=False) for j in self._jobs.values()]
                # 补充 to_dict 未包含的字段
                for j, job in zip(jobs, list(self._jobs.values())):
                    j["source"] = str(job.source)
                    j["user"] = job.user
                tmp = JOBS_DB.with_suffix(".json.tmp")
                tmp.write_text(
                    json.dumps({"jobs": jobs}, ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp.replace(JOBS_DB)
            except Exception as exc:  # noqa: BLE001
                log.warning("保存 jobs.json 失败：%s", exc)

    def set_published(self, jid: str, published: bool) -> Job | None:
        """发布/取消发布到视频库。返回更新后的任务，不存在返回 None。"""
        with self._lock:
            job = self._jobs.get(jid)
            if not job:
                return None
            job.published = published
            job.published_at = time.time() if published else 0.0
        self._save()
        return job

    # ---------------------------------------------------------- 增删查
    def create(self, filename: str, source: Path, options: dict, user: str = "default") -> Job:
        jid = uuid.uuid4().hex[:12]
        job = Job(id=jid, filename=filename, source=source, options=options, user=user)
        with self._lock:
            self._jobs[jid] = job
        return job

    def get(self, jid: str) -> Job | None:
        with self._lock:
            return self._jobs.get(jid)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def cancel(self, jid: str) -> bool:
        job = self.get(jid)
        if not job or job.status not in ("pending", "running"):
            return False
        job.cancelled = True
        job.message = "正在取消…"
        return True

    def remove(self, jid: str) -> bool:
        job = self.get(jid)
        if not job:
            return False
        if job.status == "running":
            return False
        with self._lock:
            self._jobs.pop(jid, None)
        shutil.rmtree(WORK_DIR / jid, ignore_errors=True)
        self._save()
        return True

    # ---------------------------------------------------------- 执行
    def start(self, job: Job) -> None:
        t = threading.Thread(target=self._run, args=(job,), daemon=True)
        t.start()

    def _run(self, job: Job) -> None:
        job.status = "running"
        started = time.time()
        try:
            self._pipeline(job)
            if job.cancelled:
                job.status = "cancelled"
                job.stage_label = "已取消"
            else:
                job.status = "done"
                job.progress = 1.0
                job.stage_label = "全部完成"
                job.message = "处理完成"
        except CancelledError:
            job.status = "cancelled"
            job.stage_label = "已取消"
            job.message = "任务已取消"
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.stage_label = "处理失败"
            job.message = str(exc)
            job.logs.append(f"[错误] {exc}")
            log.error("任务 %s 失败：%s\n%s", job.id, exc, traceback.format_exc())
        except BaseException as exc:  # noqa: BLE001
            # 兜底：连 KeyboardInterrupt / MemoryError 之类也要落状态，
            # 否则任务会永远停在 running，前端一直转圈。
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.stage_label = "处理中断"
            job.message = job.error
            job.logs.append(f"[中断] {job.error}")
            log.error("任务 %s 被中断：%s", job.id, exc)
        finally:
            # 结算最后一个阶段的耗时并汇总总计
            now = time.time()
            JobManager._close_stage(job, now)
            job.total_seconds = now - started
            job.finished_at = now
            parts = " · ".join(
                f"{dict(STAGES).get(k, k)} {v / 60:.1f} 分钟"
                for k, v in job.stage_timings.items() if v >= 0.05
            )
            job.logs.append(
                f"[耗时] 总计 {job.total_seconds / 60:.1f} 分钟"
                + (f"（{parts}）" if parts else "")
            )
            # 双保险：如果状态仍是 running，说明上面分支都没走到，强制标记
            if job.status == "running":
                job.status = "failed"
                job.error = job.error or "任务异常结束"
                job.stage_label = "处理失败"
            self._save()

    # ---------------------------------------------------------- 流水线
    def _pipeline(self, job: Job) -> None:
        opt = job.options
        work = WORK_DIR / job.id
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)

        self._check_cancel(job)

        # ---------- 1. 分析视频
        self._set(job, "probe", 0.02, "正在分析视频信息…")
        info = mu.probe(job.source)
        if not info.has_video:
            raise RuntimeError("这个文件里没有视频轨道，请上传视频文件")
        job.media = {
            "duration": round(info.duration, 3),
            "width": info.width,
            "height": info.height,
            "fps": round(info.fps, 2),
            "resolution": info.resolution,
            "has_audio": info.has_audio,
            "audio_codec": info.audio_codec,
            "video_codec": info.video_codec,
            "subtitle_streams": info.subtitle_streams,
        }
        job.logs.append(
            f"[视频] {info.resolution} · {info.duration:.1f}s · "
            f"音频 {'有' if info.has_audio else '无'}"
        )
        if not info.has_audio:
            raise RuntimeError("这个视频没有音轨，无法识别语音")

        total_duration = info.duration
        self._check_cancel(job)

        # ---------- 2. 分离音频
        self._set(job, "extract", 0.05, "正在分离音频…")
        audio_path = mu.extract_audio(job.source, work / "source_16k.wav")
        job.logs.append("[音频] 已分离出 16kHz 单声道音轨")

        # 如果用户选择使用内嵌字幕，优先走字幕路线（更准、更快）
        segments: list[asr.Segment] = []
        use_embedded = bool(opt.get("use_embedded_subtitle"))
        embedded_used = False

        if use_embedded and info.subtitle_streams:
            try:
                segs = self._from_embedded(job, info, work)
                if segs:
                    segments = segs
                    embedded_used = True
                    job.logs.append(
                        f"[字幕] 使用内嵌字幕流，共 {len(segments)} 句"
                    )
            except Exception as exc:  # noqa: BLE001
                job.logs.append(f"[字幕] 内嵌字幕读取失败，改用语音识别：{exc}")

        if not segments and opt.get("subtitle_file"):
            try:
                segs = self._from_srt(Path(opt["subtitle_file"]))
                if segs:
                    segments = segs
                    embedded_used = True
                    job.logs.append(f"[字幕] 使用外挂字幕，共 {len(segments)} 句")
            except Exception as exc:  # noqa: BLE001
                job.logs.append(f"[字幕] 外挂字幕读取失败：{exc}")

        # ---------- 3. 语音识别（或硬字幕 OCR 提取）
        detected_lang = ""
        if not segments and opt.get("ocr_hard_subtitle"):
            # 用户指定字幕烧录在画面里：OCR 提取代替语音识别
            self._set(job, "transcribe", 0.10, "正在从画面提取硬字幕…")

            def ocr_progress(p: float, msg: str) -> None:
                self._check_cancel(job)
                job.progress = 0.10 + p * 0.30
                job.message = msg

            ocr_segs = ocr_subtitle.extract_hard_subtitles(
                job.source, work, progress=ocr_progress,
                duration_hint=total_duration,
            )
            if not ocr_segs:
                raise RuntimeError(
                    "未能从画面中提取到任何字幕文字。请确认视频确实带硬字幕，"
                    "或改用「上传外挂字幕 / 语音识别」方式。"
                )
            segments = ocr_segs
            zh_cnt = sum(1 for s in segments if asr._has_chinese(s.text))
            # 中文为主 → 标记源语言为中文，后面自动跳过翻译
            if zh_cnt * 2 >= len(segments):
                detected_lang = "zh"
                # 第二道防线：OCR 层理论上已把纯外文伴字幕帧置空，
                # 这里再兜底一次——中文为主片源里残留的纯英文段绝不进
                # 中文 TTS（否则念英文且多占时长导致配音落后画面），
                # 中文段里夹混的外文词（Hi/OK）一并清洗。
                zh_segments = []
                en_dropped = 0
                for s in segments:
                    if asr._has_chinese(s.text):
                        s.text = ocr_subtitle.strip_latin_words(s.text)
                        zh_segments.append(s)
                    else:
                        en_dropped += 1
                if en_dropped:
                    job.logs.append(
                        f"[字幕] 中文为主片源，剔除 {en_dropped} 个纯英文伴字幕段"
                        "（不参与中文配音）"
                    )
                segments = zh_segments
                zh_cnt = len(segments)
            job.logs.append(
                f"[字幕] OCR 提取画面硬字幕 {len(segments)} 句"
                f"（中文 {zh_cnt} 句）"
            )

        if not segments:
            self._set(job, "transcribe", 0.10, "正在识别语音…")
            engine = opt.get("engine", "local")

            def asr_progress(p: float, msg: str) -> None:
                self._check_cancel(job)
                job.progress = 0.10 + p * 0.30
                job.message = msg

            raw_segments, detected_lang = asr.transcribe_with_meta(
                audio_path,
                engine=engine,
                model_id=opt.get("whisper_model", config.DEFAULT_WHISPER_MODEL),
                language=opt.get("source_language") or None,
                cloud={
                    "base_url": opt.get("cloud_base_url", ""),
                    "api_key": opt.get("cloud_api_key", ""),
                    "model": opt.get("cloud_asr_model", "whisper-1"),
                },
                progress=asr_progress,
            )
            job.logs.append(
                f"[识别] {engine} 引擎完成，共 {len(raw_segments)} 段"
                + (f"（语言：{detected_lang}）" if detected_lang else "")
            )

            # 断句合并：Whisper 按时间切分，会在一句话中间断开。
            # 先合并成完整句子再翻译与配音，中文才自然、TTS 语调才正确。
            if opt.get("merge_sentences", True):
                merged = asr.merge_into_sentences(raw_segments)
                if merged and len(merged) != len(raw_segments):
                    job.logs.append(
                        f"[字幕] 断句合并：{len(raw_segments)} 段 → {len(merged)} 句"
                    )
                segments = merged or raw_segments
            else:
                segments = raw_segments

        if detected_lang:
            job.media["detected_language"] = detected_lang

        if not segments:
            raise RuntimeError("没有识别到任何语音内容，请确认视频里有清晰的说话声")

        # 识别结果写入 srt，方便用户先检查
        raw_srt = work / "recognized.srt"
        raw_srt.write_text(asr.segments_to_srt(segments), encoding="utf-8")
        job.segments = [s.to_dict() for s in segments]

        self._check_cancel(job)

        # ---------- 4. 确认中文文本
        need_translate = bool(opt.get("translate_to_zh", True))
        provider = opt.get("translate_provider", "auto")
        src_lang = detected_lang or opt.get("source_language", "")

        # 「字幕已是中文」模式：英文视频 + 现成中文字幕，跳过识别与翻译。
        # 仅在字幕路线生效（detected_lang 为空表示没走语音识别）。
        # 误开保护：字幕内容基本不是中文时直接报错，避免英文文本被当成
        # 中文 TTS 读出来。
        if opt.get("subtitles_already_zh") and segments and not detected_lang:
            zh_cnt = sum(1 for s in segments if asr._has_chinese(s.text))
            if zh_cnt * 3 < len(segments):
                raise RuntimeError(
                    "你开启了「字幕已是中文」模式，但上传的字幕里 "
                    f"只有 {zh_cnt}/{len(segments)} 句是中文。"
                    "请关闭该模式（会自动走语音识别+翻译流程）。"
                )
            detected_lang = "zh"
            src_lang = "zh"
            # 瞬时标记两个被跳过的阶段，进度条平滑、耗时统计可见
            self._set(job, "transcribe", 0.12, "字幕已是中文，跳过语音识别")
            self._set(job, "translate", 0.44, "字幕已是中文，跳过翻译")
            job.logs.append(
                f"[模式] 字幕已是中文（{len(segments)} 句）："
                "跳过语音识别与翻译，直接配音"
            )

        # 智能兜底：字幕路线（无识别语言）时若字幕内容本身已是中文，
        # 即使没开上面的开关也不浪费翻译请求
        elif need_translate and not detected_lang and segments:
            zh_cnt = sum(1 for s in segments if asr._has_chinese(s.text))
            if zh_cnt * 2 >= len(segments):
                src_lang = "zh"
                job.logs.append(
                    f"[翻译] 检测到字幕本身已是中文（{zh_cnt}/{len(segments)} 句），"
                    "跳过翻译"
                )

        # 源语言本身就是中文 → 无需翻译，原文即字幕
        if need_translate and asr._is_chinese_lang(src_lang):
            for s in segments:
                if not s.translated:
                    s.translated = s.text
            need_translate = False
            if src_lang != "zh":
                job.logs.append("[翻译] 源语言为中文，无需翻译")

        missing = [s for s in segments if not s.translated.strip()]
        if need_translate and missing:
            self._set(job, "translate", 0.42, "正在翻译为中文…")

            def tr_progress(p: float, msg: str) -> None:
                self._check_cancel(job)
                job.progress = 0.42 + p * 0.13
                job.message = msg

            # 翻译失败直接让任务失败（不再保留原文出片）
            segments = asr.translate_segments(
                segments,
                target="zh",
                source_lang=src_lang,
                provider=provider,
                base_url=opt.get("translate_base_url", ""),
                api_key=opt.get("translate_api_key", ""),
                model=opt.get("translate_model", ""),
                progress=tr_progress,
            )
            # 统计真正翻成中文的比例，前端可据此提示
            zh_ok = sum(1 for s in segments if asr._has_chinese(s.translated))
            job.logs.append(
                f"[翻译] 中文字幕已生成（{zh_ok}/{len(segments)} 句）"
            )
            job.segments = [s.to_dict() for s in segments]
        else:
            for s in segments:
                if not s.translated:
                    s.translated = s.text
            job.segments = [s.to_dict() for s in segments]
            if not need_translate and not asr._is_chinese_lang(src_lang):
                job.logs.append("[翻译] 按设置保留原文")

        # 用户手工改过的字幕优先
        edited = opt.get("edited_segments")
        if edited:
            try:
                segments = [asr.Segment.from_dict(d) for d in edited]
                job.segments = [s.to_dict() for s in segments]
                job.logs.append("[字幕] 已应用手工修改")
            except Exception as exc:  # noqa: BLE001
                job.logs.append(f"[字幕] 手工修改解析失败，忽略：{exc}")

        self._check_cancel(job)

        # ---------- 5. 译文润色 + 时长预算
        # 免费翻译引擎给出的中文常常：带英文标点、句末没标点、
        # 字数远超原句能容纳的长度。前者让字幕不规范、TTS 语调发平，
        # 后者会让配音加速到上限还说不完，进而盖住下一句。
        # 这里统一收口，然后才进入配音。
        try:
            stats = asr.polish_segments(segments)
            if stats["polished"] or stats["trimmed"]:
                job.segments = [s.to_dict() for s in segments]
                job.logs.append(
                    f"[润色] 标点规范化 {stats['polished']} 句 · "
                    f"超长精简 {stats['trimmed']} 句（省 {stats['chars_saved']} 字）"
                )
            if stats["over_budget"]:
                job.logs.append(
                    f"[提示] 仍有 {stats['over_budget']} 句偏长，"
                    f"配音会略微加速；可在字幕页手工改短"
                )
        except Exception as exc:  # noqa: BLE001
            # 润色只是增益，失败绝不能让任务挂掉
            job.logs.append(f"[润色] 跳过（{exc}）")

        self._check_cancel(job)

        # ---------- 6. 合成配音（智能对齐）
        self._set(job, "dub", 0.56, "正在合成中文配音…")
        voice = opt.get("voice", config.DEFAULT_VOICE)

        def dub_progress(p: float, msg: str) -> None:
            self._check_cancel(job)
            job.progress = 0.56 + p * 0.30
            job.message = msg

        lines, parts = dubbing.align_segments(
            segments,
            voice,
            work / "dub",
            base_rate=int(opt.get("rate", 0)),
            volume=int(opt.get("volume", 0)),
            pitch=int(opt.get("pitch", 0)),
            auto_fit=bool(opt.get("auto_fit", True)),
            total_duration=total_duration,
            progress=dub_progress,
        )
        if not parts:
            raise RuntimeError("配音合成为空，请检查字幕内容是否为空")

        plan = dubbing.build_dub_plan(lines, total_duration)
        job.plan = plan
        job.logs.append(
            f"[配音] {plan['voiced_lines']}/{plan['total_lines']} 句成功 · "
            f"平均语速 {plan['avg_speed']}x · 变速 {plan['speed_adjusted_lines']} 句"
        )

        dubbed_audio = work / "dub_full.wav"
        mu.concat_audio(parts, dubbed_audio)

        # 拼接后校验：音轨长度必须和计划一致。
        # 曾经因为 MP3 与 WAV 混拼，concat 把全部静音段丢掉，
        # 42 秒的音轨只剩 32 秒，导致声音一路抢跑、字幕严重滞后。
        # 这里做一次兜底检查，出问题立刻在日志里暴露出来。
        real_len = mu.audio_duration(dubbed_audio)
        if total_duration > 0 and abs(real_len - total_duration) > 0.5:
            job.logs.append(
                f"[警告] 音轨长度异常：期望 {total_duration:.2f}s，"
                f"实际 {real_len:.2f}s（差 {real_len - total_duration:+.2f}s）"
            )
            log.warning(
                "任务 %s 音轨长度异常：期望 %.2fs 实际 %.2fs",
                job.id, total_duration, real_len,
            )
        self._check_cancel(job)
        job.logs.append(
            f"[音轨] 完整配音音轨已生成（{len(parts)} 段拼接，{real_len:.2f}s）"
        )

        # ---------- 7. 合成视频
        self._set(job, "mix", 0.88, "正在合成最终视频…")

        # 字幕时间轴**由配音的真实播放区间生成**，而不是原始时间轴。
        # 配音经过变速、借停顿之后，实际播放位置和原时间轴已经不同；
        # 字幕若还按原时间轴排，就会出现"声音先到、字幕后到"的错位。
        # 这里两者出自同一份数据，从根本上不可能对不上。
        display_segments = dubbing.build_subtitle_segments(
            lines, max_chars=config.SUB_MAX_CHARS
        )
        if len(display_segments) != len([l for l in lines if l.audio]):
            job.logs.append(
                f"[字幕] 长句切分：{len(lines)} 句 → {len(display_segments)} 条字幕"
            )

        max_drift = job.plan.get("max_drift", 0.0)
        final_drift = job.plan.get("final_drift", 0.0)
        job.logs.append(
            f"[同步] 配音与画面最大偏移 {max_drift:.2f}s，"
            f"片尾偏移 {final_drift:+.2f}s"
        )

        zh_srt = work / "zh.srt"
        zh_srt.write_text(
            asr.segments_to_srt(display_segments, use_translation=need_translate),
            encoding="utf-8",
        )
        job.logs.append(f"[字幕] 中文 SRT 已写出（{zh_srt.stat().st_size} 字节）")

        bilingual = opt.get("bilingual", False)
        if bilingual:
            zh_srt = work / "zh_bilingual.srt"
            zh_srt.write_text(
                _bilingual_srt(display_segments, need_translate), encoding="utf-8"
            )
            job.logs.append("[字幕] 已生成中英双语字幕")

        out_name = _safe_stem(job.filename)
        suffix = opt.get("output_suffix", "_中文配音")

        # 输出目录：用户可指定；不可用时回退到默认目录，不让任务因此失败
        out_dir = self._resolve_output_dir(job, opt)
        final = out_dir / _unique_path(out_dir, f"{out_name}{suffix}.mp4").name

        # ---- 背景音参数（兼容旧 keep_original_audio/original_volume）----
        bgm_mode = str(opt.get("bgm_mode", "") or "").strip()
        if not bgm_mode:
            bgm_mode = "original" if opt.get("keep_original_audio") else "off"
        if bgm_mode not in mu.BGM_MODES:
            bgm_mode = "off"
        try:
            bgm_volume = opt.get("bgm_volume")
            bgm_volume = float(bgm_volume) if bgm_volume is not None else None
        except (TypeError, ValueError):
            bgm_volume = None
        if bgm_volume is None and bgm_mode == "original":
            try:
                bgm_volume = float(opt.get("original_volume", 0.1))
            except (TypeError, ValueError):
                bgm_volume = 0.1
        bgm_ducking = bool(opt.get("bgm_ducking", True))
        # 中置消人声只对立体声有效；单声道片 pan 反相会抹掉全部声音
        if bgm_mode == "instrumental":
            try:
                src_info = mu.probe(job.source)
                if src_info.has_audio and 0 < src_info.audio_channels < 2:
                    job.logs.append(
                        "[背景音] 片源是单声道音轨，消人声会抹掉全部声音，"
                        "自动改为「保留原声」模式"
                    )
                    bgm_mode = "original"
            except mu.FFmpegError:
                pass
        if bgm_mode != "off":
            mode_txt = ("去除原片人声、保留背景乐/环境声"
                        if bgm_mode == "instrumental" else "保留原片声音")
            duck_txt = "；配音说话时自动压低背景、停顿间隙恢复" if bgm_ducking else ""
            job.logs.append(f"[背景音] {mode_txt}{duck_txt}")

        video_kwargs = dict(
            subtitle_file=zh_srt if opt.get("burn_subtitle") else None,
            burn_subtitle=bool(opt.get("burn_subtitle", True)),
            bgm_mode=bgm_mode,
            bgm_volume=bgm_volume,
            bgm_ducking=bgm_ducking,
            duration=total_duration,
        )
        try:
            mu.build_video(job.source, dubbed_audio, final, **video_kwargs)
        except mu.FFmpegError as exc:
            # 烧录字幕失败（常见原因：字体缺失 / 路径特殊字符）
            # 自动降级为不带字幕的画面，保证用户至少能拿到配音成片
            if opt.get("burn_subtitle"):
                job.logs.append(f"[字幕] 烧录失败，改为不烧录字幕重新合成：{exc}")
                zh_srt = work / "zh.srt"
                video_kwargs.update(subtitle_file=None, burn_subtitle=False)
                mu.build_video(job.source, dubbed_audio, final, **video_kwargs)
                job.logs.append("[字幕] 已改用软字幕方案（见下方独立字幕文件）")
            else:
                raise
        job.logs.append(
            f"[合成] 成片已生成：{final.name}（{final.stat().st_size / 1024 / 1024:.1f} MB）"
        )

        outputs = [{
            "kind": "video",
            "label": "中文配音成片",
            "name": final.name,
            "path": str(final),
            "size": final.stat().st_size,
        }]

        # 软字幕版本（可关闭的独立字幕轨道）
        if opt.get("soft_subtitle"):
            soft = _unique_path(out_dir, f"{final.stem}_软字幕.mp4")
            try:
                mu.mux_soft_subtitle(final, zh_srt, soft)
                outputs.append({
                    "kind": "video",
                    "label": "含可关闭中文字幕轨",
                    "name": soft.name,
                    "path": str(soft),
                    "size": soft.stat().st_size,
                })
            except Exception as exc:  # noqa: BLE001
                job.logs.append(f"[字幕] 软字幕封装失败：{exc}")

        # 导出字幕与文稿
        srt_out = _unique_path(out_dir, f"{final.stem}.srt")
        shutil.copy2(zh_srt, srt_out)
        outputs.append({
            "kind": "subtitle", "label": "中文字幕（SRT）",
            "name": srt_out.name, "path": str(srt_out),
            "size": srt_out.stat().st_size,
        })

        txt_out = _unique_path(out_dir, f"{final.stem}.txt")
        txt_out.write_text(
            asr.segments_to_plaintext(segments) + "\n", encoding="utf-8"
        )
        outputs.append({
            "kind": "text", "label": "配音文稿（TXT）",
            "name": txt_out.name, "path": str(txt_out),
            "size": txt_out.stat().st_size,
        })

        job.outputs = outputs
        job.media["output_dir"] = str(out_dir)
        job.message = f"已保存到 {out_dir}"
        job.progress = 1.0

    # ---------------------------------------------------------- 辅助
    @staticmethod
    def _resolve_output_dir(job: Job, opt: dict) -> Path:
        """确定输出目录：用户指定优先，不可用时回退默认目录。

        绝不因为目录问题让整个任务失败 —— 成片比目录重要。
        """
        raw = str(opt.get("output_dir") or "").strip()
        if raw:
            try:
                p = Path(raw).expanduser()
                p.mkdir(parents=True, exist_ok=True)
                if p.is_dir() and os.access(str(p), os.W_OK):
                    if str(p) != str(OUTPUT_DIR):
                        job.logs.append(f"[输出] 保存到指定目录：{p}")
                    return p
                job.logs.append(
                    f"[输出] 指定目录不可写（{p}），已改为默认输出目录"
                )
            except Exception as exc:  # noqa: BLE001
                job.logs.append(f"[输出] 指定目录不可用（{exc}），已改为默认输出目录")
        return OUTPUT_DIR

    def _from_embedded(
        self, job: Job, info: mu.MediaInfo, work: Path
    ) -> list[asr.Segment]:
        """把内嵌字幕提取出来并翻译。"""
        # 挑一条中文或英文字幕流
        streams = info.subtitle_streams
        if not streams:
            return []

        def score(s: dict) -> int:
            lang = (s.get("language") or "").lower()
            title = (s.get("title") or "").lower()
            if lang.startswith("zh") or "中文" in title or "chinese" in title:
                return 0
            if lang.startswith("en") or "english" in title:
                return 1
            return 2

        streams = sorted(streams, key=score)
        chosen = streams[0]
        srt_path = mu.extract_subtitle_stream(
            job.source, int(chosen["index"]), work / "embedded.srt"
        )
        segs = self._from_srt(srt_path)

        # 判断是否已经是中文
        is_zh = _mostly_chinese(segs)
        if is_zh:
            for s in segs:
                s.translated = s.text
            return segs

        opt = job.options
        return asr.translate_segments(
            segs,
            target="zh",
            provider=opt.get("translate_provider", "auto"),
            base_url=opt.get("translate_base_url", ""),
            api_key=opt.get("translate_api_key", ""),
            model=opt.get("translate_model", ""),
        )

    def _from_srt(self, path: Path) -> list[asr.Segment]:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        content = _strip_bom(text)
        if content.lstrip().upper().startswith("WEBVTT"):
            return _parse_vtt(content)
        return _parse_srt(content)

    @staticmethod
    def _check_cancel(job: Job) -> None:
        if job.cancelled:
            raise CancelledError()

    @staticmethod
    def _close_stage(job: Job, now: float) -> None:
        """结算当前阶段的耗时：写入 stage_timings，并在日志记一行（分钟）。"""
        if job._stage_started_at <= 0 or not job.stage:
            return
        dur = now - job._stage_started_at
        job.stage_timings[job.stage] = (
            job.stage_timings.get(job.stage, 0.0) + dur
        )
        job._stage_started_at = 0.0
        if dur >= 0.05:  # 瞬时阶段（如跳过的环节）不刷日志
            job.logs.append(
                f"[耗时] {job.stage_label or job.stage} 用时 {dur / 60:.1f} 分钟"
            )

    @staticmethod
    def _set(job: Job, stage: str, progress: float, message: str) -> None:
        # 阶段切换时结算上一个阶段的耗时
        JobManager._close_stage(job, time.time())
        job.stage = stage
        job.stage_label = dict(STAGES).get(stage, stage)
        job.progress = progress
        job.message = message
        job._stage_started_at = time.time()


class CancelledError(RuntimeError):
    pass


# ------------------------------------------------------------------ srt 解析
def _strip_bom(text: str) -> str:
    return text.lstrip("\ufeff")


TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _hms_to_sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0


def _parse_srt(content: str) -> list[asr.Segment]:
    segments: list[asr.Segment] = []
    blocks = re.split(r"\r?\n\r?\n+", content.strip())
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        time_line_idx = next(
            (i for i, ln in enumerate(lines) if "-->" in ln), None
        )
        if time_line_idx is None:
            continue
        m = TIME_RE.search(lines[time_line_idx])
        if not m:
            continue
        start = _hms_to_sec(*m.group(1, 2, 3, 4))
        end = _hms_to_sec(*m.group(5, 6, 7, 8))
        text = " ".join(lines[time_line_idx + 1:]).strip()
        text = re.sub(r"<[^>]+>", "", text).strip()
        if text:
            segments.append(asr.Segment(start=start, end=max(end, start + 0.2), text=text))
    return segments


def _parse_vtt(content: str) -> list[asr.Segment]:
    body = "\n".join(content.splitlines()[1:])
    return _parse_srt(body)


def _mostly_chinese(segments: list[asr.Segment]) -> bool:
    if not segments:
        return False
    sample = "".join(s.text for s in segments[:40])
    if not sample:
        return False
    zh = len(re.findall(r"[\u4e00-\u9fff]", sample))
    return zh / max(len(sample), 1) > 0.25


def _bilingual_srt(segments: list[asr.Segment], use_translation: bool) -> str:
    lines: list[str] = []
    for idx, seg in enumerate(segments, 1):
        zh = (seg.translated or "").strip() if use_translation else ""
        en = (seg.text or "").strip()
        body = "\n".join(x for x in (zh, en) if x)
        if not body:
            continue
        lines.append(str(idx))
        lines.append(
            f"{asr.fmt_ts(seg.start)} --> {asr.fmt_ts(seg.end)}"
        )
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def _safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    return (stem or "video")[:80]


def _unique_path(directory: Path, filename: str) -> Path:
    """同名的文件已存在时自动加序号，避免静默覆盖掉上一次的成果。"""
    target = directory / filename
    if not target.exists():
        return target
    stem, ext = Path(filename).stem, Path(filename).suffix
    for i in range(2, 100):
        candidate = directory / f"{stem}({i}){ext}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}_{int(time.time())}{ext}"


MANAGER = JobManager()


def cleanup_uploads(max_age_hours: int = 48) -> None:
    """清理过期的上传文件。"""
    cutoff = time.time() - max_age_hours * 3600
    for p in UPLOAD_DIR.glob("*"):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                mu.safe_unlink(p)
        except OSError:
            pass


def disk_usage() -> dict:
    def size_of(p: Path) -> int:
        total = 0
        for f in p.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                pass
        return total
    return {
        "uploads": size_of(UPLOAD_DIR),
        "work": size_of(WORK_DIR),
        "outputs": size_of(OUTPUT_DIR),
    }
