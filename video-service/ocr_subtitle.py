"""硬字幕 OCR：从烧录在画面里的字幕提取带时间轴的字幕段。

两级闸门链路（参考 video-subtitle-extractor 等项目的关键帧思路）：
  1. ffmpeg 按 fps 定点抽取画面底部字幕区；
  2. 每帧只跑「低分辨率文本检测网络」(480 宽，约 11ms/帧)，
     得到文字行框；框布局与上一帧几乎一致 → 同一条字幕静止中，
     直接复用上一个关键帧的识别结果（实测可跳过约 3/4 的完整 OCR）；
  3. 仅对关键帧（字幕出现/切换）跑完整检测+识别（检测边限 1280、
     关闭方向分类），约 280ms/帧；
  4. 帧级清洗 → 时间线状态机归并。

相对「逐帧完整 OCR」整体提速约 8-10 倍，且框布局变化判异在真实
片源上零误判（不同字幕的行布局必然不同，漏判只会发生在快速掠过的
场景文字上）。

提取结果复用 asr.Segment，可直接进入后续的翻译/配音流程；
语言由调用方按内容自动检测（中文为主 → 跳过翻译）。

时间轴即字幕在画面上的真实显示区间，下游 dubbing.align_segments
以 seg.start 作为配音放置锚点，因此这里必须保证：
  1. 一条字幕只产出一段（帧间 OCR 抖动不能切碎，否则同句重复配音、
     碎片各自变速导致音画不同步）；
  2. start/end 紧贴字幕出现/消失时刻。
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from media_utils import run_ffmpeg

log = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]

# 采样参数：底部 40% 画面 + 每秒 2 帧，10 分钟视频约 1200 帧。
# 每帧先跑 11ms 的低分辨率检测闸门，只有约 1/4 的字幕切换关键帧
# 需要 ~280ms 的完整 OCR，整体约为视频时长的 1/10，进度条有实时反馈
CROP_BOTTOM_RATIO = 0.40
SAMPLE_FPS = 2.0

# 两级闸门参数（实测值，改动前请先用真实片源基准回归）：
# - 闸门检测把条带缩到 480 宽：真实字幕近乎零漏检（漏检也多为孤立
#   一帧，两侧有字时由闸门级桥接补回），速度约 11ms/帧；
# - 完整 OCR 检测边限 1280(max)：避免默认配置把 720p 条带放大到
#   3271 宽送检测网络，单帧 770ms→217ms 且识别质量不变；
# - 关键帧判异双通道：文字行框布局网格异或比 > 0.15，或框内笔画
#   签名异或比 > 0.18（双语片源英文行长时间不动、中文行原位替换时
#   布局变化不足，笔画通道兜底；实测两通道均触发也只对约 4 成帧做
#   完整 OCR，且无错误复用）。
GATE_DET_WIDTH = 480
FULL_DET_MAX_SIDE = 1280
BOX_GRID_W = 240
BOX_GRID_H = 48
LAYOUT_JACCARD = 0.15
STROKE_JACCARD = 0.18
STROKE_LOCAL = 31       # 笔画签名局部背景窗口（480 宽缩图上的像素）
STROKE_DIFF = 16
# 闸门孤立漏检桥接：空帧前后各 GATE_BRIDGE 帧内都有文字 → 视为漏检，
# 继承前一关键帧文本（与时间线 GAP_BRIDGE_SEC 同量级）
GATE_BRIDGE_FRAMES = 2

# ---------- 清洗 / 归并阈值（集中管理，禁止在分支里散落魔数） ----------
ROW_SCORE_MIN = 0.35      # 单行 OCR 置信度低于此值丢弃
EDGE_X_RATIO = 0.10      # 行中心贴左右边（台标/角标）且文本很短时丢弃
EDGE_SHORT_CHARS = 4
MIN_NOISE_CHARS = 4       # 只出现 1 个采样帧且字数少于此值 → 视为 OCR 噪声
SIM_SAME = 0.80           # 相邻帧文本相似度 ≥ 此值 → 同一条字幕
SIM_MERGE = 0.88          # 相邻候选段相似度 ≥ 此值 → 合并碎片
GAP_BRIDGE_SEC = 1.2      # 空帧桥接宽限：OCR 短暂失灵不算字幕消失
MERGE_GAP_SEC = 1.5       # 相邻候选段间隔 ≤ 此值才允许相似合并
# 常驻文本（台标/水印）判定：同一行文本在极高比例关键帧中反复出现
WATERMARK_RATIO = 0.60
WATERMARK_ALMOST_ALL = 0.90
WATERMARK_MIN_CHARS = 4
WATERMARK_MIN_KEYFRAMES = 20  # 关键帧太少不做统计，避免误杀长字幕
# 中文为主片源判定：有文字的关键帧中含中文行的比例 ≥ 1/2，且至少
# 3 个中文关键帧。双语片（中文配音+中英硬字幕）里纯英文帧是同句台词
# 的外文伴字幕，不能成独立段（否则中文 TTS 念英文、且重复占时长）；
# 纯英文片则全部保留，交后续翻译成中文
CJK_DOMINANT_RATIO = 0.5
CJK_DOMINANT_MIN_KEYFRAMES = 3

_OCR = None


def _get_ocr():
    """惰性加载 RapidOCR（首次约 0.5s），统一提速参数。

    注意 rapidocr_onnxruntime 1.2.x 的参数坑：
    - 传任何 det_* 参数都必须同时传 det_model_path=None，
      否则内部 UpdateParameters 抛 KeyError；
    - 参数为扁平命名（use_angle_cls 而非 det.use_angle_cls）。
    """
    global _OCR
    if _OCR is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "未安装 OCR 组件（rapidocr_onnxruntime），"
                "请在 video-service 目录执行："
                "python\\python.exe -m pip install rapidocr_onnxruntime"
            ) from exc
        _OCR = RapidOCR(
            use_angle_cls=False,
            det_model_path=None,
            det_limit_type="max",
            det_limit_side_len=FULL_DET_MAX_SIDE,
        )
    return _OCR


# ================================================================ 文本工具
# 比较键：去掉全部空白与标点、转小写。OCR 帧间最常见的抖动就是
# 标点/空格差异，归一化后大部分误切直接消失。
_PUNCT_RE = re.compile(
    r"[\s，。！？、；：「」『』“”‘’（）《》〈〉【】…—·～~〡\|"
    r"\.,!\?;:\(\)\[\]\{\}\"'\-_`@#\$%\^&\*\+=<>/\\]+"
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    """归一化为比较键：无空白、无标点、小写。"""
    return _PUNCT_RE.sub("", s).lower()


def _display(s: str) -> str:
    """展示文本：压缩空白、去首尾。"""
    return _WS_RE.sub(" ", s).strip()


def _cjk_ratio(s: str) -> float:
    """中文字符占「中文+拉丁字母」的比例（纯标点/数字不计入分母）。"""
    cjk = len(_CJK_RE.findall(s))
    letters = len(re.findall(r"[A-Za-z]", s))
    total = cjk + letters
    return cjk / total if total else 0.0


def _similar(a: str, b: str, threshold: float) -> bool:
    """两个归一化键是否表达同一行文本。

    短串（<4 字）不使用 SequenceMatcher：两个字的串相似度容易虚高
    （如「你好」「你們」ratio=0.5 尚可，但「走吧」「好吗」也可能撞分），
    短串只认真正的包含/相等；长串才上模糊比率。
    单字串只认「前缀增长」：打字机式逐字显示首帧只有一个字，
    但任意位置包含会让角落单字噪声误并入后续句子。
    """
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) == 1 and long_.startswith(short):
        return True
    if len(short) >= 2 and short in long_:
        # 逐字显示补全 / 其中一帧只认出半行
        return True
    if len(short) >= 4 and SequenceMatcher(None, a, b).ratio() >= threshold:
        return True
    return False


# ================================================================ 数据结构
@dataclass
class _Row:
    """一帧里的一行 OCR 结果。"""
    text: str           # 原始展示文本
    key: str            # 归一化比较键
    score: float
    cx: float           # 行中心 x 占帧宽比例
    cy: float           # 行中心 y 占帧高比例


@dataclass
class _Draft:
    """归并中的一条候选字幕段。"""
    start: float
    end: float
    text: str
    key: str
    miss: int = 0       # 连续未匹配到的帧数（桥接宽限用）


# ================================================================ 帧级处理
def _gate_scan(ocr, img) -> tuple:
    """低分辨率文本检测闸门：返回 (框布局网格, 框内笔画签名)。

    只调用检测网络（跳过识别），把条带缩到 GATE_DET_WIDTH 宽后推理，
    实测约 11ms/帧（完整 OCR 约 280ms）。
    - 框网格：检测框坐标归一化后填入 BOX_GRID_W×BOX_GRID_H；
    - 笔画签名：在缩图上取局部对比像素（亮/暗于周围背景 = 字的填充
      或描边），同样栅格化并限定在框区域内。背景运动在框外不参与，
      文字静止时签名稳定，文字内容替换时签名显著变化。
    无文字时返回 (None, None)。
    """
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    sw = GATE_DET_WIDTH
    sh = max(1, int(h * sw / w))
    small = cv2.resize(img, (sw, sh))
    boxes, _ = ocr.text_detector(small)
    if boxes is None or len(boxes) == 0:
        return None, None
    grid = np.zeros((BOX_GRID_H, BOX_GRID_W), dtype=np.uint8)
    for box in boxes:
        x0 = int(box[:, 0].min() / sw * BOX_GRID_W)
        x1 = max(x0 + 1, int(box[:, 0].max() / sw * BOX_GRID_W))
        y0 = int(box[:, 1].min() / sh * BOX_GRID_H)
        y1 = max(y0 + 1, int(box[:, 1].max() / sh * BOX_GRID_H))
        grid[max(0, y0):min(BOX_GRID_H, y1),
             max(0, x0):min(BOX_GRID_W, x1)] = 1
    if not grid.any():
        return None, None

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    local = cv2.boxFilter(gray, cv2.CV_8U, (STROKE_LOCAL, STROKE_LOCAL))
    strokes = (cv2.absdiff(gray, local) > STROKE_DIFF).astype(np.uint8)
    sig = cv2.resize(strokes, (BOX_GRID_W, BOX_GRID_H),
                     interpolation=cv2.INTER_NEAREST) & grid
    return grid, sig


def _is_keyframe(prev_grid, prev_sig, grid, sig) -> bool:
    """相对上一文字帧，本帧是否为字幕切换关键帧（布局/笔画任一超阈）。

    布局通道对「新增/消失一行」敏感；笔画通道对「原位换字」敏感
    （双语片源中文行替换、英文行不动时布局变化很小）。
    """
    import numpy as np

    union = np.logical_or(prev_grid, grid).sum()
    if union == 0:
        return True
    if np.logical_xor(prev_grid, grid).sum() / union > LAYOUT_JACCARD:
        return True
    s_union = np.logical_or(prev_sig, sig).sum()
    if s_union == 0:
        return False
    return np.logical_xor(prev_sig, sig).sum() / s_union > STROKE_JACCARD


def _parse_rows(raw: list, fw: int, fh: int) -> list[_Row]:
    """把 RapidOCR 原始输出解析成行对象，并做行级过滤。

    raw: [[box(4 点), text, score], ...]
    """
    if not raw:
        return []
    rows: list[_Row] = []
    for item in raw:
        if not item or len(item) < 3:
            continue
        box, text, score = item[0], str(item[1]).strip(), float(item[2] or 0.0)
        key = _norm(text)
        if not text or not key:
            continue
        if score < ROW_SCORE_MIN:
            continue
        cx = cy = 0.5
        try:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            if fw > 0:
                cx = (min(xs) + max(xs)) / 2 / fw
            if fh > 0:
                cy = (min(ys) + max(ys)) / 2 / fh
        except Exception:  # noqa: BLE001
            pass
        # 角落短文本：台标/角标/台徽，正常字幕不会贴边又只有几个字
        if (len(key) <= EDGE_SHORT_CHARS
                and (cx <= EDGE_X_RATIO or cx >= 1 - EDGE_X_RATIO)):
            continue
        rows.append(_Row(text=text, key=key, score=score, cx=cx, cy=cy))
    # 版面顺序兜底：按纵向位置排序（两行字幕上→下拼接）
    rows.sort(key=lambda r: r.cy)
    return rows


def _detect_watermarks(frames_rows: list[list[_Row]], total_frames: int) -> set[str]:
    """检测常驻叠加文本（台标/水印/固定角标）。

    只喂关键帧（每条新字幕一帧）：水印行会出现在绝大多数关键帧中，
    正常字幕每条文本不同。total_frames 即关键帧数。
    """
    if total_frames < WATERMARK_MIN_KEYFRAMES:
        return set()  # 片段太短不做统计，避免误杀长字幕
    hit: dict[str, int] = {}
    for rows in frames_rows:
        for r in rows:
            if len(r.key) >= WATERMARK_MIN_CHARS:
                hit[r.key] = hit.get(r.key, 0) + 1
    bad = set()
    for key, cnt in hit.items():
        ratio = cnt / total_frames
        if ratio >= WATERMARK_ALMOST_ALL or ratio >= WATERMARK_RATIO:
            bad.add(key)
    if bad:
        log.info("[OCR] 检测到常驻文本 %d 个，按水印剔除：%s",
                 len(bad), "、".join(list(bad)[:5]))
    return bad


# 拉丁词前后紧贴的标点/空白（随单词一起删，避免 "Hi," 删词后留个光杆逗号）
_PUNCT_BEFORE = r"\s，。！？、；：,.!?;:（【「"
_PUNCT_AFTER = r"\s，。！？、；：,.!?;:）】」…"
_LATIN_WITH_PUNCT_RE = re.compile(
    rf"[{_PUNCT_BEFORE}]*[A-Za-z][A-Za-z'\-]*[{_PUNCT_AFTER}]*"
)


def strip_latin_words(text: str) -> str:
    """中文配音稿里剔除夹混的独立外文单词（Hi/OK/wow 等），保留中文与数字。

    只对含中文的文本生效（纯英文片的文本交给翻译环节，不动）。
    单词连同紧贴的标点一起删："Hi,打扰一下" → "打扰一下"；
    正常中文句末句号不受影响。
    """
    if not text or not _CJK_RE.search(text):
        return text
    return _LATIN_WITH_PUNCT_RE.sub("", text).strip()


def _compose_frame(rows: list[_Row], watermarks: set[str]) -> tuple[str, str]:
    """一帧内的多行 → 一句展示文本 + 比较键。

    双语字幕（中文一行、英文一行）时只保留中文行：OCR 链路的产物
    会直接送中文 TTS，夹带英文会被读成混杂发音。
    纯英文字幕则保留英文行，交给后续翻译环节。
    中文折行直接相连（原文本就是一句话），英文折行补空格。
    """
    kept = [r for r in rows if r.key not in watermarks]
    if not kept:
        return "", ""
    cjk_rows = [r for r in kept if _cjk_ratio(r.text) >= 0.3]
    chosen = cjk_rows if cjk_rows else kept
    if cjk_rows:
        text = "".join(_display(r.text) for r in chosen)
    else:
        text = " ".join(_display(r.text) for r in chosen)
    text = _display(text)
    return text, _norm(text)


def _detect_cjk_dominant(key_rows: list[list[_Row]]) -> bool:
    """整片是否为「中文为主」（中文配音+中英双语硬字幕的片源）。

    以有文字的关键帧为分母（same 帧只是关键帧的延续，不计入），
    含中文行的关键帧占比过半且不少于 CJK_DOMINANT_MIN_KEYFRAMES。
    纯英文片/只闪过一两个中文字的英文片都不会误判。
    """
    text_kf = sum(1 for rows in key_rows if rows)
    if text_kf < CJK_DOMINANT_MIN_KEYFRAMES:
        return False
    cjk_kf = sum(
        1 for rows in key_rows
        if rows and any(_cjk_ratio(r.text) >= 0.3 for r in rows)
    )
    return cjk_kf / text_kf >= CJK_DOMINANT_RATIO


def _build_stream(
    records: list[tuple[str, list[_Row] | None]],
    watermarks: set[str],
    fps: float,
    cjk_dominant: bool,
) -> tuple[list[tuple[float, float, str, str]], int]:
    """扫描记录 → 帧文本流 (ts0, ts1, text, key)，供时间线状态机消费。

    - blank：闸门没检出文字。若前后 GATE_BRIDGE_FRAMES 内都有文字，
      视为低分辨率检测的孤立漏检，继承上一关键帧文本；
    - key：完整 OCR 过的关键帧；
    - same：布局/笔画未变，继承最近关键帧文本。

    中文为主片源里，纯外文（无 CJK）关键帧是同句台词的外文伴字幕
    （中文行在相邻采样帧尚未出现/已经消失），按空帧处理：短时间由
    GAP_BRIDGE_SEC 桥进相邻中文段，不会产出独立英文段——否则中文
    TTS 会直接念英文，且与相邻中文内容重复、多占配音时长导致音画
    落后。返回 (stream, 被丢弃的纯外文关键帧数)。
    """
    total = len(records)
    stream: list[tuple[float, float, str, str]] = []
    last_text = last_key = ""
    dropped = 0
    for i, (kind, rows) in enumerate(records):
        if kind == "blank":
            lo = max(0, i - GATE_BRIDGE_FRAMES)
            hi = min(total, i + GATE_BRIDGE_FRAMES + 1)
            left = any(records[j][0] != "blank" for j in range(lo, i))
            right = any(records[j][0] != "blank" for j in range(i + 1, hi))
            if left and right and last_key:
                text, key = last_text, last_key
            else:
                text = key = ""
                last_text = last_key = ""
        elif kind == "key":
            text, key = _compose_frame(rows, watermarks)
            if cjk_dominant and text:
                if not _CJK_RE.search(text):
                    # 中文为主片源的纯外文伴字幕帧：丢弃，后续 same 帧一并置空
                    text = key = ""
                    dropped += 1
                    last_text = last_key = ""
                else:
                    # 中文行里夹混的外文词（Hi/OK 等）也要抠掉，否则 TTS 蹦英文
                    text = strip_latin_words(text)
                    key = _norm(text)
                    last_text, last_key = text, key
            else:
                last_text, last_key = text, key
        else:  # same：字幕静止，复用关键帧结果
            text, key = last_text, last_key
        stream.append((i / fps, (i + 1) / fps, text, key))
    return stream, dropped


# ================================================================ 时间线归并
def _upgrade_text(cur: _Draft, text: str, key: str) -> None:
    """同一条字幕出现更完整的识别结果时升级展示文本。

    - 新结果包含当前键：逐字显示补全 → 用新文本；
    - 当前键包含新键：这一帧丢字 → 保留更完整的旧文本；
    - 高相似但互不包含（个别字识别差异）：取较长者，等长不抖动。
    """
    if cur.key in key and len(key) > len(cur.key):
        cur.text, cur.key = text, key
    elif key in cur.key:
        return
    elif len(key) > len(cur.key):
        cur.text, cur.key = text, key


def _group_timeline(
    stream: list[tuple[float, float, str, str]],
    fps: float,
) -> list[_Draft]:
    """逐帧状态机：把帧文本流归并成候选字幕段。

    关键策略：
    - 相邻帧文本「相同/包含/高相似」→ 同段延续；
    - 空帧进入桥接宽限（GAP_BRIDGE_SEC 内又出现相似文本则延续，
      end 跨过 OCR 失灵的间隙——字幕实际仍在画面上）；
    - 宽限期满才算字幕真正消失；出现明显不同的新文本则立即切换。
    """
    drafts: list[_Draft] = []
    cur: _Draft | None = None
    max_miss = max(1, int(round(GAP_BRIDGE_SEC * fps)))

    for ts0, ts1, text, key in stream:
        if not key:
            if cur is not None:
                cur.miss += 1
                if cur.miss > max_miss:
                    drafts.append(cur)
                    cur = None
            continue

        if cur is not None and _similar(cur.key, key, SIM_SAME):
            cur.miss = 0
            cur.end = ts1
            _upgrade_text(cur, text, key)
        else:
            # 与当前段不同（或当前段已不存在）→ 结算旧段、开新段
            if cur is not None:
                drafts.append(cur)
            cur = _Draft(start=ts0, end=ts1, text=text, key=key)

    if cur is not None:
        drafts.append(cur)
    return drafts


def _finalize(drafts: list[_Draft], fps: float = SAMPLE_FPS) -> list:
    """段级清理：去短噪声、合并残余碎片、时间轴收口。"""
    from asr import Segment  # 延迟导入避免环

    one_frame = 1.0 / fps + 1e-6
    segs: list[Segment] = []
    for d in drafts:
        # 只闪了 1 个采样帧、又没几个字的才是噪声；
        # 跨多帧的短台词（「走吧」「你好」）与单帧长字幕（标题卡）都保留
        if (d.end - d.start) <= one_frame and len(d.key) < MIN_NOISE_CHARS:
            continue
        if segs and (d.start - segs[-1].end) <= MERGE_GAP_SEC:
            prev_key = _norm(segs[-1].text)
            if _similar(prev_key, d.key, SIM_MERGE):
                # 被空窗/抖动切开的同一条字幕：时间轴取并集，文本取更完整者
                segs[-1].end = max(segs[-1].end, d.end)
                if len(d.key) > len(prev_key):
                    segs[-1].text = d.text
                continue
        segs.append(Segment(d.start, d.end, d.text))

    # 防御性收口：按时间排序、消除重叠（正常不会出现，纯保险）
    segs.sort(key=lambda s: s.start)
    for a, b in zip(segs, segs[1:]):
        if b.start < a.end:
            a.end = b.start
    log.info("[OCR] 时间线归并完成，输出 %d 句字幕", len(segs))
    return segs


# ================================================================ 主入口
def extract_hard_subtitles(
    video: Path,
    work_dir: Path,
    progress: ProgressFn | None = None,
    *,
    fps: float = SAMPLE_FPS,
    duration_hint: float = 0.0,
) -> list:
    """提取画面硬字幕，返回 asr.Segment 列表（translated 留空）。

    progress(p, msg)：p∈[0,1] 为整体进度，msg 为进度描述。
    提取不到任何文字时返回空列表（调用方决定报错或回退）。
    """
    ocr = _get_ocr()

    # ---------- 1. 抽帧：裁剪底部字幕区，jpeg 质量够 OCR 用且省磁盘
    frames_dir = work_dir / "ocr_frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    vf = f"crop=iw:ih*{CROP_BOTTOM_RATIO}:0:ih*{1 - CROP_BOTTOM_RATIO},fps={fps}"
    run_ffmpeg([
        "-y", "-i", str(video),
        "-vf", vf,
        "-q:v", "4",
        str(frames_dir / "f%06d.jpg"),
    ])
    frames = sorted(frames_dir.glob("f*.jpg"))
    if not frames:
        return []

    # ---------- 2. 两级闸门扫描 ----------
    # 每帧：低分辨率检测闸门（~11ms）→ 无框=空帧；框布局变化=关键帧，
    # 才跑完整 OCR（~280ms）；布局未变则复用上一关键帧文本。
    # records: (kind, rows)，kind ∈ {"blank", "key", "same"}，rows 仅关键帧有
    import cv2

    records: list[tuple[str, list[_Row] | None]] = []
    key_rows: list[list[_Row]] = []
    total = len(frames)
    fw = fh = 0
    prev_grid = prev_sig = None
    n_key = 0
    # 进度条耗时权重（ms，纯估算用，与真实基准同量级）
    w_gate, w_key, key_ratio_est = 13.0, 280.0, 0.45
    est_ms = total * w_gate + total * key_ratio_est * w_key

    for i, fp in enumerate(frames):
        img = cv2.imread(str(fp))
        if img is None:
            # 帧文件损坏按空帧处理，不能阻断整条任务
            log.warning("[OCR] 第 %d 帧读取失败，按空帧跳过", i + 1)
            records.append(("blank", None))
            prev_grid = prev_sig = None
        else:
            fh, fw = img.shape[:2]
            try:
                grid, sig = _gate_scan(ocr, img)
            except Exception as exc:  # noqa: BLE001
                # 闸门异常时回退完整 OCR（保召回），并强制下帧重判
                log.warning("[OCR] 第 %d 帧闸门检测失败，回退完整识别：%s",
                            i + 1, exc)
                try:
                    raw, _ = ocr(img)
                except Exception as exc2:  # noqa: BLE001
                    log.warning("[OCR] 第 %d 帧识别失败，按空帧跳过：%s",
                                i + 1, exc2)
                    raw = None
                rows = _parse_rows(raw, fw, fh)
                records.append(("key", rows))
                key_rows.append(rows)
                n_key += 1
                prev_grid = prev_sig = None
            else:
                if grid is None:
                    records.append(("blank", None))
                    prev_grid = prev_sig = None
                else:
                    if prev_grid is None or _is_keyframe(
                            prev_grid, prev_sig, grid, sig):
                        try:
                            raw, _ = ocr(img)
                        except Exception as exc:  # noqa: BLE001
                            log.warning("[OCR] 第 %d 帧识别失败，按空帧跳过：%s",
                                        i + 1, exc)
                            raw = None
                        rows = _parse_rows(raw, fw, fh)
                        records.append(("key", rows))
                        key_rows.append(rows)
                        n_key += 1
                    else:
                        records.append(("same", None))
                    prev_grid, prev_sig = grid, sig

        if progress and (i % 4 == 0 or i == total - 1):
            p = min(0.99, ((i + 1) * w_gate + n_key * w_key) / est_ms)
            progress(p, f"扫描字幕画面 {i + 1}/{total} 帧，识别关键帧 {n_key}")

    log.info("[OCR] 共 %d 采样帧，关键帧 %d（跳过 %.0f%% 完整 OCR）",
             total, n_key,
             100.0 * (1 - n_key / total) if total else 0.0)

    # ---------- 3. 水印/台标剔除（基于关键帧文本频率） ----------
    watermarks = _detect_watermarks(key_rows, n_key)

    # ---------- 4. 判定片源语言基调 → 帧内选行 → 帧文本流 ----------
    # same 帧继承关键帧文本：时间戳覆盖每个采样帧，时间轴语义与
    # 逐帧 OCR 完全一致（桥接/收口逻辑不变）
    cjk_dominant = _detect_cjk_dominant(key_rows)
    if cjk_dominant:
        log.info("[OCR] 判定为中文为主片源，纯外文伴字幕帧不独立成段")
    stream, dropped = _build_stream(records, watermarks, fps, cjk_dominant)
    if dropped:
        log.info("[OCR] 丢弃 %d 个纯外文伴字幕关键帧", dropped)

    # ---------- 5. 时间线状态机归并 + 段级清理 ----------
    drafts = _group_timeline(stream, fps)
    segs = _finalize(drafts, fps)

    if progress:
        progress(1.0, f"OCR 完成，共 {len(segs)} 句")
    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)
    return segs
