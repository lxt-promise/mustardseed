import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  DUB_BASE_URL,
  fetchHealth, fetchOptions,
  uploadVideo, uploadSubtitle,
  createJob, getJob, listJobs, cancelJob, deleteJob, saveSegments, redoJob, previewVoice,
  previewVideoUrl, downloadUrl,
  fetchPublishConfig, publishWork,
  type HealthInfo, type OptionsInfo, type UploadResult,
  type JobInfo, type Segment, type JobOptions, type Voice, type WhisperModel,
  type PublishConfig, type WorkInfo,
} from '@/api/dub'
import { trackEvent } from '@/utils/analytics'

type Phase = 'loading' | 'offline' | 'setup' | 'running' | 'finished'

// 「发布到作品库」暂时下线（2026-09-20）；显式 boolean 注解避免 TS 把该块当作不可达代码
const SHOW_PUBLISH: boolean = false

const STAGE_LABELS: Record<string, string> = {
  probe: '分析视频', extract: '分离音频', transcribe: '识别语音',
  translate: '翻译字幕', dub: '合成配音', mix: '合成视频',
}
const STAGE_ORDER = ['probe', 'extract', 'transcribe', 'translate', 'dub', 'mix']

const fmtTime = (s: number) => {
  if (!isFinite(s)) return '--:--'
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

// Whisper 模型档位（按准确率/资源消耗排序）
const MODEL_RANK: Record<string, number> = {
  tiny: 0, base: 1, small: 2, medium: 3, 'large-v3': 4,
}

/** 按视频文件大小推荐档位：小视频求快用小模型，大视频内容多值得上高精度模型 */
const recommendModelBySize = (sizeBytes: number): string => {
  const mb = sizeBytes / (1024 * 1024)
  if (mb < 10) return 'tiny'
  if (mb < 100) return 'base'
  if (mb < 500) return 'small'
  if (mb < 2048) return 'medium'
  return 'large-v3'
}

/**
 * 结合本机已下载情况选出实际可用档位：
 * 推荐档位未下载时，回退到已下载模型中不高于它的最接近档位，
 * 避免任务一开跑就自动下载数 GB 模型；老后端不返回 downloaded 时不做判断。
 */
const pickAvailableModel = (
  models: WhisperModel[] | undefined,
  wanted: string,
  fallback: string,
): { id: string; downgraded: boolean } => {
  if (!models?.length || !models.some(m => m.downloaded !== undefined)) {
    return { id: wanted, downgraded: false }
  }
  if (models.some(m => m.id === wanted && m.downloaded !== false)) {
    return { id: wanted, downgraded: false }
  }
  const ready = models.filter(m => m.downloaded !== false)
  if (!ready.length) return { id: fallback, downgraded: true }
  const wr = MODEL_RANK[wanted] ?? 2
  const lower = ready.filter(m => (MODEL_RANK[m.id] ?? -1) <= wr)
  const pool = lower.length ? lower : ready
  const picked = pool.reduce((best, m) =>
    ((MODEL_RANK[m.id] ?? -1) > (MODEL_RANK[best.id] ?? -1) ? m : best)
  )
  return { id: picked.id, downgraded: picked.id !== wanted }
}

const Dub: React.FC = () => {
  const [phase, setPhase] = useState<Phase>('loading')
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [opts, setOpts] = useState<OptionsInfo | null>(null)

  // 上传与配置
  const [upload, setUpload] = useState<UploadResult | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadPct, setUploadPct] = useState(0)
  const [dragOver, setDragOver] = useState(false)
  const [subInfo, setSubInfo] = useState<{ path: string; count: number; filename: string } | null>(null)

  const [engine, setEngine] = useState<'local' | 'cloud'>('local')
  const [whisperModel, setWhisperModel] = useState('small')
  // 当前模型是否为「按视频大小自动推荐」：用户手动切换后置 false，重新上传再自动推荐
  const [modelAuto, setModelAuto] = useState(false)
  const [sourceLang, setSourceLang] = useState('en')
  const [voice, setVoice] = useState('')
  const [rate, setRate] = useState(0)
  const [volume, setVolume] = useState(0)
  const [autoFit, setAutoFit] = useState(true)
  const [burnSub, setBurnSub] = useState(true)
  const [softSub, setSoftSub] = useState(false)
  const [bilingual, setBilingual] = useState(false)
  // 背景音：off 关闭 / original 保留原声 / instrumental 智能去人声留背景乐
  const [bgmMode, setBgmMode] = useState<'off' | 'original' | 'instrumental'>('off')
  const [bgmVolume, setBgmVolume] = useState(35)
  const [bgmDucking, setBgmDucking] = useState(true)
  const onPickBgm = (m: 'off' | 'original' | 'instrumental') => {
    setBgmMode(m)
    // 切模式给该模式的推荐默认音量（用户可再手动微调）
    if (m === 'original') setBgmVolume(10)
    if (m === 'instrumental') setBgmVolume(35)
  }
  const [useEmbedded, setUseEmbedded] = useState(false)
  // 字幕已是中文模式：跳过语音识别与翻译（英文视频 + 现成中文字幕）
  const [subAlreadyZh, setSubAlreadyZh] = useState(false)
  // 硬字幕 OCR：字幕烧录在画面里时，用 OCR 提取代替语音识别
  const [ocrHardSub, setOcrHardSub] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [cloudBase, setCloudBase] = useState('')
  const [cloudKey, setCloudKey] = useState('')
  const [cloudModel, setCloudModel] = useState('whisper-1')

  // 任务
  const [job, setJob] = useState<JobInfo | null>(null)
  const [editingSegs, setEditingSegs] = useState<Segment[]>([])
  const [showEditor, setShowEditor] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // 历史任务清单（后端内存列表，按时间倒序）
  const [history, setHistory] = useState<JobInfo[]>([])
  // 作品库发布
  const [pubCfg, setPubCfg] = useState<PublishConfig | null>(null)
  const [pubOpen, setPubOpen] = useState(false)
  const [pubTitle, setPubTitle] = useState('')
  const [pubNote, setPubNote] = useState('')
  const [publishing, setPublishing] = useState(false)
  const [pubError, setPubError] = useState('')
  const [published, setPublished] = useState<WorkInfo | null>(null)
  const pollRef = useRef<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const subInputRef = useRef<HTMLInputElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  // ------------------------------------------------------------ 启动检测
  const refreshHistory = useCallback(async () => {
    try {
      const { jobs } = await listJobs()
      setHistory(jobs ?? [])
    } catch { /* 列表刷新失败不打扰用户 */ }
  }, [])

  /** 进入页面时只自动恢复还在跑的任务（进度不丢）；
   *  已完成的任务不自动打开结果窗口——退出再进停留在任务列表，点"查看结果"再看 */
  const restoreJob = useCallback(async (): Promise<boolean> => {
    try {
      const { jobs } = await listJobs()
      setHistory(jobs ?? [])
      const latest = jobs?.find(j => j.status === 'running' || j.status === 'pending')
      // cancelled/failed/done 均不自动恢复：done 停留在任务列表（用户要求），
      // cancelled 是用户主动放弃，failed 重试需要上传上下文
      if (!latest) return false
      const full = await getJob(latest.id)
      setJob(full)
      setPhase('running') // pending / running：恢复进度轮询
      return true
    } catch {
      return false
    }
  }, [])

  const checkHealth = useCallback(async () => {
    setPhase('loading')
    try {
      const h = await fetchHealth()
      setHealth(h)
      const o = await fetchOptions()
      setOpts(o)
      setVoice(v => v || o.default_voice)
      setWhisperModel(o.default_whisper_model)
      // 恢复最近一次任务：任务在后端持续运行，返回/刷新页面不影响进度
      if (!(await restoreJob())) setPhase('setup')
    } catch {
      setPhase('offline')
    }
  }, [restoreJob])

  useEffect(() => { checkHealth() }, [checkHealth])

  // ------------------------------------------------------------ 任务轮询
  useEffect(() => {
    if (!job || (job.status !== 'running' && job.status !== 'pending')) return
    pollRef.current = window.setInterval(async () => {
      try {
        const j = await getJob(job.id)
        setJob(j)
        if (['done', 'failed', 'cancelled'].includes(j.status)) {
          if (pollRef.current) window.clearInterval(pollRef.current)
          setPhase(j.status === 'done' ? 'finished' : 'setup')
          if (j.status === 'done') {
            setEditingSegs(j.segments ?? [])
            trackEvent('视频译制', '任务完成', j.filename)
          }
          refreshHistory()
        }
      } catch { /* 瞬时网络抖动，下一轮继续 */ }
    }, 1500)
    return () => { if (pollRef.current) window.clearInterval(pollRef.current) }
  }, [job?.id, job?.status, refreshHistory])

  // ------------------------------------------------------------ 上传
  const handleFile = useCallback(async (file: File) => {
    setError('')
    setUploading(true)
    setUploadPct(0)
    setSubInfo(null)
    setUseEmbedded(false)
    try {
      const r = await uploadVideo(file, pct => setUploadPct(pct))
      setUpload(r)
      // 根据视频文件大小自动推荐 Whisper 模型（本机未下载的高档位会自动回退）
      const wanted = recommendModelBySize(r.size)
      const { id } = pickAvailableModel(
        opts?.whisper_models, wanted, opts?.default_whisper_model ?? 'small',
      )
      setWhisperModel(id)
      setModelAuto(true)
      trackEvent('视频译制', '上传视频', r.filename)
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }, [opts])

  const handleSubtitle = useCallback(async (file: File) => {
    try {
      const r = await uploadSubtitle(file)
      setSubInfo(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : '字幕上传失败')
    }
  }, [])

  // ------------------------------------------------------------ 构造选项
  const buildOptions = useCallback((extra?: Partial<JobOptions>): JobOptions => {
    // LLM 翻译配置保存在浏览器本地（高级设置区）
    let llm: Record<string, string> = {}
    try { llm = JSON.parse(localStorage.getItem('dub-llm') ?? '{}') } catch { /* ignore */ }
    return {
      engine,
      whisper_model: whisperModel,
      source_language: sourceLang,
      voice,
      rate,
      volume,
      auto_fit: autoFit,
      burn_subtitle: burnSub,
      soft_subtitle: softSub,
      bilingual,
      keep_original_audio: bgmMode !== 'off',
      bgm_mode: bgmMode,
      bgm_volume: bgmVolume / 100,
      bgm_ducking: bgmDucking,
      use_embedded_subtitle: useEmbedded,
      subtitle_file: subInfo?.path ?? '',
      subtitles_already_zh: subAlreadyZh,
      ocr_hard_subtitle: ocrHardSub,
      ...(engine === 'cloud' ? {
        cloud_base_url: cloudBase,
        cloud_api_key: cloudKey,
        cloud_asr_model: cloudModel,
      } : {}),
      // provider 留 auto：三项齐全时后端自动走 LLM，否则走免费通道
      ...(llm.translate_base_url ? {
        translate_provider: 'auto',
        translate_base_url: llm.translate_base_url,
        translate_api_key: llm.translate_api_key,
        translate_model: llm.translate_model,
      } : {}),
      ...extra,
    }
  }, [engine, whisperModel, sourceLang, voice, rate, volume, autoFit,
      burnSub, softSub, bilingual, bgmMode, bgmVolume, bgmDucking, useEmbedded, subInfo,
      subAlreadyZh, ocrHardSub, cloudBase, cloudKey, cloudModel])

  const startJob = useCallback(async (edited?: Segment[]) => {
    if (!upload) return
    setError('')
    setBusy(true)
    try {
      const extra: Partial<JobOptions> = {}
      if (edited && edited.length) extra.edited_segments = edited
      const r = await createJob(upload.filename, upload.path, buildOptions(extra))
      const j = await getJob(r.id)
      setJob(j)
      setShowEditor(false)
      setPhase('running')
      refreshHistory()
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建任务失败')
    } finally {
      setBusy(false)
    }
  }, [upload, buildOptions, refreshHistory])

  // ------------------------------------------------------------ 操作
  /** 查看历史任务：加载完整信息并进入对应视图 */
  const openHistoryJob = async (id: string) => {
    setError('')
    try {
      const full = await getJob(id)
      setJob(full)
      if (full.status === 'done') {
        setEditingSegs(full.segments ?? [])
        setPhase('finished')
      } else if (full.status === 'failed') {
        setPhase('setup') // setup 视图会展示失败卡片
      } else {
        setPhase('running') // 进行中的任务恢复轮询
      }
    } catch {
      setError('任务可能已被清理，刷新后重试')
      refreshHistory()
    }
  }

  /** 删除一条历史任务及其工作目录 */
  const removeHistory = async (id: string) => {
    if (!window.confirm('确定删除这条任务吗？其产物与工作文件将一并清除。')) return
    try { await deleteJob(id) } catch { /* 可能正在运行 */ }
    if (job?.id === id) setJob(null)
    refreshHistory()
  }

  const onCancel = async () => {
    if (!job) return
    if (!window.confirm(`确定取消当前任务吗？\n「${job.filename}」已完成的处理将作废。`)) return
    try { await cancelJob(job.id) } catch { /* 状态轮询会兜底 */ }
  }

  const onRedo = async () => {
    if (!job) return
    setBusy(true); setError('')
    try {
      const r = await redoJob(job.id, buildOptions())
      const j = await getJob(r.id)
      setJob(j); setPhase('running')
    } catch (e) {
      setError(e instanceof Error ? e.message : '重跑失败')
    } finally { setBusy(false) }
  }

  const onSaveEditAndRedub = async () => {
    if (!job) return
    setBusy(true); setError('')
    try {
      await saveSegments(job.id, editingSegs)
      if (upload) {
        await startJob(editingSegs)
      } else {
        // 页面恢复出来的任务没有本地上传上下文，走 redo 复用后端保存的原视频
        const r = await redoJob(job.id, { ...buildOptions(), edited_segments: editingSegs })
        const j = await getJob(r.id)
        setJob(j); setPhase('running')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存修改失败')
    } finally { setBusy(false) }
  }

  const onPreviewVoice = async () => {
    if (!voice) return
    try {
      const url = await previewVoice('你好，这是中文配音的试听效果。', voice, rate, volume)
      if (audioRef.current) { audioRef.current.pause() }
      const a = new Audio(url)
      audioRef.current = a
      a.play()
    } catch (e) {
      setError(e instanceof Error ? e.message : '试听失败')
    }
  }

  // 任务完成后：加载发布配置并初始化作品标题
  useEffect(() => {
    if (phase !== 'finished' || !job) return
    let alive = true
    setPublished(null); setPubOpen(false); setPubError(''); setPublishing(false)
    setPubTitle(job.filename.replace(/\.[^.]+$/, ''))
    fetchPublishConfig()
      .then(cfg => { if (alive) setPubCfg(cfg) })
      .catch(() => { if (alive) setPubCfg(null) })
    return () => { alive = false }
    // job 每次轮询都会变，这里只按任务 id 跑一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, job?.id])

  const onPublish = async () => {
    if (!job || publishing) return
    if (pubCfg && !pubCfg.configured) {
      setPubError('')
      setPubOpen(true)
      return
    }
    setPublishing(true); setPubError('')
    try {
      const res = await publishWork(job.id, {
        title: pubTitle.trim() || job.filename.replace(/\.[^.]+$/, ''),
        note: pubNote.trim(),
      })
      setPublished(res.work)
      setPubOpen(false)
      trackEvent('作品库', '发布', res.work.id)
    } catch (e) {
      setPubError(e instanceof Error ? e.message : '发布失败')
    } finally {
      setPublishing(false)
    }
  }

  const resetAll = () => {
    setJob(null); setUpload(null); setSubInfo(null); setEditingSegs([])
    setShowEditor(false); setError(''); setPhase('setup')
    setPublished(null); setPubOpen(false); setPubError('')
  }

  const voiceGroups = useMemo(() => opts?.locale_groups ?? [], [opts])
  // Whisper 自动推荐提示：当前档位 / 视频大小 / 因未下载而回退时的理想档位
  const modelHint = useMemo<{ cur: string; sizeText: string; wanted?: string } | null>(() => {
    if (!modelAuto || !upload) return null
    const cur = opts?.whisper_models?.find(m => m.id === whisperModel)?.label ?? whisperModel
    const wantedId = recommendModelBySize(upload.size)
    const wantedMeta = opts?.whisper_models?.find(m => m.id === wantedId)
    return {
      cur,
      sizeText: upload.size_text,
      wanted: wantedId !== whisperModel && wantedMeta?.downloaded === false
        ? wantedMeta.label : undefined,
    }
  }, [modelAuto, upload, opts, whisperModel])
  const stageIdx = job ? STAGE_ORDER.indexOf(job.stage) : -1
  const videoOutputs = job?.outputs.filter(o => o.kind === 'video') ?? []

  // ================================================================ 渲染
  if (phase === 'loading') {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-stone-400">
        <div className="w-10 h-10 border-3 border-mint-200 border-t-mint-600 rounded-full animate-spin mb-4" />
        <p className="text-sm">正在连接本地译制服务…</p>
      </div>
    )
  }

  if (phase === 'offline') {
    return <OfflineCard onRetry={checkHealth} />
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-stone-800 flex items-center gap-2">
          🎬 视频译制
        </h1>
        <p className="text-sm text-stone-500 mt-1">
          英文视频 → 中文配音 + 中文字幕 · 本地处理，隐私安全
        </p>
      </div>

      {/* 服务状态条 */}
      {health && (
        <div className="flex items-center gap-2 text-xs px-3 py-2 rounded-xl bg-mint-50 border border-mint-100 text-mint-700">
          <span className="w-2 h-2 rounded-full bg-mint-500 animate-pulse" />
          服务在线（{health.version}）· ffmpeg {health.ffmpeg.available ? '✓' : '✗'}
          {' · '}Whisper {health.faster_whisper.available ? '✓' : '✗'}
          {' · '}Edge TTS {health.edge_tts.available ? '✓' : '✗'}
        </div>
      )}

      {error && (
        <div className="px-4 py-3 rounded-xl bg-red-50 border border-red-100 text-sm text-red-600 whitespace-pre-wrap">
          ⚠️ {error}
        </div>
      )}

      {/* ---------------- 配置阶段 ---------------- */}
      {(phase === 'setup') && (
        <>
          {/* 上传 */}
          <Card title="① 选择视频">
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*,.mkv,.mov,.avi,.flv,.wmv,.webm,.ts,.m2ts,.rmvb"
              className="hidden"
              onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])}
            />
            {!upload ? (
              <div
                onClick={() => !uploading && fileInputRef.current?.click()}
                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={e => {
                  e.preventDefault(); setDragOver(false)
                  const f = e.dataTransfer.files?.[0]
                  if (f) handleFile(f)
                }}
                className={`border-2 border-dashed rounded-2xl py-10 px-6 text-center cursor-pointer transition-colors ${
                  dragOver ? 'border-mint-500 bg-mint-50' : 'border-stone-200 hover:border-mint-300 hover:bg-mint-50/40'
                }`}
              >
                {uploading ? (
                  <div>
                    <div className="w-10 h-10 mx-auto border-3 border-mint-200 border-t-mint-600 rounded-full animate-spin mb-3" />
                    <p className="text-sm text-stone-500">上传中… {(uploadPct * 100).toFixed(0)}%</p>
                    <div className="w-48 h-1.5 bg-stone-100 rounded-full mx-auto mt-3 overflow-hidden">
                      <div className="h-full bg-mint-500 transition-all" style={{ width: `${uploadPct * 100}%` }} />
                    </div>
                  </div>
                ) : (
                  <div>
                    <div className="text-4xl mb-2">📹</div>
                    <p className="text-sm font-medium text-stone-700">点击或拖入视频文件</p>
                    <p className="text-xs text-stone-400 mt-1">
                      MP4 / MOV / MKV / AVI / WEBM 等 · 最大 {opts?.limits.max_upload_mb ?? 4096} MB
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-start gap-3 p-3 rounded-xl bg-mint-50/60 border border-mint-100">
                <div className="text-2xl">🎞️</div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-stone-800 truncate">{upload.filename}</p>
                  <p className="text-xs text-stone-500 mt-0.5">
                    {upload.size_text} · {fmtTime(upload.meta.duration)} · {upload.meta.resolution}
                    {upload.meta.subtitle_streams > 0 && ` · 含 ${upload.meta.subtitle_streams} 条内嵌字幕`}
                  </p>
                  <button
                    onClick={() => { setUpload(null); setSubInfo(null); setUseEmbedded(false) }}
                    className="text-xs text-mint-600 hover:underline mt-1"
                  >重新选择</button>
                </div>
              </div>
            )}

            {/* 字幕来源 */}
            {upload && (
              <div className="mt-3 space-y-2">
                <input
                  ref={subInputRef}
                  type="file"
                  accept=".srt,.vtt,.ass,.ssa"
                  className="hidden"
                  onChange={e => e.target.files?.[0] && handleSubtitle(e.target.files[0])}
                />
                <button
                  onClick={() => subInputRef.current?.click()}
                  className="text-xs px-3 py-1.5 rounded-lg border border-stone-200 text-stone-600 hover:border-mint-300 hover:text-mint-700"
                >
                  {subInfo ? `📝 外挂字幕：${subInfo.filename}（${subInfo.count} 条，点击替换）` : '📝 上传外挂字幕（可选，最准最快）'}
                </button>
                {upload.meta.subtitle_streams > 0 && (
                  <label className="flex items-center gap-2 text-xs text-stone-600 ml-2">
                    <input type="checkbox" checked={useEmbedded} onChange={e => setUseEmbedded(e.target.checked)}
                      className="accent-mint-600" />
                    使用视频内嵌字幕（{upload.meta.subtitle_names.join('、') || `${upload.meta.subtitle_streams} 条`}）
                  </label>
                )}
                {upload && (
                  <label className="flex items-start gap-2 text-xs text-stone-600 ml-2 cursor-pointer">
                    <input type="checkbox" checked={ocrHardSub} onChange={e => setOcrHardSub(e.target.checked)}
                      className="accent-mint-600 mt-0.5" />
                    <span>
                      字幕已烧录在画面中，用 OCR 提取（速度较慢）
                      <span className="block text-[11px] text-stone-400">
                        没有字幕文件时的选择：从画面识别字幕文字，中文/英文均可，自动跳过翻译环节
                      </span>
                    </span>
                  </label>
                )}
                {subInfo && (
                  <label className="flex items-start gap-2 text-xs text-stone-600 ml-2 cursor-pointer">
                    <input type="checkbox" checked={subAlreadyZh} onChange={e => setSubAlreadyZh(e.target.checked)}
                      className="accent-mint-600 mt-0.5" />
                    <span>
                      字幕已是中文，跳过识别与翻译
                      <span className="block text-[11px] text-stone-400">
                        适合英文视频 + 现成中文字幕：直接按字幕配音，最快且零翻译额度
                      </span>
                    </span>
                  </label>
                )}
                {subInfo && (
                  <button onClick={() => { setSubInfo(null); setSubAlreadyZh(false) }} className="text-xs text-stone-400 hover:text-red-500 ml-2">
                    移除字幕
                  </button>
                )}
              </div>
            )}
          </Card>

          {/* 识别设置 */}
          {upload && (
            <Card title="② 语音识别">
              <div className="grid grid-cols-2 gap-3">
                <Field label="识别方式">
                  <select value={engine} onChange={e => setEngine(e.target.value as 'local' | 'cloud')}
                    className={selectCls}>
                    <option value="local">本地识别（免费离线）</option>
                    <option value="cloud">云端识别（更快，需 Key）</option>
                  </select>
                </Field>
                <Field label="源语言">
                  <select value={sourceLang} onChange={e => setSourceLang(e.target.value)} className={selectCls}>
                    {(opts?.languages ?? []).map(l => <option key={l.id} value={l.id}>{l.label}</option>)}
                  </select>
                </Field>
              </div>
              {engine === 'local' ? (
                <Field
                  className="mt-3"
                  label={
                    <span className="flex items-center gap-2">
                      Whisper 模型
                      {upload && (
                        <span className="font-normal text-mint-600">
                          当前视频 {upload.size_text}
                        </span>
                      )}
                    </span>
                  }
                >
                  <select value={whisperModel}
                    onChange={e => { setWhisperModel(e.target.value); setModelAuto(false) }}
                    className={selectCls}>
                    {(opts?.whisper_models ?? []).map(m => (
                      <option key={m.id} value={m.id}>
                        {m.label} · 模型体积 {m.size}{m.downloaded === false ? '（需下载）' : ''} · {m.note}
                      </option>
                    ))}
                  </select>
                  {modelHint && (
                    <p className="text-[11px] text-stone-400 mt-1.5 leading-relaxed">
                      {modelHint.wanted
                        ? <>📐 你的视频 {modelHint.sizeText}，按大小推荐「{modelHint.wanted}」但该模型本机未下载，已自动选「{modelHint.cur}」；手动切到更高档位会在任务开始时自动下载</>
                        : <>📐 已按你的视频实际大小（{modelHint.sizeText}）自动选择「{modelHint.cur}」，可手动调整</>}
                    </p>
                  )}
                  <p className="text-[11px] text-stone-400 mt-1 leading-relaxed">
                    下拉项里的 MB 是模型文件本身的下载体积（固定值，和视频无关）；实际用哪个档位由上方你的视频大小自动推荐。
                  </p>
                </Field>
              ) : (
                <div className="mt-3 grid grid-cols-1 gap-2">
                  <input className={inputCls} placeholder="API 地址，如 https://api.openai.com/v1"
                    value={cloudBase} onChange={e => setCloudBase(e.target.value)} />
                  <input className={inputCls} placeholder="API Key" type="password"
                    value={cloudKey} onChange={e => setCloudKey(e.target.value)} />
                  <input className={inputCls} placeholder="识别模型（默认 whisper-1）"
                    value={cloudModel} onChange={e => setCloudModel(e.target.value)} />
                </div>
              )}
            </Card>
          )}

          {/* 配音设置 */}
          {upload && (
            <Card title="③ 中文配音">
              <Field label="音色">
                <div className="flex gap-2">
                  <select value={voice} onChange={e => setVoice(e.target.value)} className={`${selectCls} flex-1`}>
                    {voiceGroups.map(g => (
                      <optgroup key={g.locale} label={g.label}>
                        {g.voices.map((v: Voice) => {
                          const id = v.id ?? v.short_name ?? v.name ?? ''
                          return (
                            <option key={id} value={id}>
                              {v.gender === 'Female' ? '♀' : '♂'} {v.label} · {v.style}
                            </option>
                          )
                        })}
                      </optgroup>
                    ))}
                  </select>
                  <button onClick={onPreviewVoice}
                    className="shrink-0 px-3 rounded-xl bg-mint-50 text-mint-700 text-sm border border-mint-100 hover:bg-mint-100">
                    试听
                  </button>
                </div>
              </Field>
              <div className="grid grid-cols-2 gap-4 mt-3">
                <SliderField label="语速" value={rate} min={-50} max={100} onChange={setRate} fmt={v => v === 0 ? '默认' : `${v > 0 ? '+' : ''}${v}%`} />
                <SliderField label="音量" value={volume} min={-100} max={100} onChange={setVolume} fmt={v => v === 0 ? '默认' : `${v > 0 ? '+' : ''}${v}%`} />
              </div>
            </Card>
          )}

          {/* 输出设置 */}
          {upload && (
            <Card title="④ 输出设置">
              <div className="space-y-2.5">
                <Toggle label="智能对齐（自动变速，强烈建议开启）" checked={autoFit} onChange={setAutoFit} />
                <Toggle label="烧录中文字幕（硬字幕，随处可看）" checked={burnSub} onChange={setBurnSub} />
                <Toggle label="同时输出软字幕版（字幕可开关）" checked={softSub} onChange={setSoftSub} />
                <Toggle label="双语字幕（原文 + 中文）" checked={bilingual} onChange={setBilingual} />
                {/* 背景音：关闭 / 保留原声 / 智能去人声 */}
                <div>
                  <p className="text-sm text-stone-700 mb-1.5">背景音</p>
                  <div className="grid grid-cols-3 gap-2">
                    {([
                      { id: 'off', label: '不要背景音', sub: '只要中文配音' },
                      { id: 'original', label: '保留原声', sub: '含原片人声' },
                      { id: 'instrumental', label: '智能背景音', sub: '去人声 · 推荐' },
                    ] as const).map(opt => {
                      const active = bgmMode === opt.id
                      return (
                        <button key={opt.id} type="button" onClick={() => onPickBgm(opt.id)}
                          className={`px-2 py-2 rounded-xl border text-center transition ${
                            active
                              ? 'border-mint-400 bg-mint-50 ring-1 ring-mint-300'
                              : 'border-stone-200 bg-white hover:border-mint-200'
                          }`}>
                          <span className={`block text-xs font-medium ${active ? 'text-mint-700' : 'text-stone-600'}`}>
                            {opt.label}
                          </span>
                          <span className="block text-[10px] text-stone-400 mt-0.5">{opt.sub}</span>
                        </button>
                      )
                    })}
                  </div>
                  {bgmMode !== 'off' && (
                    <div className="mt-2.5 space-y-2">
                      <SliderField
                        label={bgmMode === 'instrumental' ? '背景乐音量' : '原声背景音量'}
                        value={bgmVolume} min={0} max={100}
                        onChange={setBgmVolume} fmt={v => `${v}%`} />
                      <Toggle label="智能闪避（配音说话自动压低背景，停顿间隙恢复）"
                        checked={bgmDucking} onChange={setBgmDucking} />
                      {bgmMode === 'instrumental' && (
                        <p className="text-[11px] text-stone-400 leading-relaxed">
                          通过左右声道反相消除居中的原片人声，保留背景音乐与环境声；
                          单声道视频无法分离，会自动改回「保留原声」。
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <button onClick={() => setShowAdvanced(s => !s)}
                className="mt-3 text-xs text-stone-400 hover:text-mint-600">
                {showAdvanced ? '收起高级设置 ▲' : '高级设置（LLM 高质量翻译等）▼'}
              </button>
              {showAdvanced && (
                <AdvancedTranslate />
              )}
              <button
                onClick={() => startJob()}
                disabled={busy || !upload}
                className="mt-4 w-full py-3 rounded-2xl bg-mint-600 text-white font-medium shadow-soft
                  hover:bg-mint-700 active:scale-[0.99] transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {busy ? '提交中…' : '🚀 开始生成中文配音视频'}
              </button>
            </Card>
          )}
        </>
      )}

      {/* ---------------- 处理中 ---------------- */}
      {phase === 'running' && job && (
        <Card title="处理进度">
          <p className="text-sm text-stone-600 truncate mb-4">📹 {job.filename}</p>
          <div className="space-y-2">
            {STAGE_ORDER.map((key, i) => {
              const done = i < stageIdx || job.status === 'done'
              const active = i === stageIdx
              return (
                <div key={key} className={`flex items-center gap-3 text-sm ${
                  active ? 'text-mint-700 font-medium' : done ? 'text-stone-500' : 'text-stone-300'
                }`}>
                  <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs shrink-0 ${
                    done ? 'bg-mint-500 text-white' : active ? 'bg-mint-100 text-mint-700' : 'bg-stone-100'
                  }`}>
                    {done ? '✓' : i + 1}
                  </span>
                  <span className="flex-1">{STAGE_LABELS[key]}</span>
                  {active && <span className="text-xs text-mint-500">{(job.progress * 100).toFixed(0)}%</span>}
                </div>
              )
            })}
          </div>
          <div className="w-full h-2 bg-stone-100 rounded-full mt-4 overflow-hidden">
            <div className="h-full bg-mint-500 rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, job.progress * 100)}%` }} />
          </div>
          {job.message && <p className="text-xs text-stone-400 mt-3 leading-relaxed">{job.message}</p>}
          {job.logs?.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-stone-400 cursor-pointer">处理日志</summary>
              <pre className="mt-2 text-[11px] text-stone-400 bg-stone-50 rounded-lg p-2 max-h-40 overflow-auto whitespace-pre-wrap">
                {job.logs.slice(-15).join('\n')}
              </pre>
            </details>
          )}
          <p className="text-xs text-mint-600 mt-3">💡 返回首页不会中断任务，可随时回到本页查看进度</p>
          <button onClick={onCancel}
            className="mt-2 w-full py-2.5 rounded-xl border border-red-200 text-red-500 text-sm hover:bg-red-50">
            取消任务
          </button>
        </Card>
      )}

      {/* 失败提示（回到 setup 时保留 job 信息） */}
      {phase === 'setup' && job?.status === 'failed' && (
        <Card title="❌ 处理失败">
          <p className="text-sm text-red-600 whitespace-pre-wrap">{job.error || '未知错误'}</p>
          <div className="flex gap-2 mt-3">
            <button onClick={() => startJob()} className="px-4 py-2 rounded-xl bg-mint-600 text-white text-sm">重试</button>
            <button onClick={resetAll} className="px-4 py-2 rounded-xl border border-stone-200 text-sm text-stone-600">重新开始</button>
          </div>
        </Card>
      )}

      {/* ---------------- 历史任务清单 ---------------- */}
      {phase === 'setup' && history.length > 0 && (
        <Card title={`📋 历史任务（${history.length}）`}>
          <div className="space-y-2 max-h-96 overflow-auto pr-1">
            {history.map(h => (
              <div key={h.id}
                className="flex items-center gap-2 px-3 py-2 rounded-xl bg-stone-50 border border-stone-100">
                <span className="text-base shrink-0">
                  {h.status === 'done' ? '✅'
                    : h.status === 'running' || h.status === 'pending' ? '⏳'
                    : h.status === 'failed' ? '❌' : '🚫'}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-stone-700 truncate">{h.filename}</p>
                  <p className="text-[11px] text-stone-400">
                    {new Date(h.created_at * 1000).toLocaleString('zh-CN', { hour12: false })}
                    {h.total_seconds ? ` · 耗时 ${fmtTime(h.total_seconds)}` : ''}
                    {h.status === 'running' || h.status === 'pending' ? ' · 进行中' : ''}
                    {h.status === 'failed' ? ' · 失败' : ''}
                    {h.status === 'cancelled' ? ' · 已取消' : ''}
                  </p>
                </div>
                {(h.status === 'done' || h.status === 'failed'
                  || h.status === 'running' || h.status === 'pending') && (
                  <button onClick={() => openHistoryJob(h.id)}
                    className="px-3 py-1.5 rounded-lg bg-mint-50 border border-mint-100 text-mint-700 text-xs hover:bg-mint-100 shrink-0">
                    {h.status === 'done' ? '查看结果' : '查看进度'}
                  </button>
                )}
                {h.status !== 'running' && h.status !== 'pending' && (
                  <button onClick={() => removeHistory(h.id)}
                    className="px-2 py-1.5 rounded-lg text-stone-300 hover:text-red-500 text-xs shrink-0"
                    title="删除任务">
                    🗑
                  </button>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ---------------- 完成 ---------------- */}
      {phase === 'finished' && job && (
        <Card title="✅ 生成完成">
          <p className="text-sm text-stone-600 truncate mb-3">{job.filename}</p>

          {/* 耗时统计：各环节 + 总计 */}
          {job.stage_timings && Object.keys(job.stage_timings).length > 0 && (
            <div className="mb-3 p-3 rounded-xl bg-stone-50 border border-stone-100">
              <p className="text-[11px] text-stone-400 mb-2">⏱ 耗时统计</p>
              <div className="flex flex-wrap gap-1.5">
                {STAGE_ORDER.filter(k => job.stage_timings?.[k]).map(k => (
                  <span key={k} className="px-2 py-0.5 rounded-lg bg-white border border-stone-200 text-[11px] text-stone-500">
                    {STAGE_LABELS[k]} {fmtTime(job.stage_timings![k])}
                  </span>
                ))}
                {job.total_seconds != null && job.total_seconds > 0 && (
                  <span className="px-2 py-0.5 rounded-lg bg-mint-50 border border-mint-200 text-[11px] text-mint-700 font-medium">
                    总计 {fmtTime(job.total_seconds)}
                  </span>
                )}
              </div>
            </div>
          )}

          {videoOutputs.length > 0 && (
            <video
              key={job.id}
              src={previewVideoUrl(job.id, 0)}
              controls
              className="w-full rounded-2xl bg-black max-h-[60vh]"
            />
          )}

          {/* 下载 */}
          <div className="mt-3 space-y-2">
            {job.outputs.map((o, i) => (
              <a key={i} href={downloadUrl(job.id, i)}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-mint-50 border border-mint-100
                  text-sm text-mint-700 hover:bg-mint-100 transition group">
                <span className="text-lg">{o.kind === 'video' ? '🎬' : o.name.endsWith('.srt') ? '📝' : '📄'}</span>
                <span className="flex-1 truncate">{o.name}</span>
                <span className="text-xs opacity-60 group-hover:opacity-100">下载 ↓</span>
              </a>
            ))}
          </div>

          {/* 发布到作品库（暂时隐藏，恢复时把 SHOW_PUBLISH 改回 true） */}
          {SHOW_PUBLISH && videoOutputs.length > 0 && (
            <div className="mt-3 p-3 rounded-xl border border-violet-100 bg-violet-50/50">
              {published ? (
                <div>
                  <p className="text-sm text-violet-800 font-medium">🎉 已发布到作品库</p>
                  <p className="mt-1 text-xs text-violet-700/70 leading-relaxed">
                    视频已上传 GitHub。网站清单提交后会触发自动部署，约 1 分钟后他人即可访问；
                    重复发布会更新这一条。
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {published.pages_url && (
                      <a href={published.pages_url} target="_blank" rel="noreferrer"
                        className="px-3 py-1.5 rounded-lg bg-violet-600 text-white text-xs hover:bg-violet-700">
                        打开作品库 ↗
                      </a>
                    )}
                    <button onClick={() => { setPublished(null); setPubOpen(true) }}
                      className="px-3 py-1.5 rounded-lg border border-violet-200 text-violet-700 text-xs bg-white/70 hover:bg-white">
                      更新发布信息
                    </button>
                  </div>
                  {published.repo_private && (
                    <p className="mt-2 text-[11px] text-amber-600 leading-relaxed">
                      ⚠️ 当前 GitHub 仓库是私有的，别人无法播放，请在 GitHub 仓库 Settings 最底部把仓库改为 Public。
                    </p>
                  )}
                </div>
              ) : !pubOpen ? (
                <button onClick={onPublish} disabled={publishing}
                  className="w-full py-2.5 rounded-xl bg-violet-600 text-white text-sm hover:bg-violet-700 disabled:opacity-60">
                  🌐 发布到作品库（他人可在线播放 / 下载）
                </button>
              ) : (
                <div className="space-y-2">
                  {pubCfg && !pubCfg.configured ? (
                    <div className="text-xs text-stone-600 leading-relaxed">
                      <p className="text-violet-800 font-medium mb-1">首次使用，先配置 GitHub 发布：</p>
                      <ol className="list-decimal pl-4 space-y-1">
                        <li>
                          到 GitHub → Settings → Developer settings → Personal access tokens →
                          Tokens (classic) 生成一个 Token，勾选 <b>repo</b> 权限；
                        </li>
                        <li>
                          打开本机 <code className="px-1 bg-white rounded">video-service/service.json</code>
                          （可从 service.example.json 复制），填入：
                        </li>
                      </ol>
                      <pre className="mt-1.5 p-2 rounded-lg bg-white border border-stone-200 text-[11px] overflow-x-auto">{`"github_token": "ghp_你的token",
"github_repo": "lxt-promise/mustardseed"`}</pre>
                      <p className="mt-1">3. 重启本地视频服务后即可发布。Token 只存在本机，不会提交到仓库。</p>
                      <button onClick={() => setPubOpen(false)}
                        className="mt-2 px-3 py-1.5 rounded-lg border border-stone-200 text-stone-600 bg-white hover:bg-stone-50">
                        知道了
                      </button>
                    </div>
                  ) : (
                    <>
                      <input value={pubTitle} onChange={e => setPubTitle(e.target.value)}
                        maxLength={80} placeholder="作品标题"
                        className="w-full text-sm rounded-lg border border-stone-200 px-3 py-2 bg-white focus:border-violet-400 outline-none" />
                      <textarea value={pubNote} onChange={e => setPubNote(e.target.value)}
                        maxLength={200} rows={2} placeholder="一句话介绍（可选）"
                        className="w-full text-sm rounded-lg border border-stone-200 px-3 py-2 bg-white resize-y focus:border-violet-400 outline-none" />
                      {publishing && (
                        <p className="text-xs text-violet-700/80">
                          正在上传到 GitHub，请耐心等待，不要关闭页面…（视频越大越久）
                        </p>
                      )}
                      <div className="grid grid-cols-2 gap-2">
                        <button onClick={() => { setPubOpen(false); setPubError('') }}
                          disabled={publishing}
                          className="py-2 rounded-lg border border-stone-200 text-sm text-stone-600 disabled:opacity-50">
                          取消
                        </button>
                        <button onClick={onPublish} disabled={publishing || !pubTitle.trim()}
                          className="py-2 rounded-lg bg-violet-600 text-white text-sm disabled:opacity-50">
                          {publishing ? '上传中…' : '确认发布'}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
              {pubError && (
                <p className="mt-2 text-xs text-red-500 leading-relaxed">发布失败：{pubError}</p>
              )}
            </div>
          )}

          {/* 字幕编辑 */}
          {editingSegs.length > 0 && (
            <div className="mt-4">
              <button onClick={() => setShowEditor(s => !s)}
                className="w-full py-2.5 rounded-xl border border-mint-200 text-mint-700 text-sm bg-mint-50/50 hover:bg-mint-50">
                {showEditor ? '收起字幕校对' : `✏️ 查看 / 修改台词译文（${editingSegs.length} 条）`}
              </button>
              {showEditor && (
                <div className="mt-3 space-y-2 max-h-96 overflow-auto pr-1">
                  {editingSegs.map((s, i) => (
                    <div key={i} className="p-2.5 rounded-xl bg-stone-50 border border-stone-100">
                      <div className="text-[11px] text-stone-400 mb-1">
                        {fmtTime(s.start)} → {fmtTime(s.end)}
                      </div>
                      <p className="text-xs text-stone-500 mb-1.5 leading-relaxed">{s.text}</p>
                      <textarea
                        value={s.translated}
                        onChange={e => setEditingSegs(prev =>
                          prev.map((x, j) => j === i ? { ...x, translated: e.target.value } : x))}
                        rows={2}
                        className="w-full text-sm rounded-lg border border-stone-200 p-2 resize-y focus:border-mint-400 outline-none"
                      />
                    </div>
                  ))}
                  <button onClick={onSaveEditAndRedub} disabled={busy}
                    className="w-full py-2.5 rounded-xl bg-mint-600 text-white text-sm disabled:opacity-50">
                    {busy ? '提交中…' : '💾 保存修改并重新配音（只重跑合成，很快）'}
                  </button>
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 mt-4">
            <button onClick={onRedo} disabled={busy}
              className="py-2.5 rounded-xl border border-stone-200 text-sm text-stone-600 disabled:opacity-50">
              换音色/设置重跑
            </button>
            <button onClick={resetAll}
              className="py-2.5 rounded-xl bg-mint-600 text-white text-sm">
              转换新视频
            </button>
          </div>
        </Card>
      )}
    </div>
  )
}

// ================================================================ 子组件
const selectCls = 'w-full text-sm rounded-xl border border-stone-200 px-3 py-2 bg-white focus:border-mint-400 outline-none'
const inputCls = 'w-full text-sm rounded-xl border border-stone-200 px-3 py-2 bg-white focus:border-mint-400 outline-none'

const Card: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <section className="bg-white rounded-2xl shadow-card border border-stone-100 p-4 sm:p-5">
    <h2 className="text-base font-semibold text-stone-800 mb-3">{title}</h2>
    {children}
  </section>
)

const Field: React.FC<{ label: React.ReactNode; children: React.ReactNode; className?: string }> = ({ label, children, className }) => (
  <div className={className}>
    <label className="block text-xs text-stone-500 mb-1.5">{label}</label>
    {children}
  </div>
)

const SliderField: React.FC<{
  label: string; value: number; min: number; max: number
  onChange: (v: number) => void; fmt: (v: number) => string
}> = ({ label, value, min, max, onChange, fmt }) => (
  <div>
    <div className="flex justify-between text-xs text-stone-500 mb-1">
      <span>{label}</span>
      <span className="text-mint-600 font-medium">{fmt(value)}</span>
    </div>
    <input type="range" min={min} max={max} value={value}
      onChange={e => onChange(Number(e.target.value))}
      className="w-full accent-mint-600" />
  </div>
)

const Toggle: React.FC<{ label: string; checked: boolean; onChange: (v: boolean) => void }> = ({ label, checked, onChange }) => (
  <label className="flex items-center gap-2.5 text-sm text-stone-700 cursor-pointer">
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`relative w-10 h-6 rounded-full transition-colors shrink-0 ${checked ? 'bg-mint-500' : 'bg-stone-200'}`}
    >
      <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-all ${checked ? 'left-[18px]' : 'left-0.5'}`} />
    </button>
    {label}
  </label>
)

/** 高级：LLM 翻译配置（存 localStorage，下次自动带） */
const AdvancedTranslate: React.FC = () => {
  const [cfg, setCfg] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('dub-llm') ?? '{}')
    } catch { return {} }
  })
  const update = (k: string, v: string) => {
    const next = { ...cfg, [k]: v }
    setCfg(next)
    localStorage.setItem('dub-llm', JSON.stringify(next))
  }
  return (
    <div className="mt-3 p-3 rounded-xl bg-stone-50 space-y-2">
      <p className="text-xs text-stone-500">
        留空翻译走免费公益通道；追求质量可填 OpenAI 兼容接口（DeepSeek 等），Key 仅保存在本浏览器。
      </p>
      <input className={inputCls} placeholder="翻译接口地址，如 https://api.deepseek.com/v1"
        value={cfg.translate_base_url ?? ''} onChange={e => update('translate_base_url', e.target.value)} />
      <input className={inputCls} placeholder="翻译 API Key" type="password"
        value={cfg.translate_api_key ?? ''} onChange={e => update('translate_api_key', e.target.value)} />
      <input className={inputCls} placeholder="模型名，如 deepseek-chat"
        value={cfg.translate_model ?? ''} onChange={e => update('translate_model', e.target.value)} />
    </div>
  )
}

/** 本地服务未运行 */
const OfflineCard: React.FC<{ onRetry: () => void }> = ({ onRetry }) => (
  <div className="space-y-4">
    <div>
      <h1 className="text-2xl font-bold text-stone-800 flex items-center gap-2">🎬 视频译制</h1>
      <p className="text-sm text-stone-500 mt-1">英文视频 → 中文配音 + 中文字幕</p>
    </div>
    <div className="bg-white rounded-2xl shadow-card border border-amber-100 p-6">
      <div className="text-4xl mb-3">🖥️</div>
      <h2 className="text-lg font-semibold text-stone-800">本地译制服务未运行</h2>
      <p className="text-sm text-stone-500 mt-2 leading-relaxed">
        视频处理在你自己的电脑上完成（不上传服务器，保护隐私）。
        使用前请先启动随项目附带的本地服务：
      </p>
      <ol className="mt-3 space-y-2 text-sm text-stone-600 list-decimal list-inside">
        <li>打开项目目录 <code className="px-1.5 py-0.5 rounded bg-stone-100 text-xs">video-service</code></li>
        <li>双击运行 <code className="px-1.5 py-0.5 rounded bg-stone-100 text-xs">start.bat</code></li>
        <li>看到 <code className="px-1.5 py-0.5 rounded bg-stone-100 text-xs">Uvicorn running</code> 后回到本页</li>
      </ol>
      <div className="mt-3 p-3 rounded-xl bg-stone-50 text-xs text-stone-500 leading-relaxed">
        服务地址：<code>{DUB_BASE_URL}</code>
        （部署后可改构建产物里的 <code>dub-config.json</code>，无需重新构建）<br />
        首次使用需 Python 环境与依赖，详见 <code>video-service/README.md</code>
      </div>
      <button onClick={onRetry}
        className="mt-4 px-5 py-2.5 rounded-xl bg-mint-600 text-white text-sm hover:bg-mint-700">
        🔄 已启动，重新检测
      </button>
    </div>
  </div>
)

export default Dub
