"""端到端验证：生成英文测试视频 → 走完整流水线 → 检查产物。"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config
import jobs as jobs_mod
import media_utils as mu

FF = config.FFMPEG
TEST_DIR = config.TMP_DIR / "selftest"

EN_SENTENCES = [
    "Hello everyone, welcome to this short demonstration video.",
    "Today we are going to test the automatic dubbing system.",
    "This tool can translate English speech into Chinese.",
    "It will also generate Chinese subtitles for the video.",
    "The whole process runs locally on your own computer.",
    "Thank you for watching, and have a wonderful day.",
]


def step(msg: str) -> None:
    print(f"\n{'=' * 62}\n  {msg}\n{'=' * 62}", flush=True)


def make_test_video() -> Path:
    """用 ffmpeg 合成一段英文语音测试视频（espeak 不可用时退化为静音+字幕）。"""
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    video = TEST_DIR / "test_en.mp4"

    # 先试试能否用 Windows 自带的语音合成生成英文音频
    wav = _try_make_speech_wav()

    dur = 0.0
    if wav and wav.exists():
        dur = mu.probe(wav).duration
        print(f"  已生成英文语音，时长 {dur:.1f}s")
    else:
        dur = 18.0
        print("  未能生成语音，改用静音音轨（仅验证流程）")

    # 生成 1280x720 测试画面 + 音频
    # 注意：lavfi 的 color 源默认无限长，必须用 -t 明确指定时长，
    # 不能用 -shortest（否则可能产出零长或空流）。
    args = [
        "-f", "lavfi", "-i", f"color=c=0x1e3a5f:s=1280x720:r=25:d={dur:.2f}",
    ]
    if wav and wav.exists():
        args += ["-i", str(wav)]
    else:
        args += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={dur:.2f}"]

    args += [
        "-t", f"{dur:.2f}",
        "-vf", (
            "drawtext=text='English Test Video':fontcolor=white:fontsize=64:"
            "x=(w-text_w)/2:y=(h-text_h)/2-40,"
            "drawtext=text='Video Dubbing Demo':fontcolor=0x9ecbff:fontsize=32:"
            "x=(w-text_w)/2:y=(h-text_h)/2+50"
        ),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart",
        str(video),
    ]
    try:
        mu.run_ffmpeg(args)
        print(f"  测试视频已生成：{video}")
        return video
    except Exception as exc:  # noqa: BLE001
        print(f"  drawtext 失败（可能缺字体），改用纯色画面：{exc}")
        args2 = [
            "-f", "lavfi", "-i", f"color=c=0x1e3a5f:s=1280x720:r=25:d={dur:.2f}",
        ]
        if wav and wav.exists():
            args2 += ["-i", str(wav)]
        else:
            args2 += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={dur:.2f}"]
        args2 += [
            "-t", f"{dur:.2f}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(video),
        ]
        mu.run_ffmpeg(args2)
        print(f"  测试视频已生成（无文字）：{video}")
        return video


def _try_make_speech_wav() -> Path | None:
    """尝试用 Windows SAPI 生成英文语音。"""
    wav = TEST_DIR / "en_speech.wav"
    if wav.exists():
        return wav

    text = " ".join(EN_SENTENCES)
    ps = f"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = 0
$s.SetOutputToWaveFile('{wav}')
$s.Speak('{text}')
$s.Dispose()
"""
    script = TEST_DIR / "speak.ps1"
    script.write_text(ps, encoding="utf-8")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, timeout=120,
        )
        if wav.exists() and wav.stat().st_size > 1000:
            return wav
        print(f"  SAPI 合成未产出文件：{(r.stderr or '')[:200]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  SAPI 合成失败：{exc}")
    return None


def run_pipeline(video: Path, engine: str, model: str, voice: str) -> dict:
    """直接调用 JobManager 跑完整流水线。"""
    options = {
        "engine": engine,
        "whisper_model": model,
        "source_language": "en",
        "voice": voice,
        "rate": 0,
        "volume": 0,
        "pitch": 0,
        "translate_to_zh": True,
        "auto_fit": True,
        "burn_subtitle": True,
        "soft_subtitle": False,
        "bilingual": False,
        "keep_original_audio": False,
        "use_embedded_subtitle": False,
        "output_suffix": "_selftest",
    }
    # 用与 Web 接口相同的规整逻辑，保证测试路径与真实路径一致
    import app as appmod
    options = appmod._normalize_options(options)

    mgr = jobs_mod.MANAGER
    job = mgr.create(video.name, video, options)

    print(f"\n  任务 ID: {job.id}")
    mgr.start(job)

    last = None
    t0 = time.time()
    while job.status in ("pending", "running"):
        line = f"  [{job.progress * 100:5.1f}%] {job.stage_label}: {job.message}"
        if line != last:
            print(line, flush=True)
            last = line
        if time.time() - t0 > 1800:
            print("  [超时] 中断")
            job.cancelled = True
            break
        time.sleep(0.8)

    print(f"\n  状态: {job.status}")
    if job.error:
        print(f"  错误: {job.error}")
    print(f"  耗时: {job.finished_at - job.created_at:.1f}s")
    for lg in job.logs:
        print(f"    {lg}")

    return {
        "status": job.status,
        "error": job.error,
        "media": job.media,
        "plan": job.plan,
        "outputs": job.outputs,
        "segments": job.segments,
    }


