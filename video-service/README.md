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

## Ubuntu / Linux 部署（服务器或桌面版）

同一套代码，Windows/Linux 通用；Linux 用 `install.sh` / `start.sh`（需 Python 3.10+，
Ubuntu 22.04 / 24.04 自带版本即可）。

### 1. 打部署包（在开发机上）

```bash
# 在 video-service/ 目录（Linux 或 Windows 的 Git Bash 里运行均可）
bash pack.sh                        # 生成 ../video-service-linux.tar.gz（不含模型）
INCLUDE_MODELS=1 bash pack.sh       # 连同 models/ 一起打包（体积大、部署免下载）
```

> Windows 便携 `python/`、`ffmpeg/` 是 exe，Linux 用不了，打包时已自动排除；
> Linux 的 ffmpeg / 中文字体由 `install.sh` 通过 apt 安装。

### 2. 传到 Ubuntu 并安装

```bash
scp video-service-linux.tar.gz 用户名@服务器IP:~/
# 在 Ubuntu 上：
tar xzf video-service-linux.tar.gz
cd video-service
bash install.sh        # apt 装 ffmpeg + fonts-noto-cjk，建 .venv，装 pip 依赖
```

`fonts-noto-cjk` 是**烧录中文字幕的必需字体**，缺失时中文会显示成方块或烧录失败。

### 3. 启动与局域网访问

- 前台：`bash start.sh`（保持窗口打开，Ctrl+C 停止）
- 安装时被询问是否开放局域网，选 `Y` 会把 `service.json` 的 `host` 改成 `0.0.0.0`；
  事后也可手动改。
- 防火墙（如启用 ufw）：`sudo ufw allow 8765/tcp`

### 4. 让服务器同源托管前端（推荐，免混合内容问题）

GitHub Pages 是 HTTPS，浏览器会拦截它直接调用 `http://服务器IP:8765`（混合内容）。
因此在服务器上让服务**自己托管页面**，浏览器只访问一个地址：

```bash
# 把前端构建产物（frontend/dist 的内容）放到 video-service/web/
# 并确保其中 dub-config.json 为：{ "dubApiBase": "origin" }
# 重启服务后浏览器直接打开：
http://<服务器IP>:8765/
```

`"origin"` 表示前端自动使用当前访问源，无需写死 IP。

### 5. 后台常驻（systemd，可选）

```bash
# 按实际路径/用户编辑单元文件里的 User / WorkingDirectory / ExecStart
sudo cp deploy/videodub.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now videodub
sudo systemctl status videodub       # 查看状态
journalctl -u videodub -f            # 看日志
```

### 6. 部署后自检

```bash
curl http://127.0.0.1:8765/api/health      # ffmpeg / whisper / edge-tts 状态
fc-list :lang=zh family | head             # 应能看到 Noto Sans/Serif CJK
.venv/bin/python selftest.py               # 端到端流水线自检（可选）
```

## 公网部署：GitHub Pages + Apache 反向代理（HTTPS 域名）

适用场景：服务器有公网域名（如 `christu.bid`）和已配好 HTTPS 的 Apache（如 10085 端口），
前端仍由 GitHub Pages 托管。浏览器要求 HTTPS 页面只能调 HTTPS 接口，所以由
**Apache 终止 HTTPS 并反代到本机 FastAPI**，后端不直接暴露公网。

```
浏览器 ──HTTPS──> Apache :10085 (christu.bid, 证书)
                      │ 反向代理 /api
                      ▼
                 FastAPI 127.0.0.1:8765（只监听本机）
```

### 1. 后端只监听本机

`service.json` 保持 `"host": "127.0.0.1"`（install.sh 询问开放局域网时选 **N**），
用 systemd 常驻（见上文第 5 节）。公网只通过 Apache 进入。

### 2. 配置 Apache（核心）

把 [deploy/apache-videodub.conf](deploy/apache-videodub.conf) 里的指令合并进
**现有监听 10085 的那个 HTTPS `<VirtualHost>`**（与现有页面共存，不要整段替换）：

```bash
sudo a2enmod proxy proxy_http headers
sudo apache2ctl configtest && sudo systemctl reload apache2
```

三个易错点（配置文件注释里也有）：

- **目标必须保留 `/api` 前缀**：后端路由本身就是 `/api/xxx`，
  `ProxyPass /api http://127.0.0.1:8765/api`（末尾**不要**加 `/`，否则 404）；
- **大文件上传**：`LimitRequestBody 0` + `ProxyTimeout 3600`，否则 60 秒掐断；
- **不要在 Apache 里再加 CORS 头**：后端已返回，重复头反而导致跨域失败。
  想收紧来源就在 `service.json` 设 `"cors_origins": ["https://lxt-promise.github.io"]`。

