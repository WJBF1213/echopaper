<script setup lang="ts">
import { computed } from 'vue'
import type { Job } from '../api'
import { t } from '../i18n'
import Icon from './Icon.vue'

const props = defineProps<{ job: Job | null }>()

const stageLabel = computed(() => {
  switch (props.job?.state) {
    case 'queued':
      return t('job.queued')
    case 'downloading':
      return t('job.downloading')
    case 'transcribing':
      return t('job.transcribing')
    case 'generating':
      return t('job.generating')
    case 'done':
      return t('job.done')
    case 'error':
      return t('job.error')
    default:
      return t('job.preparing')
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
      <span class="hint">{{ job.message || t('job.working') }}</span>
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
