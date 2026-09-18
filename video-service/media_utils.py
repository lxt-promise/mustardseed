"""ffmpeg / ffprobe 封装：媒体信息、音频抽取、音频合成、视频混流、字幕烧录。"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from config import FFMPEG, FFPROBE, SAMPLE_RATE

log = logging.getLogger("videodub.media")


class FFmpegError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int | None = None) -> tuple[int, str, str]:
    """执行命令，返回 (returncode, stdout, stderr)。Windows 下隐藏控制台窗口。"""
    kwargs: dict = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **kwargs,
        )
    except FileNotFoundError as exc:
        raise FFmpegError(f"找不到可执行文件：{cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError("处理超时") from exc
    return proc.returncode, (proc.stdout or ""), (proc.stderr or "")


def run_ffmpeg(args: list[str], timeout: int | None = None) -> None:
    code, _, err = _run([FFMPEG, "-hide_banner", "-nostdin", "-y", *args], timeout)
    if code != 0:
        tail = "\n".join(err.strip().splitlines()[-12:])
        raise FFmpegError(f"ffmpeg 执行失败（退出码 {code}）：\n{tail}")


@dataclass
class MediaInfo:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    video_codec: str = ""
    audio_codec: str = ""
    audio_channels: int = 0
    subtitle_streams: list[dict] = field(default_factory=list)
    format_name: str = ""

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}" if self.width else "—"


def probe(path: str | Path) -> MediaInfo:
    """读取媒体文件信息。"""
    code, out, err = _run([
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    if code != 0:
        detail = (err or out or "").strip()[:300]
        raise FFmpegError(f"无法读取媒体信息：{detail}")

    data = _loads_json(out)
    if data is None:
        raise FFmpegError("媒体信息解析失败")

    info = MediaInfo()
    fmt = data.get("format", {}) or {}
    info.format_name = fmt.get("format_name", "") or ""
    try:
        info.duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        info.duration = 0.0

    for st in data.get("streams", []) or []:
        kind = st.get("codec_type")
        if kind == "video":
            # 排除封面图流
            if (st.get("disposition") or {}).get("attached_pic"):
                continue
            info.has_video = True
            info.video_codec = st.get("codec_name", "") or ""
            info.width = int(st.get("width") or 0)
            info.height = int(st.get("height") or 0)
            info.fps = _parse_fps(
                st.get("avg_frame_rate") or st.get("r_frame_rate") or "0/1"
            )
        elif kind == "audio":
            info.has_audio = True
            info.audio_codec = st.get("codec_name", "") or ""
            try:
                info.audio_channels = int(st.get("channels") or 0)
            except (TypeError, ValueError):
                info.audio_channels = 0
        elif kind == "subtitle":
            tags = st.get("tags") or {}
            info.subtitle_streams.append({
                "index": st.get("index"),
                "codec": st.get("codec_name", "") or "",
                "language": tags.get("language", "") or "",
                "title": tags.get("title", "") or "",
            })

    if info.duration <= 0:
        info.duration = _duration_fallback(path)
    return info


def _loads_json(text: str) -> dict | None:
    """从可能混有日志的输出里提取 JSON 对象。

    ffprobe 偶尔会把警告写进 stdout，直接 json.loads 会失败；
    这里退化为「取第一个 { 到最后一个 }」再解析。
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _parse_fps(value: str) -> float:
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(value)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _duration_fallback(path: str | Path) -> float:
    _, _, err = _run([FFMPEG, "-hide_banner", "-i", str(path)])
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err or "")
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mi * 60 + s
    return 0.0


# ------------------------------------------------------------ 音频抽取
def extract_audio(src: str | Path, dst: str | Path) -> Path:
    """抽取为 16k 单声道 wav，专供语音识别使用。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(src),
        "-vn",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-acodec", "pcm_s16le",
        str(dst),
    ])
    return dst


def audio_duration(path: str | Path) -> float:
    info = probe(path)
    return info.duration


# ------------------------------------------------------------ 内嵌字幕提取
def extract_subtitle_stream(src: str | Path, stream_index: int, dst: str | Path) -> Path:
    """提取内嵌字幕流为 srt。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-i", str(src), "-map", f"0:{stream_index}", "-c:s", "srt", str(dst)])
    return dst


