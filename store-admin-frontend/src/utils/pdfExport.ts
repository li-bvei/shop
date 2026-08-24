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
