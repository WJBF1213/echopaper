<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  api,
  type ExamItem,
  type ExamTypeInfo,
  type MaterialListItem,
  type PaperSummary,
  type TypeStat,
  type WrongWord,
} from '../api'
import { showToast } from '../router'
import { fmtDateTime } from '../lib/time'
import { locale, t, tn } from '../i18n'
import Icon from '../components/Icon.vue'

const router = useRouter()

/** By-type accuracy across all papers (redesigned GET /api/stats). */
const typeStats = ref<TypeStat[]>([])
const wrongWords = ref<WrongWord[]>([])

/** One attempted paper + its items merged with per-item accuracy. */
interface PaperGroup {
  summary: PaperSummary
  items: {
    item: ExamItem
    attempts: number
    correct: number
  }[]
}
const paperGroups = ref<PaperGroup[]>([])

const types = ref<ExamTypeInfo[]>([])
const loading = ref(true)

function typeNameOf(key: string): string {
  const info = types.value.find((x) => x.key === key)
  if (!info) return key
  return locale.value === 'zh' ? info.name_zh : info.name_en
}

function pct(correct: number, attempts: number): number {
  return attempts > 0 ? Math.round((correct / attempts) * 100) : 0
}

async function load() {
  loading.value = true
  try {
    const [stats, wrong, typeInfo] = await Promise.all([
      api.globalStats(),
      api.getWrongWords(),
      api.examTypes().catch(() => ({ types: [] as ExamTypeInfo[] })),
    ])
    typeStats.value = stats
    wrongWords.value = wrong
    types.value = typeInfo.types

    // Papers the user has attempted: materials list -> papers -> stats.
    // A submission grades every item, so "attempted" means any item with
    // attempts > 0 (the fresh-paper 0/0 rows are skipped by design).
    const materials: MaterialListItem[] = await api.listMaterials()
    const papers = (
      await Promise.all(
        materials
          .filter((m) => m.attempts_count > 0)
          .map((m) => api.listPapers(m.id)),
      )
    ).flat()

    const groups: PaperGroup[] = []
    for (const summary of papers) {
      const stats = await api.paperStats(summary.id)
      const attempted = stats.filter((s) => s.attempts > 0)
      if (!attempted.length) continue
      const detail = await api.getPaper(summary.id)
      const byNumber = new Map(
        detail.paper.groups.flatMap((g) => g.items).map((i) => [i.number, i]),
      )
      groups.push({
        summary,
        items: attempted
          .map((s) => {
            const item = byNumber.get(s.item_number)
            return item
              ? { item, attempts: s.attempts, correct: s.correct }
              : null
          })
          .filter((x): x is PaperGroup['items'][number] => x !== null),
      })
    }
    paperGroups.value = groups
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    loading.value = false
  }
}

function openWrong(word: WrongWord) {
  // The stored paper has the player and the item's evidence; carrying
  // the word's t_start as ?t= makes PaperView seek the player straight
  // to the wrong answer's audio position (the same ?t= pattern
  // MaterialView uses).
  const start = word.t_start
  const query =
    start != null && Number.isFinite(start) && start > 0 ? `?t=${start}` : ''
  void router.push(`/paper/${word.material_id}/${word.paper_id}${query}`)
}

onMounted(load)
</script>

<template>
  <div>
    <header class="page-head">
      <h1>{{ t('review.title') }}</h1>
      <p class="sub">{{ t('review.subtitle') }}</p>
    </header>

    <div v-if="loading" class="card empty-tip">{{ t('common.loading') }}</div>
    <template v-else>
      <section class="card">
        <h2>{{ t('review.types.title') }}</h2>
        <div v-if="!typeStats.length" class="empty-tip">{{ t('review.types.empty') }}</div>
        <div v-else class="type-list">
          <div v-for="row in typeStats" :key="row.item_type" class="type-row">
            <span class="type-name">{{ typeNameOf(row.item_type) }}</span>
            <span class="type-count">{{ tn('review.types.count', row.attempts, { n: row.attempts }) }}</span>
            <span class="bar">
              <span :style="{ width: `${(row.accuracy * 100).toFixed(2)}%` }"></span>
            </span>
            <span class="type-pct">{{ pct(row.correct, row.attempts) }}%</span>
          </div>
        </div>
      </section>

      <section class="card">
        <h2>{{ t('review.papers.title') }}</h2>
        <div v-if="!paperGroups.length" class="empty-tip">{{ t('review.papers.empty') }}</div>
        <article
          v-for="g in paperGroups"
          :key="g.summary.id"
          class="paper-group"
        >
          <div class="group-head">
            <span v-for="b in g.summary.blocks" :key="b.type" class="chip">
              {{ typeNameOf(b.type) }} ×{{ b.count }}
            </span>
            <span v-if="g.summary.stale" class="chip warn">{{ t('paper.stale') }}</span>
            <span class="group-date">{{ fmtDateTime(g.summary.created_at) }}</span>
          </div>
          <div v-for="row in g.items" :key="row.item.number" class="stat-item">
            <div class="stem-line">
              <span class="num">{{ row.item.number }}.</span>
              <span class="stem">{{ row.item.stem }}</span>
              <span class="answer">{{ t('paper.answer', { answer: row.item.answer }) }}</span>
            </div>
            <div class="acc-line">
              <span class="bar">
                <span :class="{ zero: row.correct === 0 }"
                  :style="{ width: `${pct(row.correct, row.attempts)}%` }"></span>
              </span>
              <span class="acc-label">{{
                t('review.item.value', {
                  pct: pct(row.correct, row.attempts),
                  correct: row.correct,
                  attempts: row.attempts,
                })
              }}</span>
            </div>
          </div>
        </article>
      </section>

      <section class="card">
        <h2>{{ t('review.wrong.title') }}</h2>
        <div v-if="!wrongWords.length" class="empty-tip">{{ t('review.wrong.empty') }}</div>
        <div v-else class="scroll-area">
          <table class="data">
            <thead>
              <tr>
                <th>{{ t('review.wrong.word') }}</th>
                <th>{{ t('review.wrong.times') }}</th>
                <th>{{ t('review.wrong.last') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="word in wrongWords" :key="`${word.word}-${word.paper_id}`">
                <td class="word">{{ word.word }}</td>
                <td>{{ word.times_wrong }}</td>
                <td>{{ fmtDateTime(word.last_at) }}</td>
                <td class="action">
                  <button class="ghost small" type="button" @click="openWrong(word)">
                    <Icon name="headphones" :size="13" />
                    {{ t('review.wrong.relisten') }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
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

.type-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 560px;
}

.type-row {
  display: grid;
  grid-template-columns: 84px 64px 1fr 48px;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.type-name {
  font-weight: 500;
}

.type-count {
  color: var(--ink-3);
  font-size: 12px;
}

.type-pct {
  text-align: right;
  color: var(--ink-2);
}

.bar {
  display: block;
  height: 6px;
  border-radius: 3px;
  background: var(--rule);
  overflow: hidden;
}

.bar > span {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--ok);
}

.bar > span.zero {
  background: var(--accent);
}

.paper-group {
  padding: 12px 0 4px;
  border-bottom: 1px solid var(--rule);
}

.paper-group:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.group-date {
  color: var(--ink-3);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  margin-left: auto;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 0;
}

.stem-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.num {
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.stem {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--ink-2);
}

.answer {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--ink-3);
}

.acc-line {
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: 560px;
}

.acc-label {
  color: var(--ink-3);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.word {
  font-weight: 500;
}

.action {
  text-align: right;
}
</style>
