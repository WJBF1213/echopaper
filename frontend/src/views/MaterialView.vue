<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type ExamTypeInfo,
  type MaterialDetail,
  type PaperAttemptDetail,
  type PaperAttemptSummary,
  type PaperSummary,
} from '../api'
import { showToast } from '../router'
import { usePlayer } from '../composables/usePlayer'
import {
  fmtDateTime,
  fmtTime,
  hasWordTiming,
  sentenceTimeRange,
  transcriptSourceLabel,
} from '../lib/time'
import { locale, t, tn } from '../i18n'
import Icon from '../components/Icon.vue'
import TranscriptView from '../components/TranscriptView.vue'

const route = useRoute()
const router = useRouter()
const materialId = computed(() => String(route.params.materialId || ''))

const material = ref<MaterialDetail | null>(null)
const papers = ref<PaperSummary[]>([])
const types = ref<ExamTypeInfo[]>([])
const loading = ref(true)

/** Paper row whose attempt history is expanded (null = all collapsed). */
const expandedPaperId = ref<string | null>(null)
const attemptsByPaper = ref<Record<string, PaperAttemptSummary[]>>({})
/** Attempt whose per-item detail is expanded, and its loaded detail. */
const expandedAttemptId = ref<string | null>(null)
const detailByAttempt = ref<Record<string, PaperAttemptDetail>>({})

const editing = ref(false)
const transcriptDraft = ref('')
const savingTranscript = ref(false)

const audioEl = ref<HTMLAudioElement | null>(null)
const { playing, current: playTime, duration, seek, toggle, nudge } = usePlayer(audioEl)
const showStamps = ref(true)

const timed = computed(
  () => Boolean(material.value?.has_audio) &&
    hasWordTiming(material.value?.words ?? []),
)

function seekToWord(wordIndex: number) {
  if (!timed.value) return
  const word = material.value?.words[wordIndex]
  if (!word) return
  seek(word.s, true)
}

function seekToSentence(sentenceIndex: number) {
  const range = material.value?.sentences[sentenceIndex]
  if (!range || !material.value) return
  const words = material.value.words
  const times = sentenceTimeRange(words, { start: range[0], end: range[1] })
  if (times) seek(times.a, true)
}

/** Localized type name from the registry's two name fields (client locale);
 * falls back to the raw key when the registry is unavailable offline. */
function typeNameOf(key: string): string {
  const info = types.value.find((x) => x.key === key)
  if (!info) return key
  return locale.value === 'zh' ? info.name_zh : info.name_en
}

async function load() {
  loading.value = true
  try {
    material.value = await api.getMaterial(materialId.value)
    transcriptDraft.value = material.value.transcript
    // The registry is cosmetic here (composition chip labels); a failure
    // must not take the page down -- typeNameOf falls back to raw keys.
    const [paperRows, typeInfo] = await Promise.all([
      api.listPapers(materialId.value),
      api.examTypes().catch(() => ({ types: [] as ExamTypeInfo[] })),
    ])
    papers.value = paperRows
    types.value = typeInfo.types
    expandedPaperId.value = null
    expandedAttemptId.value = null
    const t = Number(route.query.t)
    if (Number.isFinite(t) && t > 0) {
      setTimeout(() => seek(t, true), 300)
    }
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    loading.value = false
  }
}

watch(
  () => route.query.t,
  (value) => {
    const t = Number(value)
    if (Number.isFinite(t) && t > 0) seek(t, true)
  },
)

function openPaper(paper: PaperSummary) {
  void router.push(`/paper/${materialId.value}/${paper.id}`)
}

function generatePaper() {
  void router.push(`/paper/${materialId.value}`)
}

async function removePaper(paper: PaperSummary) {
  if (!window.confirm(t('material.papers.deleteConfirm'))) return
  try {
    await api.deletePaper(paper.id)
    showToast(t('material.papers.deleted'))
    await load()
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  }
}

async function togglePaperAttempts(paper: PaperSummary) {
  if (expandedPaperId.value === paper.id) {
    expandedPaperId.value = null
    return
  }
  expandedPaperId.value = paper.id
  expandedAttemptId.value = null
  if (attemptsByPaper.value[paper.id]) return
  try {
    attemptsByPaper.value[paper.id] = await api.listPaperAttempts(paper.id)
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  }
}

