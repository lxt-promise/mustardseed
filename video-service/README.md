# 视频译制 · 本地服务（video-service）

为芥末种子「视频译制」页面提供本地处理能力：**英文视频 → 中文配音 + 中文字幕**。
所有处理都在本机完成，视频不上传任何服务器。

本模块是**自包含、可拷贝部署**的：所有机器相关项（端口、ffmpeg、模型目录、CORS）
都在 `service.json` 里配置，代码零硬编码路径。

## 快速开始（本机使用）

1. （仅首次）双击 `install.bat` —— 创建独立 Python 虚拟环境、装依赖，缺 ffmpeg 时可按提示一键自动下载
2. 双击 `start.bat` 启动服务（首次会自动从模板生成 `service.json`），看到 `Uvicorn running on http://127.0.0.1:8765` 即可
3. 打开芥末种子首页 → 办公工具箱 → **视频译制**（卡片带「🖥️ 本地」标记，未启动服务时页面会给出启动指引）
4. 上传视频 → 选音色 → 开始生成，完成后可在线预览、下载成片与字幕

停止服务：关闭服务窗口，或在窗口内按 `Ctrl+C`。

## 部署到另一台电脑（两种方式）

### 方式 A：全离线便携包（推荐，目标电脑零下载、零安装）

便携包已把**便携 Python 3.13 + 全部依赖 + ffmpeg 9.0.1 + tiny/small 模型**全部内置
（约 1.3 GB，解压即用，无需联网、无需装 Python）：

1. 双击 `pack.bat`，在仓库上一级目录生成 `video-service-portable.zip`
   （自动剔除 `venv/`、`data/`、缓存文件）
2. 拷贝 zip 到目标 Windows 电脑（任意目录、任意盘符均可，目录名支持中文/空格），解压
3. 双击 `start.bat` —— 自动优先使用包内 `python\python.exe`，无需 `install.bat`
4. 前端把服务地址指向这台机器：编辑芥末种子构建产物中的 **`dub-config.json`**：

> 注意：环境安装零联网；实际**使用**时 Edge TTS 配音与免费翻译通道本身是在线服务，
> 仍需能访问公网。Whisper 识别、ffmpeg 处理完全离线。
> 便携运行时仅适用于 64 位 Windows（x86_64，Win10/11）。

### 方式 B：源码部署（目标电脑自行下载依赖）

1. 拷贝整个 `video-service/` 文件夹（**不要带 `venv/`、`data/`**；如想省下载可带 `models/` 和 `ffmpeg/`）
2. 双击 `install.bat`：自动建 venv + 装依赖 + 生成 `service.json`，ffmpeg 缺失时选 `Y` 自动下载（约 90 MB）
3. 按需编辑 `service.json`（端口 / 目录 / 局域网访问），双击 `start.bat`
4. 前端把服务地址指向这台机器：编辑芥末种子构建产物中的 **`dub-config.json`**：

   ```json
   { "dubApiBase": "http://192.168.1.20:8765" }
   ```

   改完刷新页面即可，**无需重新构建前端**。局域网访问时，服务端 `service.json`
   需把 `host` 改为 `0.0.0.0`（`cors_origins` 默认 `["*"]` 已放行）。

要求：Windows 10/11 + Python 3.10 ~ 3.13（脚本会自动探测系统 Python、py 启动器、
WorkBuddy 管理的 Python，并跳过微软商店的零字节别名）。

## 配置文件 service.json

首次运行 `install.bat` / `start.bat` 时自动从 `service.example.json` 复制生成；
留空或删除的键使用默认值。**环境变量优先级高于本文件。**

