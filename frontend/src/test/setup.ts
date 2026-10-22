import { afterEach, beforeEach, vi } from 'vitest'
import { setLocale } from '../i18n'

beforeEach(() => {
  // jsdom reports navigator.languages = ['en-US'], but zh is the product
  // default. Existing tests assert Chinese strings, so pin the locale.
  localStorage.clear()
  setLocale('zh')
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  localStorage.clear()
})
