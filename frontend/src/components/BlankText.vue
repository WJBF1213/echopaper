<script setup lang="ts">
import { computed } from 'vue'
import type { Blank, Word } from '../api'
import { activeWordIndex, fmtTime } from '../lib/time'
import Icon from './Icon.vue'

const props = defineProps<{
  words: Word[]
  sentences: [number, number][]
  blanks: Blank[]
  answers: Record<string, string>
  states: Record<string, 'ok' | 'bad'>
  reveal: boolean
  current?: number
  timed?: boolean
}>()

const emit = defineEmits<{
  answer: [blankId: string, value: string]
  jump: [blank: Blank]
  focusBlank: [blank: Blank]
  seekWord: [wordIndex: number]
  seekSentence: [sentenceIndex: number]
}>()

interface Token {
  kind: 'word' | 'blank'
  text?: string
  blank?: Blank
  breakAfter?: boolean
  wordIndex?: number
  sentenceIndex?: number
  sentenceStart?: boolean
  time?: number
}

const tokens = computed<Token[]>(() => {
  const byStart = new Map<number, Blank>()
  for (const b of props.blanks) byStart.set(b.word_start, b)
  const sentenceEnds = new Set(props.sentences.map(([, end]) => end))
  const sentenceStarts = new Set(props.sentences.map(([start]) => start))
  const sentenceOf = new Map<number, number>()
  props.sentences.forEach(([start, end], index) => {
    for (let i = start; i <= end; i += 1) sentenceOf.set(i, index)
  })
  const out: Token[] = []
  let i = 0
  while (i < props.words.length) {
    const blank = byStart.get(i)
    if (blank) {
      out.push({
        kind: 'blank',
        blank,
        breakAfter: sentenceEnds.has(blank.word_end),
        wordIndex: i,
        sentenceIndex: sentenceOf.get(i),
        sentenceStart: sentenceStarts.has(i),
        time: props.words[i]?.s,
      })
      i = blank.word_end + 1
      continue
    }
    out.push({
      kind: 'word',
      text: props.words[i].w,
      breakAfter: sentenceEnds.has(i),
      wordIndex: i,
      sentenceIndex: sentenceOf.get(i),
      sentenceStart: sentenceStarts.has(i),
      time: props.words[i].s,
    })
    i += 1
  }
  return out
})

const activeIndex = computed(() =>
  props.timed ? activeWordIndex(props.words, props.current ?? 0) : -1,
)
const showTime = computed(() => Boolean(props.timed))

function isActive(token: Token): boolean {
  if (activeIndex.value < 0 || token.wordIndex == null) return false
  if (token.kind === 'blank' && token.blank) {
    return activeIndex.value >= token.blank.word_start &&
      activeIndex.value <= token.blank.word_end
  }
  return activeIndex.value === token.wordIndex
}

function onWordClick(token: Token) {
  if (!props.timed || token.wordIndex == null) return
  emit('seekWord', token.wordIndex)
}

function onSentenceClick(token: Token) {
  if (!props.timed || token.sentenceIndex == null) return
  emit('seekSentence', token.sentenceIndex)
}

function stateOf(blank: Blank): 'ok' | 'bad' | '' {
  return props.states[blank.id] || ''
}

/** Answer lines grow with the expected answer, but stay compact. */
function widthFor(blank: Blank): string {
  const chars = Math.max(6, Math.min(16, blank.answer.length + 2))
  return `${chars * 9}px`
}
</script>

