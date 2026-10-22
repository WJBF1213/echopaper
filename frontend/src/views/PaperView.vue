<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  ApiError,
  type ExamBlock,
  type ExamGroup,
  type ExamItem,
  type ExamPaper,
  type ExamTypeInfo,
  type GenerationUsageEntry,
  type MaterialDetail,
  type SkippedBlock,
} from '../api'
import { showToast } from '../router'
import { locale, t } from '../i18n'
import { usePlayer } from '../composables/usePlayer'
import Icon from '../components/Icon.vue'
import MapScene from '../components/MapScene.vue'
import PlayerBar from '../components/PlayerBar.vue'

const route = useRoute()
const router = useRouter()
const materialId = computed(() => String(route.params.materialId || ''))
/** Present when the view is opened on a stored paper (/paper/:m/:p). */
const paperIdParam = computed(() => String(route.params.paperId || ''))
const historical = computed(() => Boolean(paperIdParam.value))

const material = ref<MaterialDetail | null>(null)
const types = ref<ExamTypeInfo[]>([])
const paper = ref<ExamPaper | null>(null)
/** Id of the persisted papers row behind the rendered paper (§5.1). */
const paperId = ref('')
/** Transcript was edited after this paper was generated (stale stays answerable). */
const stale = ref(false)
/** Persisted per-call usage ledger of the rendered paper (§8, historical
 * view only -- the generate response carries no usage data). */
const generationUsage = ref<GenerationUsageEntry[]>([])
/** item_number -> {attempts, correct} from GET /papers/{id}/stats. */
const statsByNumber = ref<Record<number, { attempts: number; correct: number }>>({})
const skipped = ref<SkippedBlock[]>([])
/** Refusal list of an all-refused 400 (no paper came back, §4.5). */
const refusedSkipped = ref<SkippedBlock[]>([])
/** {type: requested count} of the last successful request, for partial badges. */
const requestedCounts = ref<Record<string, number>>({})
/** Generation spec (blocks + completion layout hint) of the newest paper
 * generated for this material: repeating it must send regenerate=true or
 * the temp=0 + llm_cache combination persists a byte-identical duplicate
 * paper. */
const lastSpec = ref<{ blocks: ExamBlock[]; layoutHint: string | null } | null>(null)

/** Selected blocks in click order — user order is the audio zone order (§4.4). */
const selected = ref<ExamBlock[]>([])
const layoutHint = ref('')

const loading = ref(true)
const loadError = ref('')
const generating = ref(false)
const error = ref('')
const submitting = ref(false)

const textAnswers = reactive<Record<number, string>>({})
const choiceAnswers = reactive<Record<number, string>>({})
const multiAnswers = reactive<Record<number, string[]>>({})
/** Server verdicts keyed by item number, driving the ok/bad rendering. */
const states = reactive<Record<number, 'ok' | 'bad'>>({})
const submitted = ref(false)
const showAnswers = ref(false)
/** Item number highlighted by the last map slot click. */
const activeNumber = ref<number | null>(null)

const audioEl = ref<HTMLAudioElement | null>(null)
const {
  playing,
  current: playTime,
  duration,
  rate,
  abA,
  abB,
  seek,
  pause,
  toggle,
  nudge,
  setRate,
  clearAb,
  cycleAb,
} = usePlayer(audioEl)
/** Evidence interval of the last 播放本题 click, highlighted on the bar. */
const evidenceRange = ref<{ start: number; end: number } | null>(null)
const playingNumber = ref<number | null>(null)

const LETTERS = 'ABCDEFGH'
type AnswerKind = 'span' | 'option' | 'option_multi' | 'matching'

/** Recommended combinations are pure frontend constants (design §六). */
const QUICK_PICKS: { labelKey: string; blocks: ExamBlock[] }[] = [
  {
    labelKey: 'paper.quick.mcqMatch',
    blocks: [
      { type: 'mcq_single', count: 5 },
      { type: 'matching', count: 5 },
    ],
  },
  {
    labelKey: 'paper.quick.completion',
    blocks: [{ type: 'completion', count: 10 }],
  },
]

const typeMap = computed<Record<string, ExamTypeInfo>>(() => {
  const map: Record<string, ExamTypeInfo> = {}
  for (const info of types.value) map[info.key] = info
  return map
})

/** Localized type name from the registry's two name fields (client locale). */
function typeName(info: ExamTypeInfo): string {
  return locale.value === 'zh' ? info.name_zh : info.name_en
}

function typeNameOf(key: string): string {
  const info = typeMap.value[key]
  return info ? typeName(info) : key
}

const hasAudio = computed(() => Boolean(material.value?.has_audio))
const allItems = computed<ExamItem[]>(() => (paper.value?.groups ?? []).flatMap((g) => g.items))
const score = computed(() => ({
  ok: allItems.value.filter((item) => states[item.number] === 'ok').length,
  total: allItems.value.length,
}))
const completionInfo = computed(() => typeMap.value.completion)
const hasCompletion = computed(() => selected.value.some((b) => b.type === 'completion'))
const displaySkipped = computed<SkippedBlock[]>(() => [...skipped.value, ...refusedSkipped.value])

/** One small line aggregating the persisted usage ledger (§8):
 * calls + prompt/cached/completion tokens across every entry. Null (the
 * line hides) when the ledger is empty. */
const usageSummary = computed<string | null>(() => {
  const entries = generationUsage.value
  if (!entries.length) return null
  return t('paper.generationUsage', {
    calls: entries.length,
    prompt: entries.reduce((sum, u) => sum + (u.prompt_tokens || 0), 0),
    cached: entries.reduce((sum, u) => sum + (u.cached_tokens || 0), 0),
    completion: entries.reduce((sum, u) => sum + (u.completion_tokens || 0), 0),
  })
})

/** True when a 换一卷 button makes sense: some paper already exists for
 * this material (rendered now, or stored from an earlier session). */
const hasAnyPaper = computed(() => Boolean(paper.value || lastSpec.value))

function kindOfType(type: string): AnswerKind {
  const info = typeMap.value[type]
  if (info) return info.answer_kind as AnswerKind
  if (type === 'mcq_multi') return 'option_multi'
  if (type === 'mcq_single') return 'option'
  if (type === 'matching' || type.endsWith('_labelling')) return 'matching'
  return 'span'
}

