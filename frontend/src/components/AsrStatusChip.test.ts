import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AsrStatusChip from './AsrStatusChip.vue'
import { api } from '../api'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      asrStatus: vi.fn(),
      asrLoad: vi.fn(),
      asrUnload: vi.fn(),
    },
  }
})

const mocked = vi.mocked(api)

function mountChip() {
  const wrapper = mount(AsrStatusChip)
  return wrapper
}

describe('AsrStatusChip engine label', () => {
  beforeEach(() => {
    mocked.asrLoad.mockReset()
    mocked.asrUnload.mockReset()
  })

  it('labels the local engine with the bare model name (repo prefix trimmed)', async () => {
    mocked.asrStatus.mockResolvedValue({
      state: 'ready',
      engine: 'parakeet',
      model: 'mlx-community/parakeet-0.6b-v3',
      idle_unload_min: 10,
    })
    const wrapper = mountChip()
    await flushPromises()
    expect(wrapper.find('.engine').text()).toBe('parakeet · parakeet-0.6b-v3')
    wrapper.unmount()
  })

  it('labels cloud mode as cloud · <cloud_model> verbatim', async () => {
    mocked.asrStatus.mockResolvedValue({
      state: 'ready',
      engine: 'cloud',
      // A slashed id must NOT be prefix-trimmed in cloud mode: the cloud
      // model is a provider-facing name, shown exactly as configured.
      model: 'groq/whisper-large-v3-turbo',
      idle_unload_min: 10,
    })
    const wrapper = mountChip()
    await flushPromises()
    expect(wrapper.find('.engine').text()).toBe('cloud · groq/whisper-large-v3-turbo')
    wrapper.unmount()
  })
})
