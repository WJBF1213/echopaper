<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  api,
  type AsrStatus,
  type PromptEntry,
  type Settings,
  type SettingsPatch,
} from '../api'
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
/** App version from GET /api/health; empty until it answers. */
const appVersion = ref('')

// --- prompts (Task 8) -----------------------------------------------------
const promptEntries = ref<PromptEntry[]>([])
/** Per-entry editable text; initialized from ``current`` on load. */
const promptDrafts = reactive<Record<string, string>>({})
/** Key of the prompt with a PUT in flight (disables its buttons). */
const savingPrompt = ref<string | null>(null)
const clearingCache = ref(false)

const promptGroups = computed(() => {
  const groups: { category: string; entries: PromptEntry[] }[] = []
  for (const p of promptEntries.value) {
    let g = groups.find((x) => x.category === p.category)
    if (!g) {
      g = { category: p.category, entries: [] }
      groups.push(g)
    }
    g.entries.push(p)
  }
  return groups
})

function variablePrint(entry: PromptEntry): string {
  return entry.variables.map((v) => `{{${v}}}`).join(' ')
}

function applyPromptUpdate(updated: PromptEntry) {
  const i = promptEntries.value.findIndex((p) => p.key === updated.key)
  if (i >= 0) promptEntries.value[i] = updated
  promptDrafts[updated.key] = updated.current
}

async function savePrompt(entry: PromptEntry) {
  savingPrompt.value = entry.key
  try {
    const updated = await api.putPrompt(entry.key, promptDrafts[entry.key] ?? '')
    applyPromptUpdate(updated)
    showToast(t('settings.prompts.savedToast'))
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    savingPrompt.value = null
  }
}

async function resetPrompt(entry: PromptEntry) {
  savingPrompt.value = entry.key
  try {
    // The PUT contract: empty text = restore the registry default.
    const updated = await api.putPrompt(entry.key, '')
    applyPromptUpdate(updated)
    showToast(t('settings.prompts.resetToast'))
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    savingPrompt.value = null
  }
}

async function clearCache() {
  clearingCache.value = true
  try {
    const { deleted } = await api.clearLlmCache()
    showToast(t('settings.llm.cacheCleared', { n: deleted }))
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    clearingCache.value = false
  }
}

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
  // The footer version is decorative: never let a health hiccup break the page.
  void api.health().then(
    (h) => {
      appVersion.value = h.version
    },
    () => {},
  )
  try {
    const [s, status, prompts] = await Promise.all([
      api.getSettings(),
      api.asrStatus(),
      api.listPrompts(),
    ])
    settings.value = s
    asrStatus.value = status
    promptEntries.value = prompts
    for (const p of prompts) promptDrafts[p.key] = p.current
    form.provider = s.llm.provider
    form.baseUrl = s.llm.base_url
    form.model = s.llm.model
    form.maxContextTokens = s.llm.max_context_tokens
    form.engine = s.asr.engine
    form.parakeetModel = s.asr.parakeet_model
    form.whisperModel = s.asr.whisper_model
    form.fasterWhisperModel = s.asr.faster_whisper_model
    form.idleUnloadMin = s.asr.idle_unload_min
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
          <button
            class="ghost small"
            type="button"
            :disabled="clearingCache"
            @click="clearCache"
          >
            <Icon name="trash" :size="13" />
            {{ clearingCache ? t('settings.llm.cacheClearing') : t('settings.llm.clearCache') }}
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
        <h2>{{ t('settings.prompts.title') }}</h2>
        <p class="hint">{{ t('settings.prompts.hint') }}</p>
        <details v-for="g in promptGroups" :key="g.category" class="prompt-group">
          <summary>
            <span>{{ t('settings.prompts.category.' + g.category) }}</span>
            <span class="chip">{{ g.entries.length }}</span>
          </summary>
          <div v-for="p in g.entries" :key="p.key" class="prompt-entry">
            <div class="row head">
              <strong>{{ p.title }}</strong>
              <span v-if="p.customized" class="chip warn">
                {{ t('settings.prompts.customized') }}
              </span>
            </div>
            <p v-if="p.variables.length" class="hint vars">
              {{ t('settings.prompts.variables', { vars: variablePrint(p) }) }}
            </p>
            <textarea
              v-model="promptDrafts[p.key]"
              rows="5"
              :disabled="savingPrompt === p.key"
            />
            <div class="row actions">
              <button
                class="small"
                type="button"
                :disabled="savingPrompt === p.key"
                @click="savePrompt(p)"
              >
                <Icon name="check" :size="12" />
                {{ t('common.save') }}
              </button>
              <button
                class="ghost small"
                type="button"
                :disabled="savingPrompt === p.key"
                @click="resetPrompt(p)"
              >
                <Icon name="refresh" :size="12" />
                {{ t('settings.prompts.reset') }}
              </button>
            </div>
          </div>
        </details>
      </section>

      <div class="row">
        <button class="big" type="button" :disabled="saving" @click="save">
          <Icon name="check" :size="14" />
          {{ saving ? t('settings.saving') : t('settings.save') }}
        </button>
      </div>

      <footer v-if="appVersion" class="version-footer">
        {{ t('settings.version', { version: appVersion }) }}
      </footer>
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

.prompt-group {
  border: 1px solid var(--rule);
  border-radius: 3px;
  margin-top: 10px;
}

.prompt-group summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  color: var(--ink-2);
  font-size: 13px;
  user-select: none;
}

.prompt-group summary:hover {
  color: var(--ink);
}

.prompt-entry {
  padding: 10px 12px 12px;
  border-top: 1px solid var(--rule);
}

.prompt-entry .head strong {
  font-size: 13px;
}

.prompt-entry .vars {
  margin: 4px 0 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.prompt-entry textarea {
  min-height: 90px;
  font-size: 12.5px;
}

.prompt-entry .actions {
  margin-top: 8px;
}

.version-footer {
  margin-top: 26px;
  color: var(--ink-3);
  font-size: 12px;
  user-select: none;
}
</style>
