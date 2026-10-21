<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  api,
  type AttemptItemResult,
  type Blank,
  type MaterialDetail,
  type SetDetail,
  type Word,
} from '../api'
import { showToast } from '../router'
import { usePlayer } from '../composables/usePlayer'
import { useDraft } from '../composables/useDraft'
import {
  blankSeekTime,
  buildDictationBlanks,
  fmtTime,
  hasWordTiming,
  modeLabel,
  pct,
  sentenceRangeFor,
  sentenceText,
  sentenceTimeRange,
  transcriptSourceLabel,
} from '../lib/time'
import PlayerBar from '../components/PlayerBar.vue'
import BlankText from '../components/BlankText.vue'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()
const setId = computed(() => String(route.params.setId || ''))

const set = ref<SetDetail | null>(null)
const material = ref<MaterialDetail | null>(null)
const loading = ref(true)
const error = ref('')

const audioEl = ref<HTMLAudioElement | null>(null)
const {
  playing,
  current: playTime,
  duration,
  rate,
  abA,
  abB,
  seek,
  toggle,
  nudge,
  setRate,
  setAb,
  clearAb,
  cycleAb,
} = usePlayer(audioEl)
const hasAudio = computed(() => Boolean(material.value?.has_audio))
const timed = computed(
  () => hasAudio.value && hasWordTiming(words.value),
)

const draft = useDraft(setId.value)
const answers = draft.answers
const states = reactive<Record<string, 'ok' | 'bad'>>({})
const reveal = ref(false)
const grading = ref(false)
const lastResult = ref<{ ok: number; total: number } | null>(null)
const startedAt = ref<number>(Date.now())

const dictation = ref(false)
const dictationInputs = reactive<Record<number, string>>({})
const dictationStates = reactive<Record<number, 'ok' | 'bad'>>({})
const dictationResult = ref<{ ok: number; total: number } | null>(null)

const showCn = ref(false)
const translations = reactive<Record<number, string>>({})
const translating = ref(false)

const blankList = computed<Blank[]>(() => set.value?.blanks ?? [])
const words = computed<Word[]>(() => material.value?.words ?? [])
const sentences = computed<[number, number][]>(() => material.value?.sentences ?? [])

const filledCount = computed(
  () => blankList.value.filter((b) => (answers[b.id] || '').trim()).length,
)
const okCount = computed(() => Object.values(states).filter((s) => s === 'ok').length)
const badCount = computed(() => Object.values(states).filter((s) => s === 'bad').length)
const modeName = computed(() => modeLabel(set.value?.mode || ''))
const sourceName = computed(() =>
  material.value ? transcriptSourceLabel(material.value.transcript_source) : '',
)

/** The paper instruction states the largest span allowed in this set. */
const wordLimitLabel = computed(() => {
  const maxSpan = blankList.value.reduce(
    (acc, b) => Math.max(acc, b.word_end - b.word_start + 1),
    1,
  )
  return maxSpan <= 1
    ? 'ONE WORD AND/OR A NUMBER'
    : maxSpan === 2
      ? 'NO MORE THAN TWO WORDS AND/OR A NUMBER'
      : 'NO MORE THAN THREE WORDS AND/OR A NUMBER'
})

const dictItems = computed(() =>
  dictation.value ? buildDictationBlanks(words.value, sentences.value) : [],
)
const dictWordIndexes = computed(() => new Set(dictItems.value.map((d) => d.wordIndex)))

function applyAbForBlank(blank: Blank) {
  if (!hasAudio.value) return
  const range = sentenceRangeFor(sentences.value, blank.word_start)
  if (!range) return
  const times = sentenceTimeRange(words.value, range)
  if (times) setAb(times.a, times.b, true)
}

function jumpToBlank(blank: Blank) {
  if (!hasAudio.value) return
  seek(blankSeekTime(blank.t_start), false)
  applyAbForBlank(blank)
}

function seekToWord(wordIndex: number) {
  if (!timed.value) return
  const word = words.value[wordIndex]
  if (!word) return
  clearAb()
  seek(word.s, true)
}

