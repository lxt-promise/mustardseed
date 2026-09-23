/**
 * 视频译制本地服务 API 客户端
 *
 * 后端是 video-service/（FastAPI，默认 127.0.0.1:8765），
 * 仅在用户本机运行；访问不到时页面显示启动指引。
 *
 * 服务地址来自运行时配置 public/dub-config.json（构建产物里同名文件），
 * 部署后直接编辑该 JSON 即可改地址，无需重新构建；
 * 也可用环境变量 VITE_DUB_API_BASE 在构建期覆盖默认值。
 * 所有接口字段与后端 app.py / jobs.py 的契约保持一致。
 */

const DEFAULT_DUB_BASE_URL =
  (import.meta.env.VITE_DUB_API_BASE as string | undefined) || 'http://127.0.0.1:8765'

// 运行时可变绑定：initDubConfig() 在应用挂载前完成赋值，
// 其他模块通过 ESM live binding 拿到解析后的地址。
export let DUB_BASE_URL = DEFAULT_DUB_BASE_URL

let configPromise: Promise<void> | null = null

/** 启动时拉取 dub-config.json；失败（离线/文件缺失）静默回退默认地址。 */
export function initDubConfig(): Promise<void> {
  if (!configPromise) {
    configPromise = (async () => {
      try {
        const res = await fetch(`${import.meta.env.BASE_URL}dub-config.json`, {
          cache: 'no-store',
        })
        if (res.ok) {
          const cfg = await res.json()
          const raw = (cfg?.dubApiBase ?? '').toString().trim().replace(/\/+$/, '')
          if (raw === 'origin' || raw === 'same-origin') {
            // 前端由视频服务同源托管（video-service/web/）时：直接用当前源，
            // 局域网 http://<服务器IP>:8765 访问无需改配置，也无混合内容问题。
            if (typeof window !== 'undefined' && /^https?:$/.test(window.location.protocol)) {
              DUB_BASE_URL = window.location.origin
            }
          } else if (raw) {
            DUB_BASE_URL = raw
          }
        }
      } catch {
        // 配置取不到就用默认本机地址
      }
    })()
  }
  return configPromise
}

// --------------------------------------------------------------- 类型
export interface HealthInfo {
  ok: boolean
  ffmpeg: { available: boolean; version: string; path: string }
  faster_whisper: { available: boolean }
  edge_tts: { available: boolean }
  version: string
}

export interface Voice {
  id?: string
  short_name?: string
  name?: string
  label: string
  gender: 'Male' | 'Female' | string
  style?: string
  locale: string
  desc?: string
}

export interface WhisperModel {
  id: string
  label: string
  size: string
  note: string
  downloaded?: boolean
}

export interface OptionsInfo {
  voices: Voice[]
  locale_groups: { locale: string; label: string; voices: Voice[] }[]
  default_voice: string
  whisper_models: WhisperModel[]
  default_whisper_model: string
  languages: { id: string; label: string }[]
  limits: { max_upload_mb: number }
  output: { default_dir: string; dir: string; suffix: string }
}

export interface VideoMeta {
  duration: number
  resolution: string
  has_video: boolean
  has_audio: boolean
  subtitle_streams: number
  subtitle_names: string[]
}

export interface UploadResult {
  filename: string
  stored_name: string
  path: string
  size: number
  size_text: string
  meta: VideoMeta
}

export type JobStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'

export interface Segment {
  start: number
  end: number
  text: string
  translated: string
}

export interface JobOutput {
  name: string
  path: string
  kind: string
  size?: number
}

export interface JobInfo {
  id: string
  filename: string
  status: JobStatus
  stage: string
  stage_label: string
  progress: number
  message: string
  error: string
  media: Record<string, unknown>
  plan: Record<string, unknown>
  outputs: JobOutput[]
  logs: string[]
  created_at: number
  finished_at: number
  /** 各环节耗时（秒）：probe/extract/transcribe/translate/dub/mix */
  stage_timings?: Record<string, number>
  /** 总耗时（秒） */
  total_seconds?: number
  /** 是否已发布到本地视频库（所有人可见） */
  published?: boolean
  published_at?: number
  options: Record<string, unknown>
  segments?: Segment[]
}

