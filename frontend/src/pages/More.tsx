import React from 'react'
import { Link } from 'react-router-dom'
import logoImg from '@/assets/logo.png'
import { trackEvent } from '@/utils/analytics'

const REPO_URL = 'https://github.com/lxt-promise/mustardseed'
const ISSUES_URL = `${REPO_URL}/issues`
const APP_VERSION = 'v1.0.0'

const TOOLS = [
  { to: '/pomodoro', icon: '🍅', name: '番茄钟', desc: '专注计时 · 三种模式' },
  { to: '/todo', icon: '✅', name: '待办清单', desc: '专注搞定今天的事' },
  { to: '/workdays', icon: '📅', name: '工作日计算', desc: '双休 / 单休 / 大小周' },
  // 暂时下线纠结人模块（恢复时取消注释即可）
  // { to: '/picker', icon: '🎯', name: '纠结人神器', desc: '吃啥？选啥？帮你决定' },
  { to: '/music', icon: '🎵', name: '音乐小站', desc: '钢琴曲 / 白噪音' },
  { to: '/quiz', icon: '🧠', name: '趣味小测试', desc: '性格 / 笑话 / 锦囊' },
  { to: '/verse', icon: '✨', name: '治愈金句', desc: '中英对照 · 200 条' },
]

const Row: React.FC<{ label: string; value: string; mono?: boolean; first?: boolean }> = ({ label, value, mono, first }) => (
  <div className={`flex items-center justify-between py-2.5 ${first ? '' : 'border-t border-mint-50'}`}>
    <span className="text-sm text-mint-700/80">{label}</span>
    <span className={`text-sm text-mint-900 font-medium ${mono ? 'font-mono' : ''}`}>{value}</span>
  </div>
)

const More: React.FC = () => {
  return (
    <div className="animate-fade-up">
      {/* 品牌头部 */}
      <section className="flex items-center gap-4 mb-6">
        <img src={logoImg} alt="芥菜种子" className="w-16 h-16 rounded-2xl shadow-soft" />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-mint-900 tracking-tight">芥菜种子</h1>
            <span className="text-[10px] bg-mint-100 text-mint-700 font-semibold px-2 py-0.5 rounded-full">
              {APP_VERSION}
            </span>
          </div>
          <p className="mt-1 text-xs text-mint-800/70">办公工具箱 + 休闲小玩意儿</p>
        </div>
      </section>

      {/* 版本信息 */}
      <section className="rounded-2xl bg-white/80 border border-mint-100 shadow-card px-4 py-2 mb-4">
        <p className="text-sm font-semibold text-mint-800 pt-2">📌 版本信息</p>
        <Row label="当前版本" value={APP_VERSION} mono first />
        <Row label="平台" value="网页版" />
        <Row label="名称" value="芥菜种子 · MustardSeed" />
        <Link
          to="/"
          className="inline-block pb-1 pt-0.5 text-xs text-mint-600 underline hover:text-mint-800"
        >
          返回首页
        </Link>
      </section>

      {/* 暂时隐藏：全部工具目录（恢复时取消注释）
      <section className="mb-4">
        <p className="text-sm font-semibold text-mint-800 mb-2 px-1">🧰 全部工具</p>
        <div className="rounded-2xl bg-white/80 border border-mint-100 shadow-card overflow-hidden">
          {TOOLS.map((t, i) => (
            <Link
              key={t.to}
              to={t.to}
              className={`flex items-center gap-3 px-4 py-3 hover:bg-mint-50/60 transition-colors ${i > 0 ? 'border-t border-mint-50' : ''}`}
            >
              <span className="w-10 h-10 rounded-xl bg-mint-50 border border-mint-100 flex items-center justify-center text-xl leading-none">
                {t.icon}
              </span>
              <span className="flex-1 min-w-0">
                <span className="block text-sm font-semibold text-mint-900">{t.name}</span>
                <span className="block text-[11px] text-mint-700/60 mt-0.5">{t.desc}</span>
              </span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 text-mint-300">
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </Link>
          ))}
        </div>
      </section>
      */}

      {/* 建议反馈 */}
      <section className="rounded-2xl bg-white/80 border border-mint-100 shadow-card p-4 mb-6">
        <p className="text-sm font-semibold text-mint-800">💬 建议与反馈</p>
        <p className="mt-1 text-xs text-mint-700/60 leading-5">
          用过程中发现任何问题，或想聊聊「下一粒种子种什么」，都欢迎来 GitHub 告诉我们：
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            href={ISSUES_URL}
            target="_blank"
            rel="noreferrer noopener"
            onClick={() => trackEvent('建议反馈', '点击', '去提 Issue')}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-mint-500 to-mint-600 shadow-soft text-white text-sm font-semibold hover:opacity-90 transition-opacity"
          >
            📝 去提 Issue
          </a>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer noopener"
            onClick={() => trackEvent('建议反馈', '点击', 'GitHub 仓库')}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-white border border-mint-200 text-mint-700 text-sm font-semibold hover:bg-mint-50 transition-colors"
          >
            ⭐ GitHub 仓库
          </a>
        </div>
      </section>
    </div>
  )
}

export default More
