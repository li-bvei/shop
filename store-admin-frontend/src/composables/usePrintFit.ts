import type { Ref } from 'vue'

const PX_PER_MM = 96 / 25.4

// Shaves a couple of percent off the printable area before fitting content
// into it. Browser px-to-print-unit rounding and printer-driver margins can
// each nibble a pixel or two off the edge; without this slack, content
// computed to exactly fill the page can still spill one line onto a blank
// second page.
const PRINT_SAFETY_MARGIN = 0.98

export interface PrintFitOptions {
  /** Page width in mm. Default: A4 portrait (210mm). */
  pageWidthMm?: number
  /** Page height in mm. Default: A4 portrait (297mm). */
  pageHeightMm?: number
  /** Must match the `@page { margin }` used in the component's print CSS. */
  marginMm?: number
  /**
   * Floor on the shrink factor, clamped to [0, 1]. `1` means never shrink at
   * all — content prints at its natural size and may legitimately overflow
   * onto further (non-blank) pages, e.g. a full month's staff schedule,
   * which is long enough that forcing it onto one page would make it
   * illegible. `0` means shrink as much as needed to guarantee a single
   * page, e.g. the daily report, which is meant to always be exactly one
   * page. Required, not defaulted — a call site that doesn't decide this
   * explicitly is exactly how this stopped shrinking at all: `minScale`
   * defaulting to `1` silently forces `scale` to always be `1`, since
   * `Math.max(1, anything <= 1)` is always `1`, no matter how tall the
   * content actually is.
   */
  minScale: number
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

function clampMinScale(minScale: number): number {
  return Math.min(1, Math.max(0, minScale))
}

/**
 * Pure scale-selection logic — exported on its own so it has direct unit
 * tests (see tests/printScale.test.ts) independent of DOM/print plumbing.
 * Never enlarges (content that already fits prints at its natural size) and
 * never shrinks past `minScale` (see PrintFitOptions.minScale).
 */
export function calculatePrintScale(
  naturalWidth: number,
  naturalHeight: number,
  availableWidth: number,
  availableHeight: number,
  minScale: number,
): number {
  const floor = clampMinScale(minScale)
  const heightScale = naturalHeight > 0 ? availableHeight / naturalHeight : 1
  const widthScale = naturalWidth > 0 ? availableWidth / naturalWidth : 1
  return Math.max(floor, Math.min(1, heightScale, widthScale))
}

/**
 * Forces printable content onto a single page (unless `minScale` opts out)
 * by measuring its natural rendered size and shrinking it (via CSS `zoom`,
 * never enlarging) to fit the page's printable area. `zoom` is
 * Chromium-only (no Firefox/Safari support), which is acceptable here since
 * printing already goes through the browser's native print/"save as PDF"
 * dialog and this project has always targeted Chrome/Edge for that flow.
 */
export function usePrintFit(rootRef: Ref<HTMLElement | null | undefined>, options: PrintFitOptions) {
  const pageWidthMm = options.pageWidthMm ?? 210
  const pageHeightMm = options.pageHeightMm ?? 297
  const marginMm = options.marginMm ?? 10
  const minScale = clampMinScale(options.minScale)

  function waitForPrint(): Promise<void> {
    return new Promise((resolve, reject) => {
      const onAfterPrint = () => {
        window.removeEventListener('afterprint', onAfterPrint)
        resolve()
      }
      window.addEventListener('afterprint', onAfterPrint)
      try {
        window.print()
        // Chrome blocks inside this call until the print dialog closes, but
        // `afterprint` can only actually dispatch once this synchronous
        // call stack unwinds back to the event loop — resolving is left
        // entirely to that listener, never assumed just because print()
        // has returned (that assumption — resetting the zoom immediately
        // after this call — was what let the zoom get torn down, and the
        // temporary print node get deleted by the caller's `finally`,
        // before the browser had actually finished paginating).
      } catch (err) {
        window.removeEventListener('afterprint', onAfterPrint)
        reject(err instanceof Error ? err : new Error(String(err)))
      }
    })
  }

  async function fitAndPrint(): Promise<void> {
    const el = rootRef.value
    if (!el) {
      await waitForPrint()
      return
    }

    el.style.zoom = '1'
    // Reading scrollHeight/scrollWidth forces a synchronous layout flush,
    // so this reflects the real post-reset size, not a stale value.
    const naturalHeight = el.scrollHeight
    const naturalWidth = el.scrollWidth

    const availableHeightPx = (pageHeightMm - marginMm * 2) * PX_PER_MM * PRINT_SAFETY_MARGIN
    const availableWidthPx = (pageWidthMm - marginMm * 2) * PX_PER_MM * PRINT_SAFETY_MARGIN

    let scale = calculatePrintScale(naturalWidth, naturalHeight, availableWidthPx, availableHeightPx, minScale)
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

    // Re-measure for real after the zoom (and any resulting reflow/redraw)
    // has actually settled, instead of trusting the arithmetic above — this
    // catches content that doesn't shrink exactly proportionally (a
    // fixed-width element, a canvas that redrew at a slightly different
    // size) and still overflows the page even at the "correct" scale.
    //
    // Must read getBoundingClientRect(), not scrollWidth/scrollHeight: zoom
    // is self-referential — an element's own scrollWidth/scrollHeight (and
    // offsetWidth/offsetHeight) stay at its unzoomed size no matter what
    // zoom is applied to that same element, since they measure content in
    // the element's own local coordinate space. getBoundingClientRect()
    // reports size in the parent's space, which is exactly where zoom's
    // scaling actually shows up. Using scrollWidth/scrollHeight here read
    // back the unzoomed size every time, so this "correction" fired on
    // every print regardless of whether the zoomed content actually still
    // overflowed, over-shrinking it well past the already-correct scale.
    const settledRect = el.getBoundingClientRect()
    if (settledRect.width > availableWidthPx || settledRect.height > availableHeightPx) {
      const correction = Math.min(
        settledRect.width > availableWidthPx ? availableWidthPx / settledRect.width : 1,
        settledRect.height > availableHeightPx ? availableHeightPx / settledRect.height : 1,
      )
      scale = Math.max(minScale, scale * correction)
      el.style.zoom = String(scale)
      await nextFrame()
      await nextFrame()
    }

    try {
      await waitForPrint()
    } finally {
      el.style.zoom = ''
    }
  }

  return { fitAndPrint }
}