function kindOf(item: ExamItem): AnswerKind {
  return kindOfType(item.type)
}

function groupKind(group: ExamGroup): AnswerKind {
  if (group.items.length) return kindOf(group.items[0])
  return kindOfType(group.type)
}

function letter(index: number): string {
  return LETTERS[index] ?? '?'
}

/** Matching option labels may already carry an "A." prefix; don't print it twice. */
function optionText(option: string): string {
  return option.replace(/^[A-H]\s*[.)\-–:]\s*/i, '')
}

/** Split an exam stem on its printed blank marker, keeping text order. */
function segments(stem: string): { text: string; blank: boolean }[] {
  const parts = stem.split(/_{3,}/)
  return parts.map((text, index) => ({ text, blank: index < parts.length - 1 }))
}

function hasBlank(stem: string): boolean {
  return /_{3,}/.test(stem)
}

/** The shared option pool for matching groups, rendered once. */
function matchOptions(group: ExamGroup): string[] {
  if (group.options.length) return group.options
  return group.items.find((item) => item.options.length)?.options ?? []
}

function answerLabel(item: ExamItem): string {
  if (kindOf(item) === 'option_multi') {
    return item.answer
      .split(/[^A-H]+/)
      .filter(Boolean)
      .join(', ')
  }
  if (kindOf(item) === 'option' || kindOf(item) === 'matching') {
    const letterIndex = LETTERS.indexOf(item.answer.trim().toUpperCase())
    const pool =
      kindOf(item) === 'matching' ? matchOptionsOf(item) : item.options
    const text = letterIndex >= 0 ? pool[letterIndex] : undefined
    return text ? `${item.answer}. ${optionText(text)}` : item.answer
  }
  return item.answer
}

/** Matching items duplicate the group pool on each item; resolve it either way. */
function matchOptionsOf(item: ExamItem): string[] {
  if (item.options.length) return item.options
  for (const group of paper.value?.groups ?? []) {
    if (group.items.some((it) => it.number === item.number)) return matchOptions(group)
  }
  return []
}

function isSelected(item: ExamItem, value: string): boolean {
  return kindOf(item) === 'option_multi'
    ? (multiAnswers[item.number] ?? []).includes(value)
    : choiceAnswers[item.number] === value
}

function selectOption(item: ExamItem, value: string) {
  if (kindOf(item) === 'option_multi') {
    const current = [...(multiAnswers[item.number] ?? [])]
    const index = current.indexOf(value)
    if (index >= 0) current.splice(index, 1)
    else current.push(value)
    multiAnswers[item.number] = current
    return
  }
  choiceAnswers[item.number] = value
}

/** Collected answers keyed by item number; only answered items are sent
 * (unanswered ones grade wrong server-side with user_answer null). */
function collectAnswers(): Record<number, string> {
  const answers: Record<number, string> = {}
  for (const item of allItems.value) {
    if (kindOf(item) === 'span') {
      const text = (textAnswers[item.number] ?? '').trim()
      if (text) answers[item.number] = text
    } else if (kindOf(item) === 'option_multi') {
      const letters = multiAnswers[item.number]
      if (letters && letters.length) answers[item.number] = letters.join(',')
    } else {
      const letter = choiceAnswers[item.number]
      if (letter) answers[item.number] = letter
    }
  }
  return answers
}

function clearAnswers() {
  for (const key of Object.keys(textAnswers)) delete textAnswers[Number(key)]
  for (const key of Object.keys(choiceAnswers)) delete choiceAnswers[Number(key)]
  for (const key of Object.keys(multiAnswers)) delete multiAnswers[Number(key)]
  for (const key of Object.keys(states)) delete states[Number(key)]
  submitted.value = false
  showAnswers.value = false
}

/** 交卷： grading lives on the server (design §5.2); the view only
 * renders the per-item verdicts that come back. */
async function submitAnswers() {
  if (submitting.value || !paperId.value) return
  submitting.value = true
  try {
    const result = await api.submitPaperAttempt(paperId.value, collectAnswers())
    for (const key of Object.keys(states)) delete states[Number(key)]
    for (const row of result.items) {
      states[row.item_number] = row.correct ? 'ok' : 'bad'
    }
    submitted.value = true
    void loadStats(paperId.value)
  } catch {
    showToast(t('paper.submitError'), 'error')
  } finally {
    submitting.value = false
  }
}

/** 播放本题: seek the persistent player to the item's evidence interval
 * and highlight it on the progress bar (design §六). */
function playItemAudio(item: ExamItem) {
  const evidence = item.evidence[0]
  if (!hasAudio.value || !evidence) return
  if (playingNumber.value === item.number && playing.value) {
    pause()
    playingNumber.value = null
    return
  }
  const start = Math.max(0, evidence.t_start || 0)
  const end = evidence.t_end > evidence.t_start ? evidence.t_end : null
  evidenceRange.value = end != null ? { start, end } : null
  playingNumber.value = item.number
  seek(start, true)
}

/** Stop at the evidence end while a per-item playback is running. */
watch(playTime, (time) => {
  const range = evidenceRange.value
  if (range && playingNumber.value != null && time >= range.end) {
    pause()
    playingNumber.value = null
  }
})

/** A manual seek takes the bar out of per-item highlight mode. */
function onManualSeek(time: number) {
  evidenceRange.value = null
  playingNumber.value = null
  seek(time)
}

/** Per-item accuracy chip label (design §六: 显示每题正确率); null hides. */
function accuracyText(item: ExamItem): string | null {
  const stat = statsByNumber.value[item.number]
  if (!stat || stat.attempts <= 0) return null
  return t('paper.accuracy', { pct: Math.round((stat.correct / stat.attempts) * 100) })
}

async function loadStats(id: string) {
  try {
    const rows = await api.paperStats(id)
    const map: Record<number, { attempts: number; correct: number }> = {}
    for (const row of rows) map[row.item_number] = { attempts: row.attempts, correct: row.correct }
    statsByNumber.value = map
  } catch {
    statsByNumber.value = {}
  }
}

