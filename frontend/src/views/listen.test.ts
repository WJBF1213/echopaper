import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ListenView from './ListenView.vue'
import PlayerBar from '../components/PlayerBar.vue'
import { api } from '../api'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      getMaterial: vi.fn(),
      getTranslations: vi.fn(),
      audioUrl: vi.fn(() => '/api/materials/m1/audio'),
    },
  }
})

const mocked = vi.mocked(api)

/** Three short sentences with clear 1.5s-adjustment headroom. */
const words = [
  { w: 'Hello', s: 2.0, e: 2.4 },
  { w: 'world', s: 2.5, e: 2.9 },
  { w: 'Good', s: 4.0, e: 4.3 },
  { w: 'morning', s: 4.4, e: 4.9 },
  { w: 'Bye', s: 6.0, e: 6.2 },
  { w: 'now', s: 6.3, e: 6.7 },
]

const material = {
  id: 'm1',
  name: 'Cambridge 18 Test 1',
  source_type: 'upload',
  audio_url: null,
  duration_s: 30,
  has_audio: true,
  transcript: 'Hello world Good morning Bye now',
  transcript_source: 'asr',
  asr_model: 'parakeet',
  words,
  sentences: [
    [0, 1],
    [2, 3],
    [4, 5],
  ] as [number, number][],
  created_at: '2026-10-21T10:00:00Z',
  updated_at: '2026-10-21T10:00:00Z',
}

/** Sentence 1 has no translation row and sentence 2 is missing entirely:
 * both must fall back to the placeholder without blocking the page. */
