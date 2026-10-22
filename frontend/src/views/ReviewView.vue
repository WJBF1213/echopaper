<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Stats, type WrongWord } from '../api'
import { showToast } from '../router'
import { fmtDateTime, pct } from '../lib/time'
import { t } from '../i18n'
import Icon from '../components/Icon.vue'

const router = useRouter()
const stats = ref<Stats | null>(null)
const wrongWords = ref<WrongWord[]>([])
const loading = ref(true)

const avgLabel = computed(() =>
  stats.value?.avg_score != null ? `${pct(stats.value.avg_score, 1)}%` : '—',
)

async function load() {
  loading.value = true
  try {
    const [s, w] = await Promise.all([api.getStats(), api.getWrongWords()])
    stats.value = s
    wrongWords.value = w
  } catch (err) {
    showToast(err instanceof Error ? err.message : String(err), 'error')
  } finally {
    loading.value = false
  }
}

function openWrong(word: WrongWord) {
  void router.push({
    path: `/material/${word.material_id}`,
    query: word.t_start != null ? { t: String(word.t_start) } : {},
  })
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
      <section class="summary">
        <div class="figure">
          <span class="figure-label">{{ t('review.stat.materials') }}</span>
          <strong>{{ stats?.materials ?? 0 }}</strong>
        </div>
        <div class="figure">
          <span class="figure-label">{{ t('review.stat.attempts') }}</span>
          <strong>{{ stats?.attempts ?? 0 }}</strong>
        </div>
        <div class="figure">
          <span class="figure-label">{{ t('review.stat.average') }}</span>
          <strong>{{ avgLabel }}</strong>
        </div>
        <div class="figure">
          <span class="figure-label">{{ t('review.stat.wrong') }}</span>
          <strong>{{ wrongWords.length }}</strong>
        </div>
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
              <tr v-for="word in wrongWords" :key="`${word.word}-${word.material_id}`">
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

.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper);
  margin-bottom: 16px;
  overflow: hidden;
}

.figure {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 18px 20px;
  border-right: 1px solid var(--rule);
}

.figure:last-child {
  border-right: none;
}

.figure-label {
  color: var(--ink-3);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.figure strong {
  color: var(--ink);
  font-size: 26px;
  font-weight: 600;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.word {
  font-weight: 500;
}

.action {
  text-align: right;
}
</style>
