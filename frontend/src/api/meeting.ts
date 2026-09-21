/**
 * 会议记录 API 客户端
 *
 * 两个后端：
 *  - 转写（录音→文字稿）：video-service（FastAPI，同视频译制服务），POST /api/meeting/transcribe
 *  - 大纲总结：backend（Spring Boot 音乐管家），POST /ai/chat（Result 包装）
 *
 * 服务地址来自运行时配置 public/meeting-config.json（构建产物里同名文件），
 * 部署后直接编辑该 JSON 即可改地址，无需重新构建；
 * asrApiBase 支持 "origin"（由视频服务同源托管时自动用当前源）。
 * 也可用 VITE_MEETING_ASR_BASE / VITE_MEETING_AI_BASE 在构建期覆盖默认值。
 */

import { dubUserId } from './dub'

const DEFAULT_ASR_BASE =
  (import.meta.env.VITE_MEETING_ASR_BASE as string | undefined) || 'http://127.0.0.1:8765'
const DEFAULT_AI_BASE =
  (import.meta.env.VITE_MEETING_AI_BASE as string | undefined) || 'http://localhost:8080/api'

export let MEETING_ASR_BASE = DEFAULT_ASR_BASE
export let MEETING_AI_BASE = DEFAULT_AI_BASE

let configPromise: Promise<void> | null = null

/** 启动时拉取 meeting-config.json；失败（离线/文件缺失）静默回退默认地址。 */
export function initMeetingConfig(): Promise<void> {
  if (!configPromise) {
    configPromise = (async () => {
      try {
        const res = await fetch(`${import.meta.env.BASE_URL}meeting-config.json`, {
          cache: 'no-store',
        })
        if (res.ok) {
          const cfg = await res.json()
          const asr = (cfg?.asrApiBase ?? '').toString().trim().replace(/\/+$/, '')
          if (asr === 'origin' || asr === 'same-origin') {
            if (typeof window !== 'undefined' && /^https?:$/.test(window.location.protocol)) {
              MEETING_ASR_BASE = window.location.origin
            }
          } else if (asr) {
            MEETING_ASR_BASE = asr
          }
          const ai = (cfg?.aiApiBase ?? '').toString().trim().replace(/\/+$/, '')
          if (ai) MEETING_AI_BASE = ai
        }
      } catch {
        // 配置取不到就用默认本机地址
      }
    })()
  }
  return configPromise
}

// --------------------------------------------------------------- 类型
export interface MeetingSegment {
  start: number
  end: number
  text: string
}

export interface MeetingResult {
  duration: number
  language: string
  model: string
  segments: MeetingSegment[]
  text: string
  srt: string
}

export interface MeetingJob {
  id: string
  status: 'processing' | 'done' | 'failed'
  progress: number
  message: string
  result?: MeetingResult
  error?: string
}

/** HTTPS 页面调 HTTP 接口会被浏览器混合内容策略拦截。 */
export function isMixedContentBlocked(base: string): boolean {
  return (
    typeof window !== 'undefined' &&
    window.location.protocol === 'https:' &&
    base.startsWith('http:')
  )
}

// --------------------------------------------------------------- 转写（video-service）
async function asrRequest<T>(path: string, init?: RequestInit, timeoutMs = 30000): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(`${MEETING_ASR_BASE}${path}`, { ...init, signal: ctrl.signal })
    if (!res.ok) {
      let detail = ''
      try {
        const data = await res.json()
        detail = data.detail || JSON.stringify(data)
      } catch {
        detail = await res.text().catch(() => '')
      }
      throw new Error(detail || `HTTP ${res.status}`)
    }
    return (await res.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

/** 上传录音/音频文件创建转写任务，返回任务 id（XHR 以汇报上传进度）。 */
export function uploadMeetingAudio(
  file: File,
  onProgress?: (pct: number) => void,
): Promise<{ id: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${MEETING_ASR_BASE}/api/meeting/transcribe`)
    // 与视频译制共用同一匿名 uid，服务端按用户隔离转写任务
    xhr.setRequestHeader('X-User-Id', dubUserId())
    xhr.timeout = 0
    xhr.upload.onprogress = e => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText)
        if (xhr.status >= 200 && xhr.status < 300) resolve(data as { id: string })
        else if (xhr.status === 405 || xhr.status === 404)
          reject(new Error('转写服务版本过旧（没有会议接口），请升级 video-service 后重试'))
        else reject(new Error(data.detail || `HTTP ${xhr.status}`))
      } catch {
        reject(new Error(`上传失败（HTTP ${xhr.status}）`))
      }
    }
    xhr.onerror = () => reject(new Error('上传失败：无法连接转写服务'))
    const fd = new FormData()
    fd.append('file', file)
    fd.append('model', 'small')
    xhr.send(fd)
  })
}

/** 轮询转写任务状态与结果。 */
export function fetchMeetingJob(id: string): Promise<MeetingJob> {
  return asrRequest<MeetingJob>(`/api/meeting/transcribe/${encodeURIComponent(id)}`, {
    headers: { 'X-User-Id': dubUserId() },
  })
}

// --------------------------------------------------------------- 总结（backend 大模型）
export interface AiChatResult {
  code: number
  message: string
  data?: { response?: string }
}

/**
 * 调用 backend /ai/chat 生成会议大纲。
 * 字数限制通过 systemPrompt 下发（backend 支持请求级 systemPrompt 覆盖）。
 */
export async function summarizeMeeting(transcript: string, wordLimit: number): Promise<string> {
  const limitText =
    wordLimit > 0 ? `全文总字数（含标点）严格控制在 ${wordLimit} 字以内。` : ''
  const systemPrompt =
    '你是专业的会议纪要助手。请把用户提供的会议文字稿整理成一份结构化内容大纲：' +
    '用简洁短句和层级要点组织（可按 议题/结论/待办事项 分组），不要逐句复述，' +
    '保留关键数字、人名、时间与结论。' +
    limitText +
    '只输出大纲正文，不要多余解释。'

  // 超长文字稿截断保护（glm 系列上下文足够大，一般不会触发）
  const MAX_CHARS = 12000
  const body =
    transcript.length > MAX_CHARS
      ? transcript.slice(0, MAX_CHARS) + '\n…（文字稿过长，已截断）'
      : transcript

  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 180000)
  try {
    const res = await fetch(`${MEETING_AI_BASE}/ai/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: body, systemPrompt }),
      signal: ctrl.signal,
    })
    if (!res.ok) throw new Error(`AI 服务 HTTP ${res.status}`)
    const data = (await res.json()) as AiChatResult
    // backend 统一 Result 包装：业务错误也是 HTTP 200，需检查 code
    if (data.code !== 200) throw new Error(data.message || 'AI 服务返回错误')
    const reply = data.data?.response ?? ''
    if (!reply) throw new Error('AI 未返回内容，请稍后重试')
    return reply
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('AI 总结超时，请稍后重试或缩短字数限制')
    }
    throw err instanceof Error ? err : new Error(String(err))
  } finally {
    clearTimeout(timer)
  }
}
