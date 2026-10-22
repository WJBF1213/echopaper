import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MapScene from './MapScene.vue'
import type { MapSceneData } from '../api'

/** Backend-normalized scene shape (exam_scene._validate_scene output). */
const scene: MapSceneData = {
  canvas: { width: 100, height: 70 },
  nodes: [
    { id: 'entrance', label: 'Entrance', x: 50, y: 60, shape: 'rect', fixed: true },
    { id: 'carpark', label: 'Car Park', x: 15, y: 50, shape: 'circle', fixed: true },
    { id: 'n1', x: 20, y: 25, shape: 'circle', blank_slot: 1 },
    { id: 'n2', x: 62, y: 30, shape: 'rect', blank_slot: 2 },
  ],
  paths: [
    { from: 'entrance', to: 'n1', label: 'Main Path' },
    { from: 'carpark', to: 'entrance', label: '' },
  ],
}

function slotNodes(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('g.map-slot')
}

describe('MapScene', () => {
  it('renders the scene as SVG: fixed rect/circle nodes with labels, labelled paths', () => {
    const wrapper = mount(MapScene, { props: { scene } })
    const svg = wrapper.find('svg.map-scene')
    expect(svg.exists()).toBe(true)
    expect(svg.attributes('viewBox')).toBe('0 0 100 70')

    // Fixed nodes: one rect + one circle, each with its printed label.
    const fixed = wrapper.findAll('g.map-node')
    expect(fixed).toHaveLength(2)
    expect(fixed[0].find('rect').exists()).toBe(true)
    expect(fixed[1].find('circle').exists()).toBe(true)
    const labels = wrapper.findAll('text.map-node-label').map((n) => n.text())
    expect(labels).toEqual(['Entrance', 'Car Park'])

    // Paths reference node coordinates; the labelled one prints its label.
    const paths = wrapper.findAll('line.map-path')
    expect(paths).toHaveLength(2)
    const pathLabels = wrapper.findAll('text.map-path-label').map((n) => n.text())
    expect(pathLabels).toEqual(['Main Path'])
    wrapper.unmount()
  })

  it('renders blank slots as numbered circles in slot order', () => {
    const wrapper = mount(MapScene, { props: { scene } })
    const slots = slotNodes(wrapper)
    expect(slots).toHaveLength(2)
    expect(slots[0].attributes('data-slot')).toBe('1')
    expect(slots[0].text()).toBe('1')
    expect(slots[1].attributes('data-slot')).toBe('2')
    expect(slots[1].text()).toBe('2')
    wrapper.unmount()
  })

  it('emits select with the slot number when a blank slot is clicked', async () => {
    const wrapper = mount(MapScene, { props: { scene } })
    await slotNodes(wrapper)[1].trigger('click')
    expect(wrapper.emitted('select')).toEqual([[2]])
    wrapper.unmount()
  })

  it('shows the chosen letter on answered slots instead of the number', () => {
    const wrapper = mount(MapScene, {
      props: { scene, answers: { 1: 'B' } },
    })
    const slots = slotNodes(wrapper)
    expect(slots[0].text()).toBe('B')
    expect(slots[0].classes()).toContain('answered')
    expect(slots[1].text()).toBe('2')
    expect(slots[1].classes()).not.toContain('answered')
    wrapper.unmount()
  })
})
