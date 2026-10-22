import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent } from 'vue'
import PaperView from './PaperView.vue'
import { api, ApiError } from '../api'
import type { ExamPaper, ExamTypes } from '../api'

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

// The view wires slot clicks through the real MapScene; stub it with a
// marker component so the view test stays at the interaction level.
vi.mock('../components/MapScene.vue', () => ({
  default: defineComponent({
    name: 'MapScene',
    props: {
      scene: { type: Object, required: true },
      answers: { type: Object, default: null },
    },
    emits: ['select'],
    template:
      '<div class="mapscene-stub" :data-slots="scene.nodes.length" ' +
      ':data-answers="JSON.stringify(answers ?? {})" />',
  }),
}))

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

const examTypes: ExamTypes = {
  types: [
    {
      key: 'mcq_single',
      name: '单选题',
      name_zh: '单选题',
      name_en: 'Multiple choice (single answer)',
      answer_kind: 'option',
      layouts: [],
      generates_visual: false,
      max_count: 10,
      min_words: 120,
    },
    {
      key: 'mcq_multi',
      name: '多选题（选两项）',
      name_zh: '多选题（选两项）',
      name_en: 'Multiple choice (two answers)',
      answer_kind: 'option_multi',
      layouts: [],
      generates_visual: false,
      max_count: 10,
      min_words: 200,
    },
    {
      key: 'matching',
      name: '匹配题',
      name_zh: '匹配题',
      name_en: 'Matching',
      answer_kind: 'matching',
      layouts: [],
      generates_visual: false,
      max_count: 10,
      min_words: 150,
    },
    {
      key: 'completion',
      name: '填空题',
      name_zh: '填空题',
      name_en: 'Completion',
      answer_kind: 'span',
      layouts: ['form', 'table', 'notes', 'sentence', 'summary', 'flowchart'],
      generates_visual: false,
      max_count: 10,
      min_words: 80,
    },
    {
      key: 'short_answer',
      name: '简答题',
      name_zh: '简答题',
      name_en: 'Short answer',
      answer_kind: 'span',
      layouts: [],
      generates_visual: false,
      max_count: 10,
      min_words: 80,
    },
    {
      key: 'map_labelling',
      name: '地图标注',
      name_zh: '地图标注',
      name_en: 'Map labelling',
      answer_kind: 'matching',
      layouts: [],
      generates_visual: true,
      max_count: 10,
      min_words: 200,
    },
  ],
}

function evidence(i0: number, i1: number, quote: string, t0 = 10, t1 = 11) {
  return [{ i0, i1, quote, t_start: t0, t_end: t1 }]
}

function spanItem(number: number, stem: string, answer: string, layout: string | null, label = '') {
  return {
    number,
    type: 'completion',
    stem,
    answer,
    options: [],
    evidence: evidence(number, number + 1, answer),
    word_limit: 'NO MORE THAN TWO WORDS AND/OR A NUMBER',
    layout,
    label,
    alternatives: [],
    group_title: 'Application form',
    answer_text: '',
  }
}

const matchOptions = [
  'A. to reduce traffic',
  'B. to improve safety',
  'C. to create jobs',
  'D. to save money',
]

const mapScene = {
  canvas: { width: 100, height: 70 },
  nodes: [
    { id: 'entrance', label: 'Entrance', x: 50, y: 60, shape: 'rect', fixed: true },
    { id: 'n1', x: 20, y: 25, shape: 'circle', blank_slot: 1 },
    { id: 'n2', x: 62, y: 30, shape: 'rect', blank_slot: 2 },
  ],
  paths: [],
}

