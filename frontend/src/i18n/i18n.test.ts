import { describe, expect, it, beforeEach, vi } from 'vitest'
import {
  DEFAULT_LOCALE,
  LOCALE_LABELS,
  SUPPORTED_LOCALES,
  catalogs,
  detectLocale,
  locale,
  setLocale,
  translate,
} from './index'

describe('i18n catalogs', () => {
  it('ships every declared locale with labels', () => {
    for (const code of SUPPORTED_LOCALES) {
      expect(catalogs[code], `missing catalog ${code}`).toBeTruthy()
      expect(LOCALE_LABELS[code]).toBeTruthy()
    }
  })

  it('has one identical key set across locales', () => {
    const reference = Object.keys(catalogs[DEFAULT_LOCALE]).sort()
    for (const code of SUPPORTED_LOCALES) {
      expect(Object.keys(catalogs[code]).sort(), `key mismatch in ${code}`).toEqual(reference)
    }
  })

  it('has no empty or whitespace-only values', () => {
    for (const code of SUPPORTED_LOCALES) {
      for (const [key, value] of Object.entries(catalogs[code])) {
        expect(value.trim(), `${code}:${key} is empty`).not.toBe('')
      }
    }
  })

  it('keeps interpolation placeholders consistent across locales', () => {
    const placeholders = (text: string) => (text.match(/\{(\w+)\}/g) ?? []).sort()
    for (const [key, zhValue] of Object.entries(catalogs.zh)) {
      expect(placeholders(catalogs.en[key]), `placeholder mismatch in ${key}`).toEqual(
        placeholders(zhValue),
      )
    }
  })
})

describe('translate', () => {
  beforeEach(() => {
    setLocale('zh')
  })

  it('interpolates named parameters', () => {
    expect(translate('common.words', { n: 42 }, 'zh')).toBe('42 词')
    expect(translate('common.words', { n: 42 }, 'en')).toBe('42 words')
  })

  it('leaves unknown placeholders untouched', () => {
    expect(translate('common.words', {}, 'zh')).toBe('{n} 词')
  })

  it('falls back to the key for unknown entries', () => {
    expect(translate('does.not.exist')).toBe('does.not.exist')
  })
})

describe('locale detection', () => {
  it('picks the first supported browser language', () => {
    expect(detectLocale(['fr-FR', 'en-US', 'zh-CN'])).toBe('en')
    expect(detectLocale(['zh-TW'])).toBe('zh')
  })

  it('falls back to the default locale', () => {
    expect(detectLocale(['de-DE', 'ja-JP'])).toBe(DEFAULT_LOCALE)
    expect(detectLocale([])).toBe(DEFAULT_LOCALE)
  })
})

describe('switching', () => {
  it('updates the reactive locale ref', () => {
    setLocale('en')
    expect(locale.value).toBe('en')
    setLocale('zh')
    expect(locale.value).toBe('zh')
    expect(vi.isMockFunction(locale.value as never)).toBe(false)
  })
})
