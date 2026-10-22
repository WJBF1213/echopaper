/** Typed client for the FastAPI contract (design spec §8). */
import { locale, t } from './i18n'

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

const BASE = '/api'

function withLocale(init?: RequestInit): RequestInit {
  // Backend messages (job stages, validation errors) follow this header.
  const headers = new Headers(init?.headers)
  headers.set('Accept-Language', locale.value === 'zh' ? 'zh-CN' : locale.value)
  return { ...init, headers }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, withLocale(init))
  } catch (err) {
    throw new ApiError(0, t('api.offline', { error: err instanceof Error ? err.message : String(err) }))
  }
  const contentType = res.headers.get('content-type') || ''
  const payload: unknown = contentType.includes('application/json')
    ? await res.json().catch(() => null)
    : await res.text().catch(() => '')
  if (!res.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : typeof payload === 'string' && payload
          ? payload
          : t('api.httpError', { status: res.status })
    throw new ApiError(res.status, detail)
  }
  return payload as T
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

/* ------------------------------------------------------------------ types */

export interface Health {
  ok: boolean
  version: string
}

export interface AsrStatus {
  state: 'unloaded' | 'loading' | 'ready' | 'error'
  engine: string
  model: string
  last_used?: string | null
  idle_unload_min: number
  detail?: string | null
}

export interface LlmSettings {
  provider: string
  base_url: string
  model: string
  max_context_tokens: number
  has_key: boolean
  key_masked: string | null
}

export interface AsrSettings {
  engine: string
  parakeet_model: string
  whisper_model: string
  faster_whisper_model: string
  idle_unload_min: number
  available_engines: string[]
  default_engine: string
}

export interface GenSettings {
  blank_count: number
}

/** One prompt-registry entry from GET /api/prompts (title follows locale). */
export interface PromptEntry {
  key: string
  title: string
  category: string
  variables: string[]
  default: string
  current: string
  customized: boolean
}

export interface Settings {
  llm: LlmSettings
  asr: AsrSettings
  gen: GenSettings
}

export interface SettingsPatch {
  llm?: Partial<Pick<LlmSettings, 'provider' | 'base_url' | 'model' | 'max_context_tokens'>> & {
    api_key?: string
  }
  asr?: Partial<AsrSettings>
  gen?: Partial<GenSettings>
}

export interface MaterialListItem {
  id: string
  name: string
  duration_s: number | null
  created_at: string
  transcript_source: string
  sets_count: number
  best_score: number | null
  last_practice: string | null
  has_audio: number | boolean
}

export interface SetSummary {
  id: string
  mode: 'llm' | 'nouns' | 'manual' | string
  blank_count: number
  stale: number
  created_at: string
}

export interface Word {
  w: string
  s: number
  e: number
  p?: number
}

export interface MaterialDetail {
  id: string
  name: string
  source_type: 'upload' | 'url' | string
  audio_url: string | null
  duration_s: number | null
  has_audio: boolean
  transcript: string
  transcript_source: 'asr' | 'aligned' | 'manual' | string
  asr_model: string | null
  words: Word[]
  sentences: [number, number][]
  sets: SetSummary[]
  created_at: string
  updated_at: string
}

export interface Blank {
  id: string
  position: number
  answer: string
  alternatives: string[]
  word_start: number
  word_end: number
  t_start: number
  t_end: number
  type: string
  word_limit: string
}

export interface SetDetail {
  id: string
  material_id: string
  mode: string
  blank_count: number
  stale: number
  created_at: string
  blanks: Blank[]
}

export type JobState =
  | 'queued'
  | 'downloading'
  | 'transcribing'
  | 'generating'
  | 'done'
  | 'error'

export interface Job {
  id: string
  state: JobState
  message: string | null
  percent: number | null
  material_id: string | null
  file_name?: string | null
  position?: number | null
  created_at: string
  updated_at: string
}

