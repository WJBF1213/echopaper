import { describe, expect, it, vi } from 'vitest'
import {
  activeWordIndex,
  blankSeekTime,
  buildDictationBlanks,
  fmtTime,
  hasWordTiming,
  pct,
  sentenceRangeFor,
  sentenceTimeRange,
  sentenceText,
} from '../lib/time'

describe('time helpers', () => {
  it('formats seconds as m:ss', () => {
    expect(fmtTime(0)).toBe('0:00')
    expect(fmtTime(61)).toBe('1:01')
    expect(fmtTime(null)).toBe('0:00')
  })

  it('seeks 1.5s before the blank word', () => {
    expect(blankSeekTime(10)).toBe(8.5)
    expect(blankSeekTime(1)).toBe(0)
  })

  it('finds the owning sentence of a word index', () => {
    const sentences: [number, number][] = [
      [0, 5],
      [6, 12],
    ]
    expect(sentenceRangeFor(sentences, 0)).toEqual({ start: 0, end: 5 })
    expect(sentenceRangeFor(sentences, 7)).toEqual({ start: 6, end: 12 })
    expect(sentenceRangeFor(sentences, 99)).toBeNull()
  })

  it('builds sentence text and AB range from words', () => {
    const words = [
      { w: 'hello', s: 1, e: 1.5 },
      { w: 'there', s: 1.6, e: 2 },
      { w: 'friend', s: 2.1, e: 2.6 },
    ]
    const range = { start: 0, end: 2 }
    expect(sentenceText(words, range)).toBe('hello there friend')
    expect(sentenceTimeRange(words, range)).toEqual({ a: 1, b: 2.85 })
  })

  it('ignores zero-length audio ranges', () => {
    const words = [{ w: 'a', s: 0, e: 0 }]
    expect(sentenceTimeRange(words, { start: 0, end: 0 })).toBeNull()
  })

  it('computes percentages safely', () => {
    expect(pct(3, 4)).toBe(75)
    expect(pct(1, 0)).toBe(0)
  })
})

describe('word timing helpers', () => {
  const words = [
    { w: 'one', s: 0, e: 0.5 },
    { w: 'two', s: 0.6, e: 1.0 },
    { w: 'three', s: 1.1, e: 1.5 },
  ]

  it('detects word-level timings', () => {
    expect(hasWordTiming(words)).toBe(true)
    expect(hasWordTiming([{ s: 0, e: 0 }])).toBe(false)
    expect(hasWordTiming([])).toBe(false)
  })

  it('finds the active word including small inter-word gaps', () => {
    expect(activeWordIndex(words, 0.55)).toBe(0)
    expect(activeWordIndex(words, 0.7)).toBe(1)
    expect(activeWordIndex(words, 1.2)).toBe(2)
  })

  it('returns -1 before the first word and in long pauses', () => {
    expect(activeWordIndex(words, -1)).toBe(-1)
    expect(activeWordIndex([{ s: 2, e: 2.5 }], 0.5)).toBe(-1)
    expect(activeWordIndex(words, 3)).toBe(-1)
  })
})

describe('dictation blanks', () => {
  const words = 'one two three four five six seven'.split(' ').map((w, i) => ({ w, s: i, e: i + 1 }))

  it('keeps sentence anchors and blanks the middle', () => {
    const blanks = buildDictationBlanks(words, [[0, 3]])
    expect(blanks.map((b) => b.wordIndex)).toEqual([1, 2])
  })

  it('skips sentences too short to blank', () => {
    expect(buildDictationBlanks(words, [[0, 1]])).toEqual([])
  })

  it('falls back to one range when sentences are missing', () => {
    const blanks = buildDictationBlanks(words.slice(0, 5), [])
    expect(blanks.map((b) => b.wordIndex)).toEqual([1, 2, 3])
  })
})
