<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { toast } from './router'
import { useTheme } from './theme'
import { LOCALE_LABELS, SUPPORTED_LOCALES, locale, setLocale, t, type Locale } from './i18n'
import Icon from './components/Icon.vue'

const route = useRoute()
const { theme, toggle } = useTheme()

const nav = computed(() => [
  { to: '/', label: t('app.nav.library'), name: 'library' },
  { to: '/review', label: t('app.nav.review'), name: 'review' },
  { to: '/settings', label: t('app.nav.settings'), name: 'settings' },
])

const routeName = computed(() => String(route.name || 'library'))
const isActive = (name: string) => routeName.value === name

function onLocaleChange(event: Event) {
  setLocale((event.target as HTMLSelectElement).value as Locale)
}
</script>

<template>
  <div class="shell">
    <header class="masthead">
      <div class="masthead-inner">
        <RouterLink to="/" class="brand">
          <Icon name="headphones" :size="17" />
          <span>{{ t('app.brand') }}</span>
        </RouterLink>

        <nav class="links" :aria-label="t('app.nav.label')">
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

        <select
          class="locale-select"
          :value="locale"
          :aria-label="t('settings.language')"
          :title="t('settings.language')"
          @change="onLocaleChange"
        >
          <option v-for="code in SUPPORTED_LOCALES" :key="code" :value="code">
            {{ LOCALE_LABELS[code] }}
          </option>
        </select>

        <button
          class="theme-toggle"
          type="button"
          :aria-label="theme === 'dark' ? t('app.theme.toLight') : t('app.theme.toDark')"
          :title="theme === 'dark' ? t('app.theme.light') : t('app.theme.dark')"
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

.locale-select {
  padding: 4px 6px;
  border: 1px solid transparent;
  border-radius: 3px;
  background: transparent;
  color: var(--ink-3);
  font-size: 12px;
}

.locale-select:hover,
.locale-select:focus {
  border-color: var(--rule);
  background: var(--paper-2);
  color: var(--ink);
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
