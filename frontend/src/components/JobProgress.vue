<script setup lang="ts">
import { computed } from 'vue'
import type { Job } from '../api'
import Icon from './Icon.vue'

const props = defineProps<{ job: Job | null }>()

const stageLabel = computed(() => {
  switch (props.job?.state) {
    case 'queued':
      return '排队'
    case 'downloading':
      return '下载音频'
    case 'transcribing':
      return '语音识别'
    case 'generating':
      return '生成题目'
    case 'done':
      return '完成'
    case 'error':
      return '失败'
    default:
      return '准备'
  }
})

const percent = computed(() => {
  const p = props.job?.percent
  return typeof p === 'number' ? Math.max(0, Math.min(100, p)) : 6
})
</script>

<template>
  <div v-if="job" class="job" role="status" aria-live="polite">
    <div class="job-head">
      <span class="chip" :class="{ ok: job.state === 'done', bad: job.state === 'error' }">
        <Icon
          :name="job.state === 'error' ? 'alert' : job.state === 'done' ? 'check' : 'clock'"
          :size="12"
        />
        {{ stageLabel }}
      </span>
      <span class="hint">{{ job.message || '正在处理…' }}</span>
      <span class="pct">{{ Math.round(percent) }}%</span>
    </div>
    <div class="progress" style="margin-top: 8px">
      <div :style="{ width: `${percent}%` }" />
    </div>
  </div>
</template>

<style scoped>
.job {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper);
}

.job-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.pct {
  margin-left: auto;
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
</style>