async function toggleAttemptDetail(attempt: PaperAttemptSummary) {
  if (expandedAttemptId.value === attempt.id) {
    expandedAttemptId.value = null
    return
  }
  expandedAttemptId.value = attempt.id
  if (detailByAttempt.value[attempt.id]) return
  try {
    detailByAttempt.value[attempt.id] = await api.getAttempt(attempt.id)
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  }
}

function attemptOk(detail: PaperAttemptDetail): number {
  return detail.items.filter((i) => i.correct).length
}

async function saveTranscript() {
  if (!material.value) return
  savingTranscript.value = true
  try {
    const res = await api.updateTranscript(material.value.id, transcriptDraft.value)
    if (res.message) showToast(res.message, 'error', 8000)
    else showToast(t('material.transcript.saved'))
    editing.value = false
    await load()
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    savingTranscript.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <header class="page-head">
      <div class="head-main">
        <button class="back" type="button" @click="router.push('/')">
          <Icon name="arrowLeft" :size="14" />
          {{ t('material.back') }}
        </button>
        <h1>{{ material?.name || t('material.title') }}</h1>
      </div>
      <div v-if="material" class="head-meta">
        <span>{{ transcriptSourceLabel(material.transcript_source) }}</span>
        <span class="dot" aria-hidden="true">·</span>
        <span>{{ tn('common.words', material.words.length, { n: material.words.length }) }}</span>
        <template v-if="material.duration_s">
          <span class="dot" aria-hidden="true">·</span>
          <span>{{ tn('common.minutes', Math.round(material.duration_s / 60), { n: Math.round(material.duration_s / 60) }) }}</span>
        </template>
      </div>
    </header>

    <div v-if="loading" class="card empty-tip">{{ t('common.loading') }}</div>

    <template v-else-if="material">
      <section v-if="material.has_audio" class="card">
        <audio
          ref="audioEl"
          :src="api.audioUrl(material.id)"
          preload="metadata"
          style="display: none"
        ></audio>
        <div class="row between">
          <div class="row">
            <button class="big" type="button" @click="toggle">
              <Icon :name="playing ? 'pause' : 'play'" :size="14" />
              {{ playing ? t('material.pause') : t('material.play') }}
            </button>
            <button class="ghost small" type="button" @click="nudge(-5)">
              <Icon name="rewind" :size="13" />
              5s
            </button>
            <button class="ghost small" type="button" @click="nudge(5)">
              5s
              <Icon name="forward" :size="13" />
            </button>
          </div>
          <span class="timecode">{{ fmtTime(playTime) }} / {{ fmtTime(duration || material.duration_s || 0) }}</span>
        </div>
        <input
          class="seek"
          type="range"
          min="0"
          max="1000"
          step="1"
          :value="duration ? Math.round((playTime / duration) * 1000) : 0"
          :aria-label="t('material.seek')"
          @input="
            seek(((($event.target as HTMLInputElement).valueAsNumber || 0) / 1000) * (duration || 0))
          "
        />
      </section>

      <section class="card">
        <div class="cardtitle">
          <h2>{{ t('material.papers.title') }}</h2>
          <button class="big" type="button" @click="generatePaper">
            <Icon name="spark" :size="14" />
            {{ t('paper.generate') }}
          </button>
        </div>

        <div v-if="papers.length" class="papers">
          <article v-for="p in papers" :key="p.id" class="paper-row">
            <div class="paper-main">
              <div class="paper-title">
                <span v-for="b in p.blocks" :key="b.type" class="chip">
                  {{ typeNameOf(b.type) }} ×{{ b.count }}
                </span>
                <span v-if="p.stale" class="chip warn">{{ t('paper.stale') }}</span>
              </div>
              <div class="paper-meta">
                <span>{{ tn('common.questions', p.item_count, { n: p.item_count }) }}</span>
                <span class="dot" aria-hidden="true">·</span>
                <span>{{ fmtDateTime(p.created_at) }}</span>
              </div>
            </div>
            <div class="row">
              <button class="open" type="button" @click="openPaper(p)">
                {{ t('material.papers.open') }}
              </button>
              <button
                class="ghost small attempts"
                type="button"
                @click="togglePaperAttempts(p)"
              >
                {{ t('material.papers.attempts') }}
              </button>
              <button
                class="icon-btn"
                type="button"
                :title="t('material.papers.delete')"
                :aria-label="t('material.papers.delete')"
                @click="removePaper(p)"
              >
                <Icon name="trash" :size="14" />
              </button>
            </div>

            <div v-if="expandedPaperId === p.id" class="paper-attempts">
              <template v-if="attemptsByPaper[p.id]?.length">
                <div v-for="a in attemptsByPaper[p.id]" :key="a.id" class="attempt-wrap">
                  <button class="attempt-row" type="button" @click="toggleAttemptDetail(a)">
                    <span>{{ fmtDateTime(a.created_at) }}</span>
                    <span class="attempt-meta">
                      {{ tn('common.questions', a.item_count, { n: a.item_count }) }}
                    </span>
                  </button>
                  <div v-if="expandedAttemptId === a.id && detailByAttempt[a.id]" class="attempt-detail">
                    <span class="chip ok">
                      {{ t('material.papers.attempt.score', {
                        ok: attemptOk(detailByAttempt[a.id]),
                        total: detailByAttempt[a.id].items.length,
                      }) }}
                    </span>
                    <span
                      v-for="i in detailByAttempt[a.id].items"
                      :key="i.item_number"
                      class="chip item-chip"
                      :class="i.correct ? 'ok' : 'bad'"
                      :title="i.expected"
                    >
                      {{ i.item_number }}
                    </span>
                  </div>
                </div>
              </template>
              <div v-else class="empty-tip">{{ t('material.papers.attempts.empty') }}</div>
            </div>
          </article>
        </div>
        <div v-else class="empty-tip">{{ t('material.papers.empty') }}</div>
      </section>

      <section class="card">
        <div class="cardtitle">
          <h2>{{ t('material.transcript.title') }}</h2>
          <div class="row">
            <button
              v-if="!editing && timed"
              class="ghost small"
              type="button"
              :class="{ on: showStamps }"
              :title="showStamps ? t('material.transcript.hideStampsTitle') : t('material.transcript.showStampsTitle')"
              @click="showStamps = !showStamps"
            >
              <Icon name="clock" :size="13" />
              {{ showStamps ? t('material.transcript.hideStamps') : t('material.transcript.showStamps') }}
            </button>
            <button v-if="!editing" class="ghost small" type="button" @click="editing = true; transcriptDraft = material.transcript">
              <Icon name="edit" :size="13" />
              {{ t('material.transcript.edit') }}
            </button>
            <template v-else>
              <button class="ghost small" type="button" :disabled="savingTranscript" @click="editing = false">
                {{ t('common.cancel') }}
              </button>
              <button class="small" type="button" :disabled="savingTranscript" @click="saveTranscript">
                {{ savingTranscript ? t('common.saving') : t('material.transcript.saveAlign') }}
              </button>
            </template>
          </div>
        </div>
        <textarea v-if="editing" v-model="transcriptDraft" style="min-height: 220px" />
        <TranscriptView
          v-else
          :words="material.words"
          :sentences="material.sentences"
          :text="material.transcript"
          :current="playTime"
          :timed="timed"
          :show-stamps="showStamps"
          @seek-word="seekToWord"
          @seek-sentence="seekToSentence"
        />
        <p class="hint" style="margin-top: 10px">
          <template v-if="timed">{{ t('material.transcript.hintTimed') }}</template>
          <template v-else>{{ t('material.transcript.hintPlain') }}</template>
          {{ t('material.transcript.hintAlign') }}
        </p>
      </section>
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

.head-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.dot {
  color: var(--rule-strong);
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

.between {
  justify-content: space-between;
}

.timecode {
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.seek {
  width: 100%;
  margin-top: 12px;
  accent-color: var(--accent);
}

.papers {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 4px;
}

.paper-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 14px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper-2);
}

.paper-main {
  min-width: 0;
  flex: 1;
}

.paper-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 13.5px;
  font-weight: 500;
}

.paper-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 4px;
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.paper-attempts {
  flex-basis: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 10px;
  border-top: 1px dashed var(--rule);
}

.attempt-wrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.attempt-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper);
  color: var(--ink);
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
  text-align: left;
}

.attempt-row:hover:not(:disabled) {
  border-color: var(--rule-strong);
  opacity: 1;
}

.attempt-meta {
  color: var(--ink-3);
}

.attempt-detail {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  padding-left: 4px;
}

.icon-btn {
  padding: 7px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--ink-3);
}

.icon-btn:hover:not(:disabled) {
  border-color: var(--rule);
  background: var(--paper);
  color: var(--accent);
  opacity: 1;
}

.transcript {
  padding: 14px 16px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper-2);
  color: var(--ink-2);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 14.5px;
  line-height: 2;
  max-height: 320px;
  overflow-y: auto;
  white-space: pre-wrap;
}
</style>
