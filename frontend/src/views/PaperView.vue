<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type ExamGroup,
  type ExamItem,
  type ExamPaper,
  type ExamPresetInfo,
  type ExamTypeInfo,
  type MaterialDetail,
} from '../api'
import { showToast } from '../router'
import { t } from '../i18n'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()
const materialId = computed(() => String(route.params.materialId || ''))

const material = ref<MaterialDetail | null>(null)
const types = ref<ExamTypeInfo[]>([])
const presets = ref<ExamPresetInfo[]>([])
const part = ref(1)
const preset = ref('')
const paper = ref<ExamPaper | null>(null)

const loading = ref(true)
const loadError = ref('')
const generating = ref(false)
const error = ref('')

const textAnswers = reactive<Record<number, string>>({})
const choiceAnswers = reactive<Record<number, string>>({})
const multiAnswers = reactive<Record<number, string[]>>({})
const states = reactive<Record<number, 'ok' | 'bad'>>({})
const submitted = ref(false)
const showAnswers = ref(false)

const audioEl = ref<HTMLAudioElement | null>(null)
const playEnd = ref<number | null>(null)
const playingNumber = ref<number | null>(null)

const LETTERS = 'ABCDEFGH'
type AnswerKind = 'span' | 'option' | 'option_multi' | 'matching'

const typeMap = computed<Record<string, ExamTypeInfo>>(() => {
  const map: Record<string, ExamTypeInfo> = {}
  for (const info of types.value) map[info.key] = info
  return map
})

const presetsForPart = computed(() => presets.value.filter((p) => p.part === part.value))
const hasAudio = computed(() => Boolean(material.value?.has_audio))
const allItems = computed<ExamItem[]>(() => (paper.value?.groups ?? []).flatMap((g) => g.items))
const score = computed(() => ({
  ok: allItems.value.filter((item) => states[item.number] === 'ok').length,
  total: allItems.value.length,
}))

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

function normalizeText(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ')
}