function resetPaper() {
  paper.value = null
  paperId.value = ''
  stale.value = false
  generationUsage.value = []
  statsByNumber.value = {}
  skipped.value = []
  refusedSkipped.value = []
  error.value = ''
  clearAnswers()
  activeNumber.value = null
  playingNumber.value = null
  evidenceRange.value = null
}

/* ------------------------------------------------- block selector (§六) */

function isSelectedType(key: string): boolean {
  return selected.value.some((block) => block.type === key)
}

function countOf(key: string): number {
  return selected.value.find((block) => block.type === key)?.count ?? 1
}

function toggleType(info: ExamTypeInfo) {
  const index = selected.value.findIndex((block) => block.type === info.key)
  if (index >= 0) {
    selected.value.splice(index, 1)
    return
  }
  selected.value.push({ type: info.key, count: Math.min(5, info.max_count) })
}

/** Clamp a chip count into 1..max_count on change (design §4.2 caps). */
function onCountChange(info: ExamTypeInfo, event: Event) {
  const input = event.target as HTMLInputElement
  const raw = Math.floor(Number(input.value))
  const clamped = Math.min(
    info.max_count,
    Math.max(1, Number.isFinite(raw) && raw > 0 ? raw : 1),
  )
  const entry = selected.value.find((block) => block.type === info.key)
  if (entry) entry.count = clamped
  input.value = String(clamped)
}

function applyQuickPick(pick: { labelKey: string; blocks: ExamBlock[] }) {
  selected.value = pick.blocks
    .filter((block) => typeMap.value[block.type])
    .map((block) => ({
      type: block.type,
      count: Math.min(block.count, typeMap.value[block.type].max_count),
    }))
}

/* ------------------------------------------------ completion layouts (§4.1) */

interface LayoutSection {
  layout: string
  items: ExamItem[]
}

/** Partition a completion group's items by their per-item layout. */
function completionSections(group: ExamGroup): LayoutSection[] {
  const order: string[] = []
  const byLayout = new Map<string, ExamItem[]>()
  for (const item of group.items) {
    const layout = item.layout || 'sentence'
    if (!byLayout.has(layout)) {
      byLayout.set(layout, [])
      order.push(layout)
    }
    byLayout.get(layout)!.push(item)
  }
  return order.map((layout) => ({ layout, items: byLayout.get(layout)! }))
}

function layoutLabel(layout: string): string {
  return t(`paper.layout.${layout}`)
}

/** 产出 N/M badge for partial groups (§4.5): shortfall stays visible. */
function partialText(group: ExamGroup): string {
  const requested = requestedCounts.value[group.type] ?? group.items.length
  return t('paper.partial', { n: group.items.length, m: requested })
}

/* ------------------------------------------------------ map wiring (§4.3) */

/** Older map items reference their slot in the stem text ("blank slot 1"
 * / "空位 1"); newer ones carry an explicit slot field (T14). */
const SLOT_RE = /(?:blank\s*slot|空位|位置)\s*#?(\d+)/i

function slotFromStem(item: ExamItem): number | null {
  const match = item.stem.match(SLOT_RE)
  return match ? Number(match[1]) : null
}

/**
 * slot -> item for one map group. The explicit `slot` field is preferred;
 * the stem text is the fallback for older papers. A duplicated slot number
 * within a group (the backend does not dedupe cross-round slots) makes the
 * claimed linkage untrustworthy, so that group falls back to in-group
 * ordinal against the scene's sorted slot list.
 */
function groupSlotMap(group: ExamGroup): Map<number, ExamItem> {
  const map = new Map<number, ExamItem>()
  if (!group.visual) return map

  const explicit = new Map<number, ExamItem>()
  let explicitDup = false
  for (const item of group.items) {
    if (item.slot == null) continue
    if (explicit.has(item.slot)) explicitDup = true
    else explicit.set(item.slot, item)
  }
  if (explicit.size && !explicitDup) return explicit

  // Once any explicit slot claim is duplicated the group's linkage is
  // untrustworthy: skip the stem parse too and go ordinal (T14 rider).
  const parsed = new Map<number, ExamItem>()
  let parsedDup = false
  if (!explicit.size) {
    for (const item of group.items) {
      const slot = slotFromStem(item)
      if (slot == null) continue
      if (parsed.has(slot)) parsedDup = true
      else parsed.set(slot, item)
    }
  }
  if (parsed.size && !parsedDup) return parsed

  const slots = (group.visual.scene.nodes ?? [])
    .filter((node) => node.blank_slot != null)
    .map((node) => node.blank_slot!)
    .sort((a, b) => a - b)
  group.items.forEach((item, index) => {
    const slot = slots[index]
    if (slot != null) map.set(slot, item)
  })
  return map
}

/** blank_slot -> chosen letter for the scene's numbered circles. */
function mapAnswers(group: ExamGroup): Record<number, string> {
  const answers: Record<number, string> = {}
  for (const [slot, item] of groupSlotMap(group)) {
    const letter = choiceAnswers[item.number]
    if (letter) answers[slot] = letter
  }
  return answers
}

/** Clicking a numbered slot highlights (and scrolls to) the item it asks about. */
function onMapSelect(group: ExamGroup, slot: number) {
  const item = groupSlotMap(group).get(slot)
  if (!item) return
  activeNumber.value = item.number
  if (typeof document !== 'undefined') {
    const element = document.querySelector(`[data-item="${item.number}"]`)
    element?.scrollIntoView?.({ block: 'center' })
  }
}

/* ------------------------------------------------------------- data flow */

/** Adopt a stored paper (historical route): keep its id for submissions,
 * surface staleness, and load the per-item accuracy. */
