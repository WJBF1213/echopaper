<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type BatchSummary, type MaterialListItem } from '../api'
import { showToast } from '../router'
import { useJobPolling } from '../composables/useJobPolling'
import { useBatchPolling } from '../composables/useBatchPolling'
import { fmtDateTime } from '../lib/time'
import MaterialForm from '../components/MaterialForm.vue'
import MaterialCard from '../components/MaterialCard.vue'
import JobProgress from '../components/JobProgress.vue'
import BatchImport from '../components/BatchImport.vue'
import BatchProgress from '../components/BatchProgress.vue'
import AsrStatusChip from '../components/AsrStatusChip.vue'
import Icon from '../components/Icon.vue'

const router = useRouter()
const materials = ref<MaterialListItem[]>([])
const batches = ref<BatchSummary[]>([])
const query = ref('')
const loading = ref(false)

const { job, start } = useJobPolling(async (finished) => {
  await load()
  if (finished.state === 'done' && finished.material_id) {
    showToast('出题完成')
    void router.push(`/material/${finished.material_id}`)
  } else if (finished.state === 'error') {
    showToast(finished.message || '处理失败', 'error', 8000)
  }
})

const { batch, start: startBatch } = useBatchPolling(async (finished, watched) => {
  await load()
  await loadBatches()
  if (!watched) return
  if (finished.error) {
    showToast(
      `批量导入结束：${finished.done} 个成功，${finished.error} 个失败`,
      'error',
      8000,
    )
  } else {
    showToast(`批量导入完成：${finished.done} 个材料已入库`)
  }
})

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return materials.value
  return materials.value.filter((m) => m.name.toLowerCase().includes(q))
})

async function load() {
  loading.value = true
  try {
    materials.value = await api.listMaterials()
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    loading.value = false
  }
}

async function loadBatches() {
  try {
    batches.value = await api.listBatches()
  } catch {
    // the batch history card is optional; leave it empty on failure
  }
}

function openMaterial(materialId: string) {
  void router.push(`/material/${materialId}`)
}

async function remove(material: MaterialListItem) {
  if (!window.confirm(`删除材料「${material.name}」？题目、成绩与错词记录将一并删除。`)) return
  try {
    await api.deleteMaterial(material.id)
    showToast('已删除')
    await load()
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  }
}

onMounted(() => {
  void load()
  void loadBatches()
})
</script>

<template>
  <div>
    <header class="page-head">
      <h1>听力填空练习</h1>
      <p class="sub">
        上传音频或粘贴原文，自动生成填空题。练习时按
        <kbd>空格</kbd> 播放，<kbd>←</kbd> <kbd>→</kbd> 前后 5 秒，<kbd>回车</kbd> 批改。
      </p>
    </header>

    <MaterialForm @created="start" />
    <JobProgress :job="job" />

    <BatchImport @created="startBatch" />
    <BatchProgress v-if="batch" :batch="batch" @open-material="openMaterial" />

    <section v-if="batches.length" class="card">
      <div class="cardtitle">
        <h2>批量导入记录</h2>
        <span class="hint">点击查看进度</span>
      </div>
      <div class="batchlist">
        <button
          v-for="b in batches"
          :key="b.id"
          class="batchrow"
          type="button"
          @click="startBatch(b.id)"
        >
          <span class="bname">{{ b.name }}</span>
          <span class="bmeta">{{ b.done }}/{{ b.total }} 完成</span>
          <span v-if="b.error" class="chip bad">{{ b.error }} 失败</span>
          <span v-else-if="b.running" class="chip">{{ b.running }} 进行中</span>
          <span v-else class="chip ok">已完成</span>
          <span class="btime">{{ fmtDateTime(b.created_at) }}</span>
        </button>
      </div>
    </section>

    <section class="card">
      <div class="cardtitle">
        <h2>材料</h2>
        <label class="search">
          <Icon name="search" :size="14" />
          <input v-model="query" type="search" placeholder="按名称搜索" aria-label="搜索材料" />
        </label>
      </div>

      <div v-if="loading" class="empty-tip">加载中…</div>
      <div v-else-if="!materials.length" class="empty-tip">
        还没有材料。上传音频或粘贴原文即可创建第一份练习。
      </div>
      <div v-else-if="!filtered.length" class="empty-tip">没有匹配「{{ query }}」的材料</div>
      <div v-else class="matlist">
        <MaterialCard
          v-for="m in filtered"
          :key="m.id"
          :material="m"
          @open="router.push(`/material/${m.id}`)"
          @remove="remove(m)"
        />
      </div>
    </section>

    <section class="card">
      <h2>本地识别</h2>
      <AsrStatusChip />
    </section>
  </div>
</template>

<style scoped>
.page-head {
  margin-bottom: 20px;
}

.page-head h1 {
  margin-bottom: 6px;
}

.matlist {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 520px;
  overflow-y: auto;
  padding-right: 4px;
}

.batchlist {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.batchrow {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 11px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper-2);
  color: var(--ink);
  font-size: 13px;
  text-align: left;
}

.batchrow:hover:not(:disabled) {
  border-color: var(--rule-strong);
  background: var(--paper);
  opacity: 1;
}

.bname {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bmeta {
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.btime {
  color: var(--ink-3);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.search {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  border: 1px solid var(--rule-strong);
  border-radius: 3px;
  background: var(--paper);
  color: var(--ink-3);
}

.search:focus-within {
  border-color: var(--focus);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--focus) 18%, transparent);
}

.search input {
  width: 190px;
  padding: 7px 0;
  border: none;
  background: transparent;
  font-size: 13px;
}

.search input:focus {
  outline: none;
  box-shadow: none;
}
</style>
