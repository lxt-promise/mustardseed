/**
 * 作品库：展示已发布到 GitHub Releases 的配音成片。
 *
 * 数据源是随 GitHub Pages 一起发布的 works.json（public/works/works.json），
 * 视频直链是 github.com/.../releases/download/...，支持浏览器原生流式播放与下载，
 * 访客无需启动任何本地服务。
 */
import React, { useEffect, useMemo, useState } from 'react'

export interface Work {
  id: string
  title: string
  note?: string
  video: string
  poster?: string
  duration?: number
  size?: number
  published_at?: number
}

function fmtDuration(sec?: number): string {
  if (!sec || sec <= 0) return ''
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function fmtSize(bytes?: number): string {
  if (!bytes) return ''
  const mb = bytes / 1024 / 1024
  if (mb < 1024) return `${mb.toFixed(1)} MB`
  return `${(mb / 1024).toFixed(2)} GB`
}

function fmtDate(ts?: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${(d.getMonth() + 1).toString().padStart(2, '0')}-${d
    .getDate()
    .toString()
    .padStart(2, '0')}`
}

async function loadWorks(): Promise<Work[]> {
  const res = await fetch(`${import.meta.env.BASE_URL}works/works.json?t=${Date.now()}`, {
    cache: 'no-store',
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  const works = Array.isArray(data?.works) ? (data.works as Work[]) : []
  return works.filter(w => w && w.video)
}

const Works: React.FC = () => {
  const [works, setWorks] = useState<Work[] | null>(null)
  const [error, setError] = useState('')
  const [active, setActive] = useState<Work | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let alive = true
    loadWorks()
      .then(list => alive && setWorks(list))
      .catch(err => alive && setError(err?.message || '加载失败'))
    return () => {
      alive = false
    }
  }, [])

  // 弹窗打开时锁滚动；Esc 关闭
  useEffect(() => {
    if (!active) return
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setActive(null)
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', onKey)
    }
  }, [active])

  const activeSize = useMemo(() => fmtSize(active?.size), [active])

  const copyLink = async () => {
    if (!active) return
    try {
      await navigator.clipboard.writeText(active.video)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // 非 https / 旧浏览器无剪贴板权限，忽略
    }
  }

  return (
    <div className="animate-fade-up">
      {/* 标题区 */}
      <section className="mb-6">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-mint-100 text-mint-700 text-xs font-semibold">
          🎬 作品库
        </div>
        <h1 className="mt-2 text-2xl font-bold text-mint-900">中文配音作品集</h1>
        <p className="mt-1 text-sm text-mint-700/70">
          在线直接播放，也可以下载到本地慢慢看。
        </p>
      </section>

      {/* 加载 / 异常 / 空态 */}
      {works === null && !error && (
        <div className="py-20 text-center text-sm text-mint-700/60">正在加载作品…</div>
      )}
      {error && (
        <div className="py-20 text-center text-sm text-mint-700/60">
          作品清单加载失败，稍后再试吧～
        </div>
      )}
      {works && works.length === 0 && (
        <div className="py-20 text-center">
          <div className="text-5xl mb-3">🌱</div>
          <p className="text-sm text-mint-700/70">还没有发布作品</p>
          <p className="mt-1 text-xs text-mint-700/50">
            在「视频译制」里完成配音后，点「发布到作品库」即可
          </p>
        </div>
      )}

      {/* 作品网格 */}
      {works && works.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {works.map(w => (
            <button
              key={w.id}
              onClick={() => setActive(w)}
              className="text-left card-hover rounded-2xl overflow-hidden bg-white border border-mint-100/70 shadow-card group"
            >
              <div className="relative aspect-video bg-stone-100 overflow-hidden">
                {w.poster ? (
                  <img
                    src={w.poster}
                    alt={w.title}
                    loading="lazy"
                    className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-300"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-4xl bg-gradient-to-br from-sky-100 to-mint-100">
                    🎬
                  </div>
                )}
                {w.duration ? (
                  <span className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded-md bg-black/65 text-white text-[11px] font-medium">
                    {fmtDuration(w.duration)}
                  </span>
                ) : null}
                <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/20 transition-colors">
                  <span className="w-12 h-12 rounded-full bg-white/90 text-mint-700 flex items-center justify-center text-xl opacity-0 group-hover:opacity-100 transition-opacity shadow-lg">
                    ▶
                  </span>
                </div>
              </div>
              <div className="p-3">
                <h3 className="text-sm font-semibold text-mint-900 truncate">{w.title}</h3>
                {w.note ? (
                  <p className="mt-0.5 text-xs text-mint-700/60 line-clamp-2 leading-relaxed">
                    {w.note}
                  </p>
                ) : null}
                <div className="mt-1.5 flex items-center gap-2 text-[11px] text-mint-700/50">
                  {w.published_at ? <span>{fmtDate(w.published_at)}</span> : null}
                  {w.size ? <span>· {fmtSize(w.size)}</span> : null}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* 播放弹窗 */}
      {active && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-3 sm:p-6"
          onClick={() => setActive(null)}
        >
          <div
            className="w-full max-w-3xl rounded-2xl bg-white overflow-hidden shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <video
              key={active.id}
              src={active.video}
              poster={active.poster}
              controls
              autoPlay
              playsInline
              className="w-full max-h-[65vh] bg-black"
            />
            <div className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="font-semibold text-mint-900 truncate">{active.title}</h3>
                  <p className="mt-0.5 text-xs text-mint-700/60">
                    {[fmtDuration(active.duration), activeSize, fmtDate(active.published_at)]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                  {active.note ? (
                    <p className="mt-2 text-sm text-mint-800/80 leading-relaxed">{active.note}</p>
                  ) : null}
                </div>
                <button
                  onClick={() => setActive(null)}
                  className="shrink-0 w-8 h-8 rounded-full bg-stone-100 text-stone-500 hover:bg-stone-200 text-sm"
                  title="关闭"
                >
                  ✕
                </button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <a
                  href={active.video}
                  target="_blank"
                  rel="noreferrer"
                  className="px-4 py-2 rounded-xl bg-mint-600 text-white text-sm hover:bg-mint-700 transition"
                >
                  ⬇ 下载视频
                </a>
                <button
                  onClick={copyLink}
                  className="px-4 py-2 rounded-xl border border-stone-200 text-stone-600 text-sm hover:bg-stone-50"
                >
                  {copied ? '✓ 已复制' : '🔗 复制直链'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Works
