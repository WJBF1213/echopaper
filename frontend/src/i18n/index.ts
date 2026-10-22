/**
 * Tiny i18n layer — no dependency, typed keys, reactive locale.
 *
 * Why hand-rolled: the UI has ~200 strings and zero need for plurals/date
 * formats beyond what Intl already does. Adding vue-i18n would pull a
 * runtime and a message-syntax dialect for no gain.
 *
 * Adding a language
 * -----------------
 * 1. Copy `zh` in `./locales/` to `<code>.ts` and translate every value.
 * 2. Add the import to `catalogs` below and the code to `SUPPORTED_LOCALES`.
 * 3. `npm test` — `i18n.test.ts` asserts every catalog has the same key set
 *    and no empty values, so a forgotten string fails CI instead of shipping.
 *
 * Interpolation: `t('common.words', { n: 3 })` with `{n}` in the
 * message. Missing keys fall back to the default locale, then to the key.
 */
import { computed, ref, watch } from 'vue'
import zh from './locales/zh'
import en from './locales/en'

export const SUPPORTED_LOCALES = ['zh', 'en'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

export type Messages = Record<string, string>
export type MessageParams = Record<string, string | number>

export const catalogs: Record<Locale, Messages> = { zh, en }

export const DEFAULT_LOCALE: Locale = 'zh'
const STORAGE_KEY = 'ielts-cloze.locale'

export const LOCALE_LABELS: Record<Locale, string> = {
  zh: '中文',
  en: 'English',
}

function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value)
}

/** Pick the first supported language from the browser's preference list. */
export function detectLocale(
  languages: readonly string[] = typeof navigator === 'undefined' ? [] : navigator.languages,
): Locale {
  for (const language of languages) {
    const primary = language.toLowerCase().split('-')[0]
    if (isLocale(primary)) return primary
  }
  return DEFAULT_LOCALE
}

function storedLocale(): Locale | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return isLocale(value) ? value : null
  } catch {
    return null
  }
}

export const locale = ref<Locale>(storedLocale() ?? detectLocale())

watch(locale, (value) => {
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // private mode / storage disabled: keep the in-memory choice
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = value === 'zh' ? 'zh-CN' : value
  }
})

export function setLocale(value: Locale): void {
  locale.value = value
}

export function initLocale(): void {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = locale.value === 'zh' ? 'zh-CN' : locale.value
  }
}

export function translate(
  key: string,
  params?: MessageParams,
  target: Locale = locale.value,
): string {
  const template = catalogs[target]?.[key] ?? catalogs[DEFAULT_LOCALE][key] ?? key
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  )
}

/** Reactive translate: use inside templates/computeds so a switch re-renders. */
export function t(key: string, params?: MessageParams): string {
  // Track the locale ref so Vue registers the dependency.
  void locale.value
  return translate(key, params)
}

/**
 * Count-aware translate: uses `<key>.one` when `n === 1`.
 *
 * Chinese does not inflect for number, so zh can omit `.one` and falls back
 * to the base key; inflecting languages provide it. Catalogs must keep an
 * identical key set, so zh declares the same `.one` keys with identical text.
 */
export function tn(key: string, n: number, params?: MessageParams): string {
  void locale.value
  const paramsIn = params ?? {}
  if (n === 1) {
    const one = translate(`${key}.one`, paramsIn)
    if (one !== `${key}.one`) return one
  }
  return translate(key, paramsIn)
}

/** Non-reactive translator for module-level constants (labels computed once). */
export function te(key: string, params?: MessageParams): string {
  return translate(key, params)
}

/** Same, but re-evaluates when the locale changes (for option lists). */
export function useT() {
  return computed(() => (key: string, params?: MessageParams) => {
    void locale.value
    return translate(key, params)
  })
}
