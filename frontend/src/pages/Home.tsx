import { Link } from 'react-router-dom'
import React from 'react'
import logoImg from '@/assets/logo.png'
import { trackEvent } from '@/utils/analytics'

type Tool = {
  to: string
  icon: React.ReactNode
  name: string
  desc: string
  color: string
  badge?: string
}

const officeTools: Tool[] = [
  {
    to: '/pomodoro',
    name: '番茄钟',
    desc: '专注 25 分钟，休息 5 分钟',
    color: 'from-rose-400 to-orange-400',
    badge: '🔥 首发',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-8 h-8 text-white">
        <circle cx="12" cy="13" r="8" />
        <path d="M12 9v4l2 2M9 2h6M19 5l1.5-1.5M5 5 3.5 3.5" />
      </svg>
    ),
  },
  {
    to: '/todo',
    name: '待办清单',
    desc: '专注搞定今天的事',
    color: 'from-mint-500 to-teal-500',
    badge: '✅ 推荐',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-8 h-8 text-white">
        <path d="M9 11l3 3L22 4" />
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
      </svg>
    ),
  },
  {
    to: '/workdays',
    name: '工作日计算',
    desc: '算区间工作日 / N 个工作日后是哪天',
    color: 'from-indigo-400 to-mint-500',
    badge: '🆕 新上',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-8 h-8 text-white">
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M3 10h18M8 3v4M16 3v4" />
        <path d="M8 14l2 2 4-4" />
      </svg>
    ),
  },
]

const funTools: Tool[] = [
  {
    to: '/verse',
    name: '治愈金句',
    desc: 'pick你喜欢的，给心灵放个假',
    color: 'from-indigo-400 to-violet-500',
    badge: '✨ 首发',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-8 h-8 text-white">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        <path d="M9 7h7M9 11h7M9 15h4" />
      </svg>
    ),
  },
  {
    to: '/picker',
    name: '纠结人神器',
    desc: '吃啥？选啥？一键帮你决定',
    color: 'from-amber-400 to-pink-500',
    badge: '🎯 首发',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-8 h-8 text-white">
        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
        <circle cx="12" cy="12" r="3.5" />
      </svg>
    ),
  },
  {
    to: '/music',
    name: '音乐小站',
    desc: '钢琴曲 / 白噪音 · 真实可播放',
    color: 'from-cyan-400 to-mint-500',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-8 h-8 text-white">
        <path d="M9 18V5l12-2v13" />
        <circle cx="6" cy="18" r="3" />
        <circle cx="18" cy="16" r="3" />
      </svg>
    ),
  },
  {
    to: '/quiz',
    name: '趣味小测试',
    desc: '颜色性格 / 笑话 / 人生锦囊',
    color: 'from-fuchsia-400 to-indigo-500',
    badge: '🆕 新上',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-8 h-8 text-white">
        <circle cx="12" cy="12" r="9" />
        <path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01" />
      </svg>
    ),
  },
  {
    to: '/reading',
    name: '研经日课',
    desc: '新约27卷 · 逐课研读经文',
    color: 'from-emerald-400 to-mint-600',
    badge: '📖 新上',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-8 h-8 text-white">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
        <path d="M9 7h7M9 11h7M9 15h4" />
      </svg>
    ),
  },
  {
    to: '/more',
    name: '更多',
    desc: '版本信息 / 建议反馈',
    color: 'from-mint-400 to-emerald-600',
    badge: '🌱 全',
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" stroke="none" className="w-8 h-8 text-white">
        <path d="M7 10.2c1.1 0 1.8.9 1.8 1.8s-.7 1.8-1.8 1.8-1.8-.9-1.8-1.8.7-1.8 1.8-1.8z" />
        <path d="M12 9c1.1 0 1.8.9 1.8 1.8v2.4c0 .9-.7 1.8-1.8 1.8s-1.8-.9-1.8-1.8v-2.4c0-.9.7-1.8 1.8-1.8z" />
        <path d="M17 10.2c1.1 0 1.8.9 1.8 1.8s-.7 1.8-1.8 1.8-1.8-.9-1.8-1.8.7-1.8 1.8-1.8z" />
      </svg>
    ),
  },
]

// 暂时隐藏的工具入口（恢复时清空数组即可）
const HIDDEN_TOOLS: string[] = ['/music', '/quiz']
const funToolsVisible = funTools.filter((t) => !HIDDEN_TOOLS.includes(t.to))

