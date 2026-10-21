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
      getAttempts: vi.fn(),
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

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/material/:materialId', component: MaterialView },
      { path: '/practice/:setId', component: { template: '<div />' } },
    ],
  })
  await router.push('/material/m1')
  await router.isReady()
  const wrapper = mount(MaterialView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('MaterialView transcript playback', () => {
  beforeEach(() => {
    stubAudio()
    mocked.getMaterial.mockResolvedValue(material)
    mocked.getAttempts.mockResolvedValue([])
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
