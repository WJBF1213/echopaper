<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api, type AsrStatus, type Settings, type SettingsPatch } from '../api'
import { showToast } from '../router'
import Icon from '../components/Icon.vue'

const settings = ref<Settings | null>(null)
const asrStatus = ref<AsrStatus | null>(null)
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const apiKey = ref('')
const testMessage = ref('')

const form = reactive({
  provider: 'zhipu',
  baseUrl: '',
  model: '',
  maxContextTokens: 262144,
  engine: 'parakeet',
  parakeetModel: '',
  whisperModel: '',
  idleUnloadMin: 10,
  blankCount: 10,
})

const PRESETS: Record<string, { baseUrl: string; model: string; label: string }> = {
  zhipu: {
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4.7-flash',
    label: '智谱 GLM',
  },
  dashscope: {
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-flash',
    label: '阿里百炼',
  },
  deepseek: { baseUrl: 'https://api.deepseek.com/v1', model: 'deepseek-chat', label: 'DeepSeek' },
  custom: { baseUrl: '', model: '', label: '自定义（OpenAI 兼容）' },
}

function onProviderChange() {
  const preset = PRESETS[form.provider]
  if (preset) {
    form.baseUrl = preset.baseUrl
    form.model = preset.model
  }
}

async function load() {
  loading.value = true
  try {
    const [s, status] = await Promise.all([api.getSettings(), api.asrStatus()])
    settings.value = s
    asrStatus.value = status
    form.provider = s.llm.provider
    form.baseUrl = s.llm.base_url
    form.model = s.llm.model
    form.maxContextTokens = s.llm.max_context_tokens
    form.engine = s.asr.engine
    form.parakeetModel = s.asr.parakeet_model
    form.whisperModel = s.asr.whisper_model
    form.idleUnloadMin = s.asr.idle_unload_min
    form.blankCount = s.gen.blank_count
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const llmPatch: NonNullable<SettingsPatch['llm']> = {
      provider: form.provider,
      base_url: form.baseUrl,
      model: form.model,
      max_context_tokens: form.maxContextTokens,
    }
    if (apiKey.value.trim()) llmPatch.api_key = apiKey.value.trim()
    const updated = await api.updateSettings({
      llm: llmPatch,
      asr: {
        engine: form.engine,
        parakeet_model: form.parakeetModel,
        whisper_model: form.whisperModel,
        idle_unload_min: form.idleUnloadMin,
      },
      gen: { blank_count: form.blankCount },
    })
    settings.value = updated
    apiKey.value = ''
    asrStatus.value = await api.asrStatus()
    showToast('设置已保存')
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    saving.value = false
  }
}

async function testLlm() {
  testing.value = true
  testMessage.value = ''
  try {
    const res = await api.testLlm()
    testMessage.value = res.message
    showToast(res.ok ? '连接正常' : res.message, res.ok ? 'info' : 'error')
  } catch (err) {
    testMessage.value = err instanceof Error ? err.message : String(err)
    showToast(testMessage.value, 'error')
  } finally {
    testing.value = false
  }
}

async function engineAction(action: 'load' | 'unload') {
  try {
    asrStatus.value = action === 'load' ? await api.asrLoad() : await api.asrUnload()
    showToast(action === 'load' ? '识别模型已加载' : '识别模型已卸载')
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  }
}

onMounted(load)
</script>

<template>
  <div>
    <header class="page-head">
      <h1>设置</h1>
      <p class="sub">配置只保存在本机数据库。API 密钥只写不读。</p>
    </header>

    <div v-if="loading" class="card empty-tip">加载中…</div>
    <template v-else>
      <section class="card">
        <h2>出题模型</h2>
        <div class="grid">
          <label class="field">
            <span class="tag">服务商</span>
            <select v-model="form.provider" @change="onProviderChange">
              <option v-for="(preset, key) in PRESETS" :key="key" :value="key">
                {{ preset.label }}
              </option>
            </select>
          </label>
          <label class="field">
            <span class="tag">接口地址</span>
            <input v-model="form.baseUrl" type="text" placeholder="https://…" />
          </label>
          <label class="field">
            <span class="tag">模型</span>
            <input v-model="form.model" type="text" placeholder="glm-4.7-flash" />
          </label>
          <label class="field">
            <span class="tag">API 密钥</span>
            <input
              v-model="apiKey"
              type="password"
              :placeholder="settings?.llm.has_key ? `已保存 ${settings.llm.key_masked}` : '未配置'"
            />
          </label>
          <label class="field">
            <span class="tag">上下文上限（tokens）</span>
            <input
              v-model.number="form.maxContextTokens"
              type="number"
              min="4096"
              max="262144"
              step="1024"
            />
          </label>
        </div>
        <div class="row" style="margin-top: 14px">
          <button class="ghost small" type="button" :disabled="testing" @click="testLlm">
            <Icon name="spark" :size="13" />
            {{ testing ? '测试中…' : '测试连接' }}
          </button>
          <span class="hint">
            {{ testMessage || '未配置密钥时使用本地规则出题；长文本会按句分段处理。' }}
          </span>
        </div>
      </section>

      <section class="card">
        <h2>语音识别</h2>
        <div class="grid">
          <label class="field">
            <span class="tag">引擎</span>
            <select v-model="form.engine">
              <option value="parakeet">parakeet-mlx</option>
              <option value="whisper">mlx-whisper</option>
            </select>
          </label>
          <label class="field">
            <span class="tag">Parakeet 模型</span>
            <input v-model="form.parakeetModel" type="text" />
          </label>
          <label class="field">
            <span class="tag">Whisper 模型</span>
            <input v-model="form.whisperModel" type="text" />
          </label>
          <label class="field">
            <span class="tag">空闲卸载（分钟）</span>
            <input v-model.number="form.idleUnloadMin" type="number" min="0" max="240" />
          </label>
        </div>
        <div class="row" style="margin-top: 14px">
          <span
            v-if="asrStatus"
            class="chip"
            :class="{ ok: asrStatus.state === 'ready', bad: asrStatus.state === 'error' }"
          >
            {{ asrStatus.state }} · {{ asrStatus.engine }}
          </span>
          <button class="ghost small" type="button" @click="engineAction('load')">立即加载</button>
          <button class="ghost small" type="button" @click="engineAction('unload')">立即卸载</button>
          <span class="hint">切换引擎会立即释放当前模型。</span>
        </div>
      </section>

      <section class="card">
        <h2>默认值</h2>
        <label class="field" style="max-width: 180px">
          <span class="tag">每次出题数</span>
          <input v-model.number="form.blankCount" type="number" min="1" max="40" />
        </label>
      </section>

      <div class="row">
        <button class="big" type="button" :disabled="saving" @click="save">
          <Icon name="check" :size="14" />
          {{ saving ? '保存中…' : '保存设置' }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  margin-bottom: 20px;
}

.page-head h1 {
  margin-bottom: 6px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}
</style>
