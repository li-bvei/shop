import { onBeforeUnmount, onMounted, ref } from 'vue'

/** The one place that decides "is this the phone layout" — 768px is the
 * same breakpoint AppShell/AppSidebar/AppTopbar already switch on, so a
 * mobile-only component and the shell chrome around it always flip together. */
export const MOBILE_MAX_WIDTH_PX = 768
const QUERY = `(max-width: ${MOBILE_MAX_WIDTH_PX}px)`

export function useIsMobile() {
  const query = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(QUERY) : null
  const isMobile = ref(query?.matches ?? false)
  const update = () => { isMobile.value = query?.matches ?? false }
  onMounted(() => { update(); query?.addEventListener('change', update) })
  onBeforeUnmount(() => query?.removeEventListener('change', update))
  return isMobile
}
