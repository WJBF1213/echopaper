<script setup lang="ts">
import { computed } from 'vue'
import { fmtTime } from '../lib/time'
import { t } from '../i18n'
import Icon from './Icon.vue'

const props = defineProps<{
  hasAudio: boolean
  playing: boolean
  current: number
  duration: number
  rate: number
  abA: number | null
  abB: number | null
  /** Evidence interval to highlight on the bar (seconds; 播放本题). */
  hlStart?: number | null
  hlEnd?: number | null
}>()

const emit = defineEmits<{
  toggle: []
  nudge: [delta: number]
  seek: [time: number]
  setRate: [rate: number]
  cycleAb: []
  clearAb: []
}>()

const progress = computed(() => {
  if (!props.duration) return 0
  return Math.min(100, (props.current / props.duration) * 100)
})

/** Highlight band geometry, as percentages of the full duration. */
const band = computed(() => {
  const { hlStart, hlEnd, duration } = props
  if (hlStart == null || hlEnd == null || !duration || hlEnd <= hlStart) return null
  return {
    left: Math.min(100, Math.max(0, (hlStart / duration) * 100)),
    width: Math.min(100, ((hlEnd - hlStart) / duration) * 100),
  }
})

const abLabel = computed(() => {
  if (props.abA == null) return t('player.ab')
  if (props.abB == null) return t('player.abWaitingB', { time: fmtTime(props.abA) })
  return `${fmtTime(props.abA)} – ${fmtTime(props.abB)}`
})

function onSeekInput(event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  if (!props.duration) return
  emit('seek', (value / 1000) * props.duration)
}

function onRateChange(event: Event) {
  emit('setRate', Number((event.target as HTMLSelectElement).value) || 1)
}
</script>

<template>
  <div v-if="hasAudio" class="player">
    <div class="seekrow">
      <span class="time">{{ fmtTime(current) }}</span>
      <div class="seekwrap">
        <span
          v-if="band"
          class="evidence-band"
          :style="{ left: `${band.left}%`, width: `${band.width}%` }"
        ></span>
        <input
          class="seek"
          type="range"
          min="0"
          max="1000"
          step="1"
          :value="Math.round(progress * 10)"
          :style="{ '--p': `${progress}%` }"
          :aria-label="t('player.progress')"
          @input="onSeekInput"
        />
      </div>
      <span class="time">{{ fmtTime(duration) }}</span>
    </div>

    <div class="playbar">
      <button class="play" type="button" :aria-label="playing ? t('player.pause') : t('player.play')" @click="emit('toggle')">
        <Icon :name="playing ? 'pause' : 'play'" :size="15" />
        {{ playing ? t('player.pause') : t('player.play') }}
      </button>
      <button class="ghost small" type="button" :title="t('player.back5')" @click="emit('nudge', -5)">
        <Icon name="rewind" :size="14" />
        5s
      </button>
      <button class="ghost small" type="button" :title="t('player.forward5')" @click="emit('nudge', 5)">
        5s
        <Icon name="forward" :size="14" />
      </button>
      <button
        class="ghost small"
        type="button"
        :class="{ on: abA != null }"
        @click="emit('cycleAb')"
      >
        <Icon name="repeat" :size="14" />
        {{ abLabel }}
      </button>
      <button v-if="abA != null" class="ghost small" type="button" @click="emit('clearAb')">
        {{ t('player.clearAb') }}
      </button>
      <select class="rate" :value="rate" :aria-label="t('player.rate')" @change="onRateChange">
        <option :value="1">1.0×</option>
        <option :value="0.8">0.8×</option>
        <option :value="0.6">0.6×</option>
      </select>
    </div>
  </div>
</template>

<style scoped>
.seekrow {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.time {
  min-width: 42px;
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}

.seekwrap {
  position: relative;
  flex: 1;
  display: flex;
}

/* Highlighted evidence interval (播放本题): a translucent band over the
 * track; pointer-events none so dragging through it still works. */
.evidence-band {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  height: 10px;
  border: 1px solid color-mix(in srgb, var(--accent) 60%, transparent);
  border-radius: 2px;
  background: color-mix(in srgb, var(--accent) 28%, transparent);
  pointer-events: none;
  z-index: 1;
}

.seek {
  flex: 1;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  border: none;
  border-radius: 2px;
  background: linear-gradient(
    90deg,
    var(--accent) var(--p, 0%),
    var(--paper-3) var(--p, 0%)
  );
  cursor: pointer;
}

.seek::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 13px;
  height: 13px;
  border: 2px solid var(--accent);
  border-radius: 50%;
  background: var(--paper);
  cursor: grab;
}

.seek::-moz-range-thumb {
  width: 11px;
  height: 11px;
  border: 2px solid var(--accent);
  border-radius: 50%;
  background: var(--paper);
  cursor: grab;
}

.playbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.play {
  min-width: 88px;
}

.rate {
  padding: 5px 8px;
  font-size: 12px;
}
</style>
