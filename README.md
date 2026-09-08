# 🌱 芥菜种子 (mustardseed)

> 一粒最小的种子，也能长成最大的植物 —— 每一件小事都算数。
> 一个清新治愈的综合工具箱：**办公 | 休闲 双模式**，**纯前端**，无需登录，所有数据保存在你的浏览器本地。
> 在线访问：https://lxt-promise.github.io/mustardseed/ · 仓库：https://github.com/lxt-promise/mustardseed

---

## ✨ 功能总览

### 🛠️ 办公工具箱
| 工具 | 状态 | 亮点 |
|---|---|---|
| 🍅 番茄钟 | ✅ 已上线 | 圆形进度 SVG；专注/短休/长休三模式；每日目标；WebAudio 合成提示音；标签页实时倒计时 |
| ✅ 待办清单 | ✅ 已上线 | 回车添加 / 星标 / 到期日 / 双击编辑 / 5 种筛选 / 导出 txt / 一键清已完成 |
| 📅 工作日计算 | ✅ 已上线 | 双休 / 单休 / 大小周三种模式；本月、本季度、今年剩余快捷选择；日历视图标注工作日与休息日 |
| 📏 JSON 格式化 | ⏳ 规划中 | 美化 / 压缩 / 校验 / 格式化错误定位 |
| ⏱️ 时间戳转换 | ⏳ 规划中 | Unix 时间戳 ↔ 本地时间 / UTC / 毫秒级 |

### 🎡 休闲娱乐
| 工具 | 状态 | 亮点 |
|---|---|---|
| 🎯 纠结人神器 | ✅ 已上线 | 6 个内置模板（吃啥/喝啥/周末/做不做/硬币/骰子）+ 快速填充 + 自定义选项；滚动减速抽奖动画；历史记录 |
| ✨ 治愈金句 | ✅ 已上线 | 内置 **200 条中英对照经文金句**；9 种主题筛选 + ⭐收藏；一键复制；导出 **SVG 矢量分享图** |
| 🎵 音乐小站 | ⏳ 即将开放 | 播放器 UI 已就绪，音源接入中 |
| 🧩 趣味小测试 | ⏳ 即将开放 | 颜色性格 / 笑话 / 人生锦囊（代码已完成，即将回归） |
| ℹ️ 更多 | ✅ 已上线 | 版本信息 / 建议反馈（GitHub Issues）/ 工具目录入口 |

---

## 🚀 本地开发

前置条件：**Node.js ≥ 18**

```bash
git clone https://github.com/lxt-promise/mustardseed.git
cd mustardseed/frontend
npm install
npm run dev       # → http://localhost:9999/
```

其他命令：

```bash
npm run build     # 生产构建 → dist/
npm run preview   # 本地预览 build 产物
```

---

## 🌐 GitHub Pages 自动部署

仓库内置 **GitHub Actions 工作流**（`.github/workflows/deploy-frontend.yml`）：

- 每次 push 到 `main` 且改动涉及 `frontend/**` 时，自动构建并部署到 Pages
- 也可在 Actions 页面手动触发（Run workflow）
- SPA 回退：构建时复制 `index.html` 为 `404.html`

### ⚠️ 如果你改了仓库名

编辑 `frontend/vite.config.ts`，同步修改：
```ts
const base = mode === 'production' ? '/mustardseed/' : '/'
```
否则部署后资源 404。使用自定义域名则改为 `'/'`。

> 注意：`frontend/vite.config.js` 与 `vite.config.d.ts` 是 tsc 编译产物，已被 .gitignore 排除。
> Vite 加载配置时 `.js` 优先于 `.ts`，请勿把它们提交进仓库，否则会遮蔽 `.ts` 配置。

---

## 🧩 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 框架 | React 18 + TypeScript (strict) | 纯组件化，无重型状态库 |
| 构建 | Vite 5 | HMR 秒开，产物 gzip ≈ 120KB |
| 路由 | react-router v6 · HashRouter | GitHub Pages 天然兼容，深链不 404 |
| 样式 | TailwindCSS 3 + 自定义 mint 色板 | 清新薄荷绿主题贯穿全站 |
| 持久化 | `localStorage` (utils/storage.ts) | 免登录：番茄统计、待办、纠结历史、金句收藏 |
| 音效 | Web Audio API (番茄钟) | 无外部音频文件，C / E / G 三音琶音合成 |
| 构建信息 | Vite define 注入 git 分支/提交/时间 | 「更多」页展示（当前已隐藏，可恢复） |

---

## 📁 目录结构

```
mustardseed/
├─ .github/workflows/deploy-frontend.yml   # Pages 自动部署
├─ .gitignore
├─ README.md
└─ frontend/
   ├─ index.html                     # 标题 / favicon（种子新芽）/ theme-color
   ├─ package.json
   ├─ vite.config.ts                 # base: '/mustardseed/'（生产）+ git 信息注入
   ├─ tailwind.config.js             # mint 色板 + shadow-soft/card
   ├─ tsconfig.json                  # strict + @/* alias
   └─ src/
      ├─ main.tsx                    # HashRouter
      ├─ App.tsx                     # 路由注册（含暂未开放页面的直达路由）
      ├─ index.css                   # 薄荷径向渐变背景 + 动画 keyframes
      ├─ assets/logo.png             # 品牌头像（与小程序共用）
      ├─ types/                      # 环境类型声明（png 导入 / git 全局量）
      ├─ utils/storage.ts
      ├─ data/verses.ts              # 200 条中英对照金句
      ├─ components/
      │   ├─ PageHeader.tsx          # 工具页统一顶部栏（返回箭头）
      │   └─ SiteFooter.tsx          # 底部品牌与版本
      └─ pages/
          ├─ Home.tsx                # 双板块导航（HIDDEN_TOOLS 控制暂隐藏入口）
          ├─ Pomodoro.tsx
          ├─ Todo.tsx
          ├─ Workdays.tsx
          ├─ Picker.tsx
          ├─ Verse.tsx
          ├─ Quiz.tsx                # 暂未开放
          ├─ Music.tsx               # 暂未开放
          └─ More.tsx                # 版本信息 / 建议反馈
```

---

## 🎨 主题设计哲学

- **主色**：薄荷绿 `#1a9464` — 干净、平静、轻松愉快，不刺激视觉疲劳
- **品牌**：🌱 种子新芽 — 最小的种子，长成最大的植物；每一件小事都算数
- **背景**：两处径向光斑 + 白色渐变，既有呼吸感，又保证全页文字可读
- **阴影**：`shadow-soft` 柔和 + `shadow-card` 实体，两套层级拉开深浅
- **动效**：卡片 `hover:scale(1.02)`、按钮 `btn-press scale(0.96)`、抽奖 `shake`、加载 `fade-up` + `popIn`

---

## 📜 License · 声明

- 代码：MIT，欢迎 Fork / Star / PR 💚
- 金句数据：来源于公共版权圣经译本的常用经文，仅供个人激励使用
- 数据：100% 保存在你本地浏览器 localStorage，任何时候不会上传

Made with 💚 · 芥菜种子 v1.0.0
