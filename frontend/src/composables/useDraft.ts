import { reactive, watch } from 'vue'

/** Per-set answer draft persisted to localStorage (spec §9/F3). */
export function useDraft(setId: string) {
  const key = `ielts_cloze_draft_${setId}`
  const answers = reactive<Record<string, string>>({})

  try {
    const raw = localStorage.getItem(key)
    if (raw) Object.assign(answers, JSON.parse(raw) as Record<string, string>)
  } catch {
    /* corrupt draft: start empty */
  }

  let timer: ReturnType<typeof setTimeout> | null = null
  watch(
    answers,
    () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        try {
          localStorage.setItem(key, JSON.stringify(answers))
        } catch {
          /* storage full */
        }
      }, 400)
    },
    { deep: true },
  )

  function clear() {
    for (const k of Object.keys(answers)) delete answers[k]
    try {
      localStorage.removeItem(key)
    } catch {
      /* ignore */
    }
  }

  return { answers, clear }
}
