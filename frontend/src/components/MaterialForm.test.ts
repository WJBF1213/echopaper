import { describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import MaterialForm from './MaterialForm.vue'
import { setLocale } from '../i18n'

async function pickFile(wrapper: VueWrapper, name: string) {
  const input = wrapper.find('input[type="file"]').element as HTMLInputElement
  const file = new File(['x'], name, { type: 'audio/mpeg' })
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await wrapper.find('input[type="file"]').trigger('change')
}

describe('MaterialForm file picker', () => {
  it('keeps the native input in the DOM but hidden', () => {
    const wrapper = mount(MaterialForm)
    const input = wrapper.find('input[type="file"]')
    expect(input.exists()).toBe(true)
    // hidden (display:none) kills the browser-painted Chinese caption and
    // removes the input from the tab order; our button is the focusable one.
    expect(input.attributes('hidden')).toBeDefined()
    wrapper.unmount()
  })

  it('shows a translated button instead of the native caption', () => {
    const wrapper = mount(MaterialForm)
    expect(wrapper.find('button.pick').text()).toBe('音频文件')
    wrapper.unmount()
  })

  it('opens the picker via the hidden input when the button is clicked', async () => {
    const wrapper = mount(MaterialForm)
    const input = wrapper.find('input[type="file"]').element as HTMLInputElement
    const click = vi.spyOn(input, 'click').mockImplementation(() => {})
    await wrapper.find('button.pick').trigger('click')
    // Exactly once: the label must not forward a second activation.
    expect(click).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('renders the chosen file name and a change label in our own UI', async () => {
    const wrapper = mount(MaterialForm)
    await pickFile(wrapper, 'cam18-test1.mp3')
    expect(wrapper.find('.fname').text()).toBe('cam18-test1.mp3')
    expect(wrapper.find('button.pick').text()).toBe('更换音频')
    wrapper.unmount()
  })

  it('labels the button in English once the locale switches', async () => {
    setLocale('en')
    const wrapper = mount(MaterialForm)
    expect(wrapper.find('button.pick').text()).toBe('Audio file')
    await pickFile(wrapper, 'cam18-test1.mp3')
    expect(wrapper.find('button.pick').text()).toBe('Change audio')
    expect(wrapper.find('.fname').text()).toBe('cam18-test1.mp3')
    wrapper.unmount()
  })
})
