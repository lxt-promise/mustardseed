import React, { Suspense, lazy } from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useRef } from 'react'
import { initAnalytics } from './utils/analytics'
import { initDubConfig } from './api/dub'
import { initMeetingConfig } from './api/meeting'
import './index.css'

// 首页同步加载（首屏即用），其余页面懒加载减小初始 bundle
import Home from './pages/Home'
import PageHeader from './components/PageHeader'
import SiteFooter from './components/SiteFooter'
import ScrollToTop from './components/ScrollToTop'
import { trackPageview } from './utils/analytics'

const Pomodoro = lazy(() => import('./pages/Pomodoro'))
const Todo = lazy(() => import('./pages/Todo'))
const Picker = lazy(() => import('./pages/Picker'))
const Verse = lazy(() => import('./pages/Verse'))
const Music = lazy(() => import('./pages/Music'))
const Workdays = lazy(() => import('./pages/Workdays'))
const Quiz = lazy(() => import('./pages/Quiz'))
const More = lazy(() => import('./pages/More'))
const Reading = lazy(() => import('./pages/Reading'))
const ReadingDetail = lazy(() => import('./pages/ReadingDetail'))
const Dub = lazy(() => import('./pages/Dub'))
const Meeting = lazy(() => import('./pages/Meeting'))
const Works = lazy(() => import('./pages/Works'))

initAnalytics()

// 异步预热研经日课索引（不阻塞首屏）
function prewarmReading() {
  import('./data/reading').then(({ prewarmReadingIndex }) => prewarmReadingIndex())
}

function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const isHome = location.pathname === '/' || location.pathname === ''
  const firstRender = useRef(true)
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return }
    trackPageview(location.pathname)
  }, [location.pathname])

  return (
    <div className="min-h-screen w-full flex flex-col">
      <ScrollToTop />
      <div className="w-full max-w-[720px] mx-auto flex-1 flex flex-col px-4 sm:px-6">
        {!isHome ? <PageHeader onBack={() => navigate(-1)} /> : null}
        <main className={`flex-1 w-full ${isHome ? 'pt-6 sm:pt-10 pb-12' : 'pb-16'}`}>
          <Suspense fallback={<div className="py-20 text-center text-sm text-mint-700/60">加载中…</div>}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/pomodoro" element={<Pomodoro />} />
              <Route path="/todo" element={<Todo />} />
              <Route path="/picker" element={<Picker />} />
              <Route path="/verse" element={<Verse />} />
              <Route path="/music" element={<Music />} />
              <Route path="/workdays" element={<Workdays />} />
              <Route path="/quiz" element={<Quiz />} />
              <Route path="/more" element={<More />} />
              <Route path="/reading" element={<Reading />} />
              <Route path="/reading/:id" element={<ReadingDetail />} />
              <Route path="/dub" element={<Dub />} />
              <Route path="/meeting" element={<Meeting />} />
              <Route path="/works" element={<Works />} />
            </Routes>
          </Suspense>
        </main>
        <SiteFooter />
      </div>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>,
)

// 挂载后再异步加载配置和预热索引
initDubConfig()
initMeetingConfig()
prewarmReading()