<template>
  <div class="exam">
    <template v-for="(token, index) in tokens" :key="index">
      <template v-if="token.sentenceStart && token.sentenceIndex != null">
        <button
          v-if="showTime"
          class="sent-time"
          type="button"
          :title="`从 ${fmtTime(token.time ?? 0)} 播放本句`"
          @click.stop="onSentenceClick(token)"
        >{{ fmtTime(token.time ?? 0) }}</button>
      </template>

      <template v-if="token.kind === 'blank' && token.blank">
        <span class="blank" :class="[stateOf(token.blank), { active: isActive(token) }]"><span class="qnum" aria-hidden="true">{{ token.blank.position }}</span><input
            :value="answers[token.blank.id] || ''"
            :style="{ width: widthFor(token.blank) }"
            autocomplete="off"
            spellcheck="false"
            :aria-label="`第 ${token.blank.position} 题，${token.blank.word_limit}`"
            :title="`第 ${token.blank.position} 题 · ${token.blank.word_limit}`"
            @input="emit('answer', token.blank.id, ($event.target as HTMLInputElement).value)"
            @focus="emit('focusBlank', token.blank)"
            @click.stop="emit('jump', token.blank)"
          /><span v-if="token.breakAfter" class="end-dot">.</span><span
            v-if="stateOf(token.blank) === 'bad' || (reveal && stateOf(token.blank) !== 'ok')"
            class="mark bad"
          >{{ token.blank.answer }}</span><Icon
            v-else-if="stateOf(token.blank) === 'ok'"
            class="mark ok"
            name="check"
            :size="13"
          /></span><template v-if="token.breakAfter"><br /></template><template v-else>{{ ' ' }}</template>
      </template>

      <template v-else>
        <span
          class="word"
          :class="{ active: isActive(token), clickable: timed }"
          :data-word-index="token.wordIndex"
          :title="timed ? `${fmtTime(token.time ?? 0)} 起播放` : undefined"
          @click="onWordClick(token)"
        >{{ token.text }}</span><template v-if="token.breakAfter"><span class="end-dot">.</span><br /></template><template v-else>{{ ' ' }}</template>
      </template>
    </template>
  </div>
</template>

<style scoped>
.exam {
  padding: 8px 2px 4px;
  font-family: Georgia, 'Times New Roman', 'Songti SC', serif;
  font-size: 17.5px;
  line-height: 2.9;
  color: var(--ink);
  max-height: 62vh;
  overflow-y: auto;
}

.word {
  white-space: pre-wrap;
  border-radius: 2px;
  transition: background-color 0.12s ease;
}

.word.clickable {
  cursor: pointer;
}

.word.clickable:hover {
  background: color-mix(in srgb, var(--ink) 7%, transparent);
}

.word.active {
  background: color-mix(in srgb, var(--accent) 20%, transparent);
  color: var(--ink);
}

.blank.active input {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}

.sent-time {
  display: inline-block;
  margin-right: 7px;
  padding: 0 5px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper);
  color: var(--ink-3);
  font-family: -apple-system, 'PingFang SC', system-ui, sans-serif;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  line-height: 1.6;
  vertical-align: 2px;
  cursor: pointer;
}

.sent-time:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--paper);
  color: var(--accent);
  opacity: 1;
}

.end-dot {
  color: var(--ink-2);
}

.blank {
  display: inline-flex;
  align-items: baseline;
  gap: 0;
  vertical-align: baseline;
  white-space: nowrap;
}

/* Question number sits in the text flow like a printed paper item. */
.qnum {
  margin-right: 3px;
  color: var(--accent);
  font-family: -apple-system, 'PingFang SC', system-ui, sans-serif;
  font-size: 10.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.blank input {
  padding: 0 4px 1px;
  border: none;
  border-bottom: 1px solid var(--ink-2);
  border-radius: 0;
  background: transparent;
  color: var(--ink);
  font-family: inherit;
  font-size: 16px;
  line-height: 1.4;
  text-align: center;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.blank input:focus {
  outline: none;
  border-bottom-color: var(--focus);
  border-bottom-width: 2px;
  background: color-mix(in srgb, var(--focus) 7%, transparent);
  box-shadow: none;
}

.blank.ok input {
  border-bottom-color: var(--ok);
  color: var(--ok);
}

.blank.bad input {
  border-bottom-color: var(--accent);
  color: var(--accent);
}

/* Corrections are written in the margin in green, like a marked paper. */
.mark {
  margin-left: 6px;
  font-family: -apple-system, 'PingFang SC', system-ui, sans-serif;
  font-size: 12.5px;
  line-height: 1.4;
}

.mark.bad {
  color: var(--ok);
  white-space: nowrap;
}

.mark.bad::before {
  content: '→ ';
  color: var(--ink-3);
}

.mark.ok {
  color: var(--ok);
}
</style>
