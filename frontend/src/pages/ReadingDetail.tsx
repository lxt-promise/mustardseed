import React, { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { loadArticles, getBibleLink, type StudyArticle } from '@/data/reading'
import { trackEvent } from '@/utils/analytics'

const ReadingDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [articles, setArticles] = useState<StudyArticle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(false)
    // 并行加载两约（有缓存时几乎瞬时），任一失败不影响另一个
    Promise.allSettled([loadArticles('nt'), loadArticles('ot')])
      .then(results => {
        if (!alive) return
        const all: StudyArticle[] = []
        results.forEach(r => {
          if (r.status === 'fulfilled') all.push(...r.value)
        })
        if (all.length === 0) {
          setError(true)
        } else {
          setArticles(all)
        }
        setLoading(false)
      })
    return () => { alive = false }
  }, [id])

  const decodedId = decodeURIComponent(id ?? '')

  const article = useMemo(
    () => articles.find(a => a.id === decodedId),
    [articles, decodedId]
  )

  const { prev, next } = useMemo(() => {
    const idx = articles.findIndex(a => a.id === decodedId)
    return {
      prev: idx > 0 ? articles[idx - 1] : null,
      next: idx >= 0 && idx < articles.length - 1 ? articles[idx + 1] : null,
    }
  }, [articles, decodedId])

  const bibleUrl = getBibleLink(article?.book ?? '', article?.chapter ?? 0, article?.title)

  if (loading) {
    return (
      <div className="text-center py-20 text-mint-600/60">
        <div className="text-4xl mb-3 animate-pulse">📖</div>
        <p className="text-sm mb-1">正在加载…</p>
        <p className="text-xs text-mint-400">首次打开需稍候片刻</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-20">
        <div className="text-4xl mb-3">😵</div>
        <p className="text-sm text-mint-700 mb-4">数据加载失败，请刷新重试</p>
        <button
          onClick={() => window.location.reload()}
          className="btn-press px-5 py-2 rounded-xl bg-mint-600 text-white text-sm font-semibold"
        >
          刷新页面
        </button>
      </div>
    )
  }

  if (!article) {
    return (
      <div className="text-center py-20 text-mint-600/60">
        <div className="text-4xl mb-2">🤔</div>
        <p>未找到该文章</p>
        <Link to="/reading" className="mt-4 inline-block text-mint-600 underline">返回目录</Link>
      </div>
    )
  }

  return (
    <div className="animate-fade-up pb-8">
      {/* 标题区 */}
      <div className="mb-5">
        <div className="text-xs text-mint-500 mb-1.5">
          {article.book} · Study {article.studyNo === 9999 ? '笔记' : article.studyNo}
        </div>
        <h1 className="text-xl font-bold text-mint-900 leading-snug">{article.title}</h1>
        {bibleUrl && (
          <a
            href={bibleUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackEvent('研经日课', '查看圣经原文', article.title)}
            className="btn-press mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-50 border border-sky-200 text-sky-700 text-xs font-semibold hover:bg-sky-100 transition-colors"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
              <path d="M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2v7z" />
              <path d="M14 3h7v7" />
              <path d="M10 14 21 3" />
            </svg>
            查看圣经原文（和合本）
          </a>
        )}
      </div>

      {/* 正文 */}
      <article className="prose-reading">
        {processBlocks(article.paragraphs).map((b, i) => renderBlock(b, i))}
      </article>

      {/* 参考回答 */}
      {article.answer && article.answer.trim() && (
        <section className="mt-8 rounded-2xl bg-amber-50/60 border border-amber-200/60 p-4">
          <h2 className="text-base font-bold text-amber-800 mb-3 flex items-center gap-2">
            <span>💡</span> 参考回答
          </h2>
          <div className="space-y-3">
            {parseAnswer(article.answer).map((item, i) => (
              <div key={i} className="text-sm leading-7">
                {item.question && (
                  <div className="font-semibold text-amber-900/90">{item.question}</div>
                )}
                {item.answer && (
                  <div className="text-mint-800 mt-1 pl-3 border-l-2 border-amber-300">
                    {item.answer}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 原文链接 */}
      <div className="mt-6 text-center">
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => trackEvent('研经日课', '查看原文', article.title)}
          className="text-xs text-mint-500 hover:text-mint-700 underline underline-offset-2"
        >
          🔗 查看原文（yimawusi.net）
        </a>
      </div>

      {/* 上一篇 / 下一篇 */}
      <div className="mt-8 flex items-stretch gap-3">
        {prev ? (
          <button
            onClick={() => { trackEvent('研经日课', '上一篇'); navigate(`/reading/${encodeURIComponent(prev.id)}`) }}
            className="btn-press flex-1 text-left rounded-2xl bg-white border border-mint-100 shadow-card p-3 hover:bg-mint-50/50 transition-colors"
          >
            <div className="text-[11px] text-mint-500 mb-1">← 上一篇</div>
            <div className="text-sm text-mint-800 line-clamp-2 leading-snug">{prev.title}</div>
          </button>
        ) : <div className="flex-1" />}
        {next ? (
          <button
            onClick={() => { trackEvent('研经日课', '下一篇'); navigate(`/reading/${encodeURIComponent(next.id)}`) }}
            className="btn-press flex-1 text-right rounded-2xl bg-white border border-mint-100 shadow-card p-3 hover:bg-mint-50/50 transition-colors"
          >
            <div className="text-[11px] text-mint-500 mb-1">下一篇 →</div>
            <div className="text-sm text-mint-800 line-clamp-2 leading-snug">{next.title}</div>
          </button>
        ) : <div className="flex-1" />}
      </div>

      {/* 返回目录 */}
      <div className="mt-4 text-center">
        <Link
          to="/reading"
          className="btn-press inline-flex items-center gap-1.5 px-5 py-2.5 rounded-xl bg-mint-50 border border-mint-200 text-mint-700 text-sm font-semibold"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
            <line x1="19" y1="12" x2="5" y2="12" />
            <polyline points="12 19 5 12 12 5" />
          </svg>
          返回目录
        </Link>
      </div>
    </div>
  )
}

/** 段落块类型 */
type Block =
  | { type: 'subtitle'; text: string }
  | { type: 'section-header'; text: string; kind: 'questions' | 'notes' | 'commentary' | 'generic' }
  | { type: 'question'; num: string; text: string }
  | { type: 'note'; num: string; text: string }
  | { type: 'commentary'; text: string }
  | { type: 'verse-ref'; ref: string; text: string }
  | { type: 'paragraph'; text: string }

/** 将扁平段落列表处理成带语义的块（过滤垃圾、分区识别） */
function processBlocks(paras: { tag: string; text: string }[]): Block[] {
  const blocks: Block[] = []
  let section: 'intro' | 'questions' | 'notes' | 'commentary' = 'intro'
  let isFirstHeading = true

  for (const p of paras) {
    const text = p.text
    const trimmed = text.trim()

    // 过滤社交分享垃圾 div
    if (p.tag === 'div' && /Share this|Share on|Like Loading|Related/.test(text)) continue

    // 标题
    if (p.tag === 'h1' || p.tag === 'h2') {
      if (isFirstHeading) {
        isFirstHeading = false
        // 首段 h2 通常是英文标题，作为副标题
        blocks.push({ type: 'subtitle', text })
      } else {
        blocks.push({ type: 'section-header', text, kind: 'generic' })
      }
      continue
    }
    if (p.tag === 'h3' || p.tag === 'h4' || p.tag === 'h5' || p.tag === 'h6') {
      blocks.push({ type: 'section-header', text, kind: 'generic' })
      continue
    }

    // figure → 经文注释/补充说明块
    if (p.tag === 'figure') {
      const m = trimmed.match(/^(\d+:\d[\d~\-–]*)\s+(.+)$/)
      if (m) {
        blocks.push({ type: 'verse-ref', ref: m[1], text: m[2] })
      } else {
        blocks.push({ type: 'commentary', text })
      }
      continue
    }

    if (p.tag === 'blockquote') {
      blocks.push({ type: 'commentary', text })
      continue
    }

    // 分区标题识别
    if (/^研经题目[:：]?\s*$/.test(trimmed)) {
      section = 'questions'
      blocks.push({ type: 'section-header', text, kind: 'questions' })
      continue
    }
    if (/^注[:：]?\s*$/.test(trimmed)) {
      section = 'notes'
      blocks.push({ type: 'section-header', text, kind: 'notes' })
      continue
    }
    if (/^【.+】/.test(trimmed)) {
      if (/经文注释/.test(trimmed)) section = 'commentary'
      blocks.push({ type: 'section-header', text, kind: /经文注释/.test(trimmed) ? 'commentary' : 'generic' })
      continue
    }

    // 编号项：1. / (1) / 一、 等
    const numMatch = trimmed.match(/^(\d+)\.\s+(.+)$/)
    if (numMatch) {
      if (section === 'questions') {
        blocks.push({ type: 'question', num: numMatch[1], text: numMatch[2] })
        continue
      }
      if (section === 'notes') {
        blocks.push({ type: 'note', num: numMatch[1], text: numMatch[2] })
        continue
      }
    }

    // 经文章节引用开头：1:1-17 / 1:1~2:23
    const verseMatch = trimmed.match(/^(\d+:\d[\d~\-–]*)\s+(.+)$/)
    if (verseMatch) {
      blocks.push({ type: 'verse-ref', ref: verseMatch[1], text: verseMatch[2] })
      continue
    }

    // 普通段落
    if (trimmed) {
      blocks.push({ type: 'paragraph', text })
    }
  }

  return blocks
}

/** 渲染单个内容块 */
function renderBlock(b: Block, i: number) {
  switch (b.type) {
    case 'subtitle':
      return <p key={i} className="mt-1 mb-5 text-sm text-mint-500 italic">{b.text}</p>

    case 'section-header': {
      const styles: Record<string, string> = {
        questions: 'text-mint-600',
        notes: 'text-slate-600',
        commentary: 'text-sky-700',
        generic: 'text-mint-800',
      }
      const icon: Record<string, string> = {
        questions: '❓',
        notes: '📝',
        commentary: '📖',
        generic: '📌',
      }
      return (
        <h3 key={i} className={`mt-6 mb-3 flex items-center gap-2 text-base font-bold ${styles[b.kind]}`}>
          <span>{icon[b.kind]}</span>{b.text}
        </h3>
      )
    }

    case 'question':
      return (
        <div key={i} className="my-2.5 flex gap-2.5 rounded-xl bg-mint-50/70 border border-mint-100 p-3">
          <span className="flex-shrink-0 w-6 h-6 rounded-full bg-mint-500 text-white text-xs font-bold flex items-center justify-center leading-none mt-0.5">
            {b.num}
          </span>
          <p className="text-sm leading-7 text-mint-900 font-medium">{b.text}</p>
        </div>
      )

    case 'note':
      return (
        <div key={i} className="my-2 flex gap-2.5 pl-1">
          <span className="flex-shrink-0 w-5 h-5 rounded-md bg-slate-400/80 text-white text-[11px] font-bold flex items-center justify-center leading-none mt-1">
            {b.num}
          </span>
          <p className="text-sm leading-7 text-slate-700">{b.text}</p>
        </div>
      )

    case 'commentary':
      return (
        <div key={i} className="my-3 rounded-xl border-l-4 border-sky-300 bg-sky-50/50 p-3 text-sm leading-7 text-slate-700">
          {b.text}
        </div>
      )

    case 'verse-ref':
      return (
        <div key={i} className="my-2.5 rounded-xl border-l-4 border-sky-300 bg-sky-50/40 p-3 text-sm leading-7 text-slate-700">
          <span className="font-bold text-sky-700 mr-1.5">{b.ref}</span>
          {b.text}
        </div>
      )

    case 'paragraph':
    default:
      return <p key={i} className="my-2.5 text-sm leading-7 text-mint-800">{b.text}</p>
  }
}

/**
 * 解析参考回答文本，拆成题目+答案对
 * 格式示例：
 *   1. 题目...
 *   答：答案...
 *   2. 题目...
 *   答：答案...
 */
function parseAnswer(text: string): { question: string; answer: string }[] {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean)
  const result: { question: string; answer: string }[] = []
  let currentQ = ''
  let currentA = ''

  for (const line of lines) {
    if (/^\d+\./.test(line) && !line.startsWith('答：')) {
      // 新的题目：先保存上一组
      if (currentQ || currentA) {
        result.push({ question: currentQ, answer: currentA })
      }
      currentQ = line
      currentA = ''
    } else if (line.startsWith('答：') || line.startsWith('答:')) {
      currentA = line.replace(/^答[：:]\s*/, '')
    } else if (currentA) {
      // 答案的续行
      currentA += ' ' + line
    } else if (currentQ) {
      // 题目的续行
      currentQ += ' ' + line
    }
  }
  if (currentQ || currentA) {
    result.push({ question: currentQ, answer: currentA })
  }
  return result
}

export default ReadingDetail