export interface BatchJobItem {
  job_id: string
  state: JobState
  message: string | null
  percent: number | null
  material_id: string | null
  file_name: string | null
  position: number | null
  created_at: string
  updated_at: string
}

export interface BatchStatus {
  id: string
  name: string
  total: number
  done: number
  error: number
  running: number
  percent: number
  created_at: string
  updated_at: string
  jobs: BatchJobItem[]
}

export interface BatchSummary {
  id: string
  name: string
  total: number
  done: number
  error: number
  running: number
  percent: number
  created_at: string
  updated_at: string
}

export interface AttemptItemResult {
  blank_id: string
  correct: boolean
  expected: string
  user_text: string
}

export interface AttemptResult {
  attempt_id: string
  ok: number
  total: number
  results: AttemptItemResult[]
}

export interface DictationItemResult {
  word_index: number
  correct: boolean
  expected: string
  t_start: number | null
  user_text: string
}

export interface DictationResult {
  attempt_id: string
  ok: number
  total: number
  results: DictationItemResult[]
}

export interface AttemptHistoryItem {
  id: string
  set_id: string | null
  mode: string
  started_at: string | null
  finished_at: string | null
  ok: number
  total: number
  duration_s: number | null
}

export interface WrongWord {
  word: string
  times_wrong: number
  last_at: string | null
  material_id: string
  t_start: number | null
}

export interface Stats {
  materials: number
  attempts: number
  avg_score: number | null
}

/* ------------------------------------------------------- full paper (exam) */

export interface ExamEvidence {
  i0: number
  i1: number
  quote: string
  t_start: number
  t_end: number
}

export interface ExamItem {
  number: number
  type: string
  stem: string
  answer: string
  options: string[]
  evidence: ExamEvidence[]
  word_limit: string | null
  label: string
  alternatives: string[]
  group_title: string
}

export interface ExamGroup {
  type: string
  title: string
  instruction: string
  /** Shared option pool for matching; empty for other types. */
  options: string[]
  items: ExamItem[]
}

export interface ExamPresetInfo {
  key: string
  part: number
  label: string
  total_items: number
  groups: { type: string; count: number }[]
}

/** The leaner echo returned next to a generated paper. */
export interface ExamPresetRef {
  key: string
  label: string
}

export interface ExamTypeInfo {
  key: string
  label: string
  parts: number[]
  answer_kind: 'span' | 'option' | 'option_multi' | 'matching' | string
  needs_visual: boolean
  word_limit: string | null
  instruction: string
}

export interface ExamTypes {
  types: ExamTypeInfo[]
  presets: ExamPresetInfo[]
}

export interface ExamPaper {
  material_id: string
  part: number
  preset: string
  total_items: number
  warnings: string[]
  available_presets: ExamPresetRef[]
  groups: ExamGroup[]
}

export interface CreateMaterialInput {
  name: string
  audioFile?: File | null
  audioUrl?: string
  transcript?: string
  mode: string
  blankCount: number
}

export interface CreateBatchInput {
  files: File[]
  name?: string
  generateSets?: boolean
  mode?: string
  blankCount?: number
}

/* --------------------------------------------------------------- endpoints */

