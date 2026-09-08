import React from 'react'
import { useLocation } from 'react-router-dom'

interface Props {
  onBack?: () => void
  title?: string
  right?: React.ReactNode
}

const titles: Record<string, string> = {
  '/pomodoro': '番茄钟',
  '/todo': '待办清单',
  '/picker': '纠结人神器',
  '/verse': '治愈金句',
  '/music': '音乐小站',
  '/workdays': '工作日计算',
  '/quiz': '趣味小测试',
  '/more': '更多',
  '/reading': '研经日课',
}

const PageHeader: React.FC<Props> = ({ onBack, title, right }) => {
  const loc = useLocation()
  // 支持子路由：取第一段路径匹配标题
  const basePath = '/' + (loc.pathname.split('/')[1] || '')
  const t = title || titles[basePath] || '芥菜种子'

  return (
    <header className="sticky top-0 z-20 -mx-4 sm:-mx-6 px-4 sm:px-6 pt-[max(env(safe-area-inset-top),12px)] pb-3 backdrop-blur-md bg-white/70 border-b border-mint-100/60">
      <div className="flex items-center h-11">
        <button
          onClick={onBack}
          className="btn-press w-10 h-10 -ml-2 rounded-full flex items-center justify-center text-mint-700 hover:bg-mint-50"
          aria-label="返回"
        >
          <svg viewBox="0 0 24 24" fill="none" className="w-6 h-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </button>
        <h1 className="flex-1 text-center text-[17px] font-semibold text-mint-900 tracking-wide">{t}</h1>
        <div className="w-10 flex items-center justify-end">{right}</div>
      </div>
    </header>
  )
}

export default PageHeader
