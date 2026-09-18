import jsPDF from 'jspdf'
import html2canvas from 'html2canvas'

const A4_WIDTH_MM = 210
const A4_HEIGHT_MM = 297
const MARGIN_MM = 10

/**
 * Renders an offscreen DOM element to a single-page A4 PDF, scaling the
 * whole rendered image down (never up) to guarantee it fits on one page —
 * same "shrink to fit" principle as usePrintFit's zoom-to-fit printing,
 * just targeting a PDF blob instead of window.print(). Because the source
 * element is a purpose-built offscreen node (not the live app shell), the
 * old print bug — hidden siblings retaining their layout height and
 * leaving blank pages — can't happen here: there are no hidden siblings.
 */
export async function downloadElementAsPdf(element: HTMLElement, filename: string) {
  // scale 1.5 is plenty for a text/lines table (this isn't a photo) — PNG
  // at scale 2 was producing multi-megabyte files for a single page of
  // text, since a screenshot-of-text compresses far worse than the same
  // content would as native vector text. JPEG trades imperceptible edge
  // softness on the (already-small) table text for a much smaller file.
  const canvas = await html2canvas(element, { scale: 1.5, backgroundColor: '#ffffff' })

  const usableWidthMm = A4_WIDTH_MM - MARGIN_MM * 2
  const usableHeightMm = A4_HEIGHT_MM - MARGIN_MM * 2

  const canvasAspectRatio = canvas.height / canvas.width
  let renderWidthMm = usableWidthMm
  let renderHeightMm = renderWidthMm * canvasAspectRatio
  if (renderHeightMm > usableHeightMm) {
    renderHeightMm = usableHeightMm
    renderWidthMm = renderHeightMm / canvasAspectRatio
  }

  const xOffset = MARGIN_MM + (usableWidthMm - renderWidthMm) / 2
  const yOffset = MARGIN_MM

  const pdf = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' })
  const imgData = canvas.toDataURL('image/jpeg', 0.92)
  pdf.addImage(imgData, 'JPEG', xOffset, yOffset, renderWidthMm, renderHeightMm)
  pdf.save(filename.endsWith('.pdf') ? filename : `${filename}.pdf`)
}

/**
 * Builds a node positioned off-screen (not display:none — html2canvas
 * can't measure/rasterize an element with no layout box), runs `build`
 * to fill it in, captures it, then always tears it down again.
 */
export async function renderOffscreenToPdf(filename: string, widthPx: number, build: (root: HTMLDivElement) => void) {
  const root = document.createElement('div')
  root.style.position = 'fixed'
  root.style.top = '0'
  root.style.left = '-99999px'
  root.style.width = `${widthPx}px`
  root.style.background = '#ffffff'
  document.body.appendChild(root)
  try {
    build(root)
    await downloadElementAsPdf(root, filename)
  } finally {
    document.body.removeChild(root)
  }
}

// This app's Element Plus theme wires several --el-color-primary-* variables
// through color-mix() (see element-overrides.css) — real browser rendering
// resolves those fine, but html2canvas 1.4.x's own CSS parser doesn't
// understand color-mix() syntax at all, which makes it error/hang on every
// node under an element that references one. Only matters for a *live* DOM
// capture (offscreen nodes built by hand, like the table above, only ever
// use literal colors and never hit this).
const COLOR_MIX_CSS_VARS = [
  '--el-color-primary-light-3',
  '--el-color-primary-light-5',
  '--el-color-primary-light-7',
  '--el-color-primary-light-8',
  '--el-color-primary-dark-2',
]

/**
 * Captures a real, already-rendered element (as opposed to an offscreen
 * node built purely from literal inline styles) as a single-page PDF.
 * Temporarily pins each color-mix()-based theme variable to its actual
 * resolved color (read from the browser's own rendering via a throwaway
 * probe element, so it stays correct across themes) as an inline override
 * on `element`, so html2canvas never sees the unsupported syntax.
 */
export async function downloadLiveElementAsPdf(element: HTMLElement, filename: string) {
  const probe = document.createElement('div')
  probe.style.position = 'fixed'
  probe.style.visibility = 'hidden'
  document.body.appendChild(probe)
  const previousValues: [string, string][] = []
  try {
    for (const name of COLOR_MIX_CSS_VARS) {
      previousValues.push([name, element.style.getPropertyValue(name)])
      probe.style.color = `var(${name})`
      element.style.setProperty(name, getComputedStyle(probe).color)
    }
    await downloadElementAsPdf(element, filename)
  } finally {
    for (const [name, previous] of previousValues) {
      if (previous) element.style.setProperty(name, previous)
      else element.style.removeProperty(name)
    }
    document.body.removeChild(probe)
  }
}
