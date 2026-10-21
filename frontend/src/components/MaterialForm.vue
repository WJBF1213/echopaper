<script setup lang="ts">
import { reactive, ref } from 'vue'
import { api } from '../api'
import { showToast } from '../router'
import Icon from './Icon.vue'

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

const MODES = [
  {
    value: 'llm',
    label: '混合出题',
    hint: 'LLM 从转写中选空，代码逐字校验；未配置密钥时自动使用本地规则。',
  },
  {
    value: 'nouns',
    label: '本地规则',
    hint: '纯本地：词性、词频与短语结构选词，不需要网络。',
  },
  {
    value: 'manual',
    label: '手动标注',
    hint: '在原文中用 [方括号] 标出答案，例如 My postcode is [GU7 4BX]。',
  },
]

function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  file.value = input.files?.[0] ?? null
}

async function submit() {
  if (!form.audioUrl && !file.value && !form.transcript.trim()) {
    showToast('请提供音频文件、音频链接或原文之一', 'error')
    return
  }
  if (form.mode === 'manual' && !form.transcript.trim()) {
    showToast('手动标注模式需要粘贴带 [方括号] 的原文', 'error')
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
    showToast('已提交，正在处理')
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
    <h2>新建材料</h2>

    <div class="grid">
      <label class="field span-2">
        <span class="tag">名称</span>
        <input
          v-model="form.name"
          type="text"
          placeholder="例如：剑桥 18 Test 1 Section 1"
        />
      </label>
      <label class="field">
        <span class="tag">出题方式</span>
        <select v-model="form.mode">
          <option v-for="m in MODES" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
      </label>
      <label class="field">
        <span class="tag">题数</span>
        <input v-model.number="form.blankCount" type="number" min="5" max="40" />
      </label>
    </div>

    <label class="field" style="margin-top: 14px">
      <span class="tag">听力原文（可选）</span>
      <textarea
        v-model="form.transcript"
        :placeholder="form.mode === 'manual'
          ? '粘贴原文并用 [方括号] 标出答案，例如：My postcode is [GU7 4BX].'
          : '粘贴官方原文可提高转写准确度；只粘贴原文时使用浏览器语音朗读。'"
      />
    </label>

    <div class="grid" style="margin-top: 14px">
      <label class="field">
        <span class="tag">音频文件</span>
        <input type="file" accept="audio/*" @change="onFile" />
      </label>
      <label class="field">
        <span class="tag">或音频链接</span>
        <input v-model="form.audioUrl" type="text" placeholder="https://…/audio.mp3" />
      </label>
    </div>

    <p class="hint" style="margin-top: 12px">{{ MODES.find((m) => m.value === form.mode)?.hint }}</p>

    <div class="actions">
      <button class="big" type="button" :disabled="submitting" @click="submit">
        <Icon name="upload" :size="14" />
        {{ submitting ? '提交中…' : '创建并出题' }}
      </button>
      <button class="ghost small" type="button" @click="advanced = !advanced">
        {{ advanced ? '收起选项' : '更多选项' }}
      </button>
    </div>

    <dl v-if="advanced" class="advanced">
      <div>
        <dt>音频处理</dt>
        <dd>音频与原文同时提供时，以原文为准，识别结果只用于对齐时间戳。</dd>
      </div>
      <div>
        <dt>识别模型</dt>
        <dd>首次识别需要下载模型，进度显示在下方任务栏。</dd>
      </div>
      <div>
        <dt>题数</dt>
        <dd>建议每 60–80 词出一题；空距过小时系统会自动减少题数。</dd>
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
