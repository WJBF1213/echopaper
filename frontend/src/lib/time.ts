/** Pure helpers shared by the listening UI and tests. */
import { locale, translate } from '../i18n'

export function fmtTime(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec < 0) return '0:00'
  const total = Math.floor(sec)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** Clicking a blank starts audio 1.5s before the word (spec §9). */
export function blankSeekTime(tStart: number): number {
  return Math.max(0, tStart - 1.5)
}

export interface SentenceRange {
  start: number
  end: number
}

/** Word range of the sentence containing `wordIndex`. */
export function sentenceRangeFor(
  sentences: [number, number][],
  wordIndex: number,
): SentenceRange | null {
  for (const [start, end] of sentences) {
    if (wordIndex >= start && wordIndex <= end) return { start, end }
  }
  return null
}

export function sentenceText(words: { w: string }[], range: SentenceRange): string {
  return words
    .slice(range.start, range.end + 1)
    .map((w) => w.w)
    .join(' ')
    .trim()
}

/** True when the word list carries real ASR timings (not pseudo 0/0 words). */
export function hasWordTiming(words: { s: number; e: number }[]): boolean {
  return words.some(
    (w) =>
      Number.isFinite(w.s) &&
      Number.isFinite(w.e) &&
      (w.s !== 0 || w.e !== 0),
  )
}

/**
 * Word index audible at `t`, or -1 in a pause / before the first word.
 * Binary search keeps this cheap enough for timeupdate on long transcripts.
 */
export function activeWordIndex(
  words: { s: number; e: number }[],
  t: number,
): number {
  if (!words.length || !Number.isFinite(t) || t < 0) return -1
  let lo = 0
  let hi = words.length - 1
  let found = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (words[mid].s <= t) {
      found = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  if (found === -1) return -1
  const word = words[found]
  if (Number.isFinite(word.e) && t > word.e + 0.35) return -1
  return found
}

/** Timed range for AB-looping the sentence that owns a blank. */
export function sentenceTimeRange(
  words: { s: number; e: number }[],
  range: SentenceRange,
): { a: number; b: number } | null {
  const first = words[range.start]
  const last = words[range.end]
  if (!first || !last) return null
  const a = first.s
  const b = last.e
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) return null
  return { a, b: b + 0.25 }
}

export function pct(ok: number, total: number): number {
  if (!total) return 0
  return Math.round((ok / total) * 100)
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en-GB', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function transcriptSourceLabel(source: string): string {
  const key = `source.${source}`
  const label = translate(key)
  return label === key ? source : label
}
