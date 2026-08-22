import type { Ref } from 'vue'

const PX_PER_MM = 96 / 25.4

export interface PrintFitOptions {
  /** Page width in mm. Default: A4 portrait (210mm). */
  pageWidthMm?: number
  /** Page height in mm. Default: A4 portrait (297mm). */
  pageHeightMm?: number
  /** Must match the `@page { margin }` used in the component's print CSS. */
  marginMm?: number
  /**
   * Floor on the shrink factor (0-1). Content that would need to shrink
   * below this to fit one page instead prints at this size and legitimately
   * overflows onto further pages — e.g. a full month's staff schedule is
   * long enough that forcing it onto one page would make it illegible.
   * Overflow here is real content continuing, not a blank page, so it
   * doesn't conflict with "never a blank page". Default 1 (always exactly
   * one page) — pass lower only for content expected to be genuinely long.
   */
  minScale?: number
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

/**
 * Forces printable content onto a single page by measuring its natural
 * rendered size and shrinking it (via CSS `zoom`, never enlarging) to fit
 * the page's printable area — the one guarantee against blank trailing
 * pages or oversized content regardless of whatever layout quirk would
 * otherwise push it past the page bounds. `zoom` is Chromium-only (no
 * Firefox/Safari support), which is acceptable here since printing already
 * goes through the browser's native print/"save as PDF" dialog and this
 * project has always targeted Chrome/Edge for that flow.
 */
export function usePrintFit(rootRef: Ref<HTMLElement | null | undefined>, options: PrintFitOptions = {}) {
  const pageWidthMm = options.pageWidthMm ?? 210
  const pageHeightMm = options.pageHeightMm ?? 297
  const marginMm = options.marginMm ?? 10
  const minScale = options.minScale ?? 1

  async function fitAndPrint() {
    const el = rootRef.value
    if (!el) {
      window.print()
      return
    }

    el.style.zoom = '1'
    // Reading scrollHeight/scrollWidth forces a synchronous layout flush,
    // so this reflects the real post-reset size, not a stale value.
    const naturalHeight = el.scrollHeight
    const naturalWidth = el.scrollWidth

    const availableHeightPx = (pageHeightMm - marginMm * 2) * PX_PER_MM
    const availableWidthPx = (pageWidthMm - marginMm * 2) * PX_PER_MM
    const heightScale = naturalHeight > 0 ? availableHeightPx / naturalHeight : 1
    const widthScale = naturalWidth > 0 ? availableWidthPx / naturalWidth : 1
    // Never enlarge — content that already fits prints at its natural size.
    // Never shrink past minScale either — see the option's doc comment.
    const scale = Math.max(minScale, Math.min(1, heightScale, widthScale))

    el.style.zoom = String(scale)

    // CSS `zoom` genuinely changes each element's layout box (unlike
    // `transform: scale`), so ResizeObserver-driven content — ECharts'
    // `autoresize`, most notably — redraws its canvas to match. But that
    // redraw runs on its own observer callback, not synchronously with the
    // style change above, so printing on the very next line would rasterize
    // stale (pre-zoom) canvases. Two animation frames give the observer
    // callback and the resulting re-render time to land first.
    await nextFrame()
    await nextFrame()

    const reset = () => {
      el.style.zoom = ''
      window.removeEventListener('afterprint', reset)
    }
    window.addEventListener('afterprint', reset)
    window.print()
    // Chrome blocks here until the print dialog closes, so this covers the
    // common case; the afterprint listener is the safety net for browsers
    // where window.print() doesn't block.
    reset()
  }

  return { fitAndPrint }
}