function seekToSentence(sentenceIndex: number) {
  if (!timed.value) return
  const range = sentences.value[sentenceIndex]
  if (!range) return
  const times = sentenceTimeRange(words.value, { start: range[0], end: range[1] })
  if (times) setAb(times.a, times.b, true)
}

function jumpDictation(item: { wordIndex: number; sentenceIndex: number }) {
  if (!hasAudio.value) return
  const word = words.value[item.wordIndex]
  if (!word) return
  seek(blankSeekTime(word.s), false)
  const range = sentences.value[item.sentenceIndex]
  if (range) {
    const times = sentenceTimeRange(words.value, { start: range[0], end: range[1] })
    if (times) setAb(times.a, times.b, true)
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const detail = await api.getSet(setId.value)
    set.value = detail
    material.value = await api.getMaterial(detail.material_id)
    const t = Number(route.query.t)
    if (Number.isFinite(t) && t > 0) setTimeout(() => seek(t, false), 300)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
  startedAt.value = Date.now()
}

async function checkAll() {
  if (!set.value || grading.value) return
  grading.value = true
  try {
    const result = await api.submitAttempt(
      set.value.id,
      blankList.value.map((b) => ({ blank_id: b.id, text: (answers[b.id] || '').trim() })),
      Math.round((Date.now() - startedAt.value) / 1000),
    )
    for (const key of Object.keys(states)) delete states[key]
    for (const item of result.results as AttemptItemResult[]) {
      states[item.blank_id] = item.correct ? 'ok' : 'bad'
    }
    lastResult.value = { ok: result.ok, total: result.total }
    if (result.total === 0) showToast('没有可批改的作答', 'error')
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    grading.value = false
  }
}

async function checkDictation() {
  if (!material.value) return
  const items = dictItems.value
    .filter((d) => (dictationInputs[d.wordIndex] || '').trim())
    .map((d) => ({ word_index: d.wordIndex, text: dictationInputs[d.wordIndex] }))
  if (!items.length) {
    showToast('先填写至少一个空再批改', 'error')
    return
  }
  try {
    const result = await api.submitDictation(material.value.id, items)
    for (const item of result.results) {
      dictationStates[item.word_index] = item.correct ? 'ok' : 'bad'
    }
    dictationResult.value = { ok: result.ok, total: result.total }
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  }
}

function revealAll() {
  reveal.value = true
  for (const b of blankList.value) {
    if (!(answers[b.id] || '').trim()) answers[b.id] = b.answer
    if (!states[b.id]) states[b.id] = 'bad'
  }
  showToast('已显示全部答案')
}

function retryWrong() {
  const wrong = blankList.value.filter((b) => states[b.id] === 'bad')
  if (!wrong.length) {
    showToast('没有错题')
    return
  }
  for (const b of wrong) {
    answers[b.id] = ''
    delete states[b.id]
  }
  reveal.value = false
  lastResult.value = null
  showToast(`已清空 ${wrong.length} 个错题，重新作答`)
}

function resetAll() {
  if (!window.confirm('清空全部作答并重做？')) return
  draft.clear()
  for (const key of Object.keys(states)) delete states[key]
  for (const key of Object.keys(dictationInputs)) delete dictationInputs[Number(key)]
  for (const key of Object.keys(dictationStates)) delete dictationStates[Number(key)]
  reveal.value = false
  lastResult.value = null
  dictationResult.value = null
  seek(0, false)
  startedAt.value = Date.now()
}

async function toggleTranslations() {
  if (showCn.value) {
    showCn.value = false
    return
  }
  showCn.value = true
  if (!material.value) return
  const ranges = material.value.sentences
  const missing = ranges
    .map((range, index) => ({
      index,
      text: sentenceText(words.value, { start: range[0], end: range[1] }),
    }))
    .filter((item) => item.text && !translations[item.index])
  if (!missing.length) return
  translating.value = true
  let failed = 0
  try {
    for (const item of missing) {
      try {
        const res = await api.translate(item.text)
        if (res.text) translations[item.index] = res.text
        else failed += 1
      } catch {
        failed += 1
      }
    }
  } finally {
    translating.value = false
  }
  if (failed) showToast(`${failed} 句翻译失败（需要联网或配置 LLM 密钥）`, 'error')
}

function speakAll(slow = false) {
  if (typeof window === 'undefined' || !('speechSynthesis' in window) || !material.value) return
  window.speechSynthesis.cancel()
  const text = material.value.transcript || words.value.map((w) => w.w).join(' ')
  const utter = new SpeechSynthesisUtterance(text)
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.startsWith('en'))
  const voice = voices.find((v) => /GB|UK/i.test(v.lang + v.name)) || voices[0]
  if (voice) utter.voice = voice
  utter.lang = 'en-GB'
  utter.rate = slow ? 0.7 : 1
  window.speechSynthesis.speak(utter)
}