function applyStoredPaper(stored: {
  id: string
  spec: { blocks?: ExamBlock[] } | null
  paper: ExamPaper
  generation?: GenerationUsageEntry[]
  stale: boolean
}) {
  paperId.value = stored.id
  paper.value = stored.paper
  stale.value = stored.stale
  generationUsage.value = stored.generation ?? []
  requestedCounts.value = Object.fromEntries(
    (stored.spec?.blocks ?? []).map((block) => [block.type, block.count]),
  )
  clearAnswers()
  activeNumber.value = null
  void loadStats(stored.id)
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [detail, meta] = await Promise.all([
      api.getMaterial(materialId.value),
      api.examTypes(),
    ])
    material.value = detail
    types.value = meta.types
    if (paperIdParam.value) {
      applyStoredPaper(await api.getPaper(paperIdParam.value))
    } else {
      // Seed the regenerate rule from the newest stored paper (a page
      // reload must not forget that this spec was already generated).
      // Cosmetic metadata: failures just leave the rule unseeded.
      try {
        const rows = await api.listPapers(materialId.value)
        if (rows.length) {
          const spec = (await api.getPaper(rows[0].id)).spec
          lastSpec.value = spec
            ? { blocks: spec.blocks ?? [], layoutHint: spec.layout_hint ?? null }
            : null
        } else {
          lastSpec.value = null
        }
      } catch {
        lastSpec.value = null
      }
    }
    // ?t= auto-seek (wrong-words 重听): same wiring as MaterialView --
    // the number is the audio position to start playback from.
    const seekTo = Number(route.query.t)
    if (Number.isFinite(seekTo) && seekTo > 0) {
      setTimeout(() => seek(seekTo, true), 300)
    }
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

/** Order- and count-sensitive blocks-spec equality (the request spec). */
function sameBlocks(a: ExamBlock[], b: ExamBlock[]): boolean {
  return (
    a.length === b.length &&
    a.every((block, index) => block.type === b[index].type && block.count === b[index].count)
  )
}

async function generate(forceRegenerate = false) {
  if (generating.value || !selected.value.length) return
  generating.value = true
  error.value = ''
  refusedSkipped.value = []
  const blocks = selected.value.map((block) => ({ ...block }))
  const layoutHintValue = hasCompletion.value && layoutHint.value ? layoutHint.value : null
  // With temp=0 + llm_cache, re-generating the SAME spec (blocks and
  // layout hint) returns a byte-identical paper persisted as a
  // duplicate -- so an identical repeat (or an explicit 换一卷) asks
  // the backend for a fresh variant.
  const regenerate =
    forceRegenerate ||
    (lastSpec.value != null &&
      sameBlocks(blocks, lastSpec.value.blocks) &&
      (lastSpec.value.layoutHint ?? null) === layoutHintValue)
  const opts = {
    layoutHint: layoutHintValue ?? undefined,
    regenerate,
  }
  try {
    const result = await api.generateExam(materialId.value, blocks, opts)
    paper.value = result.paper
    paperId.value = result.paper_id
    stale.value = false
    skipped.value = result.skipped
    requestedCounts.value = Object.fromEntries(
      blocks.map((block) => [block.type, block.count]),
    )
    lastSpec.value = { blocks, layoutHint: layoutHintValue }
    clearAnswers()
    activeNumber.value = null
    playingNumber.value = null
    evidenceRange.value = null
    void loadStats(result.paper_id)
  } catch (err) {
    paper.value = null
    paperId.value = ''
    skipped.value = []
    const data = (err instanceof ApiError ? err.data : undefined) as
      | { skipped?: SkippedBlock[] }
      | undefined
    if (data && Array.isArray(data.skipped)) refusedSkipped.value = data.skipped
    error.value = err instanceof Error ? err.message : String(err)
    showToast(t('paper.error'), 'error')
  } finally {
    generating.value = false
  }
}

watch([materialId, paperIdParam], () => {
  resetPaper()
  void load()
})

onMounted(load)
</script>

<template>
  <div>
    <header class="page-head">
      <div class="head-main">
        <button class="back" type="button" @click="router.push(`/material/${materialId}`)">
          <Icon name="arrowLeft" :size="14" />
          {{ t('paper.back') }}
        </button>
        <h1>{{ material?.name || t('paper.title') }}</h1>
        <span class="chip">{{ t('paper.title') }}</span>
        <span v-if="stale" class="chip warn">{{ t('paper.stale') }}</span>
      </div>
    </header>

    <!-- Generation cost (§8): aggregated from the persisted usage ledger,
         only when the data is present (historical view). -->
    <p v-if="usageSummary" class="generation-usage">{{ usageSummary }}</p>

    <!-- Persistent transport (design §六): the shared PlayerBar component. -->
    <section v-if="material && hasAudio" class="card player-card">
      <audio
        ref="audioEl"
        :src="api.audioUrl(material.id)"
        preload="metadata"
        style="display: none"
      ></audio>

      <PlayerBar
        :has-audio="hasAudio"
        :playing="playing"
        :current="playTime"
        :duration="duration"
        :rate="rate"
        :ab-a="abA"
        :ab-b="abB"
        :hl-start="evidenceRange?.start ?? null"
        :hl-end="evidenceRange?.end ?? null"
        @toggle="toggle"
        @nudge="nudge"
        @seek="onManualSeek"
        @set-rate="setRate"
        @cycle-ab="cycleAb"
        @clear-ab="clearAb"
      />
    </section>

    <div v-if="loading" class="card empty-tip">{{ t('common.loading') }}</div>

    <div v-else-if="loadError" class="card">
      <div class="result bad">{{ loadError }}</div>
    </div>

    <template v-else>
      <section v-if="!historical" class="card">
        <div class="gen-form">
          <div class="selector-block">
            <span class="tag">{{ t('paper.types') }}</span>
            <div class="quick-picks">
              <span class="hint">{{ t('paper.quick.title') }}</span>
              <button
                v-for="pick in QUICK_PICKS"
                :key="pick.labelKey"
                class="ghost small"
                type="button"
                @click="applyQuickPick(pick)"
              >
                {{ t(pick.labelKey) }}
              </button>
            </div>
            <div class="type-chips">
              <button
                v-for="info in types"
                :key="info.key"
                type="button"
                class="type-chip"
                :class="{ on: isSelectedType(info.key) }"
                :aria-pressed="isSelectedType(info.key)"
                @click="toggleType(info)"
              >
                <span class="chip-name">{{ typeName(info) }}</span>
                <input
                  v-if="isSelectedType(info.key)"
                  class="count-input"
                  type="number"
                  min="1"
                  :max="info.max_count"
                  :value="countOf(info.key)"
                  :aria-label="t('paper.countAria', { name: typeName(info) })"
                  @click.stop
                  @change="onCountChange(info, $event)"
                />
              </button>
            </div>
          </div>

          <label v-if="hasCompletion && completionInfo" class="field">
            <span class="tag">{{ t('paper.layoutHint') }}</span>
            <select
              v-model="layoutHint"
              class="layout-select"
              :aria-label="t('paper.layoutHint')"
            >
              <option value="">{{ t('paper.layout.auto') }}</option>
              <option v-for="layout in completionInfo.layouts" :key="layout" :value="layout">
                {{ layoutLabel(layout) }}
              </option>
            </select>
          </label>

          <button
            class="big"
            type="button"
            :disabled="generating || !selected.length"
            @click="generate()"
          >
            <span v-if="generating" class="spinner" aria-hidden="true"></span>
            <Icon v-else name="spark" :size="14" />
            {{ generating ? t('paper.generating') : t('paper.generate') }}
          </button>

          <!-- 换一卷: with a paper already generated for this material,
           explicitly ask for a fresh variant (regenerate) instead of a
           byte-identical cache hit (temp=0 + llm_cache). -->
          <button
            v-if="hasAnyPaper"
            class="ghost"
            type="button"
            :disabled="generating || !selected.length"
            @click="generate(true)"
          >
            {{ t('paper.regenerate') }}
          </button>
        </div>

        <p v-if="generating" class="hint gen-hint">{{ t('paper.generatingHint') }}</p>
        <div v-if="error" class="result bad">{{ t('paper.error') }} {{ error }}</div>
      </section>

      <section v-if="displaySkipped.length" class="card skipped-list">
        <p class="section-label">{{ t('paper.skipped.title') }}</p>
        <ul>
          <li v-for="(entry, index) in displaySkipped" :key="index">
            {{ t('paper.skipped.item', { type: typeNameOf(entry.type), reason: entry.reason }) }}
          </li>
        </ul>
      </section>

      <template v-if="paper">
        <details v-if="paper.warnings.length" class="card warnings">
          <summary>{{ t('paper.warnings.title', { n: paper.warnings.length }) }}</summary>
          <ul>
            <li v-for="(warning, index) in paper.warnings" :key="index">{{ warning }}</li>
          </ul>
        </details>

        <section
          v-for="(group, groupIndex) in paper.groups"
          :key="groupIndex"
          class="card paper-group"
        >
          <div class="cardtitle">
            <h2>{{ group.title || t('paper.questions') }}</h2>
            <span class="chip">{{ typeNameOf(group.type) }}</span>
            <span v-if="group.partial" class="chip partial-badge">
              {{ partialText(group) }}
            </span>
          </div>

          <div class="instruction">
            <span v-if="group.items.length" class="section-label">
              {{
                t('paper.questionsRange', {
                  from: group.items[0].number,
                  to: group.items[group.items.length - 1].number,
                })
              }}
            </span>
            <p>{{ group.instruction }}</p>
          </div>

          <div v-if="groupKind(group) === 'matching' && matchOptions(group).length" class="match-options">
            <div
              v-for="(option, optionIndex) in matchOptions(group)"
              :key="optionIndex"
              class="match-option"
            >
              <span class="letter">{{ letter(optionIndex) }}</span>
              <span>{{ optionText(option) }}</span>
            </div>
          </div>

          <!-- Map groups carry the drawable scene (design §4.3). -->
          <MapScene
            v-if="group.visual"
            class="scene-holder"
            :scene="group.visual.scene"
            :answers="mapAnswers(group)"
            @select="(slot) => onMapSelect(group, slot)"
          />

          <!-- Completion: items partitioned by their per-item layout (§4.1). -->
          <div v-if="group.type === 'completion'" class="items">
            <div
              v-for="section in completionSections(group)"
              :key="section.layout"
              class="layout-section"
              :class="`layout-${section.layout}`"
            >
              <span class="chip layout-chip">{{ layoutLabel(section.layout) }}</span>

              <!-- form: label column + blank row -->
              <div v-if="section.layout === 'form'" class="form-rows">
                <div
                  v-for="item in section.items"
                  :key="item.number"
                  class="paper-item form-row"
                  :class="[states[item.number], { active: item.number === activeNumber }]"
                  :data-item="item.number"
                >
                  <span class="item-number">{{ item.number }}</span>
                  <span class="form-label">{{ item.label || '—' }}</span>
                  <div class="item-body">
                    <p class="stem">
                      <template
                        v-for="(segment, segmentIndex) in segments(item.stem)"
                        :key="segmentIndex"
                      >
                        <span>{{ segment.text }}</span>
                        <input
                          v-if="segment.blank"
                          v-model="textAnswers[item.number]"
                          class="blank-input"
                          :class="states[item.number]"
                          type="text"
                          autocomplete="off"
                          spellcheck="false"
                          :aria-label="
                            t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                          "
                        />
                      </template>
                      <input
                        v-if="!hasBlank(item.stem)"
                        v-model="textAnswers[item.number]"
                        class="blank-input"
                        :class="states[item.number]"
                        type="text"
                        autocomplete="off"
                        spellcheck="false"
                        :aria-label="
                          t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                        "
                      />
                    </p>
                    <div class="item-tools">
                      <button
                        v-if="hasAudio && item.evidence.length"
                        class="play-evidence"
                        type="button"
                        :title="t('paper.playItem')"
                        :aria-label="t('paper.playItem')"
                        @click="playItemAudio(item)"
                      >
                        <Icon :name="playingNumber === item.number ? 'pause' : 'play'" :size="12" />
                        {{ t('paper.playItem') }}
                      </button>
                      <span v-if="accuracyText(item)" class="chip accuracy-chip">{{ accuracyText(item) }}</span>
                      <span v-if="item.word_limit" class="hint">{{ item.word_limit }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- table: one row per item, label column + blank cell -->
              <table v-else-if="section.layout === 'table'" class="layout-table-table">
                <tbody>
                  <tr
                    v-for="item in section.items"
                    :key="item.number"
                    :class="[states[item.number], { active: item.number === activeNumber }]"
                    :data-item="item.number"
                  >
                    <td class="item-number">{{ item.number }}</td>
                    <th class="form-label" scope="row">{{ item.label || '—' }}</th>
                    <td>
                      <p class="stem">
                        <template
                          v-for="(segment, segmentIndex) in segments(item.stem)"
                          :key="segmentIndex"
                        >
                          <span>{{ segment.text }}</span>
                          <input
                            v-if="segment.blank"
                            v-model="textAnswers[item.number]"
                            class="blank-input"
                            :class="states[item.number]"
                            type="text"
                            autocomplete="off"
                            spellcheck="false"
                            :aria-label="
                              t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                            "
                          />
                        </template>
                        <input
                          v-if="!hasBlank(item.stem)"
                          v-model="textAnswers[item.number]"
                          class="blank-input"
                          :class="states[item.number]"
                          type="text"
                          autocomplete="off"
                          spellcheck="false"
                          :aria-label="
                            t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                          "
                        />
                      </p>
                      <div class="item-tools">
                        <button
                          v-if="hasAudio && item.evidence.length"
                          class="play-evidence"
                          type="button"
                          :title="t('paper.playItem')"
                          :aria-label="t('paper.playItem')"
                          @click="playItemAudio(item)"
                        >
                          <Icon :name="playingNumber === item.number ? 'pause' : 'play'" :size="12" />
                          {{ t('paper.playItem') }}
                        </button>
                        <span v-if="accuracyText(item)" class="chip accuracy-chip">{{ accuracyText(item) }}</span>
                        <span v-if="item.word_limit" class="hint">{{ item.word_limit }}</span>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>

              <!-- notes: bulleted list -->
              <ul v-else-if="section.layout === 'notes'" class="layout-notes-list">
                <li
                  v-for="item in section.items"
                  :key="item.number"
                  class="paper-item note-row"
                  :class="[states[item.number], { active: item.number === activeNumber }]"
                  :data-item="item.number"
                >
                  <span class="item-number">{{ item.number }}</span>
                  <div class="item-body">
                    <p class="stem">
                      <span v-if="item.label" class="item-label">{{ item.label }}</span>
                      <template
                        v-for="(segment, segmentIndex) in segments(item.stem)"
                        :key="segmentIndex"
                      >
                        <span>{{ segment.text }}</span>
                        <input
                          v-if="segment.blank"
                          v-model="textAnswers[item.number]"
                          class="blank-input"
                          :class="states[item.number]"
                          type="text"
                          autocomplete="off"
                          spellcheck="false"
                          :aria-label="
                            t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                          "
                        />
                      </template>
                      <input
                        v-if="!hasBlank(item.stem)"
                        v-model="textAnswers[item.number]"
                        class="blank-input"
                        :class="states[item.number]"
                        type="text"
                        autocomplete="off"
                        spellcheck="false"
                        :aria-label="
                          t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                        "
                      />
                    </p>
                    <div class="item-tools">
                      <button
                        v-if="hasAudio && item.evidence.length"
                        class="play-evidence"
                        type="button"
                        :title="t('paper.playItem')"
                        :aria-label="t('paper.playItem')"
                        @click="playItemAudio(item)"
                      >
                        <Icon :name="playingNumber === item.number ? 'pause' : 'play'" :size="12" />
                        {{ t('paper.playItem') }}
                      </button>
                      <span v-if="accuracyText(item)" class="chip accuracy-chip">{{ accuracyText(item) }}</span>
                      <span v-if="item.word_limit" class="hint">{{ item.word_limit }}</span>
                    </div>
                  </div>
                </li>
              </ul>

              <!-- summary: one flowing paragraph -->
              <p v-else-if="section.layout === 'summary'" class="summary-para">
                <template v-for="(item, itemIndex) in section.items" :key="item.number">
                  <span class="summary-item" :class="states[item.number]">
                    <template
                      v-for="(segment, segmentIndex) in segments(item.stem)"
                      :key="segmentIndex"
                    >
                      <span>{{ segment.text }}</span>
                      <input
                        v-if="segment.blank"
                        v-model="textAnswers[item.number]"
                        class="blank-input"
                        :class="states[item.number]"
                        type="text"
                        autocomplete="off"
                        spellcheck="false"
                        :aria-label="
                          t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                        "
                      />
                    </template>
                    <input
                      v-if="!hasBlank(item.stem)"
                      v-model="textAnswers[item.number]"
                      class="blank-input"
                      :class="states[item.number]"
                      type="text"
                      autocomplete="off"
                      spellcheck="false"
                      :aria-label="
                        t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                      "
                    />
                    {{ ' ' }}
                  </span>
                </template>
              </p>

              <!-- sentence / flowchart / anything else: stacked stems -->
              <div v-else class="items">
                <div
                  v-for="item in section.items"
                  :key="item.number"
                  class="paper-item"
                  :class="[
                    section.layout === 'flowchart' ? 'flow-box' : '',
                    states[item.number],
                    { active: item.number === activeNumber },
                  ]"
                  :data-item="item.number"
                >
                  <span class="item-number">{{ item.number }}</span>
                  <div class="item-body">
                    <p class="stem">
                      <span v-if="item.label" class="item-label">{{ item.label }}</span>
                      <template
                        v-for="(segment, segmentIndex) in segments(item.stem)"
                        :key="segmentIndex"
                      >
                        <span>{{ segment.text }}</span>
                        <input
                          v-if="segment.blank"
                          v-model="textAnswers[item.number]"
                          class="blank-input"
                          :class="states[item.number]"
                          type="text"
                          autocomplete="off"
                          spellcheck="false"
                          :aria-label="
                            t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                          "
                        />
                      </template>
                      <input
                        v-if="!hasBlank(item.stem)"
                        v-model="textAnswers[item.number]"
                        class="blank-input"
                        :class="states[item.number]"
                        type="text"
                        autocomplete="off"
                        spellcheck="false"
                        :aria-label="
                          t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                        "
                      />
                    </p>
                    <div class="item-tools">
                      <button
                        v-if="hasAudio && item.evidence.length"
                        class="play-evidence"
                        type="button"
                        :title="t('paper.playItem')"
                        :aria-label="t('paper.playItem')"
                        @click="playItemAudio(item)"
                      >
                        <Icon :name="playingNumber === item.number ? 'pause' : 'play'" :size="12" />
                        {{ t('paper.playItem') }}
                      </button>
                      <span v-if="accuracyText(item)" class="chip accuracy-chip">{{ accuracyText(item) }}</span>
                      <span v-if="item.word_limit" class="hint">{{ item.word_limit }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- per-item answer keys for every completion layout -->
              <div class="layout-keys">
                <p
                  v-for="item in section.items"
                  v-show="showAnswers || states[item.number] === 'bad'"
                  :key="item.number"
                  class="answer-key"
                >
                  {{ item.number }}. {{ t('paper.answer', { answer: answerLabel(item) }) }}
                </p>
              </div>
            </div>
          </div>

          <!-- Every other type: one row per item. -->
          <div v-else class="items">
            <div
              v-for="item in group.items"
              :key="item.number"
              class="paper-item"
              :class="[states[item.number], { active: item.number === activeNumber }]"
              :data-item="item.number"
            >
              <span class="item-number">{{ item.number }}</span>

              <div class="item-body">
                <!-- short_answer: input at the printed blank -->
                <template v-if="kindOf(item) === 'span'">
                  <p class="stem">
                    <span v-if="item.label" class="item-label">{{ item.label }}</span>
                    <template v-for="(segment, segmentIndex) in segments(item.stem)" :key="segmentIndex">
                      <span>{{ segment.text }}</span>
                      <input
                        v-if="segment.blank"
                        v-model="textAnswers[item.number]"
                        class="blank-input"
                        :class="states[item.number]"
                        type="text"
                        autocomplete="off"
                        spellcheck="false"
                        :aria-label="
                          t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                        "
                      />
                    </template>
                    <!-- Defensive: a stem without a marker still gets one answer box. -->
                    <input
                      v-if="!hasBlank(item.stem)"
                      v-model="textAnswers[item.number]"
                      class="blank-input"
                      :class="states[item.number]"
                      type="text"
                      autocomplete="off"
                      spellcheck="false"
                      :aria-label="
                        t('blank.aria', { n: item.number, limit: item.word_limit || group.instruction })
                      "
                    />
                  </p>
                </template>

                <!-- Multiple choice: one lettered button per option. -->
                <template v-else-if="kindOf(item) === 'option' || kindOf(item) === 'option_multi'">
                  <p class="stem">{{ item.stem }}</p>
                  <div class="mcq-options">
                    <button
                      v-for="(option, optionIndex) in item.options"
                      :key="optionIndex"
                      class="option-btn"
                      :class="{ on: isSelected(item, letter(optionIndex)) }"
                      type="button"
                      :aria-label="t('paper.chooseOption', { letter: letter(optionIndex) })"
                      :aria-pressed="isSelected(item, letter(optionIndex))"
                      @click="selectOption(item, letter(optionIndex))"
                    >
                      <span class="letter">{{ letter(optionIndex) }}</span>
                      <span>{{ optionText(option) }}</span>
                    </button>
                  </div>
                </template>

                <!-- Matching / map: the shared option list is printed once above. -->
                <template v-else>
                  <p class="stem">{{ item.stem }}</p>
                  <div class="match-buttons">
                    <button
                      v-for="(option, optionIndex) in matchOptions(group)"
                      :key="optionIndex"
                      class="match-btn"
                      :class="{ on: isSelected(item, letter(optionIndex)) }"
                      type="button"
                      :aria-label="t('paper.chooseOption', { letter: letter(optionIndex) })"
                      :aria-pressed="isSelected(item, letter(optionIndex))"
                      :title="optionText(option)"
                      @click="selectOption(item, letter(optionIndex))"
                    >
                      {{ letter(optionIndex) }}
                    </button>
                  </div>
                </template>

                <div class="item-tools">
                  <button
                    v-if="hasAudio && item.evidence.length"
                    class="play-evidence"
                    type="button"
                    :title="t('paper.playItem')"
                    :aria-label="t('paper.playItem')"
                    @click="playItemAudio(item)"
                  >
                    <Icon :name="playingNumber === item.number ? 'pause' : 'play'" :size="12" />
                    {{ t('paper.playItem') }}
                  </button>
                  <span v-if="accuracyText(item)" class="chip accuracy-chip">{{ accuracyText(item) }}</span>
                  <span v-if="item.word_limit" class="hint">{{ item.word_limit }}</span>
                </div>

                <p
                  v-if="showAnswers || states[item.number] === 'bad'"
                  class="answer-key"
                >
                  {{ t('paper.answer', { answer: answerLabel(item) }) }}
                </p>
              </div>
            </div>
          </div>
        </section>

        <section class="card actions-card">
          <div class="row">
            <button
              class="big"
              type="button"
              :disabled="submitting || !paperId"
              @click="submitAnswers"
            >
              <Icon name="check" :size="14" />
              {{ submitting ? t('paper.submitting') : t('paper.submit') }}
            </button>
            <button
              class="ghost"
              type="button"
              :class="{ on: showAnswers }"
              @click="showAnswers = !showAnswers"
            >
              <Icon name="eye" :size="14" />
              {{ showAnswers ? t('paper.hideAnswers') : t('paper.showAnswers') }}
            </button>
            <span class="chip">{{ t('paper.total', { n: score.total }) }}</span>
          </div>

          <div
            v-if="submitted"
            class="result score-summary"
            :class="score.ok === score.total ? 'good' : 'meh'"
          >
            {{ t('paper.score', { ok: score.ok, total: score.total }) }}
          </div>
        </section>
      </template>

      <div v-else-if="!historical && !generating && !error" class="card empty-tip">
        <p>{{ t('paper.empty') }}</p>
        <p class="hint empty-hint">{{ t('paper.emptyHint') }}</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--rule);
}

