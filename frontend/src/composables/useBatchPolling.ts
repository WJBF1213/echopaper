import { onBeforeUnmount, ref } from 'vue'
import { api, type BatchStatus } from '../api'

/**
 * Polls GET /api/batches/{id} until every file is done/error.
 * `watched` tells the callback whether this session actually saw progress
 * (false when reopening an already-finished batch from history).
 */
export function useBatchPolling(
  onFinished: (batch: BatchStatus, watched: boolean) => void,
) {
  const batch = ref<BatchStatus | null>(null)
  const running = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false
  let watched = false

  function stop() {
    stopped = true
    running.value = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  async function poll(batchId: string) {
    try {
      const next = await api.getBatch(batchId)
      batch.value = next
      if (next.running > 0) watched = true
      if (next.done + next.error >= next.total) {
        stop()
        onFinished(next, watched)
        return
      }
    } catch {
      // transient network errors: keep polling
    }
    if (!stopped) timer = setTimeout(() => void poll(batchId), 1500)
  }

  function start(batchId: string) {
    stop()
    stopped = false
    running.value = true
    batch.value = null
    watched = false
    void poll(batchId)
  }

  onBeforeUnmount(stop)

  return { batch, running, start, stop }
}