### 3. 前端地址（已配置好）

GitHub Pages 上的 `dub-config.json` 已指向：

```json
{ "dubApiBase": "https://christu.bid:10085" }
```

注意**不带 `/api` 后缀**（客户端代码自己拼 `/api/...`）。合并本分支到 main 推送后，
GitHub Pages 自动生效。部署后可用浏览器 F12 → Network 确认请求走
`https://christu.bid:10085/api/health`。

### 4. 域名 / 防火墙 / 证书

- **Cloudflare 免费版不代理 10085 端口**（仅支持 443/8443 等少数端口）：
  若域名开了橙云代理，需在 Cloudflare DNS 把该记录改成**灰云（仅 DNS）**直连；
  或把 Apache 改到 443/8443。
- 防火墙：`sudo ufw allow 10085/tcp`（云厂商安全组也要放行）。
- **证书必须对 christu.bid 有效**：fetch 不像浏览器地址栏可以手动信任例外，
  证书有问题时接口会静默失败。`curl -v https://christu.bid:10085/api/health`
  验证应返回 JSON 且无证书报错。
- Ubuntu 桌面版记得在电源设置里关闭自动休眠/待机。

### 5. 公网安全提示

该服务没有登录鉴权，知道域名的人都能调用（上传/消耗 CPU 与 TTS 配额）。
私有使用建议：用 Cloudflare Access 或 Apache Basic Auth 给 `/api` 加一道认证；
不要把 8765 直接监听 `0.0.0.0` 暴露公网。

## 用户隔离

公网多人共用服务时，任务/上传互不可见：

- 前端在浏览器 `localStorage` 生成匿名 uid（`vd_uid`），所有请求携带
  `X-User-Id` 头；`<video>/<img>` 等无法带自定义头的媒体标签改用 `?uid=` 参数。
- 服务端按 uid 过滤任务列表；单个任务的查看/取消/删除/下载/预览/缩略图/
  文稿编辑/重跑/发布/会议转写查询都做归属校验，他人任务一律按 404 处理
  （不泄露存在性）。无身份头的请求（命令行/本机脚本）归入 `default`。
- 这是设备级隔离而非登录体系：uid 不可猜（UUID），但可被本机用户读走。
  如需强鉴权，可在 Apache 层加 Basic Auth 并用 `RequestHeader set` 注入
  `X-User-Id`（ REMOTE_USER），覆盖客户端伪造。
- 任务仍在内存中，服务重启后清空（现状不变）；`/api/browse` 等文件浏览
  接口仍是全局的，公网部署建议在 Apache 层限制或禁用。

## 会议记录转写接口（/api/meeting/*）

供前端「会议记录」模块调用（也可独立使用）：

- `POST /api/meeting/transcribe`：multipart 上传音频（webm/mp3/m4a/wav/ogg/opus/aac/flac/mp4…，
  ≤200MB），表单字段 `model`（tiny/base/small/medium/large-v3，默认 small）、`language`
  （留空自动检测）。返回 `{"id": "..."}`，转写为后台线程异步执行。
- `GET /api/meeting/transcribe/{id}`：轮询。返回 `status`（processing/done/failed）、
  `progress`（0~1）、`message`；完成后含 `result`：
  `{duration, language, model, segments:[{start,end,text}], text, srt}`。
- 任务与音频保留 24 小时，之后在下一次上传时自动清理；中间文件在 `data/meeting/`。

前端地址在 `frontend/public/meeting-config.json` 配置：`asrApiBase` 指向本服务
（支持 `origin` 同源约定），`aiApiBase` 指向 Java backend 的大模型接口（如
`http://localhost:8080/api`）。HTTPS 页面调 HTTP 的 aiApiBase 会被浏览器拦截，
公网使用需为 backend 配 HTTPS 反代或在本地打开页面。

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
| `web_dir` | `VD_WEB_DIR` | `./web`（不存在则不托管） | 前端构建产物目录，存在即同源托管页面 |

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
├── start.bat / start.sh      启动（Win/Linux，自动探测便携 Python → venv → 系统 Python）
├── install.bat / install.sh  首次安装（Win 建 venv 装依赖；Linux 另装 apt 依赖）
├── pack.bat / pack.sh        打包（Win 全离线 zip；Linux tar.gz 源码部署包）
├── deploy/videodub.service   systemd 后台服务单元模板（Linux）
├── run.py                    统一启动入口（读 service.json 起 uvicorn）
├── service.example.json      配置模板（入库）
├── service.json              本机实际配置（自动生成，已 gitignore）
├── web/                      可选：同源托管的前端构建产物（已 gitignore）
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
