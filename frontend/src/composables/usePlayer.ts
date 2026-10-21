import { onBeforeUnmount, ref, watch, type Ref } from 'vue'

/**
 * Audio transport with AB looping. Methods are no-ops when the material has
 * no audio (the caller renders the TTS fallback instead).
 */
export function usePlayer(audio: Ref<HTMLAudioElement | null>) {
  const playing = ref(false)
  const current = ref(0)
  const duration = ref(0)
  const rate = ref(Number(localStorage.getItem('ielts_cloze_rate')) || 1)
  const abA = ref<number | null>(null)
  const abB = ref<number | null>(null)

  const element = () => audio.value

  function clamp(t: number) {
    const d = duration.value
    if (!Number.isFinite(d) || d <= 0) return Math.max(0, t)
    return Math.max(0, Math.min(d - 0.05, t))
  }

  function seek(t: number, autoplay = false) {
    const el = element()
    if (!el) return
    el.currentTime = clamp(t)
    current.value = el.currentTime
    if (autoplay) void play()
  }

  function play() {
    const el = element()
    if (!el) return
    const result = el.play() as Promise<void> | undefined
    if (result && typeof result.catch === 'function') {
      result.catch(() => {
        playing.value = false
      })
    }
  }

  function pause() {
    element()?.pause()
  }

  function toggle() {
    if (playing.value) pause()
    else play()
  }

  function nudge(delta: number) {
    seek(current.value + delta)
  }

  function setRate(value: number) {
    rate.value = value
    const el = element()
    if (el) el.playbackRate = value
    try {
      localStorage.setItem('ielts_cloze_rate', String(value))
    } catch {
      /* ignore */
    }
  }

  function setAb(a: number, b: number, autoplay = true) {
    const lo = Math.min(a, b)
    const hi = Math.max(a, b)
    if (hi - lo < 0.5) return
    abA.value = lo
    abB.value = hi
    seek(lo, autoplay)
  }

  function clearAb() {
    abA.value = null
    abB.value = null
  }

  /** Classic three-state AB button: set A -> set B -> clear. */
  function cycleAb() {
    if (abA.value == null) {
      abA.value = current.value
    } else if (abB.value == null) {
      setAb(abA.value, current.value, true)
    } else {
      clearAb()
    }
  }

  function onTimeUpdate() {
    const el = element()
    if (!el) return
    current.value = el.currentTime
    if (abB.value != null && el.currentTime >= abB.value) {
      el.currentTime = abA.value ?? 0
      current.value = el.currentTime
      if (el.paused) void el.play().catch(() => undefined)
    }
  }

  function onLoaded() {
    const el = element()
    if (!el) return
    duration.value = Number.isFinite(el.duration) ? el.duration : 0
    el.playbackRate = rate.value
  }

  const onPlay = () => (playing.value = true)
  const onPause = () => (playing.value = false)
  const onEnded = () => (playing.value = false)

  function bind(el: HTMLAudioElement) {
    el.addEventListener('timeupdate', onTimeUpdate)
    el.addEventListener('loadedmetadata', onLoaded)
    el.addEventListener('durationchange', onLoaded)
    el.addEventListener('play', onPlay)
    el.addEventListener('pause', onPause)
    el.addEventListener('ended', onEnded)
  }

  function unbind(el: HTMLAudioElement) {
    el.removeEventListener('timeupdate', onTimeUpdate)
    el.removeEventListener('loadedmetadata', onLoaded)
    el.removeEventListener('durationchange', onLoaded)
    el.removeEventListener('play', onPlay)
    el.removeEventListener('pause', onPause)
    el.removeEventListener('ended', onEnded)
  }

  // The <audio> element lives behind a v-if, so bind whenever it appears.
  watch(
    audio,
    (el, old) => {
      if (old && old !== el) unbind(old)
      if (el) {
        bind(el)
        el.playbackRate = rate.value
        duration.value = Number.isFinite(el.duration) ? el.duration : 0
      }
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    const el = element()
    if (el) {
      unbind(el)
      el.pause()
    }
  })

  return {
    playing,
    current,
    duration,
    rate,
    abA,
    abB,
    seek,
    play,
    pause,
    toggle,
    nudge,
    setRate,
    setAb,
    clearAb,
    cycleAb,
  }
}