/* ------------------------------------------------------------- shortcuts */

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return Boolean(el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable))
}

function focusNextBlank(direction: 1 | -1) {
  const inputs = Array.from(
    document.querySelectorAll<HTMLInputElement>('.exam .blank input, .dict-word input'),
  )
  if (!inputs.length) return
  const active = document.activeElement as HTMLInputElement | null
  const index = active ? inputs.indexOf(active) : -1
  if (index === -1) {
    inputs[0].focus()
    return
  }
  const next = (index + direction + inputs.length) % inputs.length
  inputs[next].focus()
}

function onKeydown(event: KeyboardEvent) {
  if (isTypingTarget(event.target) && event.key !== 'Enter') {
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault()
      focusNextBlank(event.key === 'ArrowDown' ? 1 : -1)
    }
    return
  }
  switch (event.key) {
    case ' ':
      if (isTypingTarget(event.target)) return
      event.preventDefault()
      if (hasAudio.value) toggle()
      break
    case 'ArrowLeft':
      if (isTypingTarget(event.target)) return
      event.preventDefault()
      if (hasAudio.value) nudge(-5)
      break
    case 'ArrowRight':
      if (isTypingTarget(event.target)) return
      event.preventDefault()
      if (hasAudio.value) nudge(5)
      break
    case 'ArrowDown':
      event.preventDefault()
      focusNextBlank(1)
      break
    case 'ArrowUp':
      event.preventDefault()
      focusNextBlank(-1)
      break
    case 'Enter':
      event.preventDefault()
      if (dictation.value) void checkDictation()
      else void checkAll()
      break
  }
}

watch(setId, () => {
  void load()
})

onMounted(() => {
  void load()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
})
</script>

