import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import PaperView from './PaperView.vue'
import { api } from '../api'

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    api: {
      getMaterial: vi.fn(),
      examTypes: vi.fn(),
      generateExam: vi.fn(),
      audioUrl: vi.fn(() => '/api/materials/m1/audio'),
    },
  }
})

const mocked = vi.mocked(api)

const material = {
  id: 'm1',
  name: 'Cambridge 18 Test 1',
  source_type: 'upload',
  audio_url: null,
  duration_s: 420,
  has_audio: true,
  transcript: 'The job title is administrative assistant.',
  transcript_source: 'asr',
  asr_model: 'parakeet',
  words: [],
  sentences: [] as [number, number][],
  sets: [],
  created_at: '2026-10-21T10:00:00Z',
  updated_at: '2026-10-21T10:00:00Z',
}

const examTypes = {
  types: [
    {
      key: 'form_completion',
      label: '表单填空',
      parts: [1],
      answer_kind: 'span',
      needs_visual: false,
      word_limit: 'NO MORE THAN TWO WORDS AND/OR A NUMBER',
      instruction: 'Complete the form below.',
    },
    {
      key: 'mcq_single',
      label: '单选题',
      parts: [2, 3],
      answer_kind: 'option',
      needs_visual: false,
      word_limit: null,
      instruction: 'Choose the correct letter, A, B or C.',
    },
    {
      key: 'mcq_multi',
      label: '多选题（选两项）',
      parts: [3],
      answer_kind: 'option_multi',
      needs_visual: false,
      word_limit: null,
      instruction: 'Choose TWO letters, A-E.',
    },
    {
      key: 'matching',
      label: '匹配题',
      parts: [2, 3],
      answer_kind: 'matching',
      needs_visual: false,
      word_limit: null,
      instruction: 'Match each item with the correct option, A-F.',
    },
  ],
  presets: [
    {
      key: 'p1_form',
      part: 1,
      label: 'Part 1 · 表单填空（10 题）',
      total_items: 6,
      groups: [{ type: 'form_completion', count: 2 }],
    },
    {
      key: 'p2_mcq_matching',
      part: 2,
      label: 'Part 2 · 单选 + 匹配（5+5）',
      total_items: 10,
      groups: [
        { type: 'mcq_single', count: 5 },
        { type: 'matching', count: 5 },
      ],
    },
  ],
}

const matchOptions = [
  'A. to reduce traffic',
  'B. to improve safety',
  'C. to create jobs',
  'D. to save money',
]

