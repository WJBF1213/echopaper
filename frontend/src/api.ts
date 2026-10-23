/** Typed client for the FastAPI contract (design spec §8). */
import { locale, t } from './i18n'

export class ApiError extends Error {
  status: number
  detail: string
  /** The raw error detail when the server sent a structured object body
   * (e.g. the all-refused 400 answers `{"detail": {"skipped": [...]}}`). */
  data?: unknown

  constructor(status: number, detail: string, data?: unknown) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.data = data
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
    let detail = ''
    let data: unknown
    const objDetail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? (payload as { detail: unknown }).detail
        : undefined
    if (objDetail !== undefined && objDetail !== null && typeof objDetail === 'object') {
      // Structured body (all-refused skipped list, validation errors):
      // keep the object on .data and stringify it for the message.
      data = objDetail
      detail = JSON.stringify(objDetail)
    } else if (objDetail !== undefined) {
      detail = String(objDetail)
    } else if (typeof payload === 'string' && payload) {
      detail = payload
    } else {
      detail = t('api.httpError', { status: res.status })
    }
    throw new ApiError(res.status, detail, data)
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

/** GET /api/settings → asr (Task 3 shape). ``engine`` is derived
 * server-side: ``cloud`` in cloud mode, else the platform's one local
 * engine; the raw cloud key is never returned (mask fields instead). */
export interface AsrSettings {
  mode: 'local' | 'cloud'
  engine: string
  idle_unload_min: number
  cloud_base_url: string
  cloud_model: string
  has_cloud_key: boolean
  cloud_key_masked: string | null
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
}

export interface SettingsPatch {
  llm?: Partial<Pick<LlmSettings, 'provider' | 'base_url' | 'model' | 'max_context_tokens'>> & {
    api_key?: string
  }
  /** ``cloud_api_key: ""`` keeps the stored key (backend treats blank as
   * "no change"); send the raw key only when the user typed a new one. */
  asr?: Partial<Pick<AsrSettings, 'mode' | 'idle_unload_min' | 'cloud_base_url' | 'cloud_model'>> & {
    cloud_api_key?: string
  }
}

/** One row of GET /api/materials (design §六): paper-based counts. */
export interface MaterialListItem {
  id: string
  name: string
  duration_s: number | null
  created_at: string
  transcript_source: string
  papers_count: number
  attempts_count: number
  last_practice: string | null
  has_audio: number | boolean
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
  created_at: string
  updated_at: string
}

/** Pipeline states (design §7.2): queued → downloading → transcribing →
 * translating → done; the exam 'generating' stage died with §5.3. */
export type JobState =
  | 'queued'
  | 'downloading'
  | 'transcribing'
  | 'translating'
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

/** One row of GET /api/review/wrong-words (redesign §5.2): wrong items
 * aggregated by answer text; the jump coordinates point at the most
 * recent wrong attempt's paper, and t_start is that item's evidence
 * start inside the stored paper (auto-seek not wired yet). */
export interface WrongWord {
  word: string
  times_wrong: number
  last_at: string | null
  material_id: string
  paper_id: string
  item_number: number
  t_start: number | null
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
  /** Presentation layout (completion only, design §4.1); null elsewhere. */
  layout: string | null
  label: string
  alternatives: string[]
  group_title: string
  /** Text of the keyed option, for matching types. */
  answer_text: string
  /** The numbered map blank this item asks about (map items only);
   * absent on every non-map item. */
  slot?: number
}

/** One question type from GET /api/exam/types (registry shape, §4.2). */
export interface ExamTypeInfo {
  key: string
  /** Localized per the request locale; prefer name_zh/name_en client-side. */
  name: string
  name_zh: string
  name_en: string
  answer_kind: 'span' | 'option' | 'option_multi' | 'matching' | string
  layouts: string[]
  generates_visual: boolean
  max_count: number
  min_words: number
}

export interface ExamTypes {
  types: ExamTypeInfo[]
}

/** One requested block: {type, count} in user order (design §4.4). */
export interface ExamBlock {
  type: string
  count: number
}

/** A refused block (design §4.5): the type key and a one-line reason. */
export interface SkippedBlock {
  type: string
  reason: string
}

export interface MapSceneNode {
  id: string
  x: number
  y: number
  shape: 'rect' | 'circle' | string
  /** Printed on the map when fixed. */
  fixed?: boolean
  label?: string
  /** 1-based continuous slot number for blank nodes. */
  blank_slot?: number
}

export interface MapScenePath {
  from: string
  to: string
  label: string
}

/** Drawable scene in normalized 0-100 coordinates (design §4.3). */
export interface MapSceneData {
  canvas: { width: number; height: number }
  nodes: MapSceneNode[]
  paths: MapScenePath[]
}

export interface ExamVisual {
  kind: 'map' | 'plan' | 'diagram' | string
  scene: MapSceneData
}

export interface ExamGroup {
  type: string
  title: string
  instruction: string
  /** Shared option pool for matching; empty for other types. */
  options: string[]
  /** True when the block produced fewer items than requested (§4.5). */
  partial: boolean
  /** Scene asset for visual types (map_labelling); null elsewhere. */
  visual: ExamVisual | null
  items: ExamItem[]
}

export interface ExamPaper {
  material_id: string
  total_items: number
  warnings: string[]
  groups: ExamGroup[]
}

/** The request spec persisted with a paper (design §5.1): what the user
 * asked for when the paper was generated. */
export interface PaperSpec {
  blocks: ExamBlock[]
  layout_hint: string | null
  regenerate: boolean
}

/** One entry of a paper's persisted generation usage ledger (§8):
 * per-call token accounting as recorded at generation time. */
export interface GenerationUsageEntry {
  task: string
  prompt_tokens: number
  completion_tokens: number
  cached_tokens: number
  cached_hit: boolean
}

/** One row of GET /api/materials/{id}/papers (design §5.2): the paper's
 * type:count composition (of what actually generated, not the request),
 * total item count, staleness and creation time. */
export interface PaperSummary {
  id: string
  blocks: { type: string; count: number }[]
  item_count: number
  /** True once the material's transcript was edited after generation;
   * stale papers stay fetchable and answerable (§5.2). */
  stale: boolean
  created_at: string
}

/** GET /api/papers/{id}: the stored spec plus the full paper JSON, and
 * the parsed generation usage ledger for observability (§8). */
export interface PaperDetail {
  id: string
  material_id: string
  spec: PaperSpec
  paper: ExamPaper
  /** Per-call LLM usage of this paper's generation (empty when absent). */
  generation: GenerationUsageEntry[]
  stale: boolean
  created_at: string
}

export interface GenerateExamResult {
  /** Id of the persisted papers row (design §5.1). */
  paper_id: string
  paper: ExamPaper
  skipped: SkippedBlock[]
}

/* ----------------------------------------------- paper attempts (§5.2, T15) */

/** One graded item of a paper attempt: the item's number/type, the
 * answer as submitted (null when unanswered), the verdict and the
 * stored answer in display form. */
export interface PaperAttemptItem {
  item_number: number
  item_type: string
  user_answer: string | null
  correct: boolean
  expected: string
}

/** POST /api/papers/{id}/attempts result: the new attempt's id plus the
 * per-item grading. No score is persisted (design §5.1). */
export interface PaperAttemptResult {
  attempt_id: string
  created_at: string
  items: PaperAttemptItem[]
}

/** One row of GET /api/papers/{id}/attempts (newest first). */
export interface PaperAttemptSummary {
  id: string
  created_at: string
  item_count: number
}

/** GET /api/attempts/{id}: one attempt's full per-item detail. */
export interface PaperAttemptDetail {
  id: string
  paper_id: string
  material_id: string
  created_at: string
  items: PaperAttemptItem[]
}

/** One row of GET /api/papers/{id}/stats: per-item accuracy; every item
 * of the paper appears, unanswered ones with attempts=0 (review page). */
export interface PaperItemStat {
  item_number: number
  item_type: string
  attempts: number
  correct: number
}

/** One row of the redesigned GET /api/stats: by-type accuracy across
 * all papers (score-free, design §5.2). */
export interface TypeStat {
  item_type: string
  attempts: number
  correct: number
  accuracy: number
}

export interface CreateMaterialInput {
  name: string
  audioFile?: File | null
  audioUrl?: string
  transcript?: string
}

/** One row of GET /api/materials/{id}/translations (design §7.3): the
 * sentence's English text and Chinese translation snapshot; dst is null
 * when the pipeline produced none (listen view shows a placeholder). */
export interface SentenceTranslation {
  index: number
  src: string
  dst: string | null
}

export interface MaterialTranslations {
  material_id: string
  sentences: SentenceTranslation[]
}

export interface CreateBatchInput {
  files: File[]
  name?: string
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
  /** Probe the cloud ASR engine with unsaved form values; a blank
   * ``cloud_api_key`` means "use the stored key" (Task 3 contract). */
  testCloudAsr: (
    asr?: Partial<Pick<AsrSettings, 'cloud_base_url' | 'cloud_model'>> & { cloud_api_key?: string },
  ) =>
    request<{ ok: boolean; message: string }>(
      '/asr/test-cloud',
      jsonInit('POST', asr ?? {}),
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
    if (input.transcript) form.append('transcript', input.transcript)
    if (input.audioUrl) form.append('audio_url', input.audioUrl)
    if (input.audioFile) form.append('audio', input.audioFile)
    return request<{ job_id: string }>('/materials', { method: 'POST', body: form })
  },
  createMaterialsBatch: (input: CreateBatchInput) => {
    const form = new FormData()
    form.append('name', input.name || '')
    for (const file of input.files) form.append('audios', file)
    return request<{
      batch_id: string
      name: string
      jobs: { job_id: string; file_name: string; name: string; position: number }[]
    }>('/materials/batch', { method: 'POST', body: form })
  },
  getMaterial: (id: string) => request<MaterialDetail>(`/materials/${id}`),
  /** Intensive-listening snapshot (§7.3): per-sentence src/dst. */
  getTranslations: (id: string) =>
    request<MaterialTranslations>(`/materials/${id}/translations`),
  updateTranscript: (id: string, transcript: string) =>
    request<{
      id: string
      transcript_source: string
      message: string | null
    }>(`/materials/${id}/transcript`, jsonInit('PUT', { transcript })),
  deleteMaterial: (id: string) =>
    request<{ ok: boolean }>(`/materials/${id}`, { method: 'DELETE' }),
  audioUrl: (id: string) => `${BASE}/materials/${id}/audio`,