export const api = {
  health: () => request<Health>('/health'),

  asrStatus: () => request<AsrStatus>('/asr/status'),
  asrLoad: () => request<AsrStatus>('/asr/load', { method: 'POST' }),
  asrUnload: () => request<AsrStatus>('/asr/unload', { method: 'POST' }),

  getSettings: () => request<Settings>('/settings'),
  updateSettings: (patch: SettingsPatch) =>
    request<Settings>('/settings', jsonInit('PUT', patch)),
  testLlm: (
    llm?: Partial<Pick<LlmSettings, 'provider' | 'base_url' | 'model'>> & { api_key?: string },
  ) =>
    request<{ ok: boolean; message: string }>(
      '/settings/test-llm',
      jsonInit('POST', llm ?? {}),
    ),

  listPrompts: () => request<PromptEntry[]>('/prompts'),
  putPrompt: (key: string, text: string) =>
    request<PromptEntry>('/prompts', jsonInit('PUT', { key, text })),
  clearLlmCache: () => request<{ deleted: number }>('/llm-cache', { method: 'DELETE' }),

  listMaterials: (q = '') =>
    request<MaterialListItem[]>(`/materials${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  createMaterial: (input: CreateMaterialInput) => {
    const form = new FormData()
    form.append('name', input.name || t('common.untitledMaterial'))
    form.append('mode', input.mode)
    form.append('blank_count', String(input.blankCount))
    if (input.transcript) form.append('transcript', input.transcript)
    if (input.audioUrl) form.append('audio_url', input.audioUrl)
    if (input.audioFile) form.append('audio', input.audioFile)
    return request<{ job_id: string }>('/materials', { method: 'POST', body: form })
  },
  createMaterialsBatch: (input: CreateBatchInput) => {
    const form = new FormData()
    form.append('name', input.name || '')
    form.append('mode', input.mode || 'nouns')
    form.append('blank_count', String(input.blankCount ?? 10))
    form.append('generate_sets', input.generateSets ? 'true' : 'false')
    for (const file of input.files) form.append('audios', file)
    return request<{
      batch_id: string
      name: string
      jobs: { job_id: string; file_name: string; name: string; position: number }[]
    }>('/materials/batch', { method: 'POST', body: form })
  },
  getMaterial: (id: string) => request<MaterialDetail>(`/materials/${id}`),
  updateTranscript: (id: string, transcript: string) =>
    request<{
      id: string
      transcript_source: string
      message: string | null
      stale_sets: string[]
    }>(`/materials/${id}/transcript`, jsonInit('PUT', { transcript })),
  deleteMaterial: (id: string) =>
    request<{ ok: boolean }>(`/materials/${id}`, { method: 'DELETE' }),
  audioUrl: (id: string) => `${BASE}/materials/${id}/audio`,

  getJob: (id: string) => request<Job>(`/jobs/${id}`),

  listBatches: () => request<BatchSummary[]>('/batches'),
  getBatch: (id: string) => request<BatchStatus>(`/batches/${id}`),

  createSet: (materialId: string, mode: string, blankCount: number, transcriptOverride?: string) =>
    request<{ set_id: string }>(
      `/materials/${materialId}/sets`,
      jsonInit('POST', {
        mode,
        blank_count: blankCount,
        transcript_override: transcriptOverride,
      }),
    ),
  getSet: (id: string) => request<SetDetail>(`/sets/${id}`),
  deleteSet: (id: string) => request<{ ok: boolean }>(`/sets/${id}`, { method: 'DELETE' }),

  submitAttempt: (
    setId: string,
    answers: { blank_id: string; text: string }[],
    durationS?: number,
  ) =>
    request<AttemptResult>(
      `/sets/${setId}/attempts`,
      jsonInit('POST', { answers, duration_s: durationS }),
    ),
  submitDictation: (
    materialId: string,
    items: { word_index: number; text: string }[],
    durationS?: number,
  ) =>
    request<DictationResult>(
      `/materials/${materialId}/attempts`,
      jsonInit('POST', { mode: 'dictation', items, duration_s: durationS }),
    ),
  getAttempts: (materialId: string) =>
    request<AttemptHistoryItem[]>(`/materials/${materialId}/attempts`),

  getWrongWords: () => request<WrongWord[]>('/review/wrong-words'),
  getStats: () => request<Stats>('/stats'),

  translate: (text: string) =>
    request<{ text: string; error?: string }>('/translate', jsonInit('POST', { text })),

  examTypes: () => request<ExamTypes>('/exam/types'),
  generateExam: (materialId: string, part: number, preset?: string) =>
    request<ExamPaper>(
      `/materials/${materialId}/exam`,
      jsonInit('POST', { part, preset: preset || null }),
    ),
}