function answerLetters(value: string): string[] {
  return [...new Set(value.toUpperCase().split(/[^A-H]+/).filter(Boolean))].sort()
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

function isCorrect(item: ExamItem): boolean {
  switch (kindOf(item)) {
    case 'span': {
      const given = normalizeText(textAnswers[item.number] ?? '')
      if (!given) return false
      const accepted = [item.answer, ...item.alternatives].map(normalizeText)
      return accepted.includes(given)
    }
    case 'option':
    case 'matching':
      return (
        (choiceAnswers[item.number] ?? '').toUpperCase() ===
        item.answer.trim().toUpperCase()
      )
    case 'option_multi': {
      const expected = answerLetters(item.answer)
      const given = answerLetters((multiAnswers[item.number] ?? []).join(','))
      return (
        expected.length > 0 &&
        expected.length === given.length &&
        expected.every((value, index) => value === given[index])
      )
    }
  }
}

function clearAnswers() {
  for (const key of Object.keys(textAnswers)) delete textAnswers[Number(key)]
  for (const key of Object.keys(choiceAnswers)) delete choiceAnswers[Number(key)]
  for (const key of Object.keys(multiAnswers)) delete multiAnswers[Number(key)]
  for (const key of Object.keys(states)) delete states[Number(key)]
  submitted.value = false
  showAnswers.value = false
}

function checkAnswers() {
  if (!allItems.value.length) return
  for (const item of allItems.value) {
    states[item.number] = isCorrect(item) ? 'ok' : 'bad'
  }
  submitted.value = true
}

function playEvidence(item: ExamItem) {
  const element = audioEl.value
  const evidence = item.evidence[0]
  if (!element || !evidence) return
  if (playingNumber.value === item.number && !element.paused) {
    element.pause()
    playingNumber.value = null
    playEnd.value = null
    return
  }
  element.currentTime = Math.max(0, evidence.t_start || 0)
  playEnd.value = evidence.t_end > evidence.t_start ? evidence.t_end : null
  playingNumber.value = item.number
  const playing = element.play()
  if (playing && typeof playing.catch === 'function') {
    playing.catch(() => {
      playingNumber.value = null
      playEnd.value = null
    })
  }
}

function onTimeUpdate() {
  const element = audioEl.value
  if (!element) return
  if (playEnd.value !== null && element.currentTime >= playEnd.value) {
    element.pause()
    playEnd.value = null
    playingNumber.value = null
  }
}

function resetPaper() {
  paper.value = null
  error.value = ''
  clearAnswers()
  playingNumber.value = null
  playEnd.value = null
}

function syncPreset() {
  const list = presetsForPart.value
  if (!list.some((item) => item.key === preset.value)) {
    preset.value = list[0]?.key ?? ''
  }
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
    presets.value = meta.presets
    syncPreset()
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

async function generate() {
  if (generating.value) return
  generating.value = true
  error.value = ''
  try {
    const result = await api.generateExam(
      materialId.value,
      part.value,
      preset.value || undefined,
    )
    paper.value = result
    clearAnswers()
    playingNumber.value = null
    playEnd.value = null
    if (result.available_presets?.length) {
      // The POST echo is only {key,label}; fold the fresh labels back into
      // the richer per-part list so the selector keeps its structure.
      const labels = new Map(result.available_presets.map((p) => [p.key, p.label]))
      presets.value = presets.value.map((p) =>
        labels.has(p.key) ? { ...p, label: labels.get(p.key)! } : p,
      )
      syncPreset()
    }
  } catch (err) {
    paper.value = null
    error.value = err instanceof Error ? err.message : String(err)
    showToast(t('paper.error'), 'error')
  } finally {
    generating.value = false
  }
}

watch(part, () => {
  syncPreset()
  resetPaper()
})

watch(materialId, () => {
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
      </div>
    </header>

    <audio
      v-if="material && hasAudio"
      ref="audioEl"
      :src="api.audioUrl(material.id)"
      preload="metadata"
      style="display: none"
      @timeupdate="onTimeUpdate"
    ></audio>

    <div v-if="loading" class="card empty-tip">{{ t('common.loading') }}</div>

    <div v-else-if="loadError" class="card">
      <div class="result bad">{{ loadError }}</div>
    </div>

    <template v-else>
      <section class="card">
        <div class="gen-form">
          <label class="field">
            <span class="tag">{{ t('paper.part') }}</span>
            <select v-model.number="part" :aria-label="t('paper.part')">
              <option v-for="n in 4" :key="n" :value="n">
                {{ t('paper.partOption', { n }) }}
              </option>
            </select>
          </label>

          <label class="field">
            <span class="tag">{{ t('paper.preset') }}</span>
            <select v-model="preset" :aria-label="t('paper.preset')">
              <option v-for="item in presetsForPart" :key="item.key" :value="item.key">
                {{ item.label }}
              </option>
            </select>
          </label>

          <button class="big" type="button" :disabled="generating" @click="generate">
            <span v-if="generating" class="spinner" aria-hidden="true"></span>
            <Icon v-else name="spark" :size="14" />
            {{ generating ? t('paper.generating') : t('paper.generate') }}
          </button>
        </div>

        <p v-if="generating" class="hint gen-hint">{{ t('paper.generatingHint') }}</p>
        <div v-if="error" class="result bad">{{ t('paper.error') }} {{ error }}</div>
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
            <span v-if="typeMap[group.type]" class="chip">{{ typeMap[group.type].label }}</span>
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

          <div class="items">
            <div
              v-for="item in group.items"
              :key="item.number"
              class="paper-item"
              :class="states[item.number]"
            >
              <span class="item-number">{{ item.number }}</span>

              <div class="item-body">
                <!-- Completion / short answer: input placed at each printed blank. -->
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
                          t('blank.aria', {
                            n: item.number,
                            limit: item.word_limit || group.instruction,
                          })
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
                        t('blank.aria', {
                          n: item.number,
                          limit: item.word_limit || group.instruction,
                        })
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

                <!-- Matching: the shared option list is printed once above. -->
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
                    class="ghost small play-evidence"
                    type="button"
                    :title="t('paper.playEvidence')"
                    :aria-label="t('paper.playEvidence')"
                    @click="playEvidence(item)"
                  >
                    <Icon :name="playingNumber === item.number ? 'pause' : 'play'" :size="11" />
                    {{ t('paper.playEvidence') }}
                  </button>
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
            <button class="big" type="button" @click="checkAnswers">
              <Icon name="check" :size="14" />
              {{ t('paper.submit') }}
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

      <div v-else-if="!generating && !error" class="card empty-tip">
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
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
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
  padding: 3px 8px;
  font-size: 11.5px;
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
