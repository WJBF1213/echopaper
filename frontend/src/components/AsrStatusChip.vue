<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type AsrStatus } from '../api'
import { showToast } from '../router'
import { t } from '../i18n'
import Icon from './Icon.vue'

const status = ref<AsrStatus | null>(null)
const busy = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const label = computed(() => {
  switch (status.value?.state) {
    case 'ready':
      return t('asr.ready')
    case 'loading':
      return t('asr.loading')
    case 'error':
      return t('asr.error')
    default:
      return t('asr.unloaded')
  }
})

const chipClass = computed(() => {
  switch (status.value?.state) {
    case 'ready':
      return 'ok'
    case 'error':
      return 'bad'
    default:
      return ''
  }
})

async function refresh() {
  try {
    status.value = await api.asrStatus()
  } catch {
    status.value = null
  }
}

async function load() {
  busy.value = true
  try {
    status.value = await api.asrLoad()
    showToast(t('asr.loaded'))
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    busy.value = false
  }
}

async function unload() {
  busy.value = true
  try {
    status.value = await api.asrUnload()
    showToast(t('asr.unloadedToast'))
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  void refresh()
  timer = setInterval(refresh, 15000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="asr">
    <div class="asr-row">
      <span class="chip" :class="chipClass">
        <Icon name="mic" :size="12" />
        {{ t('asr.model', { state: label }) }}
      </span>
      <span v-if="status" class="engine">{{ status.engine }} · {{ status.model.split('/').pop() }}</span>
    </div>
    <div class="asr-row">
      <button class="ghost small" type="button" :disabled="busy || status?.state === 'ready'" @click="load">
        {{ t('asr.preload') }}
      </button>
      <button
        class="ghost small"
        type="button"
        :disabled="busy || status?.state === 'unloaded'"
        @click="unload"
      >
        {{ t('asr.unload') }}
      </button>
      <span v-if="status" class="hint">{{ t('asr.idleHint', { n: status.idle_unload_min }) }}</span>
    </div>
  </div>
</template>

<style scoped>
.asr {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.asr-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.engine {
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
</style>
