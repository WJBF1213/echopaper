<script setup lang="ts">
/**
 * Deterministic scene -> SVG renderer (design §4.3).
 *
 * The backend ships a validated scene JSON (normalized 0-100 canvas,
 * rect/circle nodes, paths with optional labels, continuous 1..N blank
 * slots); this component draws it with plain SVG -- zero external
 * dependencies, wireframe aesthetics. Fixed nodes print their label,
 * blank slots render as numbered circles; an answered slot (answers:
 * slot -> letter) prints the chosen letter instead. Clicking a slot
 * emits `select(slot)` so the parent can route the answer to the item
 * asking about that slot (the letter buttons live on the item row,
 * matching-consistent interaction).
 */
import { computed } from 'vue'
import type { MapSceneData, MapSceneNode } from '../api'

const props = defineProps<{
  scene: MapSceneData
  /** blank_slot -> chosen letter, for answer display. */
  answers?: Record<number, string>
}>()

const emit = defineEmits<{ (e: 'select', slot: number): void }>()

/** Normalized-unit geometry (canvas is 0-100, min node distance is 8). */
const RECT_W = 22
const RECT_H = 11
const CIRCLE_R = 7
const SLOT_R = 4.2

const canvas = computed(() => props.scene.canvas ?? { width: 100, height: 70 })
const viewBox = computed(() => `0 0 ${canvas.value.width} ${canvas.value.height}`)

const fixedNodes = computed(() => (props.scene.nodes ?? []).filter((n) => n.fixed))
const slotNodes = computed(() =>
  (props.scene.nodes ?? []).filter((n) => !n.fixed && n.blank_slot != null),
)
const byId = computed<Record<string, MapSceneNode>>(() => {
  const map: Record<string, MapSceneNode> = {}
  for (const node of props.scene.nodes ?? []) map[node.id] = node
  return map
})

/** Paths whose endpoints both resolve (the validator guarantees this). */
const edges = computed(() =>
  (props.scene.paths ?? [])
    .map((path) => {
      const from = byId.value[path.from]
      const to = byId.value[path.to]
      if (!from || !to) return null
      return {
        x1: from.x,
        y1: from.y,
        x2: to.x,
        y2: to.y,
        label: path.label,
        lx: (from.x + to.x) / 2,
        ly: (from.y + to.y) / 2 - 2,
      }
    })
    .filter((edge): edge is NonNullable<typeof edge> => edge !== null),
)

function answerOf(slot: number | undefined): string {
  if (slot == null) return ''
  return props.answers?.[slot] ?? ''
}

function slotMark(node: MapSceneNode): string {
  const letter = answerOf(node.blank_slot)
  return letter || String(node.blank_slot ?? '')
}

function isAnswered(node: MapSceneNode): boolean {
  return Boolean(answerOf(node.blank_slot))
}

function onSelect(node: MapSceneNode) {
  if (node.blank_slot != null) emit('select', node.blank_slot)
}
</script>

<template>
  <svg :viewBox="viewBox" class="map-scene" role="img" preserveAspectRatio="xMidYMid meet">
    <!-- paths first so nodes sit on top -->
    <g v-for="(edge, index) in edges" :key="`p${index}`" class="map-edge">
      <line
        class="map-path"
        :x1="edge.x1"
        :y1="edge.y1"
        :x2="edge.x2"
        :y2="edge.y2"
      />
      <text
        v-if="edge.label"
        class="map-path-label"
        :x="edge.lx"
        :y="edge.ly"
        text-anchor="middle"
      >
        {{ edge.label }}
      </text>
    </g>

    <!-- fixed nodes: printed labels -->
    <g v-for="node in fixedNodes" :key="node.id" class="map-node" :class="node.shape">
      <rect
        v-if="node.shape === 'rect'"
        :x="node.x - RECT_W / 2"
        :y="node.y - RECT_H / 2"
        :width="RECT_W"
        :height="RECT_H"
        rx="1"
      />
      <circle v-else :cx="node.x" :cy="node.y" :r="CIRCLE_R" />
      <text class="map-node-label" :x="node.x" :y="node.y" text-anchor="middle">
        {{ node.label }}
      </text>
    </g>

    <!-- blank slots: numbered circles, clickable -->
    <g
      v-for="node in slotNodes"
      :key="node.id"
      class="map-slot"
      :class="{ answered: isAnswered(node) }"
      :data-slot="node.blank_slot"
      role="button"
      tabindex="0"
      @click="onSelect(node)"
      @keydown.enter.prevent="onSelect(node)"
    >
      <circle :cx="node.x" :cy="node.y" :r="SLOT_R" />
      <text class="map-slot-mark" :x="node.x" :y="node.y" text-anchor="middle">
        {{ slotMark(node) }}
      </text>
    </g>
  </svg>
</template>

<style scoped>
.map-scene {
  display: block;
  width: 100%;
  max-width: 560px;
  aspect-ratio: auto;
  height: auto;
  border: 1px solid var(--rule);
  border-radius: 4px;
  background: var(--paper);
}

.map-path {
  stroke: var(--ink-3);
  stroke-width: 0.7;
  stroke-dasharray: 2.5 1.5;
}

.map-path-label {
  fill: var(--ink-3);
  font-size: 3.4px;
}

.map-node rect,
.map-node circle {
  fill: var(--paper-2);
  stroke: var(--ink-2);
  stroke-width: 0.8;
}

.map-node-label {
  fill: var(--ink);
  font-size: 4px;
  font-weight: 600;
  dominant-baseline: central;
}

.map-slot circle {
  fill: var(--paper);
  stroke: var(--ink);
  stroke-width: 0.9;
}

.map-slot {
  cursor: pointer;
}

.map-slot:hover circle,
.map-slot:focus-visible circle {
  stroke: var(--accent);
  stroke-width: 1.4;
}

.map-slot-mark {
  fill: var(--ink);
  font-size: 4.4px;
  font-weight: 700;
  dominant-baseline: central;
  font-variant-numeric: tabular-nums;
}

.map-slot.answered circle {
  fill: var(--accent-soft);
  stroke: var(--accent);
}

.map-slot.answered .map-slot-mark {
  fill: var(--accent);
}
</style>
