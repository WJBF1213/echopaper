import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import JobProgress from './JobProgress.vue'
import type { Job } from '../api'
import { setLocale } from '../i18n'

function job(overrides: Partial<Job>): Job {
  return {
    id: 'j1',
    state: 'translating',
    message: null,
    percent: 42,
    material_id: null,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

describe('JobProgress stage labels', () => {
  it('labels the translating stage (zh)', () => {
    const wrapper = mount(JobProgress, { props: { job: job({}) } })
    // The T20 crowd-warning: a missing mapping falls through to 准备中.
    expect(wrapper.text()).toContain('转译中')
    expect(wrapper.text()).not.toContain('准备中')
    wrapper.unmount()
  })

  it('labels the translating stage (en)', () => {
    setLocale('en')
    const wrapper = mount(JobProgress, { props: { job: job({}) } })
    expect(wrapper.text()).toContain('Translating')
    wrapper.unmount()
    setLocale('zh')
  })

  it('maps every remaining pipeline stage', () => {
    for (const state of ['queued', 'downloading', 'transcribing', 'done', 'error'] as const) {
      const wrapper = mount(JobProgress, { props: { job: job({ state }) } })
      expect(wrapper.text()).not.toContain('准备中')
      wrapper.unmount()
    }
  })
})
