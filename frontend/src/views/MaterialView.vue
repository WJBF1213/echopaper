<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type AttemptHistoryItem, type MaterialDetail } from '../api'
import { showToast } from '../router'
import { usePlayer } from '../composables/usePlayer'
import {
  fmtDateTime,
  fmtTime,
  hasWordTiming,
  modeLabel,
  pct,
  sentenceTimeRange,
  transcriptSourceLabel,
} from '../lib/time'
import Icon from '../components/Icon.vue'
import TranscriptView from '../components/TranscriptView.vue'

const route = useRoute()
const router = useRouter()
const materialId = computed(() => String(route.params.materialId || ''))

const material = ref<MaterialDetail | null>(null)
const attempts = ref<AttemptHistoryItem[]>([])
const loading = ref(true)
const generating = ref(false)
const blankCount = ref(10)
const manualText = ref('')
const editing = ref(false)
const transcriptDraft = ref('')
const savingTranscript = ref(false)

const audioEl = ref<HTMLAudioElement | null>(null)
const { playing, current: playTime, duration, seek, toggle, nudge } = usePlayer(audioEl)
const showStamps = ref(true)

const timed = computed(
  () => Boolean(material.value?.has_audio) &&
    hasWordTiming(material.value?.words ?? []),
)

function seekToWord(wordIndex: number) {
  if (!timed.value) return
  const word = material.value?.words[wordIndex]
  if (!word) return
  seek(word.s, true)
}

function seekToSentence(sentenceIndex: number) {
  const range = material.value?.sentences[sentenceIndex]
  if (!range || !material.value) return
  const words = material.value.words
  const times = sentenceTimeRange(words, { start: range[0], end: range[1] })
  if (times) seek(times.a, true)
}

const modes = [
  { value: 'llm', label: '混合出题' },
  { value: 'nouns', label: '本地规则' },
  { value: 'manual', label: '手动标注' },
]
const newMode = ref('llm')

async function load() {
  loading.value = true
  try {
    material.value = await api.getMaterial(materialId.value)
    attempts.value = await api.getAttempts(materialId.value)
    transcriptDraft.value = material.value.transcript
    const t = Number(route.query.t)
    if (Number.isFinite(t) && t > 0) {
      setTimeout(() => seek(t, true), 300)
    }
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    loading.value = false
  }
}

watch(
  () => route.query.t,
  (value) => {
    const t = Number(value)
    if (Number.isFinite(t) && t > 0) seek(t, true)
  },
)

async function createSet() {
  if (!material.value) return
  generating.value = true
  try {
    const { set_id } = await api.createSet(
      material.value.id,
      newMode.value,
      blankCount.value,
      newMode.value === 'manual' ? manualText.value || undefined : undefined,
    )
    const created = await api.getSet(set_id)
    if (created.blank_count < blankCount.value) {
      showToast(
        `只生成了 ${created.blank_count} 题：材料中可考的位置不足（空距、答案类型与拼写规则限制）`,
        'info',
        7000,
      )
    } else {
      showToast('题集已生成')
    }
    await load()
    void router.push(`/practice/${set_id}`)
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    generating.value = false
  }
}

async function removeSet(id: string) {
  if (!window.confirm('删除这套题？已保存的成绩会保留。')) return
  try {
    await api.deleteSet(id)
    await load()
    showToast('题集已删除')
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  }
}