/** One paper exercising every renderer: completion + mcq + matching + map. */
function makePaper(): ExamPaper {
  return {
    material_id: 'm1',
    total_items: 7,
    warnings: ['规则补题 1 道（LLM 未凑满）'],
    groups: [
      {
        type: 'completion',
        title: 'Job Application Form',
        instruction: 'Complete the form below. Write ONE WORD AND/OR A NUMBER for each answer.',
        options: [],
        partial: false,
        visual: null,
        items: [
          {
            ...spanItem(1, 'Job title: ______', 'assistant', 'form', 'Position'),
          },
          {
            ...spanItem(2, 'Deposit: ______', 'two hundred pounds', 'form', 'Fee'),
          },
        ],
      },
      {
        type: 'mcq_single',
        title: 'Multiple choice',
        instruction: 'Choose the correct letter, A, B or C.',
        options: [],
        partial: false,
        visual: null,
        items: [
          {
            number: 3,
            type: 'mcq_single',
            stem: 'What does the speaker recommend?',
            answer: 'B',
            options: ['Take the bus', 'Ride a bike', 'Walk'],
            evidence: evidence(40, 42, 'ride a bike'),
            word_limit: null,
            layout: null,
            label: '',
            alternatives: [],
            group_title: 'Multiple choice',
            answer_text: '',
          },
        ],
      },
      {
        type: 'matching',
        title: 'Why is each change made?',
        instruction: 'Match each item with the correct option, A-F.',
        options: matchOptions,
        partial: false,
        visual: null,
        items: [
          {
            number: 4,
            type: 'matching',
            stem: 'City centre',
            answer: 'A',
            options: matchOptions,
            evidence: evidence(60, 62, 'reduce traffic'),
            word_limit: null,
            layout: null,
            label: '',
            alternatives: [],
            group_title: 'Why is each change made?',
            answer_text: 'to reduce traffic',
          },
          {
            number: 5,
            type: 'matching',
            stem: 'Riverside',
            answer: 'C',
            options: matchOptions,
            evidence: evidence(70, 72, 'create jobs'),
            word_limit: null,
            layout: null,
            label: '',
            alternatives: [],
            group_title: 'Why is each change made?',
            answer_text: 'to create jobs',
          },
        ],
      },
      {
        type: 'map_labelling',
        title: 'Visitor centre map',
        instruction: 'Label the map. Choose your answers from the options (A-F).',
        options: ['A. Entrance', 'B. Gift Shop', 'C. Ticket Desk', 'D. Cafe'],
        partial: false,
        visual: { kind: 'map', scene: mapScene },
        items: [
          {
            number: 6,
            type: 'map_labelling',
            stem: 'What is at blank slot 1?',
            answer: 'B',
            options: ['A. Entrance', 'B. Gift Shop', 'C. Ticket Desk', 'D. Cafe'],
            evidence: evidence(80, 82, 'gift shop'),
            word_limit: null,
            layout: null,
            label: '',
            alternatives: [],
            group_title: 'Visitor centre map',
            answer_text: 'Gift Shop',
          },
          {
            number: 7,
            type: 'map_labelling',
            stem: 'What is at blank slot 2?',
            answer: 'C',
            options: ['A. Entrance', 'B. Gift Shop', 'C. Ticket Desk', 'D. Cafe'],
            evidence: evidence(85, 86, 'ticket desk'),
            word_limit: null,
            layout: null,
            label: '',
            alternatives: [],
            group_title: 'Visitor centre map',
            answer_text: 'Ticket Desk',
          },
        ],
      },
    ],
  }
}

