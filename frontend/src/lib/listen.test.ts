import { describe, expect, it } from 'vitest'
import { LISTEN_LEAD_S, LISTEN_TAIL_S, listenWindow } from '../lib/listen'

describe('listen window helpers', () => {
  it('exports the ±6s margins', () => {
    expect(LISTEN_LEAD_S).toBe(6)
    expect(LISTEN_TAIL_S).toBe(6)
  })

  it('widens a mid-audio interval by both margins', () => {
    expect(listenWindow(30, 40, 100)).toEqual({ start: 24, end: 46 })
  })

  it('clamps the start to 0 when tStart is within the lead margin', () => {
    expect(listenWindow(3, 10, 100)).toEqual({ start: 0, end: 16 })
    expect(listenWindow(6, 12, 100)).toEqual({ start: 0, end: 18 })
  })

  it('clamps the end to the audio duration when the tail overruns', () => {
    expect(listenWindow(90, 98, 100)).toEqual({ start: 84, end: 100 })
  })

  it('returns a null end for a null or undefined tEnd', () => {
    expect(listenWindow(30, null, 100)).toEqual({ start: 24, end: null })
    expect(listenWindow(30, undefined, 100)).toEqual({ start: 24, end: null })
  })

  it('returns a null end when tEnd does not exceed tStart', () => {
    expect(listenWindow(30, 30, 100)).toEqual({ start: 24, end: null })
    expect(listenWindow(30, 25, 100)).toEqual({ start: 24, end: null })
  })

  it('returns a null end when duration is not a positive number', () => {
    // metadata not loaded yet: no auto-stop bound (end: null) so
    // playback continues like the pre-window behavior instead of the
    // watcher pausing right after the seek.
    expect(listenWindow(30, 40, Number.NaN)).toEqual({ start: 24, end: null })
    expect(listenWindow(30, 40, -5)).toEqual({ start: 24, end: null })
  })
})