async function saveTranscript() {
  if (!material.value) return
  savingTranscript.value = true
  try {
    const res = await api.updateTranscript(material.value.id, transcriptDraft.value)
    if (res.message) showToast(res.message, 'error', 8000)
    else showToast('转写已更新，旧题集已标记为过期')
    editing.value = false
    await load()
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    savingTranscript.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <header class="page-head">
      <div class="head-main">
        <button class="back" type="button" @click="router.push('/')">
          <Icon name="arrowLeft" :size="14" />
          材料库
        </button>
        <h1>{{ material?.name || '材料' }}</h1>
      </div>
      <div v-if="material" class="head-meta">
        <span>{{ transcriptSourceLabel(material.transcript_source) }}</span>
        <span class="dot" aria-hidden="true">·</span>
        <span>{{ material.words.length }} 词</span>
        <template v-if="material.duration_s">
          <span class="dot" aria-hidden="true">·</span>
          <span>{{ Math.round(material.duration_s / 60) }} 分钟</span>
        </template>
      </div>
    </header>

    <div v-if="loading" class="card empty-tip">加载中…</div>

    <template v-else-if="material">
      <section v-if="material.has_audio" class="card">
        <audio
          ref="audioEl"
          :src="api.audioUrl(material.id)"
          preload="metadata"
          style="display: none"
        ></audio>
        <div class="row between">
          <div class="row">
            <button class="big" type="button" @click="toggle">
              <Icon :name="playing ? 'pause' : 'play'" :size="14" />
              {{ playing ? '暂停' : '播放' }}
            </button>
            <button class="ghost small" type="button" @click="nudge(-5)">
              <Icon name="rewind" :size="13" />
              5s
            </button>
            <button class="ghost small" type="button" @click="nudge(5)">
              5s
              <Icon name="forward" :size="13" />
            </button>
          </div>
          <span class="timecode">{{ fmtTime(playTime) }} / {{ fmtTime(duration || material.duration_s || 0) }}</span>
        </div>
        <input
          class="seek"
          type="range"
          min="0"
          max="1000"
          step="1"
          :value="duration ? Math.round((playTime / duration) * 1000) : 0"
          aria-label="音频进度"
          @input="
            seek(((($event.target as HTMLInputElement).valueAsNumber || 0) / 1000) * (duration || 0))
          "
        />
      </section>

      <section class="card">
        <div class="cardtitle">
          <h2>题集</h2>
        </div>

        <div v-if="material.sets.length" class="sets">
          <article v-for="s in material.sets" :key="s.id" class="set-row">
            <div class="set-main">
              <div class="set-title">
                {{ modeLabel(s.mode) }}
                <span v-if="s.stale" class="chip warn">转写已更新</span>
              </div>
              <div class="set-meta">
                <span>{{ s.blank_count }} 题</span>
                <span class="dot" aria-hidden="true">·</span>
                <span>{{ fmtDateTime(s.created_at) }}</span>
              </div>
            </div>
            <div class="row">
              <button type="button" @click="router.push(`/practice/${s.id}`)">开始练习</button>
              <button
                class="icon-btn"
                type="button"
                title="删除题集"
                aria-label="删除题集"
                @click="removeSet(s.id)"
              >
                <Icon name="trash" :size="14" />
              </button>
            </div>
          </article>
        </div>
        <div v-else class="empty-tip">还没有题集</div>

        <div class="gen-form">
          <label class="field">
            <span class="tag">出题方式</span>
            <select v-model="newMode">
              <option v-for="m in modes" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
          </label>
          <label class="field">
            <span class="tag">题数</span>
            <input v-model.number="blankCount" type="number" min="1" max="40" />
          </label>
          <button class="big" type="button" :disabled="generating" @click="createSet">
            <Icon name="spark" :size="14" />
            {{ generating ? '生成中…' : '生成新题集' }}
          </button>
        </div>

        <textarea
          v-if="newMode === 'manual'"
          v-model="manualText"
          class="manual-input"
          placeholder="可选：粘贴带 [方括号] 的原文覆盖材料转写。"
        />
      </section>

      <section class="card">
        <div class="cardtitle">
          <h2>转写原文</h2>
          <div class="row">
            <button
              v-if="!editing && timed"
              class="ghost small"
              type="button"
              :class="{ on: showStamps }"
              :title="showStamps ? '隐藏每句时间戳' : '显示每句时间戳'"
              @click="showStamps = !showStamps"
            >
              <Icon name="clock" :size="13" />
              {{ showStamps ? '隐藏时间戳' : '显示时间戳' }}
            </button>
            <button v-if="!editing" class="ghost small" type="button" @click="editing = true; transcriptDraft = material.transcript">
              <Icon name="edit" :size="13" />
              编辑
            </button>
            <template v-else>
              <button class="ghost small" type="button" :disabled="savingTranscript" @click="editing = false">
                取消
              </button>
              <button class="small" type="button" :disabled="savingTranscript" @click="saveTranscript">
                {{ savingTranscript ? '保存中…' : '保存并重新对齐' }}
              </button>
            </template>
          </div>
        </div>
        <textarea v-if="editing" v-model="transcriptDraft" style="min-height: 220px" />
        <TranscriptView
          v-else
          :words="material.words"
          :sentences="material.sentences"
          :text="material.transcript"
          :current="playTime"
          :timed="timed"
          :show-stamps="showStamps"
          @seek-word="seekToWord"
          @seek-sentence="seekToSentence"
        />
        <p class="hint" style="margin-top: 10px">
          <template v-if="timed">
            每句前的时刻可点击，从该句开头播放；点击任意单词可从该词播放，播放中的词会高亮。
          </template>
          <template v-else>纯文本没有词级时间戳，无法按词定位播放。</template>
          音频与原文同时提供时，原文为准，识别结果只提供词级时间戳。修改转写会重新对齐，并把旧题集标记为过期。
        </p>
      </section>

      <section class="card">
        <h2>练习记录</h2>
        <div v-if="!attempts.length" class="empty-tip">还没有练习记录</div>
        <table v-else class="data">
          <thead>
            <tr>
              <th>时间</th>
              <th>模式</th>
              <th>成绩</th>
              <th>用时</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in attempts" :key="a.id">
              <td>{{ fmtDateTime(a.finished_at || a.started_at) }}</td>
              <td>{{ modeLabel(a.mode) }}</td>
              <td>{{ a.ok }}/{{ a.total }}（{{ pct(a.ok, a.total) }}%）</td>
              <td>{{ a.duration_s ? `${Math.round(a.duration_s)} 秒` : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--rule);
}

.head-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.head-main h1 {
  font-size: 18px;
}

.head-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.dot {
  color: var(--rule-strong);
}

.back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--ink-3);
  font-size: 12.5px;
}

.back:hover:not(:disabled) {
  border-color: var(--rule);
  background: var(--paper);
  color: var(--ink);
  opacity: 1;
}

.between {
  justify-content: space-between;
}

.timecode {
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.seek {
  width: 100%;
  margin-top: 12px;
  accent-color: var(--accent);
}

.sets {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 18px;
}

.set-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 14px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper-2);
}

.set-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 500;
}

.set-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 2px;
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.gen-form {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 14px;
  border-top: 1px solid var(--rule);
}

.manual-input {
  margin-top: 10px;
}

.icon-btn {
  padding: 7px;
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

.transcript {
  padding: 14px 16px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper-2);
  color: var(--ink-2);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 14.5px;
  line-height: 2;
  max-height: 320px;
  overflow-y: auto;
  white-space: pre-wrap;
}
</style>