def extract_audio_stream(src: str | Path, dst: str | Path, stream_index: int = 0) -> Path:
    """按音频流序号抽取原始音频（用于 ASR 以外的场景）。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(src), "-map", f"0:a:{stream_index}",
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-acodec", "pcm_s16le", str(dst),
    ])
    return dst


# ------------------------------------------------------------ 容错清理
def safe_unlink(path: str | Path | None) -> None:
    """删除临时文件，失败也绝不抛异常。

    为什么单独封装：清理只是收尾动作，不该影响主流程结果。
    某些环境（受管控的机器、杀软锁定、云同步目录、系统回收站策略）
    会让 unlink 失败，如果直接抛出去，整个任务会被判为失败——
    用户明明已经拿到成片了却显示报错。
    """
    if path is None:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        log.debug("清理临时文件失败（已忽略）：%s -> %s", path, exc)


def safe_rmtree(path: str | Path | None) -> None:
    """删除临时目录，失败也绝不抛异常。"""
    if path is None:
        return
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        log.debug("清理临时目录失败（已忽略）：%s -> %s", path, exc)


# ------------------------------------------------------------ 音频拼接
def concat_audio(
    parts: list[Path], dst: Path, sample_rate: int = 24000
) -> Path:
    """将多个音频片段按顺序拼成一条完整音轨。

    ⚠ 所有片段必须是**同一种编码**。
    concat 协议只会保留与首段格式一致的片段，混着传（比如 MP3 + WAV）
    会把后面的整段静默丢掉，音轨凭空短掉一大截。
    因此拼接结果会和"各段时长之和"做一次校验，不符就记警告。
    """
    if not parts:
        raise FFmpegError("没有可拼接的音频片段")
    dst.parent.mkdir(parents=True, exist_ok=True)

    expected = 0.0
    for p in parts:
        try:
            expected += probe(p).duration
        except Exception:  # noqa: BLE001
            pass

    list_file = Path(tempfile.mkstemp(suffix=".txt", dir=str(dst.parent))[1])
    try:
        # concat demuxer 要求路径转义单引号
        lines = []
        for p in parts:
            safe = str(p).replace("\\", "/").replace("'", r"'\''")
            lines.append(f"file '{safe}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")
        run_ffmpeg([
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-ar", str(sample_rate), "-ac", "1", "-acodec", "pcm_s16le",
            str(dst),
        ])
    finally:
        safe_unlink(list_file)

    try:
        got = probe(dst).duration
    except Exception:  # noqa: BLE001
        return dst
    if expected > 0 and abs(got - expected) > 0.3:
        log.warning(
            "音频拼接长度异常：各段之和 %.3fs，实际 %.3fs（差 %+.3fs）。"
            "多半是片段编码不一致被 concat 丢弃，请检查是否都转成了 WAV。",
            expected, got, got - expected,
        )
    return dst


def silence(seconds: float, dst: Path, sample_rate: int = 24000) -> Path:
    """生成一段静音。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-f", "lavfi",
        "-i", f"anullsrc=r={sample_rate}:cl=mono",
        "-t", f"{max(seconds, 0.01):.4f}",
        "-acodec", "pcm_s16le",
        str(dst),
    ])
    return dst


# ------------------------------------------------------------ 视频合成
# 背景音模式：
#   off           只要中文配音
#   original      原片整条音轨压低混入（含原声人声）
#   instrumental  中置消除去掉原片人声（pan），只留背景乐/环境声
BGM_MODES = ("off", "original", "instrumental")
# 各模式默认背景音量（占原音轨电平比例）
_BGM_DEFAULT_VOLUME = {"original": 0.10, "instrumental": 0.35}