.head-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.head-main h1 {
  font-size: 18px;
}

.generation-usage {
  margin: -10px 0 16px;
  color: var(--ink-3);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--ink-3);
  font-size: 12.5px;
}

.back:hover:not(:disabled) {
  border-color: var(--rule);
  background: var(--paper);
  color: var(--ink);
  opacity: 1;
}

.gen-form {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.selector-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1 1 380px;
}

.quick-picks {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.quick-picks .hint {
  font-size: 11.5px;
}

.type-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.type-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 11px;
  border: 1px solid var(--rule-strong);
  border-radius: 999px;
  background: var(--paper);
  color: var(--ink-2);
  font-size: 12.5px;
  cursor: pointer;
}

.type-chip:hover {
  border-color: var(--ink-3);
}

.type-chip.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.count-input {
  width: 54px;
  padding: 1px 4px;
  border: 1px solid var(--rule-strong);
  border-radius: 3px;
  background: var(--paper);
  color: var(--ink);
  font-size: 12px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.gen-hint {
  margin-top: 12px;
}

.spinner {
  width: 13px;
  height: 13px;
  border: 2px solid color-mix(in srgb, var(--ink) 22%, transparent);
  border-top-color: var(--ink);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.skipped-list {
  padding: 14px 18px;
  border-left: 3px solid var(--accent);
  font-size: 12.5px;
}

.skipped-list ul {
  margin: 8px 0 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--ink-2);
}

.warnings {
  padding: 14px 18px;
  color: var(--ink-3);
  font-size: 12.5px;
}

.warnings summary {
  cursor: pointer;
  color: var(--ink-3);
  font-weight: 500;
}

.warnings ul {
  margin: 10px 0 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* Printed instruction block, like an exam paper header. */
.instruction {
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid var(--rule);
  border-left: 3px solid var(--ink);
  background: var(--paper-2);
  color: var(--ink-2);
  font-size: 13px;
}

.instruction p {
  margin-top: 4px;
}

.partial-badge {
  border-color: var(--accent);
  color: var(--accent);
}

.scene-holder {
  margin-bottom: 16px;
}

.match-options {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper-2);
}

.match-option {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 14px;
  color: var(--ink-2);
}

.letter {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  color: var(--ink-3);
  font-family: -apple-system, 'PingFang SC', system-ui, sans-serif;
  font-size: 11.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* Completion layout sections (design §4.1). */
.layout-section {
  margin-bottom: 14px;
}

.layout-chip {
  display: inline-block;
  margin-bottom: 8px;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-3);
}

.form-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.paper-item.form-row {
  display: grid;
  grid-template-columns: 26px 110px 1fr;
  gap: 10px;
  align-items: baseline;
  align-items: start;
}

.form-label {
  color: var(--ink-2);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 13.5px;
}

.layout-table-table {
  width: 100%;
  border-collapse: collapse;
}

.layout-table-table th,
.layout-table-table td {
  border: 1px solid var(--rule);
  padding: 8px 10px;
  vertical-align: top;
  text-align: left;
}

.layout-table-table tr.active td,
.layout-table-table tr.active th {
  background: var(--accent-soft);
}

.layout-notes-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.paper-item.note-row {
  position: relative;
  padding-left: 22px;
}

.paper-item.note-row::before {
  content: '•';
  position: absolute;
  left: 10px;
  top: 10px;
  color: var(--ink-3);
}

.summary-para {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 14.5px;
  line-height: 1.9;
  color: var(--ink);
}

.summary-item.ok {
  color: var(--ok);
}

.summary-item.bad {
  color: var(--accent);
}

.layout-keys {
  margin-top: 6px;
}

.layout-flow {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.paper-item.flow-box {
  position: relative;
  width: 100%;
  max-width: 460px;
  margin-top: 14px;
  text-align: center;
}

.paper-item.flow-box:first-child {
  margin-top: 0;
}

.paper-item.flow-box + .paper-item.flow-box::before {
  content: '↓';
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  color: var(--ink-3);
  font-size: 13px;
}

.items {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.paper-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--rule);
  border-left: 3px solid transparent;
  border-radius: 3px;
  background: var(--paper);
}

.paper-item.ok {
  border-left-color: var(--ok);
}

.paper-item.bad {
  border-left-color: var(--accent);
}

.paper-item.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.item-number {
  min-width: 26px;
  padding-top: 2px;
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.item-body {
  flex: 1;
  min-width: 0;
}

.stem {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 14.5px;
  line-height: 1.9;
  color: var(--ink);
}

.item-label {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 6px;
  border: 1px solid var(--rule);
  border-radius: 2px;
  background: var(--paper-2);
  color: var(--ink-3);
  font-family: -apple-system, 'PingFang SC', system-ui, sans-serif;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  vertical-align: 1px;
}

.blank-input {
  min-width: 150px;
  max-width: 100%;
  padding: 1px 6px;
  border: none;
  border-bottom: 1px solid var(--ink-2);
  border-radius: 0;
  background: transparent;
  color: var(--ink);
  font-family: inherit;
  font-size: 13.5px;
  text-align: center;
}

.blank-input:focus {
  outline: none;
  border-bottom-color: var(--focus);
  border-bottom-width: 2px;
  background: color-mix(in srgb, var(--focus) 7%, transparent);
  box-shadow: none;
}

.blank-input.ok {
  border-bottom-color: var(--ok);
  color: var(--ok);
}

.blank-input.bad {
  border-bottom-color: var(--accent);
  color: var(--accent);
}

.mcq-options {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}

.option-btn {
  justify-content: flex-start;
  gap: 10px;
  width: 100%;
  padding: 8px 12px;
  border-color: var(--rule);
  background: var(--paper);
  color: var(--ink-2);
  font-size: 13.5px;
  text-align: left;
  white-space: normal;
}

.option-btn .letter {
  min-width: 18px;
  padding: 0 4px;
  border: 1px solid var(--rule-strong);
  border-radius: 2px;
  color: var(--ink-2);
  font-size: 10.5px;
  line-height: 1.7;
}

.option-btn.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--ink);
}

.option-btn.on .letter {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--paper);
}

.match-buttons {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.match-btn {
  min-width: 38px;
  padding: 5px 0;
  border-color: var(--rule);
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}

.match-btn.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.item-tools {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.play-evidence {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
}

.accuracy-chip {
  font-size: 11px;
  color: var(--ink-3);
  font-variant-numeric: tabular-nums;
}

.player-card {
  padding-bottom: 16px;
}

.answer-key {
  margin-top: 8px;
  padding: 5px 9px;
  border-left: 2px solid var(--ok);
  background: var(--ok-soft);
  color: var(--ok);
  font-size: 12.5px;
}

.paper-item.bad .answer-key {
  border-left-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.actions-card {
  display: flex;
  flex-direction: column;
}

.empty-hint {
  margin-top: 6px;
}
</style>
