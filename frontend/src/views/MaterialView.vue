<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type AttemptHistoryItem, type MaterialDetail } from '../api'
import { showToast } from '../router'
import { usePlayer } from '../composables/usePlayer'
import {
  fmtDateTime,
  fmtTime,
  hasWordTiming,
  modeLabel,
  pct,
  sentenceTimeRange,
  transcriptSourceLabel,
} from '../lib/time'
import { t, tn } from '../i18n'
import Icon from '../components/Icon.vue'
import TranscriptView from '../components/TranscriptView.vue'

const route = useRoute()
const router = useRouter()
const materialId = computed(() => String(route.params.materialId || ''))

const material = ref<MaterialDetail | null>(null)
const attempts = ref<AttemptHistoryItem[]>([])
const loading = ref(true)
const generating = ref(false)
const blankCount = ref(10)
const manualText = ref('')
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

const modes = computed(() => [
  { value: 'llm', label: t('mode.llm') },
  { value: 'nouns', label: t('mode.nouns') },
  { value: 'manual', label: t('mode.manual') },
])
const newMode = ref('llm')

async function load() {
  loading.value = true
  try {
    material.value = await api.getMaterial(materialId.value)
    attempts.value = await api.getAttempts(materialId.value)
    transcriptDraft.value = material.value.transcript
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

async function createSet() {
  if (!material.value) return
  generating.value = true
  try {
    const { set_id } = await api.createSet(
      material.value.id,
      newMode.value,
      blankCount.value,
      newMode.value === 'manual' ? manualText.value || undefined : undefined,
    )
    const created = await api.getSet(set_id)
    if (created.blank_count < blankCount.value) {
      showToast(
        t('material.sets.fewer', { n: created.blank_count }),
        'info',
        7000,
      )
    } else {
      showToast(t('material.sets.created'))
    }
    await load()
    void router.push(`/practice/${set_id}`)
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    generating.value = false
  }
}

async function removeSet(id: string) {
  if (!window.confirm(t('material.sets.deleteConfirm'))) return
  try {
    await api.deleteSet(id)
    await load()
    showToast(t('material.sets.deleted'))
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  }
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
          <h2>{{ t('material.sets.title') }}</h2>
        </div>

        <div v-if="material.sets.length" class="sets">
          <article v-for="s in material.sets" :key="s.id" class="set-row">
            <div class="set-main">
              <div class="set-title">
                {{ modeLabel(s.mode) }}
                <span v-if="s.stale" class="chip warn">{{ t('material.sets.stale') }}</span>
              </div>
              <div class="set-meta">
                <span>{{ tn('common.questions', s.blank_count, { n: s.blank_count }) }}</span>
                <span class="dot" aria-hidden="true">·</span>
                <span>{{ fmtDateTime(s.created_at) }}</span>
              </div>
            </div>
            <div class="row">
              <button type="button" @click="router.push(`/practice/${s.id}`)">{{ t('material.sets.start') }}</button>
              <button
                class="icon-btn"
                type="button"
                :title="t('material.sets.delete')"
                :aria-label="t('material.sets.delete')"
                @click="removeSet(s.id)"
              >
                <Icon name="trash" :size="14" />
              </button>
            </div>
          </article>
        </div>
        <div v-else class="empty-tip">{{ t('material.sets.empty') }}</div>

        <div class="gen-form">
          <label class="field">
            <span class="tag">{{ t('material.generate.mode') }}</span>
            <select v-model="newMode">
              <option v-for="m in modes" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
          </label>
          <label class="field">
            <span class="tag">{{ t('material.generate.count') }}</span>
            <input v-model.number="blankCount" type="number" min="1" max="40" />
          </label>
          <button class="big" type="button" :disabled="generating" @click="createSet">
            <Icon name="spark" :size="14" />
            {{ generating ? t('material.generate.creating') : t('material.generate.create') }}
          </button>
          <button class="ghost" type="button" @click="router.push(`/paper/${material.id}`)">
            <Icon name="book" :size="14" />
            {{ t('paper.open') }}
          </button>
        </div>

        <textarea
          v-if="newMode === 'manual'"
          v-model="manualText"
          class="manual-input"
          :placeholder="t('material.manual.placeholder')"
        />
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

      <section class="card">
        <h2>{{ t('material.attempts.title') }}</h2>
        <div v-if="!attempts.length" class="empty-tip">{{ t('material.attempts.empty') }}</div>
        <table v-else class="data">
          <thead>
            <tr>
              <th>{{ t('material.attempts.time') }}</th>
              <th>{{ t('material.attempts.mode') }}</th>
              <th>{{ t('material.attempts.score') }}</th>
              <th>{{ t('material.attempts.duration') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in attempts" :key="a.id">
              <td>{{ fmtDateTime(a.finished_at || a.started_at) }}</td>
              <td>{{ modeLabel(a.mode) }}</td>
              <td>{{ t('material.attempts.scoreValue', { ok: a.ok, total: a.total, pct: pct(a.ok, a.total) }) }}</td>
              <td>{{ a.duration_s ? t('common.seconds', { n: Math.round(a.duration_s) }) : t('common.none') }}</td>
            </tr>
          </tbody>
        </table>
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

.sets {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 18px;
}

.set-row {
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

.set-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 500;
}

.set-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 2px;
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.gen-form {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 14px;
  border-top: 1px solid var(--rule);
}

.manual-input {
  margin-top: 10px;
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