/** 创建任务的选项（白名单与后端 _OPTION_KEYS 对齐） */
export interface JobOptions {
  engine?: 'local' | 'cloud'
  whisper_model?: string
  source_language?: string
  translate_to_zh?: boolean
  cloud_base_url?: string
  cloud_api_key?: string
  cloud_asr_model?: string
  translate_base_url?: string
  translate_api_key?: string
  translate_model?: string
  translate_provider?: string
  voice?: string
  rate?: number
  volume?: number
  pitch?: number
  auto_fit?: boolean
  burn_subtitle?: boolean
  soft_subtitle?: boolean
  bilingual?: boolean
  keep_original_audio?: boolean
  original_volume?: number
  /** 背景音：off 只要配音 / original 保留原片声音 / instrumental 智能去人声留背景乐 */
  bgm_mode?: 'off' | 'original' | 'instrumental'
  /** 背景音音量 0~1 */
  bgm_volume?: number
  /** 配音说话时自动压低背景音（智能闪避） */
  bgm_ducking?: boolean
  use_embedded_subtitle?: boolean
  /** 字幕已是中文：跳过语音识别与翻译（英文视频 + 现成中文字幕） */
  subtitles_already_zh?: boolean
  /** 硬字幕 OCR：字幕烧录在画面里，从画面提取代替语音识别 */
  ocr_hard_subtitle?: boolean
  subtitle_file?: string
  output_suffix?: string
  output_dir?: string
  /** 手工修改后的字幕（改稿重跑时随创建任务传入） */
  edited_segments?: Segment[]
}

// --------------------------------------------------------------- 用户隔离
// 浏览器自生成匿名 uid（localStorage 持久化），用于服务端任务隔离：
// fetch/XHR 走 X-User-Id 头；<video>/<img> 等媒体标签无法带自定义头，走 ?uid= 参数。
const DUB_UID_KEY = 'vd_uid'

export function dubUserId(): string {
  let uid = localStorage.getItem(DUB_UID_KEY) || ''
  if (!uid) {
    uid =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `u-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
    localStorage.setItem(DUB_UID_KEY, uid)
  }
  return uid
}

function withUid(url: string): string {
  return `${url}${url.includes('?') ? '&' : '?'}uid=${encodeURIComponent(dubUserId())}`
}

// --------------------------------------------------------------- 请求封装
async function request<T>(path: string, init?: RequestInit, timeoutMs = 30000): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(`${DUB_BASE_URL}${path}`, {
      ...init,
      headers: { 'X-User-Id': dubUserId(), ...(init?.headers || {}) },
      signal: ctrl.signal,
    })
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

// --------------------------------------------------------------- API
export async function fetchHealth(): Promise<HealthInfo> {
  return request<HealthInfo>('/api/health', undefined, 4000)
}

export async function fetchOptions(): Promise<OptionsInfo> {
  return request<OptionsInfo>('/api/options')
}

export async function uploadVideo(file: File, onProgress?: (pct: number) => void): Promise<UploadResult> {
  // 大文件上传需要长超时，并通过 XHR 汇报进度
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${DUB_BASE_URL}/api/upload`)
    xhr.setRequestHeader('X-User-Id', dubUserId())
    xhr.timeout = 0
    xhr.upload.onprogress = e => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText)
        if (xhr.status >= 200 && xhr.status < 300) resolve(data as UploadResult)
        else reject(new Error(data.detail || `HTTP ${xhr.status}`))
      } catch {
        reject(new Error(`上传失败（HTTP ${xhr.status}）`))
      }
    }
    xhr.onerror = () => reject(new Error('上传失败：无法连接本地服务'))
    const fd = new FormData()
    fd.append('file', file)
    xhr.send(fd)
  })
}

export async function uploadSubtitle(file: File): Promise<{ path: string; count: number; filename: string }> {
  const fd = new FormData()
  fd.append('file', file)
  return request('/api/upload-subtitle', { method: 'POST', body: fd }, 60000)
}

export async function createJob(filename: string, videoPath: string, options: JobOptions) {
  return request<{ id: string; status: string }>('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, video_path: videoPath, ...options }),
  })
}

export async function getJob(id: string): Promise<JobInfo> {
  return request<JobInfo>(`/api/jobs/${id}`)
}

