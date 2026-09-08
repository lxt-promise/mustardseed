import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getBooks, loadArticles, OT_BOOKS, NT_BOOKS, type StudyArticle, type Testament } from '@/data/reading'
import { trackEvent } from '@/utils/analytics'

interface ChapterGroup {
  chapter: number
  articles: StudyArticle[]
}

interface BookGroup {
  name: string
  order: number
  chapters: ChapterGroup[]
  totalArticles: number
}

const Reading: React.FC = () => {
  const navigate = useNavigate()
  const [testament, setTestament] = useState<Testament>('nt')
  const [articles, setArticles] = useState<StudyArticle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedBooks, setExpandedBooks] = useState<Set<number>>(new Set())

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    loadArticles(testament)
      .then(data => {
        if (alive) {
          setArticles(data)
          setLoading(false)
        }
      })
      .catch(err => {
        if (alive) {
          console.error('加载读经数据失败:', err)
          setError('数据加载失败，请刷新重试')
          setLoading(false)
        }
      })
    return () => { alive = false }
  }, [testament])

  // 空闲时预加载另一约数据，消除切换等待
  useEffect(() => {
    const other: Testament = testament === 'nt' ? 'ot' : 'nt'
    const preload = () => { loadArticles(other).catch(() => {}) }
    const ric = window.requestIdleCallback?.bind(window)
    if (ric) ric(preload, { timeout: 3000 })
    else setTimeout(preload, 1500)
  }, [testament])

  const books = useMemo<BookGroup[]>(() => {
    const bookMap = new Map<number, Map<number, StudyArticle[]>>()
    for (const a of articles) {
      if (!bookMap.has(a.bookOrder)) bookMap.set(a.bookOrder, new Map())
      const chMap = bookMap.get(a.bookOrder)!
      if (!chMap.has(a.chapter)) chMap.set(a.chapter, [])
      chMap.get(a.chapter)!.push(a)
    }
    return getBooks(testament).map(b => {
      const chMap = bookMap.get(b.order)
      if (!chMap) return null
      const chapters: ChapterGroup[] = []
      for (const [ch, list] of chMap) {
        chapters.push({ chapter: ch, articles: list })
      }
      chapters.sort((a, b) => (a.chapter === 0 ? 9999 : a.chapter) - (b.chapter === 0 ? 9999 : b.chapter))
      return {
        name: b.name,
        order: b.order,
        chapters,
        totalArticles: chapters.reduce((s, c) => s + c.articles.length, 0),
      }
    }).filter(Boolean) as BookGroup[]
  }, [articles, testament])

  function toggleBook(order: number) {
    setExpandedBooks(prev => {
      const next = new Set(prev)
      if (next.has(order)) next.delete(order)
      else next.add(order)
      return next
    })
  }

  function openArticle(article: StudyArticle) {
    trackEvent('研经日课', '打开文章', article.title)
    navigate(`/reading/${encodeURIComponent(article.id)}`)
  }

  function switchTestament(t: Testament) {
    setTestament(t)
    setExpandedBooks(new Set())
    trackEvent('研经日课', '切换约', t === 'ot' ? '旧约' : '新约')
  }

  if (loading) {
    return (
      <div className="text-center py-20 text-mint-600/60">
        <div className="text-4xl mb-3 animate-pulse">📖</div>
        <p className="text-sm mb-1">正在加载{testament === 'ot' ? '旧约' : '新约'}数据…</p>
        <p className="text-xs text-mint-400">首次加载需稍候片刻</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-20">
        <div className="text-4xl mb-3">😵</div>
        <p className="text-sm text-mint-700 mb-4">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="btn-press px-5 py-2 rounded-xl bg-mint-600 text-white text-sm font-semibold"
        >
          刷新页面
        </button>
      </div>
    )
  }

  return (
    <div className="animate-fade-up">
      {/* 头部说明 */}
      <div className="mb-5 rounded-2xl bg-gradient-to-br from-mint-50 to-white border border-mint-100 p-4 shadow-card">
        <div className="flex items-center gap-2">
          <span className="text-2xl">📖</span>
          <div>
            <h2 className="text-lg font-bold text-mint-900">研经日课</h2>
            <p className="text-xs text-mint-700/70 mt-0.5">
              旧约 {OT_BOOKS.length} 卷 · 新约 {NT_BOOKS.length} 卷 · 按圣经章节顺序排列
            </p>
          </div>
        </div>
      </div>

      {/* 新约/旧约 切换 */}
      <div className="mb-5 flex gap-2">
        <button
          onClick={() => switchTestament('ot')}
          className={`btn-press flex-1 py-2.5 rounded-xl text-sm font-semibold border transition-all ${
            testament === 'ot'
              ? 'bg-mint-600 text-white border-mint-600 shadow-sm'
              : 'bg-white text-mint-700 border-mint-100 hover:bg-mint-50'
          }`}
        >
          旧约 · 39 卷
        </button>
        <button
          onClick={() => switchTestament('nt')}
          className={`btn-press flex-1 py-2.5 rounded-xl text-sm font-semibold border transition-all ${
            testament === 'nt'
              ? 'bg-mint-600 text-white border-mint-600 shadow-sm'
              : 'bg-white text-mint-700 border-mint-100 hover:bg-mint-50'
          }`}
        >
          新约 · 27 卷
        </button>
      </div>

      {/* 书卷列表 */}
      <div className="space-y-3">
        {books.map(book => {
          const isOpen = expandedBooks.has(book.order)
          return (
            <div
              key={book.order}
              className="rounded-2xl bg-white border border-mint-100 shadow-card overflow-hidden"
            >
              <button
                onClick={() => toggleBook(book.order)}
                className="btn-press w-full flex items-center justify-between px-4 py-3.5 text-left hover:bg-mint-50/50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="w-8 h-8 rounded-full bg-mint-100 text-mint-700 text-xs font-bold flex items-center justify-center shrink-0">
                    {book.order}
                  </span>
                  <div>
                    <div className="font-semibold text-mint-900">{book.name}</div>
                    <div className="text-xs text-mint-600/70">
                      {book.chapters.length} 章 · {book.totalArticles} 课
                    </div>
                  </div>
                </div>
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className={`w-5 h-5 text-mint-400 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>

              {isOpen && (
                <div className="border-t border-mint-100/60">
                  {book.chapters.map(ch => (
                    <div key={ch.chapter} className="border-b border-mint-50 last:border-b-0">
                      <div className="px-4 py-2 bg-mint-50/40 flex items-center gap-2">
                        <span className="text-xs font-bold text-mint-600">
                          {ch.chapter === 0
                            ? (ch.articles.every(a => /复习/.test(a.title)) ? '复习'
                              : ch.articles.every(a => a.studyNo === 9999) ? '研读笔记'
                              : '补充 / 笔记')
                            : `第 ${ch.chapter} 章`}
                        </span>
                        <span className="text-[11px] text-mint-500">· {ch.articles.length} 课</span>
                      </div>
                      <div className="divide-y divide-mint-50">
                        {ch.articles.map(article => (
                          <button
                            key={article.id}
                            onClick={() => openArticle(article)}
                            className="btn-press w-full text-left px-4 py-2.5 hover:bg-mint-50/50 transition-colors flex items-center gap-3"
                          >
                            <span className="w-6 h-6 rounded-md bg-mint-50 text-mint-600 text-[11px] font-semibold flex items-center justify-center shrink-0">
                              {article.studyNo === 9999 ? '📝' : article.studyNo}
                            </span>
                            <span className="text-sm text-mint-800 leading-snug line-clamp-2 flex-1">
                              {article.title}
                            </span>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 text-mint-300 shrink-0">
                              <polyline points="9 18 15 12 9 6" />
                            </svg>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default Reading
