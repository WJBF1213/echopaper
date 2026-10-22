import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import BatchProgress from './BatchProgress.vue'
import type { BatchStatus, BatchJobItem } from '../api'

function job(overrides: Partial<BatchJobItem>): BatchJobItem {
  return {
    job_id: 'j',
    state: 'done',
    message: null,
    percent: 100,
    material_id: null,
    file_name: 'a.mp3',
    position: 0,
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

function batch(overrides: Partial<BatchStatus>): BatchStatus {
  return {
    id: 'b1',
    name: 'Batch',
    total: 2,
    done: 2,
    error: 0,
    running: 0,
    percent: 100,
    created_at: '',
    updated_at: '',
    jobs: [],
    ...overrides,
  }
}

describe('BatchProgress', () => {
  it('uses the ok tone when every file finished', () => {
    const wrapper = mount(BatchProgress, {
      props: { batch: batch({ jobs: [job({}), job({ job_id: 'j2' })] }) },
    })
    expect(wrapper.find('.progress').classes()).toContain('ok')
    expect(wrapper.text()).toContain('2/2 完成')
    wrapper.unmount()
  })

  it('never shows a full bar as success when everything failed', () => {
    const wrapper = mount(BatchProgress, {
      props: {
        batch: batch({
          done: 0,
          error: 2,
          jobs: [
            job({ job_id: 'j1', state: 'error', message: 'EngineError: boom' }),
            job({ job_id: 'j2', state: 'error', message: 'EngineError: boom' }),
          ],
        }),
      },
    })
    // 100% of the work was attempted, but the run failed: red, not green.
    expect(wrapper.find('.progress').classes()).toContain('bad')
    expect(wrapper.find('.progress').classes()).not.toContain('ok')
    expect(wrapper.text()).toContain('0/2 完成')
    expect(wrapper.text()).toContain('2 失败')
    wrapper.unmount()
  })

  it('uses a warning tone on a partial failure', () => {
    const wrapper = mount(BatchProgress, {
      props: {
        batch: batch({ done: 1, error: 1, percent: 100 }),
      },
    })
    expect(wrapper.find('.progress').classes()).toContain('warn')
    wrapper.unmount()
  })

  it('stays neutral while files are still running', () => {
    const wrapper = mount(BatchProgress, {
      props: { batch: batch({ done: 1, error: 0, running: 1, percent: 50 }) },
    })
    const classes = wrapper.find('.progress').classes()
    expect(classes).not.toContain('ok')
    expect(classes).not.toContain('bad')
    wrapper.unmount()
  })

  it('collapses a long error into a summary that can be expanded', () => {
    const message =
      "EngineError: parakeet 引擎加载失败：No module named 'parakeet_mlx'；请在设置页更换引擎或安装依赖"
    const wrapper = mount(BatchProgress, {
      props: {
        batch: batch({
          done: 0,
          error: 1,
          jobs: [job({ state: 'error', message })],
        }),
      },
    })
    const summary = wrapper.find('.err summary')
    expect(summary.text()).toContain('parakeet 引擎加载失败')
    // The remediation clause is not in the collapsed label.
    expect(summary.text()).not.toContain('请在设置页')
    // The full message is still available in the expanded body.
    expect(wrapper.find('.err p').text()).toBe(message)
    wrapper.unmount()
  })

  it('labels the translating stage instead of the raw state', () => {
    const wrapper = mount(BatchProgress, {
      props: {
        batch: batch({
          done: 0,
          error: 0,
          running: 1,
          percent: 35,
          jobs: [job({ job_id: 'j1', state: 'translating', percent: 35 })],
        }),
      },
    })
    // A missing mapping falls through to the raw state string.
    const chip = wrapper.find('.jobrow .chip').text()
    expect(chip).toContain('转译')
    expect(chip).not.toContain('translating')
    wrapper.unmount()
  })

  it('offers an open action only for finished files', () => {
    const wrapper = mount(BatchProgress, {
      props: {
        batch: batch({
          done: 1,
          error: 1,
          jobs: [
            job({ job_id: 'a', state: 'done', material_id: 'm1' }),
            job({ job_id: 'b', state: 'error', message: 'x' }),
          ],
        }),
      },
    })
    const buttons = wrapper.findAll('.jobrow button')
    expect(buttons).toHaveLength(1)
    expect(buttons[0].text()).toContain('打开材料')
    wrapper.unmount()
  })

  it('emits the material id when opening a finished file', async () => {
    const wrapper = mount(BatchProgress, {
      props: {
        batch: batch({ jobs: [job({ state: 'done', material_id: 'm9' })] }),
      },
    })
    await wrapper.find('.jobrow button').trigger('click')
    expect(wrapper.emitted('openMaterial')?.[0]).toEqual(['m9'])
    wrapper.unmount()
  })
})
