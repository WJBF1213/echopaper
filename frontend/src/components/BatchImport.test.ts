import { describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import BatchImport from './BatchImport.vue'
import { setLocale } from '../i18n'

async function pickFiles(wrapper: VueWrapper, names: string[]) {
  const input = wrapper.find('input[type="file"]').element as HTMLInputElement
  const files = names.map((n) => new File(['x'], n, { type: 'audio/mpeg' }))
  Object.defineProperty(input, 'files', { value: files, configurable: true })
  await wrapper.find('input[type="file"]').trigger('change')
}

describe('BatchImport file picker', () => {
  it('keeps the native input in the DOM but hidden', () => {
    const wrapper = mount(BatchImport)
    const input = wrapper.find('input[type="file"]')
    expect(input.exists()).toBe(true)
    // hidden (display:none) kills the browser-painted Chinese caption and
    // removes the input from the tab order; our button is the focusable one.
    expect(input.attributes('hidden')).toBeDefined()
    wrapper.unmount()
  })

  it('shows a translated button instead of the native caption', () => {
    const wrapper = mount(BatchImport)
    expect(wrapper.find('button.pick').text()).toBe('选择音频')
    wrapper.unmount()
  })

  it('opens the picker via the hidden input when the button is clicked', async () => {
    const wrapper = mount(BatchImport)
    const input = wrapper.find('input[type="file"]').element as HTMLInputElement
    const click = vi.spyOn(input, 'click').mockImplementation(() => {})
    await wrapper.find('button.pick').trigger('click')
    // Exactly once: the label must not forward a second activation.
    expect(click).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('lists the picked files in our own translated UI', async () => {
    const wrapper = mount(BatchImport)
    await pickFiles(wrapper, ['one.mp3', 'two.wav'])
    const names = wrapper.findAll('.filerow .fname').map((f) => f.text())
    expect(names).toEqual(['one.mp3', 'two.wav'])
    // Choosing again appends, so the button keeps its "choose" label.
    expect(wrapper.find('button.pick').text()).toBe('选择音频')
    wrapper.unmount()
  })

  it('labels the button in English once the locale switches', async () => {
    setLocale('en')
    const wrapper = mount(BatchImport)
    expect(wrapper.find('button.pick').text()).toBe('Choose audio')
    wrapper.unmount()
  })
})
