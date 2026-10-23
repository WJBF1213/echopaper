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
      testCloudAsr: vi.fn(),
      listPrompts: vi.fn(),
      putPrompt: vi.fn(),
      clearLlmCache: vi.fn(),
      health: vi.fn(),
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
    mode: 'local' as const,
    engine: 'parakeet',
    idle_unload_min: 10,
    cloud_base_url: 'https://api.groq.com/openai/v1',
    cloud_model: 'whisper-large-v3-turbo',
    has_cloud_key: false,
    cloud_key_masked: null,
  },
}

/** Stored cloud configuration (GET shape once mode=cloud was saved). */
const cloudSettings = {
  ...settings,
  asr: {
    ...settings.asr,
    mode: 'cloud' as const,
    engine: 'cloud',
    has_cloud_key: true,
    cloud_key_masked: 'abcd****wxyz',
  },
}

const status = {
  state: 'unloaded' as const,
  engine: 'parakeet',
  model: 'mlx-community/parakeet-tdt-0.6b-v3',
  idle_unload_min: 10,
}

const promptEntries = [
  {
    key: 'exam.system.zh',
    title: '系统提示 · 中文',
    category: 'system',
    variables: [] as string[],
    default: '默认系统提示',
    current: '默认系统提示',
    customized: false,
  },
  {
    key: 'exam.stable_frame.zh',
    title: '稳定框架 · 中文',
    category: 'frame',
    variables: ['transcript', 'candidates'],
    default: 'T: {{transcript}}\nC: {{candidates}}',
    current: 'T: {{transcript}}\nC: {{candidates}}',
    customized: false,
  },
  {
    key: 'exam.rules.form_completion.en',
    title: 'Rules · Form completion',
    category: 'rules',
    variables: ['instruction'],
    default: 'Default rules {{instruction}}',
    current: 'My custom rules {{instruction}}',
    customized: true,
  },
]

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
    mocked.updateSettings.mockResolvedValue(settings)
    // Fresh copies per mount: the view replaces entries in the array it is
    // handed, and reusing the fixture objects would leak edits across tests.
    mocked.listPrompts.mockImplementation(async () =>
      promptEntries.map((p) => ({ ...p, variables: [...p.variables] })),
    )
    mocked.putPrompt.mockImplementation(async (_key: string, text: string) => ({
      ...promptEntries[0],
      key: _key,
      current: text || promptEntries[0].default,
      customized: Boolean(text),
    }))
    mocked.clearLlmCache.mockResolvedValue({ deleted: 3 })
    mocked.health.mockResolvedValue({ ok: true, version: '0.1.0' })
  })

  it('shows the app version from /api/health in the footer', async () => {
    const wrapper = await mountView()
    expect(mocked.health).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.version-footer').text()).toContain('EchoPaper v0.1.0')
    wrapper.unmount()
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

  it('renders the Local/Cloud mode selector with fixed local engine info only', async () => {
    const wrapper = await mountView()

    // Mode radio group: local checked, cloud present.
    const radios = wrapper.findAll('input[type="radio"]')
    expect(radios).toHaveLength(2)
    expect((wrapper.find('input[type="radio"][value="local"]').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.find('input[type="radio"][value="cloud"]').exists()).toBe(true)

    // Local mode: read-only engine label + fixed-model hint + idle input.
    expect(wrapper.text()).toContain('parakeet-mlx')
    expect(wrapper.text()).toContain('本地模型已按平台固定')
    expect(
      wrapper
        .findAll('input[type="number"]')
        .find((i) => (i.element as HTMLInputElement).value === '10'),
    ).toBeTruthy()

    // No cloud fields while local: no preset select, no privacy notice,
    // no input holding the cloud base URL.
    const presetSelect = wrapper
      .findAll('select')
      .find((s) => s.findAll('option').some((o) => o.text().includes('Groq')))
    expect(presetSelect).toBeUndefined()
    expect(wrapper.text()).not.toContain('云端模式下音频将上传')
    const cloudUrlInput = wrapper
      .findAll('input[type="text"]')
      .find((i) => (i.element as HTMLInputElement).value === 'https://api.groq.com/openai/v1')
    expect(cloudUrlInput).toBeUndefined()
    wrapper.unmount()
  })

  it('cloud mode shows base URL / model / key inputs, preset select, test button and privacy notice', async () => {
    const wrapper = await mountView()
    await wrapper.find('input[type="radio"][value="cloud"]').setValue(true)

    const presetSelect = wrapper
      .findAll('select')
      .find((s) => s.findAll('option').some((o) => o.text().includes('Groq')))
    expect(presetSelect).toBeTruthy()

    const urlInput = wrapper
      .findAll('input[type="text"]')
      .find((i) => (i.element as HTMLInputElement).value === 'https://api.groq.com/openai/v1')
    expect(urlInput).toBeTruthy()
    const modelInput = wrapper
      .findAll('input[type="text"]')
      .find((i) => (i.element as HTMLInputElement).value === 'whisper-large-v3-turbo')
    expect(modelInput).toBeTruthy()

    // Second password input = the cloud key field (first is the LLM key).
    expect(wrapper.findAll('input[type="password"]')).toHaveLength(2)

    const testBtn = wrapper.findAll('button').find((b) => b.text().includes('测试连接'))
    expect(testBtn).toBeTruthy()

    expect(wrapper.text()).toContain('云端模式下音频将上传')
    wrapper.unmount()
  })

  it('applies cloud presets into the base URL and model fields', async () => {
    const wrapper = await mountView()
    await wrapper.find('input[type="radio"][value="cloud"]').setValue(true)

    const presetSelect = wrapper
      .findAll('select')
      .find((s) => s.findAll('option').some((o) => o.text().includes('Groq')))!
    await presetSelect.setValue('openai')
    let urlInput = wrapper
      .findAll('input[type="text"]')
      .find((i) => (i.element as HTMLInputElement).value === 'https://api.openai.com/v1')!
    expect(urlInput).toBeTruthy()
    expect(
      wrapper
        .findAll('input[type="text"]')
        .find((i) => (i.element as HTMLInputElement).value === 'whisper-1'),
    ).toBeTruthy()

    await presetSelect.setValue('groq')
    urlInput = wrapper
      .findAll('input[type="text"]')
      .find((i) => (i.element as HTMLInputElement).value === 'https://api.groq.com/openai/v1')!
    expect(urlInput).toBeTruthy()
    expect(
      wrapper
        .findAll('input[type="text"]')
        .find((i) => (i.element as HTMLInputElement).value === 'whisper-large-v3-turbo'),
    ).toBeTruthy()

    // Custom leaves the fields as-is (keeps the Groq values above).
    await presetSelect.setValue('custom')
    expect(
      wrapper
        .findAll('input[type="text"]')
        .find((i) => (i.element as HTMLInputElement).value === 'https://api.groq.com/openai/v1'),
    ).toBeTruthy()
    wrapper.unmount()
  })

  it('saves a mode switch through PUT with the cloud fields; blank key sends "" (keep)', async () => {
    const wrapper = await mountView()
    await wrapper.find('input[type="radio"][value="cloud"]').setValue(true)
    const cloudKeyInput = wrapper.findAll('input[type="password"]')[1]
    await cloudKeyInput.setValue('sk-cloud-new')

    const saveBtn = wrapper.findAll('button').find((b) => b.text().includes('保存设置'))
    await saveBtn!.trigger('click')
    await flushPromises()

    expect(mocked.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({
        asr: {
          mode: 'cloud',
          idle_unload_min: 10,
          cloud_base_url: 'https://api.groq.com/openai/v1',
          cloud_model: 'whisper-large-v3-turbo',
          cloud_api_key: 'sk-cloud-new',
        },
      }),
    )
    expect(mocked.asrStatus).toHaveBeenCalled()
    // Typed key is cleared after it is stored.
    expect((cloudKeyInput.element as HTMLInputElement).value).toBe('')

    // An empty key field sends "" which the backend reads as "keep stored".
    await saveBtn!.trigger('click')
    await flushPromises()
    const secondCall = mocked.updateSettings.mock.calls[1][0]
    expect(secondCall.asr).toMatchObject({ mode: 'cloud', cloud_api_key: '' })
    wrapper.unmount()
  })

  it('masks the stored cloud key in the key field placeholder', async () => {
    mocked.getSettings.mockResolvedValue(cloudSettings)
    const wrapper = await mountView()

    expect((wrapper.find('input[type="radio"][value="cloud"]').element as HTMLInputElement).checked).toBe(true)
    const cloudKeyInput = wrapper.findAll('input[type="password"]')[1]
    expect(cloudKeyInput.attributes('placeholder')).toContain('abcd****wxyz')
    wrapper.unmount()
  })

  it('tests the cloud engine with unsaved form values and shows the message verbatim', async () => {
    mocked.testCloudAsr.mockResolvedValue({ ok: true, message: '云端连接正常，可用模型 2 个' })
    const wrapper = await mountView()
    await wrapper.find('input[type="radio"][value="cloud"]').setValue(true)
    const cloudKeyInput = wrapper.findAll('input[type="password"]')[1]
    await cloudKeyInput.setValue('sk-typed-in-form')

    const testBtn = wrapper.findAll('button').find((b) => b.text().includes('测试连接'))
    await testBtn!.trigger('click')
    await flushPromises()

    expect(mocked.testCloudAsr).toHaveBeenCalledWith({
      cloud_base_url: 'https://api.groq.com/openai/v1',
      cloud_model: 'whisper-large-v3-turbo',
      cloud_api_key: 'sk-typed-in-form',
    })
    expect(wrapper.text()).toContain('云端连接正常，可用模型 2 个')
    wrapper.unmount()
  })

  it('shows the cloud test failure message verbatim too', async () => {
    mocked.testCloudAsr.mockResolvedValue({ ok: false, message: '密钥无效（401）' })
    const wrapper = await mountView()
    await wrapper.find('input[type="radio"][value="cloud"]').setValue(true)

    const testBtn = wrapper.findAll('button').find((b) => b.text().includes('测试连接'))
    await testBtn!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('密钥无效（401）')
    const { toast } = await import('../router')
    expect(toast.value?.kind).toBe('error')
    expect(toast.value?.text).toContain('密钥无效（401）')
    wrapper.unmount()
  })

  it('toasts a failed save (e.g. busy engine 409 on mode switch) without losing the form', async () => {
    mocked.updateSettings.mockRejectedValue(new Error('引擎忙，稍后再试'))
    const wrapper = await mountView()
    await wrapper.find('input[type="radio"][value="cloud"]').setValue(true)

    const saveBtn = wrapper.findAll('button').find((b) => b.text().includes('保存设置'))
    await saveBtn!.trigger('click')
    await flushPromises()

    const { toast } = await import('../router')
    expect(toast.value?.kind).toBe('error')
    expect(toast.value?.text).toContain('引擎忙，稍后再试')
    // The chosen mode stays in the form so the user can retry.
    expect((wrapper.find('input[type="radio"][value="cloud"]').element as HTMLInputElement).checked).toBe(true)
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

  it('renders the prompts card grouped by category with variables and badges', async () => {
    const wrapper = await mountView()
    const text = wrapper.text()

    // Card title + the cache-invalidation hint at the top.
    expect(text).toContain('提示词')
    expect(text).toContain('LLM 缓存失效')

    // Entries render with their localized titles, grouped by category.
    expect(text).toContain('系统提示 · 中文')
    expect(text).toContain('题型规则')

    // Read-only variable print + the customized badge.
    expect(text).toContain('{{transcript}} {{candidates}}')
    expect(text).toContain('{{instruction}}')
    expect(text).toContain('已自定义')

    // The textarea shows the current text, not the default.
    const ta = wrapper
      .findAll('textarea')
      .find((x) => (x.element as HTMLTextAreaElement).value.includes('My custom rules'))
    expect(ta).toBeTruthy()
    wrapper.unmount()
  })

  it('saves an edited prompt with the textarea content', async () => {
    const wrapper = await mountView()
    const entry = wrapper
      .findAll('.prompt-entry')
      .find(
        (e) =>
          (e.find('textarea').element as HTMLTextAreaElement).value.includes(
            'My custom rules',
          ),
      )
    expect(entry).toBeTruthy()

    await entry!.find('textarea').setValue('Rewritten rules {{instruction}}')
    const saveBtn = entry!.findAll('button').find((b) => b.text() === '保存')
    await saveBtn!.trigger('click')
    await flushPromises()

    expect(mocked.putPrompt).toHaveBeenCalledWith(
      'exam.rules.form_completion.en',
      'Rewritten rules {{instruction}}',
    )
    wrapper.unmount()
  })

  it('resets a prompt by sending an empty string', async () => {
    const wrapper = await mountView()
    const entry = wrapper
      .findAll('.prompt-entry')
      .find((e) => e.text().includes('Rules · Form completion'))
    expect(entry).toBeTruthy()

    const resetBtn = entry!.findAll('button').find((b) => b.text().includes('恢复默认'))
    await resetBtn!.trigger('click')
    await flushPromises()

    expect(mocked.putPrompt).toHaveBeenCalledWith('exam.rules.form_completion.en', '')
    wrapper.unmount()
  })

  it('clears the LLM cache and toasts the deleted count', async () => {
    const wrapper = await mountView()
    const btn = wrapper.findAll('button').find((b) => b.text().includes('清空 LLM 缓存'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    expect(mocked.clearLlmCache).toHaveBeenCalledTimes(1)
    const { toast } = await import('../router')
    expect(toast.value?.text).toContain('3')
    wrapper.unmount()
  })
})