<template>
  <div>
    <header class="page-head">
      <div class="head-main">
        <button
          class="back"
          type="button"
          @click="router.push(material ? `/material/${material.id}` : '/')"
        >
          <Icon name="arrowLeft" :size="14" />
          返回
        </button>
        <h1>{{ material?.name || '练习' }}</h1>
        <span v-if="set" class="chip">{{ modeName }}</span>
        <span v-if="material" class="chip">{{ sourceName }}</span>
        <span v-if="set?.stale" class="chip warn">基于旧转写</span>
      </div>

      <div class="head-stats">
        <span class="stat">
          <span class="stat-label">正确</span>
          <b>{{ okCount }}</b>
        </span>
        <span class="stat">
          <span class="stat-label">错误</span>
          <b class="bad">{{ badCount }}</b>
        </span>
        <span class="stat">
          <span class="stat-label">已填</span>
          <b>{{ filledCount }}<span class="total">/{{ blankList.length }}</span></b>
        </span>
      </div>
    </header>

    <div v-if="loading" class="card empty-tip">加载中…</div>
    <div v-else-if="error" class="card">
      <div class="result bad">{{ error }}</div>
    </div>

    <template v-else>
      <section class="card player-card">
        <audio
          v-if="hasAudio && material"
          ref="audioEl"
          :src="api.audioUrl(material.id)"
          preload="metadata"
          style="display: none"
        ></audio>

        <PlayerBar
          v-if="hasAudio"
          :has-audio="hasAudio"
          :playing="playing"
          :current="playTime"
          :duration="duration"
          :rate="rate"
          :ab-a="abA"
          :ab-b="abB"
          @toggle="toggle"
          @nudge="nudge"
          @seek="(t) => seek(t)"
          @set-rate="setRate"
          @cycle-ab="cycleAb"
          @clear-ab="clearAb"
        />
        <div v-else class="row">
          <button class="big" type="button" @click="speakAll(false)">
            <Icon name="volume" :size="14" />
            朗读原文
          </button>
          <button class="ghost" type="button" @click="speakAll(true)">慢速</button>
          <span class="hint">此材料无音频，使用浏览器语音朗读。</span>
        </div>

        <p class="hint player-hint">
          <template v-if="hasAudio">
            点击题号可跳到该词前 1.5 秒并循环整句。<kbd>空格</kbd> 播放/暂停，<kbd>←</kbd>
            <kbd>→</kbd> 前后 5 秒，<kbd>回车</kbd> 批改。
          </template>
          <template v-else>此材料没有词级时间戳，题号不跳转。</template>
        </p>
      </section>

      <section class="card">
        <div class="cardtitle">
          <h2>{{ dictation ? '全篇听写' : '题目' }}</h2>
          <div class="row">
            <button
              class="ghost small"
              type="button"
              :class="{ on: dictation }"
              @click="dictation = !dictation"
            >
              <Icon name="headphonesOff" :size="13" />
              {{ dictation ? '退出听写' : '全篇听写' }}
            </button>
            <button
              class="ghost small"
              type="button"
              :class="{ on: showCn }"
              :disabled="translating"
              @click="toggleTranslations"
            >
              <Icon name="translate" :size="13" />
              {{ translating ? '翻译中…' : '逐句翻译' }}
            </button>
          </div>
        </div>

        <template v-if="!dictation">
          <div class="instruction">
            <span class="section-label">
              Questions {{ blankList[0]?.position }}–{{ blankList[blankList.length - 1]?.position }}
            </span>
            <p>
              Complete the notes below. Write
              <strong>{{ wordLimitLabel }}</strong> for each answer.
            </p>
          </div>

          <BlankText
            :words="words"
            :sentences="sentences"
            :blanks="blankList"
            :answers="answers"
            :states="states"
            :reveal="reveal"
            :current="playTime"
            :timed="timed"
            @answer="(id, value) => (answers[id] = value)"
            @jump="jumpToBlank"
            @seek-word="seekToWord"
            @seek-sentence="seekToSentence"
          />

          <div v-if="showCn" class="cn-list">
            <p v-for="(range, index) in sentences" :key="index" class="cn">
              <span class="cn-tag">{{ index + 1 }}</span>
              {{ translations[index] || (translating ? '翻译中…' : '—') }}
            </p>
          </div>
        </template>

        <template v-else>
          <div class="dictation-box">
            <section v-for="(range, sentIndex) in sentences" :key="sentIndex" class="dict-sentence">
              <div class="dict-row">
                <button
                  v-if="timed"
                  class="sent-time"
                  type="button"
                  :title="`从 ${fmtTime(words[range[0]]?.s ?? 0)} 播放本句`"
                  @click.stop="seekToSentence(sentIndex)"
                >{{ fmtTime(words[range[0]]?.s ?? 0) }}</button>
                <span class="sent-index">{{ sentIndex + 1 }}</span>
                <template v-for="wi in range[1] - range[0] + 1" :key="wi">
                  <span v-if="words[range[0] + wi - 1]" class="dict-word">
                    <template v-if="dictWordIndexes.has(range[0] + wi - 1)">
                      <input
                        :value="dictationInputs[range[0] + wi - 1] || ''"
                        :class="dictationStates[range[0] + wi - 1]"
                        :style="{
                          width: `${Math.max(58, words[range[0] + wi - 1].w.length * 9 + 18)}px`,
                        }"
                        autocomplete="off"
                        spellcheck="false"
                        @input="
                          dictationInputs[range[0] + wi - 1] = (
                            $event.target as HTMLInputElement
                          ).value
                        "
                        @click="
                          jumpDictation({ wordIndex: range[0] + wi - 1, sentenceIndex: sentIndex })
                        "
                      />
                    </template>
                    <template v-else>
                      <span class="dict-anchor">{{ words[range[0] + wi - 1].w }}</span>
                    </template>
                  </span>
                </template>
              </div>
              <p v-if="showCn" class="cn">
                <span class="cn-tag">{{ sentIndex + 1 }}</span>
                {{ translations[sentIndex] || (translating ? '翻译中…' : '—') }}
              </p>
            </section>
          </div>
          <div
            v-if="dictationResult"
            class="result"
            :class="dictationResult.ok === dictationResult.total ? 'good' : 'meh'"
          >
            听写正确率 {{ pct(dictationResult.ok, dictationResult.total) }}%（{{
              dictationResult.ok
            }}/{{ dictationResult.total }}）
          </div>
        </template>
      </section>

      <section class="card actions-card">
        <div class="row">
          <button
            class="big"
            type="button"
            :disabled="grading"
            @click="dictation ? checkDictation() : checkAll()"
          >
            <Icon name="check" :size="14" />
            {{ grading ? '批改中…' : '批改' }}
          </button>
          <button class="ghost" type="button" @click="revealAll">
            <Icon name="eye" :size="14" />
            显示答案
          </button>
          <button v-if="!dictation" class="ghost" type="button" @click="retryWrong">
            <Icon name="refresh" :size="14" />
            重做错题
          </button>
          <button class="ghost" type="button" @click="resetAll">
            <Icon name="trash" :size="14" />
            清空
          </button>
        </div>

        <div
          v-if="lastResult && !dictation"
          class="result"
          :class="lastResult.ok === lastResult.total ? 'good' : 'meh'"
        >
          <template v-if="lastResult.ok === lastResult.total">
            全部正确（{{ lastResult.ok }}/{{ lastResult.total }}）。
          </template>
          <template v-else>
            正确 {{ lastResult.ok }}/{{ lastResult.total }}（{{
              pct(lastResult.ok, lastResult.total)
            }}%）。标红的题可直接改，或点「重做错题」。
          </template>
        </div>
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