const translations = {
  material_id: 'm1',
  sentences: [
    { index: 0, src: 'Hello world', dst: '你好，世界' },
    { index: 1, src: 'Good morning', dst: null },
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

async function mountView(path = '/listen/m1') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/listen/:materialId', component: ListenView },
      { path: '/material/:materialId', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(ListenView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

/** Drive the shared player's timeupdate so the view recomputes positions. */
async function tick(wrapper: Awaited<ReturnType<typeof mountView>>, t: number) {
  const audio = wrapper.find('audio').element as HTMLAudioElement
  audio.currentTime = t
  audio.dispatchEvent(new Event('timeupdate'))
  await flushPromises()
}

describe('ListenView sentence list', () => {
  beforeEach(() => {
    stubAudio()
    mocked.getMaterial.mockResolvedValue(material)
    mocked.getTranslations.mockResolvedValue(translations)
  })

  it('renders every sentence with its English text and translation', async () => {
    const wrapper = await mountView()
    const rows = wrapper.findAll('.sent-row')
    expect(rows).toHaveLength(3)
    expect(rows[0].text()).toContain('Hello world')
    expect(rows[0].text()).toContain('你好，世界')
    expect(rows[1].text()).toContain('Good morning')
    expect(rows[2].text()).toContain('Bye now')
    wrapper.unmount()
  })

  it('shows the placeholder where the translation is missing', async () => {
    const wrapper = await mountView()
    // Sentence 1 has dst null and sentence 2 has no row at all.
    const placeholders = wrapper
      .findAll('.sent-zh.missing')
      .map((node) => node.text())
    expect(placeholders).toHaveLength(2)
    expect(placeholders[0]).toBe('译文不可用')
    wrapper.unmount()
  })

  it('plays a clicked sentence from 1.5s before its first word', async () => {
    const wrapper = await mountView()
    const audio = wrapper.find('audio').element as HTMLAudioElement
    audio.currentTime = 20
    await wrapper.findAll('.sent-main')[1].trigger('click')
    // Sentence 1 starts at 4.0s -> seek 2.5s and autoplay.
    expect(audio.currentTime).toBeCloseTo(2.5)
    expect(audio.play).toHaveBeenCalled()
    // The progress bar highlights the played interval.
    const bar = wrapper.findComponent(PlayerBar)
    expect(bar.props('hlStart')).toBeCloseTo(2.5)
    expect(bar.props('hlEnd')).toBeCloseTo(5.15) // last word e 4.9 + 0.25

    // Playback stops once it passes the sentence end.
    await tick(wrapper, 5.2)
    expect(audio.pause).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('reuses the shared PlayerBar transport', async () => {
    const wrapper = await mountView()
    const bar = wrapper.findComponent(PlayerBar)
    expect(bar.exists()).toBe(true)
    expect(bar.props('hasAudio')).toBe(true)
    wrapper.unmount()
  })

  it('sets an AB loop around a sentence from its loop button', async () => {
    const wrapper = await mountView()
    const audio = wrapper.find('audio').element as HTMLAudioElement
    // A stale single-sentence play range must not pause the new loop.
    await wrapper.findAll('.sent-main')[0].trigger('click')
    vi.mocked(audio.play).mockClear()
    vi.mocked(audio.pause).mockClear()
    await wrapper.findAll('.sent-row')[1].find('button.loop').trigger('click')
    const bar = wrapper.findComponent(PlayerBar)
    expect(bar.props('abA')).toBeCloseTo(4.0)
    expect(bar.props('abB')).toBeCloseTo(5.15)
    expect(audio.currentTime).toBeCloseTo(4.0)
    expect(audio.play).toHaveBeenCalled()
    // The old stop-at-end range (2.9 + 0.25) no longer applies.
    expect(audio.pause).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('clears a stale AB loop when playing a clicked sentence', async () => {
    const wrapper = await mountView()
    const audio = wrapper.find('audio').element as HTMLAudioElement
    // 精听 core flow: loop a hard sentence, then move on by clicking the
    // next one. The old loop must not hijack the clicked sentence.
    await wrapper.findAll('.sent-row')[1].find('button.loop').trigger('click')
    expect(wrapper.findComponent(PlayerBar).props('abA')).toBeCloseTo(4.0)
    vi.mocked(audio.play).mockClear()
    vi.mocked(audio.pause).mockClear()

    await wrapper.findAll('.sent-main')[2].trigger('click')
    // Seek landed at sentence 2's start (6.0 − 1.5 = 4.5), autoplaying.
    expect(audio.currentTime).toBeCloseTo(4.5)
    expect(audio.play).toHaveBeenCalled()
    // The AB points are cleared (mutual exclusion with 单句循环).
    const bar = wrapper.findComponent(PlayerBar)
    expect(bar.props('abA')).toBeNull()
    expect(bar.props('abB')).toBeNull()

    // Crossing the old loop's B (5.15) no longer wraps playback to abA...
    audio.currentTime = 5.2
    audio.dispatchEvent(new Event('timeupdate'))
    await flushPromises()
    expect(audio.currentTime).toBeCloseTo(5.2)
    // ...and the clicked sentence is not cut short by a stale range.
    expect(audio.pause).not.toHaveBeenCalled()

    // The stop-at-end watch still ends the clicked sentence at its end.
    audio.currentTime = 7.0
    audio.dispatchEvent(new Event('timeupdate'))
    await flushPromises()
    expect(audio.pause).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('highlights the current playing word inside its sentence', async () => {
    const wrapper = await mountView()
    await tick(wrapper, 4.2) // inside "Good" (4.0-4.3)
    const active = wrapper.find('.word.active')
    expect(active.exists()).toBe(true)
    expect(active.text()).toBe('Good')
    // The owning sentence row is marked current for auto-scroll targeting.
    expect(wrapper.find('.sent-row.active').attributes('data-sentence')).toBe('1')
    wrapper.unmount()
  })

  it('scrolls the current sentence into view as playback moves', async () => {
    const spy = vi.fn()
    Element.prototype.scrollIntoView = spy
    const wrapper = await mountView()
    await tick(wrapper, 6.1) // sentence 2
    expect(spy).toHaveBeenCalled()
    const arg = spy.mock.calls.at(-1)![0] as { block?: string }
    expect(arg.block).toBe('center')
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
    wrapper.unmount()
  })

  it('shows an error state when the material does not exist', async () => {
    mocked.getMaterial.mockRejectedValueOnce(new Error('材料不存在'))
    const wrapper = await mountView('/listen/missing')
    expect(wrapper.text()).toContain('材料不存在')
    wrapper.unmount()
  })

  it('shows an empty state when there is no transcript', async () => {
    mocked.getMaterial.mockResolvedValueOnce({
      ...material,
      words: [],
      sentences: [],
    })
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('没有转写句子')
    wrapper.unmount()
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})
