"""全局配置：路径、服务参数、常量。

可移植设计：机器相关项全部写在同目录的 service.json（模板见
service.example.json），环境变量优先级最高；所有缺省路径都相对本目录，
因此把整个文件夹拷到任意 Windows 电脑、运行 install.bat 即可使用。
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

# ---------------------------------------------------------------- 基础路径
BASE_DIR = Path(__file__).resolve().parent


def _load_service_file() -> dict:
    """读取可选的 service.json；缺失或损坏时静默回退默认值。"""
    f = BASE_DIR / "service.json"
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


_SERVICE_FILE = _load_service_file()


def _cfg(key: str, env: str | None = None, default=None):
    """配置优先级：环境变量 > service.json > 默认值。空字符串视为未设置。"""
    if env:
        v = os.environ.get(env)
        if v is not None and v.strip() != "":
            return v
    v = _SERVICE_FILE.get(key)
    if v is not None and v != "":
        return v
    return default


def _cfg_list(key: str, env: str, default: list) -> list:
    """列表配置：service.json 里写数组，或环境变量里用逗号分隔。"""
    v = _cfg(key, env, None)
    if v is None:
        return list(default)
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split(",") if s.strip()]


def _cfg_path(key: str, env: str, default: Path) -> Path:
    """路径配置：相对路径相对本模块目录解析。"""
    v = _cfg(key, env, None)
    if v is None:
        return default
    p = Path(str(v)).expanduser()
    return p if p.is_absolute() else (BASE_DIR / p).resolve()


# ---------------------------------------------------------------- 数据目录
DATA_DIR = _cfg_path("data_dir", "VD_DATA_DIR", BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
WORK_DIR = DATA_DIR / "work"
OUTPUT_DIR = DATA_DIR / "outputs"
TMP_DIR = DATA_DIR / "tmp"


# ---------------------------------------------------------------- 模型目录
def _resolve_model_dir() -> Path:
    """显式配置（环境变量 > service.json）优先，否则用本目录 models/。

    配置了但目录尚不存在时仍返回该路径，首次下载会自动创建到这里。
    """
    configured = _cfg("model_dir", "VD_MODEL_DIR", None)
    if configured is not None:
        return _cfg_path("model_dir", "VD_MODEL_DIR", BASE_DIR / "models")
    return BASE_DIR / "models"


MODEL_DIR = _resolve_model_dir()

for _d in (DATA_DIR, UPLOAD_DIR, WORK_DIR, OUTPUT_DIR, MODEL_DIR, TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- ffmpeg
# 搜索根：本目录 ffmpeg/ → service.json/环境变量指定目录 → 系统 PATH
_FFMPEG_ROOTS: list[Path] = [BASE_DIR / "ffmpeg"]
_extra_ff = _cfg("ffmpeg_dir", "VD_FFMPEG_DIR", None)
if _extra_ff is not None:
    _p = Path(str(_extra_ff)).expanduser()
    _FFMPEG_ROOTS.append(_p if _p.is_absolute() else (BASE_DIR / _p).resolve())

_EXE_SUFFIX = ".exe" if os.name == "nt" else ""


def _find_executable(explicit_key: str, explicit_env: str, name: str) -> str:
    """按优先级定位 ffmpeg / ffprobe。

    1) service.json/环境变量显式指定的可执行文件；
    2) 搜索根目录（兼容版本文件夹与 bin 子目录）；
    3) 系统 PATH。
    """
    explicit = _cfg(explicit_key, explicit_env, None)
    if explicit is not None:
        p = Path(str(explicit)).expanduser()
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        if p.exists():
            return str(p)
    exe = f"{name}{_EXE_SUFFIX}"
    for root in _FFMPEG_ROOTS:
        for pattern in (f"**/bin/{exe}", f"**/{exe}"):
            hits = sorted(root.glob(pattern), reverse=True)
            if hits:
                return str(hits[0])
    found = shutil.which(name)
    return found or name


FFMPEG = _find_executable("ffmpeg_binary", "FFMPEG_BINARY", "ffmpeg")
FFPROBE = _find_executable("ffprobe_binary", "FFPROBE_BINARY", "ffprobe")


def ffmpeg_available() -> bool:
    return Path(FFMPEG).exists() or shutil.which(FFMPEG) is not None


# ---------------------------------------------------------------- 模型下载环境
def setup_model_env() -> None:
    """配置 faster-whisper 的模型下载环境。

    必须在使用 WhisperModel 之前调用（模块导入时已自动调用一次）。

    为什么要做这些：
    1. HF_HUB_DISABLE_XET=1
       新版 huggingface_hub 默认走 Xet 存储后端（xethub CDN）。
       国内镜像站不提供 Xet 服务，会直接返回 401 Unauthorized，
       表现为「模型下载失败」。关掉后回退普通 HTTP，镜像站即可正常工作。
    2. HF_ENDPOINT
       默认走 huggingface.co，国内经常连不上；用 hf-mirror.com 镜像。
       已设置过则尊重用户设置，不覆盖。
    3. 清除代理变量
       Clash / v2ray 等本地代理常把 HF 请求打成 502，直连镜像更稳。
    """
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)
    os.environ.setdefault("NO_PROXY", "*")

    os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)
    os.environ["HF_HOME"] = str(MODEL_DIR)
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

    # Windows 关键项：HF 缓存默认用符号链接把 snapshots/ 指向 blobs/。
    # 普通 Windows 账号没有创建符号链接的权限（需开发者模式或管理员），
    # 于是链接创建失败，snapshots/ 下退化成 0 字节空文件，
    # ctranslate2 读取时就会报 "File model.bin is incomplete"。
    # 打开这个开关后改为直接复制（或硬链接），即可正常加载。
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# Hugging Face 镜像（模型下载源），海外网络可改成 https://huggingface.co
HF_ENDPOINT = str(_cfg("hf_endpoint", "HF_ENDPOINT", "https://hf-mirror.com"))

setup_model_env()


# ---------------------------------------------------------------- 音视频参数
SAMPLE_RATE = 16000           # ASR 输入采样率
TTS_SAMPLE_RATE = 24000       # edge-tts 输出采样率
AUDIO_CHANNELS = 1

# ---------------------------------------------------------------- 中文音色
# locale -> 展示名
LOCALE_NAMES = {
    "zh-CN": "普通话（大陆）",
    "zh-CN-liaoning": "东北官话",
    "zh-CN-shaanxi": "中原官话（陕西）",
    "zh-HK": "粤语（中国香港）",
    "zh-TW": "国语（中国台湾）",
}

# 音色元数据：ShortName -> (展示名, 性别, 风格, locale)
VOICE_META: dict[str, dict] = {
    # ---- 普通话 · 女声 ----
    "zh-CN-XiaoxiaoNeural": {
        "label": "晓晓 Xiaoxiao", "gender": "Female", "style": "温暖亲切",
        "locale": "zh-CN", "desc": "最常用的女声，温暖自然，适合旁白与解说",
    },
    "zh-CN-XiaoyiNeural": {
        "label": "晓伊 Xiaoyi", "gender": "Female", "style": "活泼俏皮",
        "locale": "zh-CN", "desc": "年轻活泼，语气轻快，适合短视频与口播",
    },
    # ---- 普通话 · 男声 ----
    "zh-CN-YunxiNeural": {
        "label": "云希 Yunxi", "gender": "Male", "style": "阳光少年",
        "locale": "zh-CN", "desc": "年轻阳光，语感自然，适合通用解说",
    },
    "zh-CN-YunjianNeural": {
        "label": "云健 Yunjian", "gender": "Male", "style": "激情有力",
        "locale": "zh-CN", "desc": "浑厚有力量，适合体育、热血类内容",
    },
    "zh-CN-YunyangNeural": {
        "label": "云扬 Yunyang", "gender": "Male", "style": "专业播音",
        "locale": "zh-CN", "desc": "标准新闻播音腔，适合纪录片与正式内容",
    },
    "zh-CN-YunxiaNeural": {
        "label": "云夏 Yunxia", "gender": "Male", "style": "可爱童声",
        "locale": "zh-CN", "desc": "少年童声，适合动画与轻松内容",
    },
    # ---- 方言 ----
    "zh-CN-liaoning-XiaobeiNeural": {
        "label": "晓北 Xiaobei", "gender": "Female", "style": "东北幽默",
        "locale": "zh-CN-liaoning", "desc": "东北官话女声，幽默接地气",
    },
    "zh-CN-shaanxi-XiaoniNeural": {
        "label": "晓妮 Xiaoni", "gender": "Female", "style": "陕西明亮",
        "locale": "zh-CN-shaanxi", "desc": "中原官话女声，明亮爽利",
    },
    # ---- 粤语（中国香港）----
    "zh-HK-HiuMaanNeural": {
        "label": "曉曼 HiuMaan", "gender": "Female", "style": "友好自然",
        "locale": "zh-HK", "desc": "粤语女声，友好自然",
    },
    "zh-HK-HiuGaaiNeural": {
        "label": "曉佳 HiuGaai", "gender": "Female", "style": "亲切积极",
        "locale": "zh-HK", "desc": "粤语女声，亲切积极",
    },
    "zh-HK-WanLungNeural": {
        "label": "雲龍 WanLung", "gender": "Male", "style": "沉稳友好",
        "locale": "zh-HK", "desc": "粤语男声，沉稳友好",
    },
    # ---- 国语（中国台湾）----
    "zh-TW-HsiaoChenNeural": {
        "label": "曉臻 HsiaoChen", "gender": "Female", "style": "友好自然",
        "locale": "zh-TW", "desc": "台湾国语女声，友好自然",
    },
    "zh-TW-HsiaoYuNeural": {
        "label": "曉雨 HsiaoYu", "gender": "Female", "style": "温柔亲切",
        "locale": "zh-TW", "desc": "台湾国语女声，温柔亲切",
    },
    "zh-TW-YunJheNeural": {
        "label": "雲哲 YunJhe", "gender": "Male", "style": "友好沉稳",
        "locale": "zh-TW", "desc": "台湾国语男声，友好沉稳",
    },
}

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

# ---------------------------------------------------------------- Whisper 模型
WHISPER_MODELS = [
    {"id": "tiny",     "label": "Tiny · 极速",   "size": "约 75 MB",  "note": "最快，准确率一般，适合试跑"},
    {"id": "base",     "label": "Base · 快速",   "size": "约 145 MB", "note": "速度快，准确率尚可"},
    {"id": "small",    "label": "Small · 均衡",  "size": "约 480 MB", "note": "速度与准确率平衡，推荐"},
    {"id": "medium",   "label": "Medium · 精确", "size": "约 1.5 GB", "note": "准确率高，速度较慢"},
    {"id": "large-v3", "label": "Large-v3 · 最准", "size": "约 3.1 GB", "note": "最高准确率，需要较好硬件"},
]
DEFAULT_WHISPER_MODEL = "small"

# ---------------------------------------------------------------- 对齐策略
# 语速可压缩/拉伸的边界，避免听感失真。
# 上限从 1.60 收到 1.35：超过约 1.4 倍后中文会明显发飘、失去自然感，
# 与其硬压语速，不如去「借用」句间的停顿（见 PAUSE_USE）。
MIN_SPEED = 0.85
MAX_SPEED = 1.35
# 一句话允许超出原时长的最大比例，超出则触发压缩
OVERFLOW_TOLERANCE = 1.05

# 相邻句之间保留的最小间隔（秒），避免连读
MIN_GAP = 0.10
# 可借用的「句间停顿」比例。原句说完到下一句开始之间通常有 0.5~2s 空白，
# 配音超时长时优先吃掉这部分空白，而不是硬压语速。
PAUSE_USE = 0.75
# 落后时单句最多提前多少秒开始（在停顿里往回追），避免越拖越远
MAX_CATCHUP = 0.60
# 配音明显短于时间槽时，略微放慢填满，减少大段空白
FILL_GAPS = True
FILL_RATIO = 0.92

# 字幕相对配音的可读性余量（秒）：略微提前出现、延后消失
SUB_LEAD = 0.06
SUB_TAIL = 0.14
SUB_MAX_CHARS = 34

# 中文口播速度经验值（字/秒），用于给翻译做字数预算
ZH_CHARS_PER_SEC = 4.6

# ---------------------------------------------------------------- 译文后处理
# 一句话「能说多少个字」= 时长 × ZH_CHARS_PER_SEC × 下面的系数。
# 系数 1.15 表示允许配音比常速快约 15% —— 这点加速人耳几乎听不出来，
# 却能在不删字的前提下吸收大部分译文偏长的情况。
ZH_BUDGET_SLACK = 1.15
# 译文超出预算多少比例才启动「精简」。
# 1.6 是刻意定得松：轻度偏长靠上面那点语速就吸收掉了，
# 只有明显塞不下时才动文字。动文字的代价是可能损失信息，
# 实测为了对齐把 "…是关键。" 砍成 "…是。" 比听快一点糟糕得多。
ZH_TRIM_THRESHOLD = 1.60
# 精简后最少保留的字数，防止把一句话砍成残句
ZH_MIN_KEEP = 8
# 精简后允许的最长字数（硬上限），超出直接截断
ZH_HARD_MAX = 60

# ---------------------------------------------------------------- 服务
# 监听地址：仅本机用保持 127.0.0.1；局域网其他设备访问改为 0.0.0.0，
# 并在 service.json 的 cors_origins 里放行前端地址（或保持 ["*"]）。
HOST = str(_cfg("host", "VD_HOST", "127.0.0.1"))
PORT = int(_cfg("port", "VD_PORT", 8765))
MAX_UPLOAD_MB = int(_cfg("max_upload_mb", "VD_MAX_UPLOAD_MB", 4096))  # 单视频上限
# CORS 来源：service.json 写数组，或 VD_CORS_ORIGINS 用逗号分隔
CORS_ORIGINS = _cfg_list("cors_origins", "VD_CORS_ORIGINS", ["*"])

# ---------------------------------------------------------------- 作品库发布（GitHub）
# 配音成片上传到 GitHub Releases 资产，作品清单 works.json 提交进仓库随 Pages 发布，
# 访客即可在网站「作品库」在线播放 / 下载。Token 只存在本机 service.json（已 gitignore）。
GITHUB_TOKEN = str(_cfg("github_token", "VD_GITHUB_TOKEN", "") or "").strip()
# 形如 "lxt-promise/mustardseed"
GITHUB_REPO = str(_cfg("github_repo", "VD_GITHUB_REPO", "") or "").strip().strip("/")
GITHUB_BRANCH = str(_cfg("github_branch", "VD_GITHUB_BRANCH", "main") or "main").strip()
# 所有作品挂在同一个固定 Release（按 tag 找，没有就自动创建）
WORKS_RELEASE_TAG = str(_cfg("works_release_tag", "VD_WORKS_RELEASE_TAG", "works") or "works").strip()
WORKS_MANIFEST_PATH = str(
    _cfg("works_manifest_path", "VD_WORKS_MANIFEST_PATH", "frontend/public/works/works.json")
    or "frontend/public/works/works.json"
).strip().lstrip("/")
# 可选：自定义 Pages 域名基址（如 https://mustardseed.example.com）；留空按 owner.github.io/repo 推导
PAGES_BASE_URL = str(_cfg("pages_base_url", "VD_PAGES_BASE_URL", "") or "").strip().rstrip("/")
