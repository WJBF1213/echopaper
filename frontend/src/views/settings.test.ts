import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import SettingsView from './SettingsView.vue'
import { api } from '../api'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      getSettings: vi.fn(),
      updateSettings: vi.fn(),
      asrStatus: vi.fn(),
      asrLoad: vi.fn(),
      asrUnload: vi.fn(),
      testLlm: vi.fn(),
    },
  }
})

const mocked = vi.mocked(api)

const settings = {
  llm: {
    provider: 'zhipu',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4.7-flash',
    max_context_tokens: 262144,
    has_key: true,
    key_masked: 'abcd****wxyz',
  },
  asr: {
    engine: 'parakeet',
    parakeet_model: 'mlx-community/parakeet-tdt-0.6b-v3',
    whisper_model: 'mlx-community/whisper-large-v3-turbo',
    faster_whisper_model: 'large-v3-turbo',
    idle_unload_min: 10,
    available_engines: ['parakeet', 'whisper', 'faster_whisper'],
    default_engine: 'parakeet',
  },
  gen: { blank_count: 10 },
}

const status = {
  state: 'unloaded' as const,
  engine: 'parakeet',
  model: 'mlx-community/parakeet-tdt-0.6b-v3',
  idle_unload_min: 10,
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings', component: SettingsView }],
  })
  await router.push('/settings')
  await router.isReady()
  const wrapper = mount(SettingsView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('SettingsView', () => {
  beforeEach(() => {
    mocked.getSettings.mockResolvedValue(settings)
    mocked.asrStatus.mockResolvedValue(status)
    mocked.updateSettings.mockResolvedValue({
      ...settings,
      asr: { ...settings.asr, engine: 'whisper' },
    })
  })

  it('loads settings and masks the stored key', async () => {
    const wrapper = await mountView()
    const keyInput = wrapper.find('input[type="password"]')
    expect(keyInput.attributes('placeholder')).toContain('abcd****wxyz')
    const modelInput = wrapper
      .findAll('input[type="text"]')
      .find((i) => (i.element as HTMLInputElement).value === 'glm-4.7-flash')
    expect(modelInput).toBeTruthy()
    wrapper.unmount()
  })

  it('switches engine through PUT /settings and shows the new status', async () => {
    const wrapper = await mountView()
    const engineSelect = wrapper
      .findAll('select')
      .find((s) => s.findAll('option').some((o) => o.text().includes('mlx-whisper')))
    expect(engineSelect).toBeTruthy()
    await engineSelect!.setValue('whisper')

    const saveBtn = wrapper.findAll('button').find((b) => b.text().includes('保存设置'))
    await saveBtn!.trigger('click')
    await flushPromises()

    expect(mocked.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        asr: expect.objectContaining({ engine: 'whisper' }),
      }),
    )
    expect(mocked.asrStatus).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps the stored key when the input is left blank', async () => {
    const wrapper = await mountView()
    const saveBtn = wrapper.findAll('button').find((b) => b.text().includes('保存设置'))
    await saveBtn!.trigger('click')
    await flushPromises()

    const patch = mocked.updateSettings.mock.calls[0][0]
    expect(patch.llm && 'api_key' in patch.llm).toBe(false)
    wrapper.unmount()
  })

  it('reports LLM connection test result', async () => {
    mocked.testLlm.mockResolvedValue({ ok: true, message: '连接正常' })
    const wrapper = await mountView()
    const testBtn = wrapper.findAll('button').find((b) => b.text().includes('保存并测试'))
    await testBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('连接正常')
    wrapper.unmount()
  })

  it('saves the typed key before testing it', async () => {
    mocked.testLlm.mockResolvedValue({ ok: true, message: '连接正常' })
    const wrapper = await mountView()
    // Pick DeepSeek so the form holds provider + endpoint the backend has not seen.
    const providerSelect = wrapper.findAll('select')[0]
    await providerSelect.setValue('deepseek')
    await wrapper.find('input[type="password"]').setValue('sk-typed-in-form')

    const testBtn = wrapper.findAll('button').find((b) => b.text().includes('保存并测试'))
    await testBtn!.trigger('click')
    await flushPromises()

    // Saving first is what makes a typed-but-unsaved key actually usable.
    expect(mocked.updateSettings).toHaveBeenCalledWith({
      llm: expect.objectContaining({
        provider: 'deepseek',
        base_url: 'https://api.deepseek.com/v1',
        model: 'deepseek-chat',
        api_key: 'sk-typed-in-form',
      }),
    })
    expect(mocked.testLlm).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: 'deepseek',
        api_key: 'sk-typed-in-form',
      }),
    )
    // The key is cleared once stored, so the masked placeholder shows again.
    expect((wrapper.find('input[type="password"]').element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
  })
})
