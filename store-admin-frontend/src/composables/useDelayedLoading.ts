import { ref } from 'vue'

/**
 * Avoids the v-loading mask "flash" on fast requests: the loading flag only
 * flips true if the wrapped async function is still running after `delayMs`.
 */
export function useDelayedLoading(delayMs = 150) {
  const loading = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  async function run<T>(fn: () => Promise<T>): Promise<T> {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      loading.value = true
    }, delayMs)
    try {
      return await fn()
    } finally {
      if (timer) clearTimeout(timer)
      timer = null
      loading.value = false
    }
  }

  return { loading, run }
}
