<script setup lang="ts">
import { computed } from 'vue'
import type { BatchStatus, JobState } from '../api'
import Icon from './Icon.vue'

const props = defineProps<{ batch: BatchStatus }>()
const emit = defineEmits<{ openMaterial: [materialId: string] }>()

const percent = computed(() =>
  Math.max(0, Math.min(100, Number(props.batch.percent) || 0)),
)

const summary = computed(() => {
  const { done, error, running, total } = props.batch
  const parts = [`${done}/${total} 完成`]
  if (running) parts.push(`${running} 进行中`)
  if (error) parts.push(`${error} 失败`)
  return parts.join(' · ')
})

function label(state: JobState): string {
  switch (state) {
    case 'queued':
      return '排队'
    case 'downloading':
      return '下载'
    case 'transcribing':
      return '识别'
    case 'generating':
      return '出题'
    case 'done':
      return '完成'
    case 'error':
      return '失败'
    default:
      return state
  }
}
</script>

<template>
  <section class="card batch" role="status" aria-live="polite">
    <div class="cardtitle">
      <h2>批量导入 · {{ batch.name }}</h2>
      <span class="pct">{{ Math.round(percent) }}%</span>
    </div>
    <p class="hint">{{ summary }}</p>
    <div class="progress" style="margin-top: 8px">
      <div :style="{ width: `${percent}%` }" />
    </div>

    <div class="jobs">
      <div v-for="job in batch.jobs" :key="job.job_id" class="jobrow">
        <span class="chip" :class="{ ok: job.state === 'done', bad: job.state === 'error' }">
          <Icon
            :name="job.state === 'error' ? 'alert' : job.state === 'done' ? 'check' : 'clock'"
            :size="12"
          />
          {{ label(job.state) }}
        </span>
        <span class="fname" :title="job.file_name || ''">{{ job.file_name || '未命名文件' }}</span>
        <span v-if="job.state === 'error'" class="err" :title="job.message || ''">
          {{ job.message || '处理失败' }}
        </span>
        <span v-else-if="job.state !== 'done'" class="pct-small">
          {{ Math.round(job.percent || 0) }}%
        </span>
        <button
          v-if="job.state === 'done' && job.material_id"
          class="ghost small"
          type="button"
          @click="emit('openMaterial', job.material_id)"
        >打开材料</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.batch {
  margin-top: 12px;
}

.pct {
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.jobs {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 320px;
  overflow-y: auto;
}

.jobrow {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper-2);
  font-size: 12.5px;
}

.fname {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pct-small {
  color: var(--ink-3);
  font-variant-numeric: tabular-nums;
}

.err {
  max-width: 46%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--accent);
}
</style>
