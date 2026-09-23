import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App'
import { initAnalytics } from './utils/analytics'
import { initDubConfig } from './api/dub'
import { initMeetingConfig } from './api/meeting'
import { prewarmReadingIndex } from './data/reading'
import './index.css'

initAnalytics()

// 先加载运行时配置（如视频译制服务地址），再挂载应用；
// 配置文件缺失/超时时 initXxx 内部会静默回退默认值，不阻塞渲染。
Promise.all([initDubConfig(), initMeetingConfig()]).finally(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <HashRouter>
        <App />
      </HashRouter>
    </React.StrictMode>,
  )
  // 首屏渲染后空闲预热研经日课目录索引（约 160KB），进入模块即秒开
  prewarmReadingIndex()
})
