import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import MaterialView from './MaterialView.vue'
import { api } from '../api'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      getMaterial: vi.fn(),
      listPapers: vi.fn(),
      deletePaper: vi.fn(),
      listPaperAttempts: vi.fn(),
      getAttempt: vi.fn(),
      examTypes: vi.fn(),
      audioUrl: vi.fn(() => '/api/materials/m1/audio'),
      translate: vi.fn(),
    },
  }
})

const mocked = vi.mocked(api)

const words = [
  { w: 'The', s: 0, e: 0.3 },
  { w: 'museum', s: 0.4, e: 0.9 },
  { w: 'opens', s: 1, e: 1.2 },
  { w: 'at', s: 1.3, e: 1.4 },
  { w: 'nine', s: 1.5, e: 1.8 },
]

const material = {
  id: 'm1',
  name: 'Test Material',
  source_type: 'upload',
  audio_url: null,
  duration_s: 60,
  has_audio: true,
  transcript: 'The museum opens at nine.',
  transcript_source: 'asr',
  asr_model: 'parakeet',
  words,
  sentences: [[0, 4]] as [number, number][],
  sets: [],
  created_at: '2026-10-21T10:00:00Z',
  updated_at: '2026-10-21T10:00:00Z',
}

const papers = [
  {
    id: 'p2',
    blocks: [{ type: 'completion', count: 6 }, { type: 'mcq_single', count: 4 }],
    item_count: 10,
    stale: true,
    created_at: '2026-10-21T11:00:00Z',
  },
  {
    id: 'p1',
    blocks: [{ type: 'completion', count: 3 }],
    item_count: 3,
    stale: false,
    created_at: '2026-10-20T09:00:00Z',
  },
]

const examTypes = {
  types: [
    { key: 'completion', name: '填空', name_zh: '填空', name_en: 'Completion',
      answer_kind: 'span', layouts: [], generates_visual: false,
      max_count: 10, min_words: 2 },
    { key: 'mcq_single', name: '单选', name_zh: '单选', name_en: 'MCQ',
      answer_kind: 'option', layouts: [], generates_visual: false,
      max_count: 10, min_words: 2 },
  ],
}

function stubAudio() {
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: vi.fn().mockResolvedValue(undefined),
  })
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value: vi.fn(),
  })
}

async function mountView(path = '/material/m1') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/material/:materialId', component: MaterialView },
      { path: '/paper/:materialId', component: { template: '<div />' } },
      { path: '/paper/:materialId/:paperId', component: { template: '<div />' } },
      { path: '/practice/:setId', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(MaterialView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('MaterialView transcript playback', () => {
  beforeEach(() => {
    stubAudio()
    mocked.getMaterial.mockResolvedValue(material)
    mocked.listPapers.mockResolvedValue([])
    mocked.examTypes.mockResolvedValue(examTypes)
  })

  it('shows sentence timestamps in the transcript', async () => {
    const wrapper = await mountView()
    const stamps = wrapper.findAll('.transcript .sent-time')
    expect(stamps).toHaveLength(1)
    expect(stamps[0].text()).toBe('0:00')
    wrapper.unmount()
  })

  it('seeks to a transcript word on click', async () => {
    const wrapper = await mountView()
    const audio = wrapper.find('audio').element as HTMLAudioElement
    audio.currentTime = 30
    await wrapper.find('.transcript .word[data-word-index="1"]').trigger('click')
    expect(audio.currentTime).toBeCloseTo(0.4)
    wrapper.unmount()
  })

  it('plays a whole sentence from its timestamp', async () => {
    const wrapper = await mountView()
    const audio = wrapper.find('audio').element as HTMLAudioElement
    audio.currentTime = 30
    await wrapper.find('.transcript .sent-time').trigger('click')
    expect(audio.currentTime).toBeCloseTo(0)
    wrapper.unmount()
  })
})

describe('MaterialView papers list', () => {
  beforeEach(() => {
    stubAudio()
    mocked.getMaterial.mockResolvedValue(material)
    mocked.listPapers.mockReset()
    mocked.listPapers.mockResolvedValue(papers)
    mocked.examTypes.mockResolvedValue(examTypes)
  })

  it('renders papers with composition chips, item counts and stale badge', async () => {
    const wrapper = await mountView()
    const rows = wrapper.findAll('.paper-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('填空 ×6')
    expect(rows[0].text()).toContain('单选 ×4')
    expect(rows[0].text()).toContain('10 题')
    expect(rows[0].find('.chip.warn').exists()).toBe(true)
    expect(rows[1].find('.chip.warn').exists()).toBe(false)
    wrapper.unmount()
  })

  it('opens a stored paper at its historical route', async () => {
    const wrapper = await mountView()
    await wrapper.findAll('.paper-row')[0].find('button.open').trigger('click')
    await flushPromises()
    expect(wrapper.vm.$router.currentRoute.value.fullPath).toBe('/paper/m1/p2')
    wrapper.unmount()
  })

  it('links the generate entry to the paper builder', async () => {
    const wrapper = await mountView()
    const btn = wrapper.findAll('button').find((b) => b.text().includes('生成整卷'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()
    expect(wrapper.vm.$router.currentRoute.value.fullPath).toBe('/paper/m1')
    wrapper.unmount()
  })

  it('deletes a paper after confirmation and reloads the list', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    mocked.deletePaper.mockResolvedValue(undefined)
    const wrapper = await mountView()
    mocked.listPapers.mockClear()
    await wrapper.findAll('.paper-row')[1].find('button.icon-btn').trigger('click')
    await flushPromises()
    expect(mocked.deletePaper).toHaveBeenCalledWith('p1')
    expect(mocked.listPapers).toHaveBeenCalledWith('m1')
    wrapper.unmount()
  })

  it('expands a paper, lists its attempts and shows per-item correctness', async () => {
    mocked.listPaperAttempts.mockResolvedValue([
      { id: 'a1', created_at: '2026-10-21T12:00:00Z', item_count: 3 },
    ])
    mocked.getAttempt.mockResolvedValue({
      id: 'a1',
      paper_id: 'p1',
      material_id: 'm1',
      created_at: '2026-10-21T12:00:00Z',
      items: [
        { item_number: 1, item_type: 'completion', user_answer: 'nine', correct: true, expected: 'nine' },
        { item_number: 2, item_type: 'completion', user_answer: 'x', correct: false, expected: 'gate' },
        { item_number: 3, item_type: 'completion', user_answer: null, correct: false, expected: 'door' },
      ],
    })
    const wrapper = await mountView()
    const toggle = wrapper.findAll('.paper-row')[1].find('button.attempts')
    await toggle.trigger('click')
    await flushPromises()
    expect(mocked.listPaperAttempts).toHaveBeenCalledWith('p1')
    expect(wrapper.text()).toContain('3 题')

    await wrapper.find('.attempt-row').trigger('click')
    await flushPromises()
    expect(mocked.getAttempt).toHaveBeenCalledWith('a1')
    expect(wrapper.text()).toContain('正确 1/3')
    const chips = wrapper.findAll('.attempt-detail .item-chip')
    expect(chips).toHaveLength(3)
    expect(chips[0].classes()).toContain('ok')
    expect(chips[1].classes()).toContain('bad')
    wrapper.unmount()
  })
})
