import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReviewView from './ReviewView.vue'
import { api } from '../api'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      globalStats: vi.fn(),
      getWrongWords: vi.fn(),
      examTypes: vi.fn(),
      listMaterials: vi.fn(),
      listPapers: vi.fn(),
      paperStats: vi.fn(),
      getPaper: vi.fn(),
    },
  }
})

const mocked = vi.mocked(api)

const examTypes = {
  types: [
    { key: 'completion', name: '填空', name_zh: '填空', name_en: 'Completion',
      answer_kind: 'span', layouts: [], generates_visual: false,
      max_count: 10, min_words: 2 },
  ],
}

const paper = (id: string, itemCount: number) => ({
  id,
  blocks: [{ type: 'completion', count: itemCount }],
  item_count: itemCount,
  stale: false,
  created_at: '2026-10-21T10:00:00Z',
})

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/review', component: ReviewView },
      { path: '/paper/:materialId', component: { template: '<div />' } },
      { path: '/paper/:materialId/:paperId', component: { template: '<div />' } },
    ],
  })
  await router.push('/review')
  await router.isReady()
  const wrapper = mount(ReviewView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('ReviewView', () => {
  beforeEach(() => {
    mocked.globalStats.mockResolvedValue([
      { item_type: 'completion', attempts: 6, correct: 4, accuracy: 0.6667 },
    ])
    mocked.getWrongWords.mockResolvedValue([
      { word: 'postcode', times_wrong: 3, last_at: '2026-10-21T10:00:00Z',
        material_id: 'm1', paper_id: 'p1', item_number: 2, t_start: 42.5 },
    ])
    mocked.examTypes.mockResolvedValue(examTypes)
    mocked.listMaterials.mockResolvedValue([
      { id: 'm1', name: '剑桥 18 Test 1', duration_s: 120,
        created_at: '2026-10-21T10:00:00Z', transcript_source: 'asr',
        papers_count: 2, attempts_count: 2,
        last_practice: '2026-10-21T11:00:00Z', has_audio: 1 },
      { id: 'm2', name: 'Unused', duration_s: null,
        created_at: '2026-10-20T10:00:00Z', transcript_source: 'asr',
        papers_count: 0, attempts_count: 0, last_practice: null, has_audio: 0 },
    ])
    mocked.listPapers.mockImplementation(async (materialId: string) =>
      materialId === 'm1' ? [paper('p2', 2), paper('p1', 2)] : [])
    // p1 attempted, p2 never attempted (excluded from the main view).
    mocked.paperStats.mockImplementation(async (paperId: string) =>
      paperId === 'p1'
        ? [
            { item_number: 1, item_type: 'completion', attempts: 2, correct: 2 },
            { item_number: 2, item_type: 'completion', attempts: 2, correct: 0 },
          ]
        : [
            { item_number: 1, item_type: 'completion', attempts: 0, correct: 0 },
            { item_number: 2, item_type: 'completion', attempts: 0, correct: 0 },
          ])
    mocked.getPaper.mockResolvedValue({
      id: 'p1',
      material_id: 'm1',
      spec: { blocks: [], layout_hint: null, regenerate: false },
      stale: false,
      created_at: '2026-10-21T10:00:00Z',
      paper: {
        material_id: 'm1',
        total_items: 2,
        warnings: [],
        groups: [{
          type: 'completion', title: 'Crafted', instruction: '',
          options: [], partial: false, visual: null,
          items: [
            { number: 1, type: 'completion', stem: 'The museum opens at ______.',
              answer: 'nine', options: [], evidence: [], word_limit: null,
              layout: 'sentence', label: '', group_title: '', alternatives: [],
              answer_text: 'nine' },
            { number: 2, type: 'completion', stem: 'Write your ______ here.',
              answer: 'postcode', options: [], evidence: [], word_limit: null,
              layout: 'sentence', label: '', group_title: '', alternatives: [],
              answer_text: 'postcode' },
          ],
        }],
      },
    })
  })

  it('renders by-type accuracy from globalStats', async () => {
    const wrapper = await mountView()
    const typeRow = wrapper.find('.type-row')
    expect(typeRow.text()).toContain('填空')
    expect(typeRow.text()).toContain('6 题')
    expect(typeRow.text()).toContain('67%')
    expect(typeRow.find('.bar > span').attributes('style')).toContain('width: 66.67%')
    wrapper.unmount()
  })

  it('renders per-item accuracy grouped by attempted papers only', async () => {
    const wrapper = await mountView()
    // only the attempted paper becomes a group
    const groups = wrapper.findAll('.paper-group')
    expect(groups).toHaveLength(1)
    const items = groups[0].findAll('.stat-item')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain('The museum opens at')
    expect(items[0].text()).toContain('nine')
    expect(items[0].text()).toContain('100%')
    expect(items[1].text()).toContain('0%')
    expect(items[1].find('.bar > span').attributes('style')).toContain('width: 0%')
    wrapper.unmount()
  })

  it('renders wrong words and jumps to the owning paper on replay', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('postcode')
    expect(wrapper.text()).toContain('3')
    const router = wrapper.vm.$router
    const btn = wrapper.findAll('button').find((b) => b.text().includes('重听'))
    await btn!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/paper/m1/p1')
    wrapper.unmount()
  })

  it('shows the empty state when nothing has been attempted', async () => {
    mocked.globalStats.mockResolvedValue([])
    mocked.getWrongWords.mockResolvedValue([])
    mocked.listMaterials.mockResolvedValue([
      { id: 'm2', name: 'Unused', duration_s: null,
        created_at: '2026-10-20T10:00:00Z', transcript_source: 'asr',
        papers_count: 0, attempts_count: 0, last_practice: null, has_audio: 0 },
    ])
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('还没有作答')
    expect(wrapper.text()).toContain('还没有错词')
    wrapper.unmount()
  })
})
