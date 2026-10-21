<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api'
import { showToast } from '../router'
import Icon from './Icon.vue'

const emit = defineEmits<{ created: [batchId: string] }>()

const ALLOWED_EXTS = new Set([
  '.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus', '.aac', '.webm',
])

const files = ref<File[]>([])
const name = ref('')
const generateSets = ref(false)
const mode = ref('nouns')
const blankCount = ref(10)
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
    showToast(`已跳过不支持的格式：${rejected.join('、')}`, 'error', 6000)
  }
}

function removeFile(index: number) {
  files.value = files.value.filter((_, i) => i !== index)
}

async function submit() {
  if (!files.value.length) {
    showToast('请先选择至少一个音频文件', 'error')
    return
  }
  submitting.value = true
  try {
    const res = await api.createMaterialsBatch({
      files: files.value,
      name: name.value.trim(),
      generateSets: generateSets.value,
      mode: mode.value,
      blankCount: blankCount.value,
    })
    showToast(`已导入 ${res.jobs.length} 个音频，开始转写`)
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
      <h2>批量转写</h2>
      <span class="chip">多文件</span>
    </div>

    <div class="grid">
      <label class="field">
        <span class="tag">批次名称（可选）</span>
        <input v-model="name" type="text" placeholder="例如：剑桥 18 全套" />
      </label>
      <label class="field">
        <span class="tag">选择音频</span>
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
          title="移除"
          aria-label="移除"
          @click="removeFile(index)"
        >
          <Icon name="trash" :size="13" />
        </button>
      </div>
      <p class="hint">{{ files.length }} 个文件 · {{ totalMb.toFixed(1) }} MB · 逐个转写，全部保存到材料库</p>
    </div>

    <div class="options">
      <label class="check">
        <input v-model="generateSets" type="checkbox" />
        转写后顺便出题
      </label>
      <template v-if="generateSets">
        <label class="field inline">
          <span class="tag">方式</span>
          <select v-model="mode">
            <option value="nouns">本地规则</option>
            <option value="llm">混合出题</option>
          </select>
        </label>
        <label class="field inline">
          <span class="tag">题数</span>
          <input v-model.number="blankCount" type="number" min="5" max="40" />
        </label>
      </template>
      <span v-else class="hint">默认只转写并入库，之后可在材料页随时出题。</span>
    </div>

    <div class="actions">
      <button class="big" type="button" :disabled="submitting || !files.length" @click="submit">
        <Icon name="upload" :size="14" />
        {{ submitting ? '上传中…' : `开始批量转写${files.length ? `（${files.length}）` : ''}` }}
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

.options {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 14px;
}

.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-2);
  font-size: 13px;
}

.field.inline {
  flex-direction: row;
  align-items: center;
  gap: 8px;
}

.field.inline input[type='number'] {
  width: 76px;
}

.actions {
  margin-top: 16px;
}
</style>