/** Completion-only paper with one item per layout (design §4.1 layouts). */
function makeLayoutPaper(): ExamPaper {
  return {
    material_id: 'm1',
    total_items: 6,
    warnings: [],
    groups: [
      {
        type: 'completion',
        title: 'Mixed completion',
        instruction: 'Complete the notes below.',
        options: [],
        partial: true,
        visual: null,
        items: [
          spanItem(1, 'Name: ______', 'Anna', 'form', 'Name'),
          spanItem(2, 'Fee: ______', '20', 'table', 'Fee'),
          spanItem(3, 'The tour starts at the ______.', 'gate', 'notes'),
          spanItem(4, 'Seats are limited to ______ people.', 'fifty', 'sentence'),
          spanItem(5, 'The centre opened in ______ and expanded twice.', '1998', 'summary'),
          spanItem(6, 'Register at the ______ desk first.', 'arrival', 'flowchart'),
        ],
      },
    ],
  }
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

async function selectType(wrapper: Awaited<ReturnType<typeof mountView>>, name: string) {
  const chip = wrapper.findAll('.type-chip').find((c) => c.text().includes(name))
  expect(chip, `chip ${name}`).toBeTruthy()
  await chip!.trigger('click')
}

describe('PaperView selector', () => {
  beforeEach(() => {
    mocked.getMaterial.mockResolvedValue(material)
    mocked.examTypes.mockResolvedValue(examTypes)
    mocked.generateExam.mockResolvedValue({ paper: makePaper(), skipped: [] })
  })

  it('builds blocks from chips in click order, clamping counts to max_count', async () => {
    const wrapper = await mountView()

    // Six registry chips with localized names, no Part/preset dropdowns.
    const chips = wrapper.findAll('.type-chip')
    expect(chips).toHaveLength(6)
    expect(wrapper.text()).toContain('单选题')
    expect(wrapper.text()).toContain('地图标注')
    // No Part dropdown and no preset dropdown (design §六).
    expect(wrapper.find('select[aria-label="Part"]').exists()).toBe(false)
    expect(wrapper.find('select[aria-label="试卷类型"]').exists()).toBe(false)

    await selectType(wrapper, '地图标注')
    await selectType(wrapper, '单选题')

    // Count input clamps to the type's max_count (10).
    const countInput = wrapper.find('input.count-input')
    expect(countInput.exists()).toBe(true)
    await countInput.setValue(99)
    await countInput.trigger('change')

    await generatePaper(wrapper)
    // Blocks keep click order (zone order, design §4.4); no layout hint.
    expect(mocked.generateExam).toHaveBeenCalledWith(
      'm1',
      [
        { type: 'map_labelling', count: 5 },
        { type: 'mcq_single', count: 10 },
      ],
      { layoutHint: undefined, regenerate: false },
    )
    wrapper.unmount()
  })

  it('removes a block when its chip is toggled off', async () => {
    const wrapper = await mountView()
    await selectType(wrapper, '单选题')
    await selectType(wrapper, '匹配题')
    // Toggle 单选题 off again.
    await selectType(wrapper, '单选题')
    await generatePaper(wrapper)
    expect(mocked.generateExam).toHaveBeenCalledWith(
      'm1',
      [{ type: 'matching', count: 5 }],
      { layoutHint: undefined, regenerate: false },
    )
    wrapper.unmount()
  })

  it('includes layout_hint only when a completion layout is chosen', async () => {
    const wrapper = await mountView()
    await selectType(wrapper, '填空题')

    const select = wrapper.find('select.layout-select')
    expect(select.exists()).toBe(true)
    // "auto" (empty value) by default -> hint omitted.
    await generatePaper(wrapper)
    expect(mocked.generateExam).toHaveBeenLastCalledWith(
      'm1',
      [{ type: 'completion', count: 5 }],
      { layoutHint: undefined, regenerate: false },
    )

    await select.setValue('table')
    await generatePaper(wrapper)
    expect(mocked.generateExam).toHaveBeenLastCalledWith(
      'm1',
      [{ type: 'completion', count: 5 }],
      { layoutHint: 'table', regenerate: false },
    )
    wrapper.unmount()
  })
})

describe('PaperView results', () => {
  beforeEach(() => {
    mocked.getMaterial.mockResolvedValue(material)
    mocked.examTypes.mockResolvedValue(examTypes)
    mocked.generateExam.mockResolvedValue({ paper: makePaper(), skipped: [] })
  })

  it('renders completion items with one input per blank', async () => {
    const wrapper = await mountView()
    await selectType(wrapper, '填空题')
    await generatePaper(wrapper)

    expect(wrapper.findAll('input.blank-input')).toHaveLength(2)
    expect(wrapper.text()).toContain('Job title:')
    expect(wrapper.text()).toContain('Position')
    expect(wrapper.text()).toContain('Job Application Form')
    wrapper.unmount()
  })

  it('renders each completion layout with a distinct presenter', async () => {
    mocked.generateExam.mockResolvedValue({ paper: makeLayoutPaper(), skipped: [] })
    const wrapper = await mountView()
    await selectType(wrapper, '填空题')
    await generatePaper(wrapper)

    expect(wrapper.find('.layout-form').exists()).toBe(true)
    expect(wrapper.find('.layout-form .form-label').text()).toBe('Name')
    expect(wrapper.find('.layout-table table').exists()).toBe(true)
    expect(wrapper.find('.layout-notes ul').exists()).toBe(true)
    expect(wrapper.find('.layout-sentence').exists()).toBe(true)
    expect(wrapper.find('.layout-summary .summary-para').exists()).toBe(true)
    expect(wrapper.find('.layout-flowchart .flow-box').exists()).toBe(true)
    // One answer input per printed blank across all layouts.
    expect(wrapper.findAll('input.blank-input')).toHaveLength(6)

    // Answer keys render for EVERY layout after 显示答案 (notes/sentence/
    // flowchart included), once per item, with no duplicate inline keys.
    const reveal = wrapper.findAll('button').find((b) => b.text().includes('显示答案'))
    expect(reveal).toBeTruthy()
    await reveal!.trigger('click')
    const keys = wrapper.findAll('.layout-keys .answer-key')
    expect(keys.map((n) => n.text())).toEqual([
      '1. 答案：Anna',
      '2. 答案：20',
      '3. 答案：gate',
      '4. 答案：fifty',
      '5. 答案：1998',
      '6. 答案：arrival',
    ])
    expect(keys.every((n) => n.isVisible())).toBe(true)
    // The form presenter's old inline key is gone: each answer appears once.
    expect(wrapper.text().split('答案：Anna').length - 1).toBe(1)
    wrapper.unmount()
  })

  it('marks partial groups with the produced/requested badge', async () => {
    mocked.generateExam.mockResolvedValue({ paper: makeLayoutPaper(), skipped: [] })
    const wrapper = await mountView()
    await selectType(wrapper, '填空题')
    // Request more than the paper produced (6 of 10).
    const countInput = wrapper.find('input.count-input')
    await countInput.setValue(10)
    await countInput.trigger('change')
    await generatePaper(wrapper)

    const badge = wrapper.find('.partial-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('产出 6/10 题')
    wrapper.unmount()
  })

  it('renders MCQ options and the matching option pool once', async () => {
    const wrapper = await mountView()
    await selectType(wrapper, '单选题')
    await generatePaper(wrapper)

    expect(wrapper.findAll('.mcq-options')).toHaveLength(1)
    expect(wrapper.findAll('.mcq-options .option-btn')).toHaveLength(3)
    expect(wrapper.findAll('.match-options')).toHaveLength(2)
    expect(wrapper.findAll('.match-options .match-option')).toHaveLength(8)
    expect(wrapper.findAll('.match-buttons')).toHaveLength(4)
    wrapper.unmount()
  })

  it('grades locally and shows the score', async () => {
    const wrapper = await mountView()
    await selectType(wrapper, '单选题')
    await generatePaper(wrapper)

    const inputs = wrapper.findAll('input.blank-input')
    await inputs[0].setValue('Assistant')
    await inputs[1].setValue('two hundred pounds')

    const optionButtons = wrapper.findAll('.mcq-options .option-btn')
    await optionButtons[1].trigger('click') // item 3 expects B

    // Matching item 4 expects A.
    const matchGroups = wrapper.findAll('.match-buttons')
    const matchButtons4 = matchGroups[0].findAll('.match-btn')
    await matchButtons4[0].trigger('click')
    // Map item 6 expects B.
    const mapButtons6 = matchGroups[2].findAll('.match-btn')
    await mapButtons6[1].trigger('click')

    const submit = wrapper.findAll('button').find((b) => b.text().includes('交卷'))
    await submit!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.score-summary').text()).toContain('得分 5/7')
    expect(wrapper.findAll('.paper-item.ok')).toHaveLength(5)
    wrapper.unmount()
  })

  it('shows the skipped list with each refusal reason next to the paper', async () => {
    mocked.generateExam.mockResolvedValue({
      paper: makePaper(),
      skipped: [{ type: 'map_labelling', reason: '转写无空间方位描述' }],
    })
    const wrapper = await mountView()
    await selectType(wrapper, '单选题')
    await generatePaper(wrapper)

    const skipped = wrapper.find('.skipped-list')
    expect(skipped.exists()).toBe(true)
    expect(skipped.text()).toContain('已跳过：地图标注 — 转写无空间方位描述')
    // The paper still renders alongside the partial refusal.
    expect(wrapper.findAll('.paper-group').length).toBeGreaterThan(0)
    wrapper.unmount()
  })

  it('shows every reason and no paper when all blocks are refused (400)', async () => {
    const error = new ApiError(400, '生成失败')
    ;(error as unknown as { data: unknown }).data = {
      skipped: [
        { type: 'map_labelling', reason: '转写无空间方位描述' },
        { type: 'matching', reason: '缺少可匹配的特征点' },
      ],
    }
    mocked.generateExam.mockRejectedValue(error)

    const wrapper = await mountView()
    await selectType(wrapper, '地图标注')
    await generatePaper(wrapper)

    expect(wrapper.text()).toContain('生成失败')
    const skipped = wrapper.find('.skipped-list')
    expect(skipped.exists()).toBe(true)
    expect(skipped.text()).toContain('已跳过：地图标注 — 转写无空间方位描述')
    expect(skipped.text()).toContain('已跳过：匹配题 — 缺少可匹配的特征点')
    expect(wrapper.find('.paper-group').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows generator warnings in a collapsible list', async () => {
    const wrapper = await mountView()
    await selectType(wrapper, '单选题')
    await generatePaper(wrapper)

    const details = wrapper.find('details.warnings')
    expect(details.exists()).toBe(true)
    expect(details.find('summary').text()).toContain('生成提示（1）')
    expect(details.text()).toContain('规则补题 1 道')
    wrapper.unmount()
  })
})

describe('PaperView map group', () => {
  beforeEach(() => {
    mocked.getMaterial.mockResolvedValue(material)
    mocked.examTypes.mockResolvedValue(examTypes)
    mocked.generateExam.mockResolvedValue({ paper: makePaper(), skipped: [] })
  })

  it('renders the scene via MapScene with slot answers wired from item choices', async () => {
    const wrapper = await mountView()
    await selectType(wrapper, '地图标注')
    await generatePaper(wrapper)

    const stub = wrapper.find('.mapscene-stub')
    expect(stub.exists()).toBe(true)
    expect(stub.attributes('data-slots')).toBe('3')
    expect(stub.attributes('data-answers')).toBe('{}')

    // Answer item 6 (blank slot 1) with B -> the slot shows B on the map.
    const matchButtons6 = wrapper.findAll('.match-buttons')[2].findAll('.match-btn')
    await matchButtons6[1].trigger('click')
    expect(wrapper.find('.mapscene-stub').attributes('data-answers')).toBe('{"1":"B"}')
    wrapper.unmount()
  })

  it('routes a slot click on the map to the item asking about that slot', async () => {
    const wrapper = await mountView()
    await selectType(wrapper, '地图标注')
    await generatePaper(wrapper)

    const scene = wrapper.findComponent({ name: 'MapScene' })
    expect(scene.exists()).toBe(true)
    scene.vm.$emit('select', 2)
    await flushPromises()

    const active = wrapper.find('.paper-item.active')
    expect(active.exists()).toBe(true)
    expect(active.text()).toContain('blank slot 2')
    wrapper.unmount()
  })
})