def verify_outputs(result: dict) -> bool:
    """检查产物是否真实可用。"""
    step("校验产物")
    ok = True

    if result["status"] != "done":
        print(f"  ✗ 流水线未成功：{result['error']}")
        return False

    segs = result.get("segments") or []
    print(f"  字幕句数: {len(segs)}")
    if segs:
        for s in segs[:3]:
            print(f"    [{s['start']:.1f}-{s['end']:.1f}] "
                  f"{s['translated'] or '(空)'}  ← {s['text'][:50]}")
    zh_count = sum(1 for s in segs if any('\u4e00' <= c <= '\u9fff' for c in (s.get('translated') or '')))
    print(f"  含中文的句数: {zh_count}/{len(segs)}")
    if segs and zh_count == 0:
        print("  ! 没有任何中文译文（未配置翻译 API 时属预期）")

    for o in result["outputs"]:
        p = Path(o["path"])
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        flag = "✓" if exists and size > 0 else "✗"
        if not (exists and size > 0):
            ok = False
        print(f"  {flag} {o['label']}: {o['name']} ({size / 1024:.0f} KB)")

        if o["kind"] == "video" and exists:
            try:
                info = mu.probe(p)
                print(f"      → {info.resolution} · {info.duration:.1f}s · "
                      f"视频流 {info.video_codec} · 音频流 {info.audio_codec}")
                if not info.has_audio:
                    print("      ✗ 成品没有音轨！")
                    ok = False
                if info.duration < 1:
                    print("      ✗ 成品时长异常")
                    ok = False
            except Exception as exc:  # noqa: BLE001
                print(f"      ✗ 无法解析成品：{exc}")
                ok = False

    return ok


def main() -> int:
    step("视频翻译配音工作台 —— 端到端自检")

    step("环境检查")
    print(f"  ffmpeg: {mu.ffmpeg_version()}")
    print(f"  ffmpeg 路径: {config.FFMPEG}")
    print(f"  项目目录: {config.BASE_DIR}")
    try:
        import edge_tts
        print("  edge-tts: 可用")
    except ImportError:
        print("  edge-tts: 缺失")
        return 1
    try:
        import faster_whisper
        print("  faster-whisper: 可用")
    except ImportError:
        print("  faster-whisper: 缺失")

    step("生成英文测试视频")
    video = make_test_video()
    info = mu.probe(video)
    print(f"  {info.resolution} · {info.duration:.1f}s · 音频={info.has_audio}")

    # 用最小模型快速验证
    model = sys.argv[1] if len(sys.argv) > 1 else "tiny"
    voice = sys.argv[2] if len(sys.argv) > 2 else "zh-CN-XiaoxiaoNeural"

    step(f"跑完整流水线（模型={model}，音色={voice}）")
    result = run_pipeline(video, "local", model, voice)

    success = verify_outputs(result)

    step("TTS 单独验证")
    try:
        import dubbing
        out = config.TMP_DIR / "tts_check.mp3"
        dubbing.synthesize("这是一句中文配音测试。", voice, out)
        d = mu.probe(out).duration
        print(f"  ✓ edge-tts 合成成功，时长 {d:.2f}s，大小 {out.stat().st_size} B")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ edge-tts 失败：{exc}")
        success = False

    step("时间轴对齐验证")
    try:
        from asr import Segment
        segs = [
            Segment(0.0, 2.0, "Hello world", "你好，世界"),
            Segment(2.0, 3.5, "This is a much longer sentence that will not fit", "这是一个长得多的句子，肯定塞不进原本那么短的时间槽里去"),
            Segment(3.5, 5.0, "Short one", "很短"),
        ]
        lines, parts = dubbing.align_segments(
            segs, voice, config.TMP_DIR / "align_check",
            auto_fit=True, total_duration=5.0,
        )
        for ln in lines:
            print(f"  句{ln.index}: 槽 [{ln.slot_start:.2f}-{ln.slot_end:.2f}] "
                  f"语音 {ln.speech_duration:.2f}s 语速 {ln.speed:.2f}x "
                  f"{'溢出' if ln.overflowed else ''}")
        plan = dubbing.build_dub_plan(lines, 5.0)
        print(f"  统计: {json.dumps(plan, ensure_ascii=False)}")
        print(f"  ✓ 对齐模块正常，生成 {len(parts)} 个音片段")
    except Exception as exc:  # noqa: BLE001
        import traceback
        print(f"  ✗ 对齐失败：{exc}\n{traceback.format_exc()}")
        success = False

    step("字幕解析验证")
    try:
        srt = TEST_DIR / "sample.srt"
        srt.write_text(
            "1\n00:00:01,000 --> 00:00:03,500\nHello there.\n\n"
            "2\n00:00:03,500 --> 00:00:06,000\nThis is line two.\n",
            encoding="utf-8",
        )
        parsed = jobs_mod.MANAGER._from_srt(srt)  # noqa: SLF001
        print(f"  ✓ 解析出 {len(parsed)} 条")
        for p in parsed:
            print(f"    {p.start:.2f}-{p.end:.2f} {p.text}")
        assert len(parsed) == 2, "解析条数不符"
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ 字幕解析失败：{exc}")
        success = False

    print("\n" + "=" * 62)
    print("  自检结果：" + ("全部通过 ✓" if success else "存在问题 ✗"))
    print("=" * 62)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
