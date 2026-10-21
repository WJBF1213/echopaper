<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { toast } from './router'
import { useTheme } from './theme'
import Icon from './components/Icon.vue'

const route = useRoute()
const { theme, toggle } = useTheme()

const nav = [
  { to: '/', label: '材料库', name: 'library' },
  { to: '/review', label: '回顾', name: 'review' },
  { to: '/settings', label: '设置', name: 'settings' },
]

const routeName = computed(() => String(route.name || 'library'))
const isActive = (name: string) => routeName.value === name
</script>

<template>
  <div class="shell">
    <header class="masthead">
      <div class="masthead-inner">
        <RouterLink to="/" class="brand">
          <Icon name="headphones" :size="17" />
          <span>雅思听力挖空</span>
        </RouterLink>

        <nav class="links" aria-label="主导航">
          <RouterLink
            v-for="item in nav"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            :class="{ active: isActive(item.name) }"
          >
            {{ item.label }}
          </RouterLink>
        </nav>

        <button
          class="theme-toggle"
          type="button"
          :aria-label="theme === 'dark' ? '切换到亮色模式' : '切换到暗色模式'"
          :title="theme === 'dark' ? '亮色模式' : '暗色模式'"
          @click="toggle"
        >
          <Icon :name="theme === 'dark' ? 'sun' : 'moon'" :size="15" />
        </button>
      </div>
    </header>

    <main class="wrap">
      <RouterView />
    </main>

    <Transition name="toast">
      <div v-if="toast" class="toast" :class="toast.kind" role="status" aria-live="polite">
        {{ toast.text }}
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100vh;
}

.masthead {
  position: sticky;
  top: 0;
  z-index: 40;
  background: var(--paper);
  border-bottom: 1px solid var(--rule);
}

.masthead-inner {
  display: flex;
  align-items: center;
  gap: 24px;
  max-width: 940px;
  margin: 0 auto;
  padding: 0 20px;
  height: 52px;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--ink);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.01em;
  text-decoration: none;
}

.brand:hover {
  text-decoration: none;
  opacity: 0.8;
}

.links {
  display: flex;
  gap: 2px;
  margin-left: auto;
}

.nav-link {
  position: relative;
  padding: 16px 12px 15px;
  color: var(--ink-3);
  font-size: 13px;
  text-decoration: none;
  border-bottom: 2px solid transparent;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.nav-link:hover {
  color: var(--ink);
  text-decoration: none;
}

.nav-link.active {
  color: var(--ink);
  border-bottom-color: var(--accent);
  font-weight: 500;
}

.theme-toggle {
  padding: 6px;
  border: 1px solid transparent;
  border-radius: 3px;
  background: transparent;
  color: var(--ink-3);
}

.theme-toggle:hover:not(:disabled) {
  border-color: var(--rule);
  background: var(--paper-2);
  color: var(--ink);
  opacity: 1;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
