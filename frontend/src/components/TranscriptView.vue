<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Word } from '../api'
import { activeWordIndex, fmtTime } from '../lib/time'
import { t } from '../i18n'

const props = withDefaults(
  defineProps<{
    words: Word[]
    sentences: [number, number][]
    text?: string
    current?: number
    timed?: boolean
    showStamps?: boolean
  }>(),
  { text: '', current: 0, timed: false, showStamps: true },
)

const emit = defineEmits<{
  seekWord: [wordIndex: number]
  seekSentence: [sentenceIndex: number]
}>()

const root = ref<HTMLElement | null>(null)

const ranges = computed<[number, number][]>(() => {
  if (props.sentences.length) return props.sentences
  return props.words.length ? [[0, props.words.length - 1]] : []
})

const active = computed(() =>
  props.timed ? activeWordIndex(props.words, props.current) : -1,
)
const showTime = computed(() => props.timed && props.showStamps)

watch(active, (index) => {
  if (index < 0) return
  const el = root.value?.querySelector<HTMLElement>(`[data-word-index="${index}"]`)
  el?.scrollIntoView?.({ block: 'nearest' })
})

function timeOf(wordIndex: number): number {
  return props.words[wordIndex]?.s ?? 0
}

function wordAt(wordIndex: number): Word | undefined {
  return props.words[wordIndex]
}
</script>

<template>
  <div ref="root" class="transcript" :class="{ timed }">
    <p v-if="!ranges.length">{{ text || t('transcript.empty') }}</p>
    <template v-else>
      <p v-for="(range, sentenceIndex) in ranges" :key="sentenceIndex" class="sent">
        <button
          v-if="showTime"
          class="sent-time"
          type="button"
          :title="t('transcript.playFrom', { time: fmtTime(timeOf(range[0])) })"
          @click.stop="emit('seekSentence', sentenceIndex)"
        >{{ fmtTime(timeOf(range[0])) }}</button>
        <template v-for="wi in range[1] - range[0] + 1" :key="wi">
          <template v-if="wordAt(range[0] + wi - 1)">
            <span
              class="word"
              :class="{ active: timed && range[0] + wi - 1 === active, clickable: timed }"
              :data-word-index="range[0] + wi - 1"
              :title="timed ? t('transcript.playFromWord', { time: fmtTime(timeOf(range[0] + wi - 1)) }) : undefined"
              @click="timed && emit('seekWord', range[0] + wi - 1)"
            >{{ wordAt(range[0] + wi - 1)?.w }}</span>{{ wi < range[1] - range[0] + 1 ? ' ' : '' }}
          </template>
        </template>
      </p>
    </template>
  </div>
</template>

<style scoped>
.transcript {
  padding: 14px 16px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper-2);
  color: var(--ink-2);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 14.5px;
  line-height: 2;
  max-height: 340px;
  overflow-y: auto;
}

.sent {
  margin-bottom: 2px;
}

.sent:last-child {
  margin-bottom: 0;
}

.sent-time {
  display: inline-block;
  margin-right: 8px;
  padding: 0 6px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper);
  color: var(--ink-3);
  font-family: -apple-system, 'PingFang SC', system-ui, sans-serif;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  line-height: 1.7;
  vertical-align: 2px;
  cursor: pointer;
}

.sent-time:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--paper);
  color: var(--accent);
  opacity: 1;
}

.word {
  border-radius: 2px;
  padding: 1px 0;
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

@media (max-width: 560px) {
  .transcript {
    padding: 10px 12px;
    font-size: 14px;
  }
}
</style>
