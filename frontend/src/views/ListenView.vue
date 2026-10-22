<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type MaterialDetail, type Word } from '../api'
import { t } from '../i18n'
import { usePlayer } from '../composables/usePlayer'
import {
  activeWordIndex,
  blankSeekTime,
  hasWordTiming,
  sentenceTimeRange,
} from '../lib/time'
import Icon from '../components/Icon.vue'
import PlayerBar from '../components/PlayerBar.vue'

const route = useRoute()
const router = useRouter()
const materialId = computed(() => String(route.params.materialId || ''))

const material = ref<MaterialDetail | null>(null)
/** sentence_index -> Chinese translation; missing keys show the placeholder. */
const translations = ref<Record<number, string>>({})
const loading = ref(true)
const loadError = ref('')

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
  setAb,
  clearAb,
  cycleAb,
} = usePlayer(audioEl)

/** Interval of the last clicked sentence (design §7.3): started at the
 * sentence start −1.5s, ends at the sentence end. */
const playRange = ref<{ start: number; end: number } | null>(null)

const listEl = ref<HTMLElement | null>(null)

const timed = computed(
  () => Boolean(material.value?.has_audio) &&
    hasWordTiming(material.value?.words ?? []),
)

interface Row {
  index: number
  start: number
  end: number
  words: Word[]
  dst: string | null
}

const rows = computed<Row[]>(() => {
  const m = material.value
  if (!m) return []
  return m.sentences.map(([start, end], index) => ({
    index,
    start,
    end,
    words: m.words.slice(start, end + 1),
    dst: translations.value[index] ?? null,
  }))
})

const hasAudio = computed(() => Boolean(material.value?.has_audio))

/** Word currently audible (the TranscriptView highlight mechanism,
 * borrowed per-row here); -1 while paused in a pause. */
const activeWord = computed(() =>
  timed.value ? activeWordIndex(material.value?.words ?? [], playTime.value) : -1,
)

const activeSentenceIndex = computed(() => {
  if (activeWord.value < 0) return -1
  const sentences = material.value?.sentences ?? []
  return sentences.findIndex(
    ([start, end]) => activeWord.value >= start && activeWord.value <= end,
  )
})

/** Click a sentence: play from 句首−1.5s to 句尾 (design §7.3), reusing
 * the blankSeekTime / sentenceTimeRange helpers. */
function playSentence(index: number) {
  const row = rows.value[index]
  const m = material.value
  if (!row || !m || !hasAudio.value) return
  const times = sentenceTimeRange(m.words, { start: row.start, end: row.end })
  const first = m.words[row.start]
  if (!times || !first) return
  // Single-sentence playback replaces 单句循环: a stale AB loop would
  // wrap playback back to its own span and the click would never play
  // (usePlayer.onTimeUpdate seeks to abA once currentTime >= abB).
  clearAb()
  playRange.value = { start: blankSeekTime(first.s), end: times.b }
  seek(playRange.value.start, true)
}

/** Stop once playback passes the clicked sentence's end. */
watch(playTime, (time) => {
  const range = playRange.value
  if (range && time >= range.end) pause()
})

/** A manual seek on the bar leaves per-sentence playback mode. */
function onManualSeek(time: number) {
  playRange.value = null
  seek(time)
}

/** 单句循环 (design §7.3): set the player's AB loop around the sentence.
 * Looping replaces single-sentence playback mode -- otherwise the stale
 * stop-at-end watch would pause the loop on its first wrap. */
function loopSentence(index: number) {
  const row = rows.value[index]
  const m = material.value
  if (!row || !m) return
  const times = sentenceTimeRange(m.words, { start: row.start, end: row.end })
  if (times) {
    playRange.value = null
    setAb(times.a, times.b)
  }
}

/** Shortcut L: loop the sentence currently playing (design §7.3). */
function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'l' && event.key !== 'L') return
  const target = event.target as HTMLElement | null
  if (target && /^(input|textarea|select)$/i.test(target.tagName)) return
  const index = activeSentenceIndex.value >= 0
    ? activeSentenceIndex.value
    : rows.value.length
      ? rows.value[0].index
      : -1
  if (index >= 0) loopSentence(index)
}

