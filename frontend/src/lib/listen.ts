/**
 * Per-question listening window (spec: 试卷播放不要太精准，前后留几秒).
 * A paper item's evidence interval is widened by these margins before
 * seeking, so the user hears the sentence lead-in and tail instead of
 * landing mid-word on the exact answer.
 */
export const LISTEN_LEAD_S = 6
export const LISTEN_TAIL_S = 6

export interface ListenWindow {
  start: number
  end: number | null
}

/**
 * Widen [tStart, tEnd] by the lead/tail margins and clamp to the audio:
 * - start never goes below 0;
 * - end is null when the interval is unknown or degenerate (tEnd missing
 *   or <= tStart) — the caller then plays without an auto-stop bound;
 * - end is clamped to `duration` so the auto-stop watcher ALWAYS fires
 *   (an end past the audio would never be reached by playtime updates).
 * A non-finite or negative duration is treated as 0, keeping the result
 * a plain number instead of leaking NaN into the progress highlight.
 */
export function listenWindow(
  tStart: number,
  tEnd: number | null | undefined,
  duration: number,
): ListenWindow {
  const start = Math.max(0, tStart - LISTEN_LEAD_S)
  const ceiling = Number.isFinite(duration) && duration > 0 ? duration : 0
  const end =
    tEnd != null && tEnd > tStart ? Math.min(tEnd + LISTEN_TAIL_S, ceiling) : null
  return { start, end }
}