const ToolCard: React.FC<{ tool: Tool }> = ({ tool }) => {
  const isDisabled = tool.to === '#'
  const Wrapper: any = isDisabled ? 'div' : Link
  const wrapperProps = isDisabled ? {} : { to: tool.to }

  return (
    <Wrapper
      {...wrapperProps}
      onClick={() => { if (!isDisabled) trackEvent('工具入口', '点击', tool.name) }}
      className={`card-hover group relative block rounded-2xl overflow-hidden shadow-card bg-white border border-mint-100/70 ${isDisabled ? 'opacity-75 cursor-not-allowed' : ''}`}
    >
      <div className={`h-24 bg-gradient-to-br ${tool.color} relative flex items-end p-4 overflow-hidden`}>
        <div className="absolute -right-4 -top-6 w-28 h-28 rounded-full bg-white/15" />
        <div className="absolute right-8 top-1 w-14 h-14 rounded-full bg-white/10" />
        <div className="relative drop-shadow-sm">{tool.icon}</div>
        {tool.badge && (
          <span className="absolute top-3 right-3 text-[10px] bg-white/90 text-mint-700 font-semibold px-2 py-0.5 rounded-full shadow-sm">
            {tool.badge}
          </span>
        )}
      </div>
      <div className="p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-mint-900">{tool.name}</h3>
          {!isDisabled && (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 text-mint-400 group-hover:text-mint-600 group-hover:translate-x-0.5 transition-all">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          )}
        </div>
        <p className="mt-1 text-xs text-mint-700/70 leading-relaxed line-clamp-2">{tool.desc}</p>
      </div>
    </Wrapper>
  )
}

const Home: React.FC = () => {
  // 根据时间段与是否周末生成问候语
  const greeting = (() => {
    const now = new Date()
    const hour = now.getHours()
    const isWeekend = now.getDay() === 0 // 仅周日算周末
    if (hour < 6)  return isWeekend ? '凌晨好，周末愉快呀' : '凌晨好，早点休息呀'
    if (hour < 10) return isWeekend ? '早上好，周末愉快呀' : '早上好，今天也要开心呀'
    if (hour < 12) return isWeekend ? '早上好，周末愉快呀' : '早上好，元气满满呀'
    if (hour < 14) return isWeekend ? '中午好，周末愉快呀' : '中午好，记得吃饭呀'
    if (hour < 18) return isWeekend ? '下午好，周末愉快呀' : '下午好，记得喝杯水呀'
    if (hour < 22) return isWeekend ? '晚上好，周末愉快呀' : '晚上好，今天也要开心呀'
    return '夜深了，早点休息呀'
  })()

  return (
    <div className="animate-fade-up">
      {/* Hero */}
      <section className="mb-8">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm text-mint-700/70">{greeting}</p>
            <h1 className="mt-1 inline-flex items-center text-3xl sm:text-4xl font-bold text-mint-900 tracking-tight">
              芥菜种子 <span className="ml-1 text-2xl sm:text-3xl leading-none">🌱</span>
            </h1>
            <p className="mt-2 text-sm text-mint-800/80 max-w-md">
              办公工具箱 + 休闲小玩意儿，一个页面搞定你的摸鱼与专注。最小的种子，也能长成大树。
            </p>
          </div>
          <img src={logoImg} alt="芥菜种子" className="hidden sm:block w-20 h-20 rounded-3xl shadow-soft shrink-0" />
        </div>
      </section>

      {/* 办公工具箱 */}
      <section className="mb-8">
        <div className="flex items-end justify-between mb-4">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-mint-100 text-mint-700 text-xs font-semibold">
              💼 办公工具箱
            </div>
            <h2 className="mt-2 text-xl font-bold text-mint-900">生产力小帮手</h2>
          </div>
          <span className="text-xs text-mint-700/60">共 {officeTools.length} 个</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 sm:gap-4">
          {officeTools.map((t) => (
            <ToolCard key={t.name} tool={t} />
          ))}
        </div>
      </section>

      {/* 休闲娱乐 */}
      <section>
        <div className="flex items-end justify-between mb-4">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-pink-100 text-pink-600 text-xs font-semibold">
              🎈 休闲娱乐
            </div>
            <h2 className="mt-2 text-xl font-bold text-mint-900">让生活可爱一点</h2>
          </div>
          <span className="text-xs text-mint-700/60">共 {funToolsVisible.length} 个</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 sm:gap-4">
          {funToolsVisible.map((t) => (
            <ToolCard key={t.name} tool={t} />
          ))}
        </div>
      </section>
    </div>
  )
}

export default Home