| 键 | 环境变量 | 默认值 | 说明 |
|----|----------|--------|------|
| `host` | `VD_HOST` | `127.0.0.1` | 监听地址；局域网访问改 `0.0.0.0` |
| `port` | `VD_PORT` | `8765` | 服务端口 |
| `cors_origins` | `VD_CORS_ORIGINS`（逗号分隔） | `["*"]` | 允许的前端来源 |
| `data_dir` | `VD_DATA_DIR` | `./data` | 上传/中间文件/成片根目录（相对路径相对本目录） |
| `model_dir` | `VD_MODEL_DIR` | `./models` | Whisper 模型目录；首次识别时自动下载 |
| `ffmpeg_dir` | `VD_FFMPEG_DIR` | `./ffmpeg` | ffmpeg 搜索根目录（自动递归找 `bin/ffmpeg.exe`） |
| `ffmpeg_binary` | `FFMPEG_BINARY` | 空 | 直接指定 ffmpeg 可执行文件完整路径，优先级最高 |
| `ffprobe_binary` | `FFPROBE_BINARY` | 空 | 同上，ffprobe |
| `hf_endpoint` | `HF_ENDPOINT` | `https://hf-mirror.com` | 模型下载镜像；海外网络可改 `https://huggingface.co` |
| `max_upload_mb` | `VD_MAX_UPLOAD_MB` | `4096` | 单视频上传上限（MB） |

ffmpeg 查找优先级：`ffmpeg_binary` → `./ffmpeg/**` 与 `ffmpeg_dir` → 系统 PATH。
全新机器也可不配本目录，直接 `winget install Gyan.FFmpeg` 装入系统 PATH。

## 能力说明

| 环节 | 默认方案 | 可选 |
|------|----------|------|
| 语音识别 | faster-whisper 本地（tiny ~ large-v3），免费离线 | OpenAI 兼容云端识别 |
| 翻译 | 免密钥公益通道 | 自带 Key 的 OpenAI 兼容 LLM（DeepSeek 等，页面「高级设置」） |
| 语音合成 | Edge TTS，14 个中文男/女音色，免费 | — |
| 时长对齐 | 翻译字数约束 + 0.85~1.35x 变速 + 借用句间停顿 | — |
| 字幕输出 | 烧录硬字幕（ASS 样式） | 软字幕版 / 双语字幕 / 外挂 SRT |

生成后可在页面内**直接修改译文并重新配音**（只重跑 TTS 与合成，无需重新识别）。

## 目录说明

```
video-service/
├── start.bat                 启动（自动探测：包内便携 Python → venv → 系统 Python）
├── install.bat               源码方式首次安装（建 venv + 装依赖，离线包不需要）
├── pack.bat                  生成全离线 zip（video-service-portable.zip）
├── run.py                    统一启动入口（读 service.json 起 uvicorn）
├── service.example.json      配置模板（入库）
├── service.json              本机实际配置（自动生成，已 gitignore）
├── app.py                    FastAPI 接口（CORS + 私有网络访问）
├── jobs.py                   任务流水线与状态机
├── asr.py                    识别、断句、翻译
├── dubbing.py                Edge TTS 合成与时间轴对齐
├── media_utils.py            ffmpeg 封装
├── config.py                 配置加载 / 路径 / 音色 / 对齐参数
├── python/                   便携 Python 3.13 + 全部依赖（离线包内置，已 gitignore）
├── ffmpeg/                   内置 ffmpeg 9.0.1（离线包内置，已 gitignore）
├── models/                   tiny/small 模型缓存（离线包内置，已 gitignore）
└── data/                     运行时数据（已 gitignore）
    ├── uploads/  work/  tmp/
    └── outputs/              默认成片目录
```

## 常见问题

**页面提示「本地译制服务未运行」**：先双击 `start.bat`；确认页面展示的服务地址与 `service.json` 的 `host/port` 一致（前端地址在 `dub-config.json` 配置）。
**端口被占用**：改 `service.json` 里的 `port`，同时更新前端 `dub-config.json`；或关闭占用进程。
**install.bat 一闪而过**：新版脚本所有出口都有 pause；若仍闪退，请在 cmd 中手动运行查看输出。
**识别很慢**：CPU 跑大模型较慢，短视频先用 small；或改用云端识别。
**接口调试**：服务启动后访问 http://127.0.0.1:8765/docs 查看交互式 API 文档。
