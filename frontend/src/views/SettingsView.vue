<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api, type AsrStatus, type Settings, type SettingsPatch } from '../api'
import { showToast } from '../router'
import { t } from '../i18n'
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
  fasterWhisperModel: '',
  idleUnloadMin: 10,
  blankCount: 10,
  availableEngines: ['faster_whisper'] as string[],
})

function engineLabel(name: string): string {
  switch (name) {
    case 'parakeet':
      return t('settings.engine.parakeet')
    case 'whisper':
      return t('settings.engine.whisper')
    case 'faster_whisper':
      return t('settings.engine.fasterWhisper')
    default:
      return name
  }
}

const PRESETS: Record<string, { baseUrl: string; model: string; labelKey: string }> = {
  zhipu: {
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4.7-flash',
    labelKey: 'settings.provider.zhipu',
  },
  dashscope: {
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-flash',
    labelKey: 'settings.provider.dashscope',
  },
  deepseek: {
    baseUrl: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    labelKey: 'settings.provider.deepseek',
  },
  custom: { baseUrl: '', model: '', labelKey: 'settings.provider.custom' },
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
    form.fasterWhisperModel = s.asr.faster_whisper_model
    form.idleUnloadMin = s.asr.idle_unload_min
    form.blankCount = s.gen.blank_count
    form.availableEngines = s.asr.available_engines ?? ['faster_whisper']
    if (!form.availableEngines.includes(form.engine)) {
      form.engine = s.asr.default_engine ?? form.availableEngines[0]
    }
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    loading.value = false
  }
}

function llmPatch(): NonNullable<SettingsPatch['llm']> {
  const patch: NonNullable<SettingsPatch['llm']> = {
    provider: form.provider,
    base_url: form.baseUrl,
    model: form.model,
    max_context_tokens: form.maxContextTokens,
  }
  const key = apiKey.value.trim()
  if (key) patch.api_key = key
  return patch
}

async function save() {
  saving.value = true
  try {
    const updated = await api.updateSettings({
      llm: llmPatch(),
      asr: {
        engine: form.engine,
        parakeet_model: form.parakeetModel,
        whisper_model: form.whisperModel,
        faster_whisper_model: form.fasterWhisperModel,
        idle_unload_min: form.idleUnloadMin,
      },
      gen: { blank_count: form.blankCount },
    })
    settings.value = updated
    apiKey.value = ''
    asrStatus.value = await api.asrStatus()
    showToast(t('settings.llm.savedToast'))
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    saving.value = false
  }
}

async function testLlm() {
  testing.value = true
  testMessage.value = ''
  const patch = llmPatch()
  try {
    // Persist first: a key sitting in the input is not configured for the
    // backend yet, and later question generation reads the stored copy.
    const updated = await api.updateSettings({ llm: patch })
    settings.value = updated
    apiKey.value = ''
    const res = await api.testLlm(patch)
    testMessage.value = res.message
    showToast(res.ok ? t('settings.llm.testOkToast') : res.message, res.ok ? 'info' : 'error')
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
    showToast(action === 'load' ? t('settings.asr.loadedToast') : t('settings.asr.unloadedToast'))
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  }
}

onMounted(load)
</script>

<template>
  <div>
    <header class="page-head">
      <h1>{{ t('settings.title') }}</h1>
      <p class="sub">{{ t('settings.subtitle') }}</p>
    </header>

    <div v-if="loading" class="card empty-tip">{{ t('common.loading') }}</div>
    <template v-else>
      <section class="card">
        <h2>{{ t('settings.llm.title') }}</h2>
        <div class="grid">
          <label class="field">
            <span class="tag">{{ t('settings.llm.provider') }}</span>
            <select v-model="form.provider" @change="onProviderChange">
              <option v-for="(preset, key) in PRESETS" :key="key" :value="key">
                {{ t(preset.labelKey) }}
              </option>
            </select>
          </label>
          <label class="field">
            <span class="tag">{{ t('settings.llm.baseUrl') }}</span>
            <input v-model="form.baseUrl" type="text" placeholder="https://…" />
          </label>
          <label class="field">
            <span class="tag">{{ t('settings.llm.model') }}</span>
            <input v-model="form.model" type="text" placeholder="glm-4.7-flash" />
          </label>
          <label class="field">
            <span class="tag">{{ t('settings.llm.apiKey') }}</span>
            <input
              v-model="apiKey"
              type="password"
              :placeholder="settings?.llm.has_key
              ? t('settings.llm.apiKey.saved', { masked: settings.llm.key_masked ?? '' })
              : t('settings.llm.apiKey.empty')"
            />
          </label>
          <label class="field">
            <span class="tag">{{ t('settings.llm.context') }}</span>
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
            {{ testing ? t('settings.llm.testing') : t('settings.llm.test') }}
          </button>
          <span class="hint">
            {{ testMessage || t('settings.llm.hint') }}
          </span>
        </div>
      </section>

      <section class="card">
        <h2>{{ t('settings.asr.title') }}</h2>
        <div class="grid">
          <label class="field">
            <span class="tag">{{ t('settings.asr.engine') }}</span>
            <select v-model="form.engine">
              <option v-for="name in form.availableEngines" :key="name" :value="name">
                {{ engineLabel(name) }}
              </option>
            </select>
          </label>
          <label class="field">
            <span class="tag">{{ t('settings.asr.parakeetModel') }}</span>
            <input v-model="form.parakeetModel" type="text" />
          </label>
          <label class="field">
            <span class="tag">{{ t('settings.asr.whisperModel') }}</span>
            <input v-model="form.whisperModel" type="text" />
          </label>
          <label class="field">
            <span class="tag">{{ t('settings.asr.fasterWhisperModel') }}</span>
            <input v-model="form.fasterWhisperModel" type="text" />
          </label>
          <label class="field">
            <span class="tag">{{ t('settings.asr.idle') }}</span>
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
          <button class="ghost small" type="button" @click="engineAction('load')">{{ t('settings.asr.load') }}</button>
          <button class="ghost small" type="button" @click="engineAction('unload')">{{ t('settings.asr.unload') }}</button>
          <span class="hint">{{ t('settings.asr.hint') }}</span>
        </div>
      </section>

      <section class="card">
        <h2>{{ t('settings.defaults.title') }}</h2>
        <label class="field" style="max-width: 180px">
          <span class="tag">{{ t('settings.defaults.blankCount') }}</span>
          <input v-model.number="form.blankCount" type="number" min="1" max="40" />
        </label>
      </section>

      <div class="row">
        <button class="big" type="button" :disabled="saving" @click="save">
          <Icon name="check" :size="14" />
          {{ saving ? t('settings.saving') : t('settings.save') }}
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
