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

/** Red is reserved for "this run went wrong", not for "we got to 100%". */
const tone = computed(() => {
  const { done, error, running } = props.batch
  if (running) return ''
  if (error && !done) return 'bad'
  if (error) return 'warn'
  return 'ok'
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

/** The first clause is usually the actual cause; the rest is remediation. */
function shortError(message: string | null): string {
  const text = message || '处理失败'
  const cut = text.split('；')[0] ?? text
  return cut.length > 56 ? `${cut.slice(0, 55)}…` : cut
}
</script>

<template>
  <section class="card batch" role="status" aria-live="polite">
    <div class="cardtitle">
      <h2>批量导入 · {{ batch.name }}</h2>
      <span class="hint">{{ summary }}</span>
    </div>
    <div class="progress" :class="tone">
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
          <details>
            <summary>{{ shortError(job.message) }}</summary>
            <p>{{ job.message || '处理失败' }}</p>
          </details>
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

.progress.ok > div {
  background: var(--ok);
}

.progress.warn > div {
  background: var(--warn);
}

.progress.bad > div {
  background: var(--accent);
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
  max-width: 52%;
  color: var(--accent);
}

.err details {
  cursor: pointer;
}

.err summary {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  list-style: none;
}

.err summary::-webkit-details-marker {
  display: none;
}

.err summary::marker {
  content: '';
}

.err summary::after {
  content: ' ▾';
  color: var(--ink-3);
}

.err p {
  margin-top: 6px;
  padding: 8px 10px;
  border-left: 2px solid var(--accent);
  background: var(--paper);
  color: var(--ink-2);
  font-size: 12px;
  line-height: 1.7;
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
