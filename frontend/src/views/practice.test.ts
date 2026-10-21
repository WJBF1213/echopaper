import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import PracticeView from './PracticeView.vue'
import { api } from '../api'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      getSet: vi.fn(),
      getMaterial: vi.fn(),
      audioUrl: vi.fn(() => '/api/materials/m1/audio'),
      submitAttempt: vi.fn(),
      submitDictation: vi.fn(),
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
  { w: 'every', s: 1.9, e: 2.2 },
  { w: 'morning', s: 2.3, e: 2.8 },
  { w: 'and', s: 2.9, e: 3 },
  { w: 'closes', s: 3.1, e: 3.4 },
  { w: 'late', s: 3.5, e: 3.8 },
  { w: 'on', s: 3.9, e: 4 },
  { w: 'weekends', s: 4.1, e: 4.6 },
]

const blank = {
  id: 'b1',
  position: 1,
  answer: 'nine',
  alternatives: [],
  word_start: 4,
  word_end: 4,
  t_start: 1.5,
  t_end: 1.8,
  type: 'number',
  word_limit: 'ONE WORD ONLY',
}

const setDetail = {
  id: 's1',
  material_id: 'm1',
  mode: 'llm',
  blank_count: 1,
  stale: 0,
  created_at: '2026-10-21T10:00:00Z',
  blanks: [blank],
}

const materialDetail = {
  id: 'm1',
  name: 'Test Material',
  source_type: 'upload',
  audio_url: null,
  duration_s: 60,
  has_audio: true,
  transcript: 'The museum opens at nine every morning and closes late on weekends.',
  transcript_source: 'asr',
  asr_model: 'parakeet',
  words,
  sentences: [[0, 11]] as [number, number][],
  sets: [],
  created_at: '2026-10-21T10:00:00Z',
  updated_at: '2026-10-21T10:00:00Z',
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/material/:materialId', component: { template: '<div />' } },
      { path: '/practice/:setId', component: PracticeView },
    ],
  })
  await router.push('/practice/s1')
  await router.isReady()
  const wrapper = mount(PracticeView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

/** jsdom has no media element implementation. */
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

describe('PracticeView', () => {
  beforeEach(() => {
    stubAudio()
    mocked.getSet.mockResolvedValue(setDetail)
    mocked.getMaterial.mockResolvedValue(materialDetail)
    mocked.submitAttempt.mockResolvedValue({
      attempt_id: 'a1',
      ok: 1,
      total: 1,
      results: [{ blank_id: 'b1', correct: true, expected: 'nine', user_text: 'nine' }],
    })
  })

  it('renders one blank input for the set', async () => {
    const wrapper = await mountView()
    const inputs = wrapper.findAll('.exam .blank input')
    expect(inputs).toHaveLength(1)
    expect(inputs[0].attributes('aria-label')).toContain('第 1 题')
    wrapper.unmount()
  })

  it('seeks 1.5s before the blank start when the blank is clicked', async () => {
    const wrapper = await mountView()
    const audio = wrapper.find('audio').element as HTMLAudioElement
    audio.currentTime = 30
    const input = wrapper.find('.exam .blank input')
    await input.trigger('click')
    expect(audio.currentTime).toBeCloseTo(0)
    wrapper.unmount()
  })

  it('renders sentence timestamps in the cloze text', async () => {
    const wrapper = await mountView()
    const stamps = wrapper.findAll('.exam .sent-time')
    expect(stamps).toHaveLength(1)
    expect(stamps[0].text()).toBe('0:00')
    wrapper.unmount()
  })

  it('seeks to a word when it is clicked', async () => {
    const wrapper = await mountView()
    const audio = wrapper.find('audio').element as HTMLAudioElement
    audio.currentTime = 30
    await wrapper.find('.exam .word[data-word-index="1"]').trigger('click')
    expect(audio.currentTime).toBeCloseTo(0.4)
    wrapper.unmount()
  })

  it('highlights the word under the playhead', async () => {
    const wrapper = await mountView()
    const audio = wrapper.find('audio').element as HTMLAudioElement
    audio.currentTime = 0.5
    audio.dispatchEvent(new Event('timeupdate'))
    await flushPromises()
    expect(wrapper.find('.exam .word.active[data-word-index="1"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('submits answers and renders per-blank grading classes', async () => {
    const wrapper = await mountView()
    const input = wrapper.find('.exam .blank input')
    await input.setValue('nine')
    await wrapper.find('.actions-card button').trigger('click')
    await flushPromises()

    expect(mocked.submitAttempt).toHaveBeenCalledWith(
      's1',
      [{ blank_id: 'b1', text: 'nine' }],
      expect.any(Number),
    )
    expect(wrapper.find('.blank.ok').exists()).toBe(true)
    expect(wrapper.find('.result.good').text()).toContain('全部正确')
    wrapper.unmount()
  })

  it('marks wrong answers red and shows the expected word', async () => {
    mocked.submitAttempt.mockResolvedValue({
      attempt_id: 'a1',
      ok: 0,
      total: 1,
      results: [{ blank_id: 'b1', correct: false, expected: 'nine', user_text: 'ten' }],
    })
    const wrapper = await mountView()
    await wrapper.find('.exam .blank input').setValue('ten')
    await wrapper.find('.actions-card button').trigger('click')
    await flushPromises()

    expect(wrapper.find('.blank.bad').exists()).toBe(true)
    expect(wrapper.find('.blank .mark.bad').text()).toBe('nine')
    wrapper.unmount()
  })

  it('persists answers to a per-set draft', async () => {
    const wrapper = await mountView()
    await wrapper.find('.exam .blank input').setValue('nine')
    await new Promise((r) => setTimeout(r, 500))
    const raw = localStorage.getItem('ielts_cloze_draft_s1')
    expect(raw && JSON.parse(raw).b1).toBe('nine')
    wrapper.unmount()
  })

  it('toggles dictation mode and submits dictation items', async () => {
    mocked.submitDictation.mockResolvedValue({
      attempt_id: 'd1',
      ok: 1,
      total: 1,
      results: [{ word_index: 1, correct: true, expected: 'museum', t_start: 0.4, user_text: 'museum' }],
    })
    const wrapper = await mountView()
    const dictBtn = wrapper.findAll('button').find((b) => b.text().includes('全篇听写'))
    expect(dictBtn).toBeTruthy()
    await dictBtn!.trigger('click')
    await flushPromises()

    const dictInputs = wrapper.findAll('.dict-word input')
    expect(dictInputs.length).toBeGreaterThan(0)
    await dictInputs[0].setValue('museum')

    const checkBtn = wrapper.findAll('button').find((b) => b.text().includes('批改'))
    await checkBtn!.trigger('click')
    await flushPromises()

    expect(mocked.submitDictation).toHaveBeenCalledWith(
      'm1',
      [{ word_index: 1, text: 'museum' }],
    )
    expect(wrapper.text()).toContain('听写正确率')
    wrapper.unmount()
  })

  it('binds space / arrows / Enter shortcuts', async () => {
    const wrapper = await mountView()
    const audio = wrapper.find('audio').element as HTMLAudioElement
    const playSpy = vi.spyOn(audio, 'play')

    const prevent = vi.fn()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true }))
    await flushPromises()
    expect(playSpy).toHaveBeenCalled()

    const left = new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true })
    Object.defineProperty(left, 'preventDefault', { value: prevent })
    window.dispatchEvent(left)
    expect(prevent).toHaveBeenCalled()
    wrapper.unmount()
  })
})
