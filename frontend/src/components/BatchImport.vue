<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api'
import { showToast } from '../router'
import { t } from '../i18n'
import Icon from './Icon.vue'

const emit = defineEmits<{ created: [batchId: string] }>()

const ALLOWED_EXTS = new Set([
  '.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus', '.aac', '.webm',
])

const files = ref<File[]>([])
const name = ref('')
const submitting = ref(false)
const inputEl = ref<HTMLInputElement | null>(null)

const totalMb = computed(() =>
  files.value.reduce((sum, f) => sum + f.size, 0) / (1024 * 1024),
)

function extOf(file: File): string {
  const dot = file.name.lastIndexOf('.')
  return dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
}

function onFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const picked = Array.from(input.files ?? [])
  input.value = ''
  if (!picked.length) return

  const rejected: string[] = []
  const merged = [...files.value]
  for (const file of picked) {
    if (extOf(file) && !ALLOWED_EXTS.has(extOf(file))) {
      rejected.push(file.name)
      continue
    }
    const duplicate = merged.some(
      (f) =>
        f.name === file.name &&
        f.size === file.size &&
        f.lastModified === file.lastModified,
    )
    if (!duplicate) merged.push(file)
  }
  files.value = merged
  if (rejected.length) {
    showToast(t('batch.error.unsupported', { files: rejected.join(', ') }), 'error', 6000)
  }
}

function removeFile(index: number) {
  files.value = files.value.filter((_, i) => i !== index)
}

async function submit() {
  if (!files.value.length) {
    showToast(t('batch.error.noFiles'), 'error')
    return
  }
  submitting.value = true
  try {
    const res = await api.createMaterialsBatch({
      files: files.value,
      name: name.value.trim(),
    })
    showToast(t('batch.imported', { n: res.jobs.length }))
    files.value = []
    name.value = ''
    emit('created', res.batch_id)
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error', 8000)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="card">
    <div class="cardtitle">
      <h2>{{ t('batch.title') }}</h2>
      <span class="chip">{{ t('batch.badge') }}</span>
    </div>

    <div class="grid">
      <label class="field">
        <span class="tag">{{ t('batch.name') }}</span>
        <input v-model="name" type="text" :placeholder="t('batch.name.placeholder')" />
      </label>
      <label class="field">
        <span class="tag">{{ t('batch.choose') }}</span>
        <input
          ref="inputEl"
          type="file"
          accept="audio/*,.mp3,.m4a,.wav,.flac,.ogg,.opus,.aac,.webm"
          multiple
          @change="onFiles"
        />
      </label>
    </div>

    <div v-if="files.length" class="filelist">
      <div v-for="(file, index) in files" :key="`${file.name}-${file.lastModified}`" class="filerow">
        <Icon name="headphonesOff" :size="13" />
        <span class="fname">{{ file.name }}</span>
        <span class="fsize">{{ (file.size / (1024 * 1024)).toFixed(1) }} MB</span>
        <button
          class="icon-btn"
          type="button"
          :title="t('batch.remove')"
          :aria-label="t('batch.remove')"
          @click="removeFile(index)"
        >
          <Icon name="trash" :size="13" />
        </button>
      </div>
      <p class="hint">{{ t('batch.summary', { count: files.length, size: totalMb.toFixed(1) }) }}</p>
    </div>

    <p class="hint options">{{ t('batch.generateOff') }}</p>

    <div class="actions">
      <button class="big" type="button" :disabled="submitting || !files.length" @click="submit">
        <Icon name="upload" :size="14" />
        {{ submitting ? t('batch.submitting') : files.length ? t('batch.submitCount', { n: files.length }) : t('batch.submit') }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.filelist {
  margin-top: 14px;
  padding: 10px 12px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper-2);
}

.filerow {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
}

.fname {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fsize {
  color: var(--ink-3);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.icon-btn {
  padding: 4px;
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

.hint.options {
  margin-top: 14px;
}

.actions {
  margin-top: 16px;
}
</style>