/** Auto-scroll: keep the current sentence in view as playback moves. */
watch(activeSentenceIndex, (index) => {
  if (index < 0) return
  void nextTick(() => {
    const el = listEl.value?.querySelector(`[data-sentence="${index}"]`)
    el?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  })
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const detail = await api.getMaterial(materialId.value)
    material.value = detail
    // The translation snapshot never blocks the page (design §7.3):
    // a failed fetch just shows the placeholder everywhere.
    try {
      const snapshot = await api.getTranslations(materialId.value)
      const map: Record<number, string> = {}
      for (const row of snapshot.sentences) {
        if (row.dst) map[row.index] = row.dst
      }
      translations.value = map
    } catch {
      translations.value = {}
    }
  } catch (err) {
    material.value = null
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

watch(materialId, () => {
  playRange.value = null
  void load()
})

onMounted(() => {
  void load()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div>
    <header class="page-head">
      <div class="head-main">
        <button class="back" type="button" @click="router.push(`/material/${materialId}`)">
          <Icon name="arrowLeft" :size="14" />
          {{ t('listen.back') }}
        </button>
        <h1>{{ material?.name || t('listen.title') }}</h1>
        <span class="chip">{{ t('listen.title') }}</span>
      </div>
    </header>

    <!-- Shared transport (design §7.3): the same PlayerBar as PaperView. -->
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
        :hl-start="playRange?.start ?? null"
        :hl-end="playRange?.end ?? null"
        @toggle="toggle"
        @nudge="nudge"
        @seek="onManualSeek"
        @set-rate="setRate"
        @cycle-ab="cycleAb"
        @clear-ab="clearAb"
      />
      <p class="hint loop-hint">{{ t('listen.loopShortcutHint') }}</p>
    </section>

    <div v-if="loading" class="card empty-tip">{{ t('common.loading') }}</div>

    <div v-else-if="loadError" class="card">
      <div class="result bad">{{ loadError }}</div>
    </div>

    <div v-else-if="!rows.length" class="card empty-tip">
      <p>{{ t('listen.empty') }}</p>
    </div>

    <ol v-else ref="listEl" class="card sentences">
      <li
        v-for="row in rows"
        :key="row.index"
        class="sent-row"
        :class="{ active: row.index === activeSentenceIndex }"
        :data-sentence="row.index"
      >
        <button
          class="sent-main"
          type="button"
          :aria-label="t('listen.playSentence')"
          :title="t('listen.playSentence')"
          @click="playSentence(row.index)"
        >
          <span class="sent-en">
            <template v-for="(word, wi) in row.words" :key="wi">
              <span
                class="word"
                :class="{ active: timed && row.start + wi === activeWord }"
              >{{ word.w }}</span>{{ wi < row.words.length - 1 ? ' ' : '' }}
            </template>
          </span>
          <span class="sent-zh" :class="{ missing: row.dst == null }">
            {{ row.dst ?? t('listen.translationUnavailable') }}
          </span>
        </button>
        <button
          class="ghost small loop"
          type="button"
          :title="t('listen.loopSentence')"
          :aria-label="t('listen.loopSentence')"
          @click.stop="loopSentence(row.index)"
        >
          <Icon name="repeat" :size="13" />
        </button>
      </li>
    </ol>
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

.player-card {
  padding-bottom: 16px;
}

.loop-hint {
  margin-top: 10px;
}

.sentences {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: calc(100vh - 260px);
  min-height: 240px;
  overflow-y: auto;
  padding: 12px 14px;
  list-style: none;
}

.sent-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--rule);
  border-left: 3px solid transparent;
  border-radius: 3px;
  background: var(--paper);
}

.sent-row.active {
  border-color: var(--accent);
  border-left-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.sent-main {
  flex: 1;
  min-width: 0;
  padding: 2px 4px;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.sent-en {
  display: block;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 14.5px;
  line-height: 1.9;
  color: var(--ink);
}

.word {
  border-radius: 2px;
  padding: 1px 0;
  transition: background-color 0.12s ease;
}

.word.active {
  background: color-mix(in srgb, var(--accent) 22%, transparent);
}

.sent-zh {
  display: block;
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-2);
}

.sent-zh.missing {
  color: var(--ink-3);
  font-style: italic;
}

.loop {
  flex-shrink: 0;
  margin-top: 4px;
}
</style>
