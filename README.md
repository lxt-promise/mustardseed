# 🌱 芥菜种子 mustardseed — 项目总览（迁移/接手文档）

> 一粒最小的种子，也能长成最大的植物。
> 清新治愈的综合工具站，含纯前端小工具、视频译制流水线、会议转写、大模型对话等模块。
> 线上地址：https://lxt-promise.github.io/mustardseed/ · 仓库：https://github.com/lxt-promise/mustardseed

本文档面向**迁移到新机器**或**新接手的开发者/AI**，读完可独立把三个服务跑起来、改代码、部署。

---

## 目录

1. [整体架构](#1-整体架构)
2. [仓库目录结构](#2-仓库目录结构)
3. [前端 frontend/](#3-前端-frontend)
4. [视频服务 video-service/](#4-视频服务-video-service)
5. [Java 后端 backend/](#5-java-后端-backend)
6. [本地开发（三服务启动）](#6-本地开发三服务启动)
7. [运行时配置文件说明](#7-运行时配置文件说明)
8. [部署指南](#8-部署指南)
9. [核心设计与约定（改代码前必读）](#9-核心设计与约定改代码前必读)
10. [迁移到新机器 Checklist](#10-迁移到新机器-checklist)
11. [常见坑速查](#11-常见坑速查)

---

## 1. 整体架构

Monorepo，**三个相互独立、可单独运行的服务**：

```
┌─────────────────────────────────────────────────────────────────┐
│  浏览器                                                          │
│  · GitHub Pages  https://lxt-promise.github.io/mustardseed/     │
│  · 本地开发      http://localhost:9999   (vite dev)             │
│  · 服务自托管    http://<服务器>:8765    (FastAPI 托管 dist)     │
└───────┬───────────────────────────────────┬─────────────────────┘
        │ 视频译制 / 会议转写 / 视频库       │ AI 对话/总结
        ▼                                   ▼
┌──────────────────────┐            ┌──────────────────────┐
│ video-service :8765  │            │ backend :8080        │
│ FastAPI (Python)     │            │ Spring Boot 3 + JDK21│
│ ffmpeg + Whisper +   │            │ MyBatis-Plus + H2    │
│ edge-tts + OCR       │            │ 智谱 GLM (zai-sdk)   │
│ 任务持久化 jobs.json │            │ SSE 流式对话         │
└──────────┬───────────┘            └──────────────────────┘
           │ 公网入口：Apache HTTPS 反代
           ▼
   https://christu.bid:10085/api → 127.0.0.1:8765
```

**端口约定**

| 服务 | 端口 | 技术栈 |
|---|---|---|
| 前端 dev server | 9999 | Vite |
| video-service | 8765 | FastAPI / uvicorn |
| backend | 8080（context-path `/api`） | Spring Boot |
| 公网 video-service | 10085（HTTPS，Apache 反代） | — |

**典型调用链（视频译制）**：上传视频 → faster-whisper 识别英文字幕 → backend GLM 翻译成中文 → edge-tts 合成中文配音 → ffmpeg 对齐时间轴并合成成片 → 用户可选发布到视频库。

---

## 2. 仓库目录结构

```
easy/
├─ frontend/                  # ① React 前端（GitHub Pages 主站点）
├─ video-service/             # ② Python 视频处理服务（可独立分发）
├─ backend/                   # ③ Spring Boot 大模型/音乐后端
├─ scripts/                   # 研经日课数据抓取与拆分脚本（Node）
├─ pack.bat                   # 一键打 video-service Linux 部署包（双击）
├─ .github/workflows/         # GitHub Actions：push main 自动部署 Pages
└─ README.md                  # 本文档
```

---

## 3. 前端 frontend/

### 3.1 技术栈

React 18 + TypeScript(strict) + Vite 5 + TailwindCSS 3 + react-router v6（**HashRouter**，天然兼容 GitHub Pages 深链）。无重型状态库，用户数据存 `localStorage`。

### 3.2 页面（src/pages/）

| 路由 | 文件 | 说明 |
|---|---|---|
| `/` | Home.tsx | 首页双板块导航（办公/休闲） |
| `/pomodoro` | Pomodoro.tsx | 番茄钟 |
| `/todo` | Todo.tsx | 待办清单 |
| `/workdays` | Workdays.tsx | 工作日计算 |
| `/verse` | Verse.tsx | 治愈金句（200 条中英经文，SVG 分享图） |
| `/music` | Music.tsx | 音乐小站 |
| `/quiz` | Quiz.tsx | 趣味小测试（颜色性格等） |
| `/reading` `/reading/:id` | Reading.tsx / ReadingDetail.tsx | 研经日课（新旧约 66 卷，**887 个按章拆分的数据块**） |
| `/dub` | Dub.tsx | 视频译制工作台（核心重功能页） |
| `/meeting` | Meeting.tsx | 会议记录：录音→Whisper 转写→GLM 大纲 |
| `/works` | Works.tsx | 视频库（有前端写死的访问码门禁） |
| `/more` | More.tsx | 版本/Git 信息/反馈 |
| `/picker` | Picker.tsx | 纠结人神器（当前入口已隐藏） |

### 3.3 关键源码

```
src/
├─ main.tsx               # 入口：HashRouter + 全部页面 React.lazy 懒加载
│                          #   配置(dub/meeting)异步加载，不阻塞首屏
├─ api/
│   ├─ dub.ts             # video-service 全部 API + 运行时地址自适应(见 7.3)
│   ├─ meeting.ts         # 会议模块 API（ASR 走 video-service，AI 走 backend）
│   ├─ request.ts         # fetch 封装（自动带 X-User-Id）
│   └─ index.ts           # backend 音乐/AI 相关 axios 封装
├─ data/
│   ├─ reading.ts         # 研经日课：按章懒加载/缓存/预取
│   ├─ articles/{ot,nt}/<卷序>/<章>.json  # 887 个章块（split 产物，勿手改）
│   ├─ ot_index.json / nt_index.json     # 两约索引（约 160KB，空闲预取）
│   ├─ ot_articles.json / study_articles.json  # 原始大 JSON（仅抓数脚本用，app 不 import）
│   └─ verses.ts          # 金句数据
├─ components/             # BottomNav/PageHeader/SiteFooter/播放器等
├─ context/PlayerContext.tsx
└─ utils/                  # storage / analytics / shareImage 等
public/
├─ dub-config.json         # video-service 地址（运行时 fetch，免重新构建）
├─ meeting-config.json     # 会议模块 asrApiBase / aiApiBase
└─ works/works.json        # 旧版 GitHub 发布清单（本地视频库方案下已不用）
```

### 3.4 数据更新流程（研经日课）

原始数据由 `scripts/` 下的 Node 脚本抓取生成大 JSON，**必须再跑拆分脚本** app 才能用上：

```bash
node scripts/split_books.mjs   # 重建 src/data/articles/{ot,nt}/，887 个章块
cd frontend && npm run build
```

---

## 4. 视频服务 video-service/

Python ≥ 3.10 的 FastAPI 服务，可在 Windows / Ubuntu 运行，也可完全离线便携分发。

### 4.1 模块职责

| 文件 | 职责 |
|---|---|
| `run.py` | 启动入口（读 config 的 host/port，默认 127.0.0.1:8765） |
| `app.py` | 全部 HTTP 路由（约 40 个，见 4.4）+ 静态托管 `web/`（catch-all，**必须在所有 API 路由之后 mount**） |
| `config.py` | 全局配置：路径/ffmpeg 定位/模型目录/HF 镜像/音色表/端口。优先级 **环境变量 > service.json > 默认值** |
| `jobs.py` | `Job` dataclass + `JobManager`：任务生命周期、线程池、并发信号量、**jobs.json 持久化** |
| `asr.py` | faster-whisper 语音识别（模型 tiny~large-v3，默认 small） |
| `dubbing.py` | edge-tts 合成 + 时间轴对齐（借句间停顿、语速 0.85~1.35）+ ffmpeg 成片 |
| `media_utils.py` | ffprobe/ffmpeg 封装、缩略图、归一化（同步阻塞调用扔线程池） |
| `ocr_subtitle.py` | rapidocr-onnxruntime 提取画面硬字幕 |
| `publisher.py` | 旧方案：发布成片到 GitHub Releases（本地视频库方案上线后基本不用） |
| `settings.py` | 用户偏好（输出目录等）持久化 |
| `download_model.py` | Whisper 模型手动下载 |
| `selftest.py` | 环境自检（ffmpeg/字体/模型） |
| `import_outputs.py` | **一次性脚本**：把 data/outputs 里的存量 mp4 导入视频库（指定 uid 为所有者） |

### 4.2 运行时目录（均不打进部署包）

```
video-service/
├─ data/
│   ├─ jobs.json        # 任务持久化（原子写：tmp+replace；启动恢复，running→failed）
│   ├─ uploads/         # 原始上传
│   ├─ work/<jid>/      # 中间产物（识别 srt、分段音频等）
│   ├─ outputs/         # 最终成片 mp4
│   └─ tmp/             # 缩略图等临时文件
├─ models/              # Whisper 模型（首次使用自动从 hf-mirror.com 下载）
├─ web/                 # 前端构建产物（frontend/dist 拷贝到这里即同源托管）
├─ python/              # Windows 便携 Python（仅 Windows 包，Linux 用 .venv）
├─ ffmpeg/              # Windows 版 ffmpeg（Linux 走 apt）
├─ service.json         # 本机配置（gitignore，模板 service.example.json）
└─ .venv/               # Linux 虚拟环境
```

### 4.3 处理流水线与并发

`上传 → probe → ASR(语音识别/OCR) → 翻译(调 backend GLM) → TTS → 合成烧录 → done`

- **并发控制**：信号量限制同时转码任务数（按 CPU 核数，典型 2），防 CPU/内存打爆和外部 TTS 限流。
- **事件循环保护**：probe、ffmpeg 等同步阻塞操作一律丢线程池，禁止在 async 端点里直接跑。
- **断点保护**：任务状态实时落 jobs.json；服务重启后 running 任务标记 failed「服务重启中断」。

### 4.4 主要 API（前缀 /api，交互式文档 `/docs`）

- 能力/配置：`GET /health` `/options` `/settings` `/voices` `/models*`
- 文件：`POST /upload` `/upload-subtitle`、`GET /download/{jid}/{kind}` `/preview` `/thumbnail` `/audio`
- 任务：`POST /jobs`、`GET /jobs`（按用户隔离）、`GET /jobs/{jid}`、`POST /jobs/{jid}/cancel`、`DELETE /jobs/{jid}`、`POST /redo/{jid}`（换音色重跑）、`POST /segments/{jid}`（人工校对字幕）
- 视频库：`POST /jobs/{jid}/publish|unpublish`、`POST /works/publish-all`、`GET /works`（公开）、`GET /works/{jid}/video|thumb`（公开，视频标签用 `?uid=`）、`DELETE /works/{jid}`（**仅所有者**）
- 会议：`POST /meeting/transcribe`（异步）、`GET /meeting/transcribe/{job_id}`（轮询）
- 兜底：`api_route("/api/{rest:path}")` 未匹配统一返回 404 JSON（避免请求落静态挂载变 405）

### 4.5 用户隔离机制（重要）

- 浏览器首次访问在 localStorage 生成匿名 `vd_uid`；所有 fetch 自动带 `X-User-Id` 头，`<video>/<img>` 等媒体标签用 `?uid=` 参数。
- 后端 `_user_id()`：**缺身份头直接 401**（早期归入共享 `default` 池导致串号，已废弃该行为）。
- `_owned_job()`：任务详情/取消/删除/发布等校验 uid 与 `job.user` 一致，不一致返回 404。
- `/api/works` 公开可读（人人可看已发布作品），响应仅在带身份头时回 `owner` 字段供前端决定是否显示删除按钮。

---

## 5. Java 后端 backend/

Spring Boot 3.2.5 / JDK 21 / MyBatis-Plus 3.5.5 / 内嵌 **H2 文件库**（无需装数据库）。

### 5.1 模块

- **大模型**（当前主要用途）：
  - `controller/AiController.java`：`POST /api/ai/chat` 同步对话；`GET /api/ai/chat/stream` **SSE 流式**（zai-sdk 的 RxJava3 Flowable → `SseEmitter`）
  - `service/AiService.java`、`config/AiProperties.java`、`dto/AiChatRequest|AiMessage`
  - SDK：`ai.z.openapi:zai-sdk:0.3.5`（智谱 GLM，默认模型 `glm-4.7-flash` 思考模型）
- **音乐管理（遗留）**：Song / Playlist / Category / AppSetting 的 CRUD（controller/service/mapper/entity 标准 MyBatis-Plus 分层），H2 库由 `resources/db/schema.sql` + `data.sql` 自动初始化。

### 5.2 配置（resources/application.yml）

- 端口 8080，context-path `/api`；H2 数据文件 `./data/musicdb`，控制台 `/api/h2-console`。
- AI key 优先取环境变量 **`AI_API_KEY`**，yml 里有内置兜底值（迁移后建议改用环境变量并轮换该 key）。
- 429「访问量过大」时可换 `glm-4-flash` 并把 `thinking-enabled` 设为 `false`。
- 注意：zai-sdk 0.3.5 会把 HTTP 429 转成通用 `"Call Failed"`，**重试逻辑要按"任意远程失败"触发，不能匹配错误文案**。

---

## 6. 本地开发（三服务启动）

前置：Node ≥ 18、JDK 21 + Maven、Python 3.10+（Windows 可直接用 video-service 自带便携环境）。

```powershell
# ① 前端（热更新）
cd frontend
npm install
npm run dev          # http://localhost:9999

# ② video-service（Windows 首次先跑 install.bat 装便携 Python/ffmpeg/模型环境）
cd video-service
.\python\python.exe run.py     # http://127.0.0.1:8765
# Linux/Mac：bash install.sh 后  bash start.sh  或  .venv/bin/python run.py

# ③ backend
cd backend
$env:AI_API_KEY="你的key"      # 可选，不设用 yml 兜底
mvn spring-boot:run            # http://localhost:8080/api
```

开发时前端在 9999，会自动把 video-service 请求指向 `http://127.0.0.1:8765`（见 7.3）。会议总结的 AI 请求地址取 `meeting-config.json` 的 `aiApiBase`（默认 `http://localhost:8080/api`）。

---

## 7. 运行时配置文件说明

这些是**运行时 fetch 的 JSON**，改后无需重新构建前端（但要清浏览器缓存/Ctrl+F5）：

### 7.1 `frontend/public/dub-config.json`

```json
{ "dubApiBase": "https://christu.bid:10085" }
```

### 7.2 `frontend/public/meeting-config.json`

```json
{ "asrApiBase": "https://christu.bid:10085", "aiApiBase": "http://localhost:8080/api" }
```

### 7.3 dubApiBase 自适应规则（api/dub.ts `initDubConfig`）

| 打开前端的位置 | 实际请求 video-service |
|---|---|
| `*.github.io`（GitHub Pages） | 用配置值 `https://christu.bid:10085` |
| 端口 8765（FastAPI 自托管） | 同源 `当前 origin` |
| 端口 10085 / host=christu.bid（Apache 反代） | 同源 `当前 origin` |
| 其他端口（如本地 9999 开发服） | `http://127.0.0.1:8765` |

所以**只需维护一份配置**，本地开发、服务器同源托管、GitHub Pages 自动适配。

### 7.4 `video-service/service.json`（从 service.example.json 复制）

常用键：`host`（本机 127.0.0.1 / 局域网公网 0.0.0.0）、`port`、`cors_origins`（公网务必收紧为具体域名，不要 `*`）、`max_upload_mb`、`hf_endpoint`、`web_dir`。全部支持 `VD_` 前缀环境变量覆盖（如 `VD_HOST`、`VD_PORT`）。**该文件含密钥不入库、不打进部署包。**

---

## 8. 部署指南

### 8.1 前端 → GitHub Pages（自动）

push 到 `main` 且改动涉及 `frontend/**` 时，`.github/workflows/deploy-frontend.yml` 自动 `npm ci → build → 复制 404.html(SPA 回退) → deploy-pages`。也可在 Actions 手动 Run workflow。

- 改仓库名需同步 `frontend/vite.config.ts` 的 `base: '/mustardseed/'`（自定义域名改 `'/'`）。
- `vite.config.js/.d.ts` 是 tsc 产物，已被 gitignore，**切勿提交**（会遮蔽 .ts 配置）。

### 8.2 前端同步给 video-service 同源托管

```powershell
cd frontend; npm run build
robocopy .\dist ..\video-service\web /MIR /NFL /NDL /NJH
```

### 8.3 video-service → Ubuntu

1. Windows 下双击根目录 **`pack.bat`**（用系统自带 tar.exe，无需 bash），生成 `video-service-linux.tar.gz`（约 16MB）。
   排除：`venv/.venv/data/python/ffmpeg/.git/service.json/models(models_retry)/__pycache__/*.pyc/log/tmp`。
2. 上传并解压：`scp` 后 `tar -xzf video-service-linux.tar.gz -C /opt/`（得到 `/opt/video-service`）。
3. 首次部署：`cd /opt/video-service && bash install.sh`（装 ffmpeg、fonts-noto-cjk、建 .venv、装 pip 依赖、生成 service.json）。
4. 注册系统服务：复制 `deploy/videodub.service` 到 `/etc/systemd/system/`（按实际改 User/路径），`systemctl enable --now videodub`。
5. 后续更新代码：停服务 → 解压覆盖 → 启动；**脚本不用改**，data/ 与 .venv 在包外不受影响。

### 8.4 公网 HTTPS（Apache 反代）

参考 `video-service/deploy/apache-videodub.conf`，要点（容易错）：

- `ProxyPass /api http://127.0.0.1:8765/api`——**目标不能加尾斜杠**，否则 /api 前缀被剥 → 404。
- 大视频上传需 `LimitRequestBody 0` + `ProxyTimeout 3600`。
- **不要在 Apache 里加 CORS 头**：后端 CORSMiddleware 已返回，再加会产生重复头导致跨域失败；收紧来源改 service.json `cors_origins`。
- service.json 保持 `host=127.0.0.1`，只让 Apache 对公网暴露。
- 公网环境还应关闭 `/api/browse`、`/api/mkdir`、`/api/open-folder`（本机目录浏览接口）并加 Basic Auth / token。

### 8.5 backend 部署

普通 Spring Boot fat jar：`mvn package` 后 `java -jar`，配 `AI_API_KEY` 环境变量；H2 文件库随 jar 目录自动创建。

---

## 9. 核心设计与约定（改代码前必读）

1. **视频库的"发布"= jobs.json 里 `published:true` 标记**，文件原地不移动；列表查 `published && done && 有 video 产物`。删除仅校验所有者。不要改成"移动文件到 public 目录"（会引入额外元数据且破坏任务-产物一致性）。
2. **所有视频服务敏感端点必须过 `_owned_job`**；媒体公开端点用 `?uid=` 而不是头。新增涉及任务的接口照此办理。
3. **前端重活懒加载**：页面用 `React.lazy`；研经日课按章 chunk（`import.meta.glob`），同章切换零请求。别再 import 两个大 JSON（8MB+）。
4. **配置不阻塞首屏**：dub/meeting 配置在 main.tsx 挂载后异步 init；UI 先渲染。
5. **弹窗/悬浮层不要放在带 `animate-fade-up`（transform）的容器内**：transform 会创建层叠上下文导致 `position:fixed` 失效——弹层要用 Fragment 移到该容器外。
6. **TS 布尔开关写显式常量**（如 `const SHOW_PUBLISH: boolean = true`），不要用 `false && (...)`，否则类型窄化失效、死代码报错。
7. **视频译制提交前**：字幕来源（语音识别 / 硬字幕 OCR）是必选分段单选，未选禁用提交。
8. **音频走 CDN 外链**，不放本地 public/audio（小程序包体限制）；更换音源要递增 storage key（v2/v3…）清旧缓存。
9. **分析埋点**：`utils/analytics.ts`，工具入口点击、页面浏览统一 `trackEvent/trackPageview`。
10. **样式主题**：薄荷绿 `#1a9464`，Tailwind mint 色板；移动端优先，内容最大宽 720px。
11. 视频库访问码（392766）是**前端写死**的 `WORKS_PASSWORD`，sessionStorage 记住解锁——只防随手点入，不是真正的权限控制；要真安全需后端鉴权。

---

## 10. 迁移到新机器 Checklist

**拉代码**

- [ ] `git clone`（或拷贝整个目录；`data/`、`models/`、`.venv/`、`python/` 不在 git 里，见下）

**前端**

- [ ] 安装 Node ≥ 18；`cd frontend && npm install && npm run dev` 验证 9999
- [ ] 生产构建 `npm run build`，需要自托管就把 `dist/` 拷到 `video-service/web/`

**video-service（Windows）**

- [ ] 运行 `install.bat`（下载便携 Python/ffmpeg、建依赖）；首次识别会自动下载 Whisper 模型（走 hf-mirror，约 480MB small 档）
- [ ] 从 `service.example.json` 复制 `service.json`，按需改 host/cors
- [ ] `.\python\python.exe run.py`，访问 `/docs` 自检

**video-service（Ubuntu）**

- [ ] 用根目录 `pack.bat` 打包 → 上传 → 解压到 `/opt/video-service`
- [ ] `bash install.sh`（ffmpeg + 中文字体 + .venv + 依赖）
- [ ] 配置 `deploy/videodub.service` → systemd 启动；需要公网再配 Apache（8.3/8.4）

**backend**

- [ ] 安装 JDK 21 + Maven；`mvn spring-boot:run`
- [ ] 设置 `AI_API_KEY` 环境变量（H2 库首次启动自动建，无需导数据）

**改地址**

- [ ] 域名/端口变化时改：`frontend/public/dub-config.json`、`meeting-config.json`（GitHub Pages 用）；`video-service/service.json`；Apache 配置
- [ ] 本机自托管/本地开发无需改配置（7.3 自适应）

**存量数据（可选）**

- [ ] 迁移历史成片：拷贝 `video-service/data/`（含 jobs.json 与 outputs）
- [ ] 把散落 outputs 里没任务记录的 mp4 纳入视频库：`python import_outputs.py <vd_uid>`（uid 在浏览器控制台 `localStorage.getItem('vd_uid')` 获取）

---

## 11. 常见坑速查

| 现象 | 原因 / 处理 |
|---|---|
| edge-tts 报 `503 ... wss://speech.platform.bing.com` | 微软 TTS 临时不可用/限流，代码已自动重试；持续失败就重跑任务 |
| AI 总结报通用 `Call Failed` | zai-sdk 把 429 吞成通用错误；按任意远程失败重试，或换 glm-4-flash |
| 接口返回"接口不存在"但代码里有 | 方法不匹配（如 POST 路由用 GET 打）会落 catch-all；PowerShell `Invoke-RestMethod` 默认 GET，POST 要显式 `-Method Post` |
| 改了 video-service 代码不生效 | 8765 是手动常驻进程，必须重启；可查 `/api/jobs` 是否含 `stage_timings` 区分新旧代码 |
| GitHub Pages(https) 调本机 http 接口失败 | 混合内容拦截。让 FastAPI 托管 dist 同源访问，或走 HTTPS Apache 反代 |
| Apache 反代后跨域失败 | 多半是 Apache 重复加了 CORS 头，或 `ProxyPass` 加了尾斜杠剥掉 /api |
| Whisper 模型下载 401 / incomplete | config.py 已处理（关 Xet、用 hf-mirror、Windows 禁符号链接）；确认 `models/` 可写、代理已清 |
| Whisper 任务 CPU 拉满 | 信号量按核数限并发（默认约 2），别调太大 |
| 首页/导航打开要等几秒 | 检查是否在首屏同步 await 配置或 import 大 JSON；配置应异步、页面应 lazy |
| 视频播放弹窗跑到页面底部 | 祖先节点有 transform 动画破坏 fixed 定位，弹层移出 `animate-fade-up` 容器 |
| 8765 端口被占 / 重启失败 | Windows: `Get-NetTCPConnection -LocalPort 8765` 找进程，`Stop-Process` 后再起；确认子进程已退出 |
| PowerShell 打包找不到 bash | 不用 bash，根目录 `pack.bat` 用系统 tar.exe(bsdtar) 打包 |

---

Made with 💚 · 芥菜种子
