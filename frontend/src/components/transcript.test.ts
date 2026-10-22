import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TranscriptView from './TranscriptView.vue'

const words = 'The museum opens at nine'.split(' ').map((w, i) => ({
  w,
  s: i * 0.5,
  e: i * 0.5 + 0.4,
}))

describe('TranscriptView', () => {
  it('keeps a space between words', () => {
    const wrapper = mount(TranscriptView, {
      props: { words, sentences: [[0, 4]] as [number, number][] },
    })
    const text = wrapper.find('.transcript').text()
    expect(text.replace(/\s+/g, ' ').trim()).toBe('The museum opens at nine')
    wrapper.unmount()
  })

  it('separates words across multiple sentences', () => {
    const wrapper = mount(TranscriptView, {
      props: { words, sentences: [[0, 2], [3, 4]] as [number, number][] },
    })
    const sentences = wrapper.findAll('.sent')
    expect(sentences).toHaveLength(2)
    expect(sentences[0].text().trim()).toBe('The museum opens')
    expect(sentences[1].text().trim()).toBe('at nine')
    wrapper.unmount()
  })

  it('does not add a trailing space on the last word of a sentence', () => {
    const wrapper = mount(TranscriptView, {
      props: { words, sentences: [[0, 4]] as [number, number][] },
    })
    const spans = wrapper.findAll('.word')
    expect(spans).toHaveLength(5)
    // The text node after the last span must be empty.
    expect(wrapper.find('.sent').element.textContent).toBe('The museum opens at nine')
    wrapper.unmount()
  })

  it('falls back to the plain text when there are no words', () => {
    const wrapper = mount(TranscriptView, {
      props: { words: [], sentences: [], text: 'plain transcript' },
    })
    expect(wrapper.text()).toContain('plain transcript')
    wrapper.unmount()
  })

  it('marks the active word only when timed', () => {
    const timed = mount(TranscriptView, {
      props: { words, sentences: [[0, 4]], timed: true, current: 0.6 },
    })
    expect(timed.findAll('.word.active')).toHaveLength(1)
    timed.unmount()

    const untimed = mount(TranscriptView, {
      props: { words, sentences: [[0, 4]], timed: false, current: 0.6 },
    })
    expect(untimed.findAll('.word.active')).toHaveLength(0)
    untimed.unmount()
  })

  it('emits the word index when a timed word is clicked', async () => {
    const wrapper = mount(TranscriptView, {
      props: { words, sentences: [[0, 4]], timed: true },
    })
    await wrapper.findAll('.word')[2].trigger('click')
    expect(wrapper.emitted('seekWord')?.[0]).toEqual([2])
    wrapper.unmount()
  })
})
