<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type AsrStatus } from '../api'
import { showToast } from '../router'
import Icon from './Icon.vue'

const status = ref<AsrStatus | null>(null)
const busy = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const label = computed(() => {
  switch (status.value?.state) {
    case 'ready':
      return '已加载'
    case 'loading':
      return '加载中'
    case 'error':
      return '异常'
    default:
      return '未加载'
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
    showToast('识别模型已加载')
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
    showToast('识别模型已卸载')
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
        识别模型 {{ label }}
      </span>
      <span v-if="status" class="engine">{{ status.engine }} · {{ status.model.split('/').pop() }}</span>
    </div>
    <div class="asr-row">
      <button class="ghost small" type="button" :disabled="busy || status?.state === 'ready'" @click="load">
        预加载
      </button>
      <button
        class="ghost small"
        type="button"
        :disabled="busy || status?.state === 'unloaded'"
        @click="unload"
      >
        立即卸载
      </button>
      <span v-if="status" class="hint">空闲 {{ status.idle_unload_min }} 分钟后自动释放</span>
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
