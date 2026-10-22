<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import { showToast } from '../router'
import { t } from '../i18n'
import Icon from './Icon.vue'

const modes = computed(() => [
  { value: 'llm', label: t('mode.llm'), hint: t('form.mode.llm.hint') },
  { value: 'nouns', label: t('mode.nouns'), hint: t('form.mode.nouns.hint') },
  { value: 'manual', label: t('mode.manual'), hint: t('form.mode.manual.hint') },
])

const emit = defineEmits<{ created: [jobId: string] }>()

const form = reactive({
  name: '',
  mode: 'llm',
  blankCount: 10,
  transcript: '',
  audioUrl: '',
})
const file = ref<File | null>(null)
const submitting = ref(false)
const advanced = ref(false)

function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
}

async function submit() {
  if (!form.audioUrl && !file.value && !form.transcript.trim()) {
    showToast(t('form.error.needInput'), 'error')
    return
  }
  if (form.mode === 'manual' && !form.transcript.trim()) {
    showToast(t('form.error.manualNeedsText'), 'error')
    return
  }
  submitting.value = true
  try {
    const { job_id } = await api.createMaterial({
      name: form.name.trim(),
      audioFile: file.value,
      audioUrl: form.audioUrl.trim(),
      transcript: form.transcript.trim(),
      mode: form.mode,
      blankCount: form.blankCount,
    })
    showToast(t('form.submitted'))
    form.name = ''
    form.transcript = ''
    form.audioUrl = ''
    file.value = null
    emit('created', job_id)
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="card">
    <h2>{{ t('form.title') }}</h2>

    <div class="grid">
      <label class="field span-2">
        <span class="tag">{{ t('form.name') }}</span>
        <input
          v-model="form.name"
          type="text"
          :placeholder="t('form.name.placeholder')"
        />
      </label>
      <label class="field">
        <span class="tag">{{ t('form.mode') }}</span>
        <select v-model="form.mode">
          <option v-for="m in modes" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
      </label>
      <label class="field">
        <span class="tag">{{ t('form.blankCount') }}</span>
        <input v-model.number="form.blankCount" type="number" min="5" max="40" />
      </label>
    </div>

    <label class="field" style="margin-top: 14px">
      <span class="tag">{{ t('form.transcript') }}</span>
      <textarea
        v-model="form.transcript"
        :placeholder="form.mode === 'manual'
          ? t('form.transcript.placeholderManual')
          : t('form.transcript.placeholderAsr')"
      />
    </label>

    <div class="grid" style="margin-top: 14px">
      <label class="field">
        <span class="tag">{{ t('form.audioFile') }}</span>
        <input type="file" accept="audio/*" @change="onFile" />
      </label>
      <label class="field">
        <span class="tag">{{ t('form.audioUrl') }}</span>
        <input v-model="form.audioUrl" type="text" :placeholder="t('form.audioUrl.placeholder')" />
      </label>
    </div>

    <p class="hint" style="margin-top: 12px">{{ modes.find((m) => m.value === form.mode)?.hint }}</p>

    <div class="actions">
      <button class="big" type="button" :disabled="submitting" @click="submit">
        <Icon name="upload" :size="14" />
        {{ submitting ? t('form.submitting') : t('form.submit') }}
      </button>
      <button class="ghost small" type="button" @click="advanced = !advanced">
        {{ advanced ? t('form.less') : t('form.more') }}
      </button>
    </div>

    <dl v-if="advanced" class="advanced">
      <div>
        <dt>{{ t('form.advanced.audio') }}</dt>
        <dd>{{ t('form.advanced.audioText') }}</dd>
      </div>
      <div>
        <dt>{{ t('form.advanced.model') }}</dt>
        <dd>{{ t('form.advanced.modelText') }}</dd>
      </div>
      <div>
        <dt>{{ t('form.advanced.count') }}</dt>
        <dd>{{ t('form.advanced.countText') }}</dd>
      </div>
    </dl>
  </section>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.span-2 {
  grid-column: span 2;
}
@media (max-width: 560px) {
  .span-2 {
    grid-column: auto;
  }
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
}
.advanced {
  margin: 16px 0 0;
  padding-top: 14px;
  border-top: 1px solid var(--rule);
  display: grid;
  gap: 8px;
  font-size: 12.5px;
}
.advanced div {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 10px;
}
.advanced dt {
  color: var(--ink-3);
}
.advanced dd {
  color: var(--ink-2);
}
</style>