const paper = {
  material_id: 'm1',
  part: 1,
  preset: 'p1_form',
  total_items: 6,
  warnings: ['规则补题 1 道（LLM 未凑满）', '丢弃与上一题过近的题目（2 词 < 3）'],
  available_presets: [
    {
      key: 'p1_form',
      part: 1,
      label: 'Part 1 · 表单填空（10 题）',
      total_items: 6,
      groups: [{ type: 'form_completion', count: 2 }],
    },
  ],
  groups: [
    {
      type: 'form_completion',
      title: 'Job Application Form',
      instruction:
        'Complete the form below. Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.',
      options: [],
      items: [
        {
          number: 1,
          type: 'form_completion',
          stem: 'Job title: ______',
          answer: 'administrative assistant',
          options: [],
          evidence: [
            {
              i0: 10,
              i1: 11,
              quote: 'administrative assistant',
              t_start: 12.5,
              t_end: 13.8,
            },
          ],
          word_limit: 'NO MORE THAN TWO WORDS AND/OR A NUMBER',
          label: 'Position',
          alternatives: ['admin assistant'],
          group_title: 'Job Application Form',
        },
        {
          number: 2,
          type: 'form_completion',
          stem: 'Deposit: ______',
          answer: 'two hundred pounds',
          options: [],
          evidence: [
            { i0: 20, i1: 22, quote: 'two hundred pounds', t_start: 30.1, t_end: 31.5 },
          ],
          word_limit: 'NO MORE THAN TWO WORDS AND/OR A NUMBER',
          label: 'Deposit',
          alternatives: [],
          group_title: 'Job Application Form',
        },
      ],
    },
    {
      type: 'mcq_single',
      title: 'Multiple choice',
      instruction: 'Choose the correct letter, A, B or C.',
      options: [],
      items: [
        {
          number: 3,
          type: 'mcq_single',
          stem: 'What does the speaker recommend?',
          answer: 'B',
          options: ['Take the bus', 'Ride a bike', 'Walk'],
          evidence: [
            { i0: 40, i1: 42, quote: 'ride a bike', t_start: 55.0, t_end: 56.2 },
          ],
          word_limit: null,
          label: '',
          alternatives: [],
          group_title: 'Multiple choice',
        },
      ],
    },
    {
      type: 'matching',
      title: 'Why is each change made?',
      instruction: 'Match each item with the correct option, A-F.',
      options: matchOptions,
      items: [
        {
          number: 4,
          type: 'matching',
          stem: 'City centre',
          answer: 'A',
          options: matchOptions,
          evidence: [
            { i0: 60, i1: 62, quote: 'reduce traffic', t_start: 70.0, t_end: 71.0 },
          ],
          word_limit: null,
          label: '',
          alternatives: [],
          group_title: 'Why is each change made?',
        },
        {
          number: 5,
          type: 'matching',
          stem: 'Riverside',
          answer: 'C',
          options: matchOptions,
          evidence: [
            { i0: 70, i1: 72, quote: 'create jobs', t_start: 80.0, t_end: 81.0 },
          ],
          word_limit: null,
          label: '',
          alternatives: [],
          group_title: 'Why is each change made?',
        },
      ],
    },
    {
      type: 'mcq_multi',
      title: 'Multiple choice (two answers)',
      instruction: 'Choose TWO letters, A-E.',
      options: [],
      items: [
        {
          number: 6,
          type: 'mcq_multi',
          stem: 'Which TWO benefits are mentioned?',
          answer: 'A,C',
          options: [
            'Lower cost',
            'Longer hours',
            'Less noise',
            'More staff',
            'Free parking',
          ],
          evidence: [
            { i0: 80, i1: 82, quote: 'lower cost', t_start: 90.0, t_end: 91.0 },
            { i0: 85, i1: 86, quote: 'less noise', t_start: 92.0, t_end: 93.0 },
          ],
          word_limit: null,
          label: '',
          alternatives: [],
          group_title: 'Multiple choice (two answers)',
        },
      ],
    },
  ],
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/paper/:materialId', component: PaperView },
      { path: '/material/:materialId', component: { template: '<div />' } },
    ],
  })
  await router.push('/paper/m1')
  await router.isReady()
  const wrapper = mount(PaperView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

async function generatePaper(wrapper: Awaited<ReturnType<typeof mountView>>) {
  const button = wrapper.findAll('button').find((b) => b.text().includes('生成整卷'))
  expect(button).toBeTruthy()
  await button!.trigger('click')
  await flushPromises()
}

describe('PaperView', () => {
  beforeEach(() => {
    mocked.getMaterial.mockResolvedValue(material)
    mocked.examTypes.mockResolvedValue(examTypes)
    mocked.generateExam.mockResolvedValue(paper)
  })

  it('renders completion items with one input per blank', async () => {
    const wrapper = await mountView()
    await generatePaper(wrapper)

    expect(mocked.generateExam).toHaveBeenCalledWith('m1', 1, 'p1_form')
    const inputs = wrapper.findAll('input.blank-input')
    expect(inputs).toHaveLength(2)
    expect(wrapper.text()).toContain('Job title:')
    expect(wrapper.text()).toContain('Position')
    expect(wrapper.text()).toContain('Job Application Form')
    wrapper.unmount()
  })

  it('grades locally and shows the score', async () => {
    const wrapper = await mountView()
    await generatePaper(wrapper)

    const inputs = wrapper.findAll('input.blank-input')
    // Case and repeated spaces are normalised.
    await inputs[0].setValue('  Administrative   Assistant ')
    await inputs[1].setValue('one hundred pounds')

    const optionButtons = wrapper.findAll('.mcq-options .option-btn')
    // Items 3 (A-C) then 6 (A-E); item 3 expects B.
    await optionButtons[1].trigger('click')
    // Item 6 expects A,C.
    await optionButtons[3].trigger('click')
    await optionButtons[5].trigger('click')

    const submit = wrapper.findAll('button').find((b) => b.text().includes('交卷'))
    await submit!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.score-summary').text()).toContain('得分 3/6')
    expect(wrapper.findAll('.paper-item.ok')).toHaveLength(3)
    expect(wrapper.findAll('.paper-item.bad')).toHaveLength(3)
    const keys = wrapper.findAll('.answer-key').map((node) => node.text())
    expect(keys.some((text) => text.includes('two hundred pounds'))).toBe(true)
    expect(keys.some((text) => text.includes('C'))).toBe(true)
    wrapper.unmount()
  })

  it('renders MCQ options and the matching option pool once', async () => {
    const wrapper = await mountView()
    await generatePaper(wrapper)

    expect(wrapper.findAll('.mcq-options')).toHaveLength(2)
    expect(wrapper.findAll('.mcq-options .option-btn')).toHaveLength(8)
    expect(wrapper.findAll('.match-options')).toHaveLength(1)
    expect(wrapper.findAll('.match-options .match-option')).toHaveLength(4)
    expect(wrapper.findAll('.match-buttons')).toHaveLength(2)
    expect(wrapper.findAll('.match-buttons .match-btn')[0].text()).toBe('A')
    wrapper.unmount()
  })

  it('shows generator warnings in a collapsible list', async () => {
    const wrapper = await mountView()
    await generatePaper(wrapper)

    const details = wrapper.find('details.warnings')
    expect(details.exists()).toBe(true)
    expect(details.find('summary').text()).toContain('生成提示（2）')
    expect(details.text()).toContain('规则补题 1 道')
    expect(details.text()).toContain('丢弃与上一题过近的题目')
    wrapper.unmount()
  })
})
