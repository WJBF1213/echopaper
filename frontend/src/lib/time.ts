/** Pure helpers shared by the practice UI and tests. */
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

export interface DictationBlank {
  wordIndex: number
  sentenceIndex: number
  answer: string
}

/**
 * Virtual dictation blanks (not persisted in the blanks table, spec §5):
 * every word except the first and last of each sentence, so the sentence
 * remains locatable while the middle is dictated.
 */
export function buildDictationBlanks(
  words: { w: string }[],
  sentences: [number, number][],
): DictationBlank[] {
  const out: DictationBlank[] = []
  const add = (si: number, start: number, end: number) => {
    if (end - start + 1 < 3) return
    for (let i = start + 1; i <= end - 1; i++) {
      const word = words[i]
      if (!word || !/[A-Za-z0-9]/.test(word.w)) continue
      out.push({ wordIndex: i, sentenceIndex: si, answer: word.w })
    }
  }
  if (sentences.length) {
    sentences.forEach(([start, end], si) => add(si, start, end))
  } else if (words.length) {
    add(0, 0, words.length - 1)
  }
  return out
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

export function modeLabel(mode: string): string {
  const key = `mode.${mode}`
  const label = translate(key)
  return label === key ? mode : label
}

export function transcriptSourceLabel(source: string): string {
  const key = `source.${source}`
  const label = translate(key)
  return label === key ? source : label
}
