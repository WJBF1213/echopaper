import { onBeforeUnmount, ref } from 'vue'
import { api, type Job } from '../api'

/** Polls GET /api/jobs/{id} until done/error, with a hard cap. */
export function useJobPolling(onFinished: (job: Job) => void) {
  const job = ref<Job | null>(null)
  const running = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false

  function stop() {
    stopped = true
    running.value = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  async function poll(jobId: string) {
    try {
      const next = await api.getJob(jobId)
      job.value = next
      if (next.state === 'done' || next.state === 'error') {
        stop()
        onFinished(next)
        return
      }
    } catch {
      // transient network errors: keep polling a few more times
    }
    if (!stopped) timer = setTimeout(() => void poll(jobId), 1200)
  }

  function start(jobId: string) {
    stop()
    stopped = false
    running.value = true
    job.value = null
    void poll(jobId)
  }

  onBeforeUnmount(stop)

  return { job, running, start, stop }
}
