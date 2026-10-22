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
    engine: 'parakeet',
    parakeet_model: 'mlx-community/parakeet-tdt-0.6b-v3',
    whisper_model: 'mlx-community/whisper-large-v3-turbo',
    faster_whisper_model: 'large-v3-turbo',
    idle_unload_min: 10,
    available_engines: ['parakeet', 'whisper', 'faster_whisper'],
    default_engine: 'parakeet',
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
    mocked.updateSettings.mockResolvedValue({
      ...settings,
      asr: { ...settings.asr, engine: 'whisper' },
    })
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