/** 任务列表（按创建时间倒序，不含 segments；恢复页面状态用） */
export async function listJobs(): Promise<{ jobs: JobInfo[] }> {
  return request<{ jobs: JobInfo[] }>('/api/jobs')
}

export async function cancelJob(id: string): Promise<void> {
  await request(`/api/jobs/${id}/cancel`, { method: 'POST' })
}

/** 删除一条历史任务（仅非运行中的任务） */
export async function deleteJob(id: string): Promise<void> {
  await request(`/api/jobs/${id}`, { method: 'DELETE' })
}

export async function saveSegments(id: string, segments: Segment[]): Promise<void> {
  await request(`/api/segments/${id}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segments }),
  })
}

export async function redoJob(id: string, options: JobOptions): Promise<{ id: string; status: string }> {
  return request(`/api/redo/${id}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  })
}

/** 试听合成（返回可播放的 mp3 blob URL） */
export async function previewVoice(text: string, voice: string, rate = 0, volume = 0): Promise<string> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 20000)
  try {
    const res = await fetch(`${DUB_BASE_URL}/api/translate-preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice, rate, volume }),
      signal: ctrl.signal,
    })
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '试听失败')
    const blob = await res.blob()
    return URL.createObjectURL(blob)
  } finally {
    clearTimeout(timer)
  }
}

// --------------------------------------------------------------- 文件 URL
// 媒体标签无法带请求头，归属身份用 ?uid= 传递
export function previewVideoUrl(jobId: string, which = 0): string {
  return withUid(`${DUB_BASE_URL}/api/preview/${jobId}?which=${which}&t=${Date.now()}`)
}

export function thumbnailUrl(jobId: string): string {
  return withUid(`${DUB_BASE_URL}/api/thumbnail/${jobId}`)
}

export function downloadUrl(jobId: string, index: number): string {
  return withUid(`${DUB_BASE_URL}/api/download/${jobId}/${index}`)
}

export function previewSourceUrl(jobId: string): string {
  return withUid(`${DUB_BASE_URL}/api/preview-source/${jobId}`)
}

// --------------------------------------------------------------- 作品库发布
export interface PublishConfig {
  /** 本机服务是否已配置 GitHub token / repo */
  configured: boolean
  repo: string
  release_tag: string
  /** 作品库页面的公网地址（GitHub Pages） */
  pages_url: string
}

export interface WorkInfo {
  id: string
  title: string
  note: string
  video: string
  poster: string
  duration: number
  size: number
  published_at: number
  pages_url?: string
  repo_private?: boolean
}

export async function fetchPublishConfig(): Promise<PublishConfig> {
  return request<PublishConfig>('/api/publish/config', undefined, 8000)
}

/** 发布成片到 GitHub 作品库；大文件上传，给足 20 分钟超时 */
export async function publishWork(
  jobId: string,
  payload: { title: string; note?: string; index?: number },
): Promise<{ ok: boolean; work: WorkInfo }> {
  return request<{ ok: boolean; work: WorkInfo }>(
    `/api/publish/${jobId}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    20 * 60 * 1000,
  )
}

export async function unpublishWork(workId: string): Promise<void> {
  await request(`/api/publish/works/${encodeURIComponent(workId)}`, { method: 'DELETE' })
}

// --------------------------------------------------------------- 本地视频库（发布后所有人可见）
export interface WorkItem {
  id: string
  filename: string
  duration?: number
  size?: number
  created_at: number
  published_at: number
  video: string
  thumb: string
}

/** 发布/取消发布到本地视频库（仅任务所有者可操作） */
export async function setWorkPublished(jobId: string, published: boolean): Promise<void> {
  await request(`/api/jobs/${encodeURIComponent(jobId)}/${published ? 'publish' : 'unpublish'}`, {
    method: 'POST',
  })
}

/** 公开视频库列表：无需用户身份，所有人可见 */
export async function listWorks(): Promise<WorkItem[]> {
  const r = await request<{ works: WorkItem[] }>('/api/works', undefined, 15000)
  return r.works
}

export function workVideoUrl(id: string): string {
  return `${DUB_BASE_URL}/api/works/${encodeURIComponent(id)}/video`
}

export function workThumbUrl(id: string): string {
  return `${DUB_BASE_URL}/api/works/${encodeURIComponent(id)}/thumb`
}