def build_audio_filtergraph(
    mode: str,
    volume: float,
    ducking: bool,
) -> tuple[str | None, str]:
    """构造背景音混音滤镜图，返回 (filter_complex 片段, 音频 map)。

    ducking（智能闪避）：配音响起时用 sidechaincompress 自动压低背景音，
    配音停顿间隙背景音恢复，最后 alimiter 防削波。
    instrumental 用 pan 左右反相消除中置声像（人声通常居中，BGM 多在两侧）。
    """
    if mode not in ("original", "instrumental"):
        return None, "1:a"

    vol = max(0.0, min(1.0, float(volume)))
    pre = "pan=stereo|c0=c0-c1|c1=c1-c0," if mode == "instrumental" else ""

    if ducking:
        chain = (
            f"[0:a]{pre}volume={vol:.3f},aformat=channel_layouts=stereo[bgm];"
            "[1:a]volume=1.0,aformat=channel_layouts=stereo,asplit=2[dubmain][sc];"
            "[bgm][sc]sidechaincompress=threshold=0.025:ratio=8:attack=25:release=350[ducked];"
            "[ducked][dubmain]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            "alimiter=limit=0.95[aout]"
        )
    else:
        chain = (
            f"[0:a]{pre}volume={vol:.3f},aformat=channel_layouts=stereo[bgm];"
            "[1:a]volume=1.0,aformat=channel_layouts=stereo[dub];"
            "[bgm][dub]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
    return chain, "[aout]"


def build_video(
    video_src: str | Path,
    audio_src: str | Path,
    dst: str | Path,
    *,
    subtitle_file: str | Path | None = None,
    burn_subtitle: bool = False,
    keep_original_audio: bool = False,
    original_volume: float = 0.08,
    bgm_mode: str = "off",
    bgm_volume: float | None = None,
    bgm_ducking: bool = True,
    duration: float | None = None,
) -> Path:
    """将原视频画面 + 中文配音合成为最终视频。

    - burn_subtitle=True 时，用 subtitles 滤镜把中文字幕烧进画面。
    - bgm_mode：off 只要配音；original 原声压低当背景（兼容旧
      keep_original_audio）；instrumental 中置消除去掉原片英文人声、
      只保留背景乐/环境声。
    - bgm_ducking=True 时配音说话自动压低背景音（智能闪避）。
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = ["-i", str(video_src), "-i", str(audio_src)]

    # 兼容旧参数 keep_original_audio / original_volume
    if bgm_mode not in BGM_MODES:
        bgm_mode = "off"
    if bgm_mode == "off" and keep_original_audio:
        bgm_mode = "original"
    if bgm_volume is None:
        bgm_volume = original_volume if keep_original_audio else _BGM_DEFAULT_VOLUME.get(bgm_mode, 0.2)

    filters: list[str] = []
    vlabel = "0:v"
    if burn_subtitle and subtitle_file:
        sub_path = _escape_subtitle_path(subtitle_file)
        filters.append(f"[0:v]subtitles='{sub_path}'[vsub]")
        vlabel = "vsub"

    audio_chain, amap = build_audio_filtergraph(bgm_mode, bgm_volume, bgm_ducking)
    if audio_chain:
        filters.append(audio_chain)

    args: list[str] = [*inputs]
    if filters:
        args += ["-filter_complex", ";".join(filters)]
    args += ["-map", f"[{vlabel}]" if vlabel != "0:v" else "0:v"]
    args += ["-map", amap]
    args += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
    ]
    if duration and duration > 0:
        args += ["-t", f"{duration:.3f}"]
    args += [str(dst)]
    run_ffmpeg(args)
    return dst


def _escape_subtitle_path(path: str | Path) -> str:
    """subtitles 滤镜里 Windows 路径需要转义。"""
    p = str(Path(path).resolve()).replace("\\", "/")
    p = p.replace(":", r"\:")
    return p


def mux_soft_subtitle(
    video_src: str | Path,
    subtitle_file: str | Path,
    dst: str | Path,
) -> Path:
    """将中文字幕作为软字幕轨道封装进 mp4（可关闭）。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(video_src), "-i", str(subtitle_file),
        "-map", "0", "-map", "1:0",
        "-c", "copy",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=chi",
        "-metadata:s:s:0", "title=中文字幕",
        str(dst),
    ])
    return dst


def make_thumbnail(src: str | Path, dst: str | Path, at: float = 1.0) -> Path:
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-ss", f"{max(at, 0):.3f}", "-i", str(src),
        "-frames:v", "1", "-vf", "scale=640:-2",
        str(dst),
    ])
    return dst


def normalize_for_web(src: str | Path, dst: str | Path) -> Path:
    """把任意输入视频转成浏览器可播放的 mp4（预览用）。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst),
    ])
    return dst


def ffmpeg_version() -> str:
    code, out, err = _run([FFMPEG, "-version"])
    if code != 0:
        return "未安装"
    first = (out or err or "").strip().splitlines()
    return first[0] if first else "未知"
