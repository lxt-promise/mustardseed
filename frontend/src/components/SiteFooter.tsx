import React from 'react'

const SiteFooter: React.FC = () => {
  return (
    <footer className="w-full max-w-[720px] mx-auto py-6 text-center text-xs text-mint-700/70 leading-relaxed">
      <div className="flex items-center justify-center gap-1">
        <svg viewBox="0 0 24 24" fill="#1a9464" className="w-3.5 h-3.5">
          <path d="M17 8C8 10 5.9 16.17 3.82 21.34l1.89.66.95-2.3c.48.17.98.3 1.34.3C19 20 22 3 22 3c-1 2-8 2.25-13 3.25S2 11.5 2 13.5s1.75 3.75 1.75 3.75C7 8 17 8 17 8z" />
        </svg>
        <span>芥菜种子 · 一个治愈又实用的综合工具箱</span>
      </div>
      <div className="mt-1 text-mint-700/50">
        v1.1.0
      </div>
    </footer>
  )
}

export default SiteFooter
