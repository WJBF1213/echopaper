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
  mode: 'local' as 'local' | 'cloud',
  idleUnloadMin: 10,
  cloudPreset: 'custom',
  cloudBaseUrl: '',
  cloudModel: '',
})
/** Cloud API key input — write-only, cleared once stored (like apiKey). */
const cloudApiKey = ref('')
const cloudTesting = ref(false)
const cloudTestMessage = ref('')

/** Human label for the platform's fixed local engine (GET asr.engine). */
function engineLabel(name: string): string {
  switch (name) {
    case 'parakeet':
      return t('settings.engine.parakeet')
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

/** Cloud ASR presets (Task 4): frontend-only, like the LLM PRESETS. */
const ASR_PRESETS: Record<string, { baseUrl: string; model: string; labelKey: string }> = {
  groq: {
    baseUrl: 'https://api.groq.com/openai/v1',
    model: 'whisper-large-v3-turbo',
    labelKey: 'settings.asr.preset.groq',
  },
  openai: {
    baseUrl: 'https://api.openai.com/v1',
    model: 'whisper-1',
    labelKey: 'settings.asr.preset.openai',
  },
  custom: { baseUrl: '', model: '', labelKey: 'settings.asr.preset.custom' },
}

/** Pick the select entry matching a stored base URL (custom otherwise). */
function detectAsrPreset(baseUrl: string): string {
  const url = baseUrl.trim()
  for (const [key, preset] of Object.entries(ASR_PRESETS)) {
    if (key !== 'custom' && preset.baseUrl === url) return key
  }
  return 'custom'
}

function onAsrPresetChange() {
  const preset = ASR_PRESETS[form.cloudPreset]
  if (preset && form.cloudPreset !== 'custom') {
    form.cloudBaseUrl = preset.baseUrl
    form.cloudModel = preset.model
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
    form.mode = s.asr.mode === 'cloud' ? 'cloud' : 'local'
    form.idleUnloadMin = s.asr.idle_unload_min
    form.cloudBaseUrl = s.asr.cloud_base_url
    form.cloudModel = s.asr.cloud_model
    form.cloudPreset = detectAsrPreset(s.asr.cloud_base_url)
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
        mode: form.mode,
        idle_unload_min: form.idleUnloadMin,
        cloud_base_url: form.cloudBaseUrl,
        cloud_model: form.cloudModel,
        // Empty string = keep the stored key (backend contract, Task 3).
        cloud_api_key: cloudApiKey.value.trim(),
      },
    })
    settings.value = updated
    apiKey.value = ''
    cloudApiKey.value = ''
    asrStatus.value = await api.asrStatus()
    showToast(t('settings.llm.savedToast'))
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    saving.value = false
  }
}

/** Probe the cloud engine with the unsaved form values; the endpoint
 * accepts overrides, so a blank key field means "use the stored key". */
async function testCloudAsr() {
  cloudTesting.value = true
  cloudTestMessage.value = ''
  try {
    const res = await api.testCloudAsr({
      cloud_base_url: form.cloudBaseUrl,
      cloud_model: form.cloudModel,
      cloud_api_key: cloudApiKey.value.trim(),
    })
    // The message is localized server-side; show it verbatim either way.
    cloudTestMessage.value = res.message
    showToast(res.message, res.ok ? 'info' : 'error')
  } catch (err) {
    cloudTestMessage.value = err instanceof Error ? err.message : String(err)
    showToast(cloudTestMessage.value, 'error')
  } finally {
    cloudTesting.value = false
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
          <div class="field mode-field" role="radiogroup" :aria-label="t('settings.asr.mode')">
            <span class="tag">{{ t('settings.asr.mode') }}</span>
            <div class="mode-options">
              <label class="radio">
                <input v-model="form.mode" type="radio" value="local" />
                {{ t('settings.asr.mode.local') }}
              </label>
              <label class="radio">
                <input v-model="form.mode" type="radio" value="cloud" />
                {{ t('settings.asr.mode.cloud') }}
              </label>
            </div>
          </div>
          <template v-if="form.mode === 'local'">
            <div class="field mode-field">
              <span class="tag">{{ t('settings.asr.engine') }}</span>
              <span class="static-value">{{ engineLabel(settings?.asr.engine ?? '') }}</span>
            </div>
            <label class="field">
              <span class="tag">{{ t('settings.asr.idle') }}</span>
              <input v-model.number="form.idleUnloadMin" type="number" min="0" max="240" />
            </label>
          </template>
          <template v-else>
            <label class="field">
              <span class="tag">{{ t('settings.asr.preset') }}</span>
              <select v-model="form.cloudPreset" @change="onAsrPresetChange">
                <option v-for="(preset, key) in ASR_PRESETS" :key="key" :value="key">
                  {{ t(preset.labelKey) }}
                </option>
              </select>
            </label>
            <label class="field">
              <span class="tag">{{ t('settings.asr.baseUrl') }}</span>
              <input v-model="form.cloudBaseUrl" type="text" placeholder="https://…" />
            </label>
            <label class="field">
              <span class="tag">{{ t('settings.asr.model') }}</span>
              <input v-model="form.cloudModel" type="text" placeholder="whisper-large-v3-turbo" />
            </label>
            <label class="field">
              <span class="tag">{{ t('settings.asr.apiKey') }}</span>
              <input
                v-model="cloudApiKey"
                type="password"
                :placeholder="settings?.asr.has_cloud_key
                ? t('settings.asr.apiKey.saved', { masked: settings.asr.cloud_key_masked ?? '' })
                : t('settings.asr.apiKey.empty')"
              />
            </label>
          </template>
        </div>
        <p v-if="form.mode === 'cloud'" class="hint privacy-note">
          {{ t('settings.asr.privacyNote') }}
        </p>
        <p v-else class="hint">{{ t('settings.asr.localEngineHint') }}</p>
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
          <button
            v-if="form.mode === 'cloud'"
            class="ghost small"
            type="button"
            :disabled="cloudTesting"
            @click="testCloudAsr"
          >
            <Icon name="spark" :size="13" />
            {{ cloudTesting ? t('settings.asr.testing') : t('settings.asr.test') }}
          </button>
          <span v-if="form.mode === 'cloud' && cloudTestMessage" class="hint">
            {{ cloudTestMessage }}
          </span>
          <span v-else class="hint">{{ t('settings.asr.hint') }}</span>
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

/* label.field is the global pattern; the radio group and the read-only
 * engine display are divs, so mirror that layout here. */
.mode-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: var(--ink-3);
}

.mode-options {
  display: flex;
  align-items: center;
  gap: 18px;
  min-height: 34px;
  flex-wrap: wrap;
}

.mode-options .radio {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: var(--ink);
  font-size: 13px;
}

.mode-options .radio input[type='radio'] {
  accent-color: var(--accent);
}

.static-value {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  color: var(--ink-2);
  font-size: 13px;
}

.privacy-note {
  margin-top: 10px;
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
