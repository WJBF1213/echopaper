<script setup lang="ts">
import type { MaterialListItem } from '../api'
import { fmtDateTime } from '../lib/time'
import Icon from './Icon.vue'

defineProps<{ material: MaterialListItem }>()
const emit = defineEmits<{ open: []; remove: [] }>()
</script>

<template>
  <article class="mat" tabindex="0" @click="emit('open')" @keydown.enter="emit('open')">
    <div class="mat-body">
      <div class="name">{{ material.name }}</div>
      <div class="meta">
        <span>{{ material.sets_count }} 套题</span>
        <span class="dot" aria-hidden="true">·</span>
        <span>{{ material.has_audio ? '含音频' : '语音朗读' }}</span>
        <template v-if="material.duration_s">
          <span class="dot" aria-hidden="true">·</span>
          <span>{{ Math.round(material.duration_s / 60) }} 分钟</span>
        </template>
        <template v-if="material.best_score != null">
          <span class="dot" aria-hidden="true">·</span>
          <span class="score">最好 {{ Math.round(material.best_score * 100) }}%</span>
        </template>
        <template v-if="material.last_practice">
          <span class="dot" aria-hidden="true">·</span>
          <span>{{ fmtDateTime(material.last_practice) }}</span>
        </template>
      </div>
    </div>

    <div class="mat-side">
      <button
        class="icon-btn"
        type="button"
        title="删除材料"
        aria-label="删除材料"
        @click.stop="emit('remove')"
      >
        <Icon name="trash" :size="15" />
      </button>
      <Icon class="chevron" name="chevronRight" :size="16" />
    </div>
  </article>
</template>

<style scoped>
.mat {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--rule);
  border-radius: 3px;
  background: var(--paper);
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.mat:hover {
  border-color: var(--rule-strong);
  background: var(--paper-2);
}

.mat:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 1px;
}

.mat-body {
  min-width: 0;
  flex: 1;
}

.name {
  font-size: 14px;
  font-weight: 500;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 3px;
  color: var(--ink-3);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.score {
  color: var(--ok);
}

.dot {
  color: var(--rule-strong);
}

.mat-side {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.icon-btn {
  padding: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--ink-3);
}

.icon-btn:hover:not(:disabled) {
  border-color: var(--rule);
  background: var(--paper);
  color: var(--accent);
  opacity: 1;
}

.chevron {
  color: var(--rule-strong);
}
</style>
