import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchMeetingJob,
  isMixedContentBlocked,
  MEETING_AI_BASE,
  MEETING_ASR_BASE,
  summarizeMeeting,
  uploadMeetingAudio,
  type MeetingJob,
} from '@/api/meeting'
import { trackEvent } from '@/utils/analytics'

type Stage = 'idle' | 'recording' | 'paused' | 'ready' | 'uploading' | 'transcribing' | 'transcribed'

const WORD_LIMITS = [
  { value: 0, label: '不限字数' },
  { value: 150, label: '150 字以内' },
  { value: 300, label: '300 字以内' },
  { value: 500, label: '500 字以内' },
  { value: 1000, label: '1000 字以内' },
]

function fmtClock(totalSec: number): string {
  const s = Math.max(0, Math.floor(totalSec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(sec).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

function pickRecorderMime(): string {
  if (typeof MediaRecorder === 'undefined') return ''
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']
  return candidates.find(m => MediaRecorder.isTypeSupported(m)) ?? ''
}

export default function Meeting() {
  // ---------------------------------------------------------------- 录音状态
  const [stage, setStage] = useState<Stage>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [audioUrl, setAudioUrl] = useState('')
  const [error, setError] = useState('')

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const timerRef = useRef<number | null>(null)
  const pausedRef = useRef(false)

  // ---------------------------------------------------------------- 转写状态
  const [job, setJob] = useState<MeetingJob | null>(null)
  const [transcript, setTranscript] = useState('')
  const [meta, setMeta] = useState<{ duration: number; language: string; segs: number } | null>(null)
  const pollRef = useRef<number | null>(null)

  // ---------------------------------------------------------------- 总结状态
  const [wordLimit, setWordLimit] = useState(0)
  const [summary, setSummary] = useState('')
  const [summarizing, setSummarizing] = useState(false)
  const [copied, setCopied] = useState<'text' | 'summary' | ''>('')

  const cleanupRecorder = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
    recorderRef.current = null
  }, [])

  useEffect(() => () => {
    cleanupRecorder()
    if (pollRef.current) window.clearInterval(pollRef.current)
  }, [cleanupRecorder])

  // ---------------------------------------------------------------- 录音
  const startRecording = useCallback(async () => {
    setError('')
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('当前浏览器不支持录音（HTTPS 或 localhost 环境才可用），可改用「导入音频」')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mimeType = pickRecorderMime()
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      chunksRef.current = []
      rec.ondataavailable = e => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      rec.onstop = () => {
        const type = rec.mimeType || mimeType || 'audio/webm'
        const blob = new Blob(chunksRef.current, { type })
        const ext = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm'
        const file = new File([blob], `meeting-${Date.now()}.${ext}`, { type })
        setAudioFile(file)
        setAudioUrl(url => {
          if (url) URL.revokeObjectURL(url)
          return URL.createObjectURL(blob)
        })
        setStage('ready')
        trackEvent('会议记录', '录音完成', `${file.size}B`)
      }
      recorderRef.current = rec
      rec.start(1000)
      pausedRef.current = false
      setElapsed(0)
      setStage('recording')
      timerRef.current = window.setInterval(() => {
        if (!pausedRef.current) setElapsed(e => e + 1)
      }, 1000)
      trackEvent('会议记录', '开始录音')
    } catch (err) {
      cleanupRecorder()
      const name = err instanceof DOMException ? err.name : ''
      if (name === 'NotAllowedError') {
        setError('麦克风权限被拒绝，请在浏览器地址栏允许麦克风后重试')
      } else if (name === 'NotFoundError') {
        setError('没有找到可用的麦克风设备')
      } else {
        setError('无法开始录音，可改用「导入音频」')
      }
    }
  }, [cleanupRecorder])

  const stopRecording = useCallback(() => {
    recorderRef.current?.state !== 'inactive' && recorderRef.current?.stop()
    cleanupRecorder()
  }, [cleanupRecorder])

  const togglePause = useCallback(() => {
    const rec = recorderRef.current
    if (!rec) return
    if (rec.state === 'recording') {
      rec.pause()
      pausedRef.current = true
      setStage('paused')
    } else if (rec.state === 'paused') {
      rec.resume()
      pausedRef.current = false
      setStage('recording')
    }
  }, [])

  const importFile = useCallback((file: File | null) => {
    setError('')
    if (!file) return
    setAudioFile(file)
    setAudioUrl(url => {
      if (url) URL.revokeObjectURL(url)
      return URL.createObjectURL(file)
    })
    setElapsed(0)
    setStage('ready')
    trackEvent('会议记录', '导入音频', file.name)
  }, [])

  const resetAll = useCallback(() => {
    stopRecording()
    if (pollRef.current) window.clearInterval(pollRef.current)
    setAudioFile(null)
    setAudioUrl(url => {
      if (url) URL.revokeObjectURL(url)
      return ''
    })
    setJob(null)
    setTranscript('')
    setMeta(null)
    setSummary('')
    setError('')
    setStage('idle')
  }, [stopRecording])

  // ---------------------------------------------------------------- 转写
  const startTranscribe = useCallback(async () => {
    if (!audioFile) return
    setError('')
    setSummary('')
    setStage('uploading')
    setJob({ id: '', status: 'processing', progress: 0, message: '正在上传音频…' })
    try {
      const { id } = await uploadMeetingAudio(audioFile, pct => {
        setJob(j => (j ? { ...j, progress: pct * 0.1, message: `上传中 ${Math.round(pct * 100)}%` } : j))
      })
      setStage('transcribing')
      trackEvent('会议记录', '提交转写')
      pollRef.current = window.setInterval(async () => {
        try {
          const cur = await fetchMeetingJob(id)
          setJob(cur)
          if (cur.status === 'done') {
            if (pollRef.current) window.clearInterval(pollRef.current)
            const r = cur.result!
            setTranscript(r.text)
            setMeta({ duration: r.duration, language: r.language, segs: r.segments.length })
            setStage('transcribed')
            trackEvent('会议记录', '转写完成', `${r.segments.length}段`)
          } else if (cur.status === 'failed') {
            if (pollRef.current) window.clearInterval(pollRef.current)
            setError(cur.error || '转写失败')
            setStage('ready')
          }
        } catch {
          // 单次轮询失败忽略，下一轮重试
        }
      }, 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败')
      setStage('ready')
    }
  }, [audioFile])

  // ---------------------------------------------------------------- 总结
  const generateSummary = useCallback(async () => {
    if (!transcript.trim() || summarizing) return
    setError('')
    setSummary('')
    setSummarizing(true)
    try {
      const reply = await summarizeMeeting(transcript, wordLimit)
      setSummary(reply)
      trackEvent('会议记录', '生成大纲', `${wordLimit || '无限'}字`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'AI 总结失败'
      const hint = isMixedContentBlocked(MEETING_AI_BASE)
        ? '（HTTPS 页面无法调用 HTTP 接口：请在本地打开本页，或将 meeting-config.json 的 aiApiBase 改为 HTTPS 地址）'
        : ''
      setError(msg + hint)
    } finally {
      setSummarizing(false)
    }
  }, [transcript, summarizing, wordLimit])

  const copyText = useCallback(async (text: string, which: 'text' | 'summary') => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(which)
      window.setTimeout(() => setCopied(''), 1500)
    } catch {
      setError('复制失败，请手动选择文本复制')
    }
  }, [])

  // ---------------------------------------------------------------- 渲染
  const busy = stage === 'uploading' || stage === 'transcribing'
  const recUnsupported = typeof MediaRecorder === 'undefined'

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-stone-800 flex items-center gap-2">🎙️ 会议记录</h1>
        <p className="mt-1 text-sm text-stone-500">
          录音/导入音频 → 转成文字稿（本地 Whisper）→ AI 总结内容大纲
        </p>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          {error}
          <button className="ml-2 underline" onClick={() => setError('')}>关闭</button>
        </div>
      ) : null}

      {/* 第一步：录音 / 导入 */}
      <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
        <h2 className="text-base font-semibold text-stone-800">1. 录音或导入音频</h2>
        {stage === 'idle' || stage === 'recording' || stage === 'paused' ? (
          <div className="mt-3 flex flex-col items-center gap-3 py-4">
            {stage === 'idle' ? (
              <>
                <button
                  onClick={startRecording}
                  disabled={recUnsupported}
                  className="flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br from-rose-400 to-red-500 text-white shadow-lg transition hover:scale-105 disabled:cursor-not-allowed disabled:opacity-40"
                  title={recUnsupported ? '当前浏览器不支持录音' : '开始录音'}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-8 w-8">
                    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" />
                  </svg>
                </button>
                <p className="text-sm text-stone-500">{recUnsupported ? '当前环境不支持录音，请导入音频文件' : '点击开始录音'}</p>
              </>
            ) : (
              <>
                <div className={`flex h-20 w-20 items-center justify-center rounded-full text-white shadow-lg ${stage === 'recording' ? 'bg-red-500 animate-pulse' : 'bg-stone-400'}`}>
                  <span className="font-mono text-lg">{fmtClock(elapsed)}</span>
                </div>
                <div className="flex gap-3">
                  <button onClick={togglePause} className="rounded-full border border-stone-300 px-5 py-2 text-sm text-stone-700 hover:bg-stone-50">
                    {stage === 'recording' ? '暂停' : '继续'}
                  </button>
                  <button onClick={stopRecording} className="rounded-full bg-red-500 px-5 py-2 text-sm font-medium text-white hover:bg-red-600">
                    完成录音
                  </button>
                  <button onClick={resetAll} className="rounded-full px-3 py-2 text-sm text-stone-400 hover:text-stone-600">取消</button>
                </div>
              </>
            )}
            <label className="cursor-pointer text-sm text-stone-400 underline hover:text-stone-600">
              或导入音频文件（webm / mp3 / m4a / wav…）
              <input type="file" accept="audio/*,video/mp4,video/webm" className="hidden" onChange={e => importFile(e.target.files?.[0] ?? null)} />
            </label>
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-sm text-stone-600">
              <span className="truncate font-medium text-stone-800">{audioFile?.name}</span>
              {audioUrl ? <audio controls src={audioUrl} className="h-8 max-w-full" /> : null}
              {!busy && stage !== 'transcribed' ? (
                <button onClick={resetAll} className="text-stone-400 underline hover:text-stone-600">重选</button>
              ) : null}
            </div>
            {stage === 'ready' ? (
              <button onClick={startTranscribe} className="w-full rounded-xl bg-gradient-to-r from-teal-500 to-emerald-500 py-2.5 font-medium text-white shadow hover:opacity-90">
                开始转文字稿 →
              </button>
            ) : null}
          </div>
        )}
      </section>

      {/* 第二步：转写进度 */}
      {busy ? (
        <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="text-base font-semibold text-stone-800">2. 转写中…</h2>
          <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-stone-100">
            <div
              className="h-full rounded-full bg-gradient-to-r from-teal-500 to-emerald-500 transition-all"
              style={{ width: `${Math.round((job?.progress ?? 0) * 100)}%` }}
            />
          </div>
          <p className="mt-2 text-sm text-stone-500">
            {job?.message || '处理中…'}（{Math.round((job?.progress ?? 0) * 100)}%）
          </p>
        </section>
      ) : null}

      {/* 第三步：文字稿 */}
      {stage === 'transcribed' ? (
        <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-stone-800">2. 文字稿</h2>
            <div className="flex items-center gap-3 text-xs text-stone-400">
              {meta ? (
                <span>
                  {fmtClock(meta.duration)} · {meta.segs} 段 · 语言 {meta.language || '?'}
                </span>
              ) : null}
              <button className="underline hover:text-stone-600" onClick={() => copyText(transcript, 'text')}>
                {copied === 'text' ? '已复制 ✓' : '复制全文'}
              </button>
            </div>
          </div>
          <textarea
            value={transcript}
            onChange={e => setTranscript(e.target.value)}
            rows={10}
            className="mt-3 w-full resize-y rounded-xl border border-stone-200 bg-stone-50 p-3 text-sm leading-relaxed text-stone-700 focus:border-teal-400 focus:outline-none"
            placeholder="转写结果（可手动修改后再总结）"
          />
        </section>
      ) : null}

      {/* 第四步：AI 总结 */}
      {stage === 'transcribed' ? (
        <section className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="text-base font-semibold text-stone-800">3. AI 总结大纲</h2>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <select
              value={wordLimit}
              onChange={e => setWordLimit(Number(e.target.value))}
              className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700 focus:border-teal-400 focus:outline-none"
            >
              {WORD_LIMITS.map(w => (
                <option key={w.value} value={w.value}>{w.label}</option>
              ))}
            </select>
            <button
              onClick={generateSummary}
              disabled={summarizing || !transcript.trim()}
              className="rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 px-5 py-2 text-sm font-medium text-white shadow hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {summarizing ? 'AI 思考中…' : '生成内容大纲'}
            </button>
          </div>
          {isMixedContentBlocked(MEETING_AI_BASE) ? (
            <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-600">
              当前是 HTTPS 页面，浏览器会拦截对 {MEETING_AI_BASE}（HTTP）的请求。请在本地打开本页使用，或将 meeting-config.json 的 aiApiBase 改为 HTTPS 地址。
            </p>
          ) : null}
          {summary ? (
            <div className="mt-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-stone-700">大纲</h3>
                <button className="text-xs text-stone-400 underline hover:text-stone-600" onClick={() => copyText(summary, 'summary')}>
                  {copied === 'summary' ? '已复制 ✓' : '复制大纲'}
                </button>
              </div>
              <pre className="mt-2 whitespace-pre-wrap rounded-xl bg-stone-50 p-3 font-sans text-sm leading-relaxed text-stone-700">{summary}</pre>
            </div>
          ) : null}
          <p className="mt-3 text-xs text-stone-400">
            转写服务：{MEETING_ASR_BASE} · 大模型：{MEETING_AI_BASE}
          </p>
        </section>
      ) : null}
    </div>
  )
}
