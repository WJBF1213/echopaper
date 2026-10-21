import { ref } from 'vue'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'ielts_cloze_theme'

function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'dark' || stored === 'light') return stored
  } catch {
    /* localStorage unavailable */
  }
  try {
    if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'dark'
  } catch {
    /* matchMedia unavailable */
  }
  return 'light'
}

const theme = ref<Theme>(initialTheme())

export function applyTheme(value: Theme) {
  theme.value = value
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = value
  }
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    /* ignore */
  }
}

export function useTheme() {
  const toggle = () => applyTheme(theme.value === 'dark' ? 'light' : 'dark')
  return { theme, toggle }
}

/** Called once from main.ts before mount. */
export function initTheme() {
  applyTheme(theme.value)
}
