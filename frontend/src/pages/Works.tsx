/**
 * 视频库：展示所有用户发布到本地 video-service 的配音成片。
 *
 * 数据来自 video-service 公开接口 /api/works（无需用户身份），
 * 播放/缩略图走 /api/works/{id}/video、/api/works/{id}/thumb。
 * 注意：GitHub Pages（https）直连 http 服务会被浏览器拦截，
 * 在服务器自托管页面（同源）或 HTTPS 反代下播放无碍。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { DUB_BASE_URL, deleteExternalWork, deleteWork, dubUserId, listExternalWorks, listWorks, workThumbUrl, workVideoUrl } from '@/api/dub'

export interface Work {
  id: string
  title: string
  note?: string
  video: string
  poster?: string
  duration?: number
  size?: number
  published_at?: number
  owner?: string
  external?: boolean
  extName?: string
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
  const [items, ext] = await Promise.all([listWorks(), listExternalWorks().catch(() => [])])
  const regular = items.map(w => ({
    id: w.id,
    title: w.filename.replace(/\.[^.]+$/, ''),
    video: workVideoUrl(w.id),
    poster: workThumbUrl(w.id),
    duration: w.duration,
    size: w.size,
    published_at: w.published_at,
    owner: w.owner,
  }))
  const external = ext.map(w => ({
    id: w.id,
    title: w.filename.replace(/\.[^.]+$/, ''),
    video: `${DUB_BASE_URL}${w.video}`,
    poster: '',
    size: w.size,
    published_at: w.published_at || w.created_at,
    external: true,
    extName: w.filename,
  }))
  return [...regular, ...external]
}

const WORKS_PASSWORD = '392766'
const WORKS_UNLOCK_KEY = 'works_unlocked'

const Works: React.FC = () => {
  const [unlocked, setUnlocked] = useState(() => sessionStorage.getItem(WORKS_UNLOCK_KEY) === '1')
  const [pwInput, setPwInput] = useState('')
  const [pwError, setPwError] = useState(false)
  const [works, setWorks] = useState<Work[] | null>(null)
  const [error, setError] = useState('')
  const [active, setActive] = useState<Work | null>(null)
  const [copied, setCopied] = useState(false)
  const uid = useMemo(() => dubUserId(), [])

  const submitPw = () => {
    if (pwInput.trim() === WORKS_PASSWORD) {
      sessionStorage.setItem(WORKS_UNLOCK_KEY, '1')
      setUnlocked(true); setPwError(false)
    } else {
      setPwError(true)
    }
  }

  const refresh = useCallback(() => {
    let alive = true
    setWorks(null); setError('')
    loadWorks()
      .then(list => alive && setWorks(list))
      .catch(err => alive && setError(err?.message || '加载失败'))
    return () => { alive = false }
  }, [])

  useEffect(() => refresh(), [refresh])

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

  const onDelete = async () => {
    if (!active) return
    // 外部视频所有人可删；正常视频仅发布者可删
    const canDelete = active.external || (active.owner === uid)
    if (!canDelete) { window.alert('只有发布者可以删除'); return }
    if (!window.confirm(`确定删除「${active.title}」吗？\n文件将被删除，不可恢复。`)) return
    try {
      if (active.external && active.extName) {
        await deleteExternalWork(active.extName)
      } else {
        await deleteWork(active.id)
      }
      setActive(null)
      refresh()
    } catch (e) {
      window.alert(e instanceof Error ? e.message : '删除失败')
    }
  }

  if (!unlocked) {
    return (
      <div className="animate-fade-up flex items-center justify-center min-h-[60vh]">
        <div className="w-full max-w-xs bg-white rounded-2xl shadow-card border border-mint-100/70 p-6 text-center">
          <div className="text-4xl mb-3">🔒</div>
          <h2 className="text-lg font-bold text-mint-900 mb-1">视频库</h2>
          <p className="text-xs text-mint-700/60 mb-4">请输入密码以查看视频库</p>
          <input
            type="password"
            value={pwInput}
            onChange={e => { setPwInput(e.target.value); setPwError(false) }}
            onKeyDown={e => e.key === 'Enter' && submitPw()}
            placeholder="输入密码"
            className="w-full px-4 py-2.5 rounded-xl border border-stone-200 text-center text-sm focus:outline-none focus:border-mint-400"
            autoFocus
          />
          {pwError && <p className="mt-2 text-xs text-red-500">密码错误，请重试</p>}
          <button
            onClick={submitPw}
            className="mt-3 w-full py-2.5 rounded-xl bg-mint-600 text-white text-sm hover:bg-mint-700"
          >
            进入视频库
          </button>
        </div>
      </div>
    )
  }

  return (
    <>
    <div className="animate-fade-up">
      {/* 标题区 */}
      <section className="mb-6">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-mint-100 text-mint-700 text-xs font-semibold">
          🎬 视频库
        </div>
        <h1 className="mt-2 text-2xl font-bold text-mint-900">视频库 · 中文配音作品</h1>
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
            在「视频译制」里完成配音后，点「发布到视频库」即可
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

    </div>

      {/* 播放弹窗 —— 必须在 animate-fade-up 容器外，否则 transform 破坏 fixed 定位 */}
      {active && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-3 sm:p-6"
          onClick={() => setActive(null)}
        >
          <div
            className="w-full max-w-3xl max-h-[90vh] rounded-2xl bg-white overflow-hidden shadow-2xl flex flex-col"
            onClick={e => e.stopPropagation()}
          >
            <video
              key={active.id}
              src={active.video}
              poster={active.poster}
              controls
              autoPlay
              playsInline
              className="w-full max-h-[45vh] sm:max-h-[60vh] bg-black object-contain"
            />
            <div className="p-4 overflow-y-auto flex-1">
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
                {(active.external || active.owner === uid) && (
                  <button
                    onClick={onDelete}
                    className="px-4 py-2 rounded-xl border border-red-200 text-red-600 text-sm hover:bg-red-50"
                  >
                    🗑 删除
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default Works