  getJob: (id: string) => request<Job>(`/jobs/${id}`),

  listBatches: () => request<BatchSummary[]>('/batches'),
  getBatch: (id: string) => request<BatchStatus>(`/batches/${id}`),

  getWrongWords: () => request<WrongWord[]>('/review/wrong-words'),

  examTypes: () => request<ExamTypes>('/exam/types'),
  /** POST /api/materials/{id}/exam with free blocks (design §4.4/§5.2). */
  generateExam: (
    materialId: string,
    blocks: ExamBlock[],
    opts?: { layoutHint?: string; regenerate?: boolean },
  ) =>
    request<GenerateExamResult>(
      `/materials/${materialId}/exam`,
      jsonInit('POST', {
        blocks,
        layout_hint: opts?.layoutHint ?? null,
        regenerate: Boolean(opts?.regenerate),
      }),
    ),

  /* ------------------------------------------------- stored papers (§5.1) */

  /** The material's stored papers, newest first (design §5.2). */
  listPapers: (materialId: string) =>
    request<PaperSummary[]>(`/materials/${materialId}/papers`),
  /** One stored paper: spec + full paper JSON (scene included). */
  getPaper: (id: string) => request<PaperDetail>(`/papers/${id}`),
  deletePaper: (id: string) =>
    request<void>(`/papers/${id}`, { method: 'DELETE' }),

  /* -------------------------------------- paper attempts + stats (§5.2) */

  /** Submit answers for server-side grading; numeric keys serialize as
   * the endpoint's string-keyed answers object automatically. */
  submitPaperAttempt: (paperId: string, answers: Record<number, string>) =>
    request<PaperAttemptResult>(
      `/papers/${paperId}/attempts`,
      jsonInit('POST', { answers }),
    ),
  /** The paper's attempts, newest first, with item counts. */
  listPaperAttempts: (paperId: string) =>
    request<PaperAttemptSummary[]>(`/papers/${paperId}/attempts`),
  /** One attempt's per-item detail (single-attempt review). */
  getAttempt: (attemptId: string) =>
    request<PaperAttemptDetail>(`/attempts/${attemptId}`),
  /** Per-item accuracy for one paper; zero-attempt items included. */
  paperStats: (paperId: string) =>
    request<PaperItemStat[]>(`/papers/${paperId}/stats`),
  /** By-type accuracy across all papers (redesigned /stats). */
  globalStats: () => request<TypeStat[]>('/stats'),
}