.head-stats {
  display: flex;
  gap: 20px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.stat-label {
  color: var(--ink-3);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.stat b {
  font-size: 17px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.stat b.bad {
  color: var(--accent);
}

.total {
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 400;
}

.player-card {
  padding-bottom: 16px;
}

.player-hint {
  margin-top: 12px;
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

.instruction strong {
  color: var(--ink);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.cn-list {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--rule);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cn {
  padding-left: 10px;
  border-left: 2px solid var(--rule);
  color: var(--ink-3);
  font-size: 13px;
  line-height: 1.8;
}

.cn-tag {
  display: inline-block;
  min-width: 18px;
  color: var(--rule-strong);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}

.dictation-box {
  max-height: 62vh;
  overflow-y: auto;
}

.dict-sentence {
  padding: 10px 0;
  border-bottom: 1px solid var(--rule);
}

.dict-sentence:last-child {
  border-bottom: none;
}

.dict-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 5px 3px;
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 15px;
  line-height: 2.2;
}

.sent-time {
  padding: 0 5px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper);
  color: var(--ink-3);
  font-family: -apple-system, 'PingFang SC', system-ui, sans-serif;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  line-height: 1.6;
  cursor: pointer;
}

.sent-time:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--paper);
  color: var(--accent);
  opacity: 1;
}

.sent-index {
  min-width: 18px;
  color: var(--rule-strong);
  font-family: -apple-system, 'PingFang SC', system-ui, sans-serif;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}

.dict-word input {
  padding: 1px 4px;
  border: none;
  border-bottom: 1px solid var(--ink-2);
  border-radius: 0;
  background: transparent;
  color: var(--ink);
  font-family: inherit;
  font-size: 14px;
  text-align: center;
}

.dict-word input:focus {
  outline: none;
  border-bottom-color: var(--focus);
  border-bottom-width: 2px;
  background: color-mix(in srgb, var(--focus) 7%, transparent);
  box-shadow: none;
}

.dict-word input.ok {
  border-bottom-color: var(--ok);
  color: var(--ok);
}

.dict-word input.bad {
  border-bottom-color: var(--accent);
  color: var(--accent);
}

.dict-anchor {
  color: var(--ink-2);
}

.actions-card {
  display: flex;
  flex-direction: column;
}
</style>
