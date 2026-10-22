import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import LibraryView from './LibraryView.vue'
import { api } from '../api'
import { toast } from '../router'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      listMaterials: vi.fn(),
      createMaterial: vi.fn(),
      deleteMaterial: vi.fn(),
      getJob: vi.fn(),
      listBatches: vi.fn(),
      getBatch: vi.fn(),
      asrStatus: vi.fn(),
      asrLoad: vi.fn(),
      asrUnload: vi.fn(),
    },
  }
})

const mocked = vi.mocked(api)

const materials = [
  {
    id: 'm1',
    name: '剑桥 18 Test 1',
    duration_s: 120,
    created_at: '2026-10-21T10:00:00Z',
    transcript_source: 'asr',
    sets_count: 2,
    best_score: 0.8,
    last_practice: '2026-10-21T11:00:00Z',
    has_audio: 1,
  },
  {
    id: 'm2',
    name: 'TED Talk',
    duration_s: null,
    created_at: '2026-10-20T10:00:00Z',
    transcript_source: 'manual',
    sets_count: 0,
    best_score: null,
    last_practice: null,
    has_audio: 0,
  },
]

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: LibraryView },
      { path: '/material/:materialId', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(LibraryView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('LibraryView', () => {
  beforeEach(() => {
    mocked.listMaterials.mockResolvedValue(materials)
    mocked.listBatches.mockResolvedValue([])
    mocked.asrStatus.mockResolvedValue({
      state: 'unloaded',
      engine: 'parakeet',
      model: 'mlx-community/parakeet-tdt-0.6b-v3',
      idle_unload_min: 10,
    })
  })

  it('renders materials with set counts and best score chips', async () => {
    const wrapper = await mountView()
    const cards = wrapper.findAll('.mat')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('剑桥 18 Test 1')
    expect(cards[0].text()).toContain('2 套题')
    expect(cards[0].text()).toContain('最好 80%')
    expect(cards[1].text()).toContain('语音朗读')
    wrapper.unmount()
  })

  it('filters by search query', async () => {
    const wrapper = await mountView()
    await wrapper.find('input[type="search"]').setValue('ted')
    expect(wrapper.findAll('.mat')).toHaveLength(1)
    expect(wrapper.text()).toContain('TED Talk')
    wrapper.unmount()
  })

  it('polls the job until done and reloads the list', async () => {
    mocked.getJob
      .mockResolvedValueOnce({
        id: 'j1',
        state: 'transcribing',
        message: '识别中',
        percent: 30,
        material_id: null,
        created_at: '',
        updated_at: '',
      })
      .mockResolvedValueOnce({
        id: 'j1',
        state: 'done',
        message: null,
        percent: 100,
        material_id: 'm1',
        created_at: '',
        updated_at: '',
      })
    const wrapper = await mountView()
    mocked.listMaterials.mockClear()

    const form = wrapper.findComponent({ name: 'MaterialForm' })
    form.vm.$emit('created', 'j1')
    await flushPromises()
    expect(wrapper.find('.job').exists()).toBe(true)

    await new Promise((r) => setTimeout(r, 1500))
    await flushPromises()

    expect(mocked.getJob).toHaveBeenCalledTimes(2)
    expect(mocked.listMaterials).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('stops polling once a job errors', async () => {
    mocked.getJob.mockResolvedValue({
      id: 'j2',
      state: 'error',
      message: 'Material failed',
      percent: null,
      material_id: null,
      created_at: '',
      updated_at: '',
    })
    const wrapper = await mountView()
    const form = wrapper.findComponent({ name: 'MaterialForm' })
    form.vm.$emit('created', 'j2')
    await flushPromises()

    expect(wrapper.find('.job').text()).toContain('失败')
    expect(toast.value?.kind).toBe('error')
    expect(toast.value?.text).toContain('Material failed')
    toast.value = null
    wrapper.unmount()
  })

  it('shows per-file batch progress and opens finished materials', async () => {
    mocked.getBatch
      .mockResolvedValueOnce({
        id: 'b1',
        name: 'Batch A',
        total: 2,
        done: 0,
        error: 0,
        running: 2,
        percent: 30,
        created_at: '',
        updated_at: '',
        jobs: [
          {
            job_id: 'j1', state: 'transcribing', message: null, percent: 30,
            material_id: null, file_name: 'one.mp3', position: 0,
            created_at: '', updated_at: '',
          },
          {
            job_id: 'j2', state: 'queued', message: null, percent: 0,
            material_id: null, file_name: 'two.mp3', position: 1,
            created_at: '', updated_at: '',
          },
        ],
      })
      .mockResolvedValueOnce({
        id: 'b1',
        name: 'Batch A',
        total: 2,
        done: 2,
        error: 0,
        running: 0,
        percent: 100,
        created_at: '',
        updated_at: '',
        jobs: [
          {
            job_id: 'j1', state: 'done', message: null, percent: 100,
            material_id: 'm1', file_name: 'one.mp3', position: 0,
            created_at: '', updated_at: '',
          },
          {
            job_id: 'j2', state: 'done', message: null, percent: 100,
            material_id: 'm2', file_name: 'two.mp3', position: 1,
            created_at: '', updated_at: '',
          },
        ],
      })
    const wrapper = await mountView()
    const importer = wrapper.findComponent({ name: 'BatchImport' })
    importer.vm.$emit('created', 'b1')
    await flushPromises()

    expect(wrapper.find('.batch').text()).toContain('one.mp3')
    expect(wrapper.find('.batch').text()).toContain('识别')

    await new Promise((r) => setTimeout(r, 1700))
    await flushPromises()

    expect(mocked.getBatch).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.batch').text()).toContain('2/2 完成')
    expect(wrapper.find('.batch .progress').classes()).toContain('ok')
    expect(wrapper.findAll('.batch .jobrow')).toHaveLength(2)
    expect(wrapper.findAll('.batch .jobrow button')).toHaveLength(2)
    wrapper.unmount()
  })

  it('lists recent batches and reloads one on click', async () => {
    mocked.listBatches.mockResolvedValue([
      {
        id: 'b2', name: '剑桥 18', total: 3, done: 2, error: 1, running: 0,
        percent: 100, created_at: '2026-10-21T10:00:00Z',
        updated_at: '2026-10-21T10:00:00Z',
      },
    ])
    mocked.getBatch.mockResolvedValue({
      id: 'b2', name: '剑桥 18', total: 3, done: 2, error: 1, running: 0,
      percent: 100, created_at: '', updated_at: '',
      jobs: [],
    })
    const wrapper = await mountView()
    const row = wrapper.find('.batchrow')
    expect(row.text()).toContain('剑桥 18')
    expect(row.text()).toContain('1 失败')
    await row.trigger('click')
    await flushPromises()
    expect(mocked.getBatch).toHaveBeenCalledWith('b2')
    wrapper.unmount()
  })

  it('deletes a material after confirmation', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    mocked.deleteMaterial.mockResolvedValue({ ok: true })
    const wrapper = await mountView()
    await wrapper.find('.icon-btn').trigger('click')
    await flushPromises()
    expect(mocked.deleteMaterial).toHaveBeenCalledWith('m1')
    wrapper.unmount()
  })
})
