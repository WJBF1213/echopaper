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
      getStats: vi.fn(),
      getWrongWords: vi.fn(),
    },
  }
})

const mocked = vi.mocked(api)

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/review', component: ReviewView },
      { path: '/material/:materialId', component: { template: '<div />' } },
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
    mocked.getStats.mockResolvedValue({ materials: 3, attempts: 7, avg_score: 0.72 })
    mocked.getWrongWords.mockResolvedValue([
      { word: 'postcode', times_wrong: 3, last_at: '2026-10-21T10:00:00Z', material_id: 'm1', t_start: 42.5 },
    ])
  })

  it('renders stats and wrong words', async () => {
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('72%')
    expect(wrapper.text()).toContain('postcode')
    expect(wrapper.text()).toContain('3')
    wrapper.unmount()
  })

  it('navigates to the material at the wrong word timestamp', async () => {
    const wrapper = await mountView()
    const router = wrapper.vm.$router
    const btn = wrapper.findAll('button').find((b) => b.text().includes('重听'))
    await btn!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/material/m1?t=42.5')
    wrapper.unmount()
  })
})
